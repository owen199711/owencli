"""PipelineMiddleware 接口 — 可插拔、可排序的 Pipeline 阶段。

每个 Middleware 代表一个 Pipeline 阶段，
通过 order() 定义执行顺序，is_enabled() 控制是否启用。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_os.pipeline.context import PipelineContext


class PipelineMiddleware(ABC):
    """Pipeline 中间件基类。

    子类需要实现:
    - name() — 中间件名称
    - order() — 排序号 (值越小越先执行)
    - execute() — 执行逻辑
    """

    @abstractmethod
    def name(self) -> str:
        """中间件名称（用于日志、事件、监控）。"""

    @abstractmethod
    def order(self) -> int:
        """排序号。值越小越先执行。"""

    def is_enabled(self, ctx: PipelineContext) -> bool:
        """是否启用。可根据运行时条件动态决定。"""
        return True

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> None:
        """执行中间件逻辑。"""
