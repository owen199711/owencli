"""上下文压缩器。

通过摘要、截断、语义压缩等方式减少 Token 消耗。
"""

from __future__ import annotations

from typing import Any, List, Optional

from context_os.core.logger import get_logger
from context_os.core.models import ConversationTurn

logger = get_logger(__name__)


class ContextCompressor:
    """上下文压缩器。

    Args:
        llm_client: 可选的大模型客户端，用于语义压缩。
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        logger.info("ContextCompressor initialized (llm=%s)", "available" if llm_client else "None")

    @staticmethod
    def count_tokens(text: str) -> int:
        """估算文本 Token 数。

        中文字符 ~1.5 tokens，其他字符 ~0.25 tokens。

        Args:
            text: 输入文本。

        Returns:
            估算 Token 数。
        """
        chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other = len(text) - chinese
        return int(chinese * 1.5 + other * 0.25) + 1

    async def compress_conversation(
        self,
        history: List[ConversationTurn],
        max_tokens: int = 2000,
    ) -> str:
        """压缩对话历史。

        策略:
            - 未超限 → 直接拼接
            - 超限且 LLM 可用 → LLM 摘要
            - 超限且 LLM 不可用 → 保留后一半

        Args:
            history: 对话轮次列表。
            max_tokens: 压缩后的 Token 上限。

        Returns:
            压缩后的对话文本。
        """
        if not history:
            return ""

        full_text = "\n".join(f"{t.role}: {t.content}" for t in history)
        tokens = self.count_tokens(full_text)

        if tokens <= max_tokens:
            logger.debug("Conversation within budget: %d/%d tokens", tokens, max_tokens)
            return full_text

        # 超限压缩
        if self.llm_client:
            logger.info("Compressing conversation via LLM: %d -> %d tokens", tokens, max_tokens)
            prompt = (
                f"Summarize the following conversation in under {max_tokens} tokens. "
                f"Preserve all key information, decisions, and user preferences.\n\n{full_text}"
            )
            return await self.llm_client.complete(prompt, max_tokens=max_tokens + 200)

        # 降级：保留后一半
        half = len(history) // 2
        compressed = "\n".join(f"{t.role}: {t.content}" for t in history[half:])
        kept_tokens = self.count_tokens(compressed)
        logger.warning(
            "LLM unavailable, truncated conversation: %d -> %d tokens (kept last %d turns)",
            tokens, kept_tokens, len(history) - half,
        )
        return compressed

    async def compress_memories(
        self,
        memories: List[str],
        max_tokens: int = 1000,
    ) -> str:
        """压缩记忆列表。

        Args:
            memories: 记忆内容列表。
            max_tokens: Token 上限。

        Returns:
            压缩后的记忆文本。
        """
        text = "\n---\n".join(memories)
        tokens = self.count_tokens(text)

        if tokens <= max_tokens:
            return text

        if self.llm_client:
            logger.info("Compressing memories via LLM: %d -> %d tokens", tokens, max_tokens)
            prompt = (
                f"Summarize the following memory entries in under {max_tokens} tokens. "
                f"Keep all unique facts and preferences.\n\n{text}"
            )
            return await self.llm_client.complete(prompt, max_tokens=max_tokens + 200)

        # 降级：从前往后排，直到超限
        result_parts = []
        current = 0
        for m in memories:
            t = self.count_tokens(m)
            if current + t > max_tokens:
                break
            result_parts.append(m)
            current += t

        logger.debug("Compressed %d memories -> %d tokens", len(memories), current)
        return "\n---\n".join(result_parts)
