"""OpenAI 兼容 Prompt 适配器（纯文本格式）。"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import LLMProvider, OptimizedContext, PackagedContext
from context_os.packager.adapters.base import BasePromptAdapter

logger = get_logger(__name__)


class OpenAIPromptAdapter(BasePromptAdapter):
    """OpenAI/DeepSeek 适配器 — 纯文本拼接格式。

    生成可直接作为 user message 发送给 LLM 的纯文本 prompt，
    与 BaseLLMClient.complete(prompt) 的调用方式匹配。
    """

    provider = LLMProvider.OPENAI.value

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        sections: dict[str, str] = {}
        unified = ctx.context

        # ── System ──
        system = (
            "You are owencli, an intelligent AI assistant with access to "
            "various tools and contextual information. Follow the user's "
            "instructions carefully. Use the provided context to inform "
            "your responses."
        )
        sections["system"] = system

        # ── Identity ──
        if unified.identity:
            sections["identity"] = (
                f"[Identity] User: {unified.identity.user_id}, "
                f"Role: {unified.identity.role}, "
                f"Language: {unified.identity.language}"
            )

        # ── Memory ──
        if unified.memory:
            mem_lines = ["[Memory]"]
            for item in unified.memory[:30]:
                mem_lines.append(f"  - [{item.type.value}] {item.content[:200]}")
            sections["memory"] = "\n".join(mem_lines)

        # ── Knowledge ──
        if unified.knowledge:
            kn_lines = ["[Knowledge]"]
            for k in unified.knowledge[:5]:
                kn_lines.append(f"  - [{k.source}] {k.content[:200]}")
            sections["knowledge"] = "\n".join(kn_lines)

        # ── Environment ──
        if unified.environment:
            sections["environment"] = (
                f"[Environment] OS: {unified.environment.os}, "
                f"CWD: {unified.environment.working_directory}"
            )

        # ── Conversation ──
        if unified.conversation and unified.conversation.history:
            conv_lines = ["[Conversation]"]
            # Keep more history for multi-turn tracking scenarios (up to 50 turns)
            for turn in unified.conversation.history[-50:]:
                conv_lines.append(f"  {turn.role}: {turn.content}")
            sections["conversation"] = "\n".join(conv_lines)

        # ── 组装纯文本 prompt ──
        section_order = [
            "system", "identity", "environment",
            "memory", "knowledge", "conversation",
        ]
        ordered = [sections[key] for key in section_order if key in sections]
        raw_prompt = "\n\n".join(ordered)

        # 在末尾添加"请回答"信号，明确指示 LLM 对最后一条 user 消息做出回应
        if "conversation" in sections:
            raw_prompt += "\n\nAssistant:"

        logger.debug(
            "OpenAI prompt built: %d sections, %d chars",
            len(sections), len(raw_prompt),
        )

        return PackagedContext(
            provider=LLMProvider.OPENAI,
            raw_prompt=raw_prompt,
            sections=sections,
        )
