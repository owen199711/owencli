"""PromptLayout — 7 段式结构化 Prompt 模板。"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class PromptSections:
    system_prompt: str = ""; memory: str = ""; knowledge: str = ""
    tool: str = ""; task: str = ""; output_schema: str = ""; guardrail: str = ""

class PromptLayout:
    SECTIONS = ["system_prompt","memory","knowledge","tool","task","output_schema","guardrail"]

    def layout(self, sp="", mem="", kn="", tl="", tk="", os="", gr="") -> PromptSections:
        return PromptSections(sp, mem, kn, tl, tk, os, gr)

    def render(self, s: PromptSections) -> str:
        parts = []
        for sn in self.SECTIONS:
            c = getattr(s, sn, "")
            if c: parts.append(f"<{sn}>" + c + f"</{sn}>")
        return "\n".join(parts)

    @staticmethod
    def estimate_tokens(s: PromptSections) -> int:
        return len(" ".join(getattr(s, sn, "") for sn in PromptLayout.SECTIONS)) // 4

