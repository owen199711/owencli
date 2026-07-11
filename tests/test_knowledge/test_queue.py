"""KnowledgeQueue 单元测试。

覆盖：
- enqueue 入队
- dequeue_batch 出队 + 自动标记 processing
- mark_done / mark_failed 状态更新
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_os.knowledge.queue import KnowledgeQueue


@pytest.fixture
def mock_store():
    """返回 mock 的 SQLiteStore。"""
    store = MagicMock()
    store.enqueue_knowledge = AsyncMock(return_value="kq-001")
    store.dequeue_knowledge_batch = AsyncMock(return_value=[])
    store.mark_knowledge_done = AsyncMock()
    store.mark_knowledge_failed = AsyncMock()
    return store


@pytest.fixture
def queue(mock_store):
    """返回 KnowledgeQueue 实例。"""
    return KnowledgeQueue(store=mock_store)


class TestEnqueue:
    """测试入队。"""

    async def test_enqueue_returns_id(self, queue, mock_store):
        """enqueue 应返回队列 ID。"""
        qid = await queue.enqueue(
            content="用户提到喜欢 Python",
            user_id="u-001",
            source="channel_b",
        )
        assert qid == "kq-001"
        mock_store.enqueue_knowledge.assert_called_once_with(
            content="用户提到喜欢 Python",
            user_id="u-001",
            source="channel_b",
            priority=0,
        )

    async def test_enqueue_default_source(self, queue, mock_store):
        """默认 source 应为 channel_b。"""
        await queue.enqueue(content="test")
        call_args = mock_store.enqueue_knowledge.call_args
        assert call_args[1]["source"] == "channel_b"


class TestDequeue:
    """测试出队。"""

    async def test_dequeue_batch_delegates(self, queue, mock_store):
        """dequeue_batch 应委托给 store。"""
        mock_store.dequeue_knowledge_batch.return_value = [
            {"id": "kq-1", "content": "content 1", "status": "processing"},
        ]

        tasks = await queue.dequeue_batch(batch_size=5, user_id="u-001")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "processing"

    async def test_dequeue_batch_auto_marks_processing(self, queue, mock_store):
        """dequeue_batch 返回的任务应已标记为 processing。"""
        mock_store.dequeue_knowledge_batch.return_value = [
            {"id": "kq-10", "content": "test content", "status": "processing"},
        ]

        tasks = await queue.dequeue_batch(batch_size=10)
        assert len(tasks) == 1
        assert tasks[0]["status"] == "processing"


class TestMark:
    """测试状态标记。"""

    async def test_mark_done(self, queue, mock_store):
        """mark_done 应标记为完成。"""
        await queue.mark_done("kq-001")
        mock_store.mark_knowledge_done.assert_called_once_with("kq-001")

    async def test_mark_failed(self, queue, mock_store):
        """mark_failed 应标记为失败。"""
        await queue.mark_failed("kq-001", error="LLM timeout")
        mock_store.mark_knowledge_failed.assert_called_once_with(
            "kq-001", "LLM timeout",
        )

    async def test_get_pending_count(self, queue, mock_store):
        """get_pending_count 应返回 pending 数量。"""
        mock_store.dequeue_knowledge_batch.return_value = [
            {"id": "kq-1"}, {"id": "kq-2"},
        ]

        count = await queue.get_pending_count()
        assert count == 2
