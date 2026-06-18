"""测试 ContextCompressor。"""

import pytest
from context_os.optimizer.compressor import ContextCompressor
from context_os.core.models import ConversationTurn


class TestContextCompressor:
    """ContextCompressor 测试。"""

    @pytest.fixture
    def compressor(self):
        return ContextCompressor()

    def test_count_tokens_chinese(self, compressor):
        """中文 Token 估算。"""
        text = "你好世界"
        tokens = compressor.count_tokens(text)
        assert tokens == 7  # 4个中文字 * 1.5 + 1

    def test_count_tokens_english(self, compressor):
        """英文 Token 估算。"""
        tokens = compressor.count_tokens("hello world")
        assert tokens == 4  # 11个字符 * 0.25 + 1

    @pytest.mark.asyncio
    async def test_compress_conversation_below_limit(self, compressor):
        """未超限时不压缩。"""
        turns = [ConversationTurn(role="user", content="hi")]
        result = await compressor.compress_conversation(turns, max_tokens=2000)
        assert "hi" in result
        assert "user:" in result.lower()

    @pytest.mark.asyncio
    async def test_compress_conversation_above_limit(self, compressor):
        """超限时截断（无 LLM 降级）。"""
        long_turns = [
            ConversationTurn(role="user", content="a" * 5000),
            ConversationTurn(role="assistant", content="b" * 5000),
        ]
        result = await compressor.compress_conversation(long_turns, max_tokens=1000)
        # 无 LLM 时只保留后一半
        assert len(result) > 0
