"""SQLite 记忆存储层。

所有记忆类型的持久化后端统一使用 SQLite。
提供异步 CRUD 操作，自动建表。

表结构:
    - memories: 统一的记忆存储表
    - concepts: 语义记忆（知识图谱节点）
    - concept_relations: 语义记忆（知识图谱关系）
    - experiences: 统一体验表（episode/reflection/procedure/tool_usage）
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from context_os.core.errors import MemoryError
from context_os.core.logger import get_logger

logger = get_logger(__name__)


class SQLiteStore:
    """SQLite 存储层。

    管理数据库连接，提供异步的 CRUD 操作。
    自动建表，数据存储在本地文件。

    Args:
        db_path: SQLite 数据库文件路径。默认从 DATABASE_URL 环境变量读取，
                 或使用默认路径 ./data/context_os.db。
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS memories (
        id              TEXT PRIMARY KEY,
        type            TEXT NOT NULL,
        content         TEXT NOT NULL,
        embedding       TEXT,
        session_id      TEXT,
        user_id         TEXT DEFAULT 'anonymous',
        timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
        access_count    INTEGER DEFAULT 0,
        relevance_score REAL DEFAULT 0.0,
        metadata        TEXT DEFAULT '{}',
        expires_at      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
    CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
    CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
    CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp DESC);

    CREATE TABLE IF NOT EXISTS concepts (
        id              TEXT PRIMARY KEY,
        name            TEXT UNIQUE NOT NULL,
        attributes      TEXT DEFAULT '{}',
        embedding       TEXT,
        confidence      REAL DEFAULT 1.0,
        user_id         TEXT DEFAULT 'anonymous',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS concept_relations (
        id              TEXT PRIMARY KEY,
        source_id       TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        target_id       TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
        relation_type   TEXT NOT NULL,
        weight          REAL DEFAULT 1.0,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(source_id, target_id, relation_type)
    );
    CREATE INDEX IF NOT EXISTS idx_relations_source ON concept_relations(source_id);
    CREATE INDEX IF NOT EXISTS idx_relations_target ON concept_relations(target_id);

    -- 统一 Experience 表（合并 episodes / reflections / procedures / tool_experience）
    CREATE TABLE IF NOT EXISTS experiences (
        id               TEXT PRIMARY KEY,
        user_id          TEXT DEFAULT 'anonymous',
        experience_type  TEXT NOT NULL,       -- 'episode' | 'reflection' | 'procedure' | 'tool_usage'

        -- 通用
        tags             TEXT DEFAULT '[]',   -- JSON
        metadata         TEXT DEFAULT '{}',    -- JSON
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now')),

        -- episode 专有
        scene            TEXT,
        action           TEXT,
        result           TEXT,
        feedback         TEXT,

        -- reflection 专有
        task_type        TEXT,                -- 反思所属任务类型
        root_cause       TEXT,                -- 根因分析
        lesson           TEXT,                -- 经验教训
        preventive_action TEXT,               -- 预防措施

        -- procedure 专有
        proc_name        TEXT,                -- 流程名称（别名为 name）
        steps            TEXT,                -- 步骤 JSON
        total_count      INTEGER DEFAULT 0,   -- 总执行次数
        proc_success_count INTEGER DEFAULT 0, -- 成功次数（别名为 success_count）
        last_used        TEXT,                -- 最后使用时间

        -- tool_usage 专有
        tool_name        TEXT,
        tool_success     INTEGER,             -- 0 或 1（别名为 success）
        error_type       TEXT,
        duration_ms      INTEGER DEFAULT 0,
        scenario         TEXT,

        -- 输入/输出预览（tool_usage 和 episode 通用）
        input_preview    TEXT,
        output_preview   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_exp_type ON experiences(experience_type);
    CREATE INDEX IF NOT EXISTS idx_exp_user ON experiences(user_id);
    CREATE INDEX IF NOT EXISTS idx_exp_tags ON experiences(tags);
    CREATE INDEX IF NOT EXISTS idx_exp_tool ON experiences(user_id, tool_name);
    CREATE INDEX IF NOT EXISTS idx_exp_created ON experiences(created_at DESC);
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.environ.get("DATABASE_URL", "")
        # 如果 DATABASE_URL 是 postgresql:// 开头，忽略并回退到默认
        if not self._db_path or self._db_path.startswith("postgresql"):
            self._db_path = str(Path("./data/context_os.db"))
        self._conn: Optional[aiosqlite.Connection] = None
        logger.info("SQLiteStore initialized: db_path=%s", self._db_path)

    # ── 连接管理 ────────────────────────────────────────────────

    async def connect(self) -> None:
        """初始化数据库连接并建表。"""
        if self._conn:
            logger.debug("Already connected to SQLite")
            return

        try:
            db_dir = Path(self._db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row

            # 启用 WAL 模式提升并发性能
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")

            # 执行建表 DDL（使用 executescript 避免 ; 分割问题）
            await self._conn.executescript(self._DDL)
            await self._conn.commit()

            logger.info("SQLite database initialized: %s", self._db_path)

        except Exception as e:
            self._conn = None
            logger.error("Failed to connect to SQLite: %s", e)
            raise MemoryError(f"SQLite connection failed: {e}") from e

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SQLite connection closed")

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

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
            id: 记忆 ID。
            type: 记忆类型。
            content: 记忆内容。
            session_id: 关联 Session ID。
            user_id: 用户 ID。
            embedding: 可选的向量嵌入。
            metadata: 附加元数据。
            ttl_seconds: 生存时间（秒）。

        Returns:
            记忆 ID。
        """
        expires_at = None
        if ttl_seconds:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

        if not self._conn:
            return await self._fallback_save(id, type, content, session_id, user_id, metadata)

        embedding_json = json.dumps(embedding) if embedding else None

        await self._conn.execute(
            """INSERT INTO memories (id, type, content, embedding, session_id, user_id, metadata, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   content=excluded.content,
                   embedding=excluded.embedding,
                   metadata=excluded.metadata,
                   access_count=0,
                   relevance_score=0""",
            (id, type, content, embedding_json, session_id, user_id,
             json.dumps(metadata or {}), expires_at),
        )
        await self._conn.commit()
        logger.debug("Memory saved: id=%s, type=%s, session=%s", id, type, session_id)
        return id

    async def get_memory(self, id: str) -> Optional[dict[str, Any]]:
        """根据 ID 获取单条记忆。"""
        if not self._conn:
            return self._fallback_get(id)

        cursor = await self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (id,),
        )
        row = await cursor.fetchone()
        if row:
            await self._conn.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?", (id,),
            )
            await self._conn.commit()
            return self._row_to_dict(row)
        return None

    async def query_memories(
        self,
        type: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query_text: Optional[str] = None,
        embedding: Optional[list[float]] = None,  # 预留，实际向量检索由 LongTermMemory.retrieve() 完成
        top_k: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """多条件查询记忆。"""
        if not self._conn:
            return self._fallback_query(type, top_k)

        conditions: list[str] = []
        params: list[Any] = []

        if type:
            conditions.append("type = ?")
            params.append(type)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if query_text:
            # 转义 LIKE 通配符 % 和 _，避免意外的模糊匹配
            escaped_text = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped_text}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        # 过滤已过期记忆
        where += " AND (expires_at IS NULL OR expires_at > datetime('now'))"

        query = (
            f"SELECT * FROM memories WHERE {where} "
            f"ORDER BY timestamp DESC, relevance_score DESC "
            f"LIMIT ? OFFSET ?"
        )
        params.extend([top_k, offset])

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        results = [self._row_to_dict(r) for r in rows]

        # 批量更新访问计数
        if results:
            ids = [r["id"] for r in results]
            placeholders = ",".join("?" for _ in ids)
            await self._conn.execute(
                f"UPDATE memories SET access_count = access_count + 1 WHERE id IN ({placeholders})",
                ids,
            )
            await self._conn.commit()

        logger.debug("Memory query returned %d results", len(results))
        return results

    async def delete_memory(self, id: str) -> bool:
        """删除一条记忆。"""
        if not self._conn:
            return self._fallback_delete(id)

        cursor = await self._conn.execute("DELETE FROM memories WHERE id = ?", (id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def clear_all_memories(self) -> None:
        """清空所有记忆（用于 benchmark 实例间隔离）。"""
        if self._conn:
            await self._conn.execute("DELETE FROM memories")
            await self._conn.commit()
        # 清理文件系统降级存储
        if self._FALLBACK_DIR.exists():
            for path in self._FALLBACK_DIR.glob("*.json"):
                try:
                    path.unlink()
                except OSError:
                    pass
        logger.info("All memories cleared")

    async def cleanup_expired(self) -> int:
        """清理所有已过期的记忆。"""
        if not self._conn:
            return 0

        cursor = await self._conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < datetime('now')",
        )
        await self._conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info("Cleaned up %d expired memories", count)
        return count

    # ── 通用 execute / query（供子 Memory 类型使用）──────────────

    async def execute(self, sql: str, params: Optional[list] = None) -> Any:
        """执行一条写操作 SQL（INSERT/UPDATE/DELETE），自动提交。

        Args:
            sql: SQL 语句。
            params: 参数列表。

        Returns:
            aiosqlite Cursor 对象（可检查 rowcount）。
        """
        if not self._conn:
            raise MemoryError("Store not connected – call connect() first")
        cursor = await self._conn.execute(sql, params or [])
        await self._conn.commit()
        return cursor

    async def query(self, sql: str, params: Optional[list] = None) -> list[dict[str, Any]]:
        """执行一条 SELECT 查询，返回所有行为 dict 列表。

        Args:
            sql: SELECT 语句。
            params: 参数列表。

        Returns:
            查询结果行列表，每行为 dict。
        """
        if not self._conn:
            logger.warning("Store not connected, returning empty query result")
            return []
        cursor = await self._conn.execute(sql, params or [])
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── 语义记忆（知识图谱） ──────────────────────────────────

    async def save_concept(
        self,
        name: str,
        attributes: Optional[dict] = None,
        embedding: Optional[list[float]] = None,
        confidence: float = 1.0,
        user_id: str = "anonymous",
    ) -> str:
        """保存或更新一个概念节点。"""
        id = uuid.uuid4().hex
        if not self._conn:
            await self._fallback_save(id, "semantic", name, None, user_id, attributes)
            return id

        embedding_json = json.dumps(embedding) if embedding else None

        await self._conn.execute(
            """INSERT INTO concepts (id, name, attributes, embedding, confidence, user_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   attributes=excluded.attributes,
                   embedding=CASE WHEN excluded.embedding IS NOT NULL THEN excluded.embedding ELSE concepts.embedding END,
                   confidence=excluded.confidence,
                   updated_at=datetime('now')""",
            (id, name, json.dumps(attributes or {}), embedding_json, confidence, user_id),
        )
        await self._conn.commit()
        logger.debug("Concept saved: name=%s, confidence=%.2f", name, confidence)
        return id

    async def save_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> str:
        """保存概念间的关系。"""
        if not self._conn:
            logger.debug("Relation fallback (no SQLite): %s --[%s]--> %s", source_name, relation_type, target_name)
            return uuid.uuid4().hex

        cursor = await self._conn.execute(
            "SELECT id, name FROM concepts WHERE name IN (?, ?)",
            (source_name, target_name),
        )
        rows = await cursor.fetchall()
        name_to_id = {r["name"]: r["id"] for r in rows}

        if source_name not in name_to_id or target_name not in name_to_id:
            missing = [n for n in [source_name, target_name] if n not in name_to_id]
            logger.warning("Cannot create relation: concepts not found: %s", missing)
            return ""

        id = uuid.uuid4().hex
        await self._conn.execute(
            """INSERT INTO concept_relations (id, source_id, target_id, relation_type, weight)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                   weight=excluded.weight""",
            (id, name_to_id[source_name], name_to_id[target_name], relation_type, weight),
        )
        await self._conn.commit()
        logger.debug("Relation saved: %s --[%s]--> %s", source_name, relation_type, target_name)
        return id

    async def query_graph(
        self,
        concept_name: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """查询知识图谱子图（BFS 遍历）。"""
        if not self._conn:
            return {"nodes": [], "edges": []}

        cursor = await self._conn.execute(
            "SELECT * FROM concepts WHERE name = ?", (concept_name,),
        )
        start = await cursor.fetchone()
        if not start:
            return {"nodes": [], "edges": []}

        nodes: dict[str, dict] = {start["id"]: self._row_to_dict(start)}
        edges: list[dict] = []
        visited = {start["id"]}
        current_level = {start["id"]}

        for _ in range(depth):
            if not current_level:
                break

            placeholders = ",".join("?" for _ in current_level)
            cursor = await self._conn.execute(
                f"""SELECT cr.*, cs.name AS source_name, ct.name AS target_name
                    FROM concept_relations cr
                    JOIN concepts cs ON cr.source_id = cs.id
                    JOIN concepts ct ON cr.target_id = ct.id
                    WHERE cr.source_id IN ({placeholders})""",
                list(current_level),
            )
            rows = await cursor.fetchall()

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
                    t_cursor = await self._conn.execute(
                        "SELECT * FROM concepts WHERE id = ?", (r["target_id"],),
                    )
                    t_row = await t_cursor.fetchone()
                    if t_row:
                        nodes[t_row["id"]] = self._row_to_dict(t_row)

            current_level = next_level

        return {"nodes": list(nodes.values()), "edges": edges}

    # ── Experience 统一记忆 ──────────────────────────────────

    async def save_experience(
        self,
        experience_type: str,
        user_id: str = "anonymous",
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        # episode
        scene: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        feedback: Optional[str] = None,
        # reflection
        task_type: Optional[str] = None,
        root_cause: Optional[str] = None,
        lesson: Optional[str] = None,
        preventive_action: Optional[str] = None,
        # procedure
        proc_name: Optional[str] = None,
        steps_json: Optional[str] = None,
        total_count: int = 0,
        proc_success_count: int = 0,
        last_used: Optional[str] = None,
        # tool_usage
        tool_name: Optional[str] = None,
        tool_success: Optional[int] = None,
        error_type: Optional[str] = None,
        duration_ms: int = 0,
        scenario: Optional[str] = None,
        input_preview: Optional[str] = None,
        output_preview: Optional[str] = None,
        exp_id: Optional[str] = None,
    ) -> str:
        """保存一条统一体验记录。

        Args:
            experience_type: 类型: 'episode' | 'reflection' | 'procedure' | 'tool_usage'.
            user_id: 用户 ID。
            tags: 标签列表。
            metadata: 附加元数据。
            （以下为各子类型特有字段，按需传入）
            exp_id: 可选，指定 ID（更新时使用）。

        Returns:
            记录 ID。
        """
        eid = exp_id or uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat()

        if not self._conn:
            await self._fallback_save(
                eid, f"exp:{experience_type}",
                f"experience({experience_type})", None, user_id,
                {"tags": tags, "metadata": metadata},
            )
            return eid

        await self._conn.execute(
            """INSERT INTO experiences (
                id, user_id, experience_type,
                tags, metadata, created_at, updated_at,
                scene, action, result, feedback,
                task_type, root_cause, lesson, preventive_action,
                proc_name, steps, total_count, proc_success_count, last_used,
                tool_name, tool_success, error_type, duration_ms, scenario,
                input_preview, output_preview
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?
            )""",
            (
                eid, user_id, experience_type,
                json.dumps(tags or []), json.dumps(metadata or {}),
                timestamp, timestamp,
                scene, action, result, feedback,
                task_type, root_cause, lesson, preventive_action,
                proc_name, steps_json, total_count, proc_success_count, last_used,
                tool_name, tool_success, error_type, duration_ms, scenario,
                input_preview, output_preview,
            ),
        )
        await self._conn.commit()
        logger.debug("Experience saved: id=%s, type=%s", eid, experience_type)
        return eid

    async def query_experiences(
        self,
        experience_type: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        tool_name: Optional[str] = None,
        scenario_query: Optional[str] = None,
        scene_query: Optional[str] = None,
        top_k: int = 20,
        offset: int = 0,
        created_after: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """查询体验记录。

        Args:
            experience_type: 按类型筛选。
            user_id: 按用户筛选。
            tags: 按标签筛选（OR 匹配）。
            tool_name: 按工具名筛选（仅 tool_usage）。
            scenario_query: 按场景关键词 LIKE 匹配（tool_usage）。
            scene_query: 按 scene 关键词 LIKE 匹配（episode）。
            top_k: 返回上限。
            offset: 偏移量。
            created_after: 只返回此时间之后的记录（ISO 8601）。

        Returns:
            体验记录字典列表。
        """
        if not self._conn:
            return self._fallback_query(f"exp:{experience_type}" if experience_type else None, top_k)

        conditions: list[str] = []
        params: list[Any] = []

        if experience_type:
            conditions.append("experience_type = ?")
            params.append(experience_type)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if tags:
            tag_conditions = " OR ".join("tags LIKE ?" for _ in tags)
            conditions.append(f"({tag_conditions})")
            params.extend([f"%{t}%" for t in tags])
        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)
        if scenario_query:
            conditions.append("scenario LIKE ?")
            params.append(f"%{scenario_query}%")
        if scene_query:
            conditions.append("scene LIKE ?")
            params.append(f"%{scene_query}%")
        if created_after:
            conditions.append("created_at > ?")
            params.append(created_after)

        where = " AND ".join(conditions) if conditions else "1=1"

        cursor = await self._conn.execute(
            f"SELECT * FROM experiences WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, top_k, offset],
        )
        rows = await cursor.fetchall()
        results = [self._row_to_dict(r) for r in rows]
        logger.debug("Experience query: type=%s, results=%d", experience_type, len(results))
        return results

    async def get_tool_stats(
        self,
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """实时聚合工具使用统计。

        从 experiences 表中 GROUP BY tool_name 计算：
        total_calls, success_calls, avg_duration_ms, last_used。

        Args:
            user_id: 按用户筛选。
            tool_name: 按工具名筛选。

        Returns:
            [{tool_name, user_id, total_calls, success_calls, avg_duration_ms, last_used}, ...]。
        """
        if not self._conn:
            return []

        conditions: list[str] = ["experience_type = 'tool_usage'"]
        params: list[Any] = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)

        where = " AND ".join(conditions)

        cursor = await self._conn.execute(
            f"""SELECT
                    tool_name AS tool_name,
                    user_id,
                    COUNT(*) AS total_calls,
                    SUM(CASE WHEN tool_success = 1 THEN 1 ELSE 0 END) AS success_calls,
                    AVG(duration_ms) AS avg_duration_ms,
                    MAX(created_at) AS last_used
                FROM experiences
                WHERE {where}
                GROUP BY tool_name, user_id
                ORDER BY total_calls DESC""",
            params,
        )
        rows = await cursor.fetchall()
        results = [dict(r) for r in rows]

        # 格式化 avg_duration_ms
        for r in results:
            if r.get("avg_duration_ms") is not None:
                r["avg_duration_ms"] = round(r["avg_duration_ms"], 1)

        logger.debug("Tool stats: %d tools aggregated", len(results))
        return results

    # ── 辅助 ────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        """将 aiosqlite.Row 转为普通 dict。"""
        result = dict(row)
        # 反序列化 JSON 字段
        for key in ("metadata", "attributes", "embedding", "related_files", "tags", "steps"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    # ── JSON 文件降级存储 ──────────────────────────────────────

    _FALLBACK_DIR = Path("./data/memory_fallback")

    async def _fallback_save(
        self, id: str, type: str, content: str,
        session_id: Optional[str], user_id: str,
        metadata: Optional[dict],
    ) -> str:
        """无 SQLite 时的 JSON 文件降级存储。"""
        import asyncio

        self._FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        path = self._FALLBACK_DIR / f"{id}.json"

        record = {
            "id": id,
            "type": type,
            "content": content,
            "session_id": session_id,
            "user_id": user_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        def _write():
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False))

        await asyncio.to_thread(_write)
        logger.debug("Fallback saved: %s", path)
        return id

    def _fallback_get(self, id: str) -> Optional[dict]:
        """获取降级存储的单条记录。"""
        path = self._FALLBACK_DIR / f"{id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _fallback_query(self, type: Optional[str], top_k: int) -> list[dict]:
        """查询降级存储。"""
        results = []
        for path in sorted(self._FALLBACK_DIR.glob("*.json"), reverse=True)[:top_k]:
            record = json.loads(path.read_text(encoding="utf-8"))
            if type and record.get("type") != type:
                continue
            results.append(record)
        return results

    def _fallback_delete(self, id: str) -> bool:
        """删除降级存储的记录。"""
        path = self._FALLBACK_DIR / f"{id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
