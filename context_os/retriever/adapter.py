"""SourceAdapter — 统一异构检索 API。

5 个 Adapter 将不同存储源的检索接口统一为:
    async def search(query, top_k, **kwargs) -> list[RetrievedItem]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from context_os.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RetrievedItem:
    """检索结果统一包装。"""

    content: str
    source: str            # "long_term" | "experience" | "knowledge" | "session" | "journal"
    score: float = 0.0     # 各源内部得分（未加权）
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    timestamp: str = ""


@runtime_checkable
class SourceAdapter(Protocol):
    """SourceAdapter 协议（Phase 6）。

    每个 Adapter 实现 search() 方法，返回统一的 RetrievedItem 列表。
    """

    source_name: str
    source_weight: float

    async def search(self, query: str, top_k: int, **kwargs: Any) -> list[RetrievedItem]:
        ...


# ═══════════════════════════════════════════════════════════════
# LTM Adapter
# ═══════════════════════════════════════════════════════════════


class LTMAdapter:
    """LongTerm Memory 适配器。

    权重最高 (1.0)，因为 LTM 已通过 Write Decision 把关。
    """

    source_name = "long_term"
    source_weight = 1.0

    def __init__(self, ltm: Any) -> None:
        self._ltm = ltm

    async def search(self, query: str, top_k: int = 25, **kwargs: Any) -> list[RetrievedItem]:
        try:
            expand = self._ltm.detect_temporal_query(query) if hasattr(self._ltm, "detect_temporal_query") else False
            results = await self._ltm.retrieve(
                query, top_k=top_k,
                intent=kwargs.get("intent"),
                expand_history=expand,
            )
            items: list[RetrievedItem] = []
            for r in results:
                content = r.content if hasattr(r, "content") else str(r)
                meta = dict(r.metadata) if hasattr(r, "metadata") else {}
                meta.setdefault("source_reliability", 0.8)
                meta["ltm_subtype"] = meta.get("ltm_subtype", "fact" if meta.get("fact_id") else "summary")
                items.append(RetrievedItem(
                    content=content,
                    source=self.source_name,
                    score=getattr(r, "score", 0.0),
                    metadata=meta,
                    embedding=getattr(r, "embedding", None),
                    timestamp=getattr(r, "timestamp", ""),
                ))
            return items
        except Exception as e:
            logger.warning("LTMAdapter search failed: %s", e)
            return []


# ═══════════════════════════════════════════════════════════════
# Experience Adapter
# ═══════════════════════════════════════════════════════════════


class ExperienceAdapter:
    """Experience Memory 适配器。

    weight=0.8，场景还原参考。
    """

    source_name = "experience"
    source_weight = 0.8

    def __init__(self, exp: Any) -> None:
        self._exp = exp

    async def search(self, query: str, top_k: int = 10, **kwargs: Any) -> list[RetrievedItem]:
        try:
            results = await self._exp.recall_relevant(
                scenario_query=query, top_k=top_k,
            )
            items: list[RetrievedItem] = []
            for r in results:
                if isinstance(r, dict):
                    content = r.get("scene", "") or r.get("action", "") or str(r)
                    tags = r.get("tags", [])
                    if isinstance(tags, str):
                        import json
                        try:
                            tags = json.loads(tags)
                        except Exception:
                            tags = []
                    items.append(RetrievedItem(
                        content=content,
                        source=self.source_name,
                        score=0.5,
                        metadata={
                            "exp_tags": tags,
                            "experience_type": r.get("experience_type", ""),
                            "source_reliability": 0.7,
                        },
                        timestamp=r.get("created_at", ""),
                    ))
            return items
        except Exception as e:
            logger.warning("ExperienceAdapter search failed: %s", e)
            return []


# ═══════════════════════════════════════════════════════════════
# Knowledge Adapter
# ═══════════════════════════════════════════════════════════════


class KnowledgeAdapter:
    """Knowledge Graph 适配器。

    weight=0.6，语义扩展。
    """

    source_name = "knowledge"
    source_weight = 0.6

    def __init__(self, semantic_memory: Any) -> None:
        self._sem = semantic_memory

    async def search(self, query: str, top_k: int = 10, **kwargs: Any) -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        try:
            if not hasattr(self._sem, "query"):
                return items

            result = await self._sem.query(concept=query[:50], depth=1)
            if isinstance(result, dict):
                nodes = result.get("nodes", [])
                edges = result.get("edges", [])
                for n in nodes:
                    items.append(RetrievedItem(
                        content=str(n),
                        source=self.source_name,
                        score=0.6,
                        metadata={"source_reliability": 0.7, "node_type": "concept"},
                    ))
                for e in edges:
                    items.append(RetrievedItem(
                        content=str(e),
                        source=self.source_name,
                        score=0.48,  # 0.6 * 0.8
                        metadata={"source_reliability": 0.7, "node_type": "relation"},
                    ))
            return items
        except Exception as e:
            logger.warning("KnowledgeAdapter search failed: %s", e)
            return items


# ═══════════════════════════════════════════════════════════════
# Session Adapter
# ═══════════════════════════════════════════════════════════════


class SessionAdapter:
    """Session Memory 适配器。

    weight=0.3，会话上下文。
    """

    source_name = "session"
    source_weight = 0.3

    def __init__(self, session_memory: Any) -> None:
        self._session = session_memory

    async def search(self, query: str, top_k: int = 10, **kwargs: Any) -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        try:
            if not hasattr(self._session, "query_pending"):
                return items

            results = await self._session.query_pending(query=query, top_k=top_k)
            for s in results:
                if isinstance(s, dict):
                    items.append(RetrievedItem(
                        content=s.get("content", ""),
                        source=self.source_name,
                        score=0.3,
                        metadata={
                            "source_reliability": 0.5,
                            "turn": s.get("turn_number", 0) if isinstance(s.get("metadata"), dict) else 0,
                        },
                        timestamp=s.get("timestamp", ""),
                    ))
            return items
        except Exception as e:
            logger.warning("SessionAdapter search failed: %s", e)
            return items


# ═══════════════════════════════════════════════════════════════
# Journal Adapter
# ═══════════════════════════════════════════════════════════════


class JournalAdapter:
    """Journal 适配器。

    weight=0.4，未处理的原始记录，时效性补偿。
    """

    source_name = "journal"
    source_weight = 0.4

    def __init__(self, journal_store: Any) -> None:
        self._journal = journal_store

    async def search(self, query: str, top_k: int = 10, **kwargs: Any) -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        try:
            results = await self._journal.query_pending(limit=top_k)
            for r in results:
                if isinstance(r, dict):
                    items.append(RetrievedItem(
                        content=r.get("raw_input", ""),
                        source=self.source_name,
                        score=0.2,
                        metadata={
                            "source_reliability": 0.5,
                            "journal_id": r.get("id", ""),
                            "task_intent": r.get("task_intent", ""),
                            "status": r.get("status", "pending"),
                        },
                        timestamp=r.get("created_at", ""),
                    ))
            return items
        except Exception as e:
            logger.warning("JournalAdapter search failed: %s", e)
            return items
