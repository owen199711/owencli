"""BuildMiddleware — 上下文构建。"""

from context_os.builder.builder import ContextBuilder
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class BuildMiddleware(PipelineMiddleware):
    """收集身份/对话/环境/记忆 → UnifiedContext。"""

    def __init__(self, builder: ContextBuilder):
        self._b = builder

    def name(self) -> str:
        return "build"

    def order(self) -> int:
        return 300

    async def execute(self, ctx: PipelineContext) -> None:
        ctx.unified_context = await self._b.build(ctx.task_spec)
