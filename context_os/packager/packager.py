"""Context Packager — 打包编排入口。"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import LLMProvider, OptimizedContext, PackagedContext
from context_os.packager.adapters.registry import AdapterRegistry, default_registry

logger = get_logger(__name__)


class ContextPackager:
    """Context 打包器。

    将 OptimizedContext 通过适配器转换为 LLM 可读的 Prompt。
    """

    def __init__(self, registry: AdapterRegistry | None = None):
        self.registry = registry or default_registry
        logger.info("ContextPackager initialized")

    def pack(
        self,
        context: OptimizedContext,
        provider: LLMProvider = LLMProvider.CLAUDE,
    ) -> PackagedContext:
        """打包 Context。

        Args:
            context: 优化后的上下文。
            provider: 目标 LLM 提供商。

        Returns:
            PackagedContext。
        """
        adapter = self.registry.get(provider)
        packaged = adapter.pack(context)
        logger.info(
            "Context packed: provider=%s, prompt_len=%d chars, sections=%d",
            provider.value, len(packaged.raw_prompt), len(packaged.sections),
        )
        return packaged
