"""ProceduralMemory — 存储已学习的工作流程与步骤模式。

参考 Java: com.owencli.contextos.memory.ProceduralMemory
存储：procedures 表，含步骤序列、场景标签、成功率
"""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from context_os.memory.store import SQLiteStore

class ProceduralMemory:
    def __init__(self, store: SQLiteStore, user_id="anonymous"):
        self.store=store; self.user_id=user_id
        self.store.execute("""CREATE TABLE IF NOT EXISTS procedures (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT, steps TEXT NOT NULL, tags TEXT,
            success_count INTEGER DEFAULT 0, total_count INTEGER DEFAULT 0,
            last_used TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    async def save(self, name: str, steps: list[dict], description="", tags=None) -> str:
        pid = uuid.uuid4().hex[:12]; now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags or [])
        self.store.execute("INSERT INTO procedures (id,user_id,name,description,steps,tags,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            [pid, self.user_id, name, description, json.dumps(steps), tags_json, now, now])
        return pid

    async def record_usage(self, proc_id: str, success: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if success:
            self.store.execute("UPDATE procedures SET success_count=success_count+1, total_count=total_count+1, last_used=? WHERE id=?", [now, proc_id])
        else:
            self.store.execute("UPDATE procedures SET total_count=total_count+1, last_used=? WHERE id=?", [now, proc_id])

    async def search(self, query: str, limit=10) -> list[dict]:
        like = f"%{query}%"
        rows = self.store.query(
            "SELECT * FROM procedures WHERE user_id=? AND (name LIKE ? OR description LIKE ? OR tags LIKE ?) ORDER BY success_count*1.0/MAX(total_count,1) DESC LIMIT ?",
            [self.user_id, like, like, like, limit])
        return [dict(r) for r in rows]

    async def get_best(self, tag: str = None) -> list[dict]:
        if tag:
            rows = self.store.query(
                "SELECT * FROM procedures WHERE user_id=? AND tags LIKE ? ORDER BY success_count*1.0/MAX(total_count,1) DESC LIMIT 5",
                [self.user_id, f"%{tag}%"])
        else:
            rows = self.store.query(
                "SELECT * FROM procedures WHERE user_id=? ORDER BY success_count*1.0/MAX(total_count,1) DESC LIMIT 5",
                [self.user_id])
        return [dict(r) for r in rows]
