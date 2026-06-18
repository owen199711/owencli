# Context-OS 技术实现方案

> 基于 Python 实现类 Claude Code 的 AI Agent Context 管理系统

---

## 一、项目结构与包布局

```
context_os/
├── pyproject.toml                 # 项目依赖与元信息
├── .env.example                   # 环境变量模板
├── README.md
│
├── context_os/                    # 核心包
│   ├── __init__.py
│   │
│   ├── core/                      # 核心抽象层
│   │   ├── __init__.py
│   │   ├── base.py                # 基础接口定义
│   │   ├── models.py              # 统一数据模型 (Pydantic)
│   │   └── errors.py              # 自定义异常
│   │
│   ├── intent/                    # ① Intent Understanding
│   │   ├── __init__.py
│   │   ├── classifier.py          # 意图分类器
│   │   ├── extractor.py           # 实体 & 参数提取
│   │   └── parser.py              # TaskSpec 构建
│   │
│   ├── orchestrator/              # ② Context Orchestrator
│   │   ├── __init__.py
│   │   ├── router.py              # Context 路由
│   │   ├── selector.py            # 动态选择器
│   │   └── prioritizer.py         # 优先级排序
│   │
│   ├── collection/                # ③ Context Collection
│   │   ├── __init__.py
│   │   ├── identity.py            # Identity Context
│   │   ├── conversation.py        # Conversation Context
│   │   ├── environment.py         # Environment Context
│   │   └── base.py               # Collector 基类
│   │
│   ├── builder/                   # ④ Context Builder
│   │   ├── __init__.py
│   │   ├── merger.py              # Merge / Normalize / Deduplicate
│   │   ├── retriever.py           # Memory + Knowledge 检索
│   │   └── builder.py            # UnifiedContext 组装
│   │
│   ├── optimizer/                 # ⑤ Context Optimizer
│   │   ├── __init__.py
│   │   ├── compressor.py          # 压缩器 (Summary / Hierarchy / Semantic)
│   │   ├── ranker.py              # 排序器 (Relevance / Time / Priority)
│   │   ├── budget.py              # Token Budget 分配
│   │   └── optimizer.py          # 编排入口
│   │
│   ├── packager/                  # ⑥ Context Packager
│   │   ├── __init__.py
│   │   ├── adapters/             # 模型适配器
│   │   │   ├── base.py
│   │   │   ├── claude.py          # Claude XML Adapter
│   │   │   ├── openai.py          # OpenAI JSON Adapter
│   │   │   ├── gemini.py          # Gemini Adapter
│   │   │   └── registry.py        # 适配器注册中心
│   │   └── packager.py            # 打包编排
│   │
│   ├── memory/                    # Memory 系统 (跨模块)
│   │   ├── __init__.py
│   │   ├── store.py               # 存储抽象
│   │   ├── working.py             # Working Memory
│   │   ├── short_term.py          # Short-Term Memory
│   │   ├── long_term.py           # Long-Term Memory
│   │   ├── episodic.py            # Episodic Memory
│   │   └── semantic.py            # Semantic Memory
│   │
│   ├── feedback/                  # ⑧ Context Feedback
│   │   ├── __init__.py
│   │   ├── evaluator.py           # 质量评估
│   │   ├── tracer.py              # Trace 记录
│   │   └── memory_updater.py      # 记忆更新
│   │
│   ├── llm/                       # LLM 调用抽象
│   │   ├── __init__.py
│   │   ├── client.py              # LLM Client 抽象
│   │   ├── anthropic_client.py    # Anthropic 实现
│   │   └── openai_client.py       # OpenAI 实现
│   │
│   └── pipeline.py                # Pipeline 编排入口
│
├── tests/                         # 测试
│   ├── conftest.py
│   ├── test_intent/
│   ├── test_orchestrator/
│   ├── test_builder/
│   ├── test_optimizer/
│   ├── test_packager/
│   └── test_memory/
│
└── examples/                      # 使用示例
    ├── basic_pipeline.py
    └── custom_adapter.py
```

---

## 二、核心数据模型

### `context_os/core/models.py`

