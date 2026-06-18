"""Conversation Collector - 对话历史收集器。

管理当前 Session 的对话历史，采用环形缓冲区（Circular Buffer）结构。
超过最大容量时自动丢弃最早的对话轮次。

负责:
    - 追加新的对话轮次到历史记录
    - 按需返回当前会话的完整或部分历史
    - 支持清空和重置
"""

from __future__ import annotations

from typing import List, Optional

from context_os.core.base import BaseCollector
from context_os.core.logger import get_logger
from context_os.core.models import ConversationContext, ConversationTurn

logger = get_logger(__name__)


class ConversationCollector(BaseCollector):
    """对话历史收集器。

    使用环形缓冲区存储最近 N 轮对话。
    N 在初始化时通过 max_history 配置。

    Args:
        max_history: 保留的最大对话轮次数，默认 50。
    """

    def __init__(self, max_history: int = 50):
        self._history: List[ConversationTurn] = []
        self.max_history = max_history
        logger.info(
            "ConversationCollector initialized (max_history=%d)",
            max_history,
        )

    @property
    def history(self) -> List[ConversationTurn]:
        """获取当前历史记录的只读副本。"""
        return list(self._history)

    @property
    def turn_count(self) -> int:
        """历史记录中的对话轮次数。"""
        return len(self._history)

    def add_turn(self, role: str, content: str, metadata: Optional[dict] = None) -> None:
        """追加一轮对话到历史记录。

        如果超出 max_history，自动丢弃最早的条目。

        Args:
            role: 对话角色（"user" | "assistant" | "tool"）。
            content: 对话内容。
            metadata: 可选的附加元数据。
        """
        turn = ConversationTurn(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._history.append(turn)

        # 环形缓冲区：超出容量时丢弃最早的
        if len(self._history) > self.max_history:
            dropped = self._history.pop(0)
            logger.debug(
                "History buffer full, dropped oldest turn: role=%s, content=%s...",
                dropped.role,
                dropped.content[:50],
            )

        logger.debug(
            "Added conversation turn: role=%s, content_len=%d (total=%d/%d)",
            role,
            len(content),
            len(self._history),
            self.max_history,
        )

    def clear(self) -> None:
        """清空所有对话历史。"""
        dropped_count = len(self._history)
        self._history.clear()
        logger.info("Cleared conversation history (%d turns dropped)", dropped_count)

    def get_recent(self, n: int = 10) -> List[ConversationTurn]:
        """获取最近 N 轮对话。

        Args:
            n: 需要的最近轮次数。

        Returns:
            最近 N 轮对话的列表。
        """
        recent = self._history[-n:]
        logger.debug("Returning %d recent turns (requested %d)", len(recent), n)
        return recent

    async def collect(self) -> ConversationContext:
        """收集当前对话上下文。

        实现 BaseCollector 接口。

        Returns:
            ConversationContext 对象，包含当前对话历史和状态。
        """
        logger.debug(
            "Collecting conversation context (total turns=%d)",
            len(self._history),
        )

        context = ConversationContext(
            history=self._history[-self.max_history:],
            status="running",
        )

        logger.info(
            "Conversation context collected: turns=%d, status=%s",
            len(context.history),
            context.status,
        )
        return context
