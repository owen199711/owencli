# Journal 驱动记忆架构

## 架构总览

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

---

## 1. Journal：Write-Ahead Log

### 1.1 为什么需要 Journal

当前 Session 混合了两种职责：会话上下文 + 候选缓冲区（status=pending）。问题：
- Session TTL 过期 → pending 记录丢失
- Session 按时间排序 → 无法按 entity 分组聚合
- Session 结构偏会话 → 不适合做预写日志

Journal 是独立的 WAL 层，在所有持久化写入之前先落地。**Journal 不是记忆，是事件日志**。

### 1.2 表结构

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
    status       TEXT DEFAULT 'pending',   -- pending | processed | discarded
    category     TEXT DEFAULT '',
    processed_at TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    metadata     TEXT DEFAULT '{}'
);
```

### 1.3 写入与批量触发

每轮 Pipeline 调用自动写入 Journal（零门槛）。Layer 1 命中则立即处理，否则累积等待批量触发。

| 触发器 | 条件 | 行为 |
|-------|------|------|
| 窗口溢出 | pending ≥ 5 或轮次 ≥ 10 | 批量处理 |
| 会话关闭 | Pipeline.close() | 兜底触发 |
| 定时器 | 距上次处理 > 5 min | 保护机制 |

### 1.4 三个核心价值

- **WAL 恢复**：Memory 崩了，Journal 可重放重建
- **审计追溯**：每条 LTM 可追溯到 Journal 中的 raw_input 和 round_id
- **批量聚合**：同实体多条记录在窗口内合并，避免碎片化写入

---

## 2. Write Decision 与 Router 彻底解耦

### 2.1 两个完全不同的问题

当前流程把 Write Decision 和 Router 混在一个通道里：

```
当前（耦合）:
  Layer1 → Layer2 → Layer3 → Route → Knowledge/Experience/LongTerm
  看起来是一条线性 pipeline，但问题在于——
  Knowledge 也必须经过 Importance 判断
```

**反例**："Redis 使用单线程模型"——Importance 只有 0.2（不是偏好，不是任务结论，不是 KV 状态变更），但它是一段确定性的结构化知识。如果 Knowledge 经过 Write Decision，这条知识就被丢弃了，后续 Graph RAG 就残缺。

```
Write Decision 回答的是:

  这段信息未来会不会被再次用到？
  → 用户偏好、状态变更、任务结论 → 值 0.8
  → "今天天气不错" → 值 0.1

Route 回答的是:

  这段信息应该存在哪种存储结构里？
  → 能提取 Triple/Property 的 → Knowledge
  → 有经验信号的 → Experience
  → 兜底 → LongTerm

两者完全独立。"Redis 单线程模型" 重要性 0.2，但仍应进入 Knowledge。
```

### 2.2 解耦后架构

```
Journal Entry
     │
     ├── Write Decision ── "值不值得存？"
     │        │             适用对象: Memory（LongTerm + Experience）
     │        │             判断维度: Layer 1 规则 + Layer 2 新颖度 + Layer 3 重要性
     │        │
     │    pass │ (score ≥ 0.5)
     │        ▼
     │   Memory Router ── "存在哪里？"
     │        │             不做价值判断，不拒收
     │   ┌────┴────┐
     │   ▼         ▼
     │ LongTerm  Experience
     │
     └── Knowledge Event ── "能否提取知识？"
              │              判断的是"可提取性"，不是"重要性"
              │              有自己的入口，自己的队列，自己的 Worker
              ▼
         KnowledgeGraph
