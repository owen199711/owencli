"""JournalStore — 预写日志（WAL）层封装。

Journal 不是记忆，是事件日志。所有持久化写入先落地到 Journal，
再通过 EventBus 通知订阅者异步处理（Write Decision + Knowledge Extract）。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger
from context_os.events.types import JournalCreatedEvent, EVENT_JOURNAL_CREATED

if TYPE_CHECKING:
    from context_os.events.bus import EventBus
    from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# ── 批量触发常量 ──
PENDING_THRESHOLD = 5     # pending ≥ 5 条触发批量处理
TURN_THRESHOLD = 10        # 对话轮次 ≥ 10 触发
TIMER_SECONDS = 300        # 距上次处理 > 5 分钟触发


class JournalStore:
    """Journal 预写日志封装。

    职责:
    1. append(): 每轮 Pipeline 自动写入（零门槛），发布 JournalCreatedEvent
    2. query_pending(): 查询待处理记录
    3. mark_processed() / mark_discarded(): 更新处理状态
    4. get_pending_count(): 查询待处理数量，供批量触发判断

    使用方式:
        journal = JournalStore(store=store, event_bus=bus)
        await journal.append(user_id=..., session_id=..., ...)
    """

    def __init__(
        self,
        store: "SQLiteStore",
        event_bus: "EventBus",
    ) -> None:
        self._store = store
        self._event_bus = event_bus

    async def append(
        self,
        user_id: str,
        session_id: str,
        round_id: int,
        raw_input: str,
        raw_output: str = "",
        entities: Optional[dict[str, Any]] = None,
        task_intent: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """写入一条 Journal 记录并广播事件。

        Args:
            user_id: 用户 ID。
            session_id: 会话 ID。
            round_id: 对话轮次。
            raw_input: 用户原始输入。
            raw_output: LLM 回复（建议截取前 2000 字符）。
            entities: 提取的实体 dict。
            task_intent: 任务意图。
            metadata: 附加元数据。

        Returns:
            journal_id。
        """
        journal_id = uuid.uuid4().hex

        await self._store.save_journal_entry(
            journal_id=journal_id,
            user_id=user_id,
            session_id=session_id,
            round_id=round_id,
            raw_input=raw_input,
            raw_output=raw_output[:2000] if raw_output else "",
            entities=entities or {},
            task_intent=task_intent,
            metadata=metadata or {},
        )

        # 发布事件
        event = JournalCreatedEvent(
            journal_id=journal_id,
            user_id=user_id,
            session_id=session_id,
            round_id=round_id,
            raw_input=raw_input,
            raw_output=raw_output[:2000] if raw_output else "",
            entities=entities or {},
            task_intent=task_intent,
        )
        await self._event_bus.publish(event)

        logger.debug("Journal appended: id=%s, round=%d", journal_id, round_id)
        return journal_id

    async def query_pending(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询待处理记录。"""
        return await self._store.query_journal_pending(
            user_id=user_id, session_id=session_id, limit=limit,
        )

    async def mark_processed(self, journal_id: str) -> None:
        """标记为已处理。"""
        await self._store.update_journal_status(journal_id, "processed")

    async def mark_discarded(self, journal_id: str) -> None:
        """标记为已丢弃。"""
        await self._store.update_journal_status(journal_id, "discarded")

    async def get_pending_count(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """查询待处理记录数量（用于批量触发判断）。"""
        pending = await self._store.query_journal_pending(
            user_id=user_id, session_id=session_id, limit=1000,
        )
        return len(pending)
