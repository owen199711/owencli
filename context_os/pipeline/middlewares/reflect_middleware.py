"""ReflectMiddleware — 后任务自省。"""
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware
from context_os.memory.reflection_memory import ReflectionMemory

class ReflectMiddleware(PipelineMiddleware):
    def __init__(self, reflection_memory: ReflectionMemory): self._rm = reflection_memory
    def name(self): return "reflect"
    def order(self): return 800
    async def execute(self, ctx: PipelineContext) -> None:
        if not ctx.metrics: return
        await self._rm.save(task_type=ctx.task_spec.intent.value if ctx.task_spec else "unknown", success=ctx.metrics.success, root_cause=None if ctx.metrics.success else "metrics indicated failure", metadata={"session": ctx.session_id})
