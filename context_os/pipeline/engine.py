"""PipelineEngine — 基于 Middleware Chain 的 Pipeline 编排器。

按 PipelineMiddleware.order() 排序后依次执行，
每个阶段前后发布事件到 PipelineEventBus。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from context_os.pipeline.context import PipelineContext
from context_os.pipeline.event_bus import (
    PipelineCompleted,
    PipelineEventBus,
    StageCompleted,
    StageFailed,
    StageStarted,
)
from context_os.pipeline.middleware import PipelineMiddleware

logger = logging.getLogger(__name__)


class PipelineEngine:
    """Pipeline 引擎 — 顺序执行 Middleware Chain。"""

    def __init__(
        self,
        middlewares: list[PipelineMiddleware],
        event_bus: Optional[PipelineEventBus] = None,
    ):
        # 按 order 排序
        self._middlewares = sorted(middlewares, key=lambda m: m.order())
        self._event_bus = event_bus or PipelineEventBus()
        self._context_id = uuid.uuid4().hex[:12]

        logger.info(
            "PipelineEngine initialized: %d middlewares registered",
            len(self._middlewares),
        )
        for mw in self._middlewares:
            logger.info("  MW [%3d] %s", mw.order(), mw.name())

    @property
    def event_bus(self) -> PipelineEventBus:
        return self._event_bus

    @property
    def middlewares(self) -> list[PipelineMiddleware]:
        return list(self._middlewares)

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        """执行 Pipeline Middleware Chain。

        Args:
            ctx: Pipeline 执行上下文。

        Returns:
            执行完成后的上下文（与入参同一对象）。
        """
        pipeline_start = time.time()

        # 过滤已启用的 middleware
        enabled = [mw for mw in self._middlewares if mw.is_enabled(ctx)]

        logger.info(
            "========== PipelineEngine start: context=%s, mw=%d/%d ==========",
            self._context_id,
            len(enabled),
            len(self._middlewares),
        )

        try:
            for mw in enabled:
                if ctx.cancelled:
                    logger.info("Pipeline cancelled at MW [%d] %s", mw.order(), mw.name())
                    break

                t0 = time.time()
                self._event_bus.publish(
                    StageStarted(stage_name=mw.name(), context_id=self._context_id)
                )

                try:
                    await mw.execute(ctx)
                    duration_ms = (time.time() - t0) * 1000
                    self._event_bus.publish(
                        StageCompleted(
                            stage_name=mw.name(),
                            context_id=self._context_id,
                            duration_ms=duration_ms,
                        )
                    )
                    logger.info(
                        "MW [%3d] %s completed in %.0fms",
                        mw.order(),
                        mw.name(),
                        duration_ms,
                    )
                except Exception as e:
                    duration_ms = (time.time() - t0) * 1000
                    self._event_bus.publish(
                        StageFailed(
                            stage_name=mw.name(),
                            context_id=self._context_id,
                            error_message=str(e),
                        )
                    )
                    logger.error(
                        "MW [%3d] %s failed in %.0fms: %s",
                        mw.order(),
                        mw.name(),
                        duration_ms,
                        e,
                    )
                    raise

        finally:
            total_duration_ms = (time.time() - pipeline_start) * 1000
            success = not ctx.cancelled
            self._event_bus.publish(
                PipelineCompleted(
                    context_id=self._context_id,
                    success=success,
                    total_duration_ms=total_duration_ms,
                )
            )
            logger.info(
                "========== PipelineEngine end: success=%s, total=%.0fms ==========",
                success,
                total_duration_ms,
            )

        return ctx
