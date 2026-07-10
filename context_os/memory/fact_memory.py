"""FactMemory — 版本化事实 KV 存储。

表由 SQLiteStore._DDL 统一创建。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class FactRecord:
    """版本化事实记录。"""

    def __init__(
        self,
        id: str = "",
        content: str = "",
        category: str = "",
        confidence: float = 1.0,
        version: int = 1,
        user_id: str = "anonymous",
        source: str = "",
        metadata: Optional[dict] = None,
        created_at: Optional[str] = None,
    ):
        self.id = id
        self.content = content
        self.category = category
        self.confidence = confidence
        self.version = version
        self.user_id = user_id
        self.source = source
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "confidence": self.confidence,
            "version": self.version,
            "user_id": self.user_id,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class FactMemory:
    """版本化事实 KV 存储。

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("FactMemory initialized (user=%s)", user_id)

    @staticmethod
    def _row_to_record(row: dict) -> FactRecord:
        """将查询行转换为 FactRecord。"""
        return FactRecord(
            id=row["id"],
            content=row.get("current_value") or row.get("content", ""),
            category=row["category"],
            confidence=row["confidence"],
            version=row["version"],
            user_id=row["user_id"],
            source=row.get("source", ""),
            metadata=json.loads(row.get("metadata", "{}")),
            created_at=row["created_at"],
        )

    async def set(
        self,
        fact_id: str,
        content: str,
        category: str,
        confidence: float = 1.0,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> FactRecord:
        """设置/更新一条事实（版本递增）。"""
        now = datetime.now(timezone.utc).isoformat()
        existing = await self.store.query(
            "SELECT * FROM facts WHERE id = ?", [fact_id]
        )

        if existing:
            row = existing[0]
            history = json.loads(row.get("history", "[]"))
            history.append({
                "value": row.get("current_value") or row.get("content", ""),
                "version": row["version"],
                "updated_at": now,
            })
            new_version = row["version"] + 1
            await self.store.execute(
                "UPDATE facts SET content = ?, current_value = ?, version = ?, confidence = ?, "
                "metadata = ?, history = ?, updated_at = ? WHERE id = ?",
                [
                    content, content, new_version, confidence,
                    json.dumps(metadata or {}), json.dumps(history), now, fact_id,
                ],
            )
            logger.debug("Fact updated: id=%s, v%d -> v%d", fact_id, row["version"], new_version)
            return FactRecord(
                id=fact_id, content=content, category=category,
                confidence=confidence, version=new_version,
                user_id=self.user_id, source=source, metadata=metadata,
            )

        # 新事实
        await self.store.execute(
            "INSERT INTO facts (id, content, category, confidence, version, "
            "user_id, source, metadata, current_value, history, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                fact_id, content, category, confidence, 1, self.user_id,
                source, json.dumps(metadata or {}), content, json.dumps([]), now, now,
            ],
        )
        logger.info("Fact created: id=%s, category=%s", fact_id, category)
        return FactRecord(
            id=fact_id, content=content, category=category,
            confidence=confidence, version=1,
            user_id=self.user_id, source=source,
            metadata=metadata, created_at=now,
        )

    async def get(self, fact_id: str) -> Optional[FactRecord]:
        """按 ID 获取事实。"""
        rows = await self.store.query(
            "SELECT * FROM facts WHERE id = ?", [fact_id]
        )
        return self._row_to_record(rows[0]) if rows else None

    async def query(self, category: Optional[str] = None, limit: int = 100) -> list[FactRecord]:
        """按类别查询事实。"""
        if category:
            rows = await self.store.query(
                "SELECT * FROM facts WHERE user_id = ? AND category = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                [self.user_id, category, limit],
            )
        else:
            rows = await self.store.query(
                "SELECT * FROM facts WHERE user_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                [self.user_id, limit],
            )
        return [self._row_to_record(r) for r in rows]

    async def delete(self, fact_id: str) -> None:
        """删除一条事实。"""
        await self.store.execute(
            "DELETE FROM facts WHERE id = ?", [fact_id]
        )
        logger.debug("Fact deleted: id=%s", fact_id)
