"""FactMemory — 版本化事实 KV 存储。"""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from context_os.memory.store import SQLiteStore

class FactRecord:
    def __init__(self, id="", content="", category="", confidence=1.0, version=1,
                 user_id="anonymous", source="", metadata=None, created_at=None):
        self.id=id; self.content=content; self.category=category; self.confidence=confidence
        self.version=version; self.user_id=user_id; self.source=source
        self.metadata=metadata or {}; self.created_at=created_at or datetime.now(timezone.utc).isoformat()

class FactMemory:
    def __init__(self, store: SQLiteStore, user_id="anonymous"):
        self.store=store; self.user_id=user_id
        self.store.execute("""CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, version INTEGER NOT NULL DEFAULT 1,
            user_id TEXT NOT NULL, source TEXT, metadata TEXT, current_value TEXT,
            history TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def _row_to_record(self, r):
        d = dict(r)
        return FactRecord(d["id"], d["current_value"] or d["content"], d["category"], d["confidence"],
            d["version"], d["user_id"], d["source"], json.loads(d.get("metadata","{}")), d["created_at"])

    async def set(self, fact_id, content, category, confidence=1.0, source="", metadata=None):
        existing = self.store.query("SELECT * FROM facts WHERE id=?", [fact_id])
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            row = dict(existing[0])
            history = json.loads(row.get("history","[]"))
            history.append({"value":row["current_value"] or row["content"],"version":row["version"],"updated_at":now})
            self.store.execute("UPDATE facts SET content=?,version=version+1,confidence=?,metadata=?,history=?,updated_at=? WHERE id=?", 
                [content, confidence, json.dumps(metadata or {}), json.dumps(history), now, fact_id])
            return FactRecord(fact_id, content, category, confidence, row["version"]+1, self.user_id, source, metadata)
        self.store.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [fact_id, content, category, confidence, 1, self.user_id, source,
             json.dumps(metadata or {}), content, json.dumps([]), now, now])
        return FactRecord(fact_id, content, category, confidence, 1, self.user_id, source, metadata, now)

    async def get(self, fact_id):
        rows = self.store.query("SELECT * FROM facts WHERE id=?", [fact_id])
        return self._row_to_record(rows[0]) if rows else None

    async def query(self, category=None, limit=100):
        if category:
            rows=self.store.query("SELECT * FROM facts WHERE user_id=? AND category=? ORDER BY updated_at DESC LIMIT ?",[self.user_id,category,limit])
        else:
            rows=self.store.query("SELECT * FROM facts WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",[self.user_id,limit])
        return [self._row_to_record(r) for r in rows]

    async def delete(self, fact_id):
        self.store.execute("DELETE FROM facts WHERE id=?", [fact_id])

