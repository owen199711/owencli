"""ProceduralMemory — 存储已学习的工作流程与步骤模式。

参考 Java: com.owencli.contextos.memory.ProceduralMemory
存储：procedures 表，含步骤序列、场景标签、成功率。
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


class ProceduralMemory:
    """工作流过程记忆。

    存储已学习的操作流程与步骤模式，追踪每个流程的成功率，
    支持按关键词搜索和最优化查询。

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("ProceduralMemory initialized (user=%s)", user_id)

    async def save(
        self,
        name: str,
        steps: list[dict],
        description: str = "",
        tags: Optional[list[str]] = None,
    ) -> str:
        """保存一个新的工作流程。

        Args:
            name: 流程名称。
            steps: 步骤列表，每步为 dict。
            description: 流程描述。
            tags: 场景标签列表。

        Returns:
            新流程 ID。
        """
        pid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags or [])

        await self.store.execute(
            "INSERT INTO procedures (id, user_id, name, description, steps, tags, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [pid, self.user_id, name, description, json.dumps(steps), tags_json, now, now],
        )
        logger.debug("Procedure saved: id=%s, name=%s", pid, name)
        return pid

    async def record_usage(self, proc_id: str, success: bool) -> None:
        """记录一次流程使用情况，更新成功率。

        Args:
            proc_id: 流程 ID。
            success: 是否成功。
        """
        now = datetime.now(timezone.utc).isoformat()
        if success:
            await self.store.execute(
                "UPDATE procedures SET success_count = success_count + 1, "
                "total_count = total_count + 1, last_used = ? WHERE id = ?",
                [now, proc_id],
            )
        else:
            await self.store.execute(
                "UPDATE procedures SET total_count = total_count + 1, "
                "last_used = ? WHERE id = ?",
                [now, proc_id],
            )
        logger.debug("Procedure usage recorded: id=%s, success=%s", proc_id, success)

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """按关键词搜索工作流程，按成功率降序排列。

        Args:
            query: 搜索关键词。
            limit: 返回数量上限。

        Returns:
            匹配的流程列表，每项为 dict。
        """
        like = f"%{query}%"
        rows = await self.store.query(
            "SELECT * FROM procedures WHERE user_id = ? "
            "AND (name LIKE ? OR description LIKE ? OR tags LIKE ?) "
            "ORDER BY success_count * 1.0 / MAX(total_count, 1) DESC "
            "LIMIT ?",
            [self.user_id, like, like, like, limit],
        )
        return [dict(r) for r in rows]

    async def get_best(self, tag: Optional[str] = None) -> list[dict]:
        """获取成功率最高的流程，可按标签过滤。

        Args:
            tag: 可选的场景标签过滤。

        Returns:
            最优流程列表，每项为 dict。
        """
        if tag:
            rows = await self.store.query(
                "SELECT * FROM procedures WHERE user_id = ? AND tags LIKE ? "
                "ORDER BY success_count * 1.0 / MAX(total_count, 1) DESC LIMIT 5",
                [self.user_id, f"%{tag}%"],
            )
        else:
            rows = await self.store.query(
                "SELECT * FROM procedures WHERE user_id = ? "
                "ORDER BY success_count * 1.0 / MAX(total_count, 1) DESC LIMIT 5",
                [self.user_id],
            )
        return [dict(r) for r in rows]
