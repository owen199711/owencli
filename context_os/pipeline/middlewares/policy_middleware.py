"""PolicyMiddleware — 策略评估。"""
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware
from context_os.policy import ContextPolicy

class PolicyMiddleware(PipelineMiddleware):
    def __init__(self, policy: ContextPolicy): self._cp = policy
    def name(self): return "policy"
    def order(self): return 200
    async def execute(self, ctx: PipelineContext) -> None:
        ctx.policy_directive = self._cp.evaluate(ctx.task_spec)
