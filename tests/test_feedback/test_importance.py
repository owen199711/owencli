"""测试 ImportanceScorer — Layer 3 综合评分。"""

import pytest
from context_os.feedback.memory_importance import ImportanceScorer, ImportanceScore


class TestImportanceScorer:
    """ImportanceScorer 综合评分测试。"""

    def test_identity_score_high(self):
        scorer = ImportanceScorer()
        result = scorer.score("我叫小明，今年25岁", task_intent="qa", ltm_count=5)
        assert result.identity >= 0.6
        assert result.overall > 0

    def test_identity_score_low(self):
        scorer = ImportanceScorer()
        result = scorer.score("今天天气不错", task_intent="qa", ltm_count=5)
        assert result.identity <= 0.2

    def test_state_score_with_numbers_agent(self):
        scorer = ImportanceScorer()
        result = scorer.score("Alice 余额 7101 元", task_intent="agent", task_importance=0.8)
        assert result.state >= 0.7

    def test_state_score_with_memory_keyword(self):
        scorer = ImportanceScorer()
        result = scorer.score("记住我喜欢深色模式", task_intent="qa")
        assert result.state >= 0.7

    def test_cold_start_high_when_few_memories(self):
        scorer = ImportanceScorer()
        result = scorer.score("测试内容", task_intent="qa", ltm_count=5)
        assert result.cold_start > 0.5
        assert result.overall > 0  # 冷启动加权

    def test_cold_start_zero_when_many_memories(self):
        scorer = ImportanceScorer()
        result = scorer.score("测试内容", task_intent="qa", ltm_count=100)
        assert result.cold_start == 0.0

    def test_scenario_user_name_first_round(self):
        """测试 'Alice 的工资卡有 5000 元' 这种初始状态录入场景。"""
        scorer = ImportanceScorer()
        result = scorer.score(
            "Alice 的工资卡有 5000 元，Bob 的储蓄卡有 10000 元",
            task_intent="agent",
            task_importance=0.5,
            reward_score=0.5,
            ltm_count=5,  # 冷启动阶段
        )
        # 第三方角色，不涉及用户身份，identity 可能较低
        # 但有状态变更信号和冷启动保护
        assert result.state >= 0.5  # 有数字+金额信号
        assert result.cold_start > 0  # 冷启动保护

    def test_scenario_trivial_chat(self):
        """测试 '今天天气不错' 这种闲聊场景不应通过。"""
        scorer = ImportanceScorer()
        result = scorer.score(
            "今天天气不错",
            task_intent="qa",
            task_importance=0.3,
            reward_score=0.5,
            ltm_count=100,
        )
        assert result.overall < 0.5

    def test_scenario_dinner_split(self):
        """测试 'AA 制聚餐' 场景不应通过（除非结论重要）。"""
        scorer = ImportanceScorer()
        result = scorer.score(
            "Alice、Bob、Charlie 三人聚餐花费 900 元，AA 制均摊",
            task_intent="agent",
            task_importance=0.5,
            reward_score=0.6,
            ltm_count=100,
        )
        assert result.overall < 0.5  # 无身份信息，不涉及用户

    def test_passing_score_bool_property(self):
        """测试 ImportanceScore.__bool__。"""
        s = ImportanceScore(overall=0.6, identity=0.8, state=0.5,
                            task=0.5, cold_start=0.0, quality=0.5)
        assert bool(s) is True

        s2 = ImportanceScore(overall=0.3, identity=0.1, state=0.1,
                             task=0.3, cold_start=0.0, quality=0.3)
        assert bool(s2) is False

    def test_quality_score_maps_directly(self):
        scorer = ImportanceScorer()
        result = scorer.score("内容", task_intent="qa", reward_score=0.9, ltm_count=50)
        assert result.quality == 0.9

        result = scorer.score("内容", task_intent="qa", reward_score=0.2, ltm_count=50)
        assert result.quality == 0.2

    def test_breakdown_keys(self):
        scorer = ImportanceScorer()
        result = scorer.score("测试", task_intent="qa", ltm_count=10)
        assert set(result.breakdown.keys()) == {
            "identity", "state", "task", "cold_start", "quality"
        }

    def test_custom_weights(self):
        """自定义权重配置。"""
        scorer = ImportanceScorer(
            identity_weight=0.5,
            state_weight=0.0,
            task_weight=0.0,
            cold_start_weight=0.0,
            quality_weight=0.5,
        )
        result = scorer.score("我叫小明", task_intent="qa", ltm_count=50)
        assert result.overall > 0.3  # identity is high
