"""OptimizeMiddleware — 上下文优化。"""

from context_os.optimizer.optimizer import ContextOptimizer
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class OptimizeMiddleware(PipelineMiddleware):
    """排序记忆 → 压缩对话 → 分配预算。"""

    def __init__(self, optimizer: ContextOptimizer):
        self._o = optimizer

    def name(self) -> str:
        return "optimize"

    def order(self) -> int:
        return 400

    async def execute(self, ctx: PipelineContext) -> None:
        ctx.optimized_context = await self._o.optimize(
            ctx.unified_context, ctx.task_spec
        )
