# Context-OS 记忆系统架构文档

> 适用于面试答辩的技术架构说明。涵盖记忆层的完整生命周期：写入 → 存储 → 检索 → 维护。

---

## 目录

1. [架构全景](#1-架构全景)
2. [5 类记忆层](#2-5-类记忆层)
3. [写入流程](#3-写入流程)
4. [知识系统（独立于记忆）](#4-知识系统独立于记忆)
5. [统一检索引擎](#5-统一检索引擎)
6. [后台维护系统](#6-后台维护系统)
7. [基础设施](#7-基础设施)
8. [Pipeline 全链路](#8-pipeline-全链路)
9. [存储表设计](#9-存储表设计)
10. [核心设计原则与权衡](#10-核心设计原则与权衡)

---

## 1. 架构全景

### 1.1 系统分层

```
                         User Input
                             │
                             ▼
                     Context Pipeline
                             │
                    Journal（写前日志 / WAL）
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              │              ▼
       Write Decision        │      Knowledge Extractor
       "值不值得存？"         │      "可不可提取？"
       (Memory only)         │      (独立判断)
              │              │              │
          pass │             │         ┌────┴────┐
              ▼              │         ▼         ▼
        Memory Router        │     Channel A   Channel B
        "存在哪里？"          │     (规则同步)   (LLM 异步)
              │              │         │         │
       ┌─────┴─────┐         │         └────┬────┘
       ▼           ▼         │              ▼
   LongTerm    Experience    │       Knowledge Queue
                              │              │
                              │              ▼
                              │      Knowledge Updater
                              │              │
                              │              ▼
                              │      Knowledge Graph
                              │   (concepts + relations + documents)

────────────────────────────────────────────────

    Retriever（统一检索）
           │
    Search → Score → Merge → Rank
           │
           ▼
    Context Builder → LLM

────────────────────────────────────────────────

    Maintenance Worker（后台）
           │
    ┌──────┼──────┬─────────┬──────────┐
    │      │      │         │          │
    ▼      ▼      ▼         ▼          ▼
  Merge  Forget  Decay    Archive   Summarize
```

### 1.2 记忆层精简：10 类 → 5 类 + Knowledge（独立）

| # | 层 | 回答的问题 | 存储 | 生命周期 |
|---|-----|----------|------|---------|
| ① | **Working** | "我现在在干什么？" | 纯内存 Ring Buffer，容量 8000 tokens | 当前 session，FIFO 淘汰 |
| ② | **Session** | "这次对话发生了什么？" | `memories` (type="session")，TTL 24h | 单次 session |
| ③ | **LongTerm** | "我对用户/项目了解什么？" | `memories` (type="long_term")，Fact + Summary | 跨 session |
| ④ | **Experience** | "我以前做过什么？学到了什么？" | `experiences` (tags 多标签 JSON 数组) | 跨 session |
| ⊕ | **Knowledge** | "概念之间怎么关联？" | `concepts` + `concept_relations` + `knowledge_documents` | 跨 session，不衰减 |

**新增基础设施层（不存记忆，支撑写入和检索流程）：**

| 基础设施 | 职责 |
|---------|------|
| **Journal** | Write-Ahead Log，每轮自动写入，所有持久化写入的原材料 |
| **Retriever** | 统一检索引擎，Search → Score → Merge → Rank，从 Builder 中分离 |
| **Maintenance Worker** | 后台维护调度：Merge / Forget / Decay / Archive / Summarize |

### 1.3 核心设计原则

- **Write Decision 回答"值不值得存"**，只适用于 Memory（LongTerm + Experience），不做价值判断
- **Memory Router 回答"存在哪里"**，不做价值判断，不拒收
- **Knowledge 不入 Write Decision** —— "重要性"和"可提取性"是两个独立判断
- **Knowledge 不属于 Memory** —— 不同的生命周期、存储表、检索方式，由独立的 `KnowledgeUpdater` 维护
- **Journal 作为统一的写前日志** —— 所有写入经 Journal → 异步分发，支持重放恢复和审计追溯

---

## 2. 5 类记忆层

### 2.1 WorkingMemory — 当前任务上下文

**设计思路：** 容量受限的注意力窗口，仅保存当前任务最相关的上下文片段。

- **存储：** 纯内存 Ring Buffer，不持久化
- **容量：** `max_tokens = 8000`
- **淘汰策略：** FIFO，超出 token 预算时自动弹出最旧的条目
- **Token 估算：** 中文字符 × 1.5，英文字符 × 0.25
- **检索：** `get_recent(n)` 取最近 N 条，`find(keyword)` 关键词搜索，`get_attention_context(max_tokens)` 按优先级排序后按 token 预算截断

### 2.2 SessionMemory — 会话上下文 + 写入候选缓冲区

**设计思路：** 双职责——既记录当前会话的偏好/任务/错误，又作为 Write Decision 的 staging area。

- **存储：** SQLite `memories` 表，type="session"，TTL 24h（`expires_at` 列）
- **记录内容：** 用户偏好、子任务完成、错误与恢复
- **候选缓冲区（Pending Buffer）：**
  - `add_pending_candidate(content, ...)` → status="pending"，缓存待决策的原始对话片段
  - `query_pending()` → 检索所有 pending 记录
  - `update_pending_status()` → 标记为 "written" / "discarded"

**Flush 触发器：**

| 触发器 | 条件 | 说明 |
|-------|------|------|
| 窗口溢出 | pending ≥ 5 或轮次 ≥ 10 | 核心触发 |
| 会话关闭 | `Pipeline.close()` | 兜底触发 |
| 定时器 | > 5 分钟 | 保护机制 |

### 2.3 LongTermMemory — 跨 Session 的持久记忆

**设计思路：** 唯一同时支持"精确覆盖"和"语义去重"的记忆层。分为 Fact 和 Summary 两条写入路径。

**Fact vs Summary 二元设计：**

| 维度 | Fact（结构化事实） | Summary（非结构化摘要） |
|------|-------------------|---------------------|
| **entity_key** | 有（如 `user.name`, `account.balance`） | 无 |
| **写入策略** | 同键覆盖，旧值入 history | embedding 去重 + 内容对比 |
| **版本管理** | version 链（version+1，history.push） | 无版本概念 |
| **去重** | entity_key 精确匹配 | embedding sim > 0.9 → 内容对比 |
| **Decay** | 半衰期 7 天 | 半衰期 3 天（更快衰减） |
| **检索** | entity_key 精确查 + 语义查 | 纯语义检索 |

**关键 API：**

| 方法 | 用途 |
|------|------|
| `save_fact(fact_id, content, ...)` | 版本化存储，自动 version+1 |
| `save_summary(content, ...)` | embedding 去重，sim>0.9 时内容对比，有新增信息则合并 |
| `retrieve(query, top_k, ...)` | 混合检索（语义 + BM25 + 相关性 + 时间衰减） |
| `get_fact(fact_id)` | 精确获取事实及历史版本 |
| `query_facts(category, ...)` | 按类别查询事实 |
| `query_summaries(category, ...)` | 按类别查询摘要 |
| `decay_relevance(half_life_days)` | 时间衰减，Summary 用 3 天半衰期 |
| `forget(threshold_days)` | 清理低价值记忆（>90 天 + access<2 + relevance<0.3） |

**检索排序公式（有 embedding 时）：**

```
score = 0.40 × semantic + 0.25 × bm25 + 0.15 × relevance
      + 0.10 × time_decay + 0.10 × access_count
```

**无 embedding 退化：**

```
score = 0.55 × keyword + 0.20 × relevance + 0.15 × time_decay + 0.10 × access
```

**时序查询扩展：** `detect_temporal_query()` 识别"之前叫/原来叫/history"等模式，触发时降低时间衰减系数（0.001 vs 0.01），扩大候选池（1500 vs 500）。

### 2.4 ExperienceMemory — 多标签经验记录

**设计思路：** 真实经历极少是单一类型，用 JSON 数组 `tags` 替代单一 `experience_type`，一条记录可同时拥有多个标签。

**合并 4 种子类型至统一 `experiences` 表：**

| 子类型 | 字段 | 标签 |
|--------|------|------|
| Episode（事件） | scene / action / result / feedback | `"episode"` |
| Reflection（反思） | task_type / root_cause / lesson / preventive_action | `"reflection"` |
| Procedure（流程） | proc_name / steps / total_count / success_count | `"procedure"` |
| Tool Usage（工具使用） | tool_name / tool_success / error_type / duration_ms | `"tool_usage"` |

**多标签示例：**

```json
{
    "tags": ["episode", "reflection", "procedure", "sql"],
    "scene": "数据库查询执行",
    "lesson": "新表上线前必须建立索引",
    "steps": ["EXPLAIN 分析", "确认索引状态", "CREATE INDEX 如缺失"]
}
```

**检索方式：**

| 查询场景 | 方式 |
|---------|------|
| 所有反思 | `recall_by_tag("reflection")` |
| SQL 相关的失败 | `recall_relevant(tags=["sql"], experience_type="episode")` |
| 最近 10 条 | `get_recent_experiences(10)` |
| 工具成功率 | `get_latest_tool_stats("kubectl")` |

### 2.5 SemanticMemory — 知识图谱

**设计思路：** 概念-关系图，3 种节点类型。与 Experience 不同，不记录"经历"，只记录提取出的"知识"。

- **存储：** `concepts` 表（节点） + `concept_relations` 表（边）
- **节点类型（`node_type` 列）：** `'triple'`（三元组）、`'property'`（属性）、`'taxonomy'`（分类层级）
- **查询：** BFS 图遍历，默认深度 1，支持 `find_shortest_path()`
- **抽象：** `abstract_from_episodes()` 从经历中提取高频标签（>=2 次）作为概念节点

---

## 3. 写入流程

### 3.1 整体链路

```
User Input → Pipeline → Journal.append() → EventBus.publish("journal:created")
                                                │
            ┌───────────────────────────────────┤
            │                                   │
            ▼                                   ▼
    MemorySubscriber                    KnowledgeSubscriber
            │                                   │
    WriteDecision.decide()              KnowledgeExtractor.extract()
            │                                   │
    Layer 1 → Layer 2 → Layer 3          Channel A → Channel B
            │                                   │
    MemoryRouter.route()                       │
            │                                   │
    LongTerm / Experience              Knowledge Queue → Updater → Graph
```

### 3.2 Journal — 写前日志 (WAL)

**核心价值：**

1. **WAL 恢复：** Memory 崩了，Journal 可重放重建所有记忆
2. **审计追溯：** 每条 LTM 可追溯到 Journal 中的 `raw_input` 和 `round_id`
3. **批量聚合：** 同实体多条记录在窗口内合并为 Summary，避免碎片化写入

**表结构：**

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
    status       TEXT DEFAULT 'pending',   -- pending | processing | processed | discarded
    processed_at TEXT,
    created_at   TEXT NOT NULL
);
```

**批量处理流程：**

```
触发条件满足（pending ≥ 5）→
  1. 拉取：SELECT * FROM journal WHERE status='pending' ORDER BY round_id LIMIT 50
  2. 分组：按 entities 中的 person/entity 分组
  3. 决策：批量执行 write_decision()（Layer 2 + 3）→ 聚合/原样/丢弃
  4. 标记：UPDATE status='processed'（保留完整 audit trail，不删除）
```

### 3.3 Write Decision — 三层门控

**适用范围：** 仅 Memory（LongTerm + Experience）。Knowledge 不入此门——判断"重要"和判断"可提取"是两个独立问题。

**例：** "Redis 使用单线程模型"——Importance 只有 0.2（不是偏好/任务结论/状态变更），但它是一段确定性的结构化知识。如果 Knowledge 经过 Write Decision，这条知识就被丢弃了。

#### Layer 1：规则必存

三种命中条件（任意一个命中即直接通过，score=1.0，跳过 Layer 2/3）：

| 条件 | 检测方式 | 示例 |
|------|---------|------|
| 显式记忆指令 | 正则：`记住\|记录\|设置为\|保存\|remember` | "记住我喜欢深色模式" |
| KV 键值对 | 正则：`主语+是/住/在/喜欢+宾语` → `entity.attribute` | "我住在北京" → `user.location: 北京` |
| 任务关键结论 | 正则匹配数值结论（余额/统计/总计） | "余额为 7101 元" |

#### Layer 2：新颖度过滤

```
输入文本 → embedding → 与现有 LTM 最近的 top-10 做 cosine_similarity
  │
  ├─ max_sim < 0.3 → 高新颖，通过（cold_start 维度 bonus）
  ├─ 0.3 ≤ sim ≤ 0.9 → 正常，通过
  └─ sim > 0.9 → entity-value 对比
       ├─ 实体相同、值不同 → 更新，通过
       ├─ 实体相同、值相同 → 重复，丢弃
       └─ 无法提取实体 → 视为重复，丢弃
```

#### Layer 3：重要性评分

| 维度 | 权重 | 判断方法 | 说明 |
|------|------|---------|------|
| Identity | 0.30 | "我叫/我是"等身份模式 | 用户身份/偏好 |
| State | 0.20 | "余额/设置/update" + 数字 | 状态/配置变更 |
| Task | 0.20 | Evaluator 的 task_importance | 任务本身重要性 |
| Cold Start | 0.15 | LTM 总条数 < 50 → 加权 | 冷启动保护，>50 条后衰减至 0 |
| Quality | 0.15 | Evaluator 的 reward_score | LLM 输出质量 |

**阈值：** `overall ≥ 0.50` → 通过，进入 Memory Router。

### 3.4 Memory Router — 分流存储

**设计约束：** 前提是收到的都是已通过 Write Decision 的条目。Router 不做价值判断，只负责按信息性质分发。

**分流优先级：**

```
1. Knowledge Channel A（三元组命中，确定性规则）→ 直接写 Knowledge Graph
     ↓
2. Knowledge Channel B（概念信号，需 LLM 异步）→ 暂存 LTM + enqueue KnowledgeQueue
     ↓
3. Experience（检测到经历信号）→ ExperienceMemory（多标签）
     ↓
4. LongTerm（兜底）
     ├─ 有 entity_key → Fact（版本化存储）
     └─ 无 entity_key → Summary（语义去重）
```

**Experience 信号检测（正则，4 种标签）：**

| 标签 | 正则模式 |
|------|---------|
| `tool_usage` | `(调用\|use\|invoke).{0,10}(工具\|API\|tool\|function)` |
| `reflection` | `(失败\|错误\|bug\|error\|lesson\|root cause)` |
| `procedure` | `(步骤\|流程\|第一步\|step\|procedure\|workflow)` |
| `episode` | `(做了\|处理了\|completed\|executed)` + task context |

---

## 4. 知识系统（独立于记忆）

### 4.1 设计动机：Knowledge 不是 Memory

| | Memory（记忆） | Knowledge（知识） |
|---|-------------|----------------|
| 回答的问题 | "用户是谁？做过什么？" | "概念之间怎么关联？" |
| 内容 | 偏好、状态、经历、任务 | 三元组、属性、文档块、概念层级 |
| 存储表 | `memories` + `experiences` | `concepts` + `concept_relations` + `knowledge_documents` + `knowledge_properties` + `knowledge_taxonomy` |
| 写入把关 | Write Decision 三层门控 | Knowledge Extractor 独立判断（不入 Write Decision） |
| 检索方式 | 语义 + 时间 + 访问频率 | BFS 图遍历 / 向量相似度 |
| 生命周期 | TTL + Decay + Forget | 只增不删（冲突时按 reliability 裁决） |

### 4.2 提取双通道

**Channel A（规则同步）：**
- 10 组确定性正则模式
- 关系类型：`属于` / `基于` / `包含` / `是` / `X的Y是Z` / `使用` / `实现了` / `调用` / `依赖` / `等同于`
- confidence = 1.0，直接写入

**Channel B（LLM 异步）：**
- 触发条件：概念关键词 + 技术名词
- 入队 `KnowledgeQueue`，`KnowledgeUpdater` 批量消费
- Debounce：2 分钟内新 event 重置计时
- 兜底：距上次处理 > 15 分钟强制执行
- Max retry：3 次，超过标记 failed

### 4.3 四种节点类型

| 节点 | 表 | 去重策略 | 示例 |
|------|-----|---------|------|
| **Triple** | `concepts` (node_type='triple') | (S,R,O) 三元组去重 | `{Redis, 是, 缓存数据库, 1.0}` |
| **Property** | `knowledge_properties` | (entity, property_name) 去重，值冲突按 reliability 裁决 | `{Redis, 作者, "Salvatore", 0.95}` |
| **Document** | `knowledge_documents` | embedding sim > 0.95 跳过 | Redis 官方文档 chunk |
| **Taxonomy** | `knowledge_taxonomy` | (name) 去重，更新 parent | `{Redis, parent=NoSQL, level=3}` |

---

## 5. 统一检索引擎

### 5.1 架构设计

**分离前（Builder 承担了太多）：**

```
Builder 当前:
  ├─ LTM.retrieve()           } Search
  ├─ Session.query()          } Search
  ├─ Experience.recall()      } Search
  ├─ Knowledge.query_graph()  } Search
  ├─ 跨源合并去重              } Merge
  ├─ 统一排序打分              } Rank
  └─ 打包 UnifiedContext       } Build（唯一该做的）
```

**分离后：**

```
Builder → Retriever.retrieve(query, sources, top_k)
          │
          ├─ 1. Search: asyncio.gather 并发调 5 个 SourceAdapter
          ├─ 2. Score:  统一公式打分
          ├─ 3. Merge:  跨源去重 × source_weight
          └─ 4. Rank:   排序截断

Builder → 拿到结果 → 补充 identity / environment → 按 token budget 截断
```

### 5.2 SourceAdapter — 统一异构 API

各存储源的检索 API 完全不同。每个 source 需要一个 Adapter 统一调用签名：

```python
class SourceAdapter(Protocol):
    source_name: str
    source_weight: float   # 跨源合并权重

    async def search(self, query: str, top_k: int, **kwargs) -> list[RetrievedItem]:
        ...
```

| Adapter | source_weight | 底层调用 |
|---------|:------------:|---------|
| LTMAdapter | 1.0 | `LongTermMemory.retrieve(query, top_k)` |
| ExperienceAdapter | 0.8 | `ExperienceMemory.recall_relevant(query, tags)` |
| KnowledgeAdapter | 0.6 | `SemanticMemory.query(concept, depth=2)` → 子图 |
| JournalAdapter | 0.4 | `JournalStore.query_pending(query)` |
| SessionAdapter | 0.3 | `SessionMemory.query_pending(query)` |

**新增一个存储源 → 新增一个 Adapter 并注册，不修改 Retriever 核心。**

### 5.3 统一评分公式

**6 维评分（Retriever 是唯一做语义检索 + 评分的入口）：**

```
unified = 0.30 × semantic_similarity
        + 0.20 × bm25_score
        + 0.15 × source_reliability
        + 0.10 × time_decay            ← 半衰期统一 7 天
        + 0.15 × relevance_boost
        + 0.10 × access_frequency
```

**跨源最终分：** `final = unified × source_weight`

### 5.4 source_reliability vs source_weight（两个独立概念）

| | source_reliability | source_weight |
|---|---|---|
| **含义** | 这条数据来源有多可靠？ | 这个存储源在检索中优先多少？ |
| **作用域** | 每条 MemoryItem 级别 | 存储源（LTM / Experience / Knowledge）级别 |
| **会变吗** | 会——被纠正后降低，频繁访问则提升 | 不会——架构级预设 |

**Source Reliability 8 级：**

| 来源 | reliability | 说明 |
|------|:----------:|------|
| 用户显式陈述 / Channel A 规则 | 1.00 | "我住在北京" |
| 官方/系统数据 | 0.95 | API 返回值 |
| 用户隐式推断 | 0.80 | 连续 3 次选择深色模式 |
| Channel B LLM 抽取 | 0.70 | 异步批量 LLM 抽取 |
| LLM 推断结论 | 0.60 | 从对话推算"余额=7101" |
| Journal pending / Default | 0.50 | 未经过 Write Decision |

**Source Weight 5 级：**
LTM=1.0 > Experience=0.8 > Knowledge=0.6 > Journal=0.4 > Session=0.3

### 5.4 去重策略

- **Content 去重：** 完全相同内容 → 保留最高分
- **Entity 去重：** 同 entity_key → 保留最高分
- **Semantic 去重：** embedding cos sim > 0.95 → 保留最高分

---

## 6. 后台维护系统

### 6.1 调度表

```
Maintenance Worker 定时调度（asyncio 后台 loop）:
  ├─ Merge     (每 1h)   合并相似/重复记忆
  ├─ Forget    (每 24h)  遗忘低价值/过期记忆
  ├─ Decay     (每 6h)   衰减长期未访问的权重
  ├─ Archive   (每 7d)   归档冷数据
  ├─ Summarize (每 24h)  聚合多条为摘要
  └─ Journal Cleanup (每 24h) 清理过期日志
```

### 6.2 Merge（合并）

| 场景 | 策略 |
|------|------|
| 精确重复（相同 content） | 保留最早一条，合并 access_count（新=旧总和） |
| 语义重复（sim > 0.85） | 保留 content 较长的，长度差 < 20% → 保留 access_count 更高的 |
| 实体重复（同 entity_key/fact_id） | 多版本合并为 version 链，旧版本入 history |
| Experience 合并（同 tags + 相似场景） | 合并 lesson / steps，tags 取并集 |
| Fact history 截断（>10 条） | 保留最早 1 条 + 最近 5 条 |

### 6.3 Forget（遗忘）

| 条件 | 操作 |
|------|------|
| Session TTL 过期 | 直接删除 |
| 低价值（> 90 天 + access < 2 + relevance < 0.3） | 删除 |
| 用户纠正（"不对，不是北京"） | reliability → 0.2，标记已纠正 |
| Experience 过期（> 180 天） | 删除 |
| 显式遗忘指令 | metadata.deleted = True → 30 天后物理删除 |

### 6.4 Decay（衰减）

| 维度 | 策略 |
|------|------|
| 时间衰减 | Fact 半衰期 7 天：`exp(-ln(2)/7 × days)` |
| Summary 加速 | Summary 半衰期 3 天：`exp(-ln(2)/3 × days)` |
| 访问衰减 | > 30 天未访问 → relevance × 0.9 |
| 可靠度恢复 | access > 20 且 30 天内无纠正 → reliability + 0.05（cap 1.0） |

### 6.5 Archive（归档）vs Forget（遗忘）

| | Archive | Forget |
|---|---------|--------|
| 条件 | > 180 天 + 最后访问 > 90 天 + relevance < 0.5 | > 90 天 + access < 2 + relevance < 0.3 |
| 操作 | `metadata.archived = True` | 物理 DELETE |
| 是否可恢复 | 是（`include_archived=True` 时可检索） | 否 |

### 6.6 Summarize（摘要聚合）

| 场景 | 策略 |
|------|------|
| 对话摘要 | 同一 session > 10 条 Summary → 合并为一条聚合摘要 |
| 时间摘要 | 同一用户 7 天内 > 20 条 LTM → 合并为周摘要 |
| 实体摘要 | 同一 entity > 5 条 Fact → 聚合为时间线 |

---

## 7. 基础设施

### 7.1 EventBus — 进程内 Pub/Sub

**设计动机：** Journal 写入后需要触发 Write Decision（Memory 侧）和 Knowledge Extractor（Knowledge 侧）。如果由 MemoryUpdater 发布 Knowledge Event，两者仍然耦合。

**核心特性：**

- 进程内轻量 pub/sub，不做持久化（Journal 本身就是持久化事件日志）
- Publisher 不知道谁在订阅，Subscriber 不知道谁在发布
- 异常隔离：单个 handler 异常不影响其他 handler（`return_exceptions=True`）
- 自动清理：空 handler 列表自动删除

```python
class EventBus:
    def subscribe(self, event_type: str, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: str, handler: Callable) -> None: ...
    async def publish(self, event: object) -> None: ...  # asyncio.gather 并发分发
```

**事件流：**

```
Journal.append() 写入后
  │
  └─ EventBus.publish("journal:created", journal_entry)
       │
       ├─ MemoryWriteSubscriber → WriteDecision.decide()
       │
       └─ KnowledgeExtractSubscriber → KnowledgeExtractor.extract()
```

### 7.2 SQLiteStore — 唯一数据后端

**设计约束：** 全系统只有一个 `SQLiteStore` 实例，所有 5 类记忆和 4 个知识表共享同一个数据库连接。

- **引擎：** `aiosqlite` + WAL 模式 + 外键 ON
- **Lazy Connection：** `connect()` 首次调用时初始化连接和 9 张表
- **迁移：** `_migrate_node_type()` 为旧数据库补充 `node_type` 列
- **回退：** 无 SQLite 连接时回退到 JSON 文件存储（`./data/memory_fallback/`）

---

## 8. Pipeline 全链路

### 8.1 6 步 run() 流程

```
run(user_input):
  │
  ├─ ensure_store() → 懒连接 SQLite
  ├─ conversation.add_turn("user")
  ├─ tracer.start()
  │
  ├─ Step 1: TaskParser.parse(input)           → TaskSpec（意图 + 实体）
  │     IntentClassifier (LLM 分类) + EntityExtractor (规则抽取)
  │
  ├─ Step 2: ContextBuilder.build(task)         → UnifiedContext
  │     并发：identity + conversation + environment 收集器
  │     + UnifiedRetriever.retrieve(query, top_k=25)  ← 5 源检索
  │
  ├─ Step 3: ContextOptimizer.optimize(unified) → OptimizedContext
  │     RelevanceRanker → ContextCompressor → TokenBudgetAllocator
  │
  ├─ Step 4: ContextPackager.pack(optimized)    → PackagedContext
  │     Adapter 模式：Claude(XML) / OpenAI(纯文本) / DeepSeek(复用 OpenAI)
  │
  ├─ Step 5: llm_client.complete(prompt)        → LLM Response
  │     conversation.add_turn("assistant")
  │
  └─ Step 6: Feedback
       ├─ QualityEvaluator.evaluate(response, latency, tokens) → EvalMetrics
       ├─ MemoryUpdater.update_from_task() → 所有 5 层记忆
       └─ Journal.append(raw_input, raw_output, entities, intent)
```

### 8.2 生命周期管理

```python
async with ContextOSPipeline(llm_client=client) as pipeline:
    result = await pipeline.run("帮我部署 K8s 集群")
# 退出时自动调用 close():
#   → flush_pending_candidates()
#   → stop knowledge_updater
#   → stop concept_worker
#   → stop maintenance_worker
#   → close store
```

### 8.3 后台 Worker 生命周期

3 个后台 Worker 在 `__init__` 中同步启动，在 `close()` 中异步停止：

| Worker | 启动方式 | 停止方式 | 作用 |
|--------|---------|---------|------|
| `BackgroundConceptWorker` | `concept_worker.start()` | `await concept_worker.stop()` | 旧 Channel B 知识提取 |
| `KnowledgeUpdater` | `knowledge_updater.start()` | `await knowledge_updater.stop()` | 新 Channel B 知识提取（事件驱动） |
| `MaintenanceWorker` | `maintenance.start()` | `await maintenance.stop()` | 记忆维护调度 |

---

## 9. 存储表设计

### 9.1 9 张表总览

| # | 表 | 承载 | 类型 |
|---|-----|------|------|
| 1 | `memories` | Session + LongTerm，type 列区分 | 核心 |
| 2 | `concepts` | Knowledge 三元组/属性/分类节点，node_type 列区分 | Knowledge |
| 3 | `concept_relations` | Knowledge 关系边 | Knowledge |
| 4 | `experiences` | 统一经验（多标签 tags 数组） | 核心 |
| 5 | `journal` | Write-Ahead Log | 基础设施 |
| 6 | `knowledge_queue` | 异步知识提取队列 | 基础设施 |
| 7 | `knowledge_properties` | 实体-属性节点 | Knowledge |
| 8 | `knowledge_documents` | 文档块，含 embedding | Knowledge |
| 9 | `knowledge_taxonomy` | 概念层级 | Knowledge |

### 9.2 `memories` 表（最核心）

```sql
CREATE TABLE memories (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,               -- 'session' | 'long_term'
    content         TEXT NOT NULL,
    embedding       TEXT,                         -- JSON float 数组
    session_id      TEXT,
    user_id         TEXT DEFAULT 'anonymous',
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    access_count    INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    metadata        TEXT DEFAULT '{}',           -- JSON: {category, version, history, entity_key, source_reliability, archived, deleted}
    expires_at      TEXT                          -- Session TTL
);
```

### 9.3 `experiences` 表（多标签统一）

```sql
CREATE TABLE experiences (
    id               TEXT PRIMARY KEY,
    user_id          TEXT DEFAULT 'anonymous',
    experience_type  TEXT NOT NULL,               -- 兼容保留：'episode' | 'reflection' | 'procedure' | 'tool_usage'
    tags             TEXT DEFAULT '[]',           -- JSON 数组，多标签
    scene            TEXT, action TEXT, result TEXT,          -- episode
    task_type        TEXT, root_cause TEXT, lesson TEXT,      -- reflection
    proc_name        TEXT, steps TEXT,                        -- procedure
    tool_name        TEXT, tool_success INTEGER, error_type TEXT,  -- tool_usage
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    metadata         TEXT DEFAULT '{}'
);
```

---

## 10. 核心设计原则与权衡

### 10.1 关键设计决策

| 决策 | 原因 |
|------|------|
| **SQLite 而非 PostgreSQL** | 轻量嵌入式，零运维，适合个人 Agent。WAL 模式支持并发读写 |
| **Journal 作为唯一写入入口** | 统一审计追溯，支持重放恢复。Write Decision 和 Knowledge Extractor 异步订阅 |
| **Write Decision 与 Knowledge 解耦** | "这条信息重要"和"这条信息可提取知识"是两个独立问题，不应同一个门控 |
| **Memory Router 不拒收** | Router 的前提是已通过 Write Decision，只负责分发，不做价值判断 |
| **Fact vs Summary 两条写入路径** | 结构化事实可覆盖/版本化，非结构化摘要不可覆盖/只增 |
| **Experience 多标签而非单类型** | 真实经历极少单一类型，多标签支持交叉检索 |
| **检索即排序** | Retriever 是唯一做语义检索+评分的入口，Optimizer 只做结构性整理 |
| **Archive 而非 Delete** | 冷数据归档可恢复，避免误删后无法找回 |

### 10.2 扩展性保障

| 场景 | 扩展方式 |
|------|---------|
| 新增记忆层 | 新增 Memory 类 + 对应 Adapter + 注册到 Retriever |
| 新增事件消费者 | `EventBus.subscribe("journal:created", handler)` |
| 新增存储源 | 实现 `SourceAdapter` Protocol + 注册到 `UnifiedRetriever` |
| 新增维护任务 | 继承 `BaseTask` + 注册到 `MaintenanceWorker._schedule` |
| 替换 LLM Provider | 实现 `BaseLLMClient` + `complete()` |
| 替换向量数据库 | 实现 `EmbeddingProvider` Protocol + 注入到 `LongTermMemory` |

### 10.3 技术栈

- **语言：** Python 3.11+
- **数据存储：** SQLite（aiosqlite，WAL 模式）
- **数据模型：** Pydantic v2
- **异步：** asyncio（全链路 async/await）
- **测试：** pytest + pytest-asyncio
- **代码质量：** ruff（line-length=100）+ mypy

---

## 附录：技术指标

| 指标 | 数值 |
|------|------|
| 记忆层数 | 5 类（Working / Session / LongTerm / Experience / Semantic） |
| 知识节点数 | 4 种（Triple / Property / Document / Taxonomy） |
| 存储表 | 9 张（memories + concepts + concept_relations + experiences + journal + knowledge_queue + knowledge_properties + knowledge_documents + knowledge_taxonomy） |
| Source Adapter | 5 个（LTM 1.0 + Experience 0.8 + Knowledge 0.6 + Journal 0.4 + Session 0.3） |
| 主维护任务 | 6 项（Merge + Forget + Decay + Archive + Summarize + Journal Cleanup） |
| Write Decision | 3 层（规则必存 + 新颖度过滤 + 重要性评分） |
| 写入门控维度 | 5 维（Identity 0.30 + State 0.20 + Task 0.20 + Cold Start 0.15 + Quality 0.15） |
| 检索评分维度 | 6 维（Semantic 0.30 + BM25 0.20 + Reliability 0.15 + Time 0.10 + Relevance 0.15 + Access 0.10） |
| Source Reliability 级别 | 8 级（1.00 / 0.95 / 0.80 / 0.70 / 0.60 / 0.50） |
| 测试数量 | 294（292 passed） |
| 源码行数 | ~8000+ (context_os/) |

---

## 附录 B：Benchmark 实测结果

> 最新测试时间：2026-07-10，模型：DeepSeek

### 记忆 Benchmark（6 个用例）

| Case | SimpleAgent | MemoryAgent | Δ 提升 | Pass |
|------|:-----------:|:-----------:|:------:|:----:|
| T1 金融多用户 | 0% | 68% | +68% | ✅ |
| T2 多层配置级联 | 36% | 100% | +64% | ✅ |
| T3 社交关系网络 | 4% | 60% | +56% | ✅ |
| T4 系统监控时序 | 24% | 73% | +49% | ✅ |
| T5 钱包余额推理 | 8% | 70% | +62% | ✅ |
| T6 跨会话配置 | 56% | 100% | +44% | ✅ |

**汇总：**

| 指标 | 数值 |
|------|:----:|
| MemoryAgent 平均准确率 | **78.6%** |
| SimpleAgent 平均准确率 | 21.3% |
| 记忆系统提升幅度 | **+57.3%** |
| 用例通过率 | **6/6 (100%)** |

### 意图分类 Benchmark

| Case | Accuracy |
|------|:--------:|
| INT1 | 100.0% |
| INT2 | 100.0% |
| INT3 | 100.0% |
| INT4 | 100.0% |
| INT5 | 100.0% |

### Scoring Dashboard

| 维度 | 得分 | 说明 |
|------|:---:|------|
| intent | 100.0% | 意图识别准确率 |
| collection | 100.0% | 上下文数据收集 |
| builder | 100.0% | 上下文构建 |
| memory | 78.6% | 记忆系统准确率 |
| recall | 100.0% | 记忆检索召回率 |
| compression | 76.0% | 上下文压缩效率 |
| feedback | 100.0% | 反馈闭环 |
| reflection | 100.0% | 自我反思 |
| tool | N/A | 工具调用（未测试） |
| pipeline | 52.7% | 全链路延迟评分 |

**总体评分：88.5%（Grade B+）**

**关键结论：** 记忆系统在所有 6 个测试用例上均显著优于无记忆基线，平均提升 **+57.3%**，所有模块通过率 100%。pipeline 延迟评分偏低（52.7%），仍有优化空间。
