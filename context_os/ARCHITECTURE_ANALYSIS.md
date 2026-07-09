# Context-OS 架构分析

> 项目路径：`d:\study\owencli\context_os`
>
> Context-OS 是一个为 AI Agent 设计的**上下文管理系统**，负责在 Agent 与 LLM 交互的全生命周期中完成意图理解、上下文收集、记忆管理、上下文优化、Prompt 打包、LLM 调用及反馈闭环。

---

## 1. 总体架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Context-OS System                           │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │  Intent   │→ │Orchestrator│→ │Collection │→ │      Builder     │   │
│  │ Layer     │  │          │  │ Layer     │  │  (ContextBuilder) │   │
│  └──────────┘  └──────────┘  └──────────┘  └────────┬─────────┘   │
│                                                      │              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │              │
│  │ Feedback  │← │   LLM    │← │ Packager │←───────────┘              │
│  │ Layer     │  │  Client  │  │          │                           │
│  └──────────┘  └──────────┘  └──────────┘                           │
│                                                      │              │
│  ┌───────────────────────────────────────────────────┘              │
│  ▼                                                                  │
│  ┌──────────┐                                                       │
│  │ Optimizer │  (RelevanceRanker + ContextCompressor + Budget)      │
│  └──────────┘                                                       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                    Memory System                          │       │
│  │  Working │ ShortTerm │ LongTerm │ Episodic │ Semantic ...│       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                   SQLite Store (持久化层)                  │       │
│  └──────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 模块层次结构

