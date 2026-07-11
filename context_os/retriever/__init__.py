"""Retriever — 统一检索引擎。

Search → Score → Merge → Rank 四步流程。
通过 SourceAdapter 统一 LTM / Experience / Knowledge / Session / Journal
五源检索接口，ScoringEngine 用统一公式打分。
"""

from context_os.retriever.scoring import ScoringEngine, SourceReliability
from context_os.retriever.adapter import (
    SourceAdapter,
    LTMAdapter,
    ExperienceAdapter,
    KnowledgeAdapter,
    SessionAdapter,
    JournalAdapter,
    RetrievedItem,
)
from context_os.retriever.retriever import UnifiedRetriever

__all__ = [
    "ScoringEngine",
    "SourceReliability",
    "SourceAdapter",
    "LTMAdapter",
    "ExperienceAdapter",
    "KnowledgeAdapter",
    "SessionAdapter",
    "JournalAdapter",
    "RetrievedItem",
    "UnifiedRetriever",
]
