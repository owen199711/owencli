"""MaintenanceWorker 测试（Phase 8）。

覆盖:
    - MaintenanceWorker start/stop
    - MergeTask 去重
    - ForgetTask 清理
    - DecayTask 衰减
    - ArchiveTask 归档
    - SummarizeTask 摘要
"""

import asyncio
import pytest
from context_os.maintenance.worker import MaintenanceWorker, ScheduleConfig
from context_os.maintenance.merge import MergeTask
from context_os.maintenance.forget import ForgetTask
from context_os.maintenance.decay import DecayTask
from context_os.maintenance.archive import ArchiveTask
from context_os.maintenance.summarizer import SummarizeTask


# ═══════════════════════════════════════════════════════════
# Fake 依赖
# ═══════════════════════════════════════════════════════════

class FakeStore:
    def __init__(self):
        self.memories = []
        self._calls = []
        self.is_connected = True

    async def execute(self, sql, params=None):
        class FakeCursor:
            rowcount = 0
        return FakeCursor()

    async def query(self, sql, params=None):
        return self.memories

    async def query_memories(self, type=None, user_id=None, top_k=10, query_text=None):
        return self.memories

    async def delete_memory(self, id):
        self.memories = [m for m in self.memories if m.get("id") != id]
        return True

    async def save_memory(self, id, type, content, user_id, embedding=None, metadata=None):
        m = {"id": id, "type": type, "content": content, "metadata": metadata or {}}
        self.memories.append(m)
        return id

    async def cleanup_journal(self, older_than_days=30, max_records=10000):
        return 0

    async def cleanup_expired(self):
        return 0

    async def query_experiences(self, top_k=500):
        return []


class FakeLTM:
    def __init__(self, store):
        self.store = store
        self._embedding_provider = None

    def detect_temporal_query(self, text):
        return False

    async def retrieve(self, query, top_k=1, **kw):
        return []

    async def decay_relevance(self, half_life_days=7.0):
        return 0


# ═══════════════════════════════════════════════════════════
# MergeTask
# ═══════════════════════════════════════════════════════════

class TestMergeTask:
    @pytest.mark.asyncio
    async def test_empty_store(self):
        """空存储不报错。"""
        store = FakeStore()
        merge = MergeTask(ltm=FakeLTM(store), store=store)
        result = await merge.run()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_exact_duplicates_removed(self):
        """精确重复内容去重。"""
        store = FakeStore()
        store.memories = [
            {"id": "1", "type": "long_term", "content": "相同内容", "timestamp": "2024-01-01", "access_count": 5, "relevance_score": 0.5, "metadata": {}},
            {"id": "2", "type": "long_term", "content": "相同内容", "timestamp": "2024-01-02", "access_count": 3, "relevance_score": 0.5, "metadata": {}},
        ]
        merge = MergeTask(ltm=FakeLTM(store), store=store)
        result = await merge.run()
        assert result >= 1  # 至少删除了一个重复项

    @pytest.mark.asyncio
    async def test_fact_history_truncation(self):
        """Fact history >10 条时截断。"""
        store = FakeStore()
        history = [{"value": f"v{i}", "version": i} for i in range(15)]
        store.memories = [
            {"id": "1", "type": "long_term", "content": "test", "timestamp": "2024-01-01",
             "access_count": 1, "relevance_score": 0.5,
             "metadata": {"fact_id": "user.name", "history": history}},
        ]
        merge = MergeTask(ltm=FakeLTM(store), store=store)
        result = await merge.run()
        assert result >= 1
        # 验证截断后的 history 长度 ≤ 6
        for m in store.memories:
            meta = m.get("metadata", {})
            if isinstance(meta, str):
                import json
                meta = json.loads(meta)
            h = meta.get("history", [])
            if len(h) > 6:
                assert False, f"history not truncated: {len(h)} items"


# ═══════════════════════════════════════════════════════════
# ForgetTask
# ═══════════════════════════════════════════════════════════

class TestForgetTask:
    @pytest.mark.asyncio
    async def test_empty_store(self):
        """空存储不报错。"""
        store = FakeStore()
        forget = ForgetTask(ltm=FakeLTM(store), store=store)
        result = await forget.run()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_correction_cleanup_no_matches(self):
        """无纠正标记时不影响。"""
        store = FakeStore()
        forget = ForgetTask(ltm=FakeLTM(store), store=store)
        result = await forget._correction_cleanup()
        assert result == 0


# ═══════════════════════════════════════════════════════════
# DecayTask
# ═══════════════════════════════════════════════════════════

class TestDecayTask:
    @pytest.mark.asyncio
    async def test_empty_store(self):
        """空存储不报错。"""
        store = FakeStore()
        decay = DecayTask(ltm=FakeLTM(store), store=store)
        result = await decay.run()
        assert result >= 0


# ═══════════════════════════════════════════════════════════
# ArchiveTask
# ═══════════════════════════════════════════════════════════

class TestArchiveTask:
    @pytest.mark.asyncio
    async def test_empty_store(self):
        """空存储不报错。"""
        store = FakeStore()
        archive = ArchiveTask(ltm=FakeLTM(store), store=store)
        result = await archive.run()
        assert result >= 0


# ═══════════════════════════════════════════════════════════
# SummarizeTask
# ═══════════════════════════════════════════════════════════

class TestSummarizeTask:
    @pytest.mark.asyncio
    async def test_empty_store(self):
        """空存储不报错。"""
        store = FakeStore()
        summarize = SummarizeTask(ltm=FakeLTM(store), store=store)
        result = await summarize.run()
        assert result >= 0


# ═══════════════════════════════════════════════════════════
# MaintenanceWorker
# ═══════════════════════════════════════════════════════════

class TestMaintenanceWorker:
    def test_create_worker(self):
        """创建 MaintenanceWorker 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        assert worker is not None
        assert worker._schedule.merge_interval == 3600

    def test_custom_schedule(self):
        """自定义调度配置。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        schedule = ScheduleConfig(
            merge_interval=1800, forget_interval=43200,
            decay_interval=10800, archive_interval=302400,
            summarize_interval=43200, journal_cleanup_interval=43200,
        )
        worker = MaintenanceWorker(ltm=ltm, store=store, schedule=schedule)
        assert worker._schedule.merge_interval == 1800

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """start/stop 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        worker.start()
        assert worker._running is True
        # 将 running 设为 False，然后等待 worker loop 退出
        worker._running = False
        await asyncio.sleep(0.1)
        if worker._task:
            worker._task.cancel()
            try:
                await worker._task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_manual_run_merge(self):
        """手动触发 merge 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_merge()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_manual_run_forget(self):
        """手动触发 forget 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_forget()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_manual_run_decay(self):
        """手动触发 decay 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_decay()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_manual_run_archive(self):
        """手动触发 archive 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_archive()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_manual_run_summarize(self):
        """手动触发 summarize 不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_summarize()
        assert result >= 0

    @pytest.mark.asyncio
    async def test_manual_run_journal_cleanup(self):
        """手动触发 journal 清理不报错。"""
        store = FakeStore()
        ltm = FakeLTM(store)
        worker = MaintenanceWorker(ltm=ltm, store=store)
        result = await worker.run_journal_cleanup()
        assert result >= 0
