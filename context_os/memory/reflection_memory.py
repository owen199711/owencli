"""ReflectionMemory — Agent 自我反思与经验教训。

参考 Java: com.owencli.contextos.memory.ReflectionMemory
存储结构：reflections 表
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from context_os.memory.store import SQLiteStore


class ReflectionMemory:
    """Agent 自省记忆 — 记录每次交互的反思结果。

    每次 Reflection 包含：
    - root_cause: 失败根因
    - lesson_learned: 经验教训
    - preventive_action: 预防措施
    - success: 是否成功
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.store.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                task_type TEXT,
                success INTEGER NOT NULL DEFAULT 1,
                root_cause TEXT,
                lesson_learned TEXT,
                preventive_action TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)

    async def save(
        self,
        task_type: str,
        success: bool,
        root_cause: Optional[str] = None,
        lesson_learned: Optional[str] = None,
        preventive_action: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        rid = uuid.uuid4().hex[:12]
        self.store.execute(
            "INSERT INTO reflections (id, user_id, task_type, success, root_cause, "
            "lesson_learned, preventive_action, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rid, self.user_id, task_type, 1 if success else 0,
                root_cause, lesson_learned, preventive_action,
                json.dumps(metadata or {}), datetime.now(timezone.utc).isoformat(),
            ],
        )
        return rid

    async def query(self, limit: int = 20) -> list[dict]:
        rows = self.store.query(
            "SELECT * FROM reflections WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            [self.user_id, limit],
        )
        return [dict(row) for row in rows]

    async def count_failures(self, task_type: Optional[str] = None) -> int:
        if task_type:
            rows = self.store.query(
                "SELECT COUNT(*) as cnt FROM reflections WHERE user_id = ? AND task_type = ? AND success = 0",
                [self.user_id, task_type],
            )
        else:
            rows = self.store.query(
                "SELECT COUNT(*) as cnt FROM reflections WHERE user_id = ? AND success = 0",
                [self.user_id],
            )
        return rows[0][0] if rows else 0
