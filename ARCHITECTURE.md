# Context-OS 系统架构文档

> AI Agent Context 管理系统 — 管理 LLM 从接收到响应的全生命周期上下文

---

## 一、架构总览

Context-OS 采用 **Pipeline 编排模式**，将用户请求到 LLM 响应的全过程划分为 7 个阶段，数据单向流动并形成闭环反馈：

```
┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌──────────┐
│  ① Intent │ →  │  ② Context   │ →  │  ③ Context│ →  │  ④ Context│ →  │  ⑤ Context │ →  │  ⑥ LLM   │ →  │  ⑦ Feedback│
│ Under-    │    │ Orchestrator │    │ Collection│    │  Builder  │    │ Optimizer  │    │ Inference│    │ & Memory  │
│ standing  │    │              │    │           │    │           │    │            │    │          │    │  Update   │
└──────────┘    └──────────────┘    └──────────┘    └──────────┘    └────────────┘    └──────────┘    └──────────┘
                                                                                                           │
                                                                                                           ▼
                                                                                                    Memory Store
                                                                                                 (PostgreSQL)
```

**生命周期：**

```
Understand → Collect → Build → Optimize → Execute → Learn
```

Context 在系统中持续演化而非一次性 Prompt，每次交互的结果通过 Feedback 回流更新记忆，使 Agent 具备持续学习能力。

---

## 二、分层架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Pipeline 编排层                                    │
│                ContextOSPipeline.run() 串联全 7 个阶段                      │
├───────────────┬──────────────┬──────────────┬────────────────────────────┤
│  Intent       │ Orchestrator │ Collection   │ Builder                   │
├───────────────┴──────────────┴──────────────┴────────────────────────────┤
│  Optimizer                  │  Packager + Adapters      │  Feedback      │
├─────────────────────────────┴───────────────────────────┴────────────────┤
│                           Memory 系统                                     │
│     Working │ Short-Term │ Long-Term │ Episodic │ Semantic               │
├──────────────────────────────────────────────────────────────────────────┤
│                           存储层                                           │
│            PostgreSQL (主存) + ChromaDB/Qdrant (向量)                     │
├──────────────────────────────────────────────────────────────────────────┤
│                          LLM 抽象层                                       │
│                 BaseLLMClient → Anthropic / OpenAI / 扩展                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 三、模块详解

### 3.1 ① Intent Understanding — 意图理解

**文件：** `context_os/intent/`

**职责：** 将用户自然语言转换为结构化的任务描述（TaskSpec）。

**流程：**

```
User Input
    │
    ▼
IntentClassifier ────── 识别任务类型 (IntentType: QA / Coding / Debugging / Agent 等 8 种)
    │                   识别目标类型 (GoalType: Fix / Explain / Generate 等 7 种)
    ▼
EntityExtractor ──────── 提取实体 (Entity: cluster, namespace, pod 等)
    │                   推断工具需求 (ToolRequirement)
    ▼
TaskParser ───────────── 构建 TaskSpec（包含意图、目标、实体、约束、优先级、置信度）
    │
    ▼
TaskSpec ─────────────── 结构化任务描述，进入下一阶段
```

**核心类：**

| 类 | 职责 |
|---|---|
| `IntentClassifier` | 意图分类，支持 LLM 语义分类 + 关键词正则降级 |
| `EntityExtractor` | 实体/参数/工具/知识需求提取 |
| `TaskParser` | 整合分类器和提取器，输出 TaskSpec |

**关键设计：** 支持 LLM 模式和正则降级模式，无外部 LLM 依赖时仍可工作。

---

### 3.2 ② Context Orchestrator — 上下文编排

**文件：** `context_os/orchestrator/`

**职责：** 根据 TaskSpec 动态决定需要收集哪些维度的 Context，避免每次加载全部上下文。

**流程：**

```
TaskSpec
    │
    ▼
ContextSelector ──── 按意图类型映射为 ContextFlag 组合（位标志）
    │                QA → CONVERSATION + KNOWLEDGE
    │                CODING → IDENTITY + CONVERSATION + ENVIRONMENT + MEMORY + TOOLS
    │                DEBUGGING → 全部 6 种
    ▼
ContextRouter ────── 将 ContextFlag 转换为按优先级排序的路由列表
    │                (source + flag + priority)
    ▼
路由列表 ────────── 交付给 Builder 阶段执行
```