```

**关键边界**：
- Write Decision 只适用于 Memory，不涉及 Knowledge
- Knowledge 有自己的入口（Knowledge Extractor），不做 Importance 判断
- 同一条 Journal Entry 可以**同时**进入 Memory 和 Knowledge（两者并行判断）
- Memory Router 不做价值判断——它收到的都是已通过 Write Decision 的条目，Router 只负责分发

### 2.3 Event Bus：解决"谁触发 Knowledge"的争议

§2.2 中 Journal 分叉到 Write Decision 和 Knowledge Event，但谁负责发布 Kevent？如果 MemoryUpdater 发布，则两者仍然耦合。正确的做法是引入一层轻量 Event Bus：

```
Journal.append() 写入后
  │
  └─ EventBus.publish("journal:created", journal_entry)
       │
       ├─ MemoryWriteSubscriber    订阅 → 调 WriteDecision.decide()
       │    pass → MemoryRouter.route() → LongTerm / Experience
       │
       └─ KnowledgeExtractSubscriber 订阅 → 调 KnowledgeExtractor.extract()
            └─ Channel A / Channel B → KnowledgeQueue
```

**EventBus 是 in-process 的 pub/sub，不做持久化（Journal 本身已经是持久化的事件日志）。MemoryUpdater 和 KnowledgeExtractor 互不知晓对方的存在，只知道自己订阅了一个事件。**

### 2.4 Write Decision 三层门控（继承 V1，V2 不做改动）

Write Decision 的三层门控在 V1（`LTM_WRITE_STRATEGY.md` §3）中已详细设计，V2 直接复用：

| 层 | 名称 | 判断 | 命中行为 |
|----|------|------|---------|
| Layer 1 | 规则必存 | 关键词"记住/记录/设置为" + KV 模式"X 是 Y" + 任务结论数字 | 立即通过，跳过 Layer 2/3 |
| Layer 2 | 新颖度过滤 | embedding 余弦相似度 vs 现有 LTM → sim > 0.9 触发实体值对比 | 重复则丢弃，更新则通过，其他通过 |
| Layer 3 | 重要性评分 | 5 维加权：identity(0.30) + state(0.20) + task(0.20) + cold_start(0.15) + quality(0.15) | overall ≥ 0.50 → pass |

当 Layer 1 未命中时，内容进入 Journal 等待批量触发（§1.3），批量处理时走 Layer 2 → Layer 3 完整流程。

---

## 3. Knowledge：不属于 Memory，独立知识服务

### 3.1 Knowledge 不是 Memory

这是整个架构中最关键的边界。Knowledge 和 Memory 是两种完全不同的东西：

```
Memory（记忆）                          Knowledge（知识）
───────────────────────────          ──────────────────────────────
回答: "用户是谁？做过什么？"          回答: "概念之间怎么关联？"
内容: 偏好、状态、经历、任务           内容: 三元组、属性、文档块、概念层级
存储: memories 表                    存储: concepts + concept_relations 表
写入: Write Decision 把关             写入: Knowledge Extractor 独立判断
检索: 按语义 + 时间 + 访问频率         检索: BFS 图遍历 / 向量相似度
生命周期: TTL + Decay + Forget        生命周期: 只增不删（冲突时按 reliability 覆盖）
所属: MemoryUpdater                    所属: KnowledgeUpdater（独立维护）
```

**为什么不能合并**：
- Knowledge 越来越大——MemoryUpdater 会越来越臃肿
- 两者的写入触发条件完全不同——Memory 看重要性，Knowledge 看可提取性
- 两者的检索方式完全不同——Memory 是向量+BMS5，Knowledge 是图遍历
- 以后 Knowledge Service 可能需要独立部署、独立扩缩容

### 3.2 独立 KnowledgeUpdater

```
当前（Memory 承担 Knowledge）:
  MemoryUpdater
    ├─ 记忆写入决策           ← Memory 的职责
    ├─ 记忆路由分发           ← Memory 的职责
    └─ 知识三元组抽取         ← ❌ 不是 Memory 的职责
         ├─ TripleExtractor
         └─ BackgroundConceptWorker（还耦合 LTM 表）

改进后（Knowledge 独立维护）:
  MemoryUpdater                 KnowledgeUpdater
  ────────────                  ────────────────
  ├─ Write Decision             ├─ Knowledge Extractor
  ├─ Memory Router              │    ├─ Channel A: 规则同步
  └─ 写 LongTerm/Experience     │    └─ Channel B: LLM 异步
                                ├─ Knowledge Queue
                                ├─ Knowledge Worker
                                └─ KnowledgeGraph (concepts + relations)

  MemoryUpdater 发布 Event → KnowledgeUpdater 消费 → 写 KnowledgeGraph
  两者通过 Event 通信，零直接依赖。
