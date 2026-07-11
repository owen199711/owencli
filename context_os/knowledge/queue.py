"""KnowledgeQueue — 知识提取任务队列。

替换旧的 LTM 扫描模式（BackgroundConceptWorker 扫描 LTM 表）。
改为事件驱动：Memory + Knowledge 各自订阅 JournalCreatedEvent，
需要 LLM 提取知识时 enqueue 到本队列，KnowledgeUpdater 异步消费。
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger

if TYPE_CHECKING:
    from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class KnowledgeQueue:
    """知识提取任务队列。

    职责:
    1. enqueue(content): 向队列添加待提取知识的文本
    2. dequeue_batch(n): 取出一批 pending 任务
    3. mark_done(id) / mark_failed(id): 标记完成/失败

    使用方式:
        queue = KnowledgeQueue(store=store)
        await queue.enqueue("用户说他是 Python 开发者")
        tasks = await queue.dequeue_batch(10)
    """

    def __init__(self, store: "SQLiteStore") -> None:
        self._store = store

    async def enqueue(
        self,
        content: str,
        user_id: str = "anonymous",
        source: str = "channel_b",
        priority: int = 0,
    ) -> str:
        """向队列添加一条任务。

        Args:
            content: 待提取知识的文本内容。
            user_id: 用户 ID。
            source: 来源（'channel_a' 规则提取 / 'channel_b' LLM 异步提取）。
            priority: 优先级。

        Returns:
            队列记录 ID。
        """
        return await self._store.enqueue_knowledge(
            content=content, user_id=user_id, source=source, priority=priority,
        )

    async def dequeue_batch(
        self,
        batch_size: int = 10,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """取出一批待处理任务。

        Args:
            batch_size: 每批数量。
            user_id: 按用户筛选。

        Returns:
            任务列表，每条含 id/content/user_id/source/priority。
        """
        return await self._store.dequeue_knowledge_batch(
            batch_size=batch_size, user_id=user_id,
        )

    async def mark_done(self, queue_id: str) -> None:
        """标记任务完成。"""
        await self._store.mark_knowledge_done(queue_id)

    async def mark_failed(self, queue_id: str, error: str = "") -> None:
        """标记任务失败（最多重试 3 次）。"""
        await self._store.mark_knowledge_failed(queue_id, error)

    async def get_pending_count(self, user_id: Optional[str] = None) -> int:
        """查询待处理任务数量。"""
        tasks = await self._store.dequeue_knowledge_batch(
            batch_size=1000, user_id=user_id,
        )
        return len(tasks)
