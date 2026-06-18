"""Token 预算分配器。

根据模型容量和模块优先级，自动分配各模块的 Token 预算。
"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import TokenBudget

logger = get_logger(__name__)


class TokenBudgetAllocator:
    """Token 预算分配器。

    Args:
        max_total_tokens: 总 Token 上限，默认 128000（Claude Sonnet 4）。
    """

    # 各模块默认占比
    DEFAULT_RATIOS = {
        "instruction": 0.10,   # 系统指令
        "conversation": 0.20,  # 对话历史
        "memory": 0.10,        # 记忆
        "knowledge": 0.45,     # 知识
        "tools": 0.15,         # 工具
    }

    def __init__(self, max_total_tokens: int = 128000):
        self.max_total_tokens = max_total_tokens
        self._ratios = dict(self.DEFAULT_RATIOS)
        logger.info(
            "TokenBudgetAllocator initialized: max=%d, ratios=%s",
            max_total_tokens, self._ratios,
        )

    def allocate(self) -> TokenBudget:
        """按比例分配 Token 预算。

        Returns:
            TokenBudget 对象，包含各模块的预算分配。
        """
        budget = TokenBudget(total=self.max_total_tokens)

        for section, ratio in self._ratios.items():
            budget.breakdown[section] = int(self.max_total_tokens * ratio)

        budget.used = 0
        logger.debug(
            "Allocated budget: total=%d, instruction=%d, conv=%d, mem=%d, knowledge=%d, tools=%d",
            budget.total,
            budget.breakdown.get("instruction", 0),
            budget.breakdown.get("conversation", 0),
            budget.breakdown.get("memory", 0),
            budget.breakdown.get("knowledge", 0),
            budget.breakdown.get("tools", 0),
        )
        return budget

    def count_used(self, context: dict[str, str]) -> int:
        """统计已使用的 Token 数。

        Args:
            context: 各模块内容字典 {section: text}。

        Returns:
            使用的 Token 总数。
        """
        from context_os.optimizer.compressor import ContextCompressor

        total = 0
        for section, text in context.items():
            tokens = ContextCompressor.count_tokens(text)
            logger.debug("  %s: %d tokens", section, tokens)
            total += tokens

        return total

    def adjust_for_model(self, model_max_tokens: int) -> None:
        """根据模型能力调整总预算。

        Args:
            model_max_tokens: 模型的最大 Token 容量。
        """
        old_max = self.max_total_tokens
        self.max_total_tokens = min(self.max_total_tokens, model_max_tokens)
        if old_max != self.max_total_tokens:
            logger.info(
                "Adjusted budget for model: %d -> %d",
                old_max, self.max_total_tokens,
            )
