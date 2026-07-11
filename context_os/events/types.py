"""事件数据类型定义。

每个事件携带足够的信息让订阅者独立决策，
避免订阅者需要回查 Journal / Store 获取上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── 事件类型常量（字符串 key）──

EVENT_JOURNAL_CREATED = "journal:created"
EVENT_JOURNAL_PROCESSED = "journal:processed"
EVENT_WRITE_DECISION_COMPLETED = "write_decision:completed"
EVENT_MEMORY_WRITTEN = "memory:written"
EVENT_KNOWLEDGE_READY = "knowledge:ready"


# ── 事件数据类 ──


@dataclass
class JournalCreatedEvent:
    """Journal 记录写入后发布。

    MemoryWriteSubscriber + KnowledgeExtractSubscriber 各自订阅此事件。
    """

    journal_id: str
    user_id: str
    session_id: str
    round_id: int
    raw_input: str
    raw_output: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    task_intent: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WriteDecisionCompletedEvent:
    """Write Decision 三层判定完成后发布。

    携带判定结果，供 MemoryRouter / 日志 / 监控消费。
    """

    journal_id: str
    user_id: str
    should_store: bool
    score: float
    layer: int  # 1 | 2 | 3
    reason: str
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MemoryWrittenEvent:
    """记忆写入完成后发布。

    携带写入目标信息，供 Maintainer / 索引更新消费。
    """

    journal_id: str
    user_id: str
    target: str  # "long_term" | "experience"
    memory_id: str  # 写入后的记录 ID
    category: str = ""  # "fact" | "summary"（LongTerm）或 tag 列表（Experience）
    tags: list[str] = field(default_factory=list)
    entity_key: str = ""
    written_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class KnowledgeEvent:
    """Knowledge 提取完成后发布。

    携带提取结果，供知识图谱增量更新 / 通知消费。
    """

    journal_id: str
    user_id: str
    triples: list[dict[str, str]] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    taxonomy: list[dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