```python
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Enums ─────────────────────────────────────────────────────

class IntentType(str, Enum):
    QA = "qa"
    CODING = "coding"
    PLANNING = "planning"
    DEBUGGING = "debugging"
    SEARCH = "search"
    WORKFLOW = "workflow"
    AGENT = "agent"
    DATA_ANALYSIS = "data_analysis"


class GoalType(str, Enum):
    FIX = "fix"
    EXPLAIN = "explain"
    GENERATE = "generate"
    SUMMARIZE = "summarize"
    COMPARE = "compare"
    REFACTOR = "refactor"
    OPTIMIZE = "optimize"


class MemoryType(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class PriorityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LLMProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"
    QWEN = "qwen"
    DEEPSEEK = "deepseek"


# ─── Entity ────────────────────────────────────────────────────

class Entity(BaseModel):
    type: str          # e.g. "cluster", "namespace", "pod"
    value: str         # e.g. "prod", "nginx-abc123"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None
    timeout_seconds: Optional[int] = None
    allowed_tools: Optional[List[str]] = None


class ToolRequirement(BaseModel):
    name: str
    required: bool = True
    permission: Optional[str] = None  # "readonly" | "write"


class KnowledgeRequirement(BaseModel):
    domain: str
    query: str
    top_k: int = 5


# ─── TaskSpec (Intent Understanding 输出) ──────────────────────

class TaskSpec(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    raw_input: str
    intent: IntentType
    goal: GoalType
    entities: List[Entity] = Field(default_factory=list)
    constraint: Constraint = Field(default_factory=Constraint)
    priority: PriorityLevel = PriorityLevel.MEDIUM
    tool_requirements: List[ToolRequirement] = Field(default_factory=list)
    knowledge_requirements: List[KnowledgeRequirement] = Field(default_factory=list)
    domain: Optional[str] = None
    confidence: float = 0.0  # 分类置信度


# ─── Context 数据 ─────────────────────────────────────────────

class UserProfile(BaseModel):
    user_id: str
    role: str
    permission: str
    language: str
    skill_level: str
    organization: Optional[str] = None
    tenant: Optional[str] = None
    team: Optional[str] = None


class ConversationTurn(BaseModel):
    role: str          # "user" | "assistant" | "tool"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationContext(BaseModel):
    history: List[ConversationTurn] = Field(default_factory=list)
    current_topic: Optional[str] = None
    current_step: Optional[str] = None
    total_steps: Optional[int] = None
    status: str = "idle"  # "idle" | "running" | "waiting" | "done"
    task_graph: List[str] = Field(default_factory=list)


class EnvironmentContext(BaseModel):
    os: Optional[str] = None
    working_directory: Optional[str] = None
    git_branch: Optional[str] = None
    git_repo: Optional[str] = None
    runtime: Dict[str, Any] = Field(default_factory=dict)
    mcp_servers: Dict[str, str] = Field(default_factory=dict)  # name -> url
    env_vars: Dict[str, str] = Field(default_factory=dict)


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: MemoryType
    content: str
    embedding: Optional[List[float]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    access_count: int = 0
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    source: str          # "vector_db" | "document" | "api" | "codebase"
    content: str
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolContext(BaseModel):
    name: str
    schema: Dict[str, Any] = Field(default_factory=dict)
    permission: str = "readonly"
    state: Dict[str, Any] = Field(default_factory=dict)


# ─── UnifiedContext (Builder 输出) ────────────────────────────

class UnifiedContext(BaseModel):
    identity: Optional[UserProfile] = None
    conversation: Optional[ConversationContext] = None
    environment: Optional[EnvironmentContext] = None
    memory: List[MemoryItem] = Field(default_factory=list)
    knowledge: List[KnowledgeChunk] = Field(default_factory=list)
    tools: List[ToolContext] = Field(default_factory=list)


# ─── OptimizedContext (Optimizer 输出) ─────────────────────────

class TokenBudget(BaseModel):
    total: int = 0
    used: int = 0
    breakdown: Dict[str, int] = Field(default_factory=dict)  # section -> tokens


class OptimizedContext(BaseModel):
    compressed: bool = False
    token_usage: TokenBudget = Field(default_factory=TokenBudget)
    context: UnifiedContext


# ─── PackagedContext (Packager 输出) ──────────────────────────

class PackagedContext(BaseModel):
    provider: LLMProvider
    raw_prompt: str                 # 最终拼装好的 prompt 字符串
    sections: Dict[str, str]        # 各段原文 (debug 用)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Feedback / Trace ─────────────────────────────────────────

class TraceStep(BaseModel):
    step_name: str
    duration_ms: float
    input_preview: str
    output_preview: str
    token_count: Optional[int] = None


class Trace(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str
    raw_input: str
    steps: List[TraceStep] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    success: bool = False
    reward_score: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EvalMetrics(BaseModel):
    answer_quality: float = 0.0
    hallucination_score: float = 0.0
    tool_accuracy: float = 0.0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    success: bool = False
    reward_score: float = 0.0
```

---

## 三、各模块实现方案

### 3.1 Intent Understanding