**核心类：**

| 类 | 职责 |
|---|---|
| `ContextSelector` | 基于 IntentType → ContextFlag 映射表选择所需上下文类型 |
| `ContextRouter` | 将 Flag 组合转换为有序的数据源路由列表 |

**关键设计：** 使用 `Flag` 枚举支持按位组合（如 `IDENTITY | CONVERSATION`），`TIGHT_TOKEN_THRESHOLD` 阈值触发低优先级裁切。

**意图 → Context 映射表：**

| 意图 | 所需上下文 |
|---|---|
| QA | CONVERSATION + KNOWLEDGE |
| CODING | IDENTITY + CONVERSATION + ENVIRONMENT + MEMORY + TOOLS |
| DEBUGGING | 全部 6 种 |
| PLANNING | CONVERSATION + MEMORY + KNOWLEDGE |
| SEARCH | KNOWLEDGE |
| WORKFLOW | CONVERSATION + ENVIRONMENT + TOOLS |
| AGENT | 全部 6 种 |
| DATA_ANALYSIS | CONVERSATION + ENVIRONMENT + TOOLS |

---

### 3.3 ③ Context Collection — 上下文收集

**文件：** `context_os/collection/`

**职责：** 从各数据源采集原始上下文数据。

**三个 Collector：**

```
┌─ IdentityCollector ─────── 用户身份信息 (UserProfile)
│                            user_id, role, permission, language, skill_level, tenant, team
│
├─ ConversationCollector ──── 当前对话历史 (ConversationContext)
│                            history, current_topic, current_step, status, task_graph
│
└─ EnvironmentCollector ──── 系统运行环境 (EnvironmentContext)
                             os, working_directory, git_branch, runtime, mcp_servers, env_vars
```

**核心类：**

| 类 | 职责 |
|---|---|
| `IdentityCollector` | 采集用户角色、权限、语言偏好等身份信息 |
| `ConversationCollector` | 管理多轮对话历史，记录每轮 turn |
| `EnvironmentCollector` | 采集 OS、工作目录、Git 分支、运行时环境等 |

**关键设计：** 每个 Collector 继承 `BaseCollector(ABC)`，实现 `async def collect() -> dict`，支持异步并行采集。

---

### 3.4 ④ Context Builder — 上下文构建

**文件：** `context_os/builder/`

**职责：** 将多源数据 + 多级记忆合并、归一化、去重，组装为 UnifiedContext。

**流程：**

```
TaskSpec
    │
    ▼
builder.build(task)
    │
    ├─ 1. selector.select(task) → flags
    ├─ 2. router.route(task, flags) → routes
    ├─ 3. 并行收集 (asyncio.gather)
    │       ├─ collectors (identity / conversation / environment)
    │       └─ memory.retrieve() (长期记忆检索)
    ├─ 4. merger.merge() → 合并多源数据
    ├─ 5. merger.normalize() → 归一化
    └─ 6. merger.deduplicate() → 去重
         │
         ▼
    UnifiedContext ──── 统一上下文，包含:
                        identity, conversation, environment,
                        memory[], knowledge[], tools[]
```

**核心类：**

| 类 | 职责 |
|---|---|
| `ContextBuilder` | 编排整个构建过程，协调 Selector/Router/Collector/Memory |
| `ContextMerger` | merge / normalize / deduplicate 三个核心方法 |

**关键设计：** 并行收集 + 异常隔离（单个 Collector 失败不阻塞整体流程），通过 `return_exceptions=True` 捕获异常并降级。

---

### 3.5 ⑤ Context Optimizer — 上下文优化

**文件：** `context_os/optimizer/`

**职责：** 在有限的 Token 窗口内最大化有效信息密度。

**流程：**

