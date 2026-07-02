# Context-OS 记忆系统架构

## 一、整体架构总览

Context-OS 采用类似人脑认知科学设计，7+1 记忆子系统架构，包含：

```
                    Memory Manager (统一门面)
                          │
        ┌──────────────────┼──────────────────┐
        │              │                  │
        ▼              ▼                  ▼
   Working Memory    Long-Term Index
                              │
                              └── 融合检索
        ├──────────────────────────────────┤
        │
        ▼              ▼                  ▼
   Conversation     Episodic       Semantic
   Memory       Memory       Memory
                             │
        ├──────────────────────────────────┤
        │
        ▼              ▼                  ▼
   Fact        Learned
   Memory      Behavior     Long-Term
               Memory       Memory
```

**生命周期总览：

```
Understand → Collect → Build → Optimize → Execute → Learn
```

整个 Context 在系统中不断演化，而不是一次性的 Prompt。

---

## 二、记忆子系统详解

### 1. Working Memory（工作记忆）
当前会话的即时记忆，用于实时存储本次交互的所有即时上下文。类似于人类的工作记忆，是短期存储容量有限（Token 环形缓冲区，8K Token 上限。

### 2. Conversation Memory（对话记忆）
当前 Session 的对话历史，带 TTL（默认 24 小时过期，按会话结束后可以选择性归档。

### 3. Episodic Memory（情节记忆）
按事件/任务级别的长期情节记忆，永久保存，可通过向量召回，记录完整的任务经验。

### 4. Semantic Memory（语义记忆）
知识图谱（Concept-Relation-Concept），存储结构化的领域知识。

### 5. Fact Memory（事实记忆）
结构化的键值对（Key-Value）事实存储，支持：
- 版本化：所有更新历史
- 冲突检测与解决
- 置信度管理
- 状态机管理（Active / Superseded / Archived）

### 6. Learned Behavior Memory（行为记忆）
用户行为模式，通过多次观察学习固化的用户偏好和行为模式。

### 7. Long-Term Memory（长期记忆）
通用向量存储，包含所有类型记忆的永久存储，包含：
- 全文检索
- 向量相似度检索
- 时间衰减管理

### 8. Long-Term Index（全局检索层）
7+1 架构的最后一层，全局检索融合层，同时检索：
- LTM（权重 0.9
- Episodic（权重 0.8）
- Semantic（权重 0.85）
按融合去重后返回 TopK 结果。

---

## 三、存储架构

所有记忆统一存储在 SQLite 中，按 `type` 字段区分类型：

| 类型 | 表存储方式 | 元数据 |
|------|-----------|--------|
| fact | JSON history 字段 | fact_type, current_value, history[] (JSON), confidence, fact_status, source, created_at, updated_at |
| conversation | 按会话存储 | role, session_id, turn, timestamp |
| episodic | 独立表 | scene, action, result, feedback, tags[] |
| semantic | 独立的 nodes/edges 表 | 知识图谱节点与边 |
| learned_behavior | JSON 行为记录 | behavior_type, behavior_key, confidence, observation_count |
| archived | 标记 archived=true, 压缩内容 | 归档记忆 |

---

## 四、记忆入库流程

记忆入库的完整流程如下：

```
用户输入
   │
   ▼
Memory Extraction Engine
   │
   ├─ Rule Engine（毫秒级快速路径
   │   └─ 26+ 条规则直接命中
   │
   └─ LLM Extractor（兜底）
   │
   ▼
Fact Validator → 校验
   │
   ▼
Conflict Checker → 与已有事实比较
   │
   ▼
Fact Updater → Fact Memory
   │
   ├─ type 已存在 → UPDATE（保留历史版本）
   └─ type 不存在 → CREATE
```

**记忆入库决策：重要性评分引擎（RuleScorer / SemanticScorer / NoveltyScorer / GoalRelationScorer）决定存储到哪一层。

---

## 五、记忆更新机制

### 5.1 Fact 记忆更新
- 支持增量式更新：保留历史版本链
- 冲突检测：识别矛盾事实提醒
- 置信度衰减：长时间未访问的事实自动衰减

### 5.2 其他记忆更新
- Conversation：持续追加对话
- Episodic：记录事件
- Semantic：知识图谱演化
- LearnedBehavior：多次观察后合并

### 5.3 知识进化
Knowledge Evolution 模块负责知识图谱的长期演化。

---

## 六、记忆遗忘生命周期

```
      新增
        │
        │
   ┌───┴────┐
   │        │
   │  30 天 │
   │        │
   │   归档  │
   │        │
   └───┬────┘
        │
        │
   ┌───┴────┐
   │        │
   │  90 天 │
   │        │
   │  永久  │
   │  删除  │
   └────────┘
```

**生命周期规则：**
- **30 天**：未被访问的记忆自动归档，内容压缩为 "[Archived] 前 60 字符
- **90 天**：未被访问的记忆永久删除，不可恢复

**后台任务：`MemoryLifecycle.runMaintenance() 每小时执行一次维护。

---

## 七、记忆检索流程

```
用户查询
   │
   ▼
Retrieval Planner（按意图调整各源权重）
   │
   ▼
Long-Term Index
   │
   ├─ 并行检索 LTM / Episodic / Semantic
   │
   ▼
Relevance Ranking（相关性排序
   │
   ▼
Token Budget Allocation（Token 预算分配）
   │
   ▼
返回 TopK 结果
```

**检索策略：**
- 闲聊类：少记忆，多对话
- 知识类：多记忆（LTM+Semantic），少对话
- 操作类：多工具，少记忆

---

## 八、与 Pipeline 集成位置

记忆系统是整个 Context-OS 中的完整集成：

```
                User Request
                     │
                     ▼
          ① Intent Understanding
                     │
                     ▼
          ② Context Orchestrator
                     │
                     ▼
          ③ Context Collection
                     │
                     ▼
           ④ Context Builder
                     │
                     ▼
          ⑤ Context Optimization
                     │
                     ▼
          ⑥ Context Packaging
                     │
                     ▼
                 LLM Inference
                     │
                     ▼
            Tool / Agent Execute
                     │
                     ▼
           ⑦ Context Feedback
                     │
                     └───────────────► Memory Update
```

---

## 九、评测基准

- MemoryOS-Bench 自定义评测体系覆盖：
- fact：事实提取准确性
- conversation：对话历史检索
- episodic：情节记忆召回
- semantic：知识图谱查询
- behavior：行为模式学习
- noise：噪声抗干扰

已接入学术基准 LongMemEval。

---

## 十、技术栈

- 核心语言：Java
- LLM 调用：DeepSeek / OpenAI / Claude 兼容
- 向量数据库：SQLite + Embedding Service
- 知识图谱：内嵌图结构（SemanticMemory）

---

## 路线图

### Phase 1 — 基础 Pipeline

- [x]  Intent Understanding 引擎
- [x]  Context Orchestrator 动态选择
- [x]  基础 Context Collection（Identity + Conversation）
- [x]  7 记忆子系统完整实现

### Phase 2 — 智能 Context 管理

- [x]  Context Builder 完整实现
- [x]  Context Optimizer（压缩 + 排序 + Token Budget）
- [x]  Context Packager 多模型适配

### Phase 3 — 记忆与知识

- [x]  Memory 长期记忆持久化
- [x]  知识图谱实现
- [ ]  RAG Knowledge 集成

### Phase 4 — 学习与进化

- [x]  MemoryLifecycle 30/90 天遗忘机制
- [ ]  Trace & Replay 系统
- [ ]  基于反馈的 Context 自优化
