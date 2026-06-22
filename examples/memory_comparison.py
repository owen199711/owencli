"""智能体对比测试：无记忆 vs 有记忆。

运行:
    python examples/memory_comparison.py

测试场景:
    用户连续提出 3 个问题，其中后面的问题依赖前面的上下文。
    对比两个智能体的回复质量。

场景设计:
    Q1: "我的项目使用 FastAPI + PostgreSQL，帮我生成用户表模型"
    Q2: "添加创建时间和更新时间字段"        ← 依赖 Q1 知道在哪个文件改
    Q3: "刚才的 User 模型中，密码字段存储方式应该改一下"   ← 依赖 Q1+Q2 的完整上下文
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
import json


# ═══════════════════════════════════════════════════════════════════
# Agent A: 无记忆系统 — 每次调用都是独立的
# ═══════════════════════════════════════════════════════════════════

class SimpleAgent:
    """最简单的 Agent — 无记忆、无 Context 管理。

    每次调用完全独立，只传当前输入。
    """

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client
        self.conversation_history: list[dict] = []  # 简陋的手动历史
        print("[SimpleAgent] 已初始化（无记忆系统）")

    async def chat(self, user_input: str) -> str:
        """对话 — 仅拼接原始对话历史。

        Args:
            user_input: 用户输入。

        Returns:
            LLM 回复。
        """
        # 简陋拼接：把历史消息列表转文字
        context = ""
        if self.conversation_history:
            history_lines = []
            for h in self.conversation_history[-5:]:  # 最多保留 5 轮
                history_lines.append(f"{h['role']}: {h['content']}")
            context = "\n".join(history_lines) + "\n\n"

        prompt = f"{context}User: {user_input}\nAssistant:"
        response = await self.llm_client.complete(prompt, max_tokens=2000)

        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": str(response)[:200]})

        return str(response)


# ═══════════════════════════════════════════════════════════════════
# Agent B: Context-OS 完整记忆系统
# ═══════════════════════════════════════════════════════════════════

class MemoryAgent:
    """具备完整 Context-OS 记忆系统的 Agent。

    使用:
        - WorkingMemory: 当前对话活跃上下文
        - ShortTermMemory: Session 级记忆（PG 持久化）
        - LongTermMemory: 跨 Session 长期知识
        - ContextBuilder: 自动构建 UnifiedContext
        - ContextOptimizer: Token 排序压缩
    """

    def __init__(
        self,
        llm_client: Any,
        db_path: Optional[str] = None,
    ):
        from context_os.pipeline import ContextOSPipeline
        from context_os.core.models import LLMProvider

        # 自动检测 provider
        provider_name = type(llm_client).__name__.lower()
        if "anthropic" in provider_name:
            provider = LLMProvider.CLAUDE
        elif "openai" in provider_name:
            provider = LLMProvider.OPENAI
        elif "deepseek" in provider_name:
            provider = LLMProvider.DEEPSEEK
        else:
            provider = LLMProvider.CLAUDE

        self.pipeline = ContextOSPipeline(
            llm_client=llm_client,
            provider=provider,
            db_path=db_path,
            session_id=f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            user_id="memory-test",
        )
        self._initialized = False
        print(f"[MemoryAgent] 已初始化（完整记忆系统: {provider.value})")

    async def chat(self, user_input: str) -> str:
        """对话 — 走完整 Pipeline。

        Args:
            user_input: 用户输入。

        Returns:
            LLM 回复。
        """
        if not self._initialized:
            await self.pipeline._ensure_store()
            self._initialized = True

        result = await self.pipeline.run(user_input)
        return result["response"]

    async def close(self):
        await self.pipeline.close()


# ═══════════════════════════════════════════════════════════════════
# 测试场景
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TestCase:
    """测试用例。"""
    id: str
    questions: list[str]
    description: str
    # 评估标准：回答中应包含的关键词（验证记忆是否生效）
    # 每个 Q 的 expected_keywords
    expected_keywords_per_q: list[list[str]]


TEST_CASES = [
    TestCase(
        id="T1",
        questions=[
            "我的项目使用 FastAPI + SQLAlchemy，帮我生成一个 User 模型",
            "再添加一个 created_at 和 updated_at 字段",
            "刚才 User 模型的密码字段，应该用什么方式存储？",
        ],
        description="连续编码任务 — Q2 依赖 Q1 的文件，Q3 依赖 Q1+Q2",
        expected_keywords_per_q=[
            ["User", "SQLAlchemy", "model"],
            ["created_at", "updated_at"],
            ["password", "hash", "bcrypt"],  # 有记忆才能知道说的是 User.password
        ],
    ),
    TestCase(
        id="T2",
        questions=[
            "帮我 debug 这段代码: \ndef divide(a, b):\n    return a / b",
            "再考虑一下如果 b 是负数的情况",
            "综合前面的讨论，给出最终的完整函数",
        ],
        description="调试任务 — Q2 是 Q1 的补充，Q3 需要整合前两轮",
        expected_keywords_per_q=[
            ["divide", "ZeroDivisionError"],
            ["negative"],
            ["def divide", "ZeroDivisionError", "negative"],  # 有记忆才能综合
        ],
    ),
    TestCase(
        id="T3",
        questions=[
            "我喜欢 Python 和 Go 语言",
            "帮我写一个 HTTP 服务",
            "用我最喜欢的语言来写",
        ],
        description="偏好记忆 — Q3 依赖 Q1 中的用户偏好",
        expected_keywords_per_q=[
            ["Python", "Go"],
            ["HTTP", "server"],
            ["Python"],  # 有记忆才能记得用户偏好
        ],
    ),
]


async def run_comparison(llm_client: Any, db_path: Optional[str] = None):
    """运行对比测试。"""

    # ── 初始化两个 Agent ──
    simple = SimpleAgent(llm_client)
    memory = MemoryAgent(llm_client, db_path)

    # ── 对比报告 ──
    report_lines = [
        "=" * 80,
        "  记忆系统对比测试报告",
        "=" * 80,
        f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  LLM: {type(llm_client).__name__}",
        "-" * 80,
    ]

    all_results = []

    for case in TEST_CASES:
        print(f"\n{'=' * 60}")
        print(f"  测试用例: {case.id} — {case.description}")
        print(f"{'=' * 60}")

        case_lines = [
            f"\n{'─' * 70}",
            f"  测试用例 {case.id}: {case.description}",
            f"{'─' * 70}",
        ]

        case_results = {"id": case.id, "description": case.description, "rounds": []}
        total_quality_a = 0.0
        total_quality_b = 0.0

        # 逐个问题测试
        for q_idx, question in enumerate(case.questions):
            print(f"\n  Q{q_idx+1}: {question[:80]}...")

            # Agent A — 无记忆
            t0 = time.time()
            resp_a = await simple.chat(question)
            latency_a = (time.time() - t0) * 1000

            # Agent B — 有记忆
            t0 = time.time()
            resp_b = await memory.chat(question)
            latency_b = (time.time() - t0) * 1000

            # 评估关键词命中
            expected = case.expected_keywords_per_q[q_idx]
            hits_a = sum(1 for kw in expected if kw.lower() in str(resp_a).lower())
            hits_b = sum(1 for kw in expected if kw.lower() in str(resp_b).lower())
            quality_a = hits_a / len(expected) if expected else 0
            quality_b = hits_b / len(expected) if expected else 0
            total_quality_a += quality_a
            total_quality_b += quality_b

            round_info = {
                "question": question[:60],
                "quality_a": round(quality_a, 2),
                "quality_b": round(quality_b, 2),
                "latency_a_ms": round(latency_a, 0),
                "latency_b_ms": round(latency_b, 0),
                "keyword_hits_a": hits_a,
                "keyword_hits_b": hits_b,
            }
            case_results["rounds"].append(round_info)

            # 输出
            print(f"    ┌─ [无记忆] 关键词命中: {hits_a}/{len(expected)}  质量: {quality_a:.0%}  ({latency_a:.0f}ms)")
            print(f"    └─ [有记忆] 关键词命中: {hits_b}/{len(expected)}  质量: {quality_b:.0%}  ({latency_b:.0f}ms)")

            if q_idx >= 1:  # Q2+ 才体现记忆差异
                if quality_b > quality_a:
                    print(f"      ✅ 记忆系统生效: 质量提升 +{quality_b - quality_a:.0%}")
                elif quality_b == quality_a:
                    print(f"      ➖ 两者相当")
                else:
                    print(f"      ❓ 无记忆反而更好（可能当前轮次不需要记忆）")

        # 用例汇总
        avg_a = total_quality_a / len(case.questions)
        avg_b = total_quality_b / len(case.questions)
        case_results["avg_quality_a"] = round(avg_a, 2)
        case_results["avg_quality_b"] = round(avg_b, 2)
        case_results["improvement"] = round(avg_b - avg_a, 2)
        all_results.append(case_results)

        case_lines.append(f"  平均质量 — 无记忆: {avg_a:.1%}  |  有记忆: {avg_b:.1%}")
        improvement = avg_b - avg_a
        if improvement > 0.15:
            case_lines.append(f"  效果: ✅ 记忆系统显著提升 (Δ={improvement:.0%})")
        elif improvement > 0:
            case_lines.append(f"  效果: 📈 记忆系统略有提升 (Δ={improvement:.0%})")
        else:
            case_lines.append(f"  效果: ➖ 记忆系统效果不明显")
        report_lines.extend(case_lines)

    # ── 总报告 ──
    report_lines.extend([
        f"\n{'=' * 70}",
        "  总体结论",
        f"{'=' * 70}",
    ])

    total_avg_a = sum(r["avg_quality_a"] for r in all_results) / len(all_results)
    total_avg_b = sum(r["avg_quality_b"] for r in all_results) / len(all_results)
    total_improv = total_avg_b - total_avg_a

    report_lines.append(f"  全部测试平均质量:")
    report_lines.append(f"    无记忆系统: {total_avg_a:.1%}")
    report_lines.append(f"    有记忆系统: {total_avg_b:.1%}")
    report_lines.append(f"    提升幅度:   {total_improv:.1%}")

    if total_improv > 0.2:
        report_lines.append(f"\n  结论: ✅ 记忆系统效果显著 — 在连续对话场景中大幅提升回复质量")
    elif total_improv > 0.05:
        report_lines.append(f"\n  结论: 📈 记忆系统有效 — 对上下文依赖型任务有帮助")
    else:
        report_lines.append(f"\n  结论: ➖ 当前场景下记忆系统效果不明显 — 可能场景不够复杂")

    report_lines.append(f"\n{'=' * 80}")

    # 输出报告
    report = "\n".join(report_lines)
    print(f"\n{report}")

    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"memory_comparison_report_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存: {report_path}")

    await memory.close()


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os

    # 自动检测可用的 LLM（默认使用 DeepSeek）
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    db_path = os.environ.get("DATABASE_URL")

    if provider == "deepseek" or os.environ.get("DEEPSEEK_API_KEY"):
        from context_os.llm.deepseek_client import DeepSeekClient
        llm = DeepSeekClient()
        print("使用 LLM: DeepSeek")
    elif provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
        from context_os.llm.anthropic_client import AnthropicClient
        llm = AnthropicClient()
        print("使用 LLM: Anthropic Claude")
    elif provider == "openai" or os.environ.get("OPENAI_API_KEY"):
        from context_os.llm.openai_client import OpenAIClient
        llm = OpenAIClient()
        print("使用 LLM: OpenAI")
    else:
        print("错误: 未检测到 API Key。请设置 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY")
        print("或运行: $env:DEEPSEEK_API_KEY='sk-xxx'; python examples/memory_comparison.py")
        exit(1)

    if not db_path:
        print("提示: DATABASE_URL 未设置，记忆将使用 JSON 文件降级存储")
        print("     设置后记忆可持久化: $env:DATABASE_URL='./data/context_os.db'")
        print()

    asyncio.run(run_comparison(llm, db_path))
