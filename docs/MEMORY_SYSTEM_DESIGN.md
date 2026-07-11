# 记忆系统设计文档

## 目录

1. [架构总览](#1-架构总览)
2. [Journal：Write-Ahead Log](#2-journalwrite-ahead-log)
3. [Write Decision：三层门控](#3-write-decision三层门控)
4. [Memory Router：分流存储](#4-memory-router分流存储)
5. [LongTerm：Fact vs Summary](#5-longtermfact-vs-summary)
6. [Experience：多标签设计](#6-experience多标签设计)
7. [Knowledge：独立知识服务](#7-knowledge独立知识服务)
8. [Event Bus：模块解耦](#8-event-bus模块解耦)
9. [Retriever：统一检索](#9-retriever统一检索)
10. [统一评分公式](#10-统一评分公式)
11. [Maintenance Worker](#11-maintenance-worker)
12. [存储表设计](#12-存储表设计)

---

## 1. 架构总览

### 1.1 架构图

```
                         User
                          │
                          ▼
                  Context Pipeline
                          │
                 Journal（事件日志 / WAL）
                          │
              ┌───────────┼───────────┐
              │           │           │
              ▼           │           ▼
       Write Decision     │    Knowledge Event
       "值不值得存？"      │    "可不可提取？"
       (仅 Memory)        │    (独立判断)
              │           │           │
          pass│           │      ┌────┴────┐
              ▼           │      ▼         ▼
        Memory Router     │  Channel A  Channel B
        "存在哪里？"      │  (规则同步) (LLM 异步)
              │           │      │         │
        ┌─────┴─────┐     │      └────┬────┘
        ▼           ▼     │           ▼
    LongTerm    Experience │    Knowledge Queue
                           │           │
                           │           ▼
                           │    Knowledge Worker
                           │           │
                           │           ▼
                           │    KnowledgeGraph

─────────────────────────────────────────

    Retriever（统一检索）
           │
           ▼
    Search → Merge → Rank
           │
           ▼
    Context Builder
           │
           ▼
    LLM

─────────────────────────────────────────

    Maintenance Worker
           │
    ┌──────┼──────┬─────────┬──────────┐
    │      │      │         │          │
    ▼      ▼      ▼         ▼          ▼
  Merge  Forget Decay    Archive   Summarize
```

### 1.2 记忆层精简：10 层 → 5 层 + Knowledge（独立）

| # | 层 | 回答的问题 | 存储 | 写入触发 |
|---|-----|----------|------|---------|
| ① | **Working** | "我现在在干什么？" | 纯内存 Ring Buffer | 每轮自动 push，预算外 FIFO 淘汰 |
| ② | **Session** | "这次对话发生了什么？" | `memories` (type="session") | 每轮自动写入，TTL 24h 清除 |
| ③ | **LongTerm** | "我对用户/项目了解什么？" | `memories` (type="long_term") | Write Decision pass → Memory Router 分发 |
| ④ | **Experience** | "我以前做过什么？学到了什么？" | `experiences` (tags 多标签) | Write Decision pass → Memory Router 分发 |
| ⊕ | **Knowledge** | "概念之间怎么关联？" | `concepts` + `concept_relations` + `knowledge_documents` | 独立 Knowledge Extractor，不入 Write Decision |

**新增基础设施层（不存记忆，支撑写入和检索流程）：**

| 基础设施 | 职责 |
|---------|------|
| **Journal** | Write-Ahead Log，每轮自动写入，所有持久化写入的原材料 |
| **Retriever** | 统一检索引擎，Search → Merge → Rank，从 Builder 中分离 |
| **Maintenance Worker** | 后台维护：Merge / Forget / Decay / Archive / Summarize |

### 1.3 核心设计原则

- **Write Decision 回答"值不值得存"**，只适用于 Memory（LongTerm + Experience）
- **Memory Router 回答"存在哪里"**，不做价值判断，不拒收
- **Knowledge 不入 Write Decision**——判断"重要"和判断"可提取"是两个独立问题
- **Knowledge 不属于 Memory**——不同的生命周期、存储表、检索方式，由独立的 `KnowledgeUpdater` 维护
- **Journal 作为统一的写前日志**，所有写入经 Journal → 异步分发，支持重放恢复和审计追溯

---

## 2. Journal：Write-Ahead Log

### 2.1 设计动机

当前 Session 层混合了两种职责：会话上下文 + 候选缓冲区（`status=pending`）。问题：

- Session TTL 过期 → pending 记录丢失
- Session 按时间排序 → 不利于按 entity 分组聚合
- Session 结构偏会话 → 不适合做预写日志

Journal 从 Session 中分离，专门承担 WAL 职责。**Journal 不是记忆，是事件日志**——它是所有持久化写入的"原材料"。

### 2.2 表结构

```sql
CREATE TABLE journal (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    round_id     INTEGER NOT NULL,
    raw_input    TEXT NOT NULL,
    raw_output   TEXT DEFAULT '',
    entities     TEXT DEFAULT '{}',       -- {"person": "Alice", "amount": 8000}
    task_intent  TEXT DEFAULT '',
    status       TEXT DEFAULT 'pending',   -- pending | processing | processed | discarded
    category     TEXT DEFAULT '',
    processed_at TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    metadata     TEXT DEFAULT '{}'
);

CREATE INDEX idx_journal_user_status ON journal(user_id, status);
CREATE INDEX idx_journal_session ON journal(session_id);
CREATE INDEX idx_journal_created ON journal(created_at);
```

### 2.3 写入与批量触发

每轮 Pipeline 调用自动写入 Journal（零门槛）。Journal 写入后通过 Event Bus 广播 `journal:created` 事件。

**Layer 1 命中（规则必存）**→ 立即触发 write_decision → Router → 持久化，不等待批量。

**Layer 1 未命中**→ 累积在 Journal，等待以下三种条件之一触发批量处理：

| 触发器 | 条件 | 说明 |
|-------|------|------|
| 窗口溢出 | pending ≥ 5 或轮次 ≥ 10 | 核心触发，保证批量窗口合理 |
| 会话关闭 | `Pipeline.close()` | 兜底触发，不丢任何待写数据 |
| 定时器 | 距上次处理 > 5 min | 保护机制，防长对话无自然关闭 |

### 2.4 批量处理流程

```
触发条件满足：
  │
  ├─ 1. 拉取：SELECT * FROM journal WHERE status='pending' ORDER BY round_id LIMIT 50
  │
  ├─ 2. 分组：按 entities 中的 person/entity 分组
  │     Alice: [收入8000(r3), 支出5999(r4), 收入300(r5)]
  │     Bob:   [交房租3000(r3), 报销200(r4)]
  │
  ├─ 3. 决策：批量执行 write_decision()（Layer 2 + 3）
  │     → 聚合：同实体多条生成 Summary
  │     → 原样：每条独立写入 Experience（多标签）
  │     → 丢弃：低价值标记 discarded
  │
  └─ 4. 标记：UPDATE journal SET status='processed', processed_at=NOW()
        不删除——保留完整 audit trail
```

### 2.5 三个核心价值

- **WAL 恢复**：Memory 崩了，Journal 可重放重建所有记忆
- **审计追溯**：每条 LTM 可追溯到 Journal 中的 `raw_input` 和 `round_id`
- **批量聚合**：同实体多条记录在窗口内合并为 Summary，避免碎片化写入

---

## 3. Write Decision：三层门控

### 3.1 适用范围

Write Decision 只适用于 Memory（LongTerm + Experience）。Knowledge 不入 Write Decision。

**反例**："Redis 使用单线程模型"——Importance 只有 0.2（不是偏好，不是任务结论，不是状态变更），但它是一段确定性的结构化知识。如果 Knowledge 经过 Write Decision，这条知识就被丢弃了。

```
Write Decision 回答的问题:
  → 这段信息未来会不会被再次用到？
  → 判断的是"重要性"

Knowledge Extractor 回答的问题:
  → 这段信息是否包含可提取的结构化知识？
  → 判断的是"可提取性"

两者完全独立。
```

### 3.2 三层门控

| 层 | 名称 | 判断条件 | 命中行为 |
|----|------|---------|---------|
| **Layer 1** | 规则必存 | 关键词"记住/记录/设置为" + KV 模式"X 是 Y" + 任务结论数字 | 立即通过（score=1.0），跳过 Layer 2/3，立即分发 |
| **Layer 2** | 新颖度过滤 | embedding 余弦相似度 vs 现有 LTM → sim > 0.9 触发实体值对比 | 重复 → 丢弃；更新 → 通过；其他 → 通过 |
| **Layer 3** | 重要性评分 | 5 维加权：identity(0.30) + state(0.20) + task(0.20) + cold_start(0.15) + quality(0.15) | overall ≥ 0.50 → pass |

### 3.3 Layer 1：规则必存

| 触发条件 | 检测方式 | 示例 |
|---------|---------|------|
| 显式记忆指令 | 关键词：`记住`、`记录`、`设置为`、`保存`、`remember` | "记住我喜欢深色模式" |
| KV 键值对模式 | 正则：`主语+是/住/在/喜欢+宾语` | "我住在北京" → {location: 北京} |
| 任务关键结论 | LLM 回复中的数字结构化结论 | "余额为 7101 元" |

### 3.4 Layer 2：新颖度过滤

```
输入文本 → embedding → 与现有 LTM 最近的 N 条做 cosine_similarity
  │
  ├─ max_similarity > 0.9 → 高相似，进入实体值对比
  │    ├─ 实体相同但值不同 → 更新，通过
  │    ├─ 实体相同且值相同 → 重复，丢弃
  │    └─ 无法提取实体 → 视为重复，丢弃
  │
  ├─ max_similarity < 0.3 → 高新颖，通过（cold_start 维度给予 bonus）
  │
  └─ 0.3 ≤ sim ≤ 0.9 → 正常，通过
```

实体值对比仅在 similarity > 0.9 时触发，复用 Layer 1 的 KV 模式匹配，无需新增 LLM 调用。

### 3.5 Layer 3：重要性评分

| 维度 | 权重 | 判断方法 | 说明 |
|------|------|---------|------|
| identity | 0.30 | "我是/我住在/我偏好"等模式 | 用户身份/偏好 |
| state | 0.20 | intent 为 agent/coding 且含数字/金额 | 状态/配置变更 |
| task | 0.20 | Evaluator 的 task_importance | 任务本身重要性 |
| cold_start | 0.15 | 当前 LTM 总条数 < 50 → 加权 | 系统早期冷启动保护 |
| quality | 0.15 | Evaluator 的 reward_score | LLM 输出质量 |

**阈值**：`overall ≥ 0.50` → 通过，进入 Memory Router。

`cold_start` 维度随 LTM 条目增长自动衰减，> 50 条后衰减至 0。

---

## 4. Memory Router：分流存储

### 4.1 职责边界

Memory Router 的前提：**收到的都是已通过 Write Decision 的条目**。Router 不做价值判断，只负责按信息性质分发到合适的 Memory 层。

### 4.2 分流规则

```
Memory Router:
  │
  ├─ 检测到 experience 信号？
  │   （失败/错误/超时 | 原因分析/教训 | 步骤/流程 | 工具调用）
  │   → ExperienceDB（多标签 tags 数组）
  │
  └─ 兜底 → LongTerm
      ├─ 能提取 entity_key？ → Fact（版本化存储）
      └─ 无法提取 entity_key？ → Summary（语义去重，不可覆盖）
```

### 4.3 LongTerm 分流细节

```
→ LongTerm:
  │
  ├─ 能提取 entity_key？
  │   例如: "我是张三" → entity_key="user.name"
  │   例如: "余额 5000 元" → entity_key="account.balance"
  │   → Fact
  │     ├─ entity_key 已存在 → 更新 (version+1, history.push 旧值)
  │     └─ entity_key 不存在 → 新建 (version=1)
  │
  └─ 无法提取 entity_key？
      例如: "讨论了 Q3 预算分配方案"
      例如: "Retro 结论：测试覆盖率是瓶颈"
      → Summary
        ├─ embedding sim > 0.9 → 触发内容对比
        │    ├─ 实质内容相同 → 跳过（真正重复）
        │    └─ 有新增信息 → 合并，旧条目 decay 加速
        └─ sim < 0.9 → 新增
```

> **注意**：sim>0.9 不能简单跳过。例如"项目 Alpha 完成数据迁移"和"项目 Alpha 新增：完成 UI 改版"语义相似度极高但包含新信息，必须做内容对比。

### 4.4 Experience 信号检测

```
Experience Extractor（Router 内部，自动检测）:
  - 检测到失败/错误/超时/重试      → 打 "episode" 标签
  - 检测到原因分析/根因/教训/结论   → 打 "reflection" 标签
  - 检测到步骤/规范/流程/SOP        → 打 "procedure" 标签
  - 检测到工具调用/API 调用         → 打 "tool_usage" 标签
  - 检测到技术栈关键词              → 打对应标签（如 "sql", "k8s"）
```

同一经历可同时拥有多个标签。

---

## 5. LongTerm：Fact vs Summary

### 5.1 问题：LongTerm 太像 KV Store

当前 LongTerm 把所有内容都按 `entity_key → value → version 链覆盖` 处理。但 Project Summary、Meeting Summary 这类内容没有 entity_key，不应覆盖，不应 diff。

### 5.2 两类设计

```
LongTerm

  ├─ Fact（结构化事实）
  │   ✅ 有 entity_key
  │   ✅ 可对比 diff
  │   ✅ 支持 version 链覆盖
  │   例：user.location=北京, Alice.余额=5000
  │
  └─ Summary（非结构化摘要）
      ❌ 无 entity_key
      ❌ 不可 diff
      ❌ 不可覆盖
      例：Project Summary, Meeting Summary, Conversation Summary
```

| 维度 | Fact | Summary |
|------|------|---------|
| **entity_key** | ✅ 有 | ❌ 无 |
| **写入策略** | 同键覆盖，旧值入 history | embedding 去重 + 内容对比 |
| **版本管理** | version 链（version+1, history.push） | 无版本概念 |
| **检索** | entity_key 精确查 + 语义查 | 纯语义检索 |
| **去重** | entity_key 匹配 | embedding sim > 0.9 → 内容对比 |
| **Decay 速率** | 半衰期 7 天 | 半衰期 3 天（更快衰减） |

### 5.3 Fact version history 截断

频繁变更的 Fact（如"余额"每天更新）会导致 `metadata.history` 数组无限增长。Maintenance Worker 的 Merge 任务需对 history 做截断：

```
history 保留策略（触发：数组长度 > 10）:
  ├─ 保留最早的 1 条（记录初始值）
  ├─ 保留最近的 5 条（记录最近变更轨迹）
  └─ 其余删除
```

---

## 6. Experience：多标签设计

### 6.1 问题：真实经历极少是单一类型

"今天 SQL 执行失败，后来发现索引没建，以后要先 explain"——这条经历同时包含 episode（发生了什么）、reflection（为什么失败）、procedure（以后怎么做）。单标签 `experience_type` 强制选一个主类型，丢失了其他维度的价值。

### 6.2 多标签方案

每条经历存储为 `tags: JSON 数组`，而非单一 `experience_type`：

```json
{
    "id": "uuid",
    "tags": ["episode", "reflection", "procedure", "sql"],
    "scene": "数据库查询执行",
    "action": "执行 SQL 查询",
    "result": "执行失败，耗时超时",
    "root_cause": "索引未建立，导致全表扫描",
    "lesson": "新表上线前必须建立索引",
    "preventive_action": "编写 SQL 前先执行 EXPLAIN 检查执行计划",
    "steps": ["EXPLAIN 分析", "确认索引状态", "CREATE INDEX 如缺失"],
    "tool_name": null,
    "created_at": "2026-07-11T10:30:00"
}
```

### 6.3 检索方式

| 查询 | SQL 方式 | 结果 |
|------|---------|------|
| 所有反思经历 | `json_each(tags)` 匹配 `"reflection"` | 所有失败分析 + 教训 |
| SQL 相关的失败 | `tags LIKE '%"episode"%' AND tags LIKE '%"sql"%'` | 精确命中 |
| 所有规范操作 | `json_each(tags)` 匹配 `"procedure"` | 所有预防措施 |

### 6.4 表结构

```sql
CREATE TABLE experiences (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    tags              TEXT DEFAULT '[]',      -- JSON 数组，多标签
    scene             TEXT DEFAULT '',
    action            TEXT DEFAULT '',
    result            TEXT DEFAULT '',
    root_cause        TEXT DEFAULT '',
    lesson            TEXT DEFAULT '',
    preventive_action TEXT DEFAULT '',
    steps             TEXT DEFAULT '[]',      -- JSON 数组
    tool_name         TEXT DEFAULT '',
    error_type        TEXT DEFAULT '',
    duration_ms       INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT '',
    metadata          TEXT DEFAULT '{}'
);

CREATE INDEX idx_experiences_user ON experiences(user_id);
CREATE INDEX idx_experiences_tags ON experiences(user_id, tags);
CREATE INDEX idx_experiences_created ON experiences(created_at DESC);
```

---

## 7. Knowledge：独立知识服务

### 7.1 Knowledge 不是 Memory

这是整个架构中最关键的边界。两者是完全不同的系统：

```
Memory（记忆）                          Knowledge（知识）
───────────────────────────          ──────────────────────────────
回答: "用户是谁？做过什么？"          回答: "概念之间怎么关联？"
内容: 偏好、状态、经历、任务           内容: 三元组、属性、文档块、概念层级
存储: memories 表                    存储: concepts + concept_relations + knowledge_documents
写入: Write Decision 把关             写入: Knowledge Extractor 独立判断（不入 Write Decision）
检索: 按语义 + 时间 + 访问频率         检索: BFS 图遍历 / 向量相似度
生命周期: TTL + Decay + Forget        生命周期: 只增不删（冲突时按 reliability 覆盖）
所属: MemoryUpdater                    所属: KnowledgeUpdater（独立维护）
```

### 7.2 独立 KnowledgeUpdater

```
MemoryUpdater                 KnowledgeUpdater
────────────                  ────────────────
├─ Write Decision             ├─ Knowledge Extractor
├─ Memory Router              │    ├─ Channel A: 规则同步
└─ 写 LongTerm/Experience     │    └─ Channel B: LLM 异步
                              ├─ Knowledge Queue
                              ├─ Knowledge Worker
                              └─ KnowledgeGraph

EventBus: Journal 写入 → broadcast → 两者独立订阅，零直接依赖
```

### 7.3 四种节点类型

| 节点 | 格式 | 示例 | 回答的问题 | 去重策略 |
|------|------|------|-----------|---------|
| **Triple** | `{subject, relation, object, confidence}` | `{Redis, 是, 缓存数据库, 1.0}` | "X 是什么？X 跟 Y 什么关系？" | (S,R,O) 三元组去重 |
| **Property** | `{entity, property_name, value, source_reliability}` | `{Redis, 作者, "Salvatore", 1.0}` | "X 的属性是什么？" | (entity, property_name) 去重，值冲突按 reliability 裁决 |
| **Document** | `{content, embedding, source, chunk_index}` | Redis 官方文档 → chunk → embedding → 存储 | 长文本语义检索 | embedding sim > 0.95 跳过 |
| **Taxonomy** | `{name, parent, level, description}` | `{Redis, parent=缓存数据库, level=3}` | "X 属于哪类？" | (name) 去重，更新 parent |

### 7.4 提取通道

```
通道 A: 规则抽取（确定性，0 成本，同步）
  适用模式:
    Triple:  "X 是 Y" / "X 属于 Y" / "X 基于 Y" / "X 包含 Y" / "X 用 Y"
    Property: KV 键值对（主语+是/住/在/喜欢+宾语）
    Taxonomy: "X 是一种 Y" / "X 继承自 Y"
  提取后: 直接写入 Knowledge，confidence=1.0

通道 B: LLM 抽取（异步，事件驱动）
  触发: Knowledge Queue 中 pending events ≥ 30
  效果: 批量 LLM 抽取 → 写入 Knowledge，confidence=0.7
  Debounce: 2 min 内新 event 重置计时
  兜底: 距上次处理 > 15 min 强制执行
```

### 7.5 Knowledge 与 Memory 的边界

Property Node（Knowledge）和 LongTerm Fact（Memory）都存储实体属性，判断标准：

```
if entity 是当前用户或对话参与者:
    → 入 LongTerm Fact (Memory)
if 内容可提取为结构化属性且 entity 不是用户:
    → 入 Knowledge (Property Node)
if 两者都满足（如 Alice.余额=5000）:
    → 两处都入（Memory 用于记忆检索，Knowledge 用于知识问答）
```

### 7.6 Source Reliability 解决 Knowledge 冲突

```
用户说："Redis 作者是我"       → reliability = 0.75 (User)
文档说："Redis 作者是 Salvatore" → reliability = 0.95 (Official Doc)

冲突裁决: 0.95 > 0.75 → 保留 Official Doc 版本
```

---

## 8. Event Bus：模块解耦

### 8.1 为什么需要 Event Bus

Journal 写入后需要触发 Write Decision（Memory 侧）和 Knowledge Extractor（Knowledge 侧）。如果由 MemoryUpdater 发布 Knowledge Event，两者仍然耦合。

Event Bus 是 in-process 的轻量 pub/sub，不做持久化（Journal 本身就是持久化日志），让各个模块只订阅自己关心的事件，互不知晓对方的存在。

### 8.2 事件流

```
Journal.append() 写入后
  │
  └─ EventBus.publish("journal:created", journal_entry)
       │
       ├─ MemoryWriteSubscriber    订阅 → 调 WriteDecision.decide()
       │    pass → MemoryRouter.route() → LongTerm / Experience
       │
       └─ KnowledgeExtractSubscriber 订阅 → 调 KnowledgeExtractor.extract()
            └─ Channel A: 规则直接写入 KnowledgeGraph
            └─ Channel B: 发布 ConceptPendingEvent → KnowledgeQueue
```

### 8.3 设计原则

- In-process，不做持久化（Journal 已是持久化事件日志）
- Publisher 不知道谁在订阅，Subscriber 不知道谁在发布
- 新增一个消费者→ 只需新增一个 Subscriber，不修改 Journal 或 Pipeline

---

## 9. Retriever：统一检索

### 9.1 问题：Builder 承担了太多

当前 Builder 直接调用各 Memory 层的检索接口，自己完成聚合排序——它实际上已经是一个检索引擎：

```
Builder 当前:
  ├─ LTM.retrieve()           } Search
  ├─ Session.query()          } Search
  ├─ Experience.recall()      } Search
  ├─ Knowledge.query_graph()  } Search
  ├─ 跨源合并去重              } Merge
  ├─ 统一排序打分              } Rank
  └─ 打包 UnifiedContext       } Build (唯一该做的)
```

### 9.2 分离后架构

```
Builder → Retriever.retrieve(query, sources, top_k)
          │
          ├─ 1. Search: 并发调各 SourceAdapter
          ├─ 2. Score:  统一公式打分
          ├─ 3. Merge:  跨源去重 × source_weight
          └─ 4. Rank:   排序截断

Builder → 拿到结果 → 补充 identity / environment → by token budget 截断
```

### 9.3 SourceAdapter：统一异构 API

各存储源的检索 API 完全不同（`LTM.retrieve()` vs `Experience.recall_relevant()` vs `Knowledge.query_graph()`）。每个 source 需要一个 Adapter 统一调用签名：

```python
class SourceAdapter(Protocol):
    source_name: str
    source_weight: float   # 跨源合并权重

    async def search(self, query: str, top_k: int, **kwargs) -> list[RetrievedItem]:
        ...

class LTMAdapter(SourceAdapter):
    source_name = "long_term"
    source_weight = 1.0
    async def search(self, query, top_k, **kwargs):
        return await self.ltm.retrieve(query, top_k)

class ExperienceAdapter(SourceAdapter):
    source_name = "experience"
    source_weight = 0.8
    async def search(self, query, top_k, **kwargs):
        return await self.exp.recall_relevant(query, top_k, tags=kwargs.get("tags"))

class KnowledgeAdapter(SourceAdapter):
    source_name = "knowledge"
    source_weight = 0.6
    async def search(self, query, top_k, **kwargs):
        concepts = self._extract_concepts(query)
        return await self.kg.query_graph(concepts, depth=2)

class SessionAdapter(SourceAdapter):
    source_name = "session"
    source_weight = 0.3
    async def search(self, query, top_k, **kwargs):
        return await self.session.query(query, top_k)

class JournalAdapter(SourceAdapter):
    source_name = "journal"
    source_weight = 0.4
    async def search(self, query, top_k, **kwargs):
        return await self.journal.query_pending(query, top_k)
```

新增一个存储源 → 新增一个 Adapter 并注册，不修改 Retriever 核心。

### 9.4 检索流程

```
Retriever.retrieve(query, top_k=25):
  │
  ├─ 1. 并发发起多路异步检索
  │     LTM     → 语义 + BM25 + source_reliability
  │     Session → 按 session_id + 时间排序
  │     Experience → 标签匹配 + 语义相似度
  │     Knowledge  → BFS 图遍历 (max_depth=2)
  │     Journal    → 查 pending 条目（时效性补偿）
  │
  ├─ 2. 打分 → 统一评分公式（见第 10 章）
  │
  ├─ 3. 合并去重
  │     跨源重复 (embedding sim > 0.95) → 保留 source_weight 最高的
  │     实体去重 (同 entity_key) → 保留最新版本
  │
  └─ 4. 排序截断 → 返回 top-k
```

---

## 10. 统一评分公式

### 10.1 问题

当前一条记忆被评分两次，两个公式时间衰减相差 69 倍（LTM 半衰期 69 天 vs Ranker 半衰期 1 天），排序结果不可预测。

### 10.2 方案：检索即排序

Retriever 是唯一做语义检索+评分的入口。Optimizer 不再对记忆重打分，只做结构性整理（去重、分组、token budget 截断）。

### 10.3 统一公式

```
unified_score = 0.30 × semantic_similarity
              + 0.20 × bm25_score
              + 0.15 × source_reliability
              + 0.10 × time_decay           ← 半衰期统一 7 天
              + 0.15 × relevance_boost
              + 0.10 × access_frequency
```

### 10.4 两个独立概念：source_reliability vs source_weight

| | source_reliability | source_weight |
|---|---|---|
| **含义** | 这条数据来源有多可靠？ | 这个存储源在检索中优先多少？ |
| **作用域** | 每条 MemoryItem 级别 | 存储源（LTM / Experience / Knowledge）级别 |
| **谁设置** | 写入端根据来源设置，存入 `metadata.source_reliability` | SourceAdapter 预设 |
| **在哪用** | 评分公式的维度之一（0.15 权重） | 跨源合并时作为乘数 |
| **会变吗** | 会——被纠正后降低，频繁访问且无误则提升（min=0.2, max=1.0） | 不会——架构级预设 |

**跨源合并公式**：

```
final_score = unified_score × source_weight
```

例：
- LTM 中 reliability=0.6: `unified_score=0.7` → `final = 0.7 × 1.0 = 0.70`
- Knowledge 中 reliability=0.95: `unified_score=0.8` → `final = 0.8 × 0.6 = 0.48`

高可信度知识排在低可信度 LTM 记忆之后——`source_weight` 保证已通过 Write Decision 的 LTM 优先于任意 Knowledge。

### 10.5 Source Reliability 分级

| 来源 | reliability | 说明 |
|------|------------|------|
| 用户显式陈述 | 1.00 | "我住在北京" |
| 通道 A 规则抽取 | 1.00 | 确定性 KV 匹配 |
| 官方/系统数据 | 0.95 | API 返回值 |
| 用户隐式推断 | 0.80 | 连续 3 次选择深色模式 → 推断偏好 |
| 通道 B LLM 抽取 | 0.70 | 异步批量 LLM 抽取 |
| LLM 推断结论 | 0.60 | 从对话推算"余额=7101" |
| Journal pending | 0.50 | 未经 Write Decision 的原始记录 |

### 10.6 Source Weight 分级

| 存储源 | weight | 说明 |
|-------|--------|------|
| long_term | 1.0 | 已通过 Write Decision，最高优先级 |
| experience | 0.8 | 经历记录，场景还原参考 |
| knowledge | 0.6 | 知识图谱，语义扩展 |
| journal | 0.4 | 未处理的原始记录，时效性补偿 |
| session | 0.3 | 会话上下文，通常直接引用 |

---

## 11. Maintenance Worker

### 11.1 五维生命周期

长期运行后记忆膨胀，需要完整的生命周期管理：

```
Maintenance Worker 定时调度:
  ├─ Merge     (每 1h)   合并相似/重复记忆
  ├─ Forget    (每 24h)  遗忘低价值/过期记忆
  ├─ Decay     (每 6h)   衰减长期未访问的权重
  ├─ Archive   (每 7d)   归档冷数据
  └─ Summarize (每 24h)  聚合多条为摘要
```

### 11.2 Merge

| 场景 | 策略 |
|------|------|
| 精确重复（相同 content） | 保留最早一条，合并 access_count（新=旧总和） |
| 语义重复（sim > 0.85） | 保留 content 较长的，长短接近（差 < 20%）→ 保留 access_count 更高的 |
| 实体重复（同 entity_key） | 多版本合并为 version 链，旧版本入 history |
| Experience 合并（同 tags + 相似场景） | 合并 lesson / steps，tags 取并集 |

### 11.3 Forget

| 条件 | 操作 |
|------|------|
| 显式遗忘指令 | metadata.deleted = True → 30 天后物理删除 |
| TTL 过期（Session） | 直接删除 |
| 低价值（> 90天 + access < 2 + relevance < 0.3） | 删除 |
| 用户纠正（"不对，不是北京"） | reliability → 0.2，标记已纠正 |

### 11.4 Decay

| 维度 | 策略 |
|------|------|
| 时间衰减 | `exp(-t / 7days)`，半衰期 7 天 |
| Summary 加速 | `exp(-t / 3days)`，半衰期 3 天 |
| 访问衰减 | > 30 天未访问 → relevance_score × 0.9 |
| 可靠度恢复 | access_count > 20 且 30 天内无纠正 → reliability + 0.05（cap 1.0） |

### 11.5 Archive

条件（三个同时满足）：> 180 天 + 最后访问 > 90 天 + relevance < 0.5

操作：`metadata.archived = True` → 正常检索不返回，仅 `include_archived=True` 时返回。

与 Forget 的区别：Archive 移出热检索（可恢复），Forget 物理删除（不可恢复）。

### 11.6 Summarize

| 场景 | 策略 |
|------|------|
| 对话摘要 | 同一 session > 10 条 Summary → 合并为一条聚合摘要 |
| 时间摘要 | 同一用户 7 天内 > 20 条 LTM → 合并为周摘要 |
| 实体摘要 | 同一 entity > 5 条 Fact → 聚合为时间线 |

### 11.7 Journal 清理

| 策略 | 条件 | 操作 |
|------|------|------|
| 时效清理 | processed 且 > 30 天 | 分批删除（每批 1000 条，避免锁表） |
| 容量清理 | 总行数 > 10000 | 删除最早的 5000 条 processed 记录 |
| 精确保留 | status = pending | 永久不删，优先触发批量处理 |

---

## 12. 存储表设计

### 12.1 表总览

| 表 | 承载 | 变化 |
|----|------|------|
| `memories` | Session + LongTerm，type 列区分 | 保留，扩展 metadata（含 category、version、history） |
| `concepts` | Knowledge 概念节点（Triple / Property / Taxonomy） | 保留 |
| `concept_relations` | Knowledge 关系边 | 保留 |
| `knowledge_documents` | Document Node（文档块 + embedding） | **新增** |
| `experiences` | 统一经验（多标签 tags 数组） | **新增**，合并旧 episode/reflection/procedure/tool_usage 表 |
| `journal` | Write-Ahead Log | **新增** |

### 12.2 `memories` 表

```sql
CREATE TABLE memories (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,               -- 'session' | 'long_term'
    content         TEXT NOT NULL,
    embedding       TEXT,                        -- JSON float 数组
    session_id      TEXT,
    user_id         TEXT DEFAULT 'anonymous',
    timestamp       TEXT DEFAULT (datetime('now')),
    access_count    INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    metadata        TEXT DEFAULT '{}',           -- JSON: {category, version, history, entity_key, source_reliability, archived, deleted}
    expires_at      TEXT
);
```

### 12.3 `concepts` + `concept_relations` 表

```sql
CREATE TABLE concepts (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    attributes  TEXT DEFAULT '{}',              -- JSON
    embedding   TEXT,
    node_type   TEXT DEFAULT 'triple',           -- 'triple' | 'property' | 'taxonomy'
    confidence  REAL DEFAULT 1.0,
    user_id     TEXT DEFAULT 'anonymous',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT
);

CREATE TABLE concept_relations (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES concepts(id),
    target_id     TEXT NOT NULL REFERENCES concepts(id),
    relation_type TEXT NOT NULL,
    weight        REAL DEFAULT 1.0,
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, relation_type)
);
```

### 12.4 `knowledge_documents` 表

```sql
CREATE TABLE knowledge_documents (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    embedding   TEXT,                            -- JSON float 数组
    source      TEXT,
    chunk_index INTEGER DEFAULT 0,
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now'))
);
```

### 12.5 `experiences` 表

```sql
CREATE TABLE experiences (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    tags              TEXT DEFAULT '[]',          -- JSON 数组，多标签
    scene             TEXT DEFAULT '',
    action            TEXT DEFAULT '',
    result            TEXT DEFAULT '',
    root_cause        TEXT DEFAULT '',
    lesson            TEXT DEFAULT '',
    preventive_action TEXT DEFAULT '',
    steps             TEXT DEFAULT '[]',
    tool_name         TEXT DEFAULT '',
    error_type        TEXT DEFAULT '',
    duration_ms       INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT,
    metadata          TEXT DEFAULT '{}'
);
```

### 12.6 `journal` 表

```sql
CREATE TABLE journal (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    round_id     INTEGER NOT NULL,
    raw_input    TEXT NOT NULL,
    raw_output   TEXT DEFAULT '',
    entities     TEXT DEFAULT '{}',
    task_intent  TEXT DEFAULT '',
    status       TEXT DEFAULT 'pending',          -- pending | processing | processed | discarded
    category     TEXT DEFAULT '',
    processed_at TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    metadata     TEXT DEFAULT '{}'
);

CREATE INDEX idx_journal_user_status ON journal(user_id, status);
CREATE INDEX idx_journal_session ON journal(session_id);
CREATE INDEX idx_journal_created ON journal(created_at);
```
