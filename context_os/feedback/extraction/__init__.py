
"""MemoryExtractionEngine — 规则+LLM 混合事实提取。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

@dataclass
class ExtractedFact:
    content: str; category: str; confidence: float
    source: str = "rule"; metadata: dict = field(default_factory=dict)

class RuleFactExtractor:
    PATTERNS = {"preference": [r"(?:用户|user|我)\s*(?:喜欢|偏好|prefer|like|使用|use)\s+(.+)"],
                "constraint": [r"(?:cannot|不要|禁止|must not|never)\s+(.+)"],
                "fact": [r"(?:实际|actually|fact:|注意|note:|important:)\s*(.+)", r"(?:通常|always|每次|pattern:)\s*(.+)"]}

    def extract(self, text: str) -> list[ExtractedFact]:
        facts = []
        for cat, patterns in self.PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    facts.append(ExtractedFact(content=m.group(1).strip(), category=cat, confidence=0.6, source="rule"))
        return facts

class MemoryExtractionEngine:
    def __init__(self): self.rule_extractor = RuleFactExtractor()

    def extract(self, text: str, use_llm: bool = False, llm_client=None) -> list[ExtractedFact]:
        return self.rule_extractor.extract(text)

