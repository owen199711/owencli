"""KnowledgeEvolution — 知识图谱自演化（完整 Java 对齐 Pipeline）。

Pipeline: extractConcepts → clusterConcepts → mergeClusters → summarizeClusters → updateGraph
对齐 Java: com.owencli.contextos.evolution.KnowledgeEvolution
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
from context_os.memory.store import SQLiteStore
from context_os.memory.semantic import SemanticMemory

logger = logging.getLogger(__name__)

@dataclass
class ConceptEntry:
    id: str; name: str; metadata: dict = field(default_factory=dict); score: float = 0.0

@dataclass
class ConceptCluster:
    name: str; entries: list[ConceptEntry] = field(default_factory=list)

class KnowledgeEvolution:
    """知识图谱自演化引擎。"""

    def __init__(self, semantic_memory: SemanticMemory, store: SQLiteStore):
        self.sm = semantic_memory
        self.store = store

    async def evolve(self) -> dict:
        concepts = await self._extract_concepts()
        clusters = await self._cluster_concepts(concepts)
        await self._merge_clusters(clusters)
        summaries = await self._summarize_clusters(clusters)
        await self._update_graph(summaries)
        return {"concepts": len(concepts), "clusters": len(clusters), "summaries": len(summaries)}

    async def _extract_concepts(self) -> list[ConceptEntry]:
        rows = self.store.query("SELECT id, content, metadata FROM memories WHERE type='semantic' OR type='knowledge' LIMIT 1000", [])
        concepts = []
        import json
        for r in rows:
            meta = {}
            try: meta = json.loads(r[2]) if r[2] else {}
            except: pass
            if r[1] and r[1].strip():
                concepts.append(ConceptEntry(id=r[0], name=r[1].strip(), metadata=meta, score=meta.get("relevance_score", 0.0)))
        return concepts

    async def _cluster_concepts(self, concepts: list[ConceptEntry]) -> list[ConceptCluster]:
        if len(concepts) < 3: return [ConceptCluster(name=c.name, entries=[c]) for c in concepts]
        clusters = []; processed = [False] * len(concepts)
        for i in range(len(concepts)):
            if processed[i]: continue
            cluster = [concepts[i]]; processed[i] = True
            for j in range(i+1, len(concepts)):
                if processed[j]: continue
                sim = self._compute_similarity(concepts[i].name, concepts[j].name)
                if sim >= 0.6: cluster.append(concepts[j]); processed[j] = True
            cluster_name = max(c.name for c in cluster)  # keep longest
            clusters.append(ConceptCluster(name=cluster_name, entries=cluster))
        logger.info("Evolve: clustered %d concepts into %d groups", len(concepts), len(clusters))
        return clusters

    async def _merge_clusters(self, clusters: list[ConceptCluster]) -> None:
        for cluster in clusters:
            if len(cluster.entries) <= 1: continue
            main = cluster.entries[0]
            for other in cluster.entries[1:]:
                try: await self.sm.add_relation(main.name, other.name, "related_to", 0.8)
                except: pass

    async def _summarize_clusters(self, clusters: list[ConceptCluster]) -> dict:
        return {c.name: ", ".join(dict.fromkeys(e.name for e in c.entries)) for c in clusters}

    async def _update_graph(self, summaries: dict) -> None:
        for name, summary in summaries.items():
            try:
                await self.sm.add_concept(f"cluster:{name}", {"description": f"Auto-clustered: {summary}", "source": "KnowledgeEvolution"}, None, 0.7)
            except: pass
        logger.info("Evolve: graph updated with %d cluster summaries", len(summaries))

    @staticmethod
    def _compute_similarity(a: str, b: str) -> float:
        if not a or not b: return 0.0
        la, lb = a.lower(), b.lower()
        if la == lb: return 1.0
        if la in lb or lb in la: return 0.8
        a_words = {w for w in la.split() if len(w) >= 2}
        b_words = {w for w in lb.split() if len(w) >= 2}
        if not a_words or not b_words: return 0.0
        intersection = a_words & b_words; union = a_words | b_words
        return len(intersection) / len(union)
