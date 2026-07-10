"""ToolExperienceMemory — 工具调用经验与成功率追踪。

参考 Java: com.owencli.contextos.memory.ToolExperienceMemory
表由 SQLiteStore._DDL 统一创建。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class ToolExperienceMemory:
    """工具调用经验记忆。

    追踪每次工具调用的成功/失败情况，维护聚合统计信息，
    支持按成功率选择最优工具。

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("ToolExperienceMemory initialized (user=%s)", user_id)

    async def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: int = 0,
        error_type: Optional[str] = None,
        scenario: Optional[str] = None,
        input_preview: Optional[str] = None,
    ) -> str:
        """记录一次工具调用经验，同时更新聚合统计。

        Args:
            tool_name: 工具名称。
            success: 是否成功。
            duration_ms: 耗时（毫秒）。
            error_type: 错误类型（失败时）。
            scenario: 使用场景。
            input_preview: 输入摘要。

        Returns:
            经验记录 ID。
        """
        now = datetime.now(timezone.utc).isoformat()
        eid = uuid.uuid4().hex[:12]

        # 写入经验记录
        await self.store.execute(
            "INSERT INTO tool_experience (id, user_id, tool_name, success, "
            "error_type, duration_ms, scenario, input_preview, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                eid, self.user_id, tool_name, 1 if success else 0,
                error_type, duration_ms, scenario, input_preview, now,
            ],
        )

        # 更新聚合统计
        existing = await self.store.query(
            "SELECT * FROM tool_stats WHERE tool_name = ? AND user_id = ?",
            [tool_name, self.user_id],
        )

        if existing:
            r = existing[0]
            new_total = r["total_calls"] + 1
            new_success = r["success_calls"] + (1 if success else 0)
            new_avg = (r["avg_duration_ms"] * r["total_calls"] + duration_ms) / new_total
            await self.store.execute(
                "UPDATE tool_stats SET total_calls = ?, success_calls = ?, "
                "avg_duration_ms = ? WHERE tool_name = ? AND user_id = ?",
                [new_total, new_success, new_avg, tool_name, self.user_id],
            )
        else:
            await self.store.execute(
                "INSERT INTO tool_stats (tool_name, user_id, total_calls, "
                "success_calls, avg_duration_ms) VALUES (?, ?, ?, ?, ?)",
                [tool_name, self.user_id, 1, 1 if success else 0, duration_ms],
            )

        logger.debug("Tool experience recorded: %s, success=%s, duration=%dms",
                     tool_name, success, duration_ms)
        return eid

    async def get_best_tool(self, scenario: Optional[str] = None) -> str:
        """获取成功率最高的工具。

        Args:
            scenario: 可选的场景过滤。

        Returns:
            工具名称，若无数据返回 "unknown"。
        """
        rows = await self.store.query(
            "SELECT tool_name, success_calls * 1.0 / MAX(total_calls, 1) AS rate "
            "FROM tool_stats WHERE user_id = ? "
            "ORDER BY rate DESC LIMIT 1",
            [self.user_id],
        )
        return rows[0]["tool_name"] if rows else "unknown"

    async def get_stats(self, tool_name: Optional[str] = None) -> list[dict]:
        """获取工具统计信息。

        Args:
            tool_name: 可选的工具名称过滤。

        Returns:
            统计信息列表，每项为 dict。
        """
        if tool_name:
            rows = await self.store.query(
                "SELECT * FROM tool_stats WHERE user_id = ? AND tool_name = ?",
                [self.user_id, tool_name],
            )
        else:
            rows = await self.store.query(
                "SELECT * FROM tool_stats WHERE user_id = ? "
                "ORDER BY total_calls DESC LIMIT 20",
                [self.user_id],
            )
        return [dict(r) for r in rows]
