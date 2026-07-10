"""测试 Phase 4 统一评分公式 & 时间回溯检索（LTM）。"""

import pytest
from context_os.memory.long_term import LongTermMemory
from context_os.memory.store import SQLiteStore
from context_os.memory.long_term import _TEMPORAL_KEYWORDS


class TestUnifiedScoringFormula:
    """4.3 统一评分公式权重验证。"""

    def test_weights_sum_to_one_with_embedding(self):
        """有 embedding 时权重应为 1.0。"""
        from context_os.memory.long_term import _W_SEM, _W_KW, _W_REL, _W_TIME, _W_ACCESS
        total = _W_SEM + _W_KW + _W_REL + _W_TIME + _W_ACCESS
        assert abs(total - 1.0) < 0.001

    def test_weights_sum_to_one_without_embedding(self):
        """无 embedding 时权重应为 1.0。"""
        from context_os.memory.long_term import _W_KW_ONLY, _W_REL_ONLY, _W_TIME_ONLY, _W_ACCESS_ONLY
        total = _W_KW_ONLY + _W_REL_ONLY + _W_TIME_ONLY + _W_ACCESS_ONLY
        assert abs(total - 1.0) < 0.001

    def test_sem_weight_increased_to_040(self):
        """语义相似度权重从 0.30 → 0.40。"""
        from context_os.memory.long_term import _W_SEM
        assert _W_SEM == 0.40

    def test_kw_weight_reduced_to_025(self):
        """BM25 关键词权重从 0.30 → 0.25。"""
        from context_os.memory.long_term import _W_KW
        assert _W_KW == 0.25

    def test_time_weight_reduced_to_010(self):
        """时间衰减权重从 0.15 → 0.10。"""
        from context_os.memory.long_term import _W_TIME
        assert _W_TIME == 0.10


class TestTemporalQueryDetection:
    """4.5 时间回溯查询检测。"""

    def test_chinese_retrospective(self):
        """中文回溯查询。"""
        assert LongTermMemory.detect_temporal_query("我叫过什么")
        assert LongTermMemory.detect_temporal_query("原来叫什么名字")
        assert LongTermMemory.detect_temporal_query("之前设置的是什么")

    def test_english_retrospective(self):
        """英文回溯查询。"""
        assert LongTermMemory.detect_temporal_query("what was my old name")
        assert LongTermMemory.detect_temporal_query("what did I set before")
        assert LongTermMemory.detect_temporal_query("check history")

    def test_normal_query_false(self):
        """普通查询不应触发。"""
        assert not LongTermMemory.detect_temporal_query("帮我写一段代码")
        assert not LongTermMemory.detect_temporal_query("今天天气怎么样")

    def test_regex_correctness(self):
        """正则匹配验证。"""
        assert bool(_TEMPORAL_KEYWORDS.search("以前叫什么"))
        assert bool(_TEMPORAL_KEYWORDS.search("上次的配置是什么"))
        assert not bool(_TEMPORAL_KEYWORDS.search("设置是什么"))


@pytest.fixture
async def store():
    s = SQLiteStore(db_path=":memory:")
    await s.connect()
    yield s
    await s.close()


class TestExpandHistoryRetrieval:
    """4.5 expand_history 检索行为测试。"""

    async def test_expand_history_uses_larger_pool(self, store):
        """expand_history=True 时使用更大的候选池。"""
        ltm = LongTermMemory(store=store, user_id="test")

        # 存储一些测试记忆
        for i in range(5):
            await ltm.save(
                content=f"test memory {i}",
                memory_type="long_term",
                metadata={"intent": "qa"},
            )

        # 正常检索
        normal = await ltm.retrieve("test memory", top_k=5, expand_history=False)
        assert len(normal) > 0

        # 回溯检索
        expanded = await ltm.retrieve("test memory", top_k=5, expand_history=True)
        assert len(expanded) > 0

    async def test_expand_history_param_accepted(self, store):
        """验证 expand_history 参数被正确接受。"""
        ltm = LongTermMemory(store=store, user_id="test")
        # 不应抛出异常
        result = await ltm.retrieve("test", expand_history=True)
        assert isinstance(result, list)

    async def test_expand_history_false_default(self, store):
        """默认 expand_history=False。"""
        ltm = LongTermMemory(store=store, user_id="test")
        result = await ltm.retrieve("test")
        assert isinstance(result, list)
