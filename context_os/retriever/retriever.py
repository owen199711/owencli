"""UnifiedRetriever — 统一检索引擎。

四步流程:
    1. Search: 并发调各 SourceAdapter → 原始候选
    2. Score:  ScoringEngine 统一公式打分
    3. Merge: 跨源去重 (embedding sim > 0.95) + 实体去重 (同 entity_key)
    4. Rank:  按 final_score 排序截断 top-k
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.retriever.adapter import RetrievedItem
from context_os.retriever.scoring import ScoringEngine

logger = get_logger(__name__)

# 跨源去重相似度阈值
_DEDUP_SIM_THRESHOLD = 0.95


class UnifiedRetriever:
    """统一检索引擎（Phase 6）。

    使用方式:
        retriever = UnifiedRetriever(
            adapters={
                "long_term": LTMAdapter(...),
                "experience": ExperienceAdapter(...),
                "knowledge": KnowledgeAdapter(...),
                "session": SessionAdapter(...),
                "journal": JournalAdapter(...),
            },
            scoring=ScoringEngine(),
        )
        results = await retriever.retrieve("查询文本", top_k=25)
    """

    def __init__(
        self,
        adapters: dict[str, Any],  # {source_name: SourceAdapter}
        scoring: Optional[ScoringEngine] = None,
        default_top_k: int = 25,
    ) -> None:
        self._adapters = adapters
        self._scoring = scoring or ScoringEngine()
        self._default_top_k = default_top_k

        logger.info(
            "UnifiedRetriever init: adapters=%s, top_k=%d",
            list(adapters.keys()), default_top_k,
        )

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        sources: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> list[RetrievedItem]:
        """统一检索入口。

        Args:
            query: 查询文本。
            top_k: 返回数量上限（默认 self._default_top_k）。
            sources: 指定检索源列表（None 表示全部）。
            **kwargs: 透传给各 Adapter。

        Returns:
            RetrievedItem 列表（按 final_score 降序）。
        """
        top_k = top_k or self._default_top_k
        active_sources = sources or list(self._adapters.keys())

        # ── 1. Search: 并发检索 ──
        search_tasks = []
        for src in active_sources:
            adapter = self._adapters.get(src)
            if adapter is None:
                continue
            search_tasks.append(
                adapter.search(query, top_k=top_k, **kwargs)
            )

        results: list[RetrievedItem] = []
        if search_tasks:
            gathered = await asyncio.gather(*search_tasks, return_exceptions=True)
            for items in gathered:
                if isinstance(items, list):
                    results.extend(items)
                elif isinstance(items, Exception):
                    logger.warning("Adapter search failed: %s", items)

        # ── 2. Score: 统一评分 ──
        for item in results:
            adapter = self._adapters.get(item.source)
            source_weight = getattr(adapter, "source_weight", 0.5) if adapter else 0.5
            item.score = self._scoring.score(
                {"metadata": item.metadata, "relevance_score": item.score},
                source_weight=source_weight,
            )

        # ── 3. Merge: 去重 ──
        results = self._deduplicate(results)

        # ── 4. Rank: 排序截断 ──
        results.sort(key=lambda x: x.score, reverse=True)
        if len(results) > top_k:
            results = results[:top_k]

        logger.info(
            "UnifiedRetriever: query='%s' → %d results (top_k=%d)",
            query[:60], len(results), top_k,
        )
        return results

    # ── 去重 ──

    def _deduplicate(self, items: list[RetrievedItem]) -> list[RetrievedItem]:
        """跨源去重。

        策略:
            1. 实体去重：同 entity_key → 保留 score 最高的
            2. 内容精确去重：同 content → 保留 score 最高的
            3. 语义去重：embedding sim > 0.95 → 保留 score 最高的
        """
        if len(items) <= 1:
            return items

        # 1. entity_key 去重
        entity_map: dict[str, RetrievedItem] = {}
        for item in items:
            ek = item.metadata.get("entity_key") or item.metadata.get("fact_id") or ""
            if ek:
                if ek not in entity_map or item.score > entity_map[ek].score:
                    entity_map[ek] = item

        # 2. 内容精确去重
        content_map: dict[str, RetrievedItem] = {}
        for item in items:
            key = item.content[:200]  # 前 200 字符做 key
            if key not in content_map or item.score > content_map[key].score:
                content_map[key] = item

        # 3. 语义去重（有 embedding 时）
        deduped = list(content_map.values())
        if all(i.embedding is None for i in deduped):
            return deduped

        final: list[RetrievedItem] = []
        for item in deduped:
            if item.embedding is None:
                final.append(item)
                continue

            is_dup = False
            for existing in final:
                if existing.embedding is None:
                    continue
                if len(item.embedding) != len(existing.embedding):
                    continue
                sim = self._cosine_similarity(item.embedding, existing.embedding)
                if sim > _DEDUP_SIM_THRESHOLD:
                    is_dup = True
                    if item.score > existing.score:
                        # 保留 score 更高的
                        final.remove(existing)
                        final.append(item)
                    break

            if not is_dup:
                final.append(item)

        return final

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
