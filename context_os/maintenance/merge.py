"""MergeTask — 合并相似/重复记忆。

策略:
    - 精确重复 (同 content)         → 保留最早，合并 access_count
    - 语义重复 (cosine sim > 0.85)  → 保留较长的；长度差<20%时保留 access_count 高的
    - 实体重复 (同 entity_key)      → 合并版本链，旧版本入 history
    - Experience 合并 (同 tags)      → 合并 lesson/steps，tags 取并集
    - Fact history 截断 (>10)       → 保留最早 1 条 + 最近 5 条
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)

# 语义去重相似度阈值
_MERGE_SIM_THRESHOLD = 0.85
# Fact history 截断阈值
_MAX_FACT_HISTORY = 10


class MergeTask:
    """合并任务 — 定期去重和语义合并。"""

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
        """执行一次完整合并。

        Returns:
            合并/删除的总条目数。
        """
        total = 0

        # 1. 精确去重
        total += await self._exact_dedup()

        # 2. 语义去重
        total += await self._semantic_dedup()

        # 3. 实体去重（同 entity_key 版本链合并）
        total += await self._entity_dedup()

        # 4. Experience 合并
        if self._experience:
            total += await self._experience_merge()

        # 5. Fact history 截断
        total += await self._truncate_fact_history()

        if total > 0:
            logger.info("MergeTask: %d total items processed", total)
        return total

    # ── 精确去重 ────────────────────────────────────────────

    async def _exact_dedup(self) -> int:
        """精确内容去重：同 content 保留最早一条，合并 access_count。"""
        results = await self._store.query_memories(
            type="long_term", top_k=1000,
        )
        if not results:
            return 0

        seen: dict[str, dict[str, Any]] = {}
        to_delete: list[str] = []
        deleted = 0

        for r in results:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            if content in seen:
                # 合并 access_count 到保留的记录
                keep = seen[content]
                merged_count = (keep.get("access_count") or 0) + (r.get("access_count") or 0)
                await self._store.execute(
                    "UPDATE memories SET access_count = ? WHERE id = ?",
                    [merged_count, keep["id"]],
                )
                to_delete.append(r["id"])
            else:
                seen[content] = r

        for mem_id in to_delete:
            await self._store.delete_memory(mem_id)

        if to_delete:
            logger.info("Merge: %d exact duplicates removed", len(to_delete))
        return len(to_delete)

    # ── 语义去重 ────────────────────────────────────────────

    async def _semantic_dedup(self) -> int:
        """语义去重：cosine sim > 0.85 时合并。"""
        # 需要有 embedding 才能做语义去重
        ltm = self._ltm
        if not hasattr(ltm, "_embedding_provider") or not ltm._embedding_provider:
            return 0

        results = await self._store.query_memories(
            type="long_term", top_k=500,
        )
        if len(results) < 2:
            return 0

        contents = [(r.get("content") or "").strip() for r in results]
        valid_results = [(r, c) for r, c in zip(results, contents) if c]
        if len(valid_results) < 2:
            return 0

        # 批量生成 embedding
        try:
            texts = [c for _, c in valid_results]
            embeddings = await ltm._embedding_provider.embed_batch(texts)
        except Exception as e:
            logger.warning("Semantic dedup embedding failed: %s", e)
            return 0

        to_delete: set[str] = set()
        for i in range(len(valid_results)):
            if valid_results[i][0]["id"] in to_delete:
                continue
            for j in range(i + 1, len(valid_results)):
                rid_j = valid_results[j][0]["id"]
                if rid_j in to_delete:
                    continue
                sim = self._cosine_similarity(embeddings[i], embeddings[j])
                if sim > _MERGE_SIM_THRESHOLD:
                    # 保留较长的版本
                    len_i = len(valid_results[i][1])
                    len_j = len(valid_results[j][1])
                    if len_i >= len_j or (len_j - len_i) / max(len_i, 1) < 0.2:
                        # i 更长或差异 < 20%: 保留 access_count 更高者
                        ac_i = valid_results[i][0].get("access_count") or 0
                        ac_j = valid_results[j][0].get("access_count") or 0
                        if ac_i >= ac_j:
                            to_delete.add(rid_j)
                            # 合并 access_count
                            await self._store.execute(
                                "UPDATE memories SET access_count = ? WHERE id = ?",
                                [ac_i + ac_j, valid_results[i][0]["id"]],
                            )
                        else:
                            to_delete.add(valid_results[i][0]["id"])
                            await self._store.execute(
                                "UPDATE memories SET access_count = ? WHERE id = ?",
                                [ac_i + ac_j, valid_results[j][0]["id"]],
                            )
                            break
                    else:
                        to_delete.add(valid_results[i][0]["id"])
                        break

        for mem_id in to_delete:
            await self._store.delete_memory(mem_id)

        if to_delete:
            logger.info("Merge: %d semantic duplicates removed", len(to_delete))
        return len(to_delete)

    # ── 实体去重 ────────────────────────────────────────────

    async def _entity_dedup(self) -> int:
        """同 entity_key → 合并版本链。旧版本移入 history。"""
        results = await self._store.query_memories(
            type="long_term", top_k=1000,
        )
        if not results:
            return 0

        # 按 entity_key 分组
        fact_groups: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    continue
            ek = meta.get("entity_key") or meta.get("fact_id")
            if ek:
                fact_groups.setdefault(ek, []).append(r)

        changed = 0
        for ek, items in fact_groups.items():
            if len(items) <= 1:
                continue

            # 按时间排序，保留最新
            items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            keep = items[0]

            # 将旧的移入 history
            keep_meta = keep.get("metadata", {})
            if isinstance(keep_meta, str):
                try:
                    keep_meta = json.loads(keep_meta)
                except Exception:
                    keep_meta = {}

            history = list(keep_meta.get("history", []) or [])
            for old in items[1:]:
                old_meta = old.get("metadata", {})
                if isinstance(old_meta, str):
                    try:
                        old_meta = json.loads(old_meta)
                    except Exception:
                        old_meta = {}
                history.append({
                    "value": old.get("content", ""),
                    "version": old_meta.get("version", 1),
                    "updated_at": old.get("timestamp", ""),
                })

                # 合并 access_count
                keep_ac = (keep.get("access_count") or 0) + (old.get("access_count") or 0)
                await self._store.execute(
                    "UPDATE memories SET access_count = ? WHERE id = ?",
                    [keep_ac, keep["id"]],
                )

                await self._store.delete_memory(old["id"])
                changed += 1

            # 更新 keep 的 history
            keep_meta["history"] = history
            await self._store.execute(
                "UPDATE memories SET metadata = ? WHERE id = ?",
                [json.dumps(keep_meta, ensure_ascii=False), keep["id"]],
            )

        if changed > 0:
            logger.info("Merge: %d entity duplicates merged", changed)
        return changed

    # ── Experience 合并 ─────────────────────────────────────

    async def _experience_merge(self) -> int:
        """Experience 同 tags + 相似场景合并。"""
        if not self._experience or not hasattr(self._experience, "store"):
            return 0

        results = await self._experience.store.query_experiences(top_k=500)
        if len(results) < 2:
            return 0

        # 按 tags 分组
        import json as _json
        tag_groups: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            tags = r.get("tags") or r.get("metadata", {}).get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = _json.loads(tags)
                except (_json.JSONDecodeError, TypeError):
                    tags = [tags]
            tag_key = "|".join(sorted(tags)) if tags else "__none__"
            tag_groups.setdefault(tag_key, []).append(r)

        changed = 0
        for _tag_key, items in tag_groups.items():
            if len(items) <= 1:
                continue

            # 检查相似场景（基于 scene/scenario 字段）
            from difflib import SequenceMatcher
            to_delete: list[str] = []
            for i in range(len(items)):
                if items[i]["id"] in to_delete:
                    continue
                for j in range(i + 1, len(items)):
                    if items[j]["id"] in to_delete:
                        continue
                    si = (items[i].get("scene") or items[i].get("scenario") or "").lower()
                    sj = (items[j].get("scene") or items[j].get("scenario") or "").lower()
                    if si and sj:
                        ratio = SequenceMatcher(None, si, sj).ratio()
                        if ratio > 0.85:
                            # 合并 lesson/steps
                            meta_i = items[i].get("metadata", {}) or {}
                            meta_j = items[j].get("metadata", {}) or {}
                            if isinstance(meta_i, str):
                                try:
                                    meta_i = _json.loads(meta_i)
                                except Exception:
                                    meta_i = {}
                            if isinstance(meta_j, str):
                                try:
                                    meta_j = _json.loads(meta_j)
                                except Exception:
                                    meta_j = {}

                            # 合并 tags
                            tags_i = meta_i.get("tags", [])
                            tags_j = meta_j.get("tags", [])
                            if isinstance(tags_i, str):
                                tags_i = [tags_i]
                            if isinstance(tags_j, str):
                                tags_j = [tags_j]
                            merged_tags = list(set(list(tags_i) + list(tags_j)))

                            # 合并经验信息
                            lesson_i = items[i].get("lesson", "") or meta_i.get("lesson", "")
                            lesson_j = items[j].get("lesson", "") or meta_j.get("lesson", "")
                            merged_lesson = "; ".join(filter(None, [lesson_i, lesson_j]))

                            new_meta = {**meta_i, **meta_j, "tags": merged_tags}
                            if merged_lesson:
                                new_meta["lesson"] = merged_lesson

                            await self._store.execute(
                                "UPDATE experiences SET metadata = ?, tags = ? WHERE id = ?",
                                [_json.dumps(new_meta, ensure_ascii=False),
                                 _json.dumps(merged_tags, ensure_ascii=False),
                                 items[i]["id"]],
                            )
                            await self._store.execute(
                                "DELETE FROM experiences WHERE id = ?", [items[j]["id"]],
                            )
                            to_delete.append(items[j]["id"])
                            changed += 1

        if changed > 0:
            logger.info("Merge: %d experience entries merged", changed)
        return changed

    # ── Fact history 截断 ───────────────────────────────────

    async def _truncate_fact_history(self) -> int:
        """截断过长的 Fact history（>10 条时保留最早 1 条 + 最近 5 条）。"""
        results = await self._store.query_memories(
            type="long_term", top_k=1000,
        )
        if not results:
            return 0

        import json as _json
        changed = 0

        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except (_json.JSONDecodeError, TypeError):
                    continue

            history = meta.get("history", [])
            if not isinstance(history, list) or len(history) <= _MAX_FACT_HISTORY:
                continue

            # 保留最早 1 条 + 最近 5 条
            truncated = [history[0]] + history[-5:]
            meta["history"] = truncated
            await self._store.execute(
                "UPDATE memories SET metadata = ? WHERE id = ?",
                [_json.dumps(meta, ensure_ascii=False), r["id"]],
            )
            changed += 1

        if changed > 0:
            logger.info("Merge: %d fact histories truncated", changed)
        return changed

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度。"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = nA = nB = 0.0
        for va, vb in zip(a, b):
            dot += va * vb
            nA += va * va
            nB += vb * vb
        denom = (nA ** 0.5) * (nB ** 0.5)
        return dot / denom if denom != 0 else 0.0
