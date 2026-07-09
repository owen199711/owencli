"""ToolExperienceMemory — 工具调用经验与成功率追踪。

参考 Java: com.owencli.contextos.memory.ToolExperienceMemory
"""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from context_os.memory.store import SQLiteStore

class ToolExperienceMemory:
    def __init__(self, store: SQLiteStore, user_id="anonymous"):
        self.store=store; self.user_id=user_id
        self.store.execute("""CREATE TABLE IF NOT EXISTS tool_experience (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tool_name TEXT NOT NULL,
            success INTEGER NOT NULL, error_type TEXT, duration_ms INTEGER DEFAULT 0,
            scenario TEXT, input_preview TEXT, output_preview TEXT,
            created_at TEXT NOT NULL)""")
        self.store.execute("""CREATE TABLE IF NOT EXISTS tool_stats (
            tool_name TEXT, user_id TEXT, total_calls INTEGER DEFAULT 0,
            success_calls INTEGER DEFAULT 0, avg_duration_ms REAL DEFAULT 0,
            PRIMARY KEY (tool_name, user_id))""")

    async def record(self, tool_name: str, success: bool, duration_ms=0,
                     error_type=None, scenario=None, input_preview=None) -> str:
        now = datetime.now(timezone.utc).isoformat()
        eid = uuid.uuid4().hex[:12]
        self.store.execute("INSERT INTO tool_experience (id,user_id,tool_name,success,error_type,duration_ms,scenario,input_preview,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            [eid, self.user_id, tool_name, 1 if success else 0, error_type, duration_ms, scenario, input_preview, now])
        # Update stats
        existing = self.store.query("SELECT * FROM tool_stats WHERE tool_name=? AND user_id=?", [tool_name, self.user_id])
        if existing:
            r = dict(existing[0])
            new_total = r["total_calls"] + 1
            new_success = r["success_calls"] + (1 if success else 0)
            new_avg = (r["avg_duration_ms"] * r["total_calls"] + duration_ms) / new_total
            self.store.execute("UPDATE tool_stats SET total_calls=?,success_calls=?,avg_duration_ms=? WHERE tool_name=? AND user_id=?",
                [new_total, new_success, new_avg, tool_name, self.user_id])
        else:
            self.store.execute("INSERT INTO tool_stats (tool_name,user_id,total_calls,success_calls,avg_duration_ms) VALUES (?,?,?,?,?)",
                [tool_name, self.user_id, 1, 1 if success else 0, duration_ms])
        return eid

    async def get_best_tool(self, scenario: str = None) -> str:
        if scenario:
            rows = self.store.query("SELECT tool_name, success_calls*1.0/MAX(total_calls,1) as rate FROM tool_stats WHERE user_id=? ORDER BY rate DESC LIMIT 1", [self.user_id])
        else:
            rows = self.store.query("SELECT tool_name, success_calls*1.0/MAX(total_calls,1) as rate FROM tool_stats WHERE user_id=? ORDER BY rate DESC LIMIT 1", [self.user_id])
        return rows[0][0] if rows else "unknown"

    async def get_stats(self, tool_name: str = None) -> list[dict]:
        if tool_name:
            rows = self.store.query("SELECT * FROM tool_stats WHERE user_id=? AND tool_name=?", [self.user_id, tool_name])
        else:
            rows = self.store.query("SELECT * FROM tool_stats WHERE user_id=? ORDER BY total_calls DESC LIMIT 20", [self.user_id])
        return [dict(r) for r in rows]
