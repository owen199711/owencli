"""测试 SessionMemory — 会话记忆及候选缓冲区。"""

import pytest
from context_os.memory.store import SQLiteStore
from context_os.memory.session_memory import SessionMemory


@pytest.fixture
async def store():
    """创建内存 SQLite 存储。"""
    s = SQLiteStore(db_path=":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def session(store):
    """创建 SessionMemory 实例。"""
    return SessionMemory(session_id="test_session", store=store, ttl_hours=1)


class TestSessionMemoryBasic:
    """基本 CRUD 测试。"""

    async def test_add_and_get_all(self, session):
        mid = await session.add("测试内容", metadata={"key": "val"})
        assert mid
        items = await session.get_all()
        assert len(items) >= 1

    async def test_add_preference(self, session):
        await session.add_preference("language", "python")
        prefs = await session.get_preferences()
        assert prefs.get("language") == "python"

    async def test_add_task_completion(self, session):
        await session.add_task_completion("test_task", "done")
        tasks = await session.get_tasks()
        assert len(tasks) >= 1
        assert tasks[0]["task"] == "test_task"

    async def test_clear(self, session):
        await session.add("item1")
        await session.add("item2")
        items = await session.get_all()
        assert len(items) >= 2
        await session.clear()
        items = await session.get_all()
        assert len(items) == 0


class TestPendingCandidateBuffer:
    """候选缓冲区测试（Phase 3.6）。"""

    async def test_add_pending_candidate(self, session):
        cid = await session.add_pending_candidate(
            content="我叫小明",
            entities={"person": "小明", "action": "name_declaration"},
            turn_number=1,
        )
        assert cid
        assert len(cid) == 32

    async def test_query_pending(self, session):
        await session.add_pending_candidate("候选1", turn_number=1)
        await session.add_pending_candidate("候选2", turn_number=2)
        await session.add("普通记忆", metadata={"category": "general"})

        pending = await session.query_pending()
        assert len(pending) == 2

    async def test_query_pending_with_query(self, session):
        await session.add_pending_candidate("我叫小明", turn_number=1)
        await session.add_pending_candidate("我住在北京", turn_number=2)

        # 按内容检索
        pending = await session.query_pending(query="北京")
        assert len(pending) == 1
        assert "北京" in pending[0]["content"]

    async def test_query_pending_filtered_by_status(self, session):
        """只有 status=pending 的记录才被查询到。"""
        cid = await session.add_pending_candidate("候选1", turn_number=1)
        # 更新为 written 状态
        await session.update_pending_status(cid, "written")

        pending = await session.query_pending()
        assert len(pending) == 0

    async def test_update_pending_status(self, session):
        cid = await session.add_pending_candidate("候选", turn_number=1)
        ok = await session.update_pending_status(cid, "written")
        assert ok

        # 再次确认状态
        pending = await session.query_pending()
        assert len(pending) == 0

    async def test_update_pending_status_nonexistent(self, session):
        ok = await session.update_pending_status("nonexistent_id", "written")
        assert not ok

    async def test_get_pending_count(self, session):
        # 初始 0
        count = await session.get_pending_count()
        assert count == 0

        await session.add_pending_candidate("c1", turn_number=1)
        await session.add_pending_candidate("c2", turn_number=2)
        count = await session.get_pending_count()
        assert count == 2

        # 添加一个非候选记录
        await session.add("普通记录", metadata={"category": "general"})
        count = await session.get_pending_count()
        assert count == 2  # 不受影响

    async def test_get_pending_count_mixed_status(self, session):
        """已处理和未处理的混合统计。"""
        c1 = await session.add_pending_candidate("c1", turn_number=1)
        c2 = await session.add_pending_candidate("c2", turn_number=2)
        await session.add_pending_candidate("c3", turn_number=3)

        # 标记第一个为 written
        await session.update_pending_status(c1, "written")

        count = await session.get_pending_count()
        assert count == 2  # c2, c3 仍是 pending

    async def test_pending_metadata_integrity(self, session):
        cid = await session.add_pending_candidate(
            content="我在北京",
            entities={"person": "user", "location": "北京"},
            turn_number=3,
        )
        pending = await session.query_pending()
        assert len(pending) == 1
        meta = pending[0]["metadata"]
        assert meta["category"] == "write_candidate"
        assert meta["status"] == "pending"
        assert meta["turn_number"] == 3
        assert meta.get("location") == "北京"
