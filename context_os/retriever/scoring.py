"""ScoringEngine — 统一评分公式。

公式:
    unified = 0.30 × semantic + 0.20 × bm25
            + 0.15 × source_reliability + 0.10 × time_decay
            + 0.15 × relevance + 0.10 × access_freq

跨源合并:
    final = unified × source_weight
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class SourceReliability:
    """Source Reliability 分级常量。"""

    USER_EXPLICIT = 1.00       # 用户显式陈述
    CHANNEL_A_RULE = 1.00      # 通道 A 规则抽取
    OFFICIAL_DATA = 0.95       # 官方/系统数据
    USER_IMPLICIT = 0.80       # 用户隐式推断
    CHANNEL_B_LLM = 0.70       # 通道 B LLM 抽取
    LLM_INFERRED = 0.60        # LLM 推断结论
    JOURNAL_PENDING = 0.50     # Journal 未处理原始记录
    DEFAULT = 0.50             # 默认


@dataclass
class SourceWeight:
    """Source Weight 架构级预设常量。"""

    LONG_TERM = 1.0
    EXPERIENCE = 0.8
    KNOWLEDGE = 0.6
    JOURNAL = 0.4
    SESSION = 0.3


# 统一评分权重
_W_SEMANTIC = 0.30
_W_BM25 = 0.20
_W_SOURCE_RELIABILITY = 0.15
_W_TIME_DECAY = 0.10
_W_RELEVANCE = 0.15
_W_ACCESS = 0.10

# 时间衰减（统一半衰期 7 天）
_TIME_HALF_LIFE_DAYS = 7.0
_TIME_DECAY_LAMBDA = math.log(2) / _TIME_HALF_LIFE_DAYS


class ScoringEngine:
    """统一评分引擎。

    使用方式:
        engine = ScoringEngine()
        score = engine.score(item, query_embedding=None)
        final = engine.apply_source_weight(score, source_weight=1.0)
    """

    def score(
        self,
        item: dict[str, Any],
        semantic: float = 0.0,
        bm25: float = 0.0,
        source_reliability: Optional[float] = None,
        source_weight: float = 1.0,
    ) -> float:
        """计算统一综合得分。

        Args:
            item: 检索条目（含 metadata, timestamp, access_count, relevance_score）。
            semantic: 语义相似度 (0-1)。
            bm25: BM25 关键词得分（归一化后）。
            source_reliability: 来源可靠性（从 metadata 读取或传入）。
            source_weight: 跨源合并权重乘数。

        Returns:
            final_score (0-1)。
        """
        # source_reliability 从 item 读取或使用传入值
        if source_reliability is None:
            meta = item.get("metadata", {}) or {}
            source_reliability = meta.get("source_reliability", SourceReliability.DEFAULT)

        # 时间衰减
        time_decay = self._calc_time_decay(item)

        # 相关性
        relevance = min(item.get("relevance_score") or 0.0, 1.0)

        # 访问频率（除以 10 归一化）
        access_norm = min((item.get("access_count") or 0) / 10.0, 1.0)

        # 统一公式
        unified = (
            _W_SEMANTIC * semantic
            + _W_BM25 * bm25
            + _W_SOURCE_RELIABILITY * source_reliability
            + _W_TIME_DECAY * time_decay
            + _W_RELEVANCE * relevance
            + _W_ACCESS * access_norm
        )

        # 跨源权重
        final = unified * source_weight
        return min(final, 1.0)

    @staticmethod
    def _calc_time_decay(item: dict[str, Any]) -> float:
        """计算时间衰减（统一半衰期 7 天）。"""
        ts_str = item.get("timestamp") or item.get("created_at") or ""
        if not ts_str:
            return 0.5

        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            days_old = (datetime.now(timezone.utc) - ts).days
            return math.exp(-_TIME_DECAY_LAMBDA * max(0, days_old))
        except Exception:
            return 0.5

    @staticmethod
    def apply_source_weight(unified_score: float, source_weight: float) -> float:
        """跨源合并：乘以 source_weight。"""
        return unified_score * source_weight