```
context_os/
├── __init__.py              # 公共 API 导出
├── pipeline.py              # 主 Pipeline 编排入口（ContextOSPipeline）
├── config.yaml              # 配置文件（支持热加载）
│
├── core/                    # ── 核心基础层 ──
│   ├── base.py              #   抽象基类（BaseCollector/BaseMemoryStore/...）
│   ├── models.py            #   数据模型（Pydantic：TaskSpec/UnifiedContext/...）
│   ├── errors.py            #   异常定义
│   └── logger.py            #   统一日志工具
│
├── config/                  # ── 配置管理 ──
│   ├── app_config.py        #   分层配置数据类（AppConfig）
│   └── config_manager.py    #   配置管理器（mtime 热加载，环境变量替换）
│
├── intent/                  # ── 意图理解层 ──
│   ├── classifier.py        #   意图分类器（LLM / Regex 双模式）
│   ├── extractor.py         #   实体与参数提取器
│   └── parser.py            #   TaskSpec 解析器（组装分类+提取结果）
│
├── orchestrator/            # ── 编排层 ──
│   ├── selector.py          #   动态上下文选择器（按意图类型决定收集范围）
│   └── router.py            #   上下文路由器（ContextFlag → 数据源路由）
│
├── collection/              # ── 数据收集层 ──
│   ├── identity.py          #   用户身份信息收集
│   ├── conversation.py      #   对话历史收集（环形缓冲区）
│   └── environment.py       #   系统环境信息收集
│
├── memory/                  # ── 记忆系统 ──
│   ├── working.py           #   工作记忆（纯内存，令牌预算控制）
│   ├── short_term.py        #   短期记忆（Session 级，TTL 过期）
│   ├── long_term.py         #   长期记忆（跨 Session，Ebbinghaus 遗忘）
│   ├── episodic.py          #   情景记忆（场景-行动-结果链）
│   ├── semantic.py          #   语义记忆（知识图谱）
│   ├── fact_memory.py       #   事实记忆（版本化 KV 存储）
│   ├── procedural_memory.py #   流程记忆（工作流步骤模式）
│   ├── reflection_memory.py #   反思记忆（自我反思与经验教训）
│   ├── task_memory.py       #   任务执行记录
│   ├── tool_experience_memory.py # 工具调用经验追踪
│   ├── store.py             #   SQLite 存储层（统一持久化）
│   └── embedding/           #   嵌入向量提供者
│       ├── api_provider.py
│       ├── bm25_provider.py
│       ├── char_ngram_provider.py
│       └── ollama_provider.py
│
├── builder/                 # ── 上下文构建 ──
│   ├── builder.py           #   ContextBuilder（编排收集+检索+合并）
│   └── merger.py            #   ContextMerger（合并/归一化/去重）
│
├── optimizer/               # ── 上下文优化 ──
│   ├── ranker.py            #   相关性排序器（语义+时间+频率）
│   ├── compressor.py        #   上下文压缩器（摘要/截断）
│   ├── budget.py            #   Token 预算分配器
│   ├── optimizer.py         #   ContextOptimizer 编排入口
│   └── layout/              #   Prompt 布局优化
│
├── packager/                # ── Prompt 打包 ──
│   ├── packager.py          #   ContextPackager 编排入口
│   └── adapters/            #   LLM Provider 适配器
│       ├── base.py          #     BasePromptAdapter
│       ├── claude.py        #     Claude XML 格式
│       ├── openai.py        #     OpenAI/DeepSeek 纯文本格式
│       └── registry.py      #     适配器注册中心
│
├── llm/                     # ── LLM 客户端 ──
│   ├── client.py            #   BaseLLMClient 重导出
│   ├── anthropic_client.py  #   Anthropic Claude 客户端
│   ├── openai_client.py     #   OpenAI 客户端
│   └── deepseek_client.py   #   DeepSeek 客户端（OpenAI 兼容接口）
│
├── feedback/                # ── 反馈与评估层 ──
│   ├── evaluator.py         #   质量评估器（答案质量/幻觉/成本）
│   ├── tracer.py            #   执行轨迹记录器（JSON 文件）
│   ├── memory_updater.py    #   记忆更新器（自动写入各层记忆）
│   └── extraction/          #   事实提取
│
├── pipeline/                # ── Middleware 式 Pipeline 引擎 ──
│   ├── middleware.py         #   PipelineMiddleware 抽象接口
│   ├── context.py           #   PipelineContext（中间件间传递状态）
│   ├── engine.py            #   PipelineEngine（顺序执行 Middleware Chain）
│   ├── event_bus.py         #   PipelineEventBus（阶段事件发布/订阅）
│   └── middlewares/          #   具体中间件实现
│       ├── intent_middleware.py
│       ├── build_middleware.py
│       ├── optimize_middleware.py
│       ├── package_middleware.py
│       ├── llm_middleware.py
│       ├── feedback_middleware.py
│       ├── policy_middleware.py
│       └── reflect_middleware.py
│
├── store/                   # ── 存储会话管理 ──
│   ├── provider.py          #   StoreProvider
│   └── session.py           #   StoreSession
│
├── policy/                  # ── 上下文策略 ──
├── lifecycle/               # ── 记忆生命周期 ──
├── evolution/               # ── 知识演进 ──
├── agent/                   # ── Agent 层 ──
│
└── scripts/                 # ── 运行脚本 ──
    ├── p0.ps1
    ├── py_p0_1_memory.ps1
    └── task_memory.ps1
```

---

## 3. 核心数据流：Pipeline 六步执行

