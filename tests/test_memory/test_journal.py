"""JournalStore 单元测试。

覆盖：
- append 写入 + 事件发布
- query_pending 查询待处理
- mark_processed / mark_discarded 状态更新
- get_pending_count 数量查询
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_os.events.bus import EventBus
from context_os.memory.journal import JournalStore


@pytest.fixture
def mock_store():
    """返回 mock 的 SQLiteStore。"""
    store = MagicMock()
    store.save_journal_entry = AsyncMock(return_value="j-001")
    store.query_journal_pending = AsyncMock(return_value=[])
    store.update_journal_status = AsyncMock()
    return store


@pytest.fixture
def event_bus():
    """返回真实的 EventBus（轻量，不需要 mock）。"""
    return EventBus()


@pytest.fixture
def journal(mock_store, event_bus):
    """返回 JournalStore 实例。"""
    return JournalStore(store=mock_store, event_bus=event_bus)


class TestJournalAppend:
    """测试 append 方法。"""

    async def test_append_writes_to_store(self, journal, mock_store):
        """append 应调用 store.save_journal_entry。"""
        jid = await journal.append(
            user_id="u-001",
            session_id="s-001",
            round_id=1,
            raw_input="Hello",
            raw_output="Hi there",
            entities={"name": "Alice"},
            task_intent="qa",
        )

        mock_store.save_journal_entry.assert_called_once()
        call_args = mock_store.save_journal_entry.call_args
        assert call_args[1]["journal_id"] == jid
        assert call_args[1]["user_id"] == "u-001"
        assert call_args[1]["round_id"] == 1

    async def test_append_truncates_output(self, journal, mock_store):
        """长输出应被截断到 2000 字符。"""
        long_output = "x" * 3000
        await journal.append(
            user_id="u-001", session_id="s-001", round_id=1,
            raw_input="test", raw_output=long_output,
        )

        call_args = mock_store.save_journal_entry.call_args
        assert len(call_args[1]["raw_output"]) <= 2000

    async def test_append_publishes_event(self, journal, event_bus):
        """append 应发布 JournalCreatedEvent。"""
        received: list = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe("journal:created", handler)

        jid = await journal.append(
            user_id="u-001", session_id="s-001", round_id=2,
            raw_input="Test input",
        )

        assert len(received) == 1
        event = received[0]
        assert event.journal_id == jid
        assert event.user_id == "u-001"
        assert event.round_id == 2
        assert event.raw_input == "Test input"


class TestJournalQuery:
    """测试查询方法。"""

    async def test_query_pending_delegates_to_store(self, journal, mock_store):
        """query_pending 应委托给 store。"""
        mock_store.query_journal_pending.return_value = [
            {"id": "j-1", "status": "pending"},
            {"id": "j-2", "status": "pending"},
        ]

        results = await journal.query_pending(user_id="u-001", limit=10)
        assert len(results) == 2
        mock_store.query_journal_pending.assert_called_once_with(
            user_id="u-001", session_id=None, limit=10,
        )

    async def test_mark_processed(self, journal, mock_store):
        """mark_processed 应更新状态。"""
        await journal.mark_processed("j-001")
        mock_store.update_journal_status.assert_called_once_with(
            "j-001", "processed",
        )

    async def test_mark_discarded(self, journal, mock_store):
        """mark_discarded 应更新状态。"""
        await journal.mark_discarded("j-001")
        mock_store.update_journal_status.assert_called_once_with(
            "j-001", "discarded",
        )

    async def test_get_pending_count(self, journal, mock_store):
        """get_pending_count 应返回 pending 数量。"""
        mock_store.query_journal_pending.return_value = [
            {"id": "j-1"}, {"id": "j-2"}, {"id": "j-3"},
        ]

        count = await journal.get_pending_count(user_id="u-001")
        assert count == 3
