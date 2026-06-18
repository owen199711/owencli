"""测试 TaskParser。"""

import pytest
from context_os.intent.classifier import IntentClassifier
from context_os.intent.extractor import EntityExtractor
from context_os.intent.parser import TaskParser
from context_os.core.models import IntentType, GoalType


class TestTaskParser:
    """TaskParser 测试。"""

    @pytest.fixture
    def parser(self):
        return TaskParser(
            classifier=IntentClassifier(),
            extractor=EntityExtractor(),
        )

    @pytest.mark.asyncio
    async def test_parse_full(self, parser):
        """完整解析流程。"""
        task = await parser.parse("帮我写一个 FastAPI 应用")
        assert task.intent == IntentType.CODING
        assert task.goal == GoalType.GENERATE
        assert task.raw_input == "帮我写一个 FastAPI 应用"
        assert task.confidence > 0

    @pytest.mark.asyncio
    async def test_parse_debug(self, parser):
        """调试意图解析。"""
        task = await parser.parse("修复登录页面的 bug")
        assert task.intent == IntentType.DEBUGGING

    @pytest.mark.asyncio
    async def test_parse_returns_task_spec(self, parser):
        """验证返回的 TaskSpec 字段完整。"""
        task = await parser.parse("如何安装 Python？")
        assert task.id is not None
        assert task.entities is not None
        assert task.tool_requirements is not None
        assert task.knowledge_requirements is not None
