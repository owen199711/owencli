"""工作记忆（Working Memory）。

当前会话中最活跃、最即时的信息存储区。
采用纯内存环形缓冲区实现，容量有限（受 Token 预算约束）。

职责:
    - 保持当前对话轮次的消息历史
    - 缓存当前任务的中间状态
    - 支持注意力机制，优先保留关键信息
"""

from __future__ import annotations

from typing import Any, List, Optional

from context_os.core.logger import get_logger
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)


class WorkingMemory:
    """工作记忆 — 当前会话活跃上下文。

    纯内存实现，不持久化。
    超过 Token 预算时自动淘汰最早条目。

    Args:
        max_tokens: Token 预算上限，默认 8000。
    """

    def __init__(self, max_tokens: int = 8000):
        self._items: List[MemoryItem] = []
        self.max_tokens = max_tokens
        self._current_tokens: int = 0
        logger.info(
            "WorkingMemory initialized (max_tokens=%d)",
            max_tokens,
        )

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def items(self) -> List[MemoryItem]:
        """当前工作记忆中的所有条目（只读副本）。"""
        return list(self._items)

    @property
    def item_count(self) -> int:
        """条目数量。"""
        return len(self._items)

    @property
    def token_usage(self) -> int:
        """当前已用的 Token 数。"""
        return self._current_tokens

    @property
    def token_utilization(self) -> float:
        """Token 利用率（0.0 - 1.0）。"""
        return self._current_tokens / self.max_tokens if self.max_tokens > 0 else 0.0

    # ── 核心操作 ────────────────────────────────────────────────

    def push(self, content: str, metadata: Optional[dict] = None) -> MemoryItem:
        """向工作记忆中添加一条记录。

        如果超出 Token 预算，自动淘汰最旧的条目。

        Args:
            content: 记忆内容。
            metadata: 附加元数据。

        Returns:
            创建的 MemoryItem。
        """
        item = MemoryItem(
            type=MemoryType.WORKING,
            content=content,
            metadata=metadata or {},
        )

        item_tokens = self._estimate_tokens(content)
        self._current_tokens += item_tokens
        self._items.append(item)

        logger.debug(
            "Working memory push: tokens=%d, total_tokens=%d/%d",
            item_tokens, self._current_tokens, self.max_tokens,
        )

        # 超过预算 → 淘汰
        self._evict_if_needed()

        return item

    def push_multi(self, entries: list[tuple[str, Optional[dict]]]) -> List[MemoryItem]:
        """批量添加多条记录。

        Args:
            entries: (content, metadata) 元组列表。

        Returns:
            创建的 MemoryItem 列表。
        """
        items = []
        for content, metadata in entries:
            item = self.push(content, metadata)
            items.append(item)
        logger.debug("Batch pushed %d items", len(items))
        return items

    def get_recent(self, n: int = 10) -> List[MemoryItem]:
        """获取最近 N 条记录。

        Args:
            n: 需要返回的条目数。

        Returns:
            最近的 N 条 MemoryItem。
        """
        recent = self._items[-n:]
        logger.debug("Returning %d recent items (requested %d)", len(recent), n)
        return recent

    def pop(self) -> Optional[MemoryItem]:
        """弹出（移除并返回）最近一条记录。

        Returns:
            最近一条 MemoryItem，如果没有则返回 None。
        """
        if not self._items:
            return None
        item = self._items.pop()
        self._current_tokens -= self._estimate_tokens(item.content)
        logger.debug("Popped working memory item: %s...", item.content[:50])
        return item

    def peek(self) -> Optional[MemoryItem]:
        """查看最近一条记录但不移除。

        Returns:
            最近一条 MemoryItem。"""
        return self._items[-1] if self._items else None

    def clear(self) -> None:
        """清空工作记忆。"""
        count = len(self._items)
        self._items.clear()
        self._current_tokens = 0
        logger.info("Working memory cleared (%d items removed)", count)

    def find(self, keyword: str) -> List[MemoryItem]:
        """按关键词搜索工作记忆。

        Args:
            keyword: 搜索关键词（大小写不敏感）。

        Returns:
            匹配的 MemoryItem 列表。
        """
        keyword_lower = keyword.lower()
        results = [
            item for item in self._items
            if keyword_lower in item.content.lower()
        ]
        logger.debug("Working memory search '%s': %d results", keyword, len(results))
        return results

    # ── 注意力机制 ───────────────────────────────────────────────

    def get_attention_context(self, max_tokens: int = 2000) -> str:
        """获取当前工作记忆中最重要的部分（注意力上下文）。

        保留最近的条目和带 priority 标签的条目。
        截断超过 max_tokens 的部分。

        Args:
            max_tokens: 注意力上下文的 Token 预算。

        Returns:
            拼接后的注意力上下文字符串。
        """
        # 排序：带 priority 的优先，然后按时间倒序
        scored_items = []
        for item in self._items:
            priority = item.metadata.get("priority", 0) if item.metadata else 0
            scored_items.append((priority, item))

        scored_items.sort(key=lambda x: x[0], reverse=True)

        result_tokens = 0
        result_parts = []
        for priority, item in scored_items:
            tokens = self._estimate_tokens(item.content)
            if result_tokens + tokens > max_tokens:
                continue
            result_tokens += tokens
            result_parts.append(item.content)

        context = "\n".join(result_parts)
        logger.debug(
            "Attention context built: items=%d/%d, tokens=%d",
            len(result_parts), len(self._items), result_tokens,
        )
        return context

    # ── 私有方法 ─────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """超过 Token 预算时淘汰最旧的条目。"""
        while self._current_tokens > self.max_tokens and self._items:
            evicted = self._items.pop(0)
            evicted_tokens = self._estimate_tokens(evicted.content)
            self._current_tokens -= evicted_tokens
            logger.debug(
                "Evicted oldest item: tokens=%d, remaining=%d/%d",
                evicted_tokens, self._current_tokens, self.max_tokens,
            )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算文本的 Token 数。

        中文约 1.5 tokens/字，英文约 0.25 tokens/字符。

        Args:
            text: 输入文本。

        Returns:
            估算的 Token 数。
        """
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25) + 1