```
UnifiedContext + TaskSpec
    │
    ▼
RelevanceRanker ────── 1. 排序: 按相关性、时效性、优先级排序记忆和知识
    │                     记忆取 Top-10，知识取 Top-5
    ▼
ContextCompressor ──── 2. 压缩: 对过长内容做摘要压缩
    │                     支持 Summary / Hierarchy / Semantic 三种策略
    ▼
TokenBudgetAllocator ─ 3. 预算分配: 给系统指令、记忆、对话历史、
    │                     知识等各模块分配 Token 额度
    ▼
                      ── 4. 截断: 超出预算的部分进行裁剪
    │
    ▼
OptimizedContext ──── 优化后上下文:
                       compressed: bool
                       token_usage: TokenBudget
                       context: UnifiedContext
```

**核心类：**

| 类 | 职责 |
|---|---|
| `RelevanceRanker` | 按 `relevance_score` 排序记忆和知识 |
| `ContextCompressor` | Token 压缩，支持 LLM 摘要压缩和简单截断 |
| `TokenBudgetAllocator` | 动态分配各模块 Token 预算，防止超限 |
| `ContextOptimizer` | 编排以上三者 |

**关键设计：** Token Budget 量化各模块开销，智能裁切非核心内容，确保关键上下文不丢失。

---

### 3.6 ⑥ Packager + LLM — 模型适配与推理

**文件：** `context_os/packager/`、`context_os/llm/`

**职责：** 将统一上下文转换为各 LLM 特有的 Prompt 格式，调用 LLM 进行推理。

**流程：**

```
OptimizedContext
    │
    ▼
AdapterRegistry.get(provider) ── 根据 LLMProvider 选择适配器
    │
    ├─ ClaudePromptAdapter  ──── XML 格式: <identity> <memory> <conversation> ...
    │
    ├─ OpenAIPromptAdapter ───── JSON Messages 数组格式
    │
    └─ (预留) Gemini / Qwen / DeepSeek
         │
         ▼
    PackagedContext ──────────── raw_prompt + sections + metadata
         │
         ▼
    BaseLLMClient.complete() ─── LLM 推理
         │
         ▼
    LLM Response
```

**核心类：**

| 类 | 职责 |
|---|---|
| `BasePromptAdapter` (ABC) | 适配器抽象：`provider` + `pack(context) -> PackagedContext` |
| `ClaudePromptAdapter` | Claude XML 格式适配器 |
| `OpenAIPromptAdapter` | OpenAI Messages 数组格式适配器 |
| `AdapterRegistry` | 适配器注册中心，管理 Provider → Adapter 映射 |
| `ContextPackager` | 打包编排入口 |
| `BaseLLMClient` (ABC) | LLM 客户端抽象 |
| `AnthropicClient` / `OpenAIClient` | 各 Provider 的具体实现 |

**关键设计：** 通过 **Adapter 模式** 将统一上下文与模型特定格式解耦，新增模型只需实现一个 Adapter 并注册即可。

---

### 3.7 ⑦ Feedback & Memory — 反馈闭环

**文件：** `context_os/feedback/`、`context_os/memory/`

**职责：** 评估 LLM 输出质量，自动更新各层记忆，形成持续学习闭环。

**流程：**

```
LLM Response
    │
    ▼
QualityEvaluator ──── 评估输出质量、幻觉分数、工具调用准确率
    │
    ▼
MemoryUpdater ─────── 更新 5 层记忆
    │
    ├─ WorkingMemory    ── 当前会话短期上下文
    ├─ ShortTermMemory  ── 短时记忆（按 session 过期）
    ├─ LongTermMemory   ── 长期记忆（跨 session 持久化）
    ├─ EpisodicMemory   ── 情景记忆（具体操作 + 结果记录）
    └─ SemanticMemory   ── 语义记忆（概念/知识图谱）
    │
    ▼
Tracer ────────────── 全链路 Trace 记录 (每个步骤耗时、输入输出预览、Token 数)
    │
    ▼
Trace 数据 ────────── 完整的执行轨迹，用于调试和分析
```

**核心类：**

| 类 | 职责 |
|---|---|
| `QualityEvaluator` | 评估答案质量、幻觉、工具准确率 |
| `MemoryUpdater` | 协调更新 5 层记忆系统 |
| `Tracer` | 记录全链路 Trace 步骤和时间 |
| | |
| `WorkingMemory` | 当前会话的短期上下文 |
| `ShortTermMemory` | 短时记忆，按 session_id 隔离，支持过期 |
| `LongTermMemory` | 长期记忆，跨 session 持久化，按 user_id 关联 |
| `EpisodicMemory` | 情景记忆，记录 scene/action/result/feedback |
| `SemanticMemory` | 语义记忆，存储概念关系和知识图谱 |
| `PostgresStore` | 统一存储层，管理连接池、自动建表、CRUD |

