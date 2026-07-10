"""ReflectMiddleware — 后任务自省。"""
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware
from context_os.memory.experience import ExperienceMemory


class ReflectMiddleware(PipelineMiddleware):
    def __init__(self, experience_memory: ExperienceMemory):
        self._exp = experience_memory

    def name(self):
        return "reflect"

    def order(self):
        return 800

    async def execute(self, ctx: PipelineContext) -> None:
        if not ctx.metrics:
            return
        await self._exp.record_reflection(
            task_type=ctx.task_spec.intent.value if ctx.task_spec else "unknown",
            root_cause="metrics indicated failure" if not ctx.metrics.success else "",
            lesson=ctx.metrics.model_dump_json() if ctx.metrics.success else "",
            success=ctx.metrics.success,
            metadata={"session": ctx.session_id},
        )
