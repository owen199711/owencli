"""短期记忆（Short-Term Memory）。

跨越单个任务窗口，在对话 Session 周期内持续存在的记忆。
使用 PostgreSQL 持久化，与 Session 生命周期绑定。

存储内容:
    - 当前 Session 的完整对话历史（压缩后）
    - Session 内的用户临时偏好
    - 当前 Session 已完成的子任务
    - Session 内的错误和恢复记录
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)


class ShortTermMemory:
    """短期记忆 — Session 级记忆。

    会话结束后会自动过期清理。

    Args:
        session_id: 关联的 Session ID。
        store: PostgreSQL 存储层实例。
        ttl_hours: Session 记忆的存活时间（小时），默认 24。
    """

    def __init__(
        self,
        session_id: str,
        store: SQLiteStore,
        ttl_hours: int = 24,
    ):
        self.session_id = session_id
        self.store = store
        self.ttl_hours = ttl_hours
        logger.info(
            "ShortTermMemory initialized: session=%s, ttl=%dh",
            session_id, ttl_hours,
        )

    async def add(
        self,
        content: str,
        metadata: Optional[dict] = None,
        user_id: str = "anonymous",
    ) -> str:
        """添加一条短期记忆。

        Args:
            content: 记忆内容。
            metadata: 附加元数据，如 {"category": "preference", "key": "language"}。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        mem_id = uuid.uuid4().hex
        await self.store.save_memory(
            id=mem_id,
            type="short_term",
            content=content,
            session_id=self.session_id,
            user_id=user_id,
            metadata=metadata,
            ttl_seconds=self.ttl_hours * 3600,
        )
        logger.debug(
            "STM added: id=%s, session=%s, meta=%s",
            mem_id, self.session_id, metadata,
        )
        return mem_id

    async def add_preference(self, key: str, value: Any, user_id: str = "anonymous") -> str:
        """快捷方法：添加用户偏好。

        Args:
            key: 偏好键名。
            value: 偏好值。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        return await self.add(
            content=f"preference:{key}={value}",
            metadata={"category": "preference", "key": key, "value": str(value)},
            user_id=user_id,
        )

    async def add_task_completion(self, task_name: str, result: str, user_id: str = "anonymous") -> str:
        """快捷方法：记录子任务完成。

        Args:
            task_name: 子任务名称。
            result: 任务结果摘要。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        return await self.add(
            content=f"Task completed: {task_name}\nResult: {result}",
            metadata={"category": "task", "task": task_name, "status": "completed"},
            user_id=user_id,
        )

    async def add_error_record(
        self,
        error: str,
        recovery: str = "",
        user_id: str = "anonymous",
    ) -> str:
        """快捷方法：记录错误和恢复。

        Args:
            error: 错误描述。
            recovery: 恢复措施。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        content = f"Error: {error}"
        if recovery:
            content += f"\nRecovery: {recovery}"
        return await self.add(
            content=content,
            metadata={"category": "error", "error": error, "recovery": recovery},
            user_id=user_id,
        )

    async def get_all(self) -> list[MemoryItem]:
        """获取当前 Session 的所有短期记忆。

        Returns:
            MemoryItem 列表。
        """
        results = await self.store.query_memories(
            type="short_term",
            session_id=self.session_id,
        )
        items = [MemoryItem(**r) for r in results]
        logger.debug("STM get_all: session=%s, count=%d", self.session_id, len(items))
        return items

    async def get_preferences(self) -> dict[str, Any]:
        """获取当前 Session 的用户偏好。

        Returns:
            偏好键值对字典。
        """
        results = await self.store.query_memories(
            type="short_term",
            session_id=self.session_id,
        )
        prefs = {}
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("category") == "preference":
                prefs[meta["key"]] = meta.get("value")
        logger.debug("STM preferences: %d entries", len(prefs))
        return prefs

    async def get_tasks(self) -> list[dict[str, Any]]:
        """获取当前 Session 已完成的子任务。

        Returns:
            任务记录列表。
        """
        results = await self.store.query_memories(
            type="short_term",
            session_id=self.session_id,
        )
        tasks = []
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("category") == "task":
                tasks.append({
                    "task": meta.get("task"),
                    "status": meta.get("status"),
                    "result": r.get("content"),
                })
        return tasks

    async def clear(self) -> None:
        """清除当前 Session 的所有短期记忆。"""
        results = await self.store.query_memories(
            type="short_term",
            session_id=self.session_id,
        )
        for r in results:
            await self.store.delete_memory(r["id"])
        logger.info("STM cleared: session=%s, removed=%d", self.session_id, len(results))

    async def get_summary(self) -> str:
        """生成当前 Session 的短期记忆摘要。

        Returns:
            压缩后的摘要文本。
        """
        items = await self.get_all()
        if not items:
            return ""

        parts = []
        for item in items:
            meta = item.metadata or {}
            category = meta.get("category", "general")
            parts.append(f"[{category}] {item.content}")

        summary = "\n".join(parts)
        logger.debug("STM summary generated: %d chars", len(summary))
        return summary