```python
# context_os/intent/classifier.py

from typing import Tuple
from ..core.models import IntentType, GoalType, TaskSpec

class IntentClassifier:
    """意图分类器：使用 LLM 或分类模型识别用户意图"""

    def __init__(self, llm_client=None, fallback_mode: str = "regex"):
        self.llm_client = llm_client
        self.fallback_mode = fallback_mode

    async def classify(self, user_input: str) -> Tuple[IntentType, GoalType, float]:
        """
        返回 (intent, goal, confidence)
        优先使用 LLM，降级使用规则匹配
        """
        if self.llm_client:
            return await self._classify_with_llm(user_input)
        return self._classify_with_rules(user_input)

    def _classify_with_rules(self, user_input: str) -> Tuple[IntentType, GoalType, float]:
        """基于关键词规则的降级方案"""
        input_lower = user_input.lower()

        # Intent 规则
        if any(kw in input_lower for kw in ["debug", "fix", "bug", "crash", "error"]):
            return IntentType.DEBUGGING, GoalType.FIX, 0.7
        if any(kw in input_lower for kw in ["write", "create", "implement", "code"]):
            return IntentType.CODING, GoalType.GENERATE, 0.7
        # ... 更多规则

        return IntentType.QA, GoalType.EXPLAIN, 0.5

    async def _classify_with_llm(self, user_input: str):
        """使用 LLM 进行更准确的分类"""
        prompt = f"""Classify the following user request.
Return JSON with fields: intent, goal, confidence

Available intents: {[e.value for e in IntentType]}
Available goals: {[e.value for e in GoalType]}

User: {user_input}
"""
        result = await self.llm_client.complete(prompt, response_format="json")
        return IntentType(result["intent"]), GoalType(result["goal"]), result["confidence"]
```

```python
# context_os/intent/extractor.py

from ..core.models import Entity, ToolRequirement, KnowledgeRequirement

class EntityExtractor:
    """实体 & 参数提取"""

    def extract_entities(self, user_input: str, domain: str) -> list[Entity]:
        """提取命名实体"""
        # 可对接 NER 模型或 LLM
        pass

    def extract_tool_requirements(self, user_input: str) -> list[ToolRequirement]:
        """推断需要的工具"""
        pass

    def extract_knowledge_requirements(self, user_input: str) -> list[KnowledgeRequirement]:
        """推断需要的知识"""
        pass
```

```python
# context_os/intent/parser.py

from ..core.models import TaskSpec

class TaskParser:
    """组装 TaskSpec"""

    def __init__(self, classifier: IntentClassifier, extractor: EntityExtractor):
        self.classifier = classifier
        self.extractor = extractor

    async def parse(self, user_input: str) -> TaskSpec:
        intent, goal, confidence = await self.classifier.classify(user_input)
        entities = self.extractor.extract_entities(user_input, domain="")
        tools = self.extractor.extract_tool_requirements(user_input)
        knowledge = self.extractor.extract_knowledge_requirements(user_input)

        return TaskSpec(
            raw_input=user_input,
            intent=intent,
            goal=goal,
            entities=entities,
            tool_requirements=tools,
            knowledge_requirements=knowledge,
            confidence=confidence,
        )
```

---

### 3.2 Context Orchestrator

```python
# context_os/orchestrator/selector.py

from enum import Flag, auto
from ..core.models import TaskSpec, IntentType

class ContextFlag(Flag):
    IDENTITY = auto()
    CONVERSATION = auto()
    ENVIRONMENT = auto()
    MEMORY = auto()
    KNOWLEDGE = auto()
    TOOLS = auto()

# 意图 → 所需 Context 映射
INTENT_CONTEXT_MAP: dict[IntentType, ContextFlag] = {
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
    """动态上下文选择器"""

    def select(self, task: TaskSpec) -> ContextFlag:
        flags = INTENT_CONTEXT_MAP.get(task.intent, ContextFlag.CONVERSATION)

        # 根据约束调整
        if task.constraint.max_tokens and task.constraint.max_tokens < 8000:
            # Token 预算紧张时，去掉低优先级 Context
            flags &= ~ContextFlag.MEMORY
            flags &= ~ContextFlag.ENVIRONMENT

        return flags
```

```python
# context_os/orchestrator/router.py

from ..core.models import TaskSpec
from .selector import ContextFlag

class ContextRoute:
    """一条路由：某个 Context 该去哪里收集"""
    source: str          # "identity_provider" | "conversation_store" | ...
    flag: ContextFlag
    priority: int        # 越大越优先

class ContextRouter:
    """Context 路由器"""

    def route(self, task: TaskSpec, flags: ContextFlag) -> list[ContextRoute]:
        routes = []

        if ContextFlag.IDENTITY in flags:
            routes.append(ContextRoute(source="identity_provider", flag=ContextFlag.IDENTITY, priority=80))
        if ContextFlag.CONVERSATION in flags:
            routes.append(ContextRoute(source="conversation_store", flag=ContextFlag.CONVERSATION, priority=90))
        if ContextFlag.ENVIRONMENT in flags:
            routes.append(ContextRoute(source="env_provider", flag=ContextFlag.ENVIRONMENT, priority=50))
        if ContextFlag.MEMORY in flags:
            routes.append(ContextRoute(source="memory_store", flag=ContextFlag.MEMORY, priority=70))
        if ContextFlag.KNOWLEDGE in flags:
            routes.append(ContextRoute(source="knowledge_store", flag=ContextFlag.KNOWLEDGE, priority=60))
        if ContextFlag.TOOLS in flags:
            routes.append(ContextRoute(source="tool_registry", flag=ContextFlag.TOOLS, priority=40))

        # 按优先级降序排列
        routes.sort(key=lambda r: r.priority, reverse=True)
        return routes
```

