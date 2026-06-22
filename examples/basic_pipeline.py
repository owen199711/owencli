"""Context-OS 基本使用示例。

运行:
    python examples/basic_pipeline.py

需要:
    1. 设置 DEEPSEEK_API_KEY 环境变量（或 ANTHROPIC_API_KEY / OPENAI_API_KEY）
    2. （可选）设置 DATABASE_URL 环境变量指向 SQLite 数据库路径
    3. 切换 LLM: $env:LLM_PROVIDER='anthropic' | 'openai' | 'deepseek'
"""

import asyncio
import os

from context_os.core.models import LLMProvider
from context_os.llm.deepseek_client import DeepSeekClient
from context_os.llm.anthropic_client import AnthropicClient
from context_os.llm.openai_client import OpenAIClient
from context_os.pipeline import ContextOSPipeline


async def main():
    """演示 Context-OS Pipeline 的基本使用。"""

    # ── 初始化 LLM Client（默认使用 DeepSeek）──
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()

    if provider == "anthropic":
        llm = AnthropicClient()
        llm_provider = LLMProvider.CLAUDE
        print("Using Anthropic:", llm.model)
    elif provider == "openai":
        llm = OpenAIClient()
        llm_provider = LLMProvider.OPENAI
        print("Using OpenAI:", llm.model)
    else:
        llm = DeepSeekClient()
        llm_provider = LLMProvider.DEEPSEEK
        print("Using DeepSeek:", llm.model)

    # ── 初始化 Pipeline ──
    async with ContextOSPipeline(
        llm_client=llm,
        provider=llm_provider,
        db_path=os.environ.get("DATABASE_URL"),
        user_id="demo-user",
    ) as pipeline:

        # ── 示例 1: QA ──
        print("\n" + "=" * 60)
        print("示例 1: QA 问答")
        print("=" * 60)
        result = await pipeline.run("Python 中列表推导式和生成器表达式有什么区别？")
        print(f"回答: {result['response'][:300]}...")
        print(f"质量评分: {result['metrics']['answer_quality']:.3f}")
        print(f"延迟: {result['latency_ms']:.0f}ms")
        print(f"Trace ID: {result['trace_id']}")

        # ── 示例 2: 编码 ──
        print("\n" + "=" * 60)
        print("示例 2: 代码生成")
        print("=" * 60)
        result = await pipeline.run("用 FastAPI 写一个简单的健康检查接口")
        print(f"回答: {result['response'][:300]}...")
        print(f"质量评分: {result['metrics']['answer_quality']:.3f}")

        # ── 示例 3: 调试（测试记忆是否生效）──
        print("\n" + "=" * 60)
        print("示例 3: 调试（验证记忆系统）")
        print("=" * 60)
        result = await pipeline.run("我刚刚写的代码中，健康检查接口的路径是什么？")
        print(f"回答: {result['response'][:300]}...")
        print(f"质量评分: {result['metrics']['answer_quality']:.3f}")
        print(f"会话记忆生效: {'healthy' in result['response'].lower() if 'healthy' in result['response'].lower() else '请检查'}")

        print("\n✅ Pipeline 执行完成")


if __name__ == "__main__":
    asyncio.run(main())
