"""Agent 定义 — SimpleAgent (无记忆) 和 MemoryAgent (完整 Context-OS)。

每个 Agent 具备统一的 chat() 接口，方便 BenchmarkRunner 统一调用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional


class SimpleAgent:
    """无记忆 Agent — 每次调用完全独立。

    模拟"无记忆系统"的行为：
    - 无 conversation_history
    - 无检索 / 无 Context-OS Pipeline
    - 只传当前输入的原始文本给 LLM
    """

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    async def chat(self, user_input: str) -> str:
        """对话 — 完全无上下文，只传当前输入。"""
        prompt = f"User: {user_input}\nAssistant:"
        response = await self.llm_client.complete(prompt, max_tokens=2000)
        return str(response)

    async def close(self):
        pass


class MemoryAgent:
    """完整 Context-OS 记忆系统的 Agent。

    使用完整的 ContextOSPipeline，包含 Intent → Collection → Builder →
    Optimizer → Packager → LLM → Feedback → Memory Update 全链路。
    Pipeline 首次 run() 时自动完成 store 连接，无需手动初始化。
    """

    def __init__(
        self,
        llm_client: Any,
        db_path: Optional[str] = None,
        embedding_provider: Any = None,
        session_id: Optional[str] = None,
        user_id: str = "benchmark",
    ):
        from context_os import ContextOSPipeline
        from context_os.core.models import LLMProvider

        provider_name = type(llm_client).__name__.lower()
        if "anthropic" in provider_name:
            provider = LLMProvider.CLAUDE
        elif "openai" in provider_name:
            provider = LLMProvider.OPENAI
        elif "deepseek" in provider_name:
            provider = LLMProvider.DEEPSEEK
        else:
            provider = LLMProvider.CLAUDE

        # 添加微秒精度 + 随机后缀，避免同秒创建时的 session_id 碰撞
        if session_id is None:
            ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
            suffix = uuid.uuid4().hex[:6]
            session_id = f"benchmark-{ts}-{suffix}"

        self.pipeline = ContextOSPipeline(
            llm_client=llm_client,
            provider=provider,
            db_path=db_path,
            session_id=session_id,
            user_id=user_id,
            embedding_provider=embedding_provider,
        )

    async def chat(self, user_input: str) -> str:
        """对话 — 走完整 Pipeline（首次调用自动完成 store 连接）。"""
        result = await self.pipeline.run(user_input)
        return result["response"]

    async def close(self):
        await self.pipeline.close()
