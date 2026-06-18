"""长期记忆（Long-Term Memory）。

跨 Session、跨项目的持久记忆。基于 PostgreSQL 存储，支持:
    - 向量相似度检索（需 pgvector 插件）
    - 时间衰减排序
    - 访问频率加权
    - Ebbinghaus 遗忘曲线自动清理

存储内容:
    - 用户长期偏好（语言、风格、规范）
    - 项目上下文和代码库知识
    - 跨 Session 的用户行为模式
    - 重要的决策记录和理由
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.core.memory.store import PostgresStore
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)


class LongTermMemory:
    """长期记忆 — 跨 Session 持久知识库。

    Args:
        store: PostgreSQL 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: PostgresStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("LongTermMemory initialized (user=%s)", user_id)

    async def store(
        self,
        content: str,
        memory_type: str = "long_term",
        metadata: Optional[dict] = None,
        embedding: Optional[list[float]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """存储一条长期记忆。

        Args:
            content: 记忆内容。
            memory_type: 子类型（long_term|semantic|user_profile|project_context）。
            metadata: 元数据，如 {"category": "user_preference", "key": "language"}。
            embedding: 向量嵌入，用于语义检索。
            user_id: 用户 ID，默认使用构造函数中设置的。

        Returns:
            记忆 ID。
        """
        mem_id = uuid.uuid4().hex
        await self.store.save_memory(
            id=mem_id,
            type=memory_type,
            content=content,
            user_id=user_id or self.user_id,
            embedding=embedding,
            metadata=metadata,
        )
        logger.info(
            "LTM stored: id=%s, type=%s, content_len=%d",
            mem_id, memory_type, len(content),
        )
        return mem_id

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
        embedding: Optional[list[float]] = None,
    ) -> list[MemoryItem]:
        """检索长期记忆。

        检索策略（按优先级）:
            1. 向量相似度（如果有 embedding）
            2. 关键词全文检索
            3. 时间衰减排序

        Args:
            query: 检索查询文本。
            top_k: 返回数量上限。
            memory_type: 筛选特定子类型。
            embedding: 直接传入向量进行相似度检索。

        Returns:
            MemoryItem 列表，按综合得分降序排列。
        """
        results = await self.store.query_memories(
            type=memory_type or "long_term",
            user_id=self.user_id,
            query_text=query,
            embedding=embedding,
            top_k=top_k,
        )

        items = [MemoryItem(**r) for r in results]
        logger.info(
            "LTM retrieved: query='%s...', top_k=%d, results=%d",
            query[:50], top_k, len(items),
        )
        return items

    async def retrieve_by_category(self, category: str, top_k: int = 10) -> list[MemoryItem]:
        """按类别检索长期记忆。

        Args:
            category: 类别名（如 "user_preference", "project_context", "decision"）。
            top_k: 返回上限。

        Returns:
            MemoryItem 列表。
        """
        # 使用关键词匹配 metadata.category
        results = await self.store.query_memories(
            type="long_term",
            user_id=self.user_id,
            query_text=category,
            top_k=top_k,
        )
        items = [
            MemoryItem(**r) for r in results
            if r.get("metadata", {}).get("category") == category
        ]
        logger.debug("LTM by category '%s': %d results", category, len(items))
        return items

    async def update_relevance(self, memory_id: str, delta: float = 0.1) -> None:
        """更新某条记忆的相关性得分。

        通常在 LLM 实际使用了该记忆时调用，增加其得分。

        Args:
            memory_id: 记忆 ID。
            delta: 得分增量。
        """
        mem = await self.store.get_memory(memory_id)
        if mem:
            new_score = (mem.get("relevance_score") or 0.0) + delta
            async with self.store._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE memories SET relevance_score = $1 WHERE id = $2",
                    min(new_score, 1.0), memory_id,
                )
            logger.debug("LTM relevance updated: id=%s, new_score=%.2f", memory_id, new_score)

    async def consolidate(self) -> int:
        """记忆整合：合并重复内容，提炼高层概要。

        执行流程:
            1. 查找内容相似度高的条目对
            2. 合并重复条目（保留置信度高的版本）
            3. 标记过时条目

        Returns:
            整合后移除的条目数。
        """
        results = await self.store.query_memories(
            type="long_term",
            user_id=self.user_id,
            top_k=1000,
        )

        # 简单去重：内容相同的保留一条
        seen_contents: dict[str, str] = {}
        to_delete: list[str] = []

        for r in results:
            content = r.get("content", "").strip()
            if content in seen_contents:
                to_delete.append(r["id"])
            else:
                seen_contents[content] = r["id"]

        for mem_id in to_delete:
            await self.store.delete_memory(mem_id)

        if to_delete:
            logger.info("LTM consolidated: removed %d duplicates", len(to_delete))
        else:
            logger.debug("LTM consolidate: no duplicates found")

        return len(to_delete)

    async def forget(self, threshold_days: int = 90, min_access_count: int = 2) -> int:
        """基于遗忘曲线自动清理低价值记忆。

        清理条件:
            - 超过 threshold_days 未访问
            - 访问次数低于 min_access_count
            - 相关性得分低于 0.3

        Args:
            threshold_days: 阈值天数。
            min_access_count: 最低访问次数。

        Returns:
            清理的记忆数。
        """
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)

        if not self.store._pool:
            return 0

        async with self.store._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM memories
                WHERE type = 'long_term'
                  AND timestamp < $1
                  AND access_count < $2
                  AND relevance_score < 0.3
                """,
                cutoff, min_access_count,
            )
            count = int(result.split()[-1]) if result else 0

        if count > 0:
            logger.info("LTM forget: removed %d low-value memories", count)
        return count
