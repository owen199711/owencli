"""测试 Fixture 和 Mock。"""

import pytest
from context_os.core.models import (
    GoalType, IntentType, TaskSpec,
    UnifiedContext, ConversationContext, ConversationTurn,
)


class MockLLMClient:
    """Mock LLM 客户端，返回预设文本。"""

    def __init__(self, response: str = "mock response"):
        self.response = response

    async def complete(self, prompt, **kwargs):
        return self.response


@pytest.fixture
def sample_task_spec():
    """返回一个示例 TaskSpec。"""
    return TaskSpec(
        raw_input="帮我分析 Kubernetes 集群 CrashLoopBackOff",
        intent=IntentType.DEBUGGING,
        goal=GoalType.FIX,
        confidence=0.85,
    )


@pytest.fixture
def sample_unified_context():
    """返回填充了假数据的 UnifiedContext。"""
    return UnifiedContext(
        conversation=ConversationContext(
            history=[
                ConversationTurn(role="user", content="你好"),
                ConversationTurn(role="assistant", content="你好，有什么可以帮你？"),
            ],
            status="running",
        ),
    )


@pytest.fixture
def mock_llm_client():
    """返回 MockLLMClient 实例。"""
    return MockLLMClient()
