"""测试 ClaudePromptAdapter。"""

import pytest
from context_os.packager.adapters.claude import ClaudePromptAdapter
from context_os.core.models import (
    LLMProvider, OptimizedContext, UnifiedContext,
    MemoryItem, MemoryType, TokenBudget,
)


class TestClaudePromptAdapter:
    """ClaudePromptAdapter 测试。"""

    @pytest.fixture
    def adapter(self):
        return ClaudePromptAdapter()

    def test_pack_claude_xml_format(self, adapter):
        """验证输出包含 XML 标签。"""
        ctx = OptimizedContext(
            compressed=False,
            token_usage=TokenBudget(total=1000),
            context=UnifiedContext(),
        )
        result = adapter.pack(ctx)
        assert result.provider == LLMProvider.CLAUDE
        assert "owencli" in result.raw_prompt
        assert "system" in result.sections

    def test_pack_with_memory(self, adapter):
        """包含记忆时输出 memory 标签。"""
        ctx = OptimizedContext(
            compressed=False,
            token_usage=TokenBudget(total=1000),
            context=UnifiedContext(
                memory=[
                    MemoryItem(
                        type=MemoryType.LONG_TERM,
                        content="test memory content",
                        relevance_score=0.9,
                    ),
                ],
            ),
        )
        result = adapter.pack(ctx)
        assert "<memory>" in result.raw_prompt
        assert "test memory content" in result.raw_prompt

    def test_pack_empty_context(self, adapter):
        """空 Context 仍然生成有效 prompt。"""
        ctx = OptimizedContext(
            compressed=False,
            token_usage=TokenBudget(total=1000),
            context=UnifiedContext(),
        )
        result = adapter.pack(ctx)
        assert len(result.raw_prompt) > 20
