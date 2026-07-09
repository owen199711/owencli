"""IntentMiddleware — 意图理解。"""

from context_os.intent.parser import TaskParser
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class IntentMiddleware(PipelineMiddleware):
    """解析用户输入 → TaskSpec。"""

    def __init__(self, task_parser: TaskParser):
        self._tp = task_parser

    def name(self) -> str:
        return "intent"

    def order(self) -> int:
        return 100

    async def execute(self, ctx: PipelineContext) -> None:
        ctx.task_spec = await self._tp.parse(ctx.user_input)
