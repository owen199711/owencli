"""语义记忆（Semantic Memory）。

Agent 积累的通用知识和概念性理解，剥离了具体时间和场景。
以知识图谱（Concept → Relation → Concept）的形式存储。

知识来源:
    - 从情景记忆中自动抽象提炼
    - 用户显式教授的知识
    - 从文档/代码库中提取的概念
"""

from __future__ import annotations

from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class SemanticMemory:
    """语义记忆 — 知识图谱。

    Args:
        store: PostgreSQL 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("SemanticMemory initialized")

    # ── 概念管理 ────────────────────────────────────────────────

    async def add_concept(
        self,
        name: str,
        attributes: Optional[dict[str, Any]] = None,
        embedding: Optional[list[float]] = None,
        confidence: float = 1.0,
    ) -> str:
        """添加或更新一个概念节点。

        如果概念已存在（同名），则更新属性和置信度。

        Args:
            name: 概念名称，唯一标识。
            attributes: 属性字典，如 {"定义": "...", "示例": "..."}。
            embedding: 语义向量，用于相似度检索。
            confidence: 置信度 (0-1)。

        Returns:
            概念 ID。
        """
        cid = await self.store.save_concept(
            name=name,
            attributes=attributes,
            embedding=embedding,
            confidence=confidence,
            user_id=self.user_id,
        )
        logger.info("Concept %s: name='%s', confidence=%.2f", "updated" if cid else "added", name, confidence)
        return cid

    async def get_concept(self, name: str) -> Optional[dict[str, Any]]:
        """获取某个概念的详情。

        Args:
            name: 概念名称。

        Returns:
            概念字典或 None。
        """
        if not self.store._conn:
            return None

        cursor = await self.store._conn.execute(
            "SELECT * FROM concepts WHERE name = ?", (name,),
        )
        row = await cursor.fetchone()
        return self.store._row_to_dict(row) if row else None

    # ── 关系管理 ────────────────────────────────────────────────

    async def add_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> str:
        """添加概念间的关系。

        例如: add_relation("Python", "FastAPI", "框架") → Python --[框架]--> FastAPI

        Args:
            source: 源概念名称。
            target: 目标概念名称。
            relation_type: 关系类型（如 "框架", "依赖", "包含", "反模式"）。
            weight: 关系权重 (0-1)，表示关系的强弱。

        Returns:
            关系 ID（如果概念不存在则返回空字符串）。
        """
        rid = await self.store.save_relation(
            source_name=source,
            target_name=target,
            relation_type=relation_type,
            weight=weight,
        )
        if rid:
            logger.info(
                "Relation added: %s --[%s]--> %s (weight=%.2f)",
                source, relation_type, target, weight,
            )
        return rid

    async def add_relations_batch(
        self,
        relations: list[tuple[str, str, str, float]],
    ) -> int:
        """批量添加关系。

        Args:
            relations: (source, target, relation_type, weight) 元组列表。

        Returns:
            成功添加的关系数。
        """
        count = 0
        for source, target, rel_type, weight in relations:
            rid = await self.add_relation(source, target, rel_type, weight)
            if rid:
                count += 1
        logger.info("Batch relations: %d/%d added", count, len(relations))
        return count

    # ── 图谱查询 ────────────────────────────────────────────────

    async def query(self, concept: str, depth: int = 1) -> dict[str, Any]:
        """查询知识图谱子图。

        从指定概念出发，BFS 遍历到指定深度。

        Args:
            concept: 起始概念名称。
            depth: 遍历深度（1 = 直接关联，2 = 关联的关联）。

        Returns:
            子图数据: {"nodes": [...], "edges": [...]}。
        """
        result = await self.store.query_graph(
            concept_name=concept,
            depth=depth,
        )

        node_count = len(result.get("nodes", []))
        edge_count = len(result.get("edges", []))
        logger.info(
            "Graph query: concept='%s', depth=%d, nodes=%d, edges=%d",
            concept, depth, node_count, edge_count,
        )
        return result

    async def find_shortest_path(self, source: str, target: str) -> list[dict[str, Any]]:
        """查找两个概念之间的最短路径（BFS）。

        Args:
            source: 起始概念名称。
            target: 目标概念名称。

        Returns:
            路径上的节点和关系序列。
        """
        if not self.store._conn:
            return []

        # BFS 搜索
        visited = {source}
        queue: list[list[dict]] = [[{"type": "concept", "name": source}]]

        while queue:
            path = queue.pop(0)
            last_node = path[-1]["name"]

            if last_node == target:
                logger.info("Shortest path found: %s -> %s, length=%d", source, target, len(path))
                return path

            # 查询从 last_node 出发的所有关系
            cursor = await self.store._conn.execute(
                "SELECT cr.relation_type, c.name AS neighbor, c.id "
                "FROM concept_relations cr "
                "JOIN concepts cs ON cr.source_id = cs.id "
                "JOIN concepts ct ON cr.target_id = ct.id "
                "WHERE cs.name = ?",
                (last_node,),
            )
            rows = await cursor.fetchall()

            for r in rows:
                neighbor = r["neighbor"]
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = path + [
                        {"type": "relation", "type_name": r["relation_type"]},
                        {"type": "concept", "name": neighbor},
                    ]
                    queue.append(new_path)

        logger.debug("No path found: %s -> %s", source, target)
        return []

    # ── 知识抽象 ────────────────────────────────────────────────

    async def abstract_from_episodes(
        self,
        episodes: list[dict[str, Any]],
    ) -> int:
        """从情景记忆中抽象提炼通用知识。

        分析一组情景记忆，提取共同模式作为语义概念存储到图谱中。

        Args:
            episodes: 情景记忆字典列表。

        Returns:
            新添加的概念数。
        """
        concepts_added = 0

        # 收集所有标签和场景中的关键词
        tag_counter: dict[str, int] = {}
        for ep in episodes:
            tags = ep.get("tags") or []
            for tag in tags:
                tag_counter[tag] = tag_counter.get(tag, 0) + 1

        # 高频标签作为概念入库
        for tag, count in tag_counter.items():
            if count >= 2:  # 出现 2 次以上的标签提炼为概念
                exists = await self.get_concept(tag)
                if not exists:
                    await self.add_concept(
                        name=tag,
                        attributes={
                            "来源": "情景记忆抽象",
                            "出现次数": count,
                            "描述": f"从 {count} 次经历中抽象的概念",
                        },
                        confidence=min(0.5 + count * 0.1, 1.0),
                    )
                    concepts_added += 1

        if concepts_added:
            logger.info("Abstracted %d concepts from %d episodes", concepts_added, len(episodes))
        else:
            logger.debug("No new concepts abstracted from episodes")

        return concepts_added
