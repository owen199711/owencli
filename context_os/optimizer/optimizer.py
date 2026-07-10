"""Context Optimizer 编排入口。

协调 Ranker、Compressor、Budget，生成 OptimizedContext。
"""

from __future__ import annotations

from typing import Optional

from context_os.core.logger import get_logger
from context_os.core.models import (
    OptimizedContext, TaskSpec, TokenBudget, UnifiedContext,
)
from context_os.optimizer.budget import TokenBudgetAllocator
from context_os.optimizer.compressor import ContextCompressor
from context_os.optimizer.ranker import RelevanceRanker

logger = get_logger(__name__)


class ContextOptimizer:
    """Context 优化器。

    执行流程:
        1. 排序 — 对 memory 和 knowledge 按相关性排序
        2. 压缩 — 对对话历史和记忆做 Token 压缩
        3. 预算 — 分配各模块的 Token 预算
        4. 截断 — 超出预算的部分进行裁剪
    """

    def __init__(
        self,
        ranker: Optional[RelevanceRanker] = None,
        compressor: Optional[ContextCompressor] = None,
        budget: Optional[TokenBudgetAllocator] = None,
        max_conv_tokens: int = 32000,
    ):
        self.ranker = ranker or RelevanceRanker()
        self.compressor = compressor or ContextCompressor()
        self.budget = budget or TokenBudgetAllocator()
        self.max_conv_tokens = max_conv_tokens
        logger.info("ContextOptimizer initialized: max_conv_tokens=%d", max_conv_tokens)

    async def optimize(
        self,
        context: UnifiedContext,
        task: Optional[TaskSpec] = None,
    ) -> OptimizedContext:
        """优化 UnifiedContext。

        Args:
            context: 构建好的 UnifiedContext。
            task: 可选的任务信息，用于调整优化策略。

        Returns:
            OptimizedContext。
        """
        logger.info("Optimizing context...")

        # Step 1: 排序
        # top_k 与可用条数成正比，确保在大量候选时不被过度截断
        mem_top_k = max(20, min(len(context.memory), 50))
        kw_top_k = max(5, min(len(context.knowledge), 20))
        context.memory = self.ranker.rank_memories(context.memory, top_k=mem_top_k)
        context.knowledge = self.ranker.rank_knowledge(context.knowledge, top_k=kw_top_k)

        # Step 2: 压缩对话历史
        if context.conversation and context.conversation.history:
            compressed = await self.compressor.compress_conversation(
                context.conversation.history,
                max_tokens=self.max_conv_tokens,
            )
            # 将压缩后的文本存回 current_topic 字段（复用现有字段）
            context.conversation.current_topic = compressed if isinstance(compressed, str) else None

        # Step 3: 分配 Token 预算
        token_budget = self.budget.allocate()

        # Step 4: 如果指定了任务约束，调整预算
        if task and task.constraint and task.constraint.max_tokens:
            self.budget.adjust_for_model(task.constraint.max_tokens)
            token_budget = self.budget.allocate()

        optimized = OptimizedContext(
            compressed=True,
            token_usage=token_budget,
            context=context,
        )

        logger.info(
            "Optimization complete: memories=%d, knowledge=%d, budget=%d",
            len(context.memory), len(context.knowledge), token_budget.total,
        )
        return optimized
