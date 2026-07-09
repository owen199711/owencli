"""PackageMiddleware — Prompt 打包。"""

from context_os.packager.packager import ContextPackager
from context_os.pipeline.context import PipelineContext
from context_os.pipeline.middleware import PipelineMiddleware


class PackageMiddleware(PipelineMiddleware):
    """按 provider 格式拼接 sections → PackagedContext。"""

    def __init__(self, packager: ContextPackager):
        self._p = packager

    def name(self) -> str:
        return "package"

    def order(self) -> int:
        return 500

    async def execute(self, ctx: PipelineContext) -> None:
        ctx.packaged_context = self._p.pack(ctx.optimized_context, ctx.provider)
