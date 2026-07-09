$root = "d:\code\owencli\context_os"
Write-Host "Creating ReflectionMemory..."
$src = @"
class ReflectionMemory:
    def __init__(self, store, user_id="anonymous"):
        self.store = store; self.user_id = user_id
        self.store.execute("""CREATE TABLE IF NOT EXISTS reflections (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, task_type TEXT,
            success INTEGER NOT NULL DEFAULT 1, root_cause TEXT,
            lesson_learned TEXT, preventive_action TEXT, metadata TEXT,
            created_at TEXT NOT NULL)""")
    async def save(self, task_type, success, root_cause=None, lesson_learned=None,
                   preventive_action=None, metadata=None):
        import uuid, json
        from datetime import datetime, timezone
        rid = uuid.uuid4().hex[:12]
        self.store.execute("INSERT INTO reflections VALUES (?,?,?,?,?,?,?,?,?)",
            [rid, self.user_id, task_type, 1 if success else 0, root_cause,
             lesson_learned, preventive_action, json.dumps(metadata or {}),
             datetime.now(timezone.utc).isoformat()])
        return rid
    async def query(self, limit=20):
        return [dict(r) for r in self.store.query(
            "SELECT * FROM reflections WHERE user_id=? ORDER BY created_at DESC LIMIT ?", [self.user_id, limit])]
    async def count_failures(self, task_type=None):
        if task_type:
            r = self.store.query("SELECT COUNT(*) as c FROM reflections WHERE user_id=? AND task_type=? AND success=0", [self.user_id, task_type])
        else:
            r = self.store.query("SELECT COUNT(*) as c FROM reflections WHERE user_id=? AND success=0", [self.user_id])
        return r[0][0] if r else 0
"@
$header = '"""ReflectionMemory — Agent 自我反思。"""'
$imports = 'from context_os.memory.store import SQLiteStore', 'from typing import Optional'
$full = @"
$header
from __future__ import annotations
$($imports -join "`n")
$src
"@
Set-Content -Path "$root\memory\reflection_memory.py" -Value $full -Encoding UTF8
Write-Host "ReflectionMemory done"
