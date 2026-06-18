"""Context 合并器。

负责合并、归一化、去重多个 Context 源的数据。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from context_os.core.logger import get_logger
from context_os.core.models import (
    KnowledgeChunk, MemoryItem, UnifiedContext,
)

logger = get_logger(__name__)


class ContextMerger:
    """Context 合并器。

    对多个来源的 Context 做三件事：
        1. merge — 合并多个 UnifiedContext
        2. normalize — 统一数据格式
        3. deduplicate — 去重
    """

    def merge(self, contexts: List[UnifiedContext]) -> UnifiedContext:
        """合并多个 UnifiedContext。

        对 memory 和 knowledge 列表取并集。
        对 identity/conversation/environment 取第一个非空的。

        Args:
            contexts: 多个 UnifiedContext 列表。

        Returns:
            合并后的 UnifiedContext。
        """
        if not contexts:
            return UnifiedContext()

        if len(contexts) == 1:
            return contexts[0]

        result = UnifiedContext()

        # identity / conversation / environment: 取第一个非空
        for ctx in contexts:
            if ctx.identity and not result.identity:
                result.identity = ctx.identity
            if ctx.conversation and not result.conversation:
                result.conversation = ctx.conversation
            if ctx.environment and not result.environment:
                result.environment = ctx.environment

        # memory / knowledge / tools: 取并集
        seen_memory_ids: set[str] = set()
        seen_knowledge: set[str] = set()
        seen_tools: set[str] = set()

        for ctx in contexts:
            for m in ctx.memory:
                if m.id not in seen_memory_ids:
                    result.memory.append(m)
                    seen_memory_ids.add(m.id)
            for k in ctx.knowledge:
                key = f"{k.source}:{k.content[:50]}"
                if key not in seen_knowledge:
                    result.knowledge.append(k)
                    seen_knowledge.add(key)
            for t in ctx.tools:
                if t.name not in seen_tools:
                    result.tools.append(t)
                    seen_tools.add(t.name)

        logger.debug(
            "Merged %d contexts: memories=%d, knowledge=%d, tools=%d",
            len(contexts), len(result.memory), len(result.knowledge), len(result.tools),
        )
        return result

    def normalize(self, context: UnifiedContext) -> UnifiedContext:
        """统一数据格式。

        - MemoryItem 按 relevance_score 降序排列
        - KnowledgeChunk 按 score 降序排列
        - ToolContext 按 name 字母序排列

        Args:
            context: 待归一化的 UnifiedContext。

        Returns:
            归一化后的 UnifiedContext。
        """
        context.memory.sort(key=lambda x: x.relevance_score, reverse=True)
        context.knowledge.sort(key=lambda x: x.score, reverse=True)
        context.tools.sort(key=lambda x: x.name)

        logger.debug("Normalized context: memories=%d, knowledge=%d", len(context.memory), len(context.knowledge))
        return context

    def deduplicate(self, context: UnifiedContext) -> UnifiedContext:
        """去重。

        对 memory 按 content 去重（保留置信度高的）。
        对 knowledge 按 content 去重（保留 score 高的）。

        Args:
            context: 待去重的 UnifiedContext。

        Returns:
            去重后的 UnifiedContext。
        """
        # Memory 去重
        seen_content: Dict[str, MemoryItem] = {}
        for item in context.memory:
            key = item.content.strip()
            if key in seen_content:
                if item.relevance_score > seen_content[key].relevance_score:
                    seen_content[key] = item
            else:
                seen_content[key] = item
        context.memory = list(seen_content.values())

        # Knowledge 去重
        seen_k: Dict[str, KnowledgeChunk] = {}
        for k in context.knowledge:
            key = k.content.strip()
            if key in seen_k:
                if k.score > seen_k[key].score:
                    seen_k[key] = k
            else:
                seen_k[key] = k
        context.knowledge = list(seen_k.values())

        removed = sum(1 for m in context.memory if m.id not in seen_content)
        logger.debug(
            "Deduplication: memories=%d, knowledge=%d (removed %d duplicates)",
            len(context.memory), len(context.knowledge), removed,
        )
        return context
