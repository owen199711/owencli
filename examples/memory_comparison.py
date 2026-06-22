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
    # ──────────────────────────────────────────────────────────────
    # T5: 数值累积追踪 — 8 轮加减操作，最后问余额
    # 关键点：SimpleAgent 只保留最后 5 条历史（≈2 轮），
    # 一定会丢失早期的"初始余额"信息，必然算错。
    # 这正是 LTM 向量检索的用武之地。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T5",
        questions=[
            "我的钱包初始有 5 元，请记住这个数字。",
            "我刚花了 3 元买水，更新一下余额。",
            "又赚了 5 元，是帮同学跑腿的报酬。",
            "然后花了 2 元买零食。",
            "妈妈又给了我 10 元零花钱。",
            "我买了一本书花了 6 元。",
            "朋友还了我之前借的 4 元。",
            "最后我又买了杯奶茶花了 3 元，现在告诉我钱包里还剩多少钱？请给出计算过程。",
        ],
        description="长链数值累积 — 需要完整 8 轮历史才能算对，SimpleAgent 截断必丢初始值",
        expected_keywords_per_q=[
            ["5"],            # 初始余额
            ["2"],            # 5-3=2
            ["7"],            # 2+5=7
            ["5"],            # 7-2=5
            ["15"],           # 5+10=15
            ["9"],            # 15-6=9
            ["13"],           # 9+4=13
            ["10", "13", "-3"],  # 13-3=10，必须引用 13 这个中间结果
        ],
    ),

    # ──────────────────────────────────────────────────────────────
    # T6: 配置项多次变更 — 需追踪"最新值"
    # 关键点：同一配置在 7 轮中被反复修改，最终问当前值。
    # SimpleAgent 的截断会让 LLM 搞不清"最后一次修改到底是哪个"，
    # 容易给出已被覆盖的旧值。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T6",
        questions=[
            "把数据库连接池大小设为 10。",
            "把日志级别改成 DEBUG。",
            "数据库连接池大小改为 20。",
            "开启慢查询日志。",
            "日志级别改成 INFO，连接池改为 30。",
            "关闭慢查询日志。",
            "现在告诉我：当前数据库连接池大小、日志级别、慢查询日志状态分别是什么？",
        ],
        description="配置多次覆盖 — 必须按时间顺序追踪每次变更才能给出最新值",
        expected_keywords_per_q=[
            ["10", "pool"],
            ["DEBUG"],
            ["20"],
            ["slow", "query"],
            ["INFO", "30"],
            ["disable", "off", "close"],
            ["30", "INFO", "disabled", "off"],  # 最终: pool=30, log=INFO, slow=off
        ],
    ),

    # ──────────────────────────────────────────────────────────────
    # T7: 个人偏好演变 — 爱好/立场随时间反转
    # 核心挑战：同一属性被多次"反转更新"，最终问当前值 + 转变节点。
    # SimpleAgent 截断后，LLM 会把早期"讨厌"的状态当成现在的状态。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T7",
        questions=[
            "小明 5 岁时最讨厌吃蔬菜，尤其是西兰花，每次吃饭都哭。请记住他这个偏好。",
            "小明 10 岁时生了一场大病，医生建议多吃蔬菜增强免疫力，他开始尝试吃西兰花。",
            "13 岁时小明看了纪录片《奶牛阴谋》，决定成为素食主义者，西兰花成了他的最爱。",
            "18 岁小明去美国留学，室友是德州人，带他吃牛排后他开始重新吃肉，但仍然爱吃蔬菜。",
            "现在小明 25 岁。请告诉我：他现在对西兰花的态度？对肉类的态度？"
            "最初是从几岁开始转变的？经历过几次重大转变？",
        ],
        description="偏好多次反转 — Q5 需同时回答『当前状态』和『转变节点』",
        expected_keywords_per_q=[
            ["讨厌", "西兰花", "蔬菜"],
            ["尝试", "西兰花", "10"],
            ["素食", "西兰花", "13"],
            ["牛排", "肉", "18"],
            ["25", "西兰花", "转变", "10", "13", "18"],  # 必须列出所有转变节点
        ],
    ),

    # ──────────────────────────────────────────────────────────────
    # T8: 人际关系演变 — 从死对头到伴侣
    # 核心挑战：关系状态多次跃迁（敌对→和解→朋友→伴侣）。
    # SimpleAgent 截断后只能看到最后几轮，回答关系时会漏掉早期敌对史。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T8",
        questions=[
            "小明和小红是初中同桌，两人经常因为边界问题吵架，互相看不顺眼，是班里有名的死对头。",
            "高中分班后两人意外被分到同组做科技创新大赛项目，合作过程中发现彼此的优点，关系缓和。",
            "大学两人考进同一所学校不同专业，经常一起自习，成了好朋友。",
            "毕业后两人都在北京工作，合租了一套房子，日久生情，确定恋爱关系。",
            "去年国庆两人领证结婚了。"
            "现在请回顾：小明和小红的关系经历过哪几个阶段？"
            "最早是从哪个事件开始转变的？现在是什么关系？",
        ],
        description="关系多次跃迁 — Q5 需梳理完整关系演变时间线",
        expected_keywords_per_q=[
            ["死对头", "吵架", "初中"],
            ["合作", "缓和", "高中"],
            ["朋友", "大学"],
            ["恋爱", "合租", "北京"],
            ["结婚", "领证", "死对头", "朋友", "转变"],  # 必须覆盖起点和终点
        ],
    ),

    # ──────────────────────────────────────────────────────────────
    # T9: 职业理想多次转向 — 需要追踪"放弃的旧目标"
    # 核心挑战：每次更新都是"放弃 A，转向 B"，最终问被放弃的目标。
    # 这种"负向记忆"对 SimpleAgent 最难，因为它只看到最近的目标。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T9",
        questions=[
            "小明小学时的梦想是当科学家，最爱去科技馆，房间里贴满了爱因斯坦的海报。",
            "初中小明迷上了编程，参加了 NOIP 信息学竞赛拿了一等奖，梦想变成当程序员。",
            "高中小明的父亲生病，他受到医生照顾的感动，立志学医当外科医生。",
            "大学小明考进了医学院，但实习时发现自己晕血，转专业去学了医疗 AI，"
            "把编程和医学结合起来。",
            "现在请回答：小明先后放弃过哪些梦想？"
            "每次放弃的原因分别是什么？最终的职业方向是什么？",
        ],
        description="理想多次转向 — Q5 需回忆所有被放弃的目标及原因",
        expected_keywords_per_q=[
            ["科学家", "爱因斯坦"],
            ["编程", "程序员", "NOIP"],
            ["医生", "外科", "父亲"],
            ["AI", "晕血", "转专业"],
            ["科学家", "程序员", "医生", "AI", "放弃"],  # 必须列出全部被放弃的梦想
        ],
    ),

    # ──────────────────────────────────────────────────────────────
    # T10: 多属性并发演变 — 三个属性交错更新
    # 核心挑战：A/B/C 三个属性轮流变化，每轮只改一个。
    # 最终问三个属性的当前值 + 最后一次修改。
    # SimpleAgent 截断后极易把不同属性的修改混淆。
    # ──────────────────────────────────────────────────────────────
    TestCase(
        id="T10",
        questions=[
            "记录一下小明的状态：身高 120cm，体重 25kg，最喜欢的颜色是红色。",
            "小学毕业时长到 140cm了，体重 30kg。",
            "初中时迷上了蓝色，不再喜欢红色了。",
            "高中坚持打篮球，身高 175cm，体重 65kg。",
            "大学开始健身，体重涨到 75kg，但最喜欢颜色变成了黑色。",
            "工作后因为久坐没运动，体重涨到 80kg。",
            "最近开始减肥，体重回到 72kg，又喜欢上了绿色。"
            "现在请告诉我：小明当前的身高、体重、最喜欢的颜色分别是什么？"
            "每个属性分别修改过几次？",
        ],
        description="多属性并发演变 — SimpleAgent 极易混淆不同属性的修改历史",
        expected_keywords_per_q=[
            ["120", "25", "红"],
            ["140", "30"],
            ["蓝"],
            ["175", "65"],
            ["75", "黑"],
            ["80"],
            ["175", "72", "绿", "3", "4"],  # 身高=175(改3次), 体重=72(改4次), 颜色=绿
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
            print(f"    │  回复片段: {str(resp_a)[:150]}")
            print(f"    └─ [有记忆] 关键词命中: {hits_b}/{len(expected)}  质量: {quality_b:.0%}  ({latency_b:.0f}ms)")
            print(f"       回复片段: {str(resp_b)[:150]}")

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