```

### 3.3 Knowledge 四种节点类型

当前 Knowledge 只支持 Triple（S-R-O），过于单一。扩展为四种：

```
1. Triple Node（三元组）
   格式: {subject, relation, object, confidence}
   例:  {Redis, 是, 缓存数据库, 1.0}
   例:  {Redis, 使用, 单线程模型, 0.8}

2. Property Node（实体属性）
   格式: {entity, property_name, value, source_reliability}
   例:  {Redis, 作者, "Salvatore Sanfilippo", 1.0}
   例:  {Redis, 官网, "https://redis.io", 1.0}

3. Document Node（文档块）
   格式: {content, embedding, source, chunk_index}
   例:  Redis 官方文档 → chunk → embedding → 存储
   检索: 向量相似度 → 返回相关 chunk

4. Taxonomy Node（概念分类层级）
   格式: {name, parent, level, description}
   例:  {缓存数据库, parent=数据库, level=2}
   例:  {Redis, parent=缓存数据库, level=3}
   → 构建概念层级树，为 Graph RAG 提供层级推理能力
```

| 节点类型 | 回答的问题 | 去重策略 |
|---------|-----------|---------|
| Triple | "Redis 是什么？" | (S,R,O) 三元组去重 |
| Property | "Redis 作者是谁？" | (entity, property_name) 去重，值冲突按 reliability 裁决 |
| Document | "Redis 单线程原理？" | embedding sim > 0.95 跳过 |
| Taxonomy | "Redis 属于哪类？" | (name) 去重，更新 parent |

为什么需要四种节点而不是只有 Triple：

- Triple 只能表达"关系"，无法表达属性的具体值（作者 = "Salvatore"）
- 长文本（文档）无法压缩为一个 Triple
- 概念层级（Redis 属于缓存数据库，缓存数据库属于数据库）是实现 Graph RAG 的基础

**Document Node 的存储扩展**：

当前 `concepts` + `concept_relations` 表只支持 Triple/Property/Taxonomy 节点。Document Node 需要新增一个轻量表：

```sql
CREATE TABLE knowledge_documents (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    embedding   TEXT,                      -- JSON float 数组
    source      TEXT,                      -- 原始来源引用
    chunk_index INTEGER DEFAULT 0,         -- 文档分段序号
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 索引：向量检索（如果 embedding 存储服务独立部署，此表在服务侧）
CREATE INDEX idx_knowledge_docs_source ON knowledge_documents(source);
```

### 3.4 Knowledge 与 Memory 的边界：什么时候入哪里

Property Node（Knowledge）和 LongTerm Fact（Memory）都存储实体属性，但它们的判断标准不同：

| 属性 | 来源 | 入 Knowledge? | 入 Memory? | 理由 |
|------|------|-------------|-----------|------|
| `user.name=张三` | 用户说"我叫张三" | ❌ | ✅ LongTerm Fact | 这是用户相关记忆，不是通用知识 |
| `Redis.作者=Salvatore` | 用户说"Redis 作者是 Salvatore" | ✅ Property Node | ❌ | 这是通用知识，不需要作为记忆长期保存 |
| `Redis.作者=Salvatore` | 官方文档 | ✅ Property Node | ❌ | 通用知识，无需记忆 |
| `Alice.余额=5000` | 任务结论 | ✅ Property Node | ✅ LongTerm Fact | 既是结构化知识，又是用户状态记忆 |

**判断标准**：

```
if entity 是当前用户或对话参与者:
    → 入 LongTerm Fact (Memory)
if 内容可以被提取为结构化属性且 entity 不是用户:
    → 入 Knowledge (Property Node)
if 两者都满足:
    → 两处都入（不同用途：Memory 用于记忆检索，Knowledge 用于知识问答）
```

### 3.5 从"拉"改"推"

```
改前（拉模式 - 耦合 Memory）:
  MemoryUpdater → BackgroundConceptWorker → 定时扫描 LTM 表 → WHERE concept_pending=true

改后（推模式 - 零耦合）:
  Knowledge Extractor → 发布 KnowledgeEvent
    → Knowledge Queue
      → Knowledge Worker 异步消费 → 写 KnowledgeGraph
```

### 3.6 Source Reliability 解决 Knowledge 冲突

同一属性不同来源不同值：

```
用户说："Redis 作者是我"       → reliability = 0.75 (User)
文档说："Redis 作者是 Salvatore" → reliability = 0.95 (Official Doc)

冲突裁决: 0.95 > 0.75 → 保留 Official Doc 版本，用户版本丢弃
```

### 3.7 触发策略

| 触发器 | 条件 |
|-------|------|
| 事件累积 | pending ≥ 30 条 |
| Debounce | 2 min 内新事件重置计时 |
| 兜底 | 距上次 > 15 min 强制执行 |
| Session 结束 | pending ≥ 10 → 强制消费 |

---

## 4. Maintenance Worker：五维生命周期

长期运行后记忆膨胀，需要完整的生命周期管理：

```
Maintenance Worker 定时调度:
  ├─ Merge    (每 1h)   合并相似/重复记忆
  ├─ Forget   (每 24h)  遗忘低价值/过期记忆
  ├─ Decay    (每 6h)   衰减长期未访问的权重
  ├─ Archive  (每 7d)   归档冷数据
  └─ Summarize(每 24h)  聚合多条为摘要
```

| 维度 | 策略 |
|------|------|
| **Merge** | 精确重复 → 合并 access_count；语义重复(sim>0.85) → 保留较长版；同 entity_key → 合并 version 链 |
| **Forget** | TTL 过期直接删；低价值(>90天 + access<2 + relevance<0.3)；用户纠正(reliability→0.2) |
| **Decay** | 时间衰减 exp(-t/7days)；访问衰减(>30天不访问 ×0.9)；Summary 加速衰减(半衰期3天) |
| **Archive** | >180天 + 最后访问>90天 + relevance<0.5 → 移出热检索 |
| **Summarize** | 同session>10条→合并；同entity>5条→聚合时间线 |
| **Journal 清理** | processed 且 >30天 → 删除；总行数 >10000 → 删最早的 5000 条；pending 永久不删 |

---

## 5. Experience 多标签：不再靠规则单选

### 5.1 问题：真实经历极少是单一类型

当前 Memory Router 通过规则分类（`classify_and_route`），把经历强制归入单一类型：

```
当前:
  检测 tool_usage 信号 → experience_type="tool_usage"
  检测 reflection 信号 → experience_type="reflection"
  检测 procedure 信号 → experience_type="procedure"
  检测 episode 信号   → experience_type="episode"
```

**反例**："今天 SQL 执行失败，后来发现索引没建，以后要先 explain"

这条经历同时包含：
- **episode**：SQL 执行失败了（场景、动作、结果）
- **reflection**：根因是索引没建（分析、教训）
- **procedure**：以后要先 explain（预防措施、规范操作）

单标签 `experience_type` 强制选一个主类型，丢失了其他维度的价值。

### 5.2 方案：Extractor 自动打多标签

```
Experience Extractor（Router 内部，自动检测）:
  - 检测到失败/错误/超时        → 添加 "episode" 标签
  - 检测到原因分析/根因/教训     → 添加 "reflection" 标签
  - 检测到步骤/规范/流程         → 添加 "procedure" 标签
  - 检测到工具调用              → 添加 "tool_usage" 标签
  - 检测到技术栈关键词           → 添加对应标签（如 "sql", "k8s"）
```

每条经历存储为 `tags: JSON 数组`，而不是单一 `experience_type`：

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
    "steps": ["EXPLAIN 分析", "确认索引状态", "CREATE INDEX 如缺失"]
}
```

### 5.3 检索优势

| 查询 | 方式 | 结果 |
|------|------|------|
| 所有反思经历 | `json_each(tags)` 匹配 `"reflection"` | 所有失败分析 + 教训 |
| SQL 相关的失败 | `tags` LIKE `%"episode"%` AND `tags` LIKE `%"sql"%` | 精确命中 |
| 所有规范操作 | `json_each(tags)` 匹配 `"procedure"` | 所有预防措施 |

为什么多标签对 Agent Learning 更强：
- 同一事件的多维标签天然成为训练样本（episode 描述"发生了什么"，reflection 描述"为什么"，procedure 描述"以后怎么做"）
- 标签组合可以表达复杂的检索意图，无需额外分类

---

## 6. LongTerm 二分：Fact vs Summary

### 6.1 问题：LongTerm 太像 KV Store

当前 LongTerm 的设计偏向键值对（entity_key → value），所有内容都被当成结构化事实处理：

```
当前 LongTerm:
  全部 → entity_key → value → version 链 → 同键覆盖

例如:
  entity_key="user.location" → value="北京"        ✅ KV 模式适合
  entity_key="user.location" → value="上海"        ✅ 覆盖旧值合理
```

但并非所有长期记忆都是 KV 键值对：

```
反例:
  "3/5~3/8 项目 Alpha 完成了数据迁移，遇到 schema 不兼容问题"
  "和 Bob 讨论了 Q3 预算分配，决定优先投入 AI 相关模块"
  "上周团队 Retro 结论：测试覆盖率是当前最大瓶颈"

  → 这些没有 entity_key，不能覆盖，不应做 diff
  → 强制套入 KV 模式会丢失语义
```

### 6.2 方案：Fact + Summary 两类

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
| **写入策略** | 同键覆盖，旧值入 history | embedding 去重，不覆盖 |
| **版本管理** | version 链（version+1, history.push） | 无版本概念 |
| **检索** | entity_key 精确查 + 语义查 | 纯语义检索 |
| **更新** | 覆盖（保留历史） | 新增，旧条目 decay 加速 |
| **去重** | entity_key 匹配 | embedding sim > 0.9 视为重复 |

### 6.3 写入分流

Memory Router 在分发到 LongTerm 时，根据内容性质分类：

```
Memory Router → LongTerm:
  │
  ├─ 能提取 entity_key？
  │   例如: "我是张三" → entity_key="user.name"
  │   例如: "余额 5000 元" → entity_key="account.balance"
  │   → 写入 Fact
  │     ├─ entity_key 已存在 → 更新 (version+1, history.push 旧值)
  │     └─ entity_key 不存在 → 新建 (version=1)
  │
  └─ 无法提取 entity_key？
      例如: "讨论了 Q3 预算分配方案"
      例如: "Retro 结论：测试覆盖率是瓶颈"
      → 写入 Summary
        ├─ embedding sim > 0.9 → 触发内容对比
        │    ├─ 实质内容相同 → 跳过（真正重复）
        │    └─ 有新增信息 → 合并为新条目，旧条目 decay 加速
        └─ sim < 0.9 → 新增
```

> **为什么不是简单跳过**：sim>0.9 不代表内容完全重复。例如"项目 Alpha 完成数据迁移"和"项目 Alpha 新增：完成 UI 改版"语义相似度极高，但后者有新增信息。必须做内容对比而非仅靠相似度。

区分标志：`metadata.category = "fact"` 或 `"summary"`。

### 6.4 Summary 与 Fact 的特殊处理

**Summary** 代表时间段，而非永久事实。在 Maintenance Worker 中：

- **Decay**：Summary 衰减更快（半衰期 3 天 vs Fact 7 天）
- **Summarize**：同一 session 内多条 Summary → 合并为一条聚合摘要
- **Merge**：不按 entity_key 合并（没有 key），只做语义去重 + 内容对比

**Fact version history 截断**：

频繁变更的 Fact（如"余额"每天更新）会导致 `metadata.history` 数组无限增长。Maintenance Worker 的 Merge 任务需对 history 做截断：

```
history 保留策略（触发条件：数组长度 > 10）:
  ├─ 保留最早的 1 条（记录初始值）
  ├─ 保留最近的 5 条（记录最近变更轨迹）
  └─ 其余删除
```

例如：余额变更 50 次 → 保留版本 1（初始 0 元）+ 版本 46~50（最近 5 次），版本 2~45 删除。防数组膨胀，同时保留时间线追溯能力。

---

## 7. Builder 与 Retriever 分离

### 7.1 问题：Builder 承担了太多

当前 Builder 直接调用各 Memory 层的检索接口，自己完成聚合排序：

```
Builder 当前职责:
  │
  ├─ 调 LTM.retrieve(query, top_k=25)       ← Search
  ├─ 调 Session.query(query, top_k=20)      ← Search
  ├─ 调 Experience.recall_relevant(query)    ← Search
  ├─ 调 Knowledge.query_graph(concept)       ← Search
  │
  ├─ 跨源合并去重                            ← Merge
  ├─ 统一排序打分                            ← Rank
  │
  └─ 打包为 UnifiedContext                   ← Build (唯一该做的)
```

Builder 实际上已经是一个检索引擎（Retrieval Engine），而不是纯粹的上下文构建器。这导致：

- Builder 需要了解每个 Memory 层的检索 API（强耦合）
- 新增一个存储层 → Builder 必须改代码
- Merge/Rank 逻辑无法独立测试和优化
- Builder 代码臃肿，职责不清晰

### 7.2 分离后架构

```
改造前:
  Builder → LTM.retrieve() + Session.query() + Experience.recall() + Knowledge.query()
          → 自己 merge_and_rank()
          → 打包 context

改造后:
  Builder → Retriever.retrieve(query, sources, top_k)
            │
            ├─ 1. Search: 并发调各 Memory 层
            ├─ 2. Merge:  跨源去重合并
            ├─ 3. Rank:   统一评分排序
            └─ 4. 返回 top-k 结果

  Builder → 拿到 Retriever 的结果 → 打包为 UnifiedContext（只做 Build）
```

### 7.3 职责边界

```
         Retriever（检索引擎）              Builder（上下文构建器）
         ────────────────────              ──────────────────────
  做的事： Search / Merge / Rank     做的事： 按 Intent 组装上下文
                                          补全 identity / environment
                                          控制 token budget
                                          格式化输出 UnifiedContext

  不管的事： token 预算                 不管的事： 从哪搜、怎么排
           上下文组装格式                         (由 Retriever 负责)
           intent 映射
```

### 7.4 评分只在 Retriever 做一次

这也是第 8 章统一评分的前提——因为 Retriever 是唯一做语义检索+评分的入口，所以公式只在这里执行一次：

```
Retriever.retrieve():
  1. Search → 并发查多源
  2. Score → 统一公式打分（semantic + bm25 + source_reliability + time + relevance + access）
  3. Merge → 跨源去重
  4. Rank  → 排序截断
  5. Return → top-k MemoryItem[]

Builder.build():
  1. 调用 Retriever.retrieve(query, sources, top_k=25)
  2. 补充 identity / environment / tools 上下文
  3. 按 token budget 截断
  4. 打包为 UnifiedContext
  5. 返回
```

### 7.5 Retriever 接口

**SourceAdapter**：解决各存储源 API 异构的问题。

Retriever 的 `sources` 参数（`"long_term"`, `"experience"`, `"knowledge"`, `"session"`, `"journal"`）映射到不同的检索 API。每个 source 需要一个 Adapter 统一接口：

```python
class SourceAdapter(Protocol):
    """各存储源的检索适配器。统一不同 API 的调用签名。"""
    source_name: str
    source_weight: float   # 跨源合并权重（与评分公式内的 source_reliability 不同，见 §8.3）

    async def search(self, query: str, top_k: int, **kwargs) -> list[RetrievedItem]:
        ...

# 各源 Adapter 示例
class LTMAdapter(SourceAdapter):
    source_name = "long_term"
    source_weight = 1.0

    async def search(self, query, top_k, **kwargs):
        return await self.ltm.retrieve(query, top_k, expand_history=kwargs.get("expand_history", False))

class ExperienceAdapter(SourceAdapter):
    source_name = "experience"
    source_weight = 0.8

    async def search(self, query, top_k, **kwargs):
        return await self.exp.recall_relevant(query, top_k, tags=kwargs.get("tags"))

class KnowledgeAdapter(SourceAdapter):
    source_name = "knowledge"
    source_weight = 0.6

    async def search(self, query, top_k, **kwargs):
        # 从 query 提取核心概念 → BFS 图遍历
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

```python
class UnifiedRetriever:
    """
    统一检索引擎。
    职责: Search → Merge → Rank。
    不负责: token 预算、上下文组装。
    """

    def __init__(self, adapters: dict[str, SourceAdapter]):
        self._adapters = adapters  # {"long_term": LTMAdapter, ...}

    async def retrieve(
        self,
        query: str,
        sources: list[str] | None = None,
        # 默认: ["long_term", "experience", "knowledge", "session", "journal"]
        top_k: int = 25,
        expand_history: bool = False,
        include_archived: bool = False,
    ) -> list[RetrievedItem]:
        # 1. Search: 并发调各 Adapter
        # 2. Score: 统一公式打分
        # 3. Merge: 跨源去重 × source_weight
        # 4. Rank: 排序截断
        ...
```

新增一个存储源 → 只需新增一个 Adapter 并注册到 Retriever，不修改 Retriever 核心逻辑。

---

## 8. 统一评分 + Source Reliability + Source Weight

### 8.1 问题

当前一条记忆被评分两次，两个公式时间衰减相差 69 倍（LTM 69天 vs Ranker 1天），排序结果不可预测。

### 8.2 统一公式（评分维度）

**检索即排序**。Retriever 是唯一评分入口，Optimizer 只做结构性整理。

```
unified_score = 0.30 × semantic_similarity
              + 0.20 × bm25_score
              + 0.15 × source_reliability   ← 每条记录的可信度
              + 0.10 × time_decay           （半衰期统一 7 天）
              + 0.15 × relevance_boost
              + 0.10 × access_frequency
```

### 8.3 两个概念：source_reliability vs source_weight

这是方案中容易混淆的两个概念，必须区分清楚：

| | source_reliability | source_weight |
|---|---|---|
| **含义** | 这条数据来源有多可靠？ | 这个存储源在检索中优先多少？ |
| **作用域** | 每条 MemoryItem 级别的属性 | 存储源（LTM / Experience / Knowledge）级别 |
| **谁设置** | 写入端根据来源设置，存入 `metadata.source_reliability` | Retriever 的 SourceAdapter 预设 |
| **在哪用** | 统一评分公式的维度之一（0.15 权重） | 跨源合并时作为乘数 |
| **会变吗** | 会——被纠正后降低，频繁访问且无误则提升 | 不会——架构级预设 |

**跨源合并公式**：

```
final_score = unified_score × source_weight

然后按 final_score 排序，同源内也按 final_score 排序。
```

例：
- LTM 中 source_reliability=0.6 的记忆: `unified_score=0.7` → `final = 0.7 × 1.0 = 0.70`
- Knowledge 中 source_reliability=0.95 的知识: `unified_score=0.8` → `final = 0.8 × 0.6 = 0.48`

高可信度知识排在低可信度 LTM 记忆之后——这就是 source_weight 的作用：保证已通过 Write Decision 的 LTM 优先于任意 Knowledge。

### 8.4 Source Reliability 分级（写入端设置）

| 来源 | reliability | 说明 |
|------|------------|------|
| 用户显式陈述 | 1.00 | "我住在北京" |
| 通道 A 规则抽取 | 1.00 | 确定性 KV 匹配 |
| 官方/系统数据 | 0.95 | API 返回值 |
| 用户隐式推断 | 0.80 | 连续 3 次选择深色模式 → 推断偏好 |
| 通道 B LLM 抽取 | 0.70 | 异步批量 LLM 抽取 |
| LLM 推断结论 | 0.60 | 从对话推算"余额=7101" |
| Journal pending | 0.50 | 未经过 Write Decision 的原始记录 |

### 8.5 Source Weight 分级（SourceAdapter 预设）

| 存储源 | weight | 说明 |
|-------|--------|------|
| long_term | 1.0 | 已通过 Write Decision，最高优先级 |
| experience | 0.8 | 经历记录，场景还原参考 |
| knowledge | 0.6 | 知识图谱，语义扩展 |
| journal | 0.4 | 未处理的原始记录 |
| session | 0.3 | 会话上下文，通常直接引用 |

---

## 9. 实施路线

| Phase | 内容 | 预估 |
|-------|------|------|
| 1 | Journal 表 + 独立 WAL 写入层 | 3-4d |
| 2 | Write Decision ↔ Memory Router 解耦 | 2-3d |
| 3 | KnowledgeUpdater 独立 + 四种节点类型 | 3-4d |
| 4 | Experience 多标签改造（Extractor 自动打标签） | 2d |
| 5 | LongTerm Fact/Summary 分流写入 | 2d |
| 6 | Maintenance Worker（Merge/Forget/Decay/Archive/Summarize） | 2-3d |
| 7 | Retriever 从 Builder 分离 + 统一评分 + Source Reliability | 3-4d |

### 新增文件

| 文件 | 说明 |
|------|------|
| `context_os/memory/journal.py` | Journal 独立 WAL 层 |
| `context_os/knowledge/event_queue.py` | Knowledge 事件队列 |
| `context_os/knowledge/extractor.py` | 独立 Knowledge 提取器 |
| `context_os/memory/event_bus.py` | In-process Event Bus（Journal → 各模块解耦） |
| `context_os/memory/retriever.py` | UnifiedRetriever + SourceAdapter |
| `context_os/maintenance/worker.py` | 维护任务调度器 |
| `context_os/maintenance/merge.py` | Merge 逻辑 |
| `context_os/maintenance/decay.py` | Decay / Forget / Archive 逻辑 |

### 重点修改文件

| 文件 | 改动 |
|------|------|
| `context_os/feedback/memory_updater.py` | 拆出 WriteDecision / MemoryRouter，移除 Knowledge 逻辑 |
| `context_os/feedback/concept_worker.py` | 改拉为推，消费事件队列 |
| `context_os/memory/store.py` | 新增 journal 表、knowledge_documents 表 DDL |
| `context_os/optimizer/ranker.py` | 移除二次评分 |
| `context_os/entry.py` | 初始化 Journal + Retriever + Maintenance Worker |

---

## 关键设计决策速查

| 决策 | 说明 |
|------|------|
| Journal 为独立表 | 不嵌入 Session，职责分离（WAL vs 会话） |
| Write Decision 与 Router 解耦 | 一个判断价值，一个决定位置，独立演化和测试 |
| Knowledge 完全独立 | Knowledge ≠ Memory，不同生命周期、不同存储、不同检索、独立维护 |
| Knowledge 推模式 | 事件驱动而非扫描 LTM，KnowledgeUpdater 与 MemoryUpdater 零直接依赖 |
| Knowledge 四种节点 | Triple / Property / Document / Taxonomy，支撑 Graph RAG 升级 |
| Experience 多标签 | tags 数组替代单 type，一个经历同时打 episode+reflection+procedure |
| 评分只做一次 | Retriever 统一评分，Optimizer 只做整理 |
| Source Reliability + Weight | 两个概念分离：reliability 在评分公式内衡量可信度，weight 在跨源合并时设定优先级 |
| LongTerm = Fact + Summary | 结构化事实用 KV+version 链，非结构化摘要用语义去重+内容对比，不强制套 KV |
| Retriever 从 Builder 分离 | Builder 只管组装上下文，Search/Merge/Rank 全交给 Retriever + SourceAdapter |
| 五维生命周期 | Merge → Forget → Decay → Archive → Summarize + Journal 清理，避免记忆膨胀 |