---

### 3.3 Context Collection

```python
# context_os/collection/base.py

from abc import ABC, abstractmethod
from ..core.models import UnifiedContext

class BaseCollector(ABC):
    """Collector 基类"""

    @abstractmethod
    async def collect(self, context: UnifiedContext) -> UnifiedContext:
        """收集数据并填充到 context 中"""
        ...
```

```python
# context_os/collection/conversation.py

from .base import BaseCollector
from ..core.models import UnifiedContext, ConversationContext, ConversationTurn

class ConversationCollector(BaseCollector):
    """收集对话历史"""

    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self._history: list[ConversationTurn] = []

    def add_turn(self, role: str, content: str):
        self._history.append(ConversationTurn(role=role, content=content))
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]

    async def collect(self, context: UnifiedContext) -> UnifiedContext:
        context.conversation = ConversationContext(
            history=self._history[-self.max_history:],
            status="running",
        )
        return context
```

```python
# context_os/collection/environment.py

import os
import platform
import subprocess
from .base import BaseCollector
from ..core.models import UnifiedContext, EnvironmentContext

class EnvironmentCollector(BaseCollector):
    """收集系统环境信息"""

    async def collect(self, context: UnifiedContext) -> UnifiedContext:
        git_branch = self._get_git_branch()
        context.environment = EnvironmentContext(
            os=platform.system(),
            working_directory=os.getcwd(),
            git_branch=git_branch,
            runtime={
                "python_version": platform.python_version(),
                "cpu": platform.machine(),
            },
        )
        return context

    def _get_git_branch(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=3
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None
```

---

### 3.4 Context Builder

```python
# context_os/builder/builder.py

from ..collection.identity import IdentityCollector
from ..collection.conversation import ConversationCollector
from ..collection.environment import EnvironmentCollector
from ..memory.working import WorkingMemory
from ..memory.long_term import LongTermMemory
from ..orchestrator.router import ContextRouter
from ..orchestrator.selector import ContextSelector, ContextFlag
from ..core.models import TaskSpec, UnifiedContext
from ..core.errors import ContextBuildError

class ContextBuilder:
    """构建 UnifiedContext"""

    def __init__(
        self,
        selector: ContextSelector,
        router: ContextRouter,
        identity: IdentityCollector,
        conversation: ConversationCollector,
        environment: EnvironmentCollector,
        working_memory: WorkingMemory,
        long_term_memory: LongTermMemory,
    ):
        self.selector = selector
        self.router = router
        self.identity = identity
        self.conversation = conversation
        self.environment = environment
        self.working_memory = working_memory
        self.long_term_memory = long_term_memory

    async def build(self, task: TaskSpec) -> UnifiedContext:
        # 1. 选择需要哪些 Context
        flags = self.selector.select(task)

        # 2. 路由到收集器
        routes = self.router.route(task, flags)

        # 3. 并行收集
        ctx = UnifiedContext()
        collectors = {
            ContextFlag.IDENTITY: self.identity,
            ContextFlag.CONVERSATION: self.conversation,
            ContextFlag.ENVIRONMENT: self.environment,
        }

        import asyncio
        tasks = []
        for route in routes:
            collector = collectors.get(route.flag)
            if collector:
                tasks.append(collector.collect(ctx))

        # Memory 检索
        if ContextFlag.MEMORY in flags:
            memory_items = await self.long_term_memory.retrieve(task.raw_input)
            ctx.memory = memory_items

        if tasks:
            await asyncio.gather(*tasks)

        return ctx
```

---

### 3.5 Context Optimizer

```python
# context_os/optimizer/ranker.py

import numpy as np
from ..core.models import MemoryItem, KnowledgeChunk, RankingScore

class RelevanceRanker:
    """基于多维度的相关性排序"""

    def __init__(self, time_decay_hours: float = 24.0):
        self.time_decay_hours = time_decay_hours

    def rank_memories(
        self,
        items: list[MemoryItem],
        query_embedding: list[float] | None = None,
    ) -> list[MemoryItem]:
        """给记忆条目排序并返回 TopK"""
        from datetime import datetime, timezone

        for item in items:
            # 1. 语义相似度 (如果有 embedding)
            semantic_score = 0.0
            if query_embedding and item.embedding:
                semantic_score = self._cosine_similarity(query_embedding, item.embedding)

            # 2. 时间衰减
            age_hours = (datetime.now(timezone.utc) - item.timestamp).total_seconds() / 3600
            time_score = np.exp(-age_hours / self.time_decay_hours)

            # 3. 访问频率
            freq_score = np.log1p(item.access_count) / 10.0

            # 综合得分
            item.relevance_score = (
                0.5 * semantic_score +
                0.3 * time_score +
                0.2 * freq_score
            )

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        return items

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-8))
```

