"""测试 IntentClassifier。"""

import pytest
from context_os.intent.classifier import IntentClassifier
from context_os.core.models import IntentType, GoalType


class TestIntentClassifier:
    """IntentClassifier 测试。"""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier()

    def test_classify_debug_keyword(self, classifier):
        """包含 bug 关键词应返回 DEBUGGING。"""
        intent, goal, conf = classifier._classify_with_rules("fix the crash bug")
        assert intent == IntentType.DEBUGGING
        assert goal == GoalType.FIX
        assert conf >= 0.7

    def test_classify_coding_keyword(self, classifier):
        """包含 write/create 应返回 CODING。"""
        intent, goal, conf = classifier._classify_with_rules("write a fastapi app")
        assert intent == IntentType.CODING
        assert goal == GoalType.GENERATE
        assert conf >= 0.7

    def test_classify_search_keyword(self, classifier):
        """包含 search/find 应返回 SEARCH。"""
        intent, goal, conf = classifier._classify_with_rules("search for python tutorials")
        assert intent == IntentType.SEARCH

    def test_classify_default(self, classifier):
        """无匹配关键词默认返回 QA/EXPLAIN。"""
        intent, goal, conf = classifier._classify_with_rules("hello world")
        assert intent == IntentType.QA
        assert goal == GoalType.EXPLAIN
        assert conf == 0.5

    def test_classify_chinese(self, classifier):
        """中文关键词匹配。"""
        intent, goal, conf = classifier._classify_with_rules("修复这个 bug")
        assert intent == IntentType.DEBUGGING

    @pytest.mark.asyncio
    async def test_classify_llm_fallback(self, classifier):
        """无 LLM 时自动降级到规则。"""
        result = await classifier.classify("fix the crash")
        assert result[0] == IntentType.DEBUGGING

    def test_refactor_keyword(self, classifier):
        """重构关键词匹配。"""
        intent, goal, conf = classifier._classify_with_rules("重构这个模块")
        assert intent == IntentType.CODING
        assert goal == GoalType.REFACTOR
