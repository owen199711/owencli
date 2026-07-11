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
    SESSION = "session"
    LONG_TERM = "long_term"
    EXPERIENCE = "experience"
    SEMANTIC = "semantic"
    KNOWLEDGE = "knowledge"


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


# ─── Intent Understanding ─────────────────────────────────────

class Entity(BaseModel):
    type: str
    value: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None
    timeout_seconds: Optional[int] = None
    allowed_tools: Optional[List[str]] = None


class ToolRequirement(BaseModel):
    name: str
    required: bool = True
    permission: Optional[str] = None


class KnowledgeRequirement(BaseModel):
    domain: str
    query: str
    top_k: int = 5


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
    confidence: float = 0.0


# ─── Context Data ─────────────────────────────────────────────

class UserProfile(BaseModel):
    user_id: str
    role: str
    permission: str = "readonly"
    language: str = "zh-CN"
    skill_level: str = "intermediate"
    organization: Optional[str] = None
    tenant: Optional[str] = None
    team: Optional[str] = None


class ConversationTurn(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationContext(BaseModel):
    history: List[ConversationTurn] = Field(default_factory=list)
    current_topic: Optional[str] = None
    current_step: Optional[str] = None
    total_steps: Optional[int] = None
    status: str = "idle"
    task_graph: List[str] = Field(default_factory=list)


class EnvironmentContext(BaseModel):
    os: Optional[str] = None
    working_directory: Optional[str] = None
    git_branch: Optional[str] = None
    git_repo: Optional[str] = None
    runtime: Dict[str, Any] = Field(default_factory=dict)
    mcp_servers: Dict[str, str] = Field(default_factory=dict)
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
    source: str
    content: str
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Knowledge Nodes (MEMORY_SYSTEM_DESIGN §7.3) ─────────────────

class EntityNode(BaseModel):
    """Triple 节点 — "X 是什么？X 跟 Y 什么关系？"

    对应 concepts 表中 node_type='triple' 的记录。
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    node_type: str = "triple"
    attributes: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    confidence: float = 1.0
    user_id: str = "anonymous"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    # 关联的边（运行时填充，不持久化到此模型）
    relations: List["ConceptRelation"] = Field(default_factory=list)


class PropertyNode(BaseModel):
    """Property 节点 — "X 的属性是什么？"

    对应 knowledge_properties 表。
    去重规则：(entity, property_name)，值冲突按 source_reliability 裁决。
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    entity: str
    property_name: str
    value: str
    source_reliability: float = 0.5
    confidence: float = 0.7
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class DocumentNode(BaseModel):
    """Document 节点 — 长文本语义检索块。

    对应 knowledge_documents 表。
    去重规则：embedding sim > 0.95 跳过。
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: str
    embedding: Optional[List[float]] = None
    source: str = ""
    chunk_index: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaxonomyNode(BaseModel):
    """Taxonomy 节点 — "X 属于哪类？"

    对应 knowledge_taxonomy 表。
    去重规则：(name) 去重，更新 parent。
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    parent: str = ""
    level: int = 0
    description: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConceptRelation(BaseModel):
    """概念关系边（Triple 的 relation）。

    对应 concept_relations 表。
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ToolContext(BaseModel):
    name: str
    schema: Dict[str, Any] = Field(default_factory=dict)
    permission: str = "readonly"
    state: Dict[str, Any] = Field(default_factory=dict)


# ─── Unified Context ──────────────────────────────────────────

class UnifiedContext(BaseModel):
    identity: Optional[UserProfile] = None
    conversation: Optional[ConversationContext] = None
    environment: Optional[EnvironmentContext] = None
    memory: List[MemoryItem] = Field(default_factory=list)
    knowledge: List[KnowledgeChunk] = Field(default_factory=list)
    tools: List[ToolContext] = Field(default_factory=list)


class TokenBudget(BaseModel):
    total: int = 0
    used: int = 0
    breakdown: Dict[str, int] = Field(default_factory=dict)


class OptimizedContext(BaseModel):
    compressed: bool = False
    token_usage: TokenBudget = Field(default_factory=TokenBudget)
    context: UnifiedContext


class PackagedContext(BaseModel):
    provider: LLMProvider
    raw_prompt: str
    sections: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Feedback & Trace ─────────────────────────────────────────

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
    task_importance: float = 0.5
