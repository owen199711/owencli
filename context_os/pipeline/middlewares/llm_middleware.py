"""LLMMiddleware — LLM 调用。"""

from context_os.llm.client import BaseLLMClient
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class LLMMiddleware(PipelineMiddleware):
    """调用 LLM API。"""

    def __init__(self, llm_client: BaseLLMClient):
        self._c = llm_client

    def name(self) -> str:
        return "llm"

    def order(self) -> int:
        return 600

    async def execute(self, ctx: PipelineContext) -> None:
        response = await self._c.complete(ctx.packaged_context.raw_prompt)
        ctx.llm_response = str(response)
