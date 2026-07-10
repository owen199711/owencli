"""测试 Phase 4.3b Optimizer — 去重/分组/截断。"""

import pytest
from datetime import datetime
from context_os.core.models import MemoryItem, MemoryType, UnifiedContext
from context_os.optimizer.optimizer import ContextOptimizer, USE_NEW_OPTIMIZER


class TestMemoryDeduplication:
    """去重测试。"""

    def test_exact_duplicate_content_removed(self):
        opt = ContextOptimizer()
        items = [
            MemoryItem(
                type=MemoryType.LONG_TERM, content="重复内容A",
                relevance_score=0.8,
            ),
            MemoryItem(
                type=MemoryType.LONG_TERM, content="重复内容A",
                relevance_score=0.6,
            ),
            MemoryItem(
                type=MemoryType.LONG_TERM, content="不同内容B",
                relevance_score=0.5,
            ),
        ]
        result = opt._deduplicate_memories(items)
        assert len(result) == 2
        contents = [r.content for r in result]
        assert "不同内容B" in contents

    def test_unique_items_preserved(self):
        opt = ContextOptimizer()
        items = [
            MemoryItem(type=MemoryType.LONG_TERM, content="A", relevance_score=0.9),
            MemoryItem(type=MemoryType.LONG_TERM, content="B", relevance_score=0.7),
            MemoryItem(type=MemoryType.LONG_TERM, content="C", relevance_score=0.5),
        ]
        result = opt._deduplicate_memories(items)
        assert len(result) == 3

    def test_empty_list(self):
        opt = ContextOptimizer()
        result = opt._deduplicate_memories([])
        assert result == []

    def test_semantic_dedup_with_embedding(self):
        """语义去重：相似度 > 0.9 时保留高分项。"""
        opt = ContextOptimizer()
        items = [
            MemoryItem(
                type=MemoryType.LONG_TERM, content="content A",
                embedding=[1.0, 0.0, 0.0],
                relevance_score=0.9,
            ),
            MemoryItem(
                type=MemoryType.LONG_TERM, content="content A2",
                embedding=[0.95, 0.0, 0.0],  # 高相似
                relevance_score=0.5,
            ),
        ]
        result = opt._deduplicate_memories(items)
        assert len(result) == 1  # 第二个被作为重复移除


class TestGroupAndTruncate:
    """分组截断测试。"""

    def test_small_group_no_truncation(self):
        opt = ContextOptimizer()
        items = [
            MemoryItem(
                type=MemoryType.LONG_TERM, content=f"item{i}",
                relevance_score=1.0 - i * 0.1,
                metadata={"intent": f"intent_{i % 3}"},
            )
            for i in range(5)
        ]
        result = opt._group_and_truncate(items, top_k=10)
        assert len(result) == 5

    def test_truncation_uses_intent_groups(self):
        opt = ContextOptimizer()
        items = [
            MemoryItem(
                type=MemoryType.LONG_TERM, content=f"item{i}",
                relevance_score=1.0 - i * 0.05,
                metadata={"intent": f"intent_{i % 5}"},
            )
            for i in range(30)
        ]
        result = opt._group_and_truncate(items, top_k=20)
        assert 10 < len(result) <= 20

    def test_group_preserves_diversity(self):
        """分组确保不同 intent 都有代表。"""
        opt = ContextOptimizer()
        items = []
        for intent in ["qa", "coding", "debugging", "planning"]:
            for i in range(5):
                items.append(MemoryItem(
                    type=MemoryType.LONG_TERM,
                    content=f"{intent}_{i}",
                    relevance_score=0.9 - (i * 0.1),
                    metadata={"intent": intent},
                ))

        result = opt._group_and_truncate(items, top_k=12)
        result_intents = {r.metadata.get("intent") for r in result}
        assert len(result_intents) >= 3  # 至少 3 个不同 intent


class TestOptimizerNewFlow:
    """新优化流程集成测试。"""

    async def test_optimize_with_memories_new(self):
        opt = ContextOptimizer()
        ctx = UnifiedContext()
        for i in range(30):
            ctx.memory.append(MemoryItem(
                type=MemoryType.LONG_TERM,
                content=f"test content {i}",
                relevance_score=0.9 - i * 0.03,
            ))

        result = await opt._optimize_new(ctx)
        assert len(result.context.memory) <= 50
        assert result.compressed is True

    async def test_optimize_with_empty_context(self):
        opt = ContextOptimizer()
        ctx = UnifiedContext()
        result = await opt._optimize_new(ctx)
        assert len(result.context.memory) == 0

    async def test_old_flow_still_works(self):
        """旧流程仍可用。"""
        old_mode = USE_NEW_OPTIMIZER

        # 临时切换到旧模式进行验证
        import context_os.optimizer.optimizer as opt_mod
        opt_mod.USE_NEW_OPTIMIZER = False

        try:
            opt = ContextOptimizer()
            ctx = UnifiedContext()
            for i in range(5):
                ctx.memory.append(MemoryItem(
                    type=MemoryType.LONG_TERM,
                    content=f"old_test_{i}",
                    relevance_score=0.5,
                ))

            result = await opt.optimize(ctx)
            assert isinstance(result.context, UnifiedContext)
        finally:
            opt_mod.USE_NEW_OPTIMIZER = old_mode
