# 长期记忆写入策略设计文档

## 目录

0. [目标记忆架构](#0-目标记忆架构)
1. [核心原则](#1-核心原则)
2. [当前状态与问题](#2-当前状态与问题)
3. [三层写入决策](#3-三层写入决策)
4. [统一裁决与分流存储](#4-统一裁决与分流存储)
5. [写入触发时机](#5-写入触发时机)
6. [候选缓冲区设计](#6-候选缓冲区设计)
7. [检索增强：候选区联合查询](#7-检索增强)
8. [统一评分公式](#8-统一评分公式)
9. [实施方案](#9-实施方案)
10. [涉及文件清单](#10-涉及文件清单)

---

## 0. 目标记忆架构

### 0.1 精简：10 层 → 5 层 + Knowledge（独立）

当前 10 层记忆存在三类冗余：写入路径断裂（5 种从未自动写入）、内容重叠（ShortTerm↔Task、LongTerm↔Fact、Episodic→Reflection→Procedural）、排序逻辑不一致。

精简后 5 层记忆 + Knowledge 独立维护。**Knowledge 不是 Memory**——它是一张知识图谱（Knowledge Graph），生命周期、写入路径、检索方式都与记忆不同。

```
精简前 10 层                        精简后 5 层 + 独立 Knowledge
──────────────────────────────────────────────────────────────────
WorkingMemory      ──→  ① Working          纯内存，当前轮次
ShortTermMemory    ─┐
TaskMemory         ─┤→  ② Session          SQLite，TTL 24h
                   ─┘
LongTermMemory     ─┐
FactMemory         ─┘→  ③ LongTerm         SQLite，永久+衰减
                       （Fact + Summary 两类）
EpisodicMemory     ─┐
ReflectionMemory   ─┤
ProceduralMemory   ─┤→  ④ Experience       SQLite，永久
ToolExperience     ─┘    （多标签，非单选）

SemanticMemory     ──→  ⊕ Knowledge        独立知识服务（SQLite 图 / 向量）
                       （不属于 Memory，独立 KnowledgeUpdater 维护）
```

**新增基础设施层**（不存记忆，支撑写入流程）：

```
Journal (Write-Ahead Log)          ← 候选缓冲区抽象，Session 层不再承担 pending 职责
Retriever (统一检索引擎)            ← 从 Builder 中分离，专职 Search/Merge/Rank
Maintenance Worker                 ← 后台维护：Merge/Forget/Decay/Archive/Summarize
```

### 0.2 各层职责与存储

| # | 层 | 回答的问题 | 存储表 | 记录标识 | 写入触发 |
|---|-----|----------|-------|---------|---------|
| ① | **Working** | "我现在在干什么？" | 纯内存 | — | 每轮自动 push，预算外 LRU 淘汰 |
| ② | **Session** | "这次对话发生了什么？" | `memories` | `type="session"` | 每轮自动写入，session 结束 TTL 清除 |
| ③ | **LongTerm** | "我对用户/项目了解什么？" | `memories` | `type="long_term"` + `category` | Write Decision pass 后，Router 分发存入 |
| ④ | **Experience** | "我以前做过什么？学到了什么？" | `experiences` | `tags` (多标签) | Write Decision pass 后，Router 分发存入 |
| ⊕ | **Knowledge** | "概念之间怎么关联？" | `concepts` + `concept_relations` | — | **不走 Write Decision**，Knowledge Router 独立判断 |

**核心设计原则**：
- **Write Decision 回答"值不值得存"**，只适用于 Memory（LongTerm / Experience）
- **Router 回答"存在哪里"**，对 Memory 按信息性质分发
- **Knowledge 不入 Write Decision**——一个事实即使 Importance=0.2（不重要），只要能被提取为结构化知识，就应该进入 Knowledge

### 0.3 存储表精简

从 **10 张表 → 5 张表**（含 Journal）：

| 变化 | 表名 | 承载 |
|------|------|------|
| **保留** | `memories` | Session + LongTerm，`type` 列区分 |
| **保留** | `concepts` + `concept_relations` | Knowledge 图结构 |
| **新增** | `experiences` | 合并原 episodes、reflections、procedures、tool_usage，多标签 |
| **新增** | `journal` | Write-Ahead Log，承载候选区（原 Session 的 pending 职责迁移至此） |
| **删除** | `facts` | 并入 `memories`（LongTerm 的 `metadata.category="fact"`，含 `version`） |
| **删除** | `task_records` | 并入 `memories`（Session 的 `metadata` 中存 task 字段） |
| **删除** | `episodes`、`reflections`、`procedures`、`tool_experience`、`tool_stats` | 并入 `experiences` |

### 0.4 Experience 表统一结构（多标签方案）

**核心设计变化**：不再用单一 `experience_type`，改为 **`tags` 多标签数组**。

同一事件可以同时是 episode + reflection + procedure。例如"SQL 执行失败，发现索引没建，以后要先 explain"→ tags: `["episode", "reflection", "procedure", "sql"]`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键 |
| `user_id` | TEXT | 用户 ID |
| `tags` | JSON 数组 | **多标签**：`["episode", "reflection", "procedure", "tool_usage"]` 的任意组合 |
| `scene` | TEXT | 场景描述（episode 相关） |
| `action` | TEXT | 执行动作 |
| `result` | TEXT | 结果 |
| `root_cause` | TEXT | 根因分析（reflection 相关） |
| `lesson` | TEXT | 经验教训 |
| `preventive_action` | TEXT | 预防措施 |
| `steps` | JSON | 步骤（procedure 相关） |
| `tool_name` | TEXT | 工具名（tool_usage 相关） |
| `error_type` | TEXT | 错误类型 |
| `duration_ms` | INT | 耗时 |
| `created_at` | TEXT | 创建时间 |
| `metadata` | JSON | 扩展字段 |

**为什么多标签优于单类型**：
- 真实经历极少是单一类型的——一次 SQL 失败同时是 episode（发生了）、reflection（为什么）、procedure（以后怎么做）
- 多标签自然支持"按标签检索"→ 查 `tags CONTAINS "reflection"` 即可得到所有反思经历
- 为后续 Agent Learning 提供更丰富的训练样本

### 0.5 写入路径总览

```
update_from_task()
  │
  ├─ Working.push()         ← 每轮自动（纯内存，无门槛）
  ├─ Session.save()         ← 每轮自动（会话落地，无门槛）
  │
  ├─ Journal.append()       ← 每轮自动（Write-Ahead Log）
  │
  ├─ write_decision()       ← 统一闸门，回答"值不值得存？"（只适用于 Memory）
  │    │
  │    └─ if pass (score ≥ 0.5):
  │         │
  │         ├─ Memory Router ── 回答"存在哪里？"
  │         │    ├─ LongTerm.save()     ← Fact / Summary 两类
  │         │    └─ Experience.save()   ← 多标签
  │         │
  │         └─ (Knowledge 独立路由，不经过 write_decision)
  │
  └─ Knowledge Event 发布
       │
       └─ KnowledgeUpdater（独立，异步）
            ├─ Channel A: 规则直接写入
            └─ Channel B: LLM 抽取后写入

后台维护:
   Maintenance Worker
     └─ Merge / Forget / Decay / Archive / Summarize
```

**核心变化**：
1. **Write Decision 和 Router 解耦**——前者回答"值不值得存"（仅 Memory），后者回答"存在哪里"
2. **Knowledge 完全独立**——不经过 Write Decision，由独立的 KnowledgeUpdater 维护
3. **Journal 承担候选区职责**——Session 不再混入 pending 状态
4. **Experience 多标签**——同一经历可以有多个维度的标签

---

## 1. 核心原则

长期记忆只存储**未来有复用价值**的信息：

- **不存**：废话、闲聊、一次性上下文（"今天天气不错"）
- **必存**：用户属性、显式记忆指令、任务关键结论
- **选存**：状态变更、配置修改、新事实——需通过新颖度和重要性评估

全量存储 → 检索噪音大、成本高；完全不存 → "失忆"。需要设计分层写入决策。

---

## 2. 当前状态与问题

### 2.1 当前写入逻辑

```python
# context_os/feedback/memory_updater.py
is_state_update = task.intent.value in ("agent", "coding", "workflow")
if is_state_update:
    store_ltm = True               # 方案一：规则硬阈值
else:
    store_ltm = metrics.reward_score >= 0.7  # 方案二：重要性评分
```

### 2.2 存在的问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | `agent` 意图覆盖太广，一概全存 | 财务、关系、配置全部入库，噪音大 |
| 2 | 重要性评分只有 `reward_score` 一个维度 | 高质量回答（但信息无用）反而被存 |
| 3 | 缺少 KV 键值对提取 | 用户说"我住在北京"不会自动提取 `{location: 北京}` |
| 4 | 不存储任务结论 | LLM 推算出的结论（如"余额 7101"）丢失 |
| 5 | 逐轮写入无跨轮去重 | 同一个人的余额更新了 3 次，3 条全存 |
| 6 | 写入判断无新颖度检查 | 与已存记忆高度相似的内容重复入库 |
| 7 | 各记忆类型独立写入，无统一门槛 | 见 2.3 节 |

### 2.3 多类型独立写入的问题

当前 `memory_updater.update_from_task()` 对各个存储是各自独立判断的：

```
memory_updater.update_from_task()
  ├─ Working.push()        ← 每轮都写
  ├─ ShortTerm.save()      ← 每轮都写（任务摘要）
  ├─ LTM.save()            ← 有门槛（intent=agent 或 reward≥0.7）
  ├─ EpisodicMemory.save() ← 无统一门槛（每轮都存 episode）
  ├─ SemanticMemory.save() ← 无统一门槛
  ├─ FactMemory            ← 从不自动写入
  ├─ TaskMemory            ← 从不自动写入
  ├─ ProceduralMemory      ← 从不自动写入
  ├─ ReflectionMemory      ← 从不自动写入
  └─ ToolExperienceMemory  ← 从不自动写入
```

**核心问题**：5 种记忆类型从未被 pipeline 自动写入，纯属"死代码"。同时已写入的类型（LTM/Episodic/Semantic）各自独立判断是否存储，导致：

| 问题 | 表现 |
|------|------|
| 写入路径断裂 | Fact、Task、Procedural、Reflection、ToolExperience 有完整数据和表但从未自动调用 |
| 内容重叠 | ShortTerm 任务摘要 ↔ TaskMemory 完整记录（冗余）；LTM 事实 ↔ FactMemory 版本化事实（冗余） |
| 噪音沉积 | EpisodicMemory 每轮生成 episode，80% 是无价值的中间步骤 |
| 检索重复 | 同一条信息可能在 LTM、Fact、Semantic 中同时存在，检索时重复返回 |

**精简后**：只有 3 个持久层（LongTerm / Experience / Knowledge）需要通过写入决策，统一闸门按一次判断、分流写入。

---

## 3. Write Decision：值不值得存？（仅 Memory）

> **适用范围**: 本章只适用于 Memory 层（LongTerm + Experience）。Knowledge 不经过 Write Decision，见第 4 章。

```
用户输入 + LLM 回复
  │
  ├─ Layer 1: 规则必存 → 立即通过，跳过后续判断
  │   条件: 显式"记住"指令 | KV 键值对 | 任务关键结论
  │
  ├─ Layer 2: 新颖度过滤 → 低于阈值则丢弃
  │   方法: embedding 语义相似度对比现有 LTM，含实体值对比
  │
  └─ Layer 3: 重要性综合评分 → score >= 0.5 则存入（统一阈值）
      评分维度:
        - 是否涉及用户属性?       (identity_weight:  0.30)
        - 是否涉及状态/配置变更?   (state_weight:     0.20)
        - 任务重要性级别?          (task_weight:      0.20)
        - 冷启动保护?             (cold_start_weight: 0.15)
        - Evaluator reward 修正?   (quality_weight:   0.15)

  ⚠️ 权重说明: 以上所有权重均为初始实验值，后续通过 A/B 测试
     和 reward 反馈信号调优，不视为最终参数。

  ✅ pass (score ≥ 0.5) → 进入 Memory Router（第 4 章），由 Router 决定存 LongTerm 还是 Experience
  ❌ discard           → 不进任何 Memory 层
```

**为什么 Knowledge 不入 Write Decision？**

Write Decision 回答的问题是"这段信息值不值得作为记忆长期保存？"——这是一个**重要性**判断。

但 Knowledge 要回答的是"这段信息是否包含可提取的结构化知识？"——这是一个**可提取性**判断。

两者完全独立。例如：

| 信息 | Importance | 可提取为知识？ | 应该 |
|------|-----------|-------------|------|
| "Redis 使用单线程模型" | 0.2（不重要的闲聊） | ✅ 是 | → Knowledge（不走 Memory） |
| "用户偏好深色模式" | 0.8（重要偏好） | ❌ 否 | → LongTerm |
| "Alice 余额 5000 元" | 0.7（重要状态） | ✅ 是 | → LongTerm + Knowledge |

如果 Knowledge 也经过 Write Decision，Importance=0.2 的知识就被丢弃了——这是多数知识图谱系统的反模式。

### 3.1 Layer 1 详细规则

| 触发条件 | 检测方式 | 示例 |
|---------|---------|------|
| 显式记忆指令 | 关键词：`记住`、`记录`、`设置为`、`保存` | "记住我喜欢深色模式" |
| 键值对模式 | 正则提取 `主语+是/住/在/喜欢+宾语` | "我在北京" → {location: 北京} |
| 任务关键结论 | LLM 回复中的结构化摘要 | "余额为 7101 元" |

### 3.2 Layer 2 新颖度判定

```
输入文本 → embedding → 与现有 LTM 最近的 N 条做 cosine_similarity
  │
  ├─ max_similarity > 0.9  → 高相似，进入实体值对比
  │    ├─ 实体相同但值不同 → 更新（非重复），跳至 Layer 3 打分
  │    ├─ 实体相同且值相同 → 重复，丢弃
  │    └─ 无法提取实体     → 视为重复，丢弃
  │
  ├─ max_similarity < 0.3  → 高新颖，进入 Layer 3 打分（cold_start 维度给予 bonus）
  │
  └─ 0.3 ≤ sim ≤ 0.9      → 正常，进入 Layer 3 打分
```

**实体值对比**（仅在 similarity > 0.9 时触发）：

从候选文本和匹配到的已存记忆中分别提取 `{entity: value}` 键值对，对比逻辑：

```
候选: "Alice 余额 7101 元"
已存: "Alice 余额 5000 元"
  → 提取 → {Alice_余额: 7101} vs {Alice_余额: 5000}
  → 实体相同，值不同 → 更新，标记 update_type="entity_value_change"

候选: "Alice 住在北京"
已存: "Alice 住在北京"
  → 提取 → {Alice_居住地: 北京} vs {Alice_居住地: 北京}
  → 实体相同，值相同 → 重复，丢弃

候选: "今天天气不错"  （无法提取任何 entity-value）
已存: "今天天气不错"
  → similarity > 0.95 but 无法提取实体 → 重复，丢弃
```

实体提取复用 Layer 1 的 KV 模式匹配（主语+是/住/在/喜欢+宾语），结合数字字段正则 `[\d.]+元/个/人/次`。无需新增 LLM 调用。

### 3.3 Layer 3 评分维度说明

| 维度 | 含义 | 判断方法 |
|------|------|---------|
| identity_weight | 是否涉及用户身份/偏好 | 包含"我是/我住在/我偏好"等模式 |
| state_weight | 是否涉及状态变更 | intent 为 agent/coding 且含数字/金额 |
| task_weight | 任务本身的重要性 | Evaluator 给的 task_importance |
| cold_start_weight | LTM 冷启动保护 | 当前 LTM 总条数 < 50 → 加权 |
| quality_weight | LLM 输出的质量 | Evaluator 的 reward_score |

> **关于 cold_start**：该维度的正确含义是"系统早期数据稀疏时的保护性加权"，而非"被查询频率的反向加权"。冷启动阶段的记忆可能有更高噪音容忍度，但随着 LTM 条目增长（> 50 条），该权重自动衰减至 0。

---

## 4. Router 层：存在哪里？

### 4.1 架构总览：Write Decision 与 Router 解耦

```
                          User Input → Journal
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             │             ▼
            Write Decision        │      Knowledge Router
          "值不值得存？"          │    "能否提取知识？"
            (仅 Memory)          │     (独立判断)
                    │             │             │
              pass  │             │        ┌────┴────┐
                    ▼             │        ▼         ▼
             Memory Router        │    Channel A  Channel B
            "存在哪里？"          │    (规则直接写) (LLM异步)
                    │             │
              ┌─────┴─────┐      │
              ▼           ▼      │
          LongTerm   Experience  │
```

**关键边界**：
- Write Decision 和 Router 是**两个独立阶段**，不耦合
- Knowledge Router 有**自己的入口**，不与 Write Decision 共享闸门
- Memory Router 和 Knowledge Router 可以**并行判断**——同一条信息可以同时进入 Memory 和 Knowledge

### 4.2 Memory Router：LongTerm vs Experience

通过 Write Decision（score ≥ 0.5）的信息进入 Memory Router。Router 的唯一职责是：**按信息性质决定分发到哪个 Memory 层**。

```
Memory Router 判断:

  1. 信息涉及 episode / reflection / procedure / tool_usage 信号?
     → Experience（可多标签）

  2. 兜底 → LongTerm（Fact 或 Summary）
```

**不再设 Experience 阈值**：Write Decision 已做质量闸门，Router 只做分发。如果信息通过了 Write Decision 但 Experience Router 因阈值拒收，会出现"信息被判有价值却无处可去"的矛盾。

**不与 LTM 重叠的说明**：同一信息可能同时分流到 LongTerm 和 Experience——这是合理的。例如"处理了一个报销请求"→ LongTerm 存 `{user: Bob, 最新报销: 200元}`，Experience 存完整 episode。两层的检索路径不同：LTM 用于快速查事实，Experience 用于场景还原。

### 4.3 LongTerm 两分：Fact + Summary

当前 LongTerm 设计偏向 KV 键值对（entity_key → value），但并非所有长期记忆都是键值对：

| 类别 | 示例 | entity_key | 特点 |
|------|------|-----------|------|
| **Fact** | `user.location=北京`, `Alice.余额=5000` | ✅ 有 | 结构化，可对比 diff，支持 version 链 |
| **Summary** | "3/5~3/8 项目 Alpha 完成了数据迁移，遇到 schema 不兼容问题" | ❌ 无 | 非结构化，不可 diff，不可覆盖 |

**Fact** 的存取逻辑：
```
写入: entity_key 严格匹配 → 同键更新（version+1, history.push 旧值）
检索: 按 entity_key 精确查 / 按 content 语义查
更新: 同键覆盖，version 链保留历史
```

**Summary** 的存取逻辑：
```
写入: embedding 相似度去重（sim > 0.9 视为重复）
检索: 纯语义检索，无精确匹配
更新: 不覆盖，新增后旧条目 decay 加速
```

`metadata.category` 区分：`"fact"` 或 `"summary"`。

### 4.4 Experience Router：多标签（非单选）

真实经历极少是单一类型。考虑这个例子：

```
"今天 SQL 执行失败，后来发现索引没建，以后要先 explain"
```

它同时包含：
- **episode**：SQL 执行失败了（场景、动作、结果）
- **reflection**：根因是索引没建（分析、教训）
- **procedure**：以后要先 explain（预防措施）

当前单标签 `experience_type` 迫使选一个主类型，丢失了其他维度。

**多标签方案**：

```python
# Experience 记录
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
}
```

**Extractor 自动打标签**（非手动选择）：

```
Experience Extractor（Router 内部）:
  - 检测到失败/错误/超时 → 添加 "episode" 标签
  - 检测到原因分析/根因 → 添加 "reflection" 标签
  - 检测到步骤/规范 → 添加 "procedure" 标签
  - 检测到工具调用 → 添加 "tool_usage" 标签
  - 检测到技术栈关键词 → 添加对应标签（如 "sql", "k8s"）
```

**检索优势**：
- `tags CONTAINS "reflection"` → 所有反思经历
- `tags CONTAINS "episode" AND tags CONTAINS "sql"` → SQL 相关的失败经历
- `tags CONTAINS "procedure"` → 所有规范化操作

### 4.5 Knowledge Router：独立入口

Knowledge 不经过 Write Decision。任何信息，只要能被提取为结构化知识，就应该进入 Knowledge——无论它的 Importance 是多少。

#### 4.5.1 Knowledge 节点类型

当前 Knowledge 只支持三元组（Subject-Relation-Object）。这限制了知识表示能力。应该支持**四种节点类型**：

```
Knowledge Node Types:

  1. Triple Node（三元组）
     格式: {subject, relation, object}
     示例: {Redis, 是, 缓存数据库}
     例:  {Redis, 使用, 单线程模型}

  2. Property Node（属性）
     格式: {entity, property_name, value, confidence}
     示例: {Redis, 作者, "Salvatore Sanfilippo", 1.0}
     例:  {Redis, 官网, "https://redis.io", 1.0}

  3. Document Node（文档块）
     格式: {content, embedding, source, chunk_index}
     示例: Redis 官方文档的一个段落 chuncked 后存为 Document Node
     检索: 向量相似度 → 返回相关 chunk

  4. Taxonomy Node（分类）
     格式: {name, parent, level, description}
     示例: {缓存数据库, parent=数据库, level=2}
     例:  {Redis, parent=缓存数据库, level=3}
     → 构建概念层级树（为 Graph RAG 提供层级关系）
```

**为什么需要四种节点**：
- **Triple**：回答"Redis 是什么" → 快速关系查询
- **Property**：回答"Redis 作者是谁" → 精确属性查询
- **Document**：回答"Redis 单线程模型的原理" → 长文本语义检索
- **Taxonomy**：回答"Redis 属于哪类数据库" → 概念层级推理

#### 4.5.2 Knowledge Router 判断流程

```
Knowledge Router:

  输入 → 同时尝试所有节点类型:

  ├─ Triple 提取:  通道 A 规则 / 通道 B LLM
  │   命中 → 写 Triple Node
  │
  ├─ Property 提取: KV 模式匹配 (同 Layer 1)
  │   命中 → 写 Property Node
  │
  ├─ Document 提取: 长文本 (>200 chars) → chunk → embedding
  │   命中 → 写 Document Node
  │
  └─ Taxonomy 提取: 检测"X 是一种/属于/继承自 Y"模式
      命中 → 写 Taxonomy Node
```

#### 4.5.3 Knowledge 通道 A 与通道 B（精简）

保留双通道方案，但入口从 LTM 扫描改为**事件驱动**：

```
通道 A: 规则抽取（确定性，0 成本）
  适用模式:
    Triple:  "X 是 Y" / "X 属于 Y" / "X 基于 Y" / "X 包含 Y" / "X 的 Y 是 Z" / "X 用 Y"
    Property: KV 键值对（主语+是/住/在/喜欢+宾语）
    Taxonomy: "X 是一种 Y" / "X 继承自 Y"
  提取后: 直接写入 Knowledge，confidence=1.0

通道 B: LLM 抽取（异步，不阻塞主流程）
  触发: Publishing Event → Knowledge Worker 消费
  效果: 批量 LLM 抽取 → 写入 Knowledge，confidence=0.7
```

#### 4.5.4 Knowledge Worker：事件驱动（替代扫描 LTM）

**当前方案的问题**：BackgroundConceptWorker 通过定时扫描 `concept_pending=true` 的 LTM 记录来触发批量处理。这种"拉"模式有以下问题：

1. 与 LTM 耦合——Knowledge Worker 需要理解 LTM 的数据结构
2. 定时轮询有延迟——概念可能等待 2 分钟才被处理
3. 无法独立扩展——Worker 必须依附于 Pipeline 生命周期

**改进：Event Queue 模式**：

```
MemoryUpdater
  │
  ├─ Triple 提取命中 / Property 提取命中 / Taxonomy 提取命中
  │    → Publish Event: "ConceptExtractedEvent(entity=Redis, type=triple, ...)"
  │
  └─ 通道 A 未命中但检测到概念信号
       → Publish Event: "ConceptPendingEvent(text=..., keywords=[...])"

        │
        ▼
  Knowledge Queue (in-process / Redis Stream / Kafka)
        │
        ▼
  Knowledge Worker（独立进程/协程）
    ├─ 直接消费 ConceptPendingEvent
    ├─ 无需扫描 LTM，无需理解 LTM schema
    └─ 批量 LLM 抽取 → 写 Knowledge
```

**触发策略**（保留，但切换到事件计数）：

```
Event 驱动:
  - 累积 ConceptPendingEvent ≥ 30 条 → 触发批量 LLM 抽取
  - 2 分钟 debounce（期间有新 event 则重置计时）

定时兜底:
  - 距上次处理 > 15 min → 强制执行（无论 event 数量）

Session 结束:
  - Pipeline.close() → 强制消费所有 pending events
  - pending ≥ 10 → 触发批量抽取
```

**优势**：
- Knowledge 与 Memory **完全解耦**——Knowledge Worker 不需要知道 LTM
- 支持独立部署——Knowledge Service 可以独立扩缩容
- 未来可以用 Kafka/Redis Stream 替换内存队列，零代码改动

### 4.6 分流后合并去重

**LongTerm 去重与更新**：

```
写入 LongTerm 前 → 查 memories 表中 type="long_term" 的同实体记录

类别为 Fact:
  entity_key 严格匹配 → 同一实体
    ├─ 有且值相同 → 跳过
    ├─ 有但值不同 → 更新: version+1, history.push(旧值)
    └─ 无 → 新增（version=1）

类别为 Summary:
  embedding 相似度 > 0.9 → 视为重复
    ├─ 重复 → 跳过（或合并摘要内容）
    └─ 新 → 新增
```

**实体键（entity_key）设计**：用于 Fact 类别区分不同实体的同一属性：

```
entity_key 格式: {实体类型}.{属性名}.{实体标识}

示例:
  "我叫小明"   → entity_key="user.name"         value="小明"
  "我叫张三"   → entity_key="user.name"         value="张三"  ← 同一键，更新
  "小红叫李四" → entity_key="person.小红.name"  value="李四"  ← 不同键，新增
```

**Experience 去重**：
```
写入 Experience 前 → 查同 user + 相似内容的最近 N 条
  ├─ embedding sim > 0.9 且 tags 高度重叠 → 合并（合并 tags, lesson, steps）
  ├─ embedding sim > 0.9 但 tags 差异大 → 新增（不同维度的经历）
  └─ sim < 0.9 → 新增
```

**Knowledge 去重**：
```
写入 Knowledge 前 → 按节点类型分别去重:
  Triple: (subject, relation, object) 三元组去重 → 合并 attributes
  Property: (entity, property_name) 去重 → 更新 value
  Document: embedding sim > 0.95 → 跳过
  Taxonomy: (name) 去重 → 更新 parent / description
```

---

## 5. 写入触发时机

### 5.1 核心思路：Journal 作为 Write-Ahead Log

写入流程的新切入点不再是 Session 层，而是 **Journal（Write-Ahead Log）**——每轮自动追加，零门槛。Journal 是以下所有写入的"原材料"：

```
每轮 Pipeline 调用:
  │
  ├─ Working.push()       ← 纯内存，当前轮次
  ├─ Session.save()       ← 会话落地，Session 级 TTL
  │
  ├─ Journal.append()     ← Write-Ahead Log，零门槛
  │    │                    （存 raw input/output、实体提示、task context）
  │    │
  │    └─ Layer 1 规则必存 命中？
  │         │
  │         ├─ 是 → 立即通过 write_decision() → Memory Router → 持久化
  │         │       (显式指令 / KV 键值对 / 任务结论 — 不等待批量触发)
  │         │
  │         └─ 否 → 继续累积在 Journal（等待批量触发生效）
  │
  └─ Knowledge Event 发布（独立，每轮）
       │
       └─ 通道 A 命中 → 立即写入 Knowledge
          通道 A 未命中 → 发布 ConceptPendingEvent → Knowledge Queue
```

### 5.2 批量触发策略（三种）

当信息未命中 Layer 1 规则（非必存），它累积在 Journal 中。批量触发由以下三种条件之一驱动：

| 触发器 | 条件 | 说明 |
|-------|------|------|
| **窗口溢出** | Journal 中 pending 条目 ≥ 5 或 对话轮次 ≥ 10 | 核心触发，保证批量去重和聚合窗口不超过合理大小 |
| **对话关闭** | `Pipeline.close()` 调用或 session 退出 | 兜底触发，不丢任何待写入数据 |
| **定时器超时** | 距上次批量处理超过 5 分钟 | 保护机制，防止长对话无自然关闭 |

触发后的批量处理流程：

```
Journal pending 达到触发条件:
  │
  ├─ 1. 按 person/entity 分组
  │     Journal 中同实体的多条记录聚合，形成跨轮视图
  │
  ├─ 2. 批量执行 write_decision()
  │     Layer 2 新颖度过滤（跨 Journal 条目对比已存 LTM）
  │     Layer 3 重要性评分
  │
  ├─ 3. 通过 write_decision 的条目 → Memory Router
  │     ├─ LongTerm：去除 Journal 中的冗余，保留摘要 + 关键事实
  │     └─ Experience：保留完整的原始 episode 记录
  │
  ├─ 4. Knowledge Event 发布
  │     每条通过 write_decision 的条目同时发布 Knowledge Event
  │
  └─ 5. 标记 Journal 条目为 "processed"
        不删除 Journal 记录（保留为 audit log）
```

### 5.3 为什么用批量而非逐轮写入

| 对比维度 | 逐轮写入 | 窗口批量写入（Journal） |
|---------|---------|----------------------|
| 跨轮去重 | ❌ 无上下文 | ✅ Journal 窗口内可去重合并 |
| 冲突检测 | ❌ 无法感知后续更新 | ✅ 同一实体多次更新只保留最后 |
| 聚合能力 | ❌ 单条无关系 | ✅ 窗口内生成聚合摘要 |
| 写入次数 | N 次（N=轮次） | ~N/5 次 |
| 检索实时性 | ✅ 立即可查 | ⚠️ Journal 参与联合检索（见 7.2） |
| 审计追溯 | ❌ 写入后源数据丢失 | ✅ Journal 保留原始记录 |

### 5.4 Journal 与 Session 的边界

| 维度 | Session | Journal |
|------|---------|---------|
| **写入时机** | 每轮自动 | 每轮自动 |
| **目的** | 当前对话上下文，供 LLM 回答时引用 | 待持久化的候选原料，供 write_decision 处理 |
| **检索** | 按 session_id + 时间排序 | 按 status + entity 分组 |
| **生命周期** | Session 结束 TTL 过期 | 处理后不删除（标记 processed），保留完整的 audit trail |
| **表** | `memories` (type="session") | `journal` (独立表，见第 6 章) |

---

## 6. Journal 设计（Write-Ahead Log）

### 6.1 设计动机：为什么需要独立的 Journal

当前设计中，Session 层混合了两种职责：
1. **会话上下文**：供 LLM 引用当前对话历史
2. **候选缓冲区**：暂存待持久化的信息（`status="pending"`）

这种耦合导致：Session TTL 过期后，pending 的记录也丢失了；Session 按时间排序，不利于按 entity 分组聚合。Journal 从 Session 中分离出来，专门承担 WAL 职责。

### 6.2 表结构

```sql
CREATE TABLE journal (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    round_id    INTEGER NOT NULL,          -- 第几轮对话
    raw_input   TEXT NOT NULL,             -- 原始输入（清洗后）
    raw_output  TEXT DEFAULT '',           -- LLM 原始回复
    entities    TEXT DEFAULT '{}',         -- JSON: {"person": "Alice", "amount": 8000}
    task_intent TEXT DEFAULT '',           -- 当前轮意图
    status      TEXT DEFAULT 'pending',    -- pending / processed / discarded
    category    TEXT DEFAULT '',           -- 处理后的分类（可选）：fact / summary / episode 等
    processed_at TEXT,                     -- 处理时间
    created_at  TEXT NOT NULL,
    metadata    TEXT DEFAULT '{}'          -- 扩展字段
);
```

### 6.3 Journal 写入（每轮自动，零门槛）

```python
# MemoryUpdater.update_from_task() 中
await journal.append(
    raw_input=task.raw_input,
    raw_output=task.response,
    entities=json.dumps(extract_entities(task)),  # 轻量实体提示
    task_intent=task.intent.value,
    round_id=self._round_count,
    session_id=self._session_id,
)
```

**为什么存 raw_input 和 raw_output？**
- 保留完整原始数据，Write Decision 和 Knowledge 抽取都从这里消费
- 事后可审计："这条 LTM 是从哪轮对话的什么输入产生的？"
- 数据恢复：如果 write_decision 出错，可从 Journal 重放

### 6.4 Journal 批量处理流程

```
Journal 触发批量处理（第 5 章条件命中）:
  │
  ├─ 1. SELECT * FROM journal WHERE status='pending' AND user_id=?
  │     ORDER BY round_id ASC LIMIT 50
  │
  ├─ 2. 按 entities 中的 person/entity 分组
  │     Alice: [收入8000(r3), 支出5999(r4), 收入300(r5), 支出200(r6)]
  │     Bob:   [交房租3000(r3), 报销200(r4), 年终奖20000(r5)]
  │
  ├─ 3. 聚合 → LongTerm Summary
  │     "Alice r3~r6 收支汇总: 8300 收入, 6499 支出" → LongTerm (category="summary")
  │     "Bob r3~r5 收支汇总: 20000 收入, 3200 支出"   → LongTerm (category="summary")
  │
  ├─ 4. 保留原始 → Experience
  │     每条 Journal 独立存为 Experience entry（多标签，保留完整原始上下文）
  │
  ├─ 5. Knowledge Event
  │     每条聚合结果发布 ConceptExtractedEvent / ConceptPendingEvent
  │
  └─ 6. 标记 Journal
        UPDATE journal SET status='processed', processed_at=NOW(),
        category='summary' WHERE id IN (...)
```

### 6.5 动态窗口大小

```
Journal 中同 entity 出现 ≥ 3 次 → 缩小窗口，提前触发批量（同一实体高频更新，尽快入库）
Journal 中 entity 分布均匀，全是低频独立条目 → 扩大窗口（没有可聚合的，等更多上下文）
```

### 6.6 Journal 清理策略

Journal 不无限增长。清理策略由 Maintenance Worker 执行：

| 策略 | 触发条件 | 操作 |
|------|---------|------|
| **时效清理** | 距 `created_at` > 30 天 | 删除（已处理完毕的原始记录不需要永久保留） |
| **容量清理** | Journal 总行数 > 10000 | 删除最早的 5000 条 processed 记录 |
| **精确保留** | 未处理（status=pending） | 永远不删，优先触发批量处理 |

```sql
-- Maintenance Worker 定期执行
DELETE FROM journal
WHERE status = 'processed'
  AND created_at < datetime('now', '-30 days')
ORDER BY created_at ASC
LIMIT 1000;  -- 分批删除，避免锁表
```

---

## 7. 检索增强：Retriever 统一检索引擎

### 7.1 问题：Builder 耦合了检索逻辑

当前 Builder 直接调用各 Memory 层的检索接口：

```python
# builder.py 当前逻辑 — Builder 承担了"检索"的全部职责
self.long_term_memory.retrieve(query, top_k=25)
self.session_memory.query(query, top_k=10)
self.experience_memory.recall_relevant(query, top_k=5)
# 然后 Builder 自己做 merge_and_rank
```

这导致：
- Builder 需要了解每个 Memory 层的检索 API（耦合）
- 新增一个 Memory 层 → Builder 必须改代码
- merge/rank 逻辑分散在 Builder 中，无法独立测试和优化

### 7.2 方案：Retriever 从 Builder 中分离

**Retriever 是独立的检索引擎**，负责 Search → Merge → Rank。Builder 只声明"我需要什么"，不关心"怎么搜、从哪搜"。

```
改造前:
  Builder → LTM.retrieve() + Session.query() + Experience.recall() → merge_and_rank()

改造后:
  Builder → Retriever.retrieve(query, sources, top_k)
            │
            ├─ 1. Search: 并发调 LTM / Session / Experience / Knowledge / Journal
            ├─ 2. Merge: 按 source_weight 合并
            ├─ 3. Rank:  统一评分公式排序
            └─ 4. Return: top-k 结果
```

**Retriever 接口设计**：

```python
class UnifiedRetriever:
    """统一检索引擎。负责 Search → Merge → Rank。"""

    async def retrieve(
        self,
        query: str,
        sources: list[str] | None = None,  # 默认全源: ["ltm", "session", "experience", "knowledge", "journal"]
        top_k: int = 25,
        expand_history: bool = False,
    ) -> list[MemoryItem]:
        ...
```

### 7.3 多源检索流程

```
Retriever.retrieve(query, top_k=25):
  │
  ├─ 1. 并发发起 5 路异步检索
  │
  │    ┌─ LTM.retrieve(query, top_k=25)
  │    │    ├─ 语义向量检索 (embedding cosine)
  │    │    ├─ BM25 关键词检索 (TF-IDF token 级)
  │    │    └─ 统一评分公式计算 (见 8.3)
  │    │    └─ expand_history（如果关键词命中）
  │    │
  │    ├─ Session.query(query, top_k=20)
  │    │    └─ 按 session_id + 时间排序，取最近的
  │    │
  │    ├─ Experience.recall_relevant(query, top_k=8)
  │    │    ├─ 按 tags 匹配（reflection / procedure / tool_usage）
  │    │    └─ 按语义相似度 + 时间衰减排序
  │    │
  │    ├─ Knowledge.query_graph(seed_concept, depth=2)
  │    │    ├─ 从查询中提取核心概念（第一个名词短语 / 实体）
  │    │    ├─ BFS 遍历关系图（max_depth=2）
  │    │    └─ 返回相关 Triple + Property 节点
  │    │
  │    └─ Journal.query_pending(query, top_k=10)
  │         └─ 查 status='pending' 的待处理条目（时效性高的新信息）
  │
  ├─ 2. 合并 & 去重
  │     ├─ 跨源重复检测: embedding similarity > 0.95 → 保留 source_weight 最高的源
  │     └─ 实体去重: 同 entity_key 的多条记录保留最新版本
  │
  ├─ 3. 统一排序
  │     final_score = unified_score × source_weight
  │     (unified_score 见 8.3, source_weight 见 7.4)
  │
  └─ 4. 截断返回 top_k
```

### 7.4 来源权重（Source Weight）

合并时每条结果按来源给予不同的权重加成：

```
source_weight = {
    "long_term":          1.0,   # LongTerm（事实/属性），直接影响准确性
    "journal_pending":    0.9,   # Journal pending（窗口内新信息，时效性高）
    "experience":         0.6,   # Experience（经历/工具），场景还原参考
    "knowledge":          0.4,   # Knowledge（概念关系），语义扩展
    "session":            0.3,   # Session（对话历史），通常由上下文直接引用
}
```

`final_score = unified_score × source_weight`，同类得分内按 final_score 排序。

### 7.5 时间回溯检索：展开历史旧值

**问题**：4.6 节的更新逻辑保留了历史旧值（`metadata.history`），但检索时只返回当前值。用户问"我原来叫什么"，LLM 只能看到 `{name: 张三, version: 3}`，不知道以前叫小明。

**方案**：Retriever 检索结果返回时，检测查询是否包含时间回溯意图，命中则展开 history。

```
检测规则（关键词命中）:
  "原来" / "以前" / "之前" / "曾经" / "过去" / "历史" / "改名" / "变更" / "最早"

未命中 → 正常返回:
  {key: "user.name", value: "张三", version: 3}

命中 → 展开 history:
  {key: "user.name", current: "张三", version: 3,
   history: [
     {value: "小明", version: 1, updated_at: "2026-01-01"},
     {value: "李四", version: 2, updated_at: "2026-03-15"}
   ]}
```

**展开时 token 控制**：history 条目超过 5 条时，只保留最早 + 最近 3 条，中间省略。避免一个频繁更新的字段（如余额）撑爆上下文。

**Retriever 在展开时的职责**：在 `LTM.retrieve()` 返回后（步骤 1），Retriever 对每个 LongTerm 条目检测查询关键词 → 标记 `expand_history=True` → 展开 metadata.history → 将展开后的版本放入合并排序。

**与 Layer 2 实体对比的关联**：

```
写入时（4.6）:  entity + value 对比 → 判定更新 → version+1, history.push(旧值)
检索时（7.5）:  查询含时间回溯词 → expand_history → 返回完整版本链
```

两条逻辑配套：写入端保证 history 完整，检索端按需展开。

---

## 8. 统一评分公式

### 8.1 当前问题：两套公式先后评分

pipeline 中一条记忆被评分两次，两个公式的时间衰减相差 69 倍：

| | `LTM.retrieve()` | `RelevanceRanker.rank_memories()` |
|---|---|---|
| **阶段** | Builder 检索时 | Optimizer 重排序时 |
| **公式** | `0.30×semantic + 0.30×bm25 + 0.15×relevance + 0.15×time + 0.10×access` | `0.50×semantic + 0.30×time + 0.20×access` |
| **时间衰减** | `exp(-0.01 × days)`，半衰期 **69 天** | `exp(-hours / 24)`，半衰期 **24 小时** |
| **BM25** | ✅ 有（词频匹配） | ❌ 无 |

**后果**：Builder 按 69 天半衰期排序取 top-25；Optimizer 按 24 小时半衰期重排——两天前的记忆在 Builder 端还有 97% 权重，到 Optimizer 直接降到 12%。同一条记忆的排序结果不可预测。

### 8.2 方案：合并为单一公式，取消二次排序

**核心原则**：检索即排序。Retriever 是唯一做语义检索+评分的入口，Optimizer 不再对记忆做重新评分，只做简单的整理（去重、分组、截断）。

```
改造前:
  Builder.retrieve() → 评分公式 A → top-25
  Optimizer.rank()   → 评分公式 B → top-20
  → 一条记忆经历两套不兼容的打分

改造后:
  Retriever.retrieve() → 统一评分公式 → top-25
  Optimizer            → 去重 + 分组 + 截断（不重打分）
  → 一条记忆只打一次分，排序逻辑唯一
```

### 8.3 统一公式（含 Source Reliability）

在合并两个旧公式的基础上，新增 **source_reliability 维度**——回答"这条记忆的数据来源有多可靠？"：

```
score = 0.35 × semantic_similarity
      + 0.20 × bm25_score
      + 0.15 × source_reliability
      + 0.10 × time_decay
      + 0.10 × relevance_boost
      + 0.10 × access_frequency
```

| 维度 | 权重 | 计算方式 | 说明 |
|------|------|---------|------|
| **semantic_similarity** | 0.35 | cosine(vector_query, vector_item) | 原是 0.30 / 0.50 分裂值 |
| **bm25_score** | 0.20 | 标准 BM25（k1=1.5, b=0.75），token 级 TF-IDF | 原是 0.30，只在 LTM 侧有 |
| **source_reliability** | 0.15 | 按来源分级（见 8.3.1） | **新增**，防止低质量源污染检索结果 |
| **time_decay** | 0.10 | `exp(-t / 7_days)`，半衰期 **7 天** | 统一到 7 天（原是 69 天 / 1 天分裂） |
| **relevance_boost** | 0.10 | `item.relevance_score`，通过 `update_relevance()` 累加 | 原是 0.15 |
| **access_frequency** | 0.10 | `min(access_count / 10.0, 1.0)` | 原是 0.10 |

> ⚠️ 所有权重均为初始实验值，后续通过 A/B 测试和 reward 反馈信号调优。

### 8.3.1 Source Reliability 分级

每条记忆写入时附带 `metadata.source_reliability`，由写入端根据来源设定：

| 来源 | reliability | 说明 |
|------|------------|------|
| 用户显式陈述（"我住在北京"） | 1.0 | 直接来自用户，最高信任度 |
| 通道 A 规则抽取（KV 模式匹配） | 1.0 | 确定性规则，无误提取 |
| 用户隐式偏好（行为推断） | 0.8 | 如"连续 3 次选择深色模式" |
| 通道 B LLM 抽取（异步批量） | 0.7 | LLM 抽取，有概率误差 |
| 任务结论（LLM 推断结果） | 0.6 | 如"余额=7101元"（从对话推算） |
| Journal pending（未处理） | 0.5 | 原始记录，尚未通过 write_decision |

**可靠性更新**：一条记忆被多次访问且从未被纠正 → 可靠性可以提升：

```
if access_count > 20 and no_correction_in_last_30_days:
    source_reliability = min(1.0, source_reliability + 0.1)
```

**修正信号检测**：当用户说"不对，不是北京，是上海"→ 旧记忆被纠正 → 更新 reliability=0.2（标记为"已被纠正"，几乎不被检索返回）。

### 8.3.2 时间衰减选择的依据

| 半衰期 | 适用场景 | 选择？ |
|--------|---------|--------|
| 1 天（旧 Ranker） | 极短记忆，适合 hot-reload 场景 | ❌ 太激进，两天前的有用信息被遗忘 |
| 7 天（新统一值） | 一般 Agent 交互的一个工作周期 | ✅ 平衡新鲜度和长期知识 |
| 69 天（旧 LTM） | 近乎永久记忆 | ❌ 太保守，垃圾数据几乎不衰减 |

**公式只在 Retriever 使用**。Optimizer 的职责变为：

```
Optimizer.optimize() 改造后:

  输入: UnifiedContext (含 Builder 已评分排序的 memories)
    │
    ├─ 1. 去重           ← 对 memories 做 embedding 重复检测，similarity>0.95 的只保留得分高的
    ├─ 2. 意图分组        ← 按 intent 聚类：同一 intent 的记忆放一起，避免上下文跳变
    ├─ 3. Compressor     ← 保留：压缩对话历史（LLM 摘要），超过 N 轮的对话转为摘要
    ├─ 4. Token Budget   ← 保留：计算各部分配额（identity/conv/env/memory/knowledge）
    └─ 5. 截断           ← token 预算超限时从后往前裁剪低分记忆

  输出: OptimizedContext
```

**关键边界**：
- Compressor 和 Token Budget 是 Optimizer 的原有职责，保留不动
- 去重和意图分组是新加的，替代原来的 RelevanceRanker 重排序
- 不涉及二次语义评分——评分布在 Builder 端完成，Optimizer 只做结构性整理

### 8.4 检索时多源合并的优先级

Builder 向 4 个源发起检索，合并时的权重（不是评分权重，是来源权重）：

```
merge_priority = {
    "long_term":          1.0,   # LongTerm（事实/属性），直接影响准确性
    "session_pending":    0.9,   # 候选区（Session 层的 pending 子集），时效性加分
    "experience":         0.6,   # Experience（经历/工具），场景还原参考
    "knowledge":          0.4,   # Knowledge（概念关系），语义扩展
}
```

`final_score = unified_score × source_weight`，同类得分内按 final_score 排序。

> **命名说明**："候选区"是 Session 层的子集（`status="pending"` 的记录），不是独立的记忆层。在检索代码中用 `session_memory.query_pending()` 访问，在合并优先级中标记为 `session_pending` 以区分 Session 层已完成的记录。

---

## 9. 实施方案

按操作顺序分五个阶段。核心原则：**先建新层，再迁旧层，最后删旧层**，保证每步可验证。

### 阶段一：新建统一 Experience 层

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1.1 | 设计 `experiences` 表 DDL（统一 episodes/reflections/procedures/tool_usage） | `store.py` |
| 1.2 | 实现 `ExperienceMemory` 类（含 4 种子类型的 CRUD） | 新建 `memory/experience.py` |
| 1.3 | 实现 tool_stats 实时聚合查询（替代单独的 `tool_stats` 表） | `memory/experience.py` |
| 1.4 | **依赖注入**：在 `Pipeline.__init__` 中初始化 `ExperienceMemory`，注入 `MemoryUpdater` 和 `ContextBuilder` | `entry.py` |
| 1.5 | 在 `MemoryUpdater.__init__` 中增加 `experience_memory` 参数，替换旧的 `episodic_memory` / `semantic_memory` | `feedback/memory_updater.py` |
| 1.6 | 编写测试 | `tests/test_memory/test_experience.py` |

**DI 注入路径**（阶段一就要做，否则后续阶段无法使用）：

```
Pipeline.__init__():
  self.experience_memory = ExperienceMemory(
      store=self.store, user_id=user_id
  )
  self.session_memory = SessionMemory(...)    # 重命名后的
  self.long_term_memory = LongTermMemory(...)
  self.knowledge_memory = SemanticMemory(...)  # 保持原名

  self.memory_updater = MemoryUpdater(
      working_memory=self.working_memory,
      session_memory=self.session_memory,       # 新参数
      long_term_memory=self.long_term_memory,
      experience_memory=self.experience_memory, # 新参数
      knowledge_memory=self.knowledge_memory,   # 新参数
  )
```

### 阶段二：合并冗余表到 memories

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 2.1 | `facts` 表字段迁移：`content`/`category`/`confidence`/`version`/`history` → `memories` 的 `metadata` JSON | `store.py`, `memory/long_term.py` |
| 2.2 | `task_records` 字段迁移：input/output/token/duration → `memories` 的 `metadata` JSON（`type="session"`） | `store.py`, `memory/short_term.py` |
| 2.3 | 重命名 ShortTermMemory → SessionMemory | `memory/short_term.py` → 重命名 |
| 2.4 | 编写数据迁移脚本（可选：从旧表迁移历史数据到新结构） | 新建 `scripts/migrate_memory.py` |

### 阶段三：实现统一写入决策

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 3.1 | 实现 `write_decision()` 统一入口（Layer 1/2/3） | `feedback/memory_updater.py` |
| 3.2 | 实现 `classify_and_route()` 分流逻辑（→ LTM/Experience/Knowledge） | `feedback/memory_updater.py` |
| 3.3 | **【高优先级】** 实现 Layer 2 新颖度过滤 + 实体值对比（小节 3.2）：高相似时提取 entity-value 对比，区分"更新"和"重复" | `feedback/memory_updater.py` + `memory/long_term.py` |
| 3.4 | 实现 Layer 3 综合评分 | 新建 `feedback/memory_importance.py` |
| 3.5 | **【高优先级】** 实现 Knowledge 三元组抽取（小节 4.4）：通道 A 规则抽取（同步）+ concept_pending 标记写入 | `feedback/memory_updater.py` + 新建 `feedback/triple_extractor.py` |
| 3.5b | 实现 `BackgroundConceptWorker`（小节 4.4）：事件驱动 + 2min debounce → pending ≥ 30 开始批量抽取 + 15min 定时兜底 + close() 强制刷新 | 新建 `feedback/concept_worker.py` |
| 3.5c | 在 `Pipeline.__init__` 中创建并启动 `BackgroundConceptWorker`，在 `close()` 中停止 | `entry.py` |
| 3.6 | 实现候选缓冲区写入（Session 层 `status="pending"`） | `feedback/memory_updater.py` + `memory/short_term.py` |
| 3.7 | 实现批量写入触发（窗口溢出 / 对话关闭 / 定时器） | `feedback/memory_updater.py` + `entry.py` |
| 3.8 | 实现 entity_key 归一化（小节 4.6）：Layer 1 KV 提取后，增加 entity 类型推断 → 生成 `{实体类型}.{属性}.{标识}` → 存入 metadata.entity_key | `feedback/memory_updater.py` |

### 阶段四：检索增强 + 评分统一

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 4.1 | 候选区联合检索接口 | `memory/short_term.py` |
| 4.2 | Experience recall 接口（按标签/场景/时间检索） | `memory/experience.py` |
| 4.3 | **【高优先级】** 统一评分公式（小节 8）：将统一的公式实现在 `LTM.retrieve()` 中，取消 `RelevanceRanker` 的二次评分，改为去重+分组+截断 | `memory/long_term.py` + `optimizer/ranker.py` |
| 4.4 | Builder 多源检索合并逻辑（含多源 source_weight 优先级） | `builder/builder.py` |
| 4.5 | 实现时间回溯检索（小节 7.4）：`LongTerm.retrieve()` 增加 `expand_history` 参数，Builder 合并阶段检测时间回溯关键词 → 展开 metadata.history | `memory/long_term.py` + `builder/builder.py` |

### 阶段五：清理旧代码

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 5.1 | 删除旧表 DDL（`facts`, `task_records`, `episodes`, `reflections`, `procedures`, `tool_experience`, `tool_stats`） | `store.py` |
| 5.2 | 删除旧类文件 | `memory/fact_memory.py`, `memory/task_memory.py`, `memory/episodic.py`, `memory/reflection_memory.py`, `memory/procedural_memory.py`, `memory/tool_experience_memory.py` |
| 5.3 | 清理 `core/models.py` 中旧 `MemoryType` 枚举 | `core/models.py` |
| 5.4 | 全量测试 + 回归 | `tests/`

---

## 10. 涉及文件清单

### 新增文件

| 文件路径 | 内容 |
|---------|------|
| `context_os/memory/experience.py` | Experience 统一记忆层（合并 episodes/reflections/procedures/tool_usage） |
| `context_os/feedback/memory_importance.py` | Layer 3 重要性评分模块 |
| `context_os/feedback/triple_extractor.py` | Knowledge 三元组抽取（通道 A 规则匹配） |
| `context_os/feedback/concept_worker.py` | 后台异步 worker：批量 LLM 抽取 concept_pending 中的三元组 |
| `scripts/migrate_memory.py` | 可选：旧表到新结构的数据迁移脚本 |
| `docs/LTM_WRITE_STRATEGY.md` | 本文档 |

### 修改文件

| 文件路径 | 改动范围 |
|---------|---------|
| `context_os/feedback/memory_updater.py` | **核心改造**：统一 `write_decision()` + `classify_and_route()` + 批量写入触发 |
| `context_os/memory/long_term.py` | 新增：新颖度检测、结构化事实存储（含 version + history） |
| `context_os/memory/short_term.py` | 重命名为 SessionMemory；新增：候选区 CRUD、联合查询接口 |
| `context_os/memory/store.py` | 新增 `experiences` 表 DDL；`memories` 表扩展 metadata；最终删除旧表 DDL |
| `context_os/builder/builder.py` | 多源检索合并逻辑 |
| `context_os/optimizer/ranker.py` | 统一评分公式适配新架构 |
| `context_os/entry.py` | `close()` 中触发批次写入；初始化 Experience 层 |
| `context_os/core/models.py` | 更新 `MemoryType` 枚举（5 层）；新增 `ExperienceType` 枚举 |

### 删除文件

| 文件路径 | 说明 |
|---------|------|
| `context_os/memory/fact_memory.py` | 并入 LongTerm 的 metadata |
| `context_os/memory/task_memory.py` | 并入 Session 的 metadata |
| `context_os/memory/episodic.py` | 并入 Experience |
| `context_os/memory/reflection_memory.py` | 并入 Experience |
| `context_os/memory/procedural_memory.py` | 并入 Experience |
| `context_os/memory/tool_experience_memory.py` | 并入 Experience |
