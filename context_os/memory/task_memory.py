\"\"\"TaskMemory — 任务执行记录。\"\"\"
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from context_os.memory.store import SQLiteStore

class TaskMemory:
    def __init__(self, store: SQLiteStore, user_id=\"anonymous\"):
        self.store=store; self.user_id=user_id
        self.store.execute(\"\"\"CREATE TABLE IF NOT EXISTS task_records (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, task_type TEXT,
            intent TEXT, status TEXT NOT NULL DEFAULT 'pending',
            input TEXT, output TEXT, error TEXT,
            token_used INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0,
            metadata TEXT, created_at TEXT NOT NULL, completed_at TEXT)\"\"\")

    async def save(self, task_type, intent, input_text):
        tid = uuid.uuid4().hex[:12]
        self.store.execute(\"INSERT INTO task_records (id,user_id,task_type,intent,status,input,created_at) VALUES (?,?,?,?,?,?,?)\",
            [tid, self.user_id, task_type, intent, \"pending\", input_text, datetime.now(timezone.utc).isoformat()])
        return tid

    async def complete(self, task_id, output, token_used=0, duration_ms=0, error=None):
        status = \"failed\" if error else \"completed\"
        self.store.execute(\"UPDATE task_records SET status=?,output=?,error=?,token_used=?,duration_ms=?,completed_at=? WHERE id=?\",
            [status, output, error, token_used, duration_ms, datetime.now(timezone.utc).isoformat(), task_id])

    async def query(self, limit=50):
        return [dict(r) for r in self.store.query(
            \"SELECT * FROM task_records WHERE user_id=? ORDER BY created_at DESC LIMIT ?\", [self.user_id, limit])]
