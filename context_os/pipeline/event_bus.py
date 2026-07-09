"""PipelineEventBus — 参考 DeerFlow StreamBridge + EventStore 设计。

在 Pipeline 执行过程中发布阶段级事件，支持监控、Metrics、Trace。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── 事件类型 ──


@dataclass
class StageStarted:
    """阶段开始事件。"""
    stage_name: str
    context_id: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StageCompleted:
    """阶段成功完成事件。"""
    stage_name: str
    context_id: str
    duration_ms: float
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StageFailed:
    """阶段失败事件。"""
    stage_name: str
    context_id: str
    error_message: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PipelineCompleted:
    """Pipeline 整体完成事件。"""
    context_id: str
    success: bool
    total_duration_ms: float
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TokenUsageUpdated:
    """Token 用量更新事件。"""
    context_id: str
    total: int
    used: int
    remaining: int
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── 事件总线 ──

EventHandler = Callable[[Any], None]


class PipelineEventBus:
    """Pipeline 事件总线 — 支持注册/发布事件。"""

    def __init__(self):
        self._handlers: dict[type, list[EventHandler]] = {}

    def register(self, event_type: type, handler: EventHandler) -> None:
        """注册事件处理器。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        """发布事件，通知所有已注册的处理器。"""
        event_type = type(event)
        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error("Event handler error for %s: %s", event_type.__name__, e)

        # 也通知基类 PipelineEvent 的处理器
        for handler in self._handlers.get(object, []):
            try:
                handler(event)
            except Exception as e:
                logger.error("Event handler error: %s", e)

    def clear(self) -> None:
        """清空所有处理器。"""
        self._handlers.clear()
