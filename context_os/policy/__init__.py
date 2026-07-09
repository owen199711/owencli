"""ContextPolicy — 声明式策略引擎。"""
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PolicyDirective:
    matched_rule: str = "default"
    max_tokens: int = 128000
    skip_knowledge: bool = False
    skip_memory: bool = False
    relevance_threshold: float = 0.3

class ContextPolicy:
    RULES = {"simple_chat": {"max_tokens": 32000, "skip_knowledge": True}, "coding_task": {"max_tokens": 128000, "relevance_threshold": 0.5}, "debug_session": {"max_tokens": 128000, "relevance_threshold": 0.6}, "planning_session": {"max_tokens": 64000, "skip_memory": True}}

    def evaluate(self, task_spec) -> PolicyDirective:
        intent = task_spec.intent.value if task_spec else "QA"
        cfg = self.RULES.get(self._match_rule(intent), {})
        return PolicyDirective(matched_rule=self._match_rule(intent), max_tokens=cfg.get("max_tokens", 128000), skip_knowledge=cfg.get("skip_knowledge", False), skip_memory=cfg.get("skip_memory", False), relevance_threshold=cfg.get("relevance_threshold", 0.3))

    def _match_rule(self, intent: str) -> str:
        if intent in ("CODING", "REFACTOR"): return "coding_task"
        if intent in ("DEBUGGING",): return "debug_session"
        if intent in ("PLANNING",): return "planning_session"
        return "simple_chat"
