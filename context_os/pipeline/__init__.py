"""Pipeline — Middleware Chain 编排引擎。

参考 DeerFlow 17 个 AgentMiddleware 链式设计，
将 Pipeline 各阶段重构为可插拔、可排序的 Middleware。
"""

from context_os.pipeline.middleware import PipelineMiddleware
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.event_bus import PipelineEventBus, StageStarted, StageCompleted, StageFailed
from context_os.pipeline.engine import PipelineEngine

__all__ = [
    "PipelineMiddleware",
    "PipelineContext",
    "PipelineEventBus",
    "PipelineEngine",
    "StageStarted",
    "StageCompleted",
    "StageFailed",
]
