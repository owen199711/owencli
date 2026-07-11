"""ScoringEngine 专项测试（Phase 8）。

覆盖:
    - 统一评分公式各维度
    - 时间衰减半衰期
    - 跨源权重
    - 边界情况
"""

import pytest
from datetime import datetime, timezone

from context_os.retriever.scoring import ScoringEngine, SourceReliability, SourceWeight


class TestScoringEngineFormula:
    """评分公式测试。"""

    def setup_method(self):
        self.engine = ScoringEngine()

    def test_perfect_score(self):
        """完美参数得高分。"""
        now = datetime.now(timezone.utc).isoformat()
        score = self.engine.score(
            {"metadata": {"source_reliability": 1.0}, "relevance_score": 1.0, "access_count": 100, "timestamp": now},
            semantic=1.0, bm25=1.0,
            source_reliability=1.0, source_weight=1.0,
        )
        assert score > 0.6

    def test_zero_score_case(self):
        """零参数得低分。"""
        score = self.engine.score(
            {"metadata": {}, "relevance_score": 0.0},
            source_reliability=0.5,
        )
        assert score < 0.3

    def test_semantic_dominates(self):
        """语义分最高权重 0.30。"""
        now = datetime.now(timezone.utc).isoformat()
        high_sem = self.engine.score(
            {"metadata": {}, "relevance_score": 0.0, "timestamp": now},
            semantic=1.0, bm25=0.0,
            source_reliability=0.5,
        )
        low_sem = self.engine.score(
            {"metadata": {}, "relevance_score": 0.0, "timestamp": now},
            semantic=0.0, bm25=0.0,
            source_reliability=0.5,
        )
        assert high_sem > low_sem

    def test_source_weight_multiplier(self):
        """跨源权重乘法正确应用。"""
        now = datetime.now(timezone.utc).isoformat()
        score_high = self.engine.score(
            {"metadata": {}, "relevance_score": 0.5, "timestamp": now},
            semantic=0.5, source_reliability=0.8, source_weight=1.0,
        )
        score_low = self.engine.score(
            {"metadata": {}, "relevance_score": 0.5, "timestamp": now},
            semantic=0.5, source_reliability=0.8, source_weight=0.3,
        )
        assert score_high > score_low
        assert score_low < score_high * 0.8  # 权重差别明显

    def test_capped_at_one(self):
        """分数不超过 1.0。"""
        now = datetime.now(timezone.utc).isoformat()
        score = self.engine.score(
            {"metadata": {"source_reliability": 1.0}, "relevance_score": 1.0, "access_count": 99999, "timestamp": now},
            semantic=1.0, bm25=1.0,
            source_reliability=1.0, source_weight=1.0,
        )
        assert score <= 1.0

    def test_source_reliability_from_metadata(self):
        """source_reliability 从 metadata 自动读取。"""
        score_default = self.engine.score(
            {"metadata": {}, "relevance_score": 0.5},
        )
        score_high = self.engine.score(
            {"metadata": {"source_reliability": 1.0}, "relevance_score": 0.5},
        )
        assert score_high > score_default

    def test_time_decay_old(self):
        """旧时间戳衰减值低。"""
        score_old = self.engine.score(
            {"metadata": {}, "relevance_score": 0.5, "timestamp": "2020-01-01T00:00:00Z"},
            source_reliability=0.8,
        )
        assert score_old < 0.2  # 很旧的时间

    def test_no_timestamp_default(self):
        """无时间戳使用默认衰减 0.5。"""
        score = self.engine.score(
            {"metadata": {}, "relevance_score": 0.5},
            source_reliability=0.8,
        )
        assert 0 <= score <= 1


class TestSourceConstants:
    """常量测试。"""

    def test_user_explicit_highest(self):
        """用户显式陈述可靠性最高。"""
        assert SourceReliability.USER_EXPLICIT == 1.00

    def test_default_midpoint(self):
        """默认可靠性在中间。"""
        assert SourceReliability.DEFAULT == 0.50

    def test_long_term_weight_highest(self):
        """LTM 权重最高。"""
        assert SourceWeight.LONG_TERM > SourceWeight.EXPERIENCE
        assert SourceWeight.LONG_TERM > SourceWeight.SESSION

    def test_session_weight_lowest(self):
        """Session 权重最低。"""
        assert SourceWeight.SESSION <= SourceWeight.JOURNAL
        assert SourceWeight.SESSION < SourceWeight.LONG_TERM
