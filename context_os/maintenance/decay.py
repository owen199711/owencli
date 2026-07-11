"""DecayTask — 衰减长期未访问的 relevance_score。

策略:
    - 时间衰减           → relevance *= exp(-t / half_life)
    - Fact 半衰期 7 天    → 标准衰减
    - Summary 半衰期 3 天 → 加速衰减（更快过期）
    - 访问衰减           → >30 天无访问 → relevance *= 0.9
    - 可靠性恢复          → access_count > 20 + 无纠正 30 天 → reliability + 0.05 (cap 1.0)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# 衰减常数
_FACT_HALF_LIFE_DAYS = 7.0
_SUMMARY_HALF_LIFE_DAYS = 3.0
_FACT_LAMBDA = math.log(2) / _FACT_HALF_LIFE_DAYS
_SUMMARY_LAMBDA = math.log(2) / _SUMMARY_HALF_LIFE_DAYS

# 访问衰减阈值（天）
_ACCESS_DECAY_DAYS = 30
_ACCESS_DECAY_FACTOR = 0.9

# 可靠性恢复阈值
_RELIABILITY_RECOVERY_MIN_ACCESS = 20
_RELIABILITY_RECOVERY_DAYS = 30
_RELIABILITY_RECOVERY_DELTA = 0.05


class DecayTask:
    """衰减任务 — 定期降低未使用记忆的 relevance_score。"""

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
        """执行一次完整衰减。

        Returns:
            更新的条目数。
        """
        total = 0

        # 1. 时间衰减
        total += await self._time_decay()

        # 2. 访问衰减
        total += await self._access_decay()

        # 3. 可靠性恢复
        total += await self._reliability_recovery()

        if total > 0:
            logger.info("DecayTask: %d total items decayed", total)
        return total

    # ── 时间衰减 ────────────────────────────────────────────

    async def _time_decay(self) -> int:
        """时间衰减：relevance_score *= exp(-λ × days_old)。

        Fact 半衰期 7 天，Summary 半衰期 3 天。
        """
        if not self._store.is_connected:
            return 0

        results = await self._store.query_memories(
            type="long_term", top_k=2000,
        )
        if not results:
            return 0

        now = datetime.now(timezone.utc)
        updated = 0

        for r in results:
            ts_str = r.get("timestamp")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                days_old = max(0, (now - ts).days)
            except Exception:
                continue

            # 判断 Fact vs Summary
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            is_summary = meta.get("ltm_subtype") == "summary" if isinstance(meta, dict) else False
            decay_lambda = _SUMMARY_LAMBDA if is_summary else _FACT_LAMBDA

            # 计算衰减
            decay_factor = math.exp(-decay_lambda * days_old)
            current_score = r.get("relevance_score") or 0.0
            new_score = round(current_score * decay_factor, 4)

            # 至少衰减到 0.01，避免归零
            if new_score < 0.01:
                new_score = 0.01

            if abs(new_score - current_score) > 0.001:
                await self._store.execute(
                    "UPDATE memories SET relevance_score = ? WHERE id = ?",
                    [new_score, r["id"]],
                )
                updated += 1

        if updated > 0:
            logger.info(
                "Decay: %d memories time-decayed (Fact λ=%.2f, Summary λ=%.2f)",
                updated, _FACT_LAMBDA, _SUMMARY_LAMBDA,
            )
        return updated

    # ── 访问衰减 ────────────────────────────────────────────

    async def _access_decay(self) -> int:
        """访问衰减：>30 天无任何更新 → relevance *= 0.9。"""
        if not self._store.is_connected:
            return 0

        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_ACCESS_DECAY_DAYS)).isoformat()

        results = await self._store.query(
            "SELECT id, relevance_score FROM memories "
            "WHERE type = 'long_term' AND timestamp < ? AND relevance_score > 0.01",
            [cutoff],
        )
        if not results:
            return 0

        updated = 0
        for r in results:
            current = r["relevance_score"] or 0.0
            new_score = round(current * _ACCESS_DECAY_FACTOR, 4)
            if new_score < 0.01:
                new_score = 0.01

            await self._store.execute(
                "UPDATE memories SET relevance_score = ? WHERE id = ?",
                [new_score, r["id"]],
            )
            updated += 1

        if updated > 0:
            logger.info("Decay: %d memories access-decayed (>30d no access)", updated)
        return updated

    # ── 可靠性恢复 ──────────────────────────────────────────

    async def _reliability_recovery(self) -> int:
        """可靠性恢复：access_count > 20 且在 30 天内无纠正 → reliability + 0.05。"""
        if not self._store.is_connected:
            return 0

        results = await self._store.query(
            "SELECT id, access_count, metadata FROM memories "
            "WHERE type = 'long_term' AND access_count >= ?",
            [_RELIABILITY_RECOVERY_MIN_ACCESS],
        )
        if not results:
            return 0

        import json as _json
        recovered = 0

        for r in results:
            meta_raw = r.get("metadata", "{}")
            if isinstance(meta_raw, str):
                try:
                    meta = _json.loads(meta_raw)
                except (_json.JSONDecodeError, TypeError):
                    continue
            else:
                meta = meta_raw

            if not isinstance(meta, dict):
                continue

            reliability = meta.get("source_reliability") or meta.get("reliability") or 1.0
            if reliability >= 1.0:
                continue

            # 检查是否有纠正标记
            if meta.get("correction_count", 0) > 0:
                continue

            new_reliability = min(reliability + _RELIABILITY_RECOVERY_DELTA, 1.0)
            meta["source_reliability"] = round(new_reliability, 4)

            await self._store.execute(
                "UPDATE memories SET metadata = ? WHERE id = ?",
                [_json.dumps(meta, ensure_ascii=False), r["id"]],
            )
            recovered += 1

        if recovered > 0:
            logger.info("Decay: %d memories reliability recovered", recovered)
        return recovered
