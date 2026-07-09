"""KnowledgeEvolution — 知识图谱自演化。

自动聚类语义概念、合并重复、更新知识图谱。
参考 Java: com.owencli.contextos.evolution.KnowledgeEvolution
"""
from __future__ import annotations
import logging
from context_os.memory.store import SQLiteStore

logger = logging.getLogger(__name__)

class KnowledgeEvolution:
    """知识图谱自演化引擎。"""

    def __init__(self, store: SQLiteStore):
        self.store = store

    async def cluster_concepts(self) -> int:
        """聚类相似概念，标记可能重复的。"""
        rows = self.store.query("SELECT id, name, description FROM concepts ORDER BY name", [])
        clusters = 0
        names_seen = []
        for r in rows:
            name_lower = r[1].strip().lower()
            for seen in names_seen:
                if self._is_similar(name_lower, seen):
                    self.store.execute("UPDATE concepts SET metadata='{\"duplicate_of\":\"' || ? || '\"}' WHERE id=?", [seen, r[0]])
                    clusters += 1
                    break
            names_seen.append(name_lower)
        if clusters: logger.info("Cluster: marked %d potential duplicates", clusters)
        return clusters

    async def merge_duplicates(self) -> int:
        """合并已标记的重复概念（将关系重定向到原概念）。"""
        rows = self.store.query("SELECT id, metadata FROM concepts WHERE metadata LIKE '%duplicate_of%'", [])
        merged = 0
        for r in rows:
            import json
            try: meta = json.loads(r[1]); orig_id = meta.get("duplicate_of")
            except: continue
            if orig_id:
                self.store.execute("UPDATE concept_relations SET source_id=? WHERE source_id=?", [orig_id, r[0]])
                self.store.execute("UPDATE concept_relations SET target_id=? WHERE target_id=?", [orig_id, r[0]])
                self.store.execute("DELETE FROM concepts WHERE id=?", [r[0]])
                merged += 1
        if merged: logger.info("Merge: merged %d duplicate concepts", merged)
        return merged

    async def evolve(self) -> dict:
        """执行一轮知识演化。"""
        return {"clustered": await self.cluster_concepts(), "merged": await self.merge_duplicates()}

    @staticmethod
    def _is_similar(a: str, b: str) -> bool:
        """简单相似度检测（编辑距离 < 3 或前缀匹配）。"""
        if len(a) < 3 or len(b) < 3: return False
        if a == b: return True
        if len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:3]) or b.startswith(a[:3])): return True
        return KnowledgeEvolution._levenshtein(a, b) <= 2

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        if len(s1) < len(s2): s1, s2 = s2, s1
        if len(s2) == 0: return len(s1)
        prev = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + (c1 != c2)))
            prev = curr
        return prev[-1]
