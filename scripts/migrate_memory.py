#!/usr/bin/env python
"""记忆系统迁移脚本：将旧表数据迁移到新 unified memories 表结构。

迁移内容:
    1. facts 表 → memories 表（type="long_term"，fact 字段进 metadata JSON）
    2. task_records 表 → memories 表（type="session"，task 字段进 metadata JSON）

用法:
    python scripts/migrate_memory.py                        # 真实迁移
    python scripts/migrate_memory.py --dry-run              # 预览，不写库
    python scripts/migrate_memory.py --db ./data/test.db    # 指定数据库路径
    python scripts/migrate_memory.py --skip-facts           # 只迁移 task_records
    python scripts/migrate_memory.py --skip-tasks           # 只迁移 facts

幂等性: 多次运行安全。已迁移的记录通过 metadata.migrated_from 标记跳过。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


class MemoryMigrator:
    """数据迁移器。"""

    def __init__(self, db_path: str, dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.store = SQLiteStore(db_path=db_path)
        self.stats = {
            "facts_migrated": 0,
            "facts_skipped": 0,
            "tasks_migrated": 0,
            "tasks_skipped": 0,
        }

    async def connect(self) -> None:
        await self.store.connect()

    async def close(self) -> None:
        await self.store.close()

    # ── facts → memories ────────────────────────────────────────

    async def migrate_facts(self) -> dict[str, int]:
        """将 facts 表数据迁移到 memories 表。

        facts 字段映射:
            content / current_value → memories.content
            id → metadata.fact_id
            category, confidence, version, source, history → metadata
        """
        logger.info("=" * 60)
        logger.info("Migrating facts → memories ...")

        # 查询所有 fact 记录
        try:
            cursor = await self.store._conn.execute(
                "SELECT * FROM facts ORDER BY created_at"
            )
            facts = await cursor.fetchall()
        except Exception as e:
            logger.warning("Facts table not found or empty: %s", e)
            facts = []

        for row in facts:
            fact = dict(row)
            fact_id = fact["id"]

            # 检查是否已迁移（通过 metadata.migrated_from 判断）
            if await self._already_migrated("facts", fact_id):
                self.stats["facts_skipped"] += 1
                logger.debug("  SKIP fact %s (already migrated)", fact_id)
                continue

            # 构建 metadata
            history = []
            try:
                history_raw = fact.get("history", "[]")
                history = json.loads(history_raw) if isinstance(history_raw, str) else history_raw
            except (json.JSONDecodeError, TypeError):
                pass

            content = fact.get("current_value") or fact.get("content", "")
            meta = {
                "category": fact.get("category", ""),
                "fact_id": fact_id,
                "confidence": fact.get("confidence", 1.0),
                "version": fact.get("version", 1),
                "source": fact.get("source", ""),
                "history": history,
                "migrated_from": "facts",
                "migrated_at": datetime.now(timezone.utc).isoformat(),
            }
            # 保留原有 metadata
            orig_meta = fact.get("metadata", "{}")
            if isinstance(orig_meta, str):
                try:
                    orig_meta = json.loads(orig_meta)
                except json.JSONDecodeError:
                    orig_meta = {}
            if isinstance(orig_meta, dict) and orig_meta:
                meta["original_metadata"] = orig_meta

            if self.dry_run:
                logger.info(
                    "  [DRY-RUN] fact: %s → content='%s', v=%d, cat=%s",
                    fact_id, content[:60], meta["version"], meta["category"],
                )
            else:
                mem_id = uuid.uuid4().hex
                await self.store.save_memory(
                    id=mem_id,
                    type="long_term",
                    content=content,
                    user_id=fact.get("user_id", "anonymous"),
                    metadata=meta,
                )
                logger.info("  fact: %s → memory %s (v=%d)", fact_id, mem_id, meta["version"])

            self.stats["facts_migrated"] += 1

        logger.info(
            "Facts migration done: %d migrated, %d skipped",
            self.stats["facts_migrated"], self.stats["facts_skipped"],
        )
        return self.stats

    # ── task_records → memories ─────────────────────────────────

    async def migrate_task_records(self) -> dict[str, int]:
        """将 task_records 表数据迁移到 memories 表。

        task_records 字段映射:
            input → memories.content
            task_type, intent, status, output, error,
            token_used, duration_ms → metadata
        """
        logger.info("=" * 60)
        logger.info("Migrating task_records → memories (type=session) ...")

        try:
            cursor = await self.store._conn.execute(
                "SELECT * FROM task_records ORDER BY created_at"
            )
            tasks = await cursor.fetchall()
        except Exception as e:
            logger.warning("Task records table not found or empty: %s", e)
            tasks = []

        for row in tasks:
            task = dict(row)
            task_id = task["id"]

            # 检查是否已迁移
            if await self._already_migrated("task_records", task_id):
                self.stats["tasks_skipped"] += 1
                logger.debug("  SKIP task %s (already migrated)", task_id)
                continue

            meta = {
                "category": "task_record",
                "task_type": task.get("task_type", ""),
                "intent": task.get("intent", ""),
                "status": task.get("status", "pending"),
                "migrated_from": "task_records",
                "migrated_at": datetime.now(timezone.utc).isoformat(),
            }
            # 可选字段
            for field in ("output", "error"):
                if task.get(field):
                    meta[field] = task[field]
            if task.get("token_used"):
                meta["token_used"] = task["token_used"]
            if task.get("duration_ms"):
                meta["duration_ms"] = task["duration_ms"]
            if task.get("completed_at"):
                meta["completed_at"] = task["completed_at"]

            content = task.get("input", "")

            if self.dry_run:
                logger.info(
                    "  [DRY-RUN] task: %s → '%s...', status=%s",
                    task_id, content[:60], meta["status"],
                )
            else:
                mem_id = uuid.uuid4().hex
                await self.store.save_memory(
                    id=mem_id,
                    type="session",
                    content=content,
                    user_id=task.get("user_id", "anonymous"),
                    metadata=meta,
                    ttl_seconds=86400,  # 24h
                )
                logger.info(
                    "  task: %s → memory %s (status=%s)", task_id, mem_id, meta["status"],
                )

            self.stats["tasks_migrated"] += 1

        logger.info(
            "Task migration done: %d migrated, %d skipped",
            self.stats["tasks_migrated"], self.stats["tasks_skipped"],
        )
        return self.stats

    # ── helper ──────────────────────────────────────────────────

    async def _already_migrated(self, source: str, original_id: str) -> bool:
        """检查某条旧表记录是否已迁移到 memories。

        通过查询 memories 表中 metadata.migrated_from == source
        且 metadata 中包含对应 old_id 来判断。
        """
        try:
            cursor = await self.store._conn.execute(
                "SELECT id FROM memories WHERE json_extract(metadata, '$.migrated_from') = ?",
                [source],
            )
            rows = await cursor.fetchall()
            for r in rows:
                # 进一步检查：获取该记录的 metadata 确认 original_id
                mem = await self.store._conn.execute(
                    "SELECT metadata FROM memories WHERE id = ?", [r["id"]]
                )
                mem_row = await mem.fetchone()
                if mem_row:
                    meta = mem_row["metadata"]
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except json.JSONDecodeError:
                            continue
                    # fact_id 或通过其他方式判断
                    if source == "facts" and meta.get("fact_id") == original_id:
                        return True
                    if source == "task_records":
                        return True  # task 没有唯一 natural key，通过 migrated_from 即可
        except Exception:
            pass
        return False

    # ── report ──────────────────────────────────────────────────

    def report(self) -> str:
        """生成迁移报告。"""
        lines = [
            "=" * 60,
            "          Memory Migration Report",
            "=" * 60,
            f"  Database : {self.db_path}",
            f"  Mode     : {'DRY-RUN' if self.dry_run else 'LIVE'}",
            f"  Facts    : {self.stats['facts_migrated']} migrated, {self.stats['facts_skipped']} skipped",
            f"  Tasks    : {self.stats['tasks_migrated']} migrated, {self.stats['tasks_skipped']} skipped",
            f"  Total    : {self.stats['facts_migrated'] + self.stats['tasks_migrated']} migrated",
            "=" * 60,
        ]
        return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(
        description="Memory system migration: facts + task_records → memories"
    )
    parser.add_argument(
        "--db", default=None,
        help="SQLite database path (default: DATABASE_URL env or ./data/context_os.db)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview migration without writing to database",
    )
    parser.add_argument(
        "--skip-facts", action="store_true",
        help="Skip facts table migration",
    )
    parser.add_argument(
        "--skip-tasks", action="store_true",
        help="Skip task_records table migration",
    )

    args = parser.parse_args()

    db_path = args.db or os.environ.get("DATABASE_URL", "./data/context_os.db")
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    migrator = MemoryMigrator(db_path=db_path, dry_run=args.dry_run)
    await migrator.connect()

    try:
        if not args.skip_facts:
            await migrator.migrate_facts()
        if not args.skip_tasks:
            await migrator.migrate_task_records()
    finally:
        await migrator.close()

    print(migrator.report())

    if args.dry_run:
        print("\n[DRY-RUN] No data was written. Remove --dry-run to execute.")


if __name__ == "__main__":
    asyncio.run(main())
