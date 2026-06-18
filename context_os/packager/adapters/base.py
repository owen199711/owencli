"""Prompt 适配器基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from context_os.core.models import OptimizedContext, PackagedContext


class BasePromptAdapter(ABC):
    """Prompt 适配器基类。

    将 OptimizedContext 转换为特定 LLM Provider 的 Prompt 格式。
    """

    provider: str

    @abstractmethod
    def pack(self, context: OptimizedContext) -> PackagedContext:
        """将优化后的 Context 打包为特定模型的 Prompt。

        Args:
            context: 优化后的上下文字典。

        Returns:
            PackagedContext — 包含 provider 名、原始 prompt、各段原文。
        """
        ...