```python
# context_os/optimizer/compressor.py

import tiktoken
from ..core.models import MemoryItem, KnowledgeChunk

class ContextCompressor:
    """上下文压缩器"""

    def __init__(self, llm_client=None, model: str = "gpt-4"):
        self.llm_client = llm_client
        self.encoder = tiktoken.encoding_for_model(model) if model else None

    def count_tokens(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        return len(text) // 4  # 粗略估算

    async def compress_conversation(self, history: list[dict], max_tokens: int = 2000) -> str:
        """对对话历史做摘要压缩"""
        text = "\n".join(f"{t['role']}: {t['content']}" for t in history)
        if self.count_tokens(text) <= max_tokens:
            return text

        if self.llm_client:
            prompt = f"Summarize the following conversation in under {max_tokens} tokens:\n\n{text}"
            return await self.llm_client.complete(prompt)
        else:
            # 降级：保留最近一半
            return "\n".join(
                f"{t['role']}: {t['content']}"
                for t in history[-len(history)//2:]
            )

    async def semantic_compress(self, text: str, compression_ratio: float = 0.5) -> str:
        """语义压缩：保留关键信息，去除冗余"""
        if not self.llm_client:
            return text[:int(len(text) * compression_ratio)]

        prompt = f"""Compress the following text to {compression_ratio*100:.0f}% of its original length.
Preserve all key facts, entities, and relationships. Remove redundancy and filler.

Text:
{text}
"""
        return await self.llm_client.complete(prompt)
```

```python
# context_os/optimizer/budget.py

from ..core.models import TokenBudget, OptimizedContext, UnifiedContext

class TokenBudgetAllocator:
    """Token 预算分配器"""

    # 各模块默认比例
    DEFAULT_RATIOS = {
        "instruction": 0.10,
        "conversation": 0.20,
        "memory": 0.10,
        "knowledge": 0.45,
        "tools": 0.15,
    }

    def __init__(self, max_total_tokens: int = 128000):
        self.max_total_tokens = max_total_tokens
        self.ratios = dict(self.DEFAULT_RATIOS)

    def allocate(self, context: OptimizedContext) -> OptimizedContext:
        budget = TokenBudget(total=self.max_total_tokens)
        for section, ratio in self.ratios.items():
            budget.breakdown[section] = int(self.max_total_tokens * ratio)
        context.token_usage = budget
        return context

    def adjust_for_model(self, model_max_tokens: int):
        """根据模型能力调整总预算"""
        self.max_total_tokens = min(self.max_total_tokens, model_max_tokens)
```

---

### 3.6 Context Packager

```python
# context_os/packager/adapters/base.py

from abc import ABC, abstractmethod
from ...core.models import OptimizedContext, PackagedContext, LLMProvider

class BasePromptAdapter(ABC):
    """模型 Prompt 适配器"""

    provider: LLMProvider

    @abstractmethod
    def pack(self, context: OptimizedContext) -> PackagedContext:
        ...
```

```python
# context_os/packager/adapters/claude.py

from .base import BasePromptAdapter
from ...core.models import OptimizedContext, PackagedContext, LLMProvider

class ClaudePromptAdapter(BasePromptAdapter):
    """Claude XML Adapter"""

    provider = LLMProvider.CLAUDE

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        sections = {}

        # System
        system = """You are owencli, an AI assistant with access to various tools.
Follow the user's instructions carefully and use the available tools when needed."""
        sections["system"] = system

        # Memory
        if ctx.context.memory:
            memory_xml = "<memory>\n"
            for item in ctx.context.memory:
                memory_xml += f"  <{item.type.value}>\n    {item.content}\n  </{item.type.value}>\n"
            memory_xml += "</memory>"
            sections["memory"] = memory_xml

        # Knowledge
        if ctx.context.knowledge:
            knowledge_xml = "<knowledge>\n"
            for k in ctx.context.knowledge:
                knowledge_xml += f"  <source score=\"{k.score:.2f}\">\n    {k.content}\n  </source>\n"
            knowledge_xml += "</knowledge>"
            sections["knowledge"] = knowledge_xml

        # Tools
        if ctx.context.tools:
            tools_xml = "<tools>\n"
            for t in ctx.context.tools:
                tools_xml += f"  <tool name=\"{t.name}\">\n    {t.schema}\n  </tool>\n"
            tools_xml += "</tools>"
            sections["tools"] = tools_xml

        # Conversation
        if ctx.context.conversation and ctx.context.conversation.history:
            conv_xml = "<conversation>\n"
            for turn in ctx.context.conversation.history:
                conv_xml += f"  <{turn.role}>\n    {turn.content}\n  </{turn.role}>\n"
            conv_xml += "</conversation>"
            sections["conversation"] = conv_xml

        # 组装完整 prompt
        raw = "\n\n".join(sections.values())
        return PackagedContext(
            provider=self.provider,
            raw_prompt=raw,
            sections=sections,
        )
```

