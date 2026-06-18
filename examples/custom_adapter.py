"""自定义 Prompt 适配器示例。"""

from context_os.packager.adapters.base import BasePromptAdapter
from context_os.core.models import OptimizedContext, PackagedContext


class MarkdownPromptAdapter(BasePromptAdapter):
    """Markdown 格式适配器示例。"""

    provider = "markdown"

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        """将 Context 打包为 Markdown 格式。"""
        unified = ctx.context
        sections = {}

        # System
        system = "# System\n\nYou are owencli, a helpful AI assistant."
        sections["system"] = system

        # Memory
        if unified.memory:
            mem_lines = ["## Memory\n"]
            for item in unified.memory:
                mem_lines.append(f"- *[{item.type.value}]* {item.content[:200]}")
            sections["memory"] = "\n".join(mem_lines)

        # Conversation
        if unified.conversation and unified.conversation.history:
            conv_lines = ["## Conversation\n"]
            for turn in unified.conversation.history[-10:]:
                conv_lines.append(f"**{turn.role}**: {turn.content}")
            sections["conversation"] = "\n".join(conv_lines)

        # 组装
        raw = "\n\n---\n\n".join(sections.values())
        return PackagedContext(
            provider=self.provider,
            raw_prompt=raw,
            sections=sections,
        )


# 使用示例
def example():
    """演示如何使用自定义适配器。"""
    from context_os.packager.adapters.registry import AdapterRegistry

    # 注册自定义适配器
    registry = AdapterRegistry()
    registry.register(MarkdownPromptAdapter())

    # 使用
    adapter = registry.get("markdown")
    print(f"Custom adapter: {adapter.provider}")


if __name__ == "__main__":
    example()
