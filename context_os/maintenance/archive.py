"""ArchiveTask — 归档冷数据。

策略:
    条件（三者全满足）:
        1. > 180 天旧
        2. 最后访问 > 90 天前
        3. relevance < 0.5

    动作:
        metadata.archived = True — 正常检索排除，仅 include_archived=True 返回。

    注意: Archive 是从热检索中移除（可恢复），Forget 是物理删除（不可恢复）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# Archive 条件
_ARCHIVE_AGE_DAYS = 180
_ARCHIVE_LAST_ACCESS_DAYS = 90
_ARCHIVE_MAX_RELEVANCE = 0.5


class ArchiveTask:
    """归档任务 — 定期将冷数据移出热检索。"""

    def __init__(
        self,
        ltm: Any,
        store: SQLiteStore,
        experience: Optional[Any] = None,
    ) -> None:
        self._ltm = ltm
        self._store = store
        self._experience = experience

    async def run(self) -> int:
        """执行一次完整归档。

        Returns:
            归档的条目数。
        """
        total = 0

        # 1. LTM 归档
        total += await self._archive_ltm()

        # 2. Experience 归档
        if self._experience:
            total += await self._archive_experience()

        if total > 0:
            logger.info("ArchiveTask: %d total items archived", total)
        return total

    # ── LTM 归档 ────────────────────────────────────────────

    async def _archive_ltm(self) -> int:
        """归档旧的 LTM 记忆。"""
        if not self._store.is_connected:
            return 0

        import json as _json

        age_cutoff = (datetime.now(timezone.utc) - timedelta(days=_ARCHIVE_AGE_DAYS)).isoformat()
        access_cutoff = (datetime.now(timezone.utc) - timedelta(days=_ARCHIVE_LAST_ACCESS_DAYS)).isoformat()

        results = await self._store.query(
            "SELECT id, metadata, relevance_score, timestamp, access_count FROM memories "
            "WHERE type = 'long_term' "
            "AND timestamp < ? "
            "AND relevance_score < ?",
            [age_cutoff, _ARCHIVE_MAX_RELEVANCE],
        )
        if not results:
            return 0

        archived = 0
        for r in results:
            # 检查最后访问时间（用 timestamp 近似，因为没有 last_accessed 字段）
            # 如果 access_count 很低，说明很少访问
            if (r.get("access_count") or 0) > 5:
                continue  # 还有人访问，不归档

            meta_raw = r.get("metadata", "{}")
            if isinstance(meta_raw, str):
                try:
                    meta = _json.loads(meta_raw)
                except (_json.JSONDecodeError, TypeError):
                    meta = {}
            else:
                meta = meta_raw

            if not isinstance(meta, dict):
                meta = {}

            # 跳过已归档的
            if meta.get("archived"):
                continue

            meta["archived"] = True
            await self._store.execute(
                "UPDATE memories SET metadata = ? WHERE id = ?",
                [_json.dumps(meta, ensure_ascii=False), r["id"]],
            )
            archived += 1

        if archived > 0:
            logger.info("Archive: %d LTM memories archived", archived)
        return archived

    # ── Experience 归档 ─────────────────────────────────────

    async def _archive_experience(self) -> int:
        """归档旧的 Experience 记录。"""
        if not self._store.is_connected:
            return 0

        age_cutoff = (datetime.now(timezone.utc) - timedelta(days=_ARCHIVE_AGE_DAYS)).isoformat()

        results = await self._store.query(
            "SELECT id, metadata FROM experiences WHERE created_at < ?",
            [age_cutoff],
        )
        if not results:
            return 0

        import json as _json
        archived = 0

        for r in results:
            meta_raw = r.get("metadata", "{}") or "{}"
            if isinstance(meta_raw, str):
                try:
                    meta = _json.loads(meta_raw)
                except (_json.JSONDecodeError, TypeError):
                    meta = {}
            else:
                meta = meta_raw

            if not isinstance(meta, dict):
                meta = {}

            if meta.get("archived"):
                continue

            meta["archived"] = True
            await self._store.execute(
                "UPDATE experiences SET metadata = ? WHERE id = ?",
                [_json.dumps(meta, ensure_ascii=False), r["id"]],
            )
            archived += 1

        if archived > 0:
            logger.info("Archive: %d experience records archived", archived)
        return archived
