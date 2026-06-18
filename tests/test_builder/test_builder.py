"""测试 ContextBuilder。"""

import pytest
from context_os.builder.builder import ContextBuilder
from context_os.collection.conversation import ConversationCollector
from context_os.collection.environment import EnvironmentCollector
from context_os.collection.identity import IdentityCollector
from context_os.memory.working import WorkingMemory
from context_os.orchestrator.router import ContextRouter
from context_os.orchestrator.selector import ContextSelector
from context_os.core.models import TaskSpec, IntentType, GoalType
from tests.conftest import MockLLMClient


class TestContextBuilder:
    """ContextBuilder 测试。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder(
            selector=ContextSelector(),
            router=ContextRouter(),
            identity=IdentityCollector(),
            conversation=ConversationCollector(),
            environment=EnvironmentCollector(),
            working_memory=WorkingMemory(),
            long_term_memory=None,  # 测试中跳过记忆
        )

    @pytest.mark.asyncio
    async def test_build_success(self, builder):
        """正常构建 UnifiedContext。"""
        task = TaskSpec(
            raw_input="test",
            intent=IntentType.QA,
            goal=GoalType.EXPLAIN,
        )
        ctx = await builder.build(task)
        assert ctx is not None
        assert ctx.conversation is not None
        assert ctx.environment is not None

    @pytest.mark.asyncio
    async def test_build_with_empty_input(self, builder):
        """空输入时不崩溃。"""
        task = TaskSpec(
            raw_input="",
            intent=IntentType.QA,
            goal=GoalType.EXPLAIN,
        )
        ctx = await builder.build(task)
        assert ctx is not None
