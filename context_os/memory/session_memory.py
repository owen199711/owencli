"""会话记忆（Session Memory）。

跨越单个任务窗口，在对话 Session 周期内持续存在的记忆。
使用 SQLite 持久化，与 Session 生命周期绑定。
合并了原 TaskMemory 的任务执行记录功能。

存储内容:
    - 当前 Session 的完整对话历史（压缩后）
    - Session 内的用户临时偏好
    - 当前 Session 已完成的子任务
    - Session 内的错误和恢复记录
    - 任务执行记录（输入/输出/token/耗时）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)


class SessionMemory:
    """会话记忆 — Session 级记忆（原 ShortTermMemory，合并 TaskMemory）。

    会话结束后会自动过期清理。

    Args:
        session_id: 关联的 Session ID。
        store: SQLite 存储层实例。
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
            "SessionMemory initialized: session=%s, ttl=%dh",
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
            type="session",
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
            type="session",
            session_id=self.session_id,
        )
        items: list[MemoryItem] = []
        for r in results:
            try:
                items.append(MemoryItem(**r))
            except Exception as e:
                logger.warning(
                    "MemoryItem deserialization failed (id=%s): %s",
                    r.get("id", "?"), e,
                )
        logger.debug("STM get_all: session=%s, count=%d", self.session_id, len(items))
        return items

    async def get_preferences(self) -> dict[str, Any]:
        """获取当前 Session 的用户偏好。

        Returns:
            偏好键值对字典。
        """
        results = await self.store.query_memories(
            type="session",
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
            type="session",
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
            type="session",
            session_id=self.session_id,
        )
        for r in results:
            await self.store.delete_memory(r["id"])
        logger.info("STM cleared: session=%s, removed=%d", self.session_id, len(results))

    # ── Task 记录（原 TaskMemory，已合并） ──────────────────────

    async def save_task(
        self,
        task_type: str,
        intent: str,
        input_text: str,
        user_id: str = "anonymous",
    ) -> str:
        """记录一个待执行的任务（原 TaskMemory.save）。

        Args:
            task_type: 任务类型。
            intent: 意图描述。
            input_text: 输入内容。
            user_id: 用户 ID。

        Returns:
            任务记录 ID。
        """
        return await self.add(
            content=input_text,
            metadata={
                "category": "task_record",
                "task_type": task_type,
                "intent": intent,
                "status": "pending",
            },
            user_id=user_id,
        )

    async def complete_task(
        self,
        task_id: str,
        output: str,
        token_used: int = 0,
        duration_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """标记任务为完成或失败（原 TaskMemory.complete）。

        通过更新已存储记录的 metadata 实现。

        Args:
            task_id: 任务记录 ID。
            output: 输出内容。
            token_used: 消耗的 token 数。
            duration_ms: 耗时（毫秒）。
            error: 错误信息（如有则标记为 failed）。
        """
        import json

        record = await self.store.get_memory(task_id)
        if not record:
            logger.warning("Task not found: id=%s", task_id)
            return

        meta = record.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        meta["output"] = output
        meta["token_used"] = token_used
        meta["duration_ms"] = duration_ms
        meta["status"] = "failed" if error else "completed"
        if error:
            meta["error"] = error
        meta["completed_at"] = datetime.now(timezone.utc).isoformat()

        await self.store.save_memory(
            id=task_id,
            type="session",
            content=record.get("content", ""),
            session_id=self.session_id,
            user_id=record.get("user_id", "anonymous"),
            metadata=meta,
            ttl_seconds=self.ttl_hours * 3600,
        )
        logger.debug(
            "Task completed: id=%s, status=%s, token=%d, duration=%dms",
            task_id, meta["status"], token_used, duration_ms,
        )

    async def query_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """查询最近的完整任务执行记录（原 TaskMemory.query）。

        Args:
            limit: 返回数量上限。

        Returns:
            任务记录列表，每项为 dict（含 metadata 中的 task 字段）。
        """
        results = await self.store.query_memories(
            type="session",
            session_id=self.session_id,
            top_k=limit,
        )
        tasks = []
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("category") == "task_record":
                tasks.append(r)
        logger.debug("Task query: %d records found", len(tasks))
        return tasks

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

    # ── 候选缓冲区（Phase 3: 写入决策暂存） ─────────────────

    async def add_pending_candidate(
        self,
        content: str,
        entities: Optional[dict[str, Any]] = None,
        turn_number: int = 0,
        user_id: str = "anonymous",
    ) -> str:
        """向候选缓冲区添加一条待评估的写入候选。

        此类记录在 Session 层中存储，待批量写入决策触发后，
        进行 Layer 2/3 评估和分流存储。状态为 "pending"。

        Args:
            content: 候选内容（清洗后的文本）。
            entities: 提取的实体（person/action/amount 等）。
            turn_number: 对话轮次编号。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        meta = {
            "category": "write_candidate",
            "status": "pending",
            "turn_number": turn_number,
        }
        if entities:
            meta.update(entities)
        return await self.add(content=content, metadata=meta, user_id=user_id)

    async def query_pending(
        self,
        query: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """查询候选区中 status="pending" 的记录。

        用于批量写入决策触发和联合检索。

        Args:
            query: 可选的查询文本（暂不支持语义检索，做简单内容匹配）。
            top_k: 返回上限。

        Returns:
            待处理候选记录列表。
        """
        results = await self.store.query_memories(
            type="session",
            session_id=self.session_id,
            top_k=500,
        )
        pending = []
        for r in results:
            meta = r.get("metadata", {})
            if not isinstance(meta, dict):
                continue
            if meta.get("category") != "write_candidate":
                continue
            if meta.get("status") != "pending":
                continue
            # 简单内容匹配
            if query:
                content = r.get("content", "").lower()
                if query.lower() not in content:
                    continue
            pending.append(r)
            if len(pending) >= top_k:
                break

        logger.debug("Pending candidates: %d (query='%s')", len(pending), query or "all")
        return pending

    async def update_pending_status(
        self,
        candidate_id: str,
        status: str,
    ) -> bool:
        """更新候选记录的状态。

        Args:
            candidate_id: 候选记录 ID。
            status: 新状态（"written" / "discarded" / "processing"）。

        Returns:
            是否更新成功。
        """
        import json

        record = await self.store.get_memory(candidate_id)
        if not record:
            return False

        meta = record.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        meta["status"] = status
        meta["processed_at"] = datetime.now(timezone.utc).isoformat()

        await self.store.save_memory(
            id=candidate_id,
            type="session",
            content=record.get("content", ""),
            session_id=self.session_id,
            user_id=record.get("user_id", "anonymous"),
            metadata=meta,
            ttl_seconds=self.ttl_hours * 3600,
        )
        logger.debug("Pending status updated: id=%s → %s", candidate_id, status)
        return True

    async def get_pending_count(self) -> int:
        """获取当前候选区中 pending 记录数。

        Returns:
            Pending 数量。
        """
        results = await self.store.query_memories(
            type="session",
            session_id=self.session_id,
            top_k=500,
        )
        count = sum(
            1 for r in results
            if isinstance(r.get("metadata"), dict)
            and r["metadata"].get("category") == "write_candidate"
            and r["metadata"].get("status") == "pending"
        )
        return count