```python
# context_os/packager/adapters/registry.py

from ...core.models import LLMProvider
from .base import BasePromptAdapter
from .claude import ClaudePromptAdapter
from .openai import OpenAIPromptAdapter

class AdapterRegistry:
    """适配器注册中心"""

    def __init__(self):
        self._adapters: dict[LLMProvider, BasePromptAdapter] = {}

    def register(self, adapter: BasePromptAdapter):
        self._adapters[adapter.provider] = adapter

    def get(self, provider: LLMProvider) -> BasePromptAdapter:
        adapter = self._adapters.get(provider)
        if not adapter:
            raise ValueError(f"No adapter for provider: {provider}")
        return adapter

    def register_defaults(self):
        self.register(ClaudePromptAdapter())
        self.register(OpenAIPromptAdapter())


# 全局默认注册中心
default_registry = AdapterRegistry()
default_registry.register_defaults()
```

```python
# context_os/packager/packager.py

from ..core.models import OptimizedContext, PackagedContext, LLMProvider
from .adapters.registry import default_registry, AdapterRegistry

class ContextPackager:
    """上下文打包器"""

    def __init__(self, registry: AdapterRegistry = None):
        self.registry = registry or default_registry

    def pack(
        self,
        context: OptimizedContext,
        provider: LLMProvider = LLMProvider.CLAUDE,
    ) -> PackagedContext:
        adapter = self.registry.get(provider)
        return adapter.pack(context)
```

---

### 3.7 Feedback & Trace

```python
# context_os/feedback/evaluator.py

import time
from ..core.models import EvalMetrics, PackagedContext
from ..llm.client import BaseLLMClient

class QualityEvaluator:
    """评估 LLM 输出质量"""

    def __init__(self, llm_client: BaseLLMClient = None):
        self.llm_client = llm_client

    async def evaluate(
        self,
        packed: PackagedContext,
        llm_response: str,
        latency_ms: float,
        token_count: int,
    ) -> EvalMetrics:
        metrics = EvalMetrics(
            latency_ms=latency_ms,
            cost_usd=self._estimate_cost(token_count),
            success=self._check_success(llm_response),
        )

        if self.llm_client:
            quality = await self._rate_quality(packed.raw_prompt, llm_response)
            metrics.answer_quality = quality
            metrics.reward_score = quality * (0.8 if metrics.success else 0.2)

        return metrics

    def _estimate_cost(self, tokens: int) -> float:
        # 按 Claude 价格估算: $3/M input + $15/M output
        return tokens * 3 / 1_000_000

    def _check_success(self, response: str) -> bool:
        # 简单检查：没有错误信息
        return "error" not in response.lower()[:200]

    async def _rate_quality(self, prompt: str, response: str) -> float:
        prompt_template = f"""Rate the quality of the following AI response on a scale of 0-1.
Consider: accuracy, completeness, clarity, helpfulness.

Response: {response[:2000]}

Return only a number between 0 and 1.
"""
        result = await self.llm_client.complete(prompt_template)
        try:
            return max(0.0, min(1.0, float(result.strip())))
        except ValueError:
            return 0.5
```

```python
# context_os/feedback/tracer.py

import time
import json
from datetime import datetime
from pathlib import Path
from ..core.models import Trace, TraceStep

class Tracer:
    """执行轨迹记录器"""

    def __init__(self, storage_dir: str = "./traces"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_trace: Trace | None = None

    def start(self, task_id: str, raw_input: str) -> str:
        self._current_trace = Trace(task_id=task_id, raw_input=raw_input)
        return self._current_trace.id

    def step_begin(self, step_name: str) -> TraceStep:
        return TraceStep(step_name=step_name, duration_ms=0.0, input_preview="", output_preview="")

    def step_end(self, step: TraceStep, input_text: str, output_text: str):
        step.input_preview = input_text[:200]
        step.output_preview = output_text[:200]
        if self._current_trace:
            self._current_trace.steps.append(step)
            self._current_trace.total_latency_ms += step.duration_ms

    def finish(self, success: bool):
        if self._current_trace:
            self._current_trace.success = success
            self._save(self._current_trace)

    def _save(self, trace: Trace):
        path = self.storage_dir / f"trace_{trace.id}_{datetime.now():%Y%m%d_%H%M%S}.json"
        path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
```

---

## 四、Pipeline 编排入口

