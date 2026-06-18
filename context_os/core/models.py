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
