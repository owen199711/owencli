# Context-OS 实现步骤（面向大模型）

> 面向大模型的逐文件实现指南。每个步骤包含 **文件路径**、**目标**、**核心逻辑**，大模型照着依次执行即可。

---

## 目录

- [Phase 1：项目骨架 + 数据模型](#phase-1项目骨架--数据模型)
- [Phase 2：Intent Understanding](#phase-2intent-understanding)
- [Phase 3：Context Orchestrator](#phase-3context-orchestrator)
- [Phase 4：Context Collection](#phase-4context-collection)
- [Phase 5：Memory 系统](#phase-5memory-系统)
- [Phase 6：Context Builder](#phase-6context-builder)
- [Phase 7：Context Optimizer](#phase-7context-optimizer)
- [Phase 8：Context Packager](#phase-8context-packager)
- [Phase 9：LLM Client](#phase-9llm-client)
- [Phase 10：Feedback & Trace](#phase-10feedback--trace)
- [Phase 11：Pipeline 主入口](#phase-11pipeline-主入口)
- [Phase 12：测试](#phase-12测试)
- [Phase 13：示例](#phase-13示例)

---

## Phase 1：项目骨架 + 数据模型

### 步骤 1.1 — pyproject.toml

```
文件: d:\study\owencli\pyproject.toml
目标: 项目元信息与依赖声明
```

创建 `pyproject.toml`，内容：

- `name = "context-os"`, `version = "0.1.0"`, `requires-python = ">=3.11"`
- 核心依赖：`pydantic>=2.0`, `anthropic>=0.30`, `openai>=1.0`, `tiktoken>=0.5`, `numpy>=1.24`, `httpx>=0.25`
- 可选依赖 dev: `pytest`, `pytest-asyncio`, `ruff`
- 可选依赖 vector: `chromadb>=0.4`

### 步骤 1.2 — 项目目录结构

```
文件: 创建以下目录
d:\study\owencli\context_os\
d:\study\owencli\context_os\core\
d:\study\owencli\context_os\intent\
d:\study\owencli\context_os\orchestrator\
d:\study\owencli\context_os\collection\
d:\study\owencli\context_os\builder\
d:\study\owencli\context_os\optimizer\
d:\study\owencli\context_os\packager\
d:\study\owencli\context_os\packager\adapters\
d:\study\owencli\context_os\memory\
d:\study\owencli\context_os\feedback\
d:\study\owencli\context_os\llm\
d:\study\owencli\tests\
d:\study\owencli\examples\
```

每个目录创建 `__init__.py`（空文件或简单导出）。

### 步骤 1.3 — core/errors.py

```
文件: d:\study\owencli\context_os\core\errors.py
目标: 自定义异常类
```

实现三个异常类继承链：

```python
class ContextOSError(Exception): ...
class ContextBuildError(ContextOSError): ...
class MemoryError(ContextOSError): ...
```

### 步骤 1.4 — core/base.py

```
文件: d:\study\owencli\context_os\core\base.py
目标: 抽象基类定义
```

实现以下 ABC：

- `BaseCollector` — `async def collect() -> dict`
- `BaseMemoryStore` — `async def retrieve(query, top_k)`, `async def store(item)`
- `BasePromptAdapter` — `def pack(context) -> str`
- `BaseLLMClient` — `async def complete(prompt, system, max_tokens, temperature, response_format)`

### 步骤 1.5 — core/models.py

```
文件: d:\study\owencli\context_os\core\models.py
目标: 所有 Pydantic 数据模型
```

**枚举类：**

| 枚举 | 值 |
|------|-----|
| `IntentType` | qa, coding, planning, debugging, search, workflow, agent, data_analysis |
| `GoalType` | fix, explain, generate, summarize, compare, refactor, optimize |
| `MemoryType` | working, short_term, long_term, episodic, semantic |
| `PriorityLevel` | low, medium, high, critical |
| `LLMProvider` | claude, openai, gemini, qwen, deepseek |

**数据模型（全部使用 Pydantic BaseModel）：**

| 类 | 关键字段 |
|------|---------|
| `Entity` | type: str, value: str, metadata: dict |
| `Constraint` | max_tokens: int?, max_steps: int?, timeout_seconds: int? |
| `ToolRequirement` | name: str, required: bool, permission: str? |
| `KnowledgeRequirement` | domain: str, query: str, top_k: int |
| `TaskSpec` | id, raw_input, intent, goal, entities[], constraint, priority, tool_requirements[], knowledge_requirements[], confidence |
| `UserProfile` | user_id, role, permission, language, skill_level, tenant, team |
| `ConversationTurn` | role, content, timestamp, metadata |
| `ConversationContext` | history[], current_topic?, current_step?, total_steps?, status, task_graph[] |
| `EnvironmentContext` | os?, working_directory?, git_branch?, runtime{}, mcp_servers{}, env_vars{} |
| `MemoryItem` | id, type, content, embedding?, timestamp, access_count, relevance_score, metadata |
| `KnowledgeChunk` | source, content, score, metadata |
| `ToolContext` | name, schema{}, permission, state{} |
| `UnifiedContext` | identity?, conversation?, environment?, memory[], knowledge[], tools[] |
| `TokenBudget` | total, used, breakdown{} |
| `OptimizedContext` | compressed, token_usage, context |
| `PackagedContext` | provider, raw_prompt, sections{}, metadata{} |
| `TraceStep` | step_name, duration_ms, input_preview, output_preview, token_count? |
| `Trace` | id, task_id, raw_input, steps[], total_latency_ms, total_tokens, success, reward_score? |
| `EvalMetrics` | answer_quality, hallucination_score, tool_accuracy, latency_ms, cost_usd, success, reward_score |

每个模型都必须有完整的字段注解、默认值和类型提示。

### 步骤 1.6 — .env.example

```
文件: d:\study\owencli\.env.example
目标: 环境变量模板
```

包含：

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
CLAUDE_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o
MEMORY_STORAGE_DIR=./data/memory
MEMORY_MAX_TOKENS=128000
TRACE_ENABLED=true
TRACE_STORAGE_DIR=./data/traces
VECTOR_DB_PROVIDER=chroma
CHROMA_PERSIST_DIR=./data/chroma
```

---

## Phase 2：Intent Understanding

### 步骤 2.1 — intent/classifier.py

```
文件: d:\study\owencli\context_os\intent\classifier.py
目标: 意图分类器，将用户输入归类为 IntentType + GoalType
```

实现 `IntentClassifier` 类：

```python
class IntentClassifier:
    def __init__(self, llm_client=None, fallback_mode="regex"):
        self.llm_client = llm_client

    async def classify(self, user_input: str) -> tuple[IntentType, GoalType, float]:
        # LLM 模式: 调用 LLM 进行分类，返回 JSON
        # 降级模式: 关键词规则
        #   "debug|fix|bug|crash|error" → DEBUGGING
        #   "write|create|implement|code|generate" → CODING
        #   "search|find|lookup|查询" → SEARCH
        #   "plan|设计|方案" → PLANNING
        #   默认 → QA
```

### 步骤 2.2 — intent/extractor.py

```
文件: d:\study\owencli\context_os\intent\extractor.py
目标: 实体与参数提取
```

实现 `EntityExtractor` 类，三个方法：

- `extract_entities(user_input, domain) -> list[Entity]` — 提取命名实体
- `extract_tool_requirements(user_input) -> list[ToolRequirement]` — 推断工具需求
- `extract_knowledge_requirements(user_input) -> list[KnowledgeRequirement]` — 推断知识需求

降级方案使用正则匹配。

### 步骤 2.3 — intent/parser.py

```
文件: d:\study\owencli\context_os\intent\parser.py
目标: 组装 TaskSpec
```

实现 `TaskParser` 类：

```python
class TaskParser:
    def __init__(self, classifier: IntentClassifier, extractor: EntityExtractor): ...

    async def parse(self, user_input: str) -> TaskSpec:
        # 1. classifier.classify(user_input) → intent, goal, confidence
        # 2. extractor.extract_entities(user_input) → entities
        # 3. extractor.extract_tool_requirements(user_input) → tools
        # 4. extractor.extract_knowledge_requirements(user_input) → knowledge
        # 5. 组装并返回 TaskSpec
```

---

## Phase 3：Context Orchestrator

### 步骤 3.1 — orchestrator/selector.py

```
文件: d:\study\owencli\context_os\orchestrator\selector.py
目标: 动态上下文选择器
```

实现 `ContextFlag`（Flag 枚举）和 `ContextSelector`：

```python
class ContextFlag(Flag):
    IDENTITY = auto()
    CONVERSATION = auto()
    ENVIRONMENT = auto()
    MEMORY = auto()
    KNOWLEDGE = auto()
    TOOLS = auto()

# IntentType → ContextFlag 映射表
INTENT_CONTEXT_MAP = {
    IntentType.QA:            ContextFlag.CONVERSATION | ContextFlag.KNOWLEDGE,
    IntentType.CODING:        ContextFlag.IDENTITY | ContextFlag.CONVERSATION
                              | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
                              | ContextFlag.TOOLS,
    IntentType.DEBUGGING:     ContextFlag.IDENTITY | ContextFlag.CONVERSATION
                              | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
                              | ContextFlag.KNOWLEDGE | ContextFlag.TOOLS,
    IntentType.PLANNING:      ContextFlag.CONVERSATION | ContextFlag.MEMORY
                              | ContextFlag.KNOWLEDGE,
    IntentType.SEARCH:        ContextFlag.KNOWLEDGE,
    IntentType.WORKFLOW:      ContextFlag.CONVERSATION | ContextFlag.ENVIRONMENT
                              | ContextFlag.TOOLS,
    IntentType.AGENT:         ContextFlag.IDENTITY | ContextFlag.CONVERSATION
                              | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
                              | ContextFlag.KNOWLEDGE | ContextFlag.TOOLS,
    IntentType.DATA_ANALYSIS: ContextFlag.CONVERSATION | ContextFlag.ENVIRONMENT
                              | ContextFlag.TOOLS,
}

class ContextSelector:
    def select(self, task: TaskSpec) -> ContextFlag:
        # 1. 从 INTENT_CONTEXT_MAP 获取 flags
        # 2. 根据 task.constraint.max_tokens 调整（如果 <8000 去掉低优先级 Context）
```

### 步骤 3.2 — orchestrator/router.py

```
文件: d:\study\owencli\context_os\orchestrator\router.py
目标: Context 路由器
```

实现 `ContextRoute` 数据类和 `ContextRouter` 类：

- `ContextRoute` — source: str, flag: ContextFlag, priority: int
- `ContextRouter.route(task, flags) → list[ContextRoute]` — 将 flags 转为带优先级的路由列表，按优先级降序排列

收集器 source 名称：`identity_provider`, `conversation_store`, `env_provider`, `memory_store`, `knowledge_store`, `tool_registry`

---

## Phase 4：Context Collection

### 步骤 4.1 — collection/identity.py

```
文件: d:\study\owencli\context_os\collection\identity.py
目标: 用户身份信息收集
```

实现 `IdentityCollector`（继承 BaseCollector）：

```python
class IdentityCollector(BaseCollector):
    def __init__(self, user_profile: UserProfile | None = None):
        self.user_profile = user_profile

    async def collect(self) -> UserProfile:
        # 1. 如果有注入的 user_profile → 直接返回
        # 2. 否则从环境变量读取
        # 3. 返回 UserProfile
```

### 步骤 4.2 — collection/conversation.py

```
文件: d:\study\owencli\context_os\collection\conversation.py
目标: 对话历史收集（环形缓冲区）
```

实现 `ConversationCollector`（继承 BaseCollector）：

```python
class ConversationCollector(BaseCollector):
    def __init__(self, max_history: int = 50):
        self._history: list[ConversationTurn] = []

    def add_turn(self, role: str, content: str):
        # 追加到尾部，超过 max_history 时从头部丢弃

    async def collect(self) -> ConversationContext:
        # 返回 ConversationContext(history=self._history)
```

### 步骤 4.3 — collection/environment.py

```
文件: d:\study\owencli\context_os\collection\environment.py
目标: 系统环境信息收集
```

实现 `EnvironmentCollector`：

```python
class EnvironmentCollector(BaseCollector):
    async def collect(self) -> EnvironmentContext:
        # os = platform.system()
        # working_directory = os.getcwd()
        # git_branch = 运行 git rev-parse --abbrev-ref HEAD
        # runtime = { python_version, cpu 等 }
```

### 步骤 4.4 — collection/base.py

```
文件: d:\study\owencli\context_os\collection\__init__.py
目标: 统一导出
```

---

## Phase 5：Memory 系统

### 步骤 5.1 — memory/store.py

```
文件: d:\study\owencli\context_os\memory\store.py
目标: 记忆存储统一抽象
```

实现 `MemoryStore`（继承 BaseMemoryStore）：

```python
class MemoryStore(BaseMemoryStore):
    def __init__(self, storage_dir: str = "./data/memory"):
        # 确保目录存在
        # 初始化 SQLite 连接（建表）

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        # 1. 关键词检索（LIKE 或 FTS）
        # 2. 如果有 embedding 列，计算余弦相似度
        # 3. 按 (0.7 * 语义相似度 + 0.3 * 时间衰减) 排序
        # 4. 返回 top_k

    async def store(self, item: MemoryItem):
        # 写入 SQLite
        # 如果有 embedding 则一并存储

    async def forget(self, threshold_days: int = 30):
        # 基于 Ebbinghaus 曲线清除访问频率低 + 时间久的记忆
```

SQLite 表结构：

```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,
    timestamp TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    metadata TEXT DEFAULT '{}'
);
```

### 步骤 5.2 — memory/working.py

```
文件: d:\study\owencli\context_os\memory\working.py
目标: 工作记忆（纯内存，环形缓冲区）
```

```python
class WorkingMemory:
    def __init__(self, max_tokens: int = 8000):
        self.items: list[MemoryItem] = []
        self.max_tokens = max_tokens
        self._current_token_count = 0

    def push(self, item: MemoryItem):
        # 追加，更新 token 计数
        # 超过预算时从头部淘汰最旧条目

    def get_recent(self, n: int = 10) -> list[MemoryItem]:
        return self.items[-n:]

    def clear(self):
        self.items.clear()
        self._current_token_count = 0

    def estimate_tokens(self, text: str) -> int:
        # 粗略估算: len(text) // 4
```

### 步骤 5.3 — memory/short_term.py

```
文件: d:\study\owencli\context_os\memory\short_term.py
目标: 短期记忆（当前 Session，SQLite 持久化）
```

```python
class ShortTermMemory:
    def __init__(self, session_id: str, storage_dir: str = "./data/memory"):
        self.session_id = session_id
        self.store = MemoryStore(storage_dir)

    async def add(self, item: MemoryItem):
        # 写入 SQLite，标记 type=short_term
        # 关联 session_id

    async def get_session_history(self) -> list[MemoryItem]:
        # 查询当前 session 的所有记录

    async def clear_session(self):
        # 删除当前 session 记录
```

### 步骤 5.4 — memory/long_term.py

```
文件: d:\study\owencli\context_os\memory\long_term.py
目标: 长期记忆（跨 Session，带向量检索）
```

```python
class LongTermMemory:
    def __init__(self, storage_dir: str = "./data/memory"):
        self.store = MemoryStore(storage_dir)
        self._init_vector_index()

    def _init_vector_index(self):
        # 初始化简单的向量索引（使用 numpy 实现近似检索）

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        # 1. 从 SQLite 获取候选
        # 2. 计算语义相似度
        # 3. 加权排序返回

    async def store(self, content: str, memory_type: str, metadata: dict = None):
        # 生成 embedding（如果有 LLM client）
        # 写入 store

    async def consolidate(self):
        # 记忆整合：合并重复项，提炼高层概要

    async def forget(self, threshold_days: int = 30):
        # 调用 store.forget()
```

### 步骤 5.5 — memory/episodic.py

```
文件: d:\study\owencli\context_os\memory\episodic.py
目标: 情景记忆（过去经历的"故事"记录）
```

```python
class EpisodicMemory:
    """记录"什么场景下做了什么，结果如何" """
    def __init__(self, storage_dir: str = "./data/memory"):
        self.store = MemoryStore(storage_dir)

    async def record_episode(self, scene: str, action: str, result: str,
                             feedback: str = "", related_files: list[str] = None):
        # 构建结构化的 Episode 记录
        # 写入存储

    async def recall_similar(self, scene_query: str, top_k: int = 3) -> list[MemoryItem]:
        # 相似场景检索
```

### 步骤 5.6 — memory/semantic.py

```
文件: d:\study\owencli\context_os\memory\semantic.py
目标: 语义记忆（知识图谱）
```

```python
class SemanticMemory:
    """剥离具体场景的通用知识，以图谱形式存储"""
    def __init__(self):
        self.graph: dict[str, dict] = {}  # node_id → {attributes, relations}

    def add_concept(self, name: str, attributes: dict, relations: dict):
        # 添加概念节点

    def add_relation(self, from_node: str, to_node: str, relation_type: str):
        # 添加关系边

    def query(self, concept: str, depth: int = 1) -> dict:
        # BFS 查询子图

    def abstract_from_episodes(self, episodes: list[MemoryItem]):
        # 从情景记忆中提炼通用知识
```

---

## Phase 6：Context Builder

### 步骤 6.1 — builder/merger.py

```
文件: d:\study\owencli\context_os\builder\merger.py
目标: 合并、归一化、去重
```

实现 `ContextMerger` 类：

```python
class ContextMerger:
    def merge(self, contexts: list[UnifiedContext]) -> UnifiedContext:
        # 合并多个 UnifiedContext（取并集）

    def normalize(self, context: UnifiedContext) -> UnifiedContext:
        # 统一格式（如时间戳转统一时区）

    def deduplicate(self, context: UnifiedContext) -> UnifiedContext:
        # 对 memory 和 knowledge 按内容去重
        # 保留置信度高的版本
```

### 步骤 6.2 — builder/builder.py

```
文件: d:\study\owencli\context_os\builder\builder.py
目标: 组装 UnifiedContext
```

实现 `ContextBuilder` 类：

```python
class ContextBuilder:
    def __init__(self, selector: ContextSelector, router: ContextRouter,
                 identity: IdentityCollector, conversation: ConversationCollector,
                 environment: EnvironmentCollector,
                 working_memory: WorkingMemory, long_term_memory: LongTermMemory): ...

    async def build(self, task: TaskSpec) -> UnifiedContext:
        # 1. selector.select(task) → flags
        # 2. router.route(task, flags) → routes
        # 3. 并行收集（asyncio.gather）：
        #    - 遍历 routes，匹配对应的 collector
        #    - memory.retrieve(task.raw_input)
        # 4. merger.merge() + normalize() + deduplicate()
        # 5. 返回 UnifiedContext
```

---

## Phase 7：Context Optimizer

### 步骤 7.1 — optimizer/ranker.py

```
文件: d:\study\owencli\context_os\optimizer\ranker.py
目标: 多维相关性排序
```

实现 `RelevanceRanker`：

```python
class RelevanceRanker:
    def __init__(self, time_decay_hours: float = 24.0): ...

    def rank_memories(self, items: list[MemoryItem],
                      query_embedding: list[float] | None = None) -> list[MemoryItem]:
        # 对每个 item 计算综合得分：
        # score = 0.5 * semantic_similarity + 0.3 * time_decay + 0.2 * frequency
        # time_decay = exp(-age_hours / time_decay_hours)
        # frequency = log1p(access_count) / 10
        # 按 score 降序排列

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        # 余弦相似度计算
```

### 步骤 7.2 — optimizer/compressor.py

```
文件: d:\study\owencli\context_os\optimizer\compressor.py
目标: 上下文压缩
```

实现 `ContextCompressor`：

```python
class ContextCompressor:
    def __init__(self, llm_client=None, model="gpt-4"):
        self.llm_client = llm_client
        self.encoder = tiktoken.encoding_for_model(model) if model else None

    def count_tokens(self, text: str) -> int:
        # 使用 tiktoken 或 len(text)//4

    async def compress_conversation(self, history: list[ConversationTurn],
                                    max_tokens: int = 2000) -> str:
        # 如果 token ≤ max_tokens → 直接拼接
        # 否则 → 如果有 LLM 则 LLM 摘要，否则保留后一半

    async def semantic_compress(self, text: str, ratio: float = 0.5) -> str:
        # LLM 语义压缩：保留关键事实，去除冗余
```

### 步骤 7.3 — optimizer/budget.py

```
文件: d:\study\owencli\context_os\optimizer\budget.py
目标: Token 预算分配
```

实现 `TokenBudgetAllocator`：

```python
class TokenBudgetAllocator:
    DEFAULT_RATIOS = {
        "instruction": 0.10, "conversation": 0.20,
        "memory": 0.10, "knowledge": 0.45, "tools": 0.15,
    }

    def __init__(self, max_total_tokens: int = 128000):
        self.max_total_tokens = max_total_tokens

    def allocate(self) -> TokenBudget:
        # 按比例分配预算
        # 返回 TokenBudget(total, breakdown)

    def adjust_for_model(self, model_max_tokens: int):
        # 根据模型能力调整
```

### 步骤 7.4 — optimizer/optimizer.py

```
文件: d:\study\owencli\context_os\optimizer\optimizer.py
目标: 优化编排入口
```

实现 `ContextOptimizer`：

```python
class ContextOptimizer:
    def __init__(self, ranker: RelevanceRanker,
                 compressor: ContextCompressor,
                 budget: TokenBudgetAllocator): ...

    async def optimize(self, context: UnifiedContext,
                       task: TaskSpec) -> OptimizedContext:
        # 1. ranker.rank_memories(context.memory)
        # 2. compressor.compress_conversation(context.conversation)
        # 3. budget.allocate() → 分配预算
        # 4. 截断超出预算的部分
        # 5. 返回 OptimizedContext
```

---

## Phase 8：Context Packager

### 步骤 8.1 — packager/adapters/base.py

```
文件: d:\study\owencli\context_os\packager\adapters\base.py
目标: Prompt 适配器基类
```

```python
class BasePromptAdapter(ABC):
    provider: LLMProvider

    @abstractmethod
    def pack(self, context: OptimizedContext) -> PackagedContext: ...
```

### 步骤 8.2 — packager/adapters/claude.py

```
文件: d:\study\owencli\context_os\packager\adapters\claude.py
目标: Claude XML 格式适配器
```

核心逻辑：

```python
class ClaudePromptAdapter(BasePromptAdapter):
    provider = LLMProvider.CLAUDE

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        sections = {}
        # system: 系统指令
        # memory: <memory><working>...</working></memory>
        # knowledge: <knowledge><source score="...">...</source></knowledge>
        # tools: <tools><tool name="...">...</tool></tools>
        # conversation: <conversation><user>...</user></conversation>
        # raw_prompt = "\n\n".join(sections.values())
        # 返回 PackagedContext
```

### 步骤 8.3 — packager/adapters/openai.py

```
文件: d:\study\owencli\context_os\packager\adapters\openai.py
目标: OpenAI JSON 格式适配器
```

```python
class OpenAIPromptAdapter(BasePromptAdapter):
    provider = LLMProvider.OPENAI

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        # 构建 OpenAI messages 格式
        # system → {"role": "system", "content": ...}
        # 其他 → {"role": "user", "content": 拼接后的字符串}
        # raw_prompt = json.dumps(messages)
```

### 步骤 8.4 — packager/adapters/registry.py

```
文件: d:\study\owencli\context_os\packager\adapters\registry.py
目标: 适配器注册中心
```

```python
class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[LLMProvider, BasePromptAdapter] = {}

    def register(self, adapter: BasePromptAdapter): ...
    def get(self, provider: LLMProvider) -> BasePromptAdapter: ...
    def register_defaults(self):
        self.register(ClaudePromptAdapter())
        self.register(OpenAIPromptAdapter())

default_registry = AdapterRegistry()
default_registry.register_defaults()
```

### 步骤 8.5 — packager/packager.py

```
文件: d:\study\owencli\context_os\packager\packager.py
目标: 打包编排
```

```python
class ContextPackager:
    def __init__(self, registry: AdapterRegistry | None = None): ...

    def pack(self, context: OptimizedContext,
             provider: LLMProvider = LLMProvider.CLAUDE) -> PackagedContext:
        adapter = self.registry.get(provider)
        return adapter.pack(context)
```

---

## Phase 9：LLM Client

### 步骤 9.1 — llm/client.py

```
文件: d:\study\owencli\context_os\llm\client.py
目标: LLM 客户端抽象
```

已在 base.py 中定义 `BaseLLMClient`，此处只导出。

### 步骤 9.2 — llm/anthropic_client.py

```
文件: d:\study\owencli\context_os\llm\anthropic_client.py
目标: Anthropic Claude 实现
```

```python
class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key=None, model="claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    async def complete(self, prompt, system=None, max_tokens=4096,
                       temperature=0.7, response_format=None):
        # 调用 self.client.messages.create()
        # 如果 response_format="json" 则 json.loads()
```

### 步骤 9.3 — llm/openai_client.py

```
文件: d:\study\owencli\context_os\llm\openai_client.py
目标: OpenAI 实现
```

```python
class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key=None, model="gpt-4o"):
        self.client = AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model

    async def complete(self, prompt, system=None, max_tokens=4096,
                       temperature=0.7, response_format=None):
        # 调用 self.client.chat.completions.create()
```

---

## Phase 10：Feedback & Trace

### 步骤 10.1 — feedback/evaluator.py

```
文件: d:\study\owencli\context_os\feedback\evaluator.py
目标: 输出质量评估
```

```python
class QualityEvaluator:
    def __init__(self, llm_client=None): ...

    async def evaluate(self, packed: PackagedContext, llm_response: str,
                       latency_ms: float, token_count: int) -> EvalMetrics:
        # 1. 计算 latency、cost
        # 2. 检查 success (response 不含 error)
        # 3. 如果有 LLM，调用 LLM 评估 answer_quality
        # 4. 计算 reward_score = quality * (0.8 if success else 0.2)
        # 5. 返回 EvalMetrics
```

### 步骤 10.2 — feedback/tracer.py

```
文件: d:\study\owencli\context_os\feedback\tracer.py
目标: 执行轨迹记录
```

```python
class Tracer:
    def __init__(self, storage_dir: str = "./data/traces"): ...

    def start(self, task_id: str, raw_input: str) -> str:
        # 创建 Trace 实例

    def step_begin(self, step_name: str) -> TraceStep: ...
    def step_end(self, step: TraceStep, input_text: str, output_text: str):
        # 记录耗时、input/output 预览

    def finish(self, success: bool):
        # 写入 JSON 文件

    def _save(self, trace: Trace):
        # trace.model_dump_json(indent=2) → 写入 storage_dir
```

### 步骤 10.3 — feedback/memory_updater.py

```
文件: d:\study\owencli\context_os\feedback\memory_updater.py
目标: 记忆更新
```

```python
class MemoryUpdater:
    def __init__(self, long_term_memory: LongTermMemory,
                 episodic_memory: EpisodicMemory): ...

    async def update_from_task(self, task: TaskSpec, response: str,
                               metrics: EvalMetrics):
        # 1. 写入情景记忆（episodic）
        # 2. 如果 reward_score 高→写入长期记忆
        # 3. 更新用户的语义偏好

    async def update_from_feedback(self, user_feedback: str):
        # 根据用户纠正反馈更新记忆
```

---

## Phase 11：Pipeline 主入口

### 步骤 11.1 — pipeline.py

```
文件: d:\study\owencli\context_os\pipeline.py
目标: 完整流程编排
```

实现 `ContextOSPipeline` 类：

```python
class ContextOSPipeline:
    def __init__(self, llm_client: BaseLLMClient,
                 provider: LLMProvider = LLMProvider.CLAUDE,
                 memory_dir: str = "./data/memory"): ...

    async def run(self, user_input: str) -> dict:
        """
        1. tracer.start()
        2. task_parser.parse(user_input)           → TaskSpec
        3. builder.build(task)                      → UnifiedContext
        4. optimizer.optimize(unified, task)         → OptimizedContext
        5. packager.pack(optimized, provider)        → PackagedContext
        6. llm_client.complete(packaged.raw_prompt)  → response
        7. evaluator.evaluate(...)                   → EvalMetrics
        8. memory_updater.update(...)
        9. tracer.finish(success)
        10. 返回 {"response", "metrics", "trace_id", "task_spec"}
        """
```

### 步骤 11.2 — context_os/__init__.py

```
文件: d:\study\owencli\context_os\__init__.py
目标: 统一导出
```

导出 `ContextOSPipeline`、所有模型、所有客户端。

---

## Phase 12：测试

### 步骤 12.1 — tests/conftest.py

```
文件: d:\study\owencli\tests\conftest.py
目标: 全局测试 Fixture
```

提供以下 pytest fixture：

- `sample_task_spec()` — 返回一个示例 TaskSpec
- `sample_unified_context()` — 返回填充了假数据的 UnifiedContext
- `mock_llm_client()` — 返回 MockLLMClient（总是返回预设文本）

### 步骤 12.2 — tests/test_intent/test_classifier.py

```
文件: d:\study\owencli\tests\test_intent\test_classifier.py
目标: 测试 IntentClassifier
```

测试用例：

- `test_classify_debug_keyword` — 输入含 "bug" 应返回 DEBUGGING
- `test_classify_coding_keyword` — 输入含 "write" 应返回 CODING
- `test_classify_default` — 无匹配关键字返回 QA
- `test_classify_with_llm` — mock LLM 时的测试

### 步骤 12.3 — tests/test_intent/test_parser.py

```
文件: d:\study\owencli\tests\test_intent\test_parser.py
目标: 测试 TaskParser
```

- `test_parse_full` — 完整解析流程，验证返回的 TaskSpec 字段完整

### 步骤 12.4 — tests/test_orchestrator/test_selector.py

```
文件: d:\study\owencli\tests\test_orchestrator\test_selector.py
目标: 测试 ContextSelector
```

- `test_select_qa` — QA 类型只含 CONVERSATION | KNOWLEDGE
- `test_select_coding` — CODING 类型含所有 flags
- `test_select_with_token_constraint` — Token 紧张时去掉低优先级

### 步骤 12.5 — tests/test_builder/test_builder.py

```
文件: d:\study\owencli\tests\test_builder\test_builder.py
目标: 测试 ContextBuilder
```

- `test_build_success` — 正常构建 UnifiedContext
- `test_build_with_empty_input` — 空输入时不会崩溃

### 步骤 12.6 — tests/test_optimizer/test_ranker.py

```
文件: d:\study\owencli\tests\test_optimizer\test_ranker.py
目标: 测试 RelevanceRanker
```

- `test_rank_memories` — 验证排序结果（最近访问的排前面）
- `test_cosine_similarity` — 余弦相似度计算正确

### 步骤 12.7 — tests/test_optimizer/test_compressor.py

```
文件: d:\study\owencli\tests\test_optimizer\test_compressor.py
目标: 测试 ContextCompressor
```

- `test_count_tokens` — Token 计数正确
- `test_compress_conversation_below_limit` — 未超限时不压缩
- `test_compress_conversation_above_limit` — 超限时截断

### 步骤 12.8 — tests/test_packager/test_claude.py

```
文件: d:\study\owencli\tests\test_packager\test_claude.py
目标: 测试 ClaudePromptAdapter
```

- `test_pack_claude` — 验证输出包含 XML 标签 `<memory>`, `<tools>`, `<conversation>`
- `test_pack_empty_context` — 空 Context 仍然生成有效 prompt

### 步骤 12.9 — tests/test_memory/test_working.py

```
文件: d:\study\owencli\tests\test_memory\test_working.py
目标: 测试 WorkingMemory
```

- `test_push_and_get` — 推入和获取
- `test_eviction_when_exceed_budget` — 超过 Token 预算时淘汰旧条目

### 步骤 12.10 — tests/test_memory/test_long_term.py

```
文件: d:\study\owencli\tests\test_memory\test_long_term.py
目标: 测试 LongTermMemory
```

- `test_store_and_retrieve` — 存储后能检索到
- `test_empty_retrieve` — 空库检索返回空列表

---

## Phase 13：示例

### 步骤 13.1 — examples/basic_pipeline.py

```
文件: d:\study\owencli\examples\basic_pipeline.py
目标: 完整使用示例
```

```python
import asyncio
from context_os.pipeline import ContextOSPipeline
from context_os.llm.anthropic_client import AnthropicClient
from context_os.core.models import LLMProvider

async def main():
    llm = AnthropicClient()
    pipeline = ContextOSPipeline(
        llm_client=llm,
        provider=LLMProvider.CLAUDE,
        memory_dir="./data/memory",
    )

    # 测试 1: QA
    result = await pipeline.run("Python 的 GIL 是什么？")
    print(f"QA 质量: {result['metrics']['reward_score']}")

    # 测试 2: 编码
    result = await pipeline.run("写一个 FastAPI 健康检查接口")
    print(f"编码质量: {result['metrics']['reward_score']}")

    # 测试 3: 调试（测试记忆是否生效）
    result = await pipeline.run("刚才生成的接口有 bug 吗？")
    print(f"调试质量: {result['metrics']['reward_score']}")
    print(f"Trace ID: {result['trace_id']}")

asyncio.run(main())
```

### 步骤 13.2 — examples/custom_adapter.py

```
文件: d:\study\owencli\examples\custom_adapter.py
目标: 自定义 Prompt 适配器示例
```

```python
from context_os.packager.adapters.base import BasePromptAdapter
from context_os.core.models import LLMProvider, OptimizedContext, PackagedContext

class CustomAdapter(BasePromptAdapter):
    provider = "custom"

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        # 自定义格式
        prompt = f"""【系统指令】
You are a helpful assistant.

【记忆】
{chr(10).join(m.content for m in ctx.context.memory)}

【对话】
{chr(10).join(f"{t.role}: {t.content}" for t in (ctx.context.conversation.history if ctx.context.conversation else []))}
"""
        return PackagedContext(provider=self.provider, raw_prompt=prompt, sections={"full": prompt})
```

---

## 附录：执行顺序速查表

```
Phase  | 步骤 | 文件                               | 行数估计
───────┼──────┼────────────────────────────────────┼─────────
1      | 1.1  | pyproject.toml                     | ~30
1      | 1.2  | (目录结构)                         | -
1      | 1.3  | core/errors.py                     | ~5
1      | 1.4  | core/base.py                       | ~30
1      | 1.5  | core/models.py                     | ~200  ← 最大文件
1      | 1.6  | .env.example                       | ~10
───────┼──────┼────────────────────────────────────┼─────────
2      | 2.1  | intent/classifier.py               | ~80
2      | 2.2  | intent/extractor.py                | ~60
2      | 2.3  | intent/parser.py                   | ~30
───────┼──────┼────────────────────────────────────┼─────────
3      | 3.1  | orchestrator/selector.py           | ~50
3      | 3.2  | orchestrator/router.py             | ~40
───────┼──────┼────────────────────────────────────┼─────────
4      | 4.1  | collection/identity.py             | ~30
4      | 4.2  | collection/conversation.py         | ~40
4      | 4.3  | collection/environment.py          | ~40
───────┼──────┼────────────────────────────────────┼─────────
5      | 5.1  | memory/store.py                    | ~120
5      | 5.2  | memory/working.py                  | ~50
5      | 5.3  | memory/short_term.py               | ~40
5      | 5.4  | memory/long_term.py                | ~80
5      | 5.5  | memory/episodic.py                 | ~50
5      | 5.6  | memory/semantic.py                 | ~60
───────┼──────┼────────────────────────────────────┼─────────
6      | 6.1  | builder/merger.py                  | ~60
6      | 6.2  | builder/builder.py                 | ~80
───────┼──────┼────────────────────────────────────┼─────────
7      | 7.1  | optimizer/ranker.py                | ~60
7      | 7.2  | optimizer/compressor.py            | ~70
7      | 7.3  | optimizer/budget.py                | ~30
7      | 7.4  | optimizer/optimizer.py             | ~40
───────┼──────┼────────────────────────────────────┼─────────
8      | 8.1  | packager/adapters/base.py          | ~10
8      | 8.2  | packager/adapters/claude.py        | ~60
8      | 8.3  | packager/adapters/openai.py        | ~50
8      | 8.4  | packager/adapters/registry.py      | ~20
8      | 8.5  | packager/packager.py               | ~20
───────┼──────┼────────────────────────────────────┼─────────
9      | 9.1  | llm/client.py (导出)               | ~5
9      | 9.2  | llm/anthropic_client.py            | ~40
9      | 9.3  | llm/openai_client.py               | ~40
───────┼──────┼────────────────────────────────────┼─────────
10     | 10.1 | feedback/evaluator.py              | ~60
10     | 10.2 | feedback/tracer.py                 | ~60
10     | 10.3 | feedback/memory_updater.py         | ~40
───────┼──────┼────────────────────────────────────┼─────────
11     | 11.1 | pipeline.py                        | ~100  ← 核心文件
11     | 11.2 | context_os/__init__.py             | ~20
───────┼──────┼────────────────────────────────────┼─────────
12     | 12.x | tests/ 下所有文件                   | ~400 总计
───────┼──────┼────────────────────────────────────┼─────────
13     | 13.x | examples/ 下文件                    | ~80
```

> 按顺序执行即可，每个步骤完成后测试再进入下一步。