```python
# context_os/pipeline.py

import time
from .core.models import (
    TaskSpec, UnifiedContext, OptimizedContext,
    PackagedContext, LLMProvider,
)
from .intent.parser import TaskParser
from .orchestrator.selector import ContextSelector
from .orchestrator.router import ContextRouter
from .collection.identity import IdentityCollector
from .collection.conversation import ConversationCollector
from .collection.environment import EnvironmentCollector
from .builder.builder import ContextBuilder
from .optimizer.ranker import RelevanceRanker
from .optimizer.compressor import ContextCompressor
from .optimizer.budget import TokenBudgetAllocator
from .optimizer.optimizer import ContextOptimizer
from .packager.packager import ContextPackager
from .feedback.evaluator import QualityEvaluator
from .feedback.tracer import Tracer
from .memory.working import WorkingMemory
from .memory.long_term import LongTermMemory
from .llm.client import BaseLLMClient


class ContextOSPipeline:
    """
    Context-OS 主 Pipeline

    使用示例:
        pipeline = ContextOSPipeline(llm_client=my_client)
        result = await pipeline.run("帮我分析 K8s 集群 CrashLoopBackOff")
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        provider: LLMProvider = LLMProvider.CLAUDE,
        memory_dir: str = "./memory",
    ):
        # Intent
        self.task_parser = TaskParser(llm_client=llm_client)

        # Orchestrator
        self.selector = ContextSelector()
        self.router = ContextRouter()

        # Collection
        self.identity = IdentityCollector()
        self.conversation = ConversationCollector()
        self.environment = EnvironmentCollector()

        # Memory
        self.working_memory = WorkingMemory()
        self.long_term_memory = LongTermMemory(storage_dir=memory_dir)

        # Builder
        self.builder = ContextBuilder(
            selector=self.selector,
            router=self.router,
            identity=self.identity,
            conversation=self.conversation,
            environment=self.environment,
            working_memory=self.working_memory,
            long_term_memory=self.long_term_memory,
        )

        # Optimizer
        self.ranker = RelevanceRanker()
        self.compressor = ContextCompressor(llm_client=llm_client)
        self.budget = TokenBudgetAllocator()
        self.optimizer = ContextOptimizer(
            ranker=self.ranker,
            compressor=self.compressor,
            budget=self.budget,
        )

        # Packager
        self.packager = ContextPackager()

        # Feedback
        self.evaluator = QualityEvaluator(llm_client=llm_client)
        self.tracer = Tracer()

        # LLM
        self.llm_client = llm_client
        self.provider = provider

    async def run(self, user_input: str) -> dict:
        """执行完整的 Context Pipeline"""
        tracer_id = self.tracer.start(task_id="", raw_input=user_input)

        try:
            # Step 1: Intent Understanding
            step = self.tracer.step_begin("intent_understanding")
            t0 = time.time()
            task: TaskSpec = await self.task_parser.parse(user_input)
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, user_input, task.model_dump_json())

            # Step 2: Context Building
            step = self.tracer.step_begin("context_building")
            t0 = time.time()
            unified: UnifiedContext = await self.builder.build(task)
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, task.model_dump_json(), unified.model_dump_json())

            # Step 3: Context Optimization
            step = self.tracer.step_begin("context_optimization")
            t0 = time.time()
            optimized: OptimizedContext = await self.optimizer.optimize(unified, task)
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, unified.model_dump_json(), optimized.model_dump_json())

            # Step 4: Context Packaging
            step = self.tracer.step_begin("context_packaging")
            t0 = time.time()
            packaged: PackagedContext = self.packager.pack(optimized, self.provider)
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, optimized.model_dump_json(), packaged.raw_prompt[:500])

            # Step 5: LLM Inference
            step = self.tracer.step_begin("llm_inference")
            t0 = time.time()
            llm_response = await self.llm_client.complete(packaged.raw_prompt)
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, packaged.raw_prompt[:500], llm_response[:500])

            # Step 6: Feedback
            step = self.tracer.step_begin("feedback")
            t0 = time.time()
            metrics = await self.evaluator.evaluate(
                packed=packaged,
                llm_response=llm_response,
                latency_ms=step.duration_ms,
                token_count=optimized.token_usage.used,
            )
            step.duration_ms = (time.time() - t0) * 1000
            self.tracer.step_end(step, packaged.raw_prompt[:200], metrics.model_dump_json())

            # 更新记忆
            await self.long_term_memory.store(
                content=f"Task: {task.raw_input}\nResult: {llm_response[:500]}",
                memory_type="episodic",
            )

            self.tracer.finish(success=metrics.success)

            return {
                "response": llm_response,
                "metrics": metrics.model_dump(),
                "trace_id": tracer_id,
                "task_spec": task.model_dump(),
            }

        except Exception as e:
            self.tracer.finish(success=False)
            raise
```

---

## 五、LLM Client 抽象

```python
# context_os/llm/client.py

from abc import ABC, abstractmethod
from typing import Any

class BaseLLMClient(ABC):
    """LLM 客户端抽象"""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: str | None = None,  # "json" | "text"
    ) -> str | dict[str, Any]:
        ...
```

```python
# context_os/llm/anthropic_client.py

import os
from typing import Any
from anthropic import AsyncAnthropic
from .client import BaseLLMClient

class AnthropicClient(BaseLLMClient):
    """Anthropic Claude 实现"""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: str | None = None,
    ) -> str | dict[str, Any]:
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        text = response.content[0].text

        if response_format == "json":
            import json
            return json.loads(text)
        return text
```

---

## 六、依赖配置

### `pyproject.toml`

