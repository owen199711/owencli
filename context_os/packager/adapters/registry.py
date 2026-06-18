"""适配器注册中心。"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import LLMProvider
from context_os.packager.adapters.base import BasePromptAdapter
from context_os.packager.adapters.claude import ClaudePromptAdapter
from context_os.packager.adapters.openai import OpenAIPromptAdapter

logger = get_logger(__name__)


class AdapterRegistry:
    """适配器注册中心。

    管理所有 LLM Provider 的 PromptAdapter 映射。
    """

    def __init__(self):
        self._adapters: dict[str, BasePromptAdapter] = {}

    def register(self, adapter: BasePromptAdapter) -> None:
        """注册一个适配器。

        Args:
            adapter: PromptAdapter 实例。
        """
        self._adapters[adapter.provider] = adapter
        logger.debug("Adapter registered: %s", adapter.provider)

    def get(self, provider: LLMProvider) -> BasePromptAdapter:
        """获取指定 Provider 的适配器。

        Args:
            provider: LLMProvider 枚举。

        Returns:
            PromptAdapter 实例。

        Raises:
            ValueError: 未注册该 Provider 的适配器。
        """
        key = provider.value if isinstance(provider, LLMProvider) else provider
        adapter = self._adapters.get(key)
        if not adapter:
            raise ValueError(f"No adapter registered for provider: {key}. "
                           f"Available: {list(self._adapters.keys())}")
        return adapter

    def register_defaults(self) -> None:
        """注册默认适配器（Claude + OpenAI）。"""
        self.register(ClaudePromptAdapter())
        self.register(OpenAIPromptAdapter())
        logger.info("Default adapters registered: %s", list(self._adapters.keys()))

    @property
    def available_providers(self) -> list[str]:
        """获取已注册的 Provider 列表。"""
        return list(self._adapters.keys())


# 全局默认注册中心
default_registry = AdapterRegistry()
default_registry.register_defaults()
