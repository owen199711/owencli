"""测试 ContextSelector。"""

import pytest
from context_os.orchestrator.selector import ContextSelector, ContextFlag
from context_os.core.models import TaskSpec, IntentType, GoalType, Constraint


class TestContextSelector:
    """ContextSelector 测试。"""

    @pytest.fixture
    def selector(self):
        return ContextSelector()

    def make_task(self, intent: IntentType, max_tokens=None):
        return TaskSpec(
            raw_input="test",
            intent=intent,
            goal=GoalType.EXPLAIN,
            constraint=Constraint(max_tokens=max_tokens),
        )

    def test_select_qa(self, selector):
        """QA 类型只含 CONVERSATION | KNOWLEDGE。"""
        task = self.make_task(IntentType.QA)
        flags = selector.select(task)
        assert ContextFlag.CONVERSATION in flags
        assert ContextFlag.KNOWLEDGE in flags
        assert ContextFlag.IDENTITY not in flags
        assert ContextFlag.TOOLS not in flags

    def test_select_coding(self, selector):
        """CODING 类型含全部 flags。"""
        task = self.make_task(IntentType.CODING)
        flags = selector.select(task)
        assert ContextFlag.IDENTITY in flags
        assert ContextFlag.CONVERSATION in flags
        assert ContextFlag.ENVIRONMENT in flags
        assert ContextFlag.MEMORY in flags
        assert ContextFlag.TOOLS in flags

    def test_select_search(self, selector):
        """SEARCH 类型只含 KNOWLEDGE。"""
        task = self.make_task(IntentType.SEARCH)
        flags = selector.select(task)
        assert ContextFlag.KNOWLEDGE in flags
        assert ContextFlag.IDENTITY not in flags
        assert ContextFlag.CONVERSATION not in flags

    def test_select_with_tight_token(self, selector):
        """Token 紧张时裁减低优先级 Context。"""
        task = self.make_task(IntentType.CODING, max_tokens=4000)
        flags = selector.select(task)
        assert ContextFlag.MEMORY not in flags
        assert ContextFlag.ENVIRONMENT not in flags
