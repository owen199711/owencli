"""Context Optimizer 编排入口。

协调 Ranker、Compressor、Budget，生成 OptimizedContext。

Phase 4.3b: 保留旧 Ranking 作为 fallback，新增去重→分组→截断流程。
"""

from __future__ import annotations

import math
import numpy as np
from typing import List, Optional

from context_os.core.logger import get_logger
from context_os.core.models import (
    MemoryItem, OptimizedContext, TaskSpec, TokenBudget, UnifiedContext,
)
from context_os.optimizer.budget import TokenBudgetAllocator
from context_os.optimizer.compressor import ContextCompressor
from context_os.optimizer.ranker import RelevanceRanker

logger = get_logger(__name__)

# ════════════════════════════════════════════════════════════════
# Phase 4.3b 新旧策略开关
# ════════════════════════════════════════════════════════════════
USE_NEW_OPTIMIZER = True

# 去重阈值
_DEDUP_SIMILARITY_THRESHOLD = 0.9


class ContextOptimizer:
    """Context 优化器。

    Phase 4.3b 新流程（USE_NEW_OPTIMIZER=True）:
        1. 排序 — 保持 LTM.retrieve() 的 score，不再二次权重打分
        2. 去重 — 移除语义相似度 > 0.9 的近重复项
        3. 分组 — 按 intent/category 分组，确保各意图有代表性
        4. 压缩 — 对话历史压缩
        5. 预算 — 分配 Token 预算
        6. 截断 — 按预算裁剪 memory 和 knowledge

    Phase 4.3b 旧流程（USE_NEW_OPTIMIZER=False）:
        1. ranker.rank_memories() 二次打分
        2. 压缩对话历史
        3. Token 预算分配
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
        logger.info(
            "ContextOptimizer initialized: max_conv_tokens=%d, new_optimizer=%s",
            max_conv_tokens, USE_NEW_OPTIMIZER,
        )

    async def optimize(
        self,
        context: UnifiedContext,
        task: Optional[TaskSpec] = None,
    ) -> OptimizedContext:
        """优化 UnifiedContext。"""
        logger.info("Optimizing context...")

        if USE_NEW_OPTIMIZER:
            return await self._optimize_new(context, task)
        else:
            return await self._optimize_old(context, task)

    # ════════════════════════════════════════════════════════════
    # 新流程（Phase 4.3b）
    # ════════════════════════════════════════════════════════════

    async def _optimize_new(
        self,
        context: UnifiedContext,
        task: Optional[TaskSpec] = None,
    ) -> OptimizedContext:
        """新优化流程：去重 → 分组 → 压缩 → 预算 → 截断。"""
        top_k = max(20, min(len(context.memory), 50))

        # Step 1: 保持 LTM 已排好的序（按 relevance_score 降序）
        sorted_mem = sorted(
            context.memory, key=lambda x: x.relevance_score, reverse=True,
        )

        # Step 2: 去重 — 移除语义近重复项
        deduped = self._deduplicate_memories(sorted_mem)
        logger.debug(
            "Dedup: %d → %d memories", len(sorted_mem), len(deduped),
        )

        # Step 3: 分组 — 按 source_weight 和 intent 分组截断
        grouped = self._group_and_truncate(deduped, top_k)
        context.memory = grouped

        # Knowledge 排序（保持现有 score）
        kw_top_k = max(5, min(len(context.knowledge), 20))
        sorted_kw = sorted(
            context.knowledge, key=lambda x: x.score, reverse=True,
        )
        context.knowledge = sorted_kw[:kw_top_k]

        # Step 4: 压缩对话历史
        await self._compress_conversation(context)

        # Step 5: 分配 Token 预算
        token_budget = self.budget.allocate()

        # Step 6: 如果指定了任务约束，调整预算
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

    def _deduplicate_memories(self, items: List[MemoryItem]) -> List[MemoryItem]:
        """去重：移除语义相似度 > _DEDUP_SIMILARITY_THRESHOLD 的近重复项。

        规则:
            - 精确内容重复 → 直接丢弃
            - 语义相似 > 0.9 → 保留 score 更高的
        """
        if not items:
            return []

        seen_content = set()
        result = []
        for item in items:
            # 精确去重
            content_hash = item.content.strip().lower()
            if content_hash in seen_content:
                continue

            # 语义去重（与已保留的条目比较）
            is_dup = False
            if item.embedding:
                for kept in result:
                    if kept.embedding:
                        sim = self._cosine_similarity(item.embedding, kept.embedding)
                        if sim > _DEDUP_SIMILARITY_THRESHOLD:
                            is_dup = True
                            break

            if not is_dup:
                seen_content.add(content_hash)
                result.append(item)

        return result

    def _group_and_truncate(
        self,
        items: List[MemoryItem],
        top_k: int,
    ) -> List[MemoryItem]:
        """分组截断：按 source_weight / intent 分组，确保各意图有代表项。

        策略:
            - 前 60% 按 score 全局取
            - 后 40% 按 intent 分组取，每组至少 1 条
        """
        if len(items) <= top_k:
            return items

        # 全局高分取前 60%
        global_count = max(int(top_k * 0.6), 1)
        result = list(items[:global_count])

        # 余量按 intent 分组
        remaining = items[global_count:]
        group_budget = top_k - global_count
        if group_budget <= 0:
            return result

        # 分组
        groups: dict[str, list[MemoryItem]] = {}
        for item in remaining:
            intent = item.metadata.get("intent", "unknown")
            groups.setdefault(intent, []).append(item)

        # 每组取 1 条（有剩余预算则多取）
        added = 0
        for _intent, group_items in sorted(
            groups.items(), key=lambda x: len(x[1]), reverse=True,
        ):
            if added >= group_budget:
                break
            take = min(2, len(group_items), group_budget - added)
            result.extend(group_items[:take])
            added += take

        return result

    async def _compress_conversation(self, context: UnifiedContext) -> None:
        """压缩对话历史。"""
        if context.conversation and context.conversation.history:
            compressed = await self.compressor.compress_conversation(
                context.conversation.history,
                max_tokens=self.max_conv_tokens,
            )
            if compressed and isinstance(compressed, str) and len(compressed) > 0:
                from context_os.core.models import ConversationTurn
                context.conversation.history = [
                    ConversationTurn(role="system", content=compressed),
                ]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度。"""
        try:
            a_arr = np.array(a, dtype=np.float64)
            b_arr = np.array(b, dtype=np.float64)
            norm_a = np.linalg.norm(a_arr)
            norm_b = np.linalg.norm(b_arr)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
        except Exception:
            return 0.0

    # ════════════════════════════════════════════════════════════
    # 旧流程（保留，阶段五删除）
    # ════════════════════════════════════════════════════════════

    async def _optimize_old(
        self,
        context: UnifiedContext,
        task: Optional[TaskSpec] = None,
    ) -> OptimizedContext:
        """旧优化流程。"""
        mem_top_k = max(20, min(len(context.memory), 50))
        kw_top_k = max(5, min(len(context.knowledge), 20))
        context.memory = self.ranker.rank_memories(context.memory, top_k=mem_top_k)
        context.knowledge = self.ranker.rank_knowledge(context.knowledge, top_k=kw_top_k)

        await self._compress_conversation(context)

        token_budget = self.budget.allocate()
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
