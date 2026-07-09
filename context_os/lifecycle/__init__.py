"""MemoryLifecycle — 记忆生命周期管理。

Write → Consolidate → Summarize → Archive → Forget
参考 Java: com.owencli.contextos.lifecycle.MemoryLifecycle
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from context_os.memory.store import SQLiteStore

logger = logging.getLogger(__name__)

class MemoryLifecycle:
    """管理记忆的完整生命周期。"""

    def __init__(self, store: SQLiteStore):
        self.store = store
        self._register_ttl_seconds = {"short_term": 86400, "long_term": 7776000}  # 1d / 90d

    async def consolidate(self, user_id: str = None) -> int:
        """合并重复记忆。"""
        if user_id:
            rows = self.store.query("SELECT id, content, type FROM memories WHERE user_id=? ORDER BY created_at", [user_id])
        else:
            rows = self.store.query("SELECT id, content, type FROM memories ORDER BY created_at", [])
        seen = {}; removed = 0
        for r in rows:
            key = (r[1].strip().lower(), r[2])
            if key in seen:
                self.store.execute("DELETE FROM memories WHERE id=?", [r[0]])
                removed += 1
            else:
                seen[key] = r[0]
        if removed: logger.info("Consolidate: removed %d duplicate memories", removed)
        return removed

    async def archive(self, days: int = 30) -> int:
        """归档旧记录（标记而非删除）。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self.store.execute("UPDATE memories SET type='archived' WHERE type!='archived' AND created_at<?", [cutoff])
        rows = self.store.execute("SELECT changes() as c")
        logger.info("Archive: archived records older than %d days", days)
        return 0

    async def forget(self, days: int = 90) -> int:
        """清理过期短期记忆。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self.store.execute("DELETE FROM memories WHERE type='short_term' AND created_at<?", [cutoff])
        logger.info("Forget: cleaned short-term memories older than %d days", days)
        return 0

    async def run_maintenance(self) -> dict:
        """执行所有后台维护任务。"""
        return {"consolidated": await self.consolidate(), "forgotten": await self.forget()}
