"""FeedbackMiddleware — 反馈评估 + 记忆更新。"""

from context_os.feedback.evaluator import QualityEvaluator
from context_os.feedback.memory_updater import MemoryUpdater
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class FeedbackMiddleware(PipelineMiddleware):
    """评估 LLM 输出质量，更新记忆。"""

    def __init__(self, evaluator: QualityEvaluator, memory_updater: MemoryUpdater):
        self._e = evaluator
        self._m = memory_updater

    def name(self) -> str:
        return "feedback"

    def order(self) -> int:
        return 700

    async def execute(self, ctx: PipelineContext) -> None:
        pc = ctx.packaged_context
        token_est = ctx.optimized_context.token_usage.used or len(pc.raw_prompt) // 4
        ctx.metrics = await self._e.evaluate(
            packed=pc,
            llm_response=ctx.llm_response,
            latency_ms=0,
            token_count=token_est,
        )
        ctx.memory_update_result = await self._m.update_from_task(
            task=ctx.task_spec,
            response=ctx.llm_response,
            metrics=ctx.metrics,
            user_id=ctx.user_id,
        )
