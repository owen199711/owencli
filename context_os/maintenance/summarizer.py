"""SummarizeTask — 聚合同类记忆为摘要。

策略:
    - 同 session Summary 合并     → >10 条 Summary → 合并为一条聚合摘要
    - 时间期摘要                  → 同 user 7 天内 >20 条 LTM → 合并为周摘要
    - 实体时间线                  → 同 entity >5 条 Fact → 合并为时间线
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# 摘要阈值
_SESSION_SUMMARY_THRESHOLD = 10
_TIME_PERIOD_LTM_THRESHOLD = 20
_TIME_PERIOD_DAYS = 7
_ENTITY_TIMELINE_THRESHOLD = 5


class SummarizeTask:
    """摘要任务 — 定期聚合相似记忆。"""

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
        """执行一次完整摘要。

        Returns:
            新创建的摘要条目数。
        """
        total = 0

        # 1. 同 session Summary 合并
        total += await self._summarize_by_session()

        # 2. 时间期摘要
        total += await self._summarize_by_time_period()

        # 3. 实体时间线
        total += await self._summarize_entity_timeline()

        if total > 0:
            logger.info("SummarizeTask: %d total summaries created", total)
        return total

    # ── 按 Session 合并摘要 ─────────────────────────────────

    async def _summarize_by_session(self) -> int:
        """同 session 内 >10 条 Summary → 合并为一条。"""
        if not self._store.is_connected:
            return 0

        results = await self._store.query_memories(
            type="long_term", top_k=2000,
        )
        if not results:
            return 0

        import json as _json

        # 按 session_id 分组 Summary
        session_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except (_json.JSONDecodeError, TypeError):
                    continue
            if isinstance(meta, dict) and meta.get("ltm_subtype") == "summary":
                sid = r.get("session_id") or meta.get("session_id") or "__orphan__"
                session_groups[sid].append(r)

        created = 0
        for _sid, items in session_groups.items():
            if len(items) < _SESSION_SUMMARY_THRESHOLD:
                continue

            # 合并所有摘要内容
            contents = []
            to_delete = []
            for r in items:
                content = (r.get("content") or "").strip()
                if content:
                    contents.append(content)
                to_delete.append(r["id"])

            if not contents:
                continue

            # 生成聚合摘要
            aggregated = " · ".join(contents[:50])  # 最多 50 条
            aggregated = aggregated[:2000]  # 截断

            import uuid
            now = datetime.now(timezone.utc).isoformat()

            new_meta = {
                "category": "summary",
                "ltm_subtype": "summary",
                "source": "maintenance:session_aggregation",
                "original_count": len(contents),
                "created_at": now,
            }

            new_id = uuid.uuid4().hex
            await self._store.save_memory(
                id=new_id,
                type="long_term",
                content=aggregated,
                user_id=items[0].get("user_id", "anonymous"),
                metadata=new_meta,
            )
            created += 1

            # 删除旧 Summary
            for mid in to_delete:
                await self._store.delete_memory(mid)

        if created > 0:
            logger.info(
                "Summarize: %d session-aggregated summaries created (%d old deleted)",
                created, sum(len(v) for v in session_groups.values() if len(v) >= _SESSION_SUMMARY_THRESHOLD),
            )
        return created

    # ── 时间期摘要 ──────────────────────────────────────────

    async def _summarize_by_time_period(self) -> int:
        """同 user 7 天内 >20 条 LTM → 合并为周摘要。"""
        if not self._store.is_connected:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=_TIME_PERIOD_DAYS)).isoformat()

        results = await self._store.query(
            "SELECT id, content, user_id, metadata, session_id FROM memories "
            "WHERE type = 'long_term' AND timestamp >= ?",
            [cutoff],
        )
        if not results:
            return 0

        import json as _json

        # 按 user 分组
        user_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in results:
            uid = r.get("user_id") or "anonymous"
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except (_json.JSONDecodeError, TypeError):
                    meta = {}

            # 排除已存在的摘要
            if isinstance(meta, dict) and meta.get("source") == "maintenance:weekly_summary":
                continue

            user_groups[uid].append(r)

        created = 0
        for uid, items in user_groups.items():
            if len(items) < _TIME_PERIOD_LTM_THRESHOLD:
                continue

            contents = []
            to_delete = []
            for r in items:
                content = (r.get("content") or "").strip()
                if content:
                    contents.append(content)
                to_delete.append(r["id"])

            if not contents:
                continue

            import uuid
            now = datetime.now(timezone.utc).isoformat()

            aggregated = f"[Week Summary {now[:10]}] " + " · ".join(contents[:30])
            aggregated = aggregated[:2000]

            new_meta = {
                "category": "summary",
                "ltm_subtype": "summary",
                "source": "maintenance:weekly_summary",
                "original_count": len(contents),
                "created_at": now,
            }

            new_id = uuid.uuid4().hex
            await self._store.save_memory(
                id=new_id,
                type="long_term",
                content=aggregated,
                user_id=uid,
                metadata=new_meta,
            )
            created += 1

            # 删除旧记录
            for mid in to_delete:
                await self._store.delete_memory(mid)

        if created > 0:
            logger.info("Summarize: %d weekly summaries created", created)
        return created

    # ── 实体时间线 ──────────────────────────────────────────

    async def _summarize_entity_timeline(self) -> int:
        """同 entity >5 条 Fact → 合并为时间线。"""
        if not self._store.is_connected:
            return 0

        results = await self._store.query_memories(
            type="long_term", top_k=2000,
        )
        if not results:
            return 0

        import json as _json

        # 按 entity_key/fact_id 分组
        entity_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except (_json.JSONDecodeError, TypeError):
                    continue
            if isinstance(meta, dict):
                ek = meta.get("entity_key") or meta.get("fact_id")
                if ek:
                    entity_groups[ek].append(r)

        created = 0
        for ek, items in entity_groups.items():
            if len(items) < _ENTITY_TIMELINE_THRESHOLD:
                continue

            # 按时间排序
            items.sort(key=lambda x: x.get("timestamp", ""))

            # 生成时间线
            timeline_parts = []
            for r in items:
                ts = r.get("timestamp", "")[:16]
                content = (r.get("content") or "").strip()
                if content:
                    timeline_parts.append(f"[{ts}] {content}")

            if not timeline_parts:
                continue

            import uuid
            now = datetime.now(timezone.utc).isoformat()

            timeline_text = f"Timeline for '{ek}':\n" + "\n".join(timeline_parts[:50])
            timeline_text = timeline_text[:3000]

            new_meta = {
                "category": "summary",
                "ltm_subtype": "summary",
                "source": "maintenance:entity_timeline",
                "entity_key": ek,
                "original_count": len(items),
                "created_at": now,
            }

            new_id = uuid.uuid4().hex
            await self._store.save_memory(
                id=new_id,
                type="long_term",
                content=timeline_text,
                user_id=items[0].get("user_id", "anonymous"),
                metadata=new_meta,
            )
            created += 1

            # 标记旧记录（降低 relevance 但不删除）
            for r in items:
                await self._store.execute(
                    "UPDATE memories SET relevance_score = MAX(0.1, relevance_score * 0.5) "
                    "WHERE id = ?",
                    [r["id"]],
                )

        if created > 0:
            logger.info("Summarize: %d entity timelines created", created)
        return created
