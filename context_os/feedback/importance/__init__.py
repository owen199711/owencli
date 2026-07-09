"""MemoryImportanceEngine — 5 维评分 + StorageTier。"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re


class StorageTier(Enum):
    FACT_SEMANTIC = "fact_semantic"
    EPISODE_LTM = "episode_ltm"
    CONV_MED = "conv_med"
    SHORT_TERM = "short_term"
    DISCARD = "discard"


_TIERS = [
    (0.90, StorageTier.FACT_SEMANTIC),
    (0.75, StorageTier.EPISODE_LTM),
    (0.50, StorageTier.CONV_MED),
    (0.20, StorageTier.SHORT_TERM),
]


@dataclass
class MemoryImportanceResult:
    overall_score: float
    rule_score: float
    semantic_score: float
    novelty_score: float
    fact_weight_score: float
    goal_relation_score: float
    storage_tier: StorageTier


class MemoryImportanceEngine:
    W = {
        "rule": 0.20,
        "semantic": 0.35,
        "novelty": 0.20,
        "fact_weight": 0.15,
        "goal_relation": 0.10,
    }

    def score(
        self,
        content: str,
        task_spec=None,
        existing_facts=None,
    ) -> MemoryImportanceResult:
        rs = self._rule_score(content)
        ss = self._semantic_score(content)
        ns = self._novelty_score(content, existing_facts)
        fw = self._fact_weight(content)
        gr = self._goal_relation(content, task_spec)
        ov = (
            rs * self.W["rule"]
            + ss * self.W["semantic"]
            + ns * self.W["novelty"]
            + fw * self.W["fact_weight"]
            + gr * self.W["goal_relation"]
        )
        tier = StorageTier.DISCARD
        for th, t in _TIERS:
            if ov >= th:
                tier = t
                break
        return MemoryImportanceResult(ov, rs, ss, ns, fw, gr, tier)

    @staticmethod
    def _rule_score(c: str) -> float:
        keywords = ["always", "never", "must", "rule", "important"]
        return min(1.0, sum(1 for k in keywords if k in c.lower()) * 0.15)

    @staticmethod
    def _semantic_score(c: str) -> float:
        w = len(c.split())
        return 0.9 if w > 100 else 0.7 if w > 50 else 0.5 if w > 20 else 0.3 if w > 5 else 0.1

    @staticmethod
    def _novelty_score(c: str, existing=None) -> float:
        if not existing:
            return 0.8
        c_lower = c.lower()
        max_sim = 0.0
        for f in existing:
            fc = f.lower() if isinstance(f, str) else (
                f.content.lower() if hasattr(f, "content") else str(f).lower()
            )
            words_c = set(c_lower.split())
            words_f = set(fc.split())
            common = len(words_c & words_f)
            total = len(words_c | words_f)
            max_sim = max(max_sim, common / total if total > 0 else 0)
        return 1.0 - max_sim

    @staticmethod
    def _fact_weight(c: str) -> float:
        s = 0.3
        if re.search(r"\d+", c):
            s += 0.3
        if c.count("\"") >= 2 or c.count("'") >= 2:
            s += 0.2
        if any(w in c.lower() for w in ["version", "api", "sdk"]):
            s += 0.2
        return min(1.0, s)

    @staticmethod
    def _goal_relation(c: str, ts=None) -> float:
        if not ts:
            return 0.3
        iv = ts.intent.value.lower() if hasattr(ts.intent, "value") else str(ts.intent).lower()
        return 0.5 if iv in c.lower() else 0.3
