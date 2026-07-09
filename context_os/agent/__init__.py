"""InteractiveAgent — CLI 交互式 Agent。

参考 Java: com.owencli.contextos.agent.InteractiveAgent
支持命令：/memory, /debug, /clear, /stats, /help
"""
from __future__ import annotations
import asyncio
import logging
from context_os.pipeline import PipelineEngine, PipelineContext, PipelineEventBus

logger = logging.getLogger(__name__)

class InteractiveAgent:
    def __init__(self, engine: PipelineEngine, event_bus: PipelineEventBus = None):
        self.engine = engine
        self._event_bus = event_bus or PipelineEventBus()
        self._running = False

    async def run(self, session_id: str = None, user_id: str = None) -> None:
        """启动交互式 Agent CLI。"""
        import uuid
        session_id = session_id or uuid.uuid4().hex[:8]
        user_id = user_id or "cli_user"
        self._running = True
        print(f"InteractiveAgent session={session_id} user={user_id}")
        print("Commands: /help, /memory, /debug, /stats, /clear, /quit")
        while self._running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, input, "\n> ")
                if not line: continue
                if line.startswith("/"): await self._handle_command(line, session_id, user_id)
                else: await self._process_input(line, session_id, user_id)
            except (EOFError, KeyboardInterrupt): break
            except Exception as e: print(f"Error: {e}")

    async def _handle_command(self, cmd: str, session_id: str, user_id: str) -> None:
        parts = cmd.strip().split()
        cmd_name = parts[0].lower()
        if cmd_name == "/quit" or cmd_name == "/exit": self._running = False
        elif cmd_name == "/help":
            print("Commands: /help, /memory, /debug <stage>, /stats, /clear, /quit")
        elif cmd_name == "/memory": print("Memory: Feature available (connect via store session)")
        elif cmd_name == "/debug":
            stage = parts[1] if len(parts) > 1 else "all"
            print(f"Debugging stage: {stage}")
        elif cmd_name == "/stats":
            print(f"Middlewares: {len(self.engine.middlewares)}")
            for mw in self.engine.middlewares:
                print(f"  [{'x' if mw.is_enabled(PipelineContext('','','',None,{})) else ' '}] {mw.order():3d} {mw.name()}")
        elif cmd_name == "/clear": print("\n" * 40)
        else: print(f"Unknown command: {cmd_name}")

    async def _process_input(self, text: str, session_id: str, user_id: str) -> None:
        ctx = PipelineContext(user_input=text, session_id=session_id, user_id=user_id)
        result = await self.engine.execute(ctx)
        if result.llm_response: print(f"\n{result.llm_response}")
        if result.metrics: print(f"\n[metrics: success={result.metrics.success}, reward={getattr(result.metrics,'reward_score','N/A')}]")