```toml
[project]
name = "context-os"
version = "0.1.0"
description = "Context-OS: AI Agent Context Management System"
requires-python = ">=3.11"

dependencies = [
    "pydantic>=2.0",
    "anthropic>=0.30",
    "openai>=1.0",
    "tiktoken>=0.5",
    "numpy>=1.24",
    "httpx>=0.25",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "ruff>=0.1",
    "mypy>=1.0",
]
vector = [
    "chromadb>=0.4",
    "qdrant-client>=1.0",
]
graph = [
    "neo4j>=5.0",
]
trace = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
]

[tool.ruff]
line-length = 100
target-version = "py311"
```

---

## 七、执行流程时序图

```
User                     Pipeline              Intent           Orchestrator    Builder/Optimizer    Packager       LLM          Memory/Feedback
 │                          │                     │                  │                │                  │            │               │
 │── 输入请求 ──────────────▶│                     │                  │                │                  │            │               │
 │                          │── parse() ─────────▶│                 │                │                  │            │               │
 │                          │◀──── TaskSpec ──────│                 │                │                  │            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── select/route() ────│────────────────▶│                │                  │            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── build() ───────────│─────────────────────────────────▶│                  │            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │  ┌─ IdentityCollect  │                  │               │                  │            │               │
 │                          │  ├─ ConvsCollect     │                  │               │                  │            │               │
 │                          │  ├─ EnvCollect       │  ← 并行收集      │               │                  │            │               │
 │                          │  ├─ MemoryRetrieve   │                  │               │                  │            │── retrieve ─▶│
 │                          │  └─ KnowledgeRetrieve│                  │               │                  │            │              │
 │                          │◀── UnifiedContext ───│─────────────────────────────────│                  │            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── optimize() ────────│─────────────────────────────────▶│                  │            │               │
 │                          │  ├─ Rank             │                  │               │                  │            │               │
 │                          │  ├─ Compress         │                  │               │                  │            │               │
 │                          │  └─ Budget           │                  │               │                  │            │               │
 │                          │◀── OptimizedCtx ─────│─────────────────────────────────│                  │            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── pack() ────────────│───────────────────────────────────────────────────▶│            │               │
 │                          │◀── PackagedCtx ──────│───────────────────────────────────────────────────│            │               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── complete() ────────│───────────────────────────────────────────────────────────────▶│               │
 │                          │◀── Response ─────────│────────────────────────────────────────────────────────────────│               │
 │                          │                      │                  │               │                  │            │               │
 │                          │── evaluate() ────────│───────────────────────────────────────────────────────────────────▶│               │
 │                          │── update_memory() ───│───────────────────────────────────────────────────────────────────▶│               │
 │                          │                      │                  │               │                  │            │               │
 │◀── 返回结果 ─────────────│                     │                  │               │                  │            │               │
```

---

## 八、配置与环境变量

### `.env.example`

```bash
# LLM Provider
LLM_PROVIDER=anthropic          # anthropic | openai
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Model
CLAUDE_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o

# Memory
MEMORY_STORAGE_DIR=./data/memory
MEMORY_MAX_TOKENS=128000

# Trace
TRACE_ENABLED=true
TRACE_STORAGE_DIR=./data/traces

# Vector DB (optional)
VECTOR_DB_PROVIDER=chroma        # chroma | qdrant
CHROMA_PERSIST_DIR=./data/chroma
```

---

## 九、快速开始示例

```python
# examples/basic_pipeline.py

import asyncio
from context_os.pipeline import ContextOSPipeline
from context_os.llm.anthropic_client import AnthropicClient

async def main():
    # 初始化 LLM Client
    llm = AnthropicClient()

    # 初始化 Pipeline
    pipeline = ContextOSPipeline(llm_client=llm)

    # 运行
    result = await pipeline.run("帮我分析一下当前项目的代码结构")

    print(f"Response: {result['response']}")
    print(f"Trace ID: {result['trace_id']}")
    print(f"Quality Score: {result['metrics']['reward_score']}")

asyncio.run(main())
```

---

## 十、后续演进方向

| 阶段 | 功能 | 预计工作量 |
|------|------|-----------|
| **P0** | 基础 Pipeline + Intent + Builder + Packager (Claude) | ~500 行核心代码 |
| **P1** | Optimizer (Ranker + Compressor + Budget) | ~300 行 |
| **P2** | Memory 持久化 (SQLite + 向量检索) | ~400 行 |
| **P3** | Feedback + Trace + Eval | ~300 行 |
| **P4** | 多模型 Adapter (OpenAI / Gemini / Qwen) | ~200 行 |
| **P5** | 知识图谱 (Semantic Memory) | ~500 行 |

---

## 十一、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据验证 | Pydantic v2 | 类型安全、序列化/反序列化开箱即用 |
| LLM 调用 | 自定义抽象层 | 避免与特定 SDK 耦合，方便切换模型 |
| 异步 | asyncio + async/await | I/O 密集型场景（多次 LLM 调用）需要并发 |
| 配置 | 环境变量 + Pydantic Settings | 12-factor 应用原则 |
| 测试 | pytest + pytest-asyncio | 成熟的异步测试生态 |
| 包管理 | pyproject.toml (PEP 621) | 现代 Python 标准 |
