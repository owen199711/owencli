"""ReflectionMemory — Agent 自我反思与经验教训。

参考 Java: com.owencli.contextos.memory.ReflectionMemory
存储结构：reflections 表。
表由 SQLiteStore._DDL 统一创建。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class ReflectionMemory:
    """Agent 自省记忆 — 记录每次交互的反思结果。

    每次 Reflection 包含：
    - root_cause: 失败根因
    - lesson_learned: 经验教训
    - preventive_action: 预防措施
    - success: 是否成功

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("ReflectionMemory initialized (user=%s)", user_id)

    async def save(
        self,
        task_type: str,
        success: bool,
        root_cause: Optional[str] = None,
        lesson_learned: Optional[str] = None,
        preventive_action: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """保存一条反思记录。

        Args:
            task_type: 任务类型。
            success: 是否成功。
            root_cause: 失败根因。
            lesson_learned: 经验教训。
            preventive_action: 预防措施。
            metadata: 附加元数据。

        Returns:
            反思记录 ID。
        """
        rid = uuid.uuid4().hex[:12]
        await self.store.execute(
            "INSERT INTO reflections (id, user_id, task_type, success, root_cause, "
            "lesson_learned, preventive_action, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rid,
                self.user_id,
                task_type,
                1 if success else 0,
                root_cause,
                lesson_learned,
                preventive_action,
                json.dumps(metadata or {}),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        logger.debug("Reflection saved: id=%s, type=%s, success=%s", rid, task_type, success)
        return rid

    async def query(self, limit: int = 20) -> list[dict]:
        """查询最近的反思记录。

        Args:
            limit: 返回数量上限。

        Returns:
            反思记录列表，每项为 dict。
        """
        rows = await self.store.query(
            "SELECT * FROM reflections WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            [self.user_id, limit],
        )
        return [dict(row) for row in rows]

    async def count_failures(self, task_type: Optional[str] = None) -> int:
        """统计失败次数，可按任务类型过滤。

        Args:
            task_type: 可选的过滤任务类型。

        Returns:
            失败次数。
        """
        if task_type:
            rows = await self.store.query(
                "SELECT COUNT(*) AS cnt FROM reflections "
                "WHERE user_id = ? AND task_type = ? AND success = 0",
                [self.user_id, task_type],
            )
        else:
            rows = await self.store.query(
                "SELECT COUNT(*) AS cnt FROM reflections "
                "WHERE user_id = ? AND success = 0",
                [self.user_id],
            )
        return rows[0]["cnt"] if rows else 0
