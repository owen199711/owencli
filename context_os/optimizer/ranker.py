"""相关性排序器。

基于语义相似度、时间衰减、访问频率三个维度，对记忆条目进行综合排序。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import numpy as np

from context_os.core.logger import get_logger
from context_os.core.models import KnowledgeChunk, MemoryItem

logger = get_logger(__name__)


class RelevanceRanker:
    """多维相关性排序器。

    Args:
        time_decay_hours: 时间衰减的半衰期（小时），默认 24。
    """

    def __init__(self, time_decay_hours: float = 24.0):
        self.time_decay_hours = time_decay_hours
        logger.info("RelevanceRanker initialized (time_decay=%.1fh)", time_decay_hours)

    def rank_memories(
        self,
        items: List[MemoryItem],
        query_embedding: Optional[List[float]] = None,
        top_k: int = 10,
    ) -> List[MemoryItem]:
        """按综合得分排序记忆条目。

        得分公式: score = 0.5 * 语义相似度 + 0.3 * 时间衰减 + 0.2 * 访问频率

        Args:
            items: 待排序的记忆条目。
            query_embedding: 查询向量，用于语义相似度计算。
            top_k: 返回数量上限。

        Returns:
            排序后的 MemoryItem 列表。
        """
        if not items:
            return []

        # 统一为 offset-naive UTC，与 SQLite 存储的 timestamp 保持一致
        now = datetime.utcnow()

        for item in items:
            # 1. 语义相似度
            semantic_score = 0.0
            if query_embedding and item.embedding:
                semantic_score = self._cosine_similarity(query_embedding, item.embedding)

            # 2. 时间衰减（越近的越高）
            # 防御性处理：若 timestamp 带 tz，先剥离
            ts = item.timestamp
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            age_seconds = (now - ts).total_seconds()
            age_hours = age_seconds / 3600
            time_score = float(np.exp(-age_hours / self.time_decay_hours))

            # 3. 访问频率
            freq_score = float(np.log1p(item.access_count) / 10.0)

            # 综合得分
            item.relevance_score = (
                0.5 * semantic_score +
                0.3 * time_score +
                0.2 * min(freq_score, 1.0)
            )

        # 排序
        items.sort(key=lambda x: x.relevance_score, reverse=True)

        result = items[:top_k]
        avg_score = np.mean([r.relevance_score for r in result]) if result else 0
        logger.debug(
            "Ranked %d memories -> top %d (avg_score=%.3f)",
            len(items), len(result), avg_score,
        )
        return result

    def rank_knowledge(
        self,
        chunks: List[KnowledgeChunk],
        top_k: int = 5,
    ) -> List[KnowledgeChunk]:
        """按得分排序知识块。

        Args:
            chunks: 待排序的知识块。
            top_k: 返回上限。

        Returns:
            排序后的 KnowledgeChunk 列表。
        """
        chunks.sort(key=lambda x: x.score, reverse=True)
        result = chunks[:top_k]
        logger.debug("Ranked %d knowledge chunks -> top %d", len(chunks), len(result))
        return result

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算两个向量的余弦相似度。"""
        a_arr = np.array(a, dtype=np.float64)
        b_arr = np.array(b, dtype=np.float64)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
