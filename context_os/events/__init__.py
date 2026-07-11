"""Events 包 — 进程内 pub/sub 事件系统。

提供统一的异步事件总线，用于解除记忆系统各模块间的直接耦合。
"""

from context_os.events.bus import EventBus
from context_os.events.types import (
    JournalCreatedEvent,
    WriteDecisionCompletedEvent,
    MemoryWrittenEvent,
    KnowledgeEvent,
    EVENT_JOURNAL_CREATED,
    EVENT_JOURNAL_PROCESSED,
    EVENT_WRITE_DECISION_COMPLETED,
    EVENT_MEMORY_WRITTEN,
    EVENT_KNOWLEDGE_READY,
)

__all__ = [
    "EventBus",
    "JournalCreatedEvent",
    "WriteDecisionCompletedEvent",
    "MemoryWrittenEvent",
    "KnowledgeEvent",
    "EVENT_JOURNAL_CREATED",
    "EVENT_JOURNAL_PROCESSED",
    "EVENT_WRITE_DECISION_COMPLETED",
    "EVENT_MEMORY_WRITTEN",
    "EVENT_KNOWLEDGE_READY",
]