**关键设计：** 5 层记忆按时间跨度和抽象粒度逐层递增，Working → Short-Term → Long-Term 按会话生命周期管理，Episodic → Semantic 从具体到抽象。

**PostgreSQL 表结构：**

```
memories        ─── 统一记忆主表 (id, type, content, embedding, session_id, user_id, ...)
episodes        ─── 情景记忆表 (id, scene, action, result, feedback, tags, ...)
memory_embeddings ─ 向量索引表 (需 pgvector 插件)
concepts        ─── 语义记忆表 (知识图谱节点)
```

---

## 四、核心数据模型

**文件：** `context_os/core/models.py`

所有数据模型基于 **Pydantic BaseModel 2.0**，统一在 `models.py` 中定义。

### 枚举

| 枚举 | 取值 |
|---|---|
| `IntentType` | qa, coding, planning, debugging, search, workflow, agent, data_analysis |
| `GoalType` | fix, explain, generate, summarize, compare, refactor, optimize |
| `MemoryType` | working, short_term, long_term, episodic, semantic |
| `PriorityLevel` | low, medium, high, critical |
| `LLMProvider` | claude, openai, gemini, qwen, deepseek |

### 核心模型链

```
TaskSpec (意图理解输出)
    │
    ▼
UnifiedContext (上下文构建输出)
    ├── identity: UserProfile
    ├── conversation: ConversationContext
    ├── environment: EnvironmentContext
    ├── memory: MemoryItem[]
    ├── knowledge: KnowledgeChunk[]
    └── tools: ToolContext[]
    │
    ▼
OptimizedContext (优化后)
    ├── compressed: bool
    ├── token_usage: TokenBudget
    └── context: UnifiedContext
    │
    ▼
PackagedContext (打包后)
    ├── provider: LLMProvider
    ├── raw_prompt: str
    ├── sections: Dict[str, str]
    └── metadata: Dict[str, Any]
    │
    ▼
Trace (全链路轨迹)
    ├── steps: TraceStep[]
    ├── total_latency_ms
    ├── total_tokens
    └── success: bool

EvalMetrics (评估指标)
    ├── answer_quality
    ├── hallucination_score
    ├── tool_accuracy
    ├── latency_ms
    ├── cost_usd
    └── reward_score
```

---

## 五、Pipeline 主入口

**文件：** `context_os/pipeline.py`

**类：** `ContextOSPipeline`

### 初始化

```python
pipeline = ContextOSPipeline(
    llm_client=my_client,       # BaseLLMClient 实现
    provider=LLMProvider.CLAUDE, # 目标 LLM
    pg_dsn="postgresql://...",   # PostgreSQL 连接串（可选）
    session_id="...",            # Session ID（可选，自动生成）
    user_id="alice",             # 用户标识
)

result = await pipeline.run("帮我分析 K8s 集群")
```

### 执行流程

```python
async def run(self, user_input: str) -> dict:
    # 1. Intent Understanding     → TaskSpec
    # 2. Context Builder          → UnifiedContext
    # 3. Context Optimizer        → OptimizedContext
    # 4. Context Packager         → PackagedContext
    # 5. LLM Inference            → Response
    # 6. Feedback                 → 评估 + 更新记忆 + 记录轨迹
    #
    # 返回:
    #   response, metrics, trace_id, task_spec, latency_ms
```

### 返回结构

```json
{
  "response": "LLM 回复内容",
  "metrics": {
    "answer_quality": 0.95,
    "hallucination_score": 0.02,
    "tool_accuracy": 1.0,
    "latency_ms": 2340,
    "success": true
  },
  "trace_id": "a1b2c3d4",
  "task_spec": { ... },
  "latency_ms": 2850.5
}
```

---

## 六、关键设计亮点

