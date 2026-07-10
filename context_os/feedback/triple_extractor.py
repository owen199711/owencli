"""Knowledge 三元组抽取器（通道 A：规则抽取）。

基于 LTM_WRITE_STRATEGY.md 第 4.4 节的设计，实现确定性规则匹配，
从文本中抽取 {subject, relation, object} 三元组。

双通道方案:
    通道 A: 规则抽取（本文件）— 确定性，0 成本，confidence=1.0
    通道 B: LLM 异步抽取 — 由 BackgroundConceptWorker 处理

通道 A 命中的规则模式:
    - "X 是 Y"           → {X, 是, Y}
    - "X 属于 Y"         → {X, 属于, Y}
    - "X 基于 Y"         → {X, 基于, Y}
    - "X 包含 Y"         → {X, 包含, Y}
    - "X 的 Y 是 Z"      → {X.Y, 是, Z}
    - "X 用 Y 实现了 Z"  → {X, 使用, Y}, {X, 产出, Z}

通道 B 触发信号检测:
    - 文本包含关系/概念关键词但通道 A 未命中 → concept_pending=True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Triple:
    """单个三元组。"""

    subject: str
    relation: str
    obj: str
    confidence: float = 1.0
    source: str = "rule"  # "rule" | "llm"


@dataclass
class TripleExtractResult:
    """三元组抽取结果。"""

    triples: list[Triple] = field(default_factory=list)
    channel_a_hit: bool = False
    channel_b_signal: bool = False
    # 通道 B 信号得分 (0~1)
    channel_b_score: float = 0.0

    @property
    def should_store_knowledge(self) -> bool:
        """通道 A 命中 → 直接写入 Knowledge。"""
        return self.channel_a_hit

    @property
    def should_pend_concept(self) -> bool:
        """通道 B 触发 → 标记 concept_pending，等待异步抽取。"""
        return not self.channel_a_hit and self.channel_b_signal


# ── 模式定义 ─────────────────────────────────────────────────

# 模式格式: (pattern, relation, group_mapping)
# group_mapping: [(group_name, role), ...]
# 其中 role 为 "subject", "relation", "obj"

_RULE_PATTERNS: list[tuple[re.Pattern, str, list[tuple[str, str]]]] = [
    # "X 属于 Y" — X belongs to Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(属于|属于|belongs?\s+to)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "属于",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 基于 Y" — X is based on Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(基于|based\s+on)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "基于",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 包含 Y" — X contains Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(包含|包括|contains?|includes?)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "包含",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 是 Y" — X is Y (most generic)
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(是|is\s+a\s+|is\s+an\s+|is\s+)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "是",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 的 Y 是 Z" — X's Y is Z
    (
        re.compile(
            r"(?P<owner>.{1,20}?)的(?P<attr>.{1,15}?)\s*(是|is)\s*(?P<val>.{1,30}?)(?:[，。,.]|$)"
        ),
        "是",
        [("o_a", "subject"), ("val", "obj")],
    ),
    # "X 用 Y" 模式（产出关系）
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(用|使用|利用|uses?)\s*(?P<tool>.{1,30}?)"),
        "使用",
        [("s", "subject"), ("tool", "obj")],
    ),
    # "X 实现了/产出了 Y" — X implements/produces Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(实现了|产出了|implement|produce[sd]?)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "产出",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 调用 Y" — X calls/invokes Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(调用|calls?|invokes?)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "调用",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 依赖 Y" — X depends on Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(依赖|depends?\s+on)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "依赖",
        [("s", "subject"), ("o", "obj")],
    ),
    # "X 等同于 Y" — X equals Y
    (
        re.compile(r"(?P<s>.{1,30}?)\s*(等同于|等价于|equals?)\s*(?P<o>.{1,30}?)(?:[，。,.]|$)"),
        "等同于",
        [("s", "subject"), ("o", "obj")],
    ),
]

# ── 通道 B 触发信号关键词 ───────────────────────────────────
_CONCEPT_KEYWORDS = re.compile(
    r"概念|关系|定义|术语|协议|接口|架构|框架|模式|类型|分类|"
    r"concept|relation|define|term|protocol|interface|architecture|"
    r"framework|pattern|type|classify|category|taxonomy",
    re.IGNORECASE,
)

_TECHNICAL_NOUN_PATTERN = re.compile(
    r"[A-Z][a-z]+|[A-Z]{2,}|\b(?:API|SDK|HTTP|JSON|XML|REST|SQL|ORM)\b",
)

# ── 清理函数 ─────────────────────────────────────────────────
def _clean_text(text: str) -> str:
    """清理文本中的标点符号，替换为空格，保留字母数字和中文。"""
    import unicodedata
    result_chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        # 保留字母(L)、数字(N)、标记(Mn/Mc)、空格(Zs/Zl/Zp)，其余替换为空格
        if cat.startswith('L') or cat.startswith('N') or cat.startswith('M'):
            result_chars.append(ch)
        elif cat.startswith('Z'):
            result_chars.append(' ')
        elif ch in ('-', '_', '+', '#', '@', '.', '/'):
            result_chars.append(ch)
        else:
            result_chars.append(' ')
    return ''.join(result_chars)


class TripleExtractor:
    """通道 A 三元组规则抽取器。

    确定性规则匹配，从文本中抽取 {subject, relation, object} 三元组。
    同时也检测通道 B 的触发信号（概念关键词 / 技术名词）。
    """

    def __init__(self, extra_patterns: Optional[list] = None):
        """初始化抽取器。

        Args:
            extra_patterns: 额外规则模式列表，格式同 _RULE_PATTERNS。
        """
        self._patterns = list(_RULE_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def extract(self, text: str) -> TripleExtractResult:
        """从文本中抽取三元组。

        Args:
            text: 输入文本。

        Returns:
            TripleExtractResult，包含抽取的三元组和通道 B 信号。
        """
        triples: list[Triple] = []
        seen: set[tuple[str, str, str]] = set()
        cleaned = _clean_text(text)

        for pattern, relation, group_mappings in self._patterns:
            for match in pattern.finditer(cleaned):
                groups = match.groupdict()

                # 根据映射解析 subject, obj
                subject_parts = []
                obj_parts = []
                for gname, role in group_mappings:
                    val = groups.get(gname, "").strip()
                    if not val:
                        continue
                    if role == "subject":
                        subject_parts.append(val)
                    elif role == "obj":
                        obj_parts.append(val)

                subject = ".".join(subject_parts).strip()
                obj = " ".join(obj_parts).strip()

                # 处理复合 subject (如 "X.Y" 格式)
                if not subject and len(group_mappings) >= 2:
                    # 尝试从特殊 group 组合 subject
                    special_parts = []
                    for gname, role in group_mappings:
                        if gname not in ("s", "o"):
                            val = groups.get(gname, "").strip()
                            if val:
                                special_parts.append(val)
                    for gname, role in group_mappings:
                        if role == "obj":
                            val = groups.get(gname, "").strip()
                            if val:
                                obj_parts.append(val)
                    if special_parts:
                        subject = ".".join(special_parts)

                if not subject or not obj:
                    continue

                # 特殊处理 "X 的 Y 是 Z" 模式
                owner = groups.get("owner")
                attr = groups.get("attr")
                if owner and attr and not subject:
                    subject = f"{owner}.{attr}"
                    for gname, role in group_mappings:
                        if role == "obj":
                            val = groups.get(gname, "").strip()
                            if val:
                                obj = val

                if not subject or not obj:
                    continue

                subject = self._normalize(subject)
                obj = self._normalize(obj)

                # 去重
                key = (subject, relation, obj)
                if key in seen:
                    continue
                seen.add(key)

                triples.append(Triple(
                    subject=subject,
                    relation=relation,
                    obj=obj,
                    confidence=1.0,
                    source="rule",
                ))

        # ── 通道 B 信号检测 ──
        channel_b_signal = False
        channel_b_score = 0.0

        if not triples:
            # 检测概念关键词
            kw_count = len(_CONCEPT_KEYWORDS.findall(text))
            # 检测技术名词
            tech_count = len(_TECHNICAL_NOUN_PATTERN.findall(text))

            if kw_count >= 1 and tech_count >= 1:
                channel_b_score = 0.8
                channel_b_signal = True
            elif kw_count >= 1:
                channel_b_score = 0.5
                channel_b_signal = True
            elif tech_count >= 2:
                channel_b_score = 0.4
                channel_b_signal = True

        return TripleExtractResult(
            triples=triples,
            channel_a_hit=len(triples) > 0,
            channel_b_signal=channel_b_signal,
            channel_b_score=channel_b_score,
        )

    @staticmethod
    def _normalize(s: str) -> str:
        """规范化文本：去掉多余空格和标点。"""
        s = s.strip(" ，。；：""''！？、")
        s = re.sub(r"\s+", " ", s)
        return s
