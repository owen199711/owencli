"""OpenAI JSON Prompt 适配器。"""

from __future__ import annotations

import json

from context_os.core.logger import get_logger
from context_os.core.models import LLMProvider, OptimizedContext, PackagedContext
from context_os.packager.adapters.base import BasePromptAdapter

logger = get_logger(__name__)


class OpenAIPromptAdapter(BasePromptAdapter):
    """OpenAI 适配器 — messages 数组格式。"""

    provider = LLMProvider.OPENAI.value

    def pack(self, ctx: OptimizedContext) -> PackagedContext:
        sections: dict[str, str] = {}
        unified = ctx.context

        # System message
        system = "You are owencli, an intelligent AI assistant."
        sections["system"] = system

        # Context sections
        context_parts = []

        if unified.identity:
            context_parts.append(
                f"[Identity] User: {unified.identity.user_id}, "
                f"Role: {unified.identity.role}, Language: {unified.identity.language}"
            )

        if unified.memory:
            context_parts.append("[Memory]")
            for item in unified.memory[:10]:
                context_parts.append(f"  - [{item.type.value}] {item.content[:200]}")

        if unified.knowledge:
            context_parts.append("[Knowledge]")
            for k in unified.knowledge[:5]:
                context_parts.append(f"  - [{k.source}] {k.content[:200]}")

        if unified.environment:
            context_parts.append(
                f"[Environment] OS: {unified.environment.os}, "
                f"CWD: {unified.environment.working_directory}"
            )

        sections["context"] = "\n".join(context_parts)

        # Conversation
        conv_text = ""
        if unified.conversation and unified.conversation.history:
            conv_lines = []
            for turn in unified.conversation.history[-20:]:
                conv_lines.append(f"{turn.role}: {turn.content}")
            conv_text = "\n".join(conv_lines)
            sections["conversation"] = conv_text

        # Build messages
        messages = [
            {"role": "system", "content": system},
        ]
        if context_parts:
            messages.append({"role": "system", "content": "\n".join(context_parts)})
        if conv_text:
            messages.append({"role": "user", "content": conv_text})

        raw_prompt = json.dumps(messages, ensure_ascii=False)
        logger.debug("OpenAI prompt built: %d messages, %d chars", len(messages), len(raw_prompt))

        return PackagedContext(
            provider=LLMProvider.OPENAI,
            raw_prompt=raw_prompt,
            sections=sections,
        )
