"""ForgetTask — 遗忘低价值/过期/纠正记忆。

策略:
    - TTL 过期         → 直接删除
    - 低价值           → >90 天 + access<2 + relevance<0.3 → 删除
    - 纠正标记         → reliability ≤ 0.2 → 删除（原逻辑为标记 corrections）
    - Session 过期     → expires_at 过期 -> 直接删除（由 store.cleanup_expired 处理）
"""

from __future__ import annotations

import json
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# 低价值遗忘条件
_LOW_VALUE_DAYS = 90
_LOW_VALUE_MIN_ACCESS = 2
_LOW_VALUE_MAX_RELEVANCE = 0.3
# 纠正标记可靠性阈值
_CORRECTION_MAX_RELIABILITY = 0.2


class ForgetTask:
    """遗忘任务 — 定期删除低价值和过期记忆。"""

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
        """执行一次完整遗忘清理。

        Returns:
            删除的总条目数。
        """
        total = 0

        # 1. store 层 TTL 过期清理
        total += await self._store.cleanup_expired()

        # 2. 低价值记忆清理
        total += await self._low_value_cleanup()

        # 3. 纠正标记清理
        total += await self._correction_cleanup()

        # 4. Experience 过期清理
        if self._experience:
            total += await self._experience_cleanup()

        if total > 0:
            logger.info("ForgetTask: %d total items deleted", total)
        return total

    # ── 低价值清理 ──────────────────────────────────────────

    async def _low_value_cleanup(self) -> int:
        """清理低价值 LTM 记忆（>90 天未访问 + 低频率 + 低相关性）。"""
        if not self._store.is_connected:
            return 0

        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_LOW_VALUE_DAYS)).isoformat()

        try:
            cursor = await self._store.execute(
                "DELETE FROM memories "
                "WHERE type = 'long_term' "
                "AND timestamp < ? "
                "AND access_count < ? "
                "AND relevance_score < ?",
                [cutoff, _LOW_VALUE_MIN_ACCESS, _LOW_VALUE_MAX_RELEVANCE],
            )
            count = cursor.rowcount
            if count > 0:
                logger.info("Forget: %d low-value LTM memories deleted", count)
            return count
        except Exception as e:
            logger.warning("Low-value cleanup failed: %s", e)
            return 0

    # ── 纠正标记清理 ────────────────────────────────────────

    async def _correction_cleanup(self) -> int:
        """清理被用户纠正的记忆（reliability ≤ 0.2，即 metadata.reliability 很低）。

        注意：use LTM forget 方法也做类似工作，这里补充处理 metadata.reliability 字段。
        """
        if not self._store.is_connected:
            return 0

        # 查询 memories，手动检查 metadata.reliability
        results = await self._store.query(
            "SELECT id, metadata FROM memories WHERE type = 'long_term'",
        )
        if not results:
            return 0

        import json as _json
        to_delete: list[str] = []

        for r in results:
            meta_raw = r.get("metadata", "{}")
            if isinstance(meta_raw, str):
                try:
                    meta = _json.loads(meta_raw)
                except (_json.JSONDecodeError, TypeError):
                    continue
                if isinstance(meta, dict):
                    reliability = meta.get("reliability") or meta.get("source_reliability") or 1.0
                    if isinstance(reliability, (int, float)) and reliability <= _CORRECTION_MAX_RELIABILITY:
                        to_delete.append(r["id"])

        for mem_id in to_delete:
            await self._store.delete_memory(mem_id)

        if to_delete:
            logger.info("Forget: %d corrected/reliable memories deleted", len(to_delete))
        return len(to_delete)

    # ── Experience 过期清理 ─────────────────────────────────

    async def _experience_cleanup(self) -> int:
        """清理旧的 Experience 记录（>180 天且低价值）。"""
        if not self._store.is_connected:
            return 0

        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()

        try:
            cursor = await self._store.execute(
                "DELETE FROM experiences WHERE created_at < ?",
                [cutoff],
            )
            count = cursor.rowcount
            if count > 0:
                logger.info("Forget: %d old experience records deleted", count)
            return count
        except Exception as e:
            logger.warning("Experience cleanup failed: %s", e)
            return 0
