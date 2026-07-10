"""Benchmark 入口。

用法:
    python -m benchmark.run                          # 完整 Benchmark
    python -m benchmark.run --mode module            # 只测模块
    python -m benchmark.run --mode pipeline          # 只测 Pipeline
    python -m benchmark.run --mode memory            # 只测记忆对比
    python -m benchmark.run --mode retriever         # 只测检索
    python -m benchmark.run --output ./my_reports    # 自定义报告输出目录
    python -m benchmark.run --cases T1,T2            # 只跑指定用例
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime


def setup_llm(provider: str = "deepseek") -> object:
    """自动检测并初始化 LLM 客户端。"""
    provider = provider.lower()

    if provider == "deepseek" or os.environ.get("DEEPSEEK_API_KEY"):
        from context_os.llm.deepseek_client import DeepSeekClient
        print(f"[LLM] DeepSeek")
        return DeepSeekClient()

    if provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
        from context_os.llm.anthropic_client import AnthropicClient
        print(f"[LLM] Anthropic Claude")
        return AnthropicClient()

    if provider == "openai" or os.environ.get("OPENAI_API_KEY"):
        from context_os.llm.openai_client import OpenAIClient
        print(f"[LLM] OpenAI")
        return OpenAIClient()

    raise RuntimeError(
        "未检测到 API Key。请设置 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY"
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Context-OS Benchmark Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python -m benchmark.run                          # 完整 Benchmark
    python -m benchmark.run --mode module            # 只测模块
    python -m benchmark.run --mode memory --cases T1,T2  # 只跑 T1,T2 的记忆对比
        """,
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["all", "module", "pipeline", "memory", "retriever"],
        default="all",
        help="测试模式（默认: all）",
    )
    parser.add_argument(
        "--output", "-o",
        default="benchmark/reports",
        help="报告输出目录（默认: benchmark/reports）",
    )
    parser.add_argument(
        "--provider", "-p",
        default=os.environ.get("LLM_PROVIDER", "deepseek"),
        help="LLM 提供商（默认: deepseek，也可设置 LLM_PROVIDER 环境变量）",
    )
    parser.add_argument(
        "--cases", "-c",
        default="",
        help="逗号分隔的用例 ID（如 T1,T2），不指定则运行全部",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("DATABASE_URL", ""),
        help="数据库路径（默认: DATABASE_URL 环境变量）",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  Context-OS Benchmark Framework")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {args.mode}")
    print("=" * 60)

    # 初始化 LLM
    llm = setup_llm(args.provider)
    runner = None

    try:
        db_path = args.db or None

        if not db_path:
            print("[DB] DATABASE_URL 未设置，使用降级存储")

        # 初始化 Runner
        from benchmark.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(llm, db_path)

        # 加载测试用例
        from benchmark.datasets import MEMORY_TEST_CASES

        test_cases = MEMORY_TEST_CASES
        if args.cases:
            selected_ids = set(c.strip().upper() for c in args.cases.split(","))
            test_cases = [tc for tc in MEMORY_TEST_CASES if tc.id in selected_ids]
            if not test_cases:
                raise ValueError(
                    f"未找到指定用例 {args.cases}，可用: {[tc.id for tc in MEMORY_TEST_CASES]}"
                )
            print(f"[Cases] 选中: {[tc.id for tc in test_cases]}")

        # 运行
        run_module = args.mode in ("all", "module")
        run_pipeline = args.mode in ("all", "pipeline")
        run_memory = args.mode in ("all", "memory")
        run_retriever = args.mode in ("all", "retriever")

        results = await runner.run_all(
            test_cases=test_cases,
            run_module=run_module,
            run_pipeline=run_pipeline,
            run_memory=run_memory,
            run_retriever=run_retriever,
        )

        # 生成报告
        from benchmark.reporter import ReportGenerator
        reporter = ReportGenerator(args.output)

        reporter.print_console_summary(results)

        json_path = reporter.generate_json(results)
        print(f"\nJSON 报告: {json_path}")

        html_path = reporter.generate_html(results)
        print(f"HTML 报告: {html_path}")

    finally:
        # 确保 LLM client 和 runner 资源被释放
        if runner is not None:
            # runner 内部管理 agent 生命周期，但确保整体清理
            pass
        if hasattr(llm, "close"):
            try:
                await llm.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