| 设计 | 说明 |
|---|---|
| **Pipeline 模式** | 7 阶段顺序执行，每阶段职责单一、可独立替换和测试 |
| **动态上下文选择** | 基于意图类型按需收集 Context，避免全量加载浪费 Token |
| **五层 Memory** | Working → Short-Term → Long-Term → Episodic → Semantic，时间跨度和抽象粒度逐层递增 |
| **Adapter 模式** | 统一 Context → 多模型 Prompt，新增模型只需加 Adapter |
| **Token Budget 动态分配** | 量化各模块开销，智能裁切非核心内容 |
| **反馈闭环** | 每次交互结果自动更新记忆，Agent 持续进化 |
| **异步全链路** | asyncio 贯穿，支持高并发 Agent 场景 |
| **LLM 降级策略** | Intent Classifier 等模块支持无 LLM 时的正则降级模式 |
| **异常隔离** | 单个 Collector 失败不阻塞整体 Pipeline |

---

## 七、项目结构

```
context_os/
├── pyproject.toml                  # 项目依赖与元信息
├── .env.example                    # 环境变量模板
│
├── context_os/                     # 核心包
│   ├── core/                       # 核心抽象层
│   │   ├── base.py                 # 抽象基类 (BaseCollector, BaseMemoryStore, BasePromptAdapter, BaseLLMClient)
│   │   ├── models.py               # Pydantic 数据模型
│   │   ├── errors.py               # 自定义异常
│   │   └── logger.py               # 日志工具
│   │
│   ├── intent/                     # ① 意图理解
│   │   ├── classifier.py           # 意图分类器
│   │   ├── extractor.py            # 实体 & 参数提取
│   │   └── parser.py               # TaskSpec 构建
│   │
│   ├── orchestrator/               # ② 上下文编排
│   │   ├── router.py               # Context 路由
│   │   └── selector.py             # 动态选择器
│   │
│   ├── collection/                 # ③ 上下文收集
│   │   ├── identity.py             # Identity Context
│   │   ├── conversation.py         # Conversation Context
│   │   └── environment.py          # Environment Context
│   │
│   ├── builder/                    # ④ 上下文构建
│   │   ├── builder.py              # ContextBuilder 编排
│   │   └── merger.py               # Merge / Normalize / Deduplicate
│   │
│   ├── optimizer/                  # ⑤ 上下文优化
│   │   ├── optimizer.py            # 编排入口
│   │   ├── ranker.py               # 相关性排序
│   │   ├── compressor.py           # Token 压缩
│   │   └── budget.py               # Token Budget 分配
│   │
│   ├── packager/                   # ⑥ 模型打包
│   │   ├── packager.py             # 打包编排
│   │   └── adapters/               # 模型适配器
│   │       ├── base.py             # BasePromptAdapter
│   │       ├── claude.py           # Claude XML Adapter
│   │       ├── openai.py           # OpenAI JSON Adapter
│   │       └── registry.py         # 适配器注册中心
│   │
│   ├── memory/                     # Memory 系统
│   │   ├── store.py                # PostgreSQL 存储层
│   │   ├── working.py              # Working Memory
│   │   ├── short_term.py           # Short-Term Memory
│   │   ├── long_term.py            # Long-Term Memory
│   │   ├── episodic.py             # Episodic Memory
│   │   └── semantic.py             # Semantic Memory
│   │
│   ├── feedback/                   # ⑦ 反馈与学习
│   │   ├── evaluator.py            # 质量评估
│   │   ├── tracer.py               # Trace 记录
│   │   └── memory_updater.py       # 记忆更新
│   │
│   ├── llm/                        # LLM 调用抽象
│   │   ├── client.py               # BaseLLMClient
│   │   ├── anthropic_client.py     # Anthropic 实现
│   │   └── openai_client.py        # OpenAI 实现
│   │
│   └── pipeline.py                 # Pipeline 主入口
│
├── tests/                          # 测试
│   ├── conftest.py                 # 公共 Fixture & Mock
│   ├── test_intent/
│   ├── test_orchestrator/
│   ├── test_builder/
│   ├── test_optimizer/
│   ├── test_packager/
│   └── test_memory/
│
└── examples/                       # 使用示例
    ├── basic_pipeline.py
    └── custom_adapter.py
```
