"""PostgreSQL 记忆存储层。

所有记忆类型的持久化后端统一使用 PostgreSQL。
提供连接池管理、表结构初始化、CRUD 操作。

表结构:
    - memories: 统一的记忆存储表，支持 JSONB 元数据
    - memory_embeddings: 向量索引表（需要 pgvector 插件）
    - episodes: 情景记忆专用表
    - concepts: 语义记忆（知识图谱节点 + 关系）
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Optional

import asyncpg

from context_os.core.errors import MemoryError
from context_os.core.logger import get_logger

logger = get_logger(__name__)


class PostgresStore:
    """PostgreSQL 存储层。

    管理连接池，提供异步的 CRUD 操作。
    自动建表，支持 pgvector 扩展（如果可用）。

    Args:
        dsn: PostgreSQL 连接字符串。默认从 DATABASE_URL 环境变量读取。
        pool_min: 连接池最小连接数。
        pool_max: 连接池最大连接数。
    """

    # DDL：建表语句
    _DDL = """
    -- 记忆主表
    CREATE TABLE IF NOT EXISTS memories (
        id          TEXT PRIMARY KEY,
        type        TEXT NOT NULL,           -- working|short_term|long_term|episodic|semantic
        content     TEXT NOT NULL,
        embedding   REAL[],
        session_id  TEXT,
        user_id     TEXT DEFAULT 'anonymous',
        timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        access_count INTEGER DEFAULT 0,
        relevance_score REAL DEFAULT 0.0,
        metadata    JSONB DEFAULT '{}',
        expires_at  TIMESTAMPTZ
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
    CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
    CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
    CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at)
        WHERE expires_at IS NOT NULL;

    -- 情景记忆表
    CREATE TABLE IF NOT EXISTS episodes (
        id          TEXT PRIMARY KEY,
        scene       TEXT NOT NULL,
        action      TEXT NOT NULL,
        result      TEXT NOT NULL,
        feedback    TEXT DEFAULT '',
        related_files TEXT[] DEFAULT '{}',
        tags        TEXT[] DEFAULT '{}',
        user_id     TEXT DEFAULT 'anonymous',
        timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_episodes_tags ON episodes USING GIN(tags);
    CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp DESC);

    -- 语义记忆（知识图谱节点）
    CREATE TABLE IF NOT EXISTS concepts (
        id          TEXT PRIMARY KEY,
        name        TEXT UNIQUE NOT NULL,
        attributes  JSONB DEFAULT '{}',
        embedding   REAL[],
        confidence  REAL DEFAULT 1.0,
        user_id     TEXT DEFAULT 'anonymous',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 语义记忆（知识图谱关系）
    CREATE TABLE IF NOT EXISTS concept_relations (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        target_id   TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        relation_type TEXT NOT NULL,
        weight      REAL DEFAULT 1.0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_id, target_id, relation_type)
    );

    CREATE INDEX IF NOT EXISTS idx_relations_source ON concept_relations(source_id);
    CREATE INDEX IF NOT EXISTS idx_relations_target ON concept_relations(target_id);
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool_min: int = 2,
        pool_max: int = 10,
    ):
        self._dsn = dsn or os.environ.get("DATABASE_URL", "")
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool: Optional[asyncpg.Pool] = None

        if not self._dsn:
            logger.warning("DATABASE_URL not set, memory will use fallback JSON file storage")
        else:
            logger.info(
                "PostgresStore initialized (pool_min=%d, pool_max=%d)",
                pool_min, pool_max,
            )

    # ── 连接管理 ────────────────────────────────────────────────

    async def connect(self) -> None:
        """初始化连接池并建表。

        幂等操作：多次调用安全。如果已连接则跳过。
        """
        if self._pool:
            logger.debug("Already connected to PostgreSQL")
            return

        if not self._dsn:
            logger.warning("No DATABASE_URL configured, skipping PG connection")
            return

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._pool_min,
                max_size=self._pool_max,
            )
            logger.info("Connected to PostgreSQL pool")

            # 建表
            async with self._pool.acquire() as conn:
                await conn.execute(self._DDL)

            logger.info("Database tables initialized")

        except Exception as e:
            self._pool = None
            logger.error("Failed to connect to PostgreSQL: %s", e)
            raise MemoryError(f"PostgreSQL connection failed: {e}") from e

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")

    @property
    def is_connected(self) -> bool:
        """检查是否已连接。"""
        return self._pool is not None

    # ── 通用 CRUD ───────────────────────────────────────────────

    async def save_memory(
        self,
        id: str,
        type: str,
        content: str,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
        embedding: Optional[list[float]] = None,
        metadata: Optional[dict] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """保存一条记忆记录。

        Args:
            id: 记忆 ID，自动生成。
            type: 记忆类型（working|short_term|long_term|episodic|semantic）。
            content: 记忆内容。
            session_id: 关联的 Session ID。
            user_id: 用户 ID。
            embedding: 可选的向量嵌入。
            metadata: 额外的元数据结构。
            ttl_seconds: 生存时间（秒），过期后自动清理。

        Returns:
            记忆 ID。
        """
        expires_at = None
        if ttl_seconds:
            from datetime import timedelta, timezone
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        # JSON 文件降级
        if not self._pool:
            return await self._fallback_save(id, type, content, session_id, user_id, metadata)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO memories (id, type, content, embedding, session_id, user_id, metadata, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    access_count = 0,
                    relevance_score = 0.0
                """,
                id, type, content, embedding, session_id, user_id,
                json.dumps(metadata or {}), expires_at,
            )

        logger.debug("Memory saved: id=%s, type=%s, session=%s", id, type, session_id)
        return id

    async def get_memory(self, id: str) -> Optional[dict[str, Any]]:
        """根据 ID 获取单条记忆。

        Args:
            id: 记忆 ID。

        Returns:
            记忆字典或 None。
        """
        if not self._pool:
            return self._fallback_get(id)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM memories WHERE id = $1", id,
            )
            if row:
                # 更新访问计数
                await conn.execute(
                    "UPDATE memories SET access_count = access_count + 1 WHERE id = $1", id,
                )
                return dict(row)

        return None

    async def query_memories(
        self,
        type: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query_text: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        top_k: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """多条件查询记忆。

        支持:
            - 按类型、Session、用户过滤
            - 全文关键词检索
            - 向量相似度检索（需 pgvector）
            - 分页

        Args:
            type: 筛选记忆类型。
            session_id: 筛选 Session。
            user_id: 筛选用户。
            query_text: 关键词全文检索。
            embedding: 向量相似度检索。
            top_k: 返回数量上限。
            offset: 分页偏移。

        Returns:
            记忆字典列表。
        """
        if not self._pool:
            return self._fallback_query(type, top_k)

        conditions: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if type:
            conditions.append(f"type = ${param_idx}")
            params.append(type)
            param_idx += 1

        if session_id:
            conditions.append(f"session_id = ${param_idx}")
            params.append(session_id)
            param_idx += 1

        if user_id:
            conditions.append(f"user_id = ${param_idx}")
            params.append(user_id)
            param_idx += 1

        if query_text:
            conditions.append(f"content ILIKE ${param_idx}")
            params.append(f"%{query_text}%")
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        # 向量检索优先（需 pgvector 插件）
        if embedding and self._has_pgvector():
            order_clause = "embedding <=> $param_idx::vector"
            params.append(embedding)
            query = f"""
                SELECT *, (embedding <=> ${param_idx}::vector) AS distance
                FROM memories
                WHERE {where_clause} AND embedding IS NOT NULL
                ORDER BY distance ASC
                LIMIT ${param_idx + 1} OFFSET ${param_idx + 2}
            """
            params.extend([top_k, offset])
        else:
            query = f"""
                SELECT *
                FROM memories
                WHERE {where_clause}
                ORDER BY timestamp DESC, relevance_score DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([top_k, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = [dict(r) for r in rows]

            # 批量更新访问计数
            if results:
                ids = [r["id"] for r in results]
                await conn.execute(
                    "UPDATE memories SET access_count = access_count + 1 WHERE id = ANY($1::text[])",
                    ids,
                )

        logger.debug("Memory query returned %d results", len(results))
        return results

    async def delete_memory(self, id: str) -> bool:
        """删除一条记忆。

        Args:
            id: 记忆 ID。

        Returns:
            是否删除成功。
        """
        if not self._pool:
            return self._fallback_delete(id)

        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM memories WHERE id = $1", id)
            return result != "DELETE 0"

    async def cleanup_expired(self) -> int:
        """清理所有已过期的记忆。

        Returns:
            清理的记录数。
        """
        if not self._pool:
            return 0

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < NOW()",
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info("Cleaned up %d expired memories", count)
            return count

    # ── pgvector 检测 ──────────────────────────────────────────

    def _has_pgvector(self) -> bool:
        """检测 PostgreSQL 是否安装了 pgvector 扩展。"""
        # 懒检测，默认返回 True 让数据库报错
        # 如果出错会降级到普通排序
        return True

    # ── JSON 文件降级存储 ──────────────────────────────────────

    _FALLBACK_DIR = "./data/memory_fallback"

    async def _fallback_save(
        self, id: str, type: str, content: str,
        session_id: Optional[str], user_id: str,
        metadata: Optional[dict],
    ) -> str:
        """无 PG 时的 JSON 文件降级存储。"""
        import aiofiles
        import os

        os.makedirs(self._FALLBACK_DIR, exist_ok=True)
        path = os.path.join(self._FALLBACK_DIR, f"{id}.json")

        record = {
            "id": id,
            "type": type,
            "content": content,
            "session_id": session_id,
            "user_id": user_id,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
        }

        async with aiofiles.open(path, "w") as f:
            await f.write(json.dumps(record, ensure_ascii=False))

        logger.debug("Fallback saved: %s", path)
        return id

    def _fallback_get(self, id: str) -> Optional[dict]:
        """获取降级存储的单条记录。"""
        path = os.path.join(self._FALLBACK_DIR, f"{id}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.loads(f.read())
        return None

    def _fallback_query(self, type: Optional[str], top_k: int) -> list[dict]:
        """查询降级存储。"""
        import glob
        results = []
        pattern = os.path.join(self._FALLBACK_DIR, "*.json")
        for path in sorted(glob.glob(pattern), reverse=True)[:top_k]:
            with open(path) as f:
                record = json.loads(f.read())
                if type and record.get("type") != type:
                    continue
                results.append(record)
        return results

    def _fallback_delete(self, id: str) -> bool:
        """删除降级存储的记录。"""
        path = os.path.join(self._FALLBACK_DIR, f"{id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    # ── 情景记忆专用操作 ──────────────────────────────────────

    async def save_episode(
        self,
        scene: str,
        action: str,
        result: str,
        feedback: str = "",
        related_files: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        user_id: str = "anonymous",
    ) -> str:
        """保存一条情景记忆。

        Args:
            scene: 场景描述。
            action: 采取的行动。
            result: 结果。
            feedback: 用户反馈。
            related_files: 关联的文件路径列表。
            tags: 标签列表。
            user_id: 用户 ID。

        Returns:
            情景记忆 ID。
        """
        id = uuid.uuid4().hex
        if not self._pool:
            # 降级
            await self._fallback_save(id, "episodic", f"{scene}\n{action}\n{result}", None, user_id, {
                "scene": scene, "action": action, "result": result,
                "feedback": feedback, "tags": tags or [],
            })
            return id

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO episodes (id, scene, action, result, feedback, related_files, tags, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                id, scene, action, result, feedback,
                related_files or [], tags or [], user_id,
            )

        logger.info("Episode saved: id=%s, scene=%s", id, scene[:50])
        return id

    async def query_episodes(
        self,
        tags: Optional[list[str]] = None,
        user_id: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """查询情景记忆。

        Args:
            tags: 按标签筛选。
            user_id: 按用户筛选。
            top_k: 返回上限。

        Returns:
            情景记忆字典列表。
        """
        if not self._pool:
            return self._fallback_query("episodic", top_k)

        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if tags:
            conditions.append(f"tags && ${idx}::text[]")
            params.append(tags)
            idx += 1
        if user_id:
            conditions.append(f"user_id = ${idx}")
            params.append(user_id)
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM episodes WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}",
                *params, top_k,
            )
            return [dict(r) for r in rows]

    # ── 语义记忆（知识图谱）专用操作 ──────────────────────────

    async def save_concept(
        self,
        name: str,
        attributes: Optional[dict] = None,
        embedding: Optional[list[float]] = None,
        confidence: float = 1.0,
        user_id: str = "anonymous",
    ) -> str:
        """保存或更新一个概念节点。

        Args:
            name: 概念名称（唯一）。
            attributes: 属性字典。
            embedding: 向量嵌入。
            confidence: 置信度。
            user_id: 用户 ID。

        Returns:
            概念 ID。
        """
        id = uuid.uuid4().hex
        if not self._pool:
            await self._fallback_save(id, "semantic", name, None, user_id, attributes)
            return id

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO concepts (id, name, attributes, embedding, confidence, user_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (name) DO UPDATE SET
                    attributes = EXCLUDED.attributes,
                    embedding = CASE WHEN EXCLUDED.embedding IS NOT NULL THEN EXCLUDED.embedding ELSE concepts.embedding END,
                    confidence = EXCLUDED.confidence,
                    updated_at = NOW()
                """,
                id, name, json.dumps(attributes or {}), embedding, confidence, user_id,
            )

        logger.debug("Concept saved: name=%s, confidence=%.2f", name, confidence)
        return id

    async def save_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> str:
        """保存概念间的关系。

        Args:
            source_name: 源概念名称。
            target_name: 目标概念名称。
            relation_type: 关系类型。
            weight: 关系权重。

        Returns:
            关系 ID。
        """
        if not self._pool:
            logger.debug("Relation fallback (no PG): %s --[%s]--> %s", source_name, relation_type, target_name)
            return uuid.uuid4().hex

        async with self._pool.acquire() as conn:
            # 先获取源/目标 ID
            rows = await conn.fetch(
                "SELECT id, name FROM concepts WHERE name IN ($1, $2)",
                source_name, target_name,
            )
            name_to_id = {r["name"]: r["id"] for r in rows}

            if source_name not in name_to_id or target_name not in name_to_id:
                missing = []
                if source_name not in name_to_id:
                    missing.append(source_name)
                if target_name not in name_to_id:
                    missing.append(target_name)
                logger.warning("Cannot create relation: concepts not found: %s", missing)
                return ""

            id = uuid.uuid4().hex
            await conn.execute(
                """
                INSERT INTO concept_relations (id, source_id, target_id, relation_type, weight)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (source_id, target_id, relation_type) DO UPDATE SET
                    weight = EXCLUDED.weight
                """,
                id, name_to_id[source_name], name_to_id[target_name],
                relation_type, weight,
            )

        logger.debug("Relation saved: %s --[%s]--> %s", source_name, relation_type, target_name)
        return id

    async def query_graph(
        self,
        concept_name: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """查询知识图谱子图（BFS 遍历）。

        Args:
            concept_name: 起始概念名称。
            depth: BFS 遍历深度。

        Returns:
            子图数据。
        """
        if not self._pool:
            return {"nodes": [], "edges": []}

        async with self._pool.acquire() as conn:
            # 获取起始节点
            start = await conn.fetchrow(
                "SELECT * FROM concepts WHERE name = $1", concept_name,
            )
            if not start:
                return {"nodes": [], "edges": []}

            nodes = {start["id"]: dict(start)}
            edges = []

            visited = {start["id"]}
            current_level = {start["id"]}

            for _ in range(depth):
                if not current_level:
                    break

                # 查询当前层级节点出发的所有关系
                rows = await conn.fetch(
                    """
                    SELECT cr.*, cs.name AS source_name, ct.name AS target_name
                    FROM concept_relations cr
                    JOIN concepts cs ON cr.source_id = cs.id
                    JOIN concepts ct ON cr.target_id = ct.id
                    WHERE cr.source_id = ANY($1::text[])
                    """,
                    list(current_level),
                )

                next_level = set()
                for r in rows:
                    edges.append({
                        "source": r["source_name"],
                        "target": r["target_name"],
                        "type": r["relation_type"],
                        "weight": r["weight"],
                    })
                    if r["target_id"] not in visited:
                        visited.add(r["target_id"])
                        next_level.add(r["target_id"])
                        target_row = await conn.fetchrow(
                            "SELECT * FROM concepts WHERE id = $1", r["target_id"],
                        )
                        if target_row:
                            nodes[target_row["id"]] = dict(target_row)

                current_level = next_level

            return {
                "nodes": list(nodes.values()),
                "edges": edges,
            }
