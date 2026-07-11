"""EventBus — 进程内异步 pub/sub 事件总线。

设计原则：
- 字符串 key 路由（非类型路由），避免模块间类型依赖
- 异步 handler 支持，通过 asyncio.gather 并发调度
- handler 异常隔离：单个 handler 异常不影响其他 handler
- subscribe / unsubscribe 运行时动态管理
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# EventHandler 支持同步 (Callable) 和异步 (Awaitable) 两种形式
EventHandler = Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]


class EventBus:
    """进程内异步事件总线。

    使用方式:
        bus = EventBus()

        async def on_journal_created(event: JournalCreatedEvent):
            await do_something(event)

        bus.subscribe("journal:created", on_journal_created)
        await bus.publish(event)
        bus.unsubscribe("journal:created", on_journal_created)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    # ── 订阅管理 ──

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """订阅事件。

        Args:
            event_type: 事件类型字符串，如 "journal:created"。
            handler: 事件处理器（同步或异步均可）。
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug("Subscribed %s to %s", _handler_name(handler), event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """取消订阅。

        Args:
            event_type: 事件类型字符串。
            handler: 之前注册的处理器引用。
        """
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("Unsubscribed %s from %s", _handler_name(handler), event_type)
        if not handlers:
            self._handlers.pop(event_type, None)

    # ── 发布 ──

    async def publish(self, event: object) -> None:
        """发布事件，并发调用所有订阅者。

        通过事件对象的 __class__.__name__ 转换为事件类型字符串。
        约定：数据类名去掉 "Event" 后缀并转为 snake_case 即事件类型。
        例如 JournalCreatedEvent → "journal_created"，
        或显式使用字符串 subscribe 到的 key。

        Args:
            event: 事件数据类实例。

        注意：
        - handler 异常被捕获并记录日志，不会阻断其他 handler。
        - 若未指定 event_type 参数，将尝试按命名约定推断。
        """
        # 尝试多种命名约定匹配
        event_types = self._resolve_event_types(event)

        coros: list[Awaitable[Any]] = []
        for etype in event_types:
            for handler in self._handlers.get(etype, []):
                coros.append(self._invoke_handler(handler, event))

        if coros:
            results = await asyncio.gather(*coros, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Event handler error: %s", result)

    def publish_sync(self, event: object) -> None:
        """同步发布（非阻塞，适合非异步环境）。

        在已有事件循环中时用 create_task 调度；否则直接 run。

        Args:
            event: 事件数据类实例。
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            asyncio.run(self.publish(event))

    # ── 查询 ──

    def handler_count(self, event_type: str | None = None) -> int:
        """查询已注册的 handler 数量。

        Args:
            event_type: 指定事件类型；不指定则返回总数。

        Returns:
            handler 总数。
        """
        if event_type:
            return len(self._handlers.get(event_type, []))
        return sum(len(v) for v in self._handlers.values())

    def clear(self) -> None:
        """清空所有处理器（用于测试重置）。"""
        self._handlers.clear()

    # ── 内部 ──

    def _resolve_event_types(self, event: object) -> list[str]:
        """解析事件对象对应的事件类型字符串。

        支持两条路径：
        1. handler 注册时用的字符串 key（如 "journal:created"）
        2. 数据类命名约定（JournalCreatedEvent → "journal:created"）
        """
        candidates: list[str] = []

        # 按命名约定推断：CamelCase → snake_case，去 Event 后缀
        class_name = event.__class__.__name__
        if class_name.endswith("Event"):
            base = class_name[:-5]  # 去掉 "Event" 后缀
            snake = _camel_to_snake(base)
            # journal_created → journal:created
            colon = snake.replace("_", ":", 1) if "_" in snake else snake
            candidates.append(colon)

        return candidates

    @staticmethod
    async def _invoke_handler(handler: EventHandler, event: object) -> None:
        """安全调用 handler（同步/异步均可）。"""
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result


# ── 工具函数 ──


def _handler_name(handler: EventHandler) -> str:
    """获取 handler 的可读名称。"""
    if hasattr(handler, "__name__"):
        return handler.__name__
    if hasattr(handler, "__class__"):
        return handler.__class__.__name__
    return str(handler)


def _camel_to_snake(name: str) -> str:
    """CamelCase → snake_case。"""
    result = []
    for i, ch in enumerate(name):
        if ch.isupper():
            if i > 0 and name[i - 1].islower():
                result.append("_")
            result.append(ch.lower())
        else:
            result.append(ch)
    return "".join(result)