> 主入口：[context_os/pipeline.py](file:///d:/study/owencli/context_os/pipeline.py) — `ContextOSPipeline.run(user_input)`

```
User Input
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 1: 意图理解 (Intent Understanding)                              │
│  ├── IntentClassifier.classify() → (IntentType, GoalType, confidence)│
│  ├── EntityExtractor.extract_entities() → 命名实体列表               │
│  └── TaskParser.parse() → TaskSpec (标准结构化任务描述)              │
├──────────────────────────────────────────────────────────────────────┤
│ Step 2: 上下文构建 (Context Building)                                │
│  ├── ContextSelector.select(task) → ContextFlag (按意图筛选收集维度)│
│  ├── ContextRouter.route(task, flags) → ContextRoute[]               │
│  ├── 并行调用: IdentityCollector + ConversationCollector +            │
│  │   EnvironmentCollector + LongTermMemory.retrieve()                │
│  └── ContextMerger.merge() + normalize() + deduplicate() →           │
│      UnifiedContext                                                  │
├──────────────────────────────────────────────────────────────────────┤
│ Step 3: 上下文优化 (Context Optimization)                            │
│  ├── RelevanceRanker.rank_memories() (语义+时间+频率三维排序)        │
│  ├── ContextCompressor.compress_conversation() (摘要/截断)           │
│  └── TokenBudgetAllocator.allocate() → TokenBudget                   │
├──────────────────────────────────────────────────────────────────────┤
│ Step 4: Prompt 打包 (Context Packaging)                              │
│  └── ContextPackager.pack() → 按 Provider 格式组装 Prompt            │
│      (Claude → XML 格式, OpenAI → 纯文本分段格式)                   │
├──────────────────────────────────────────────────────────────────────┤
│ Step 5: LLM 推理 (LLM Inference)                                    │
│  └── BaseLLMClient.complete(packaged.raw_prompt) → LLM Response     │
├──────────────────────────────────────────────────────────────────────┤
│ Step 6: 反馈闭环 (Feedback)                                          │
│  ├── QualityEvaluator.evaluate() → EvalMetrics (质量/成本/成功率)    │
│  ├── MemoryUpdater.update_from_task() → 写入 5 层记忆                │
│  └── Tracer.finish() → 轨迹持久化到 JSON                            │
└──────────────────────────────────────────────────────────────────────┘
    │
    ▼
Return: {response, metrics, trace_id, task_spec, latency_ms}
```

### 3.1 两种 Pipeline 实现

| 实现 | 文件 | 特点 |
|------|------|------|
| **ContextOSPipeline** | [pipeline.py](file:///d:/study/owencli/context_os/pipeline.py) | 单体编排，六步硬编码，依赖直接注入，日志详细 |
| **PipelineEngine** | [pipeline/middleware/](file:///d:/study/owencli/context_os/pipeline/engine.py) | Middleware Chain 模式，可插拔，事件驱动，更灵活 |

`ContextOSPipeline` 是面向用户的直接入口，`PipelineEngine` 是更工程化的设计，支持通过配置动态启用/禁用中间件。

---

## 4. 记忆系统架构（核心亮点）

记忆系统是 Context-OS 最核心的模块，采用**分层记忆架构**，参考了认知科学中的记忆模型。

```
                      ┌─────────────────────┐
                      │   Working Memory     │ ← 纯内存，Token 预算控制
                      │  (当前会话活跃区)    │   → 自动淘汰最早条目
                      └──────────┬──────────┘
                                 │ 注意力机制
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Short-Term Memory                              │
│  (Session 级，SQLite 持久化，TTL=24h)                              │
│  ├── 用户偏好 (preferences)                                         │
│  ├── 子任务完成记录 (tasks)                                          │
│  └── 错误与恢复记录 (errors)                                         │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Long-Term Memory                               │
│  (跨 Session，Ebbinghaus 遗忘曲线自动清理)                          │
│  ├── 用户长期偏好 / 项目上下文 / 决策记录                            │
│  ├── 检索策略: 向量相似度 → 关键词全文 → 时间衰减                    │
│  └── consolidate() 去重 + forget() 清理低价值记忆                    │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Episodic Memory     │    Semantic Memory (知识图谱)                 │
│  (场景-行动-结果链)   │    (Concept → Relation → Concept)           │
│  ├── record_success() │    ├── add_concept() + add_relation()        │
│  ├── record_failure() │    ├── query(BFS 子图遍历)                  │
│  └── recall_similar() │    ├── find_shortest_path()                 │
│                       │    └── abstract_from_episodes() 自动抽象    │
└─────────────────────────────────────────────────────────────────────┘

此外还有：
  FactMemory          — 版本化事实 KV 存储（支持历史版本追溯）
  ProceduralMemory    — 流程步骤模式存储（附带成功率统计）
  ReflectionMemory    — Agent 自我反思记录（根因/经验/预防措施）
  TaskMemory          — 任务执行记录（状态/耗时/Token 用量）
  ToolExperienceMemory— 工具调用经验（成功率/平均耗时统计）
```

### 4.1 记忆写入策略（MemoryUpdater）

写入策略定义于 [memory_updater.py](file:///d:/study/owencli/context_os/feedback/memory_updater.py)：

| 记忆层级 | 写入条件 | 内容 |
|----------|---------|------|
| Working | 每次执行 | 用户输入 + LLM 回复 |
| ShortTerm | 每次执行 | 任务完成记录 |
| LongTerm | reward_score ≥ 0.7 | 高质量问答对 |
| Episodic | 总是 | success/failure 经验 |
| Semantic | 批量抽象 | 从高频 Episodic 标签提炼概念 |

### 4.2 记忆检索排序算法（RelevanceRanker）

定义于 [ranker.py](file:///d:/study/owencli/context_os/optimizer/ranker.py)：

```
score = 0.5 × 语义相似度(cosine) + 0.3 × 时间衰减(exp) + 0.2 × 访问频率(log)
```

- 语义相似度：余弦相似度，需配合 Embedding 服务
- 时间衰减：指数衰减，半衰期 24 小时
- 访问频率：`log1p(access_count) / 10`

### 4.3 持久化层（SQLiteStore）

定义于 [store.py](file:///d:/study/owencli/context_os/memory/store.py)：

```
数据库: context_os.db
├── memories          # 通用记忆表（所有记忆类型的统一存储）
├── episodes          # 情景记忆表（scene/action/result/feedback）
├── concepts          # 语义记忆概念节点（知识图谱）
├── concept_relations # 语义记忆概念关系（有向边）
```

- 使用 `aiosqlite` 异步驱动
- WAL 模式提升并发性能
- 有 JSON 文件降级存储方案（SQLite 不可用时自动 fallback）

---

## 5. LLM 集成层

| 客户端 | 文件 | 模型 | 备注 |
|--------|------|------|------|
| `AnthropicClient` | [anthropic_client.py](file:///d:/study/owencli/context_os/llm/anthropic_client.py) | claude-sonnet-4-20250514 | Anthropic SDK |
| `OpenAIClient` | [openai_client.py](file:///d:/study/owencli/context_os/llm/openai_client.py) | gpt-4o | OpenAI SDK |
| `DeepSeekClient` | [deepseek_client.py](file:///d:/study/owencli/context_os/llm/deepseek_client.py) | deepseek-chat | OpenAI 兼容接口 |

所有客户端统一实现 `BaseLLMClient.complete()` 接口，支持：
- `prompt` / `system` / `max_tokens` / `temperature`
- `response_format="json"` 自动解析 JSON 响应

### Prompt 适配器

| 适配器 | 目标 | 格式 |
|--------|------|------|
| `ClaudePromptAdapter` | Claude | XML 标签格式 (`<identity>`, `<memory>`, `<conversation>` 等) |
| `OpenAIPromptAdapter` | OpenAI / DeepSeek | 纯文本分段格式 (`[Identity]`, `[Memory]`, `[Conversation]`) |

---

## 6. 配置系统

- **配置文件**：[config.yaml](file:///d:/study/owencli/context_os/config.yaml)
- **配置加载**：[ConfigManager](file:///d:/study/owencli/context_os/config/config_manager.py)
  - 支持 `mtime` 热加载（每 30s 检测）
  - 支持 `${VAR:default}` 环境变量替换
- **配置模型**：[AppConfig](file:///d:/study/owencli/context_os/config/app_config.py) 分层数据类

```yaml
context-os:
  pipeline:
    middlewares:        # Middleware 开关与排序
      - name: intent;   enabled: true;  order: 100
      - name: build;    enabled: true;  order: 300
      - name: optimize; enabled: true;  order: 400
      - name: package;  enabled: true;  order: 500
      - name: llm;      enabled: true;  order: 600
      - name: feedback; enabled: true;  order: 700
  llm:
    provider: deepseek
    api-key: ${DEEPSEEK_API_KEY:}
    model: deepseek-chat
  memory:
    working-memory: { max-tokens: 32000 }
    short-term:    { ttl-hours: 24 }
    long-term:     { max-items: 1000 }
  store:
    provider: sqlite
    db-path: ./data/context_os.db
```

---

## 7. 意图驱动的上下文选择机制

核心优化策略：**不是所有任务都需要全部上下文**。

定义于 [selector.py](file:///d:/study/owencli/context_os/orchestrator/selector.py)：

| 意图类型 | 收集的上下文 |
|---------|-------------|
| QA | CONVERSATION + MEMORY + KNOWLEDGE |
| CODING | IDENTITY + CONVERSATION + ENVIRONMENT + MEMORY + TOOLS |
| DEBUGGING | 全部（IDENTITY + CONVERSATION + ENVIRONMENT + MEMORY + KNOWLEDGE + TOOLS） |
| PLANNING | CONVERSATION + MEMORY + KNOWLEDGE |
| SEARCH | MEMORY + KNOWLEDGE |
| WORKFLOW | CONVERSATION + MEMORY + ENVIRONMENT + TOOLS |
| AGENT | 全部 |
| DATA_ANALYSIS | CONVERSATION + MEMORY + ENVIRONMENT + TOOLS |

当 Token 预算紧张（< 8000）时，自动裁减 MEMORY 和 ENVIRONMENT。

---

## 8. 错误处理

定义于 [errors.py](file:///d:/study/owencli/context_os/core/errors.py)：

```
ContextOSError          ← 所有异常的基类
├── ContextBuildError   ← 上下文构建失败
└── MemoryError         ← 记忆操作失败
```

Pipeline 中 `ContextBuildError` 和 `ContextOSError` 被显式捕获并记录，其他异常会被包装为 `ContextOSError` 抛出。

---

## 9. 质量评估与轨迹追踪

### 质量评估（QualityEvaluator）

评估维度：
| 指标 | 说明 |
|------|------|
| `answer_quality` | 答案质量（0-1），有 LLM 时调用 LLM 评分，否则基于规则 |
| `latency_ms` | LLM 调用延迟 |
| `cost_usd` | Token 成本估算（$3/M input） |
| `success` | 回复是否包含错误信号（error/unable/failed 等） |
| `reward_score` | 综合奖励分 = quality × (0.8 if success else 0.2) |

### 轨迹追踪（Tracer）

每次 Pipeline 执行生成一个 JSON 轨迹文件，存储在 `./data/traces/`，记录：
- 每个步骤的输入/输出预览
- 各步骤耗时
- 最终成功率

---

## 10. 设计模式总结

| 模式 | 使用场景 |
|------|---------|
| **策略模式** | IntentClassifier 的 LLM/Regex 双模式策略 |
| **适配器模式** | PromptAdapter（Claude/OpenAI/DeepSeek 统一接口） |
| **职责链模式** | PipelineEngine + Middleware Chain |
| **观察者模式** | PipelineEventBus 的事件发布/订阅 |
| **工厂模式** | AdapterRegistry 注册中心 |
| **备忘录模式** | Tracer 记录执行轨迹 |
| **组合模式** | ContextMerger 合并多个数据源 |
| **环形缓冲区** | ConversationCollector / WorkingMemory 的容量控制 |

---

## 11. 关键设计决策

1. **双 Pipeline 实现**：`ContextOSPipeline`（硬编码单体）面向简单使用，`PipelineEngine`（Middleware Chain）面向灵活编排
2. **意图驱动优化**：根据意图类型动态选择上下文收集范围，而非每次加载全部
3. **分层记忆**：5层记忆 + 5个扩展记忆，各有不同的生命周期和写入策略
4. **SQLite 优先**：统一使用 SQLite 持久化，去除 PostgreSQL 依赖，降低部署复杂度
5. **降级策略**：LLM 不可用时自动降级到规则引擎，SQLite 不可用时降级到 JSON 文件
6. **环境变量配置**：敏感信息（API Key）通过 `${VAR:default}` 从环境变量读取，不进代码仓库
7. **中文优先**：关键词规则和日志大量使用中文，面向中文开发者
