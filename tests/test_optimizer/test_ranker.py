"""测试 RelevanceRanker。"""

import pytest
from datetime import datetime, timedelta, timezone
from context_os.optimizer.ranker import RelevanceRanker
from context_os.core.models import MemoryItem, MemoryType


class TestRelevanceRanker:
    """RelevanceRanker 测试。"""

    @pytest.fixture
    def ranker(self):
        return RelevanceRanker(time_decay_hours=24)

    def make_item(self, content: str, age_hours: float = 0, access_count: int = 0):
        return MemoryItem(
            type=MemoryType.LONG_TERM,
            content=content,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=age_hours),
            access_count=access_count,
        )

    def test_rank_memories_newer_first(self, ranker):
        """较新的记忆应该排在前面（相同条件下）。"""
        old = self.make_item("old item", age_hours=48)
        new = self.make_item("new item", age_hours=1)
        result = ranker.rank_memories([old, new])
        assert result[0].content == "new item"

    def test_rank_memories_frequent_first(self, ranker):
        """高频访问的排在前面（相同时间条件下）。"""
        low = self.make_item("low freq", age_hours=1, access_count=1)
        high = self.make_item("high freq", age_hours=1, access_count=20)
        result = ranker.rank_memories([low, high])
        assert result[0].content == "high freq"

    def test_empty_input(self, ranker):
        """空输入返回空列表。"""
        result = ranker.rank_memories([])
        assert result == []

    def test_top_k(self, ranker):
        """验证 top_k 限制。"""
        items = [self.make_item(f"item-{i}") for i in range(20)]
        result = ranker.rank_memories(items, top_k=5)
        assert len(result) == 5

    @staticmethod
    def test_cosine_similarity():
        """余弦相似度计算正确。"""
        ranker = RelevanceRanker()
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert ranker._cosine_similarity(a, b) == 1.0
        assert ranker._cosine_similarity(a, [0.0, 1.0, 0.0]) == 0.0
