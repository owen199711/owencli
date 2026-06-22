"""Claude XML Prompt 适配器。

将 UnifiedContext 转换为 Claude 偏好的 XML 格式 Prompt。
"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import LLMProvider, OptimizedContext, PackagedContext
from context_os.packager.adapters.base import BasePromptAdapter

logger = get_logger(__name__)


class ClaudePromptAdapter(BasePromptAdapter):
    """Claude XML 适配器。"""

    provider = LLMProvider.CLAUDE.value

    @staticmethod
    def _warn(msg: str) -> str:
        return f"<!-- {msg} -->"

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        sections: dict[str, str] = {}
        unified = ctx.context

        # ── System ──
        system = """You are owencli, an intelligent AI assistant with access to various tools and contextual information. Follow the user's instructions carefully. Use the provided context to inform your responses."""
        sections["system"] = system

        # ── Identity ──
        if unified.identity:
            id_xml = f"<identity>\n  <user_id>{unified.identity.user_id}</user_id>\n  <role>{unified.identity.role}</role>\n  <language>{unified.identity.language}</language>\n  <skill_level>{unified.identity.skill_level}</skill_level>\n</identity>"
            sections["identity"] = id_xml

        # ── Memory ──
        if unified.memory:
            mem_parts = ["<memory>"]
            for item in unified.memory:
                mem_parts.append(f"  <{item.type.value} score=\"{item.relevance_score:.2f}\">")
                mem_parts.append(f"    {item.content}")
                mem_parts.append(f"  </{item.type.value}>")
            mem_parts.append("</memory>")
            sections["memory"] = "\n".join(mem_parts)

        # ── Knowledge ──
        if unified.knowledge:
            kn_parts = ["<knowledge>"]
            for k in unified.knowledge:
                kn_parts.append(f"  <source type=\"{k.source}\" score=\"{k.score:.2f}\">")
                kn_parts.append(f"    {k.content}")
                kn_parts.append(f"  </source>")
            kn_parts.append("</knowledge>")
            sections["knowledge"] = "\n".join(kn_parts)

        # ── Tools ──
        if unified.tools:
            tool_parts = ["<tools>"]
            for t in unified.tools:
                tool_parts.append(f"  <tool name=\"{t.name}\" permission=\"{t.permission}\" />")
            tool_parts.append("</tools>")
            sections["tools"] = "\n".join(tool_parts)

        # ── Conversation ──
        if unified.conversation and unified.conversation.history:
            conv_parts = ["<conversation>"]
            for turn in unified.conversation.history[-20:]:  # 最多 20 轮
                conv_parts.append(f"  <{turn.role}>{turn.content}</{turn.role}>")
            conv_parts.append("</conversation>")
            sections["conversation"] = "\n".join(conv_parts)

        # ── Environment ──
        if unified.environment:
            env_parts = ["<environment>"]
            if unified.environment.os:
                env_parts.append(f"  <os>{unified.environment.os}</os>")
            if unified.environment.working_directory:
                env_parts.append(f"  <cwd>{unified.environment.working_directory}</cwd>")
            if unified.environment.git_branch:
                env_parts.append(f"  <git_branch>{unified.environment.git_branch}</git_branch>")
            env_parts.append("</environment>")
            sections["environment"] = "\n".join(env_parts)

        # ── 组装 ──
        section_order = ["system", "identity", "environment", "memory", "knowledge", "tools", "conversation"]
        ordered = []
        for key in section_order:
            if key in sections:
                ordered.append(sections[key])

        raw = "\n\n".join(ordered)
        # 在末尾添加请回答信号
        if "conversation" in sections:
            raw += "\n\nAssistant:"
        logger.debug(
            "Claude prompt built: %d sections, %d chars",
            len(sections), len(raw),
        )

        return PackagedContext(
            provider=LLMProvider.CLAUDE,
            raw_prompt=raw,
            sections=sections,
        )
