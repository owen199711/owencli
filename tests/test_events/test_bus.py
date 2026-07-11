"""EventBus 单元测试。

覆盖：
- 单 handler 订阅/发布/取消订阅
- 多 handler 并发发布
- handler 异常隔离
- sync/async handler 混合
- 无订阅者发布（无错误）
- clear 重置
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from context_os.events import (
    EventBus,
    JournalCreatedEvent,
    WriteDecisionCompletedEvent,
    MemoryWrittenEvent,
    KnowledgeEvent,
    EVENT_JOURNAL_CREATED,
    EVENT_JOURNAL_PROCESSED,
    EVENT_WRITE_DECISION_COMPLETED,
    EVENT_MEMORY_WRITTEN,
    EVENT_KNOWLEDGE_READY,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def bus() -> EventBus:
    """返回一个干净的 EventBus 实例。"""
    return EventBus()


@pytest.fixture
def journal_event() -> JournalCreatedEvent:
    """返回一个示例 JournalCreatedEvent。"""
    return JournalCreatedEvent(
        journal_id="j-001",
        user_id="u-001",
        session_id="s-001",
        round_id=1,
        raw_input="我叫张三，今年 30 岁",
        raw_output="你好张三！",
        entities={"person": "张三", "age": 30},
        task_intent="qa",
    )


# ═══════════════════════════════════════════════════════════════
# 基础订阅/发布
# ═══════════════════════════════════════════════════════════════


class TestSubscribePublish:
    """测试基础订阅/发布流程。"""

    def test_subscribe_and_publish_sync(self, bus: EventBus, journal_event):
        """同步 handler：订阅后发布能收到事件。"""
        received: list[Any] = []

        def handler(event):
            received.append(event)

        bus.subscribe(EVENT_JOURNAL_CREATED, handler)
        bus.publish_sync(journal_event)

        assert len(received) == 1
        assert received[0] is journal_event

    async def test_subscribe_and_publish_async(self, bus: EventBus, journal_event):
        """异步 handler：异步发布能收到事件。"""
        received: list[Any] = []

        async def handler(event):
            await asyncio.sleep(0.001)  # 模拟异步操作
            received.append(event)

        bus.subscribe(EVENT_JOURNAL_CREATED, handler)
        await bus.publish(journal_event)

        assert len(received) == 1
        assert received[0] is journal_event

    async def test_publish_no_handlers(self, bus: EventBus, journal_event):
        """没有订阅者时 publish 不应报错。"""
        await bus.publish(journal_event)  # 不应该抛出异常

    async def test_publish_mixed_sync_async(self, bus: EventBus, journal_event):
        """混合同步和异步 handler。"""
        received: list[str] = []

        def sync_handler(event):
            received.append("sync")

        async def async_handler(event):
            await asyncio.sleep(0)
            received.append("async")

        bus.subscribe(EVENT_JOURNAL_CREATED, sync_handler)
        bus.subscribe(EVENT_JOURNAL_CREATED, async_handler)
        await bus.publish(journal_event)

        # 两个 handler 都应该被调用
        assert "sync" in received
        assert "async" in received


# ═══════════════════════════════════════════════════════════════
# 多 handler 并发
# ═══════════════════════════════════════════════════════════════


class TestMultipleHandlers:
    """测试多 handler 并发调度。"""

    async def test_three_handlers_all_called(self, bus: EventBus, journal_event):
        """3 个 handler 订阅同一事件 → 全部被调用。"""
        calls: list[str] = []

        async def h1(event):
            calls.append("h1")

        async def h2(event):
            calls.append("h2")

        async def h3(event):
            calls.append("h3")

        bus.subscribe(EVENT_JOURNAL_CREATED, h1)
        bus.subscribe(EVENT_JOURNAL_CREATED, h2)
        bus.subscribe(EVENT_JOURNAL_CREATED, h3)
        await bus.publish(journal_event)

        assert sorted(calls) == ["h1", "h2", "h3"]

    async def test_handlers_run_concurrently(self, bus: EventBus, journal_event):
        """handlers 应并发执行（总耗时 ≈ max(各耗时) 而非 sum）。"""
        latencies: list[int] = []

        async def slow_handler(event):
            await asyncio.sleep(0.05)
            latencies.append(50)

        async def medium_handler(event):
            await asyncio.sleep(0.03)
            latencies.append(30)

        bus.subscribe(EVENT_JOURNAL_CREATED, slow_handler)
        bus.subscribe(EVENT_JOURNAL_CREATED, medium_handler)

        t0 = asyncio.get_event_loop().time()
        await bus.publish(journal_event)
        elapsed = (asyncio.get_event_loop().time() - t0) * 1000

        assert len(latencies) == 2
        # 并发执行意味着总耗时应该 < sum(50+30=80ms)，留 10ms 余量  < 70ms
        assert elapsed < 70, f"Expected concurrent execution (<70ms), got {elapsed:.0f}ms"


# ═══════════════════════════════════════════════════════════════
# Unsubscribe
# ═══════════════════════════════════════════════════════════════


class TestUnsubscribe:
    """测试取消订阅。"""

    async def test_unsubscribe_stops_receiving(self, bus: EventBus, journal_event):
        """取消订阅后不再收到事件。"""
        calls: list[Any] = []

        async def handler(event):
            calls.append(event)

        bus.subscribe(EVENT_JOURNAL_CREATED, handler)
        await bus.publish(journal_event)
        assert len(calls) == 1

        bus.unsubscribe(EVENT_JOURNAL_CREATED, handler)
        await bus.publish(journal_event)
        assert len(calls) == 1  # 仍然是 1，第二次没有触发

    async def test_unsubscribe_nonexistent_ok(self, bus: EventBus):
        """取消订阅不存在的 handler 不应报错。"""

        async def handler(event):
            pass

        # 不应该抛出异常
        bus.unsubscribe("nonexistent:event", handler)


# ═══════════════════════════════════════════════════════════════
# 异常隔离
# ═══════════════════════════════════════════════════════════════


class TestExceptionIsolation:
    """测试 handler 异常隔离。"""

    async def test_failing_handler_does_not_break_others(self, bus: EventBus, journal_event):
        """一个 handler 抛异常不影响其他 handler 执行。"""
        calls: list[str] = []

        async def failing_handler(event):
            raise RuntimeError("boom")

        async def normal_handler(event):
            calls.append("ok")

        bus.subscribe(EVENT_JOURNAL_CREATED, failing_handler)
        bus.subscribe(EVENT_JOURNAL_CREATED, normal_handler)
        await bus.publish(journal_event)  # 不应抛异常

        assert calls == ["ok"]


# ═══════════════════════════════════════════════════════════════
# handler_count / clear
# ═══════════════════════════════════════════════════════════════


class TestQueryAndClear:
    """测试 handler 查询和清空。"""

    def test_handler_count(self, bus: EventBus):
        """handler_count 返回正确的注册数量。"""
        assert bus.handler_count() == 0

        def h1(e): pass

        def h2(e): pass

        bus.subscribe(EVENT_JOURNAL_CREATED, h1)
        assert bus.handler_count() == 1
        assert bus.handler_count(EVENT_JOURNAL_CREATED) == 1
        assert bus.handler_count(EVENT_MEMORY_WRITTEN) == 0

        bus.subscribe(EVENT_MEMORY_WRITTEN, h2)
        assert bus.handler_count() == 2
        assert bus.handler_count(EVENT_JOURNAL_CREATED) == 1
        assert bus.handler_count(EVENT_MEMORY_WRITTEN) == 1

    def test_clear(self, bus: EventBus):
        """clear 清空所有 handler。"""
        def h(e): pass

        bus.subscribe(EVENT_JOURNAL_CREATED, h)
        bus.subscribe(EVENT_MEMORY_WRITTEN, h)
        assert bus.handler_count() == 2

        bus.clear()
        assert bus.handler_count() == 0

    def test_subscribe_duplicate_idempotent(self, bus: EventBus):
        """重复订阅同一 handler 不会增加计数。"""
        def h(e): pass

        bus.subscribe(EVENT_JOURNAL_CREATED, h)
        bus.subscribe(EVENT_JOURNAL_CREATED, h)
        assert bus.handler_count() == 1


# ═══════════════════════════════════════════════════════════════
# 事件类型
# ═══════════════════════════════════════════════════════════════


class TestEventTypes:
    """测试事件数据类的构造和属性。"""

    def test_journal_created_event(self):
        event = JournalCreatedEvent(
            journal_id="j-001",
            user_id="u-001",
            session_id="s-001",
            round_id=3,
            raw_input="Hello",
            entities={"name": "Alice"},
        )
        assert event.journal_id == "j-001"
        assert event.entities["name"] == "Alice"

    def test_write_decision_completed_event(self):
        event = WriteDecisionCompletedEvent(
            journal_id="j-001",
            user_id="u-001",
            should_store=True,
            score=0.85,
            layer=3,
            reason="importance=0.85 >= threshold=0.50",
        )
        assert event.should_store is True
        assert event.layer == 3

    def test_memory_written_event(self):
        event = MemoryWrittenEvent(
            journal_id="j-001",
            user_id="u-001",
            target="long_term",
            memory_id="m-001",
            category="fact",
            entity_key="user.name",
        )
        assert event.target == "long_term"
        assert event.category == "fact"

    def test_knowledge_event(self):
        event = KnowledgeEvent(
            journal_id="j-001",
            user_id="u-001",
            triples=[{"subject": "张三", "predicate": "age", "object": "30"}],
        )
        assert len(event.triples) == 1


# ═══════════════════════════════════════════════════════════════
# 事件类型常量
# ═══════════════════════════════════════════════════════════════


class TestEventConstants:
    """测试事件类型常量字符串。"""

    def test_constants_defined(self):
        """所有事件类型常量应有定义。"""
        assert EVENT_JOURNAL_CREATED == "journal:created"
        assert EVENT_JOURNAL_PROCESSED == "journal:processed"
        assert EVENT_WRITE_DECISION_COMPLETED == "write_decision:completed"
        assert EVENT_MEMORY_WRITTEN == "memory:written"
        assert EVENT_KNOWLEDGE_READY == "knowledge:ready"
