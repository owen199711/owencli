"""TaskMemory — 任务执行记录。

表由 SQLiteStore._DDL 统一创建。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class TaskMemory:
    """任务执行记录。

    追踪每个任务的完整生命周期：创建 → 执行 → 完成/失败，
    记录 token 消耗、耗时和错误信息。

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("TaskMemory initialized (user=%s)", user_id)

    async def save(self, task_type: str, intent: str, input_text: str) -> str:
        """记录一个待执行的任务。

        Args:
            task_type: 任务类型。
            intent: 意图描述。
            input_text: 输入内容。

        Returns:
            任务 ID。
        """
        tid = uuid.uuid4().hex[:12]
        await self.store.execute(
            "INSERT INTO task_records (id, user_id, task_type, intent, status, input, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                tid,
                self.user_id,
                task_type,
                intent,
                "pending",
                input_text,
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        logger.debug("Task saved: id=%s, type=%s", tid, task_type)
        return tid

    async def complete(
        self,
        task_id: str,
        output: str,
        token_used: int = 0,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> None:
        """标记任务为完成或失败。

        Args:
            task_id: 任务 ID。
            output: 输出内容。
            token_used: 消耗的 token 数。
            duration_ms: 耗时（毫秒）。
            error: 错误信息（如有则标记为 failed）。
        """
        status = "failed" if error else "completed"
        await self.store.execute(
            "UPDATE task_records SET status = ?, output = ?, error = ?, "
            "token_used = ?, duration_ms = ?, completed_at = ? WHERE id = ?",
            [
                status,
                output,
                error,
                token_used,
                duration_ms,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ],
        )
        logger.debug("Task completed: id=%s, status=%s, token=%d, duration=%dms",
                     task_id, status, token_used, duration_ms)

    async def query(self, limit: int = 50) -> list[dict]:
        """查询最近的任务执行记录。

        Args:
            limit: 返回数量上限。

        Returns:
            任务记录列表，每项为 dict。
        """
        rows = await self.store.query(
            "SELECT * FROM task_records WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [self.user_id, limit],
        )
        return [dict(r) for r in rows]
