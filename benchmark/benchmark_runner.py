"""Benchmark 调度器 — 统筹 Module Test / Pipeline Test / Memory Test / Retriever Test。

执行流程:
    BenchmarkRunner
        ├── Module Test (逐模块断言)
        ├── Pipeline Test (全链路诊断输出)
        ├── Memory Benchmark (对比 SimpleAgent vs MemoryAgent)
        └── Retriever Benchmark (检索质量验证)
            │
            ▼
        EvaluationEngine → 多层评测
            │
            ▼
        ReportGenerator → JSON / HTML
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from benchmark.agents import MemoryAgent, SimpleAgent
from benchmark.assertions import (
    assert_builder,
    assert_collection,
    assert_intent,
    assert_memory_counts,
    assert_optimizer,
)
from benchmark.enhanced_assertions import (
    verify_builder,
    verify_collection,
    verify_feedback,
    verify_intent,
    verify_optimizer,
    verify_reflection,
    verify_tool_call,
)
from benchmark.evaluator import EvaluationEngine, MultiLayerEvalResult
from benchmark.metrics import MetricsCollector
from benchmark.observer import PipelineObserver
from benchmark.datasets.memory_cases import TestCase


@dataclass
class ModuleTestResult:
    """模块测试结果。"""
    module_name: str
    passed: bool
    details: dict
    sub_tests: list[dict] = field(default_factory=list)


@dataclass
class RoundDiagnostics:
    """单轮对话的完整诊断。"""
    round_idx: int
    question: str
    diagnostics: dict  # observer 输出
    response: str
    eval_result: Optional[MultiLayerEvalResult] = None
    simple_response: str = ""
    simple_eval: Optional[MultiLayerEvalResult] = None


@dataclass
class CaseResult:
    """单个测试用例结果。"""
    case_id: str
    description: str
    rounds: list[RoundDiagnostics] = field(default_factory=list)
    module_results: list[ModuleTestResult] = field(default_factory=list)
    avg_keyword_score: float = 0.0
    avg_judge_score: float = 0.0
    avg_final_score: float = 0.0
    simple_avg_score: float = 0.0
    # ── 回顾轮（最后一轮）专用分 — 唯一真正测试记忆召回的轮次 ──
    review_final_score: float = 0.0
    review_simple_score: float = 0.0
    passed: bool = False


class BenchmarkRunner:
    """Benchmark 调度器。"""

    def __init__(
        self,
        llm_client: Any,
        db_path: Optional[str] = None,
        llm_client_for_judge: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.db_path = db_path
        self.metrics_collector = MetricsCollector()
        self.eval_engine = EvaluationEngine(llm_client_for_judge or llm_client)
        self.results: dict[str, Any] = {}

        # 嵌入引擎（自动检测）
        self._embedding_provider = None
        try:
            from context_os.memory.embedding import EmbeddingServiceFactory
            self._embedding_provider = EmbeddingServiceFactory().create("auto")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Embedding provider init failed, semantic search disabled: %s", e
            )

    def _create_memory_agent(self) -> tuple:
        """创建 MemoryAgent 和 PipelineObserver（消除重复代码）。"""
        from benchmark.agents import MemoryAgent
        from benchmark.observer import PipelineObserver
        agent = MemoryAgent(
            self.llm_client, self.db_path,
            embedding_provider=self._embedding_provider,
        )
        observer = PipelineObserver(agent.pipeline)
        return agent, observer

    # ═══════════════════════════════════════════════════════════════
    # Module Test — 逐模块断言
    # ═══════════════════════════════════════════════════════════════

    async def run_module_test(
        self,
        user_input: str,
        warmup_questions: Optional[list[str]] = None,
    ) -> list[ModuleTestResult]:
        """对单条输入执行模块级测试。

        可在测试前先运行 warmup_questions 建立对话上下文和记忆，
        确保 Builder/Feedback 有真实数据可验证。

        Args:
            user_input: 测试问题。
            warmup_questions: 预热问题列表，会在测试前依次执行。

        Returns:
            ModuleTestResult 列表。
        """
        agent, observer = self._create_memory_agent()
        results = []

        warmup_count = len(warmup_questions) if warmup_questions else 0

        try:
            # 预热轮次
            if warmup_questions:
                for wq in warmup_questions:
                    await observer.observe_run(wq)

            # 正式测试
            _, diag = await observer.observe_run(user_input)

            # ── Intent Layer ──
            if "intent" in diag and "error" not in diag["intent"]:
                details = diag["intent"]
                has_intent = details.get("intent", "") != ""
                has_entities = details.get("entity_count", 0) > 0
                results.append(ModuleTestResult(
                    module_name="Intent",
                    passed=has_intent,
                    details=details,
                    sub_tests=[
                        {"name": "意图分类", "passed": has_intent, "value": details["intent"]},
                        {"name": "实体抽取", "passed": has_entities, "count": details.get("entity_count", 0)},
                    ],
                ))

            # ── Collection Layer ──
            if "collection" in diag and "error" not in diag["collection"]:
                col = diag["collection"]
                has_conversation = col.get("conversation_turns", 0) > 0
                has_identity = col.get("identity_present", False)
                results.append(ModuleTestResult(
                    module_name="Collection",
                    passed=has_conversation,
                    details=col,
                    sub_tests=[
                        {"name": "对话历史", "passed": has_conversation, "turns": col.get("conversation_turns", 0)},
                        {"name": "身份信息", "passed": has_identity},
                    ],
                ))

            # ── Builder Layer ──
            if "builder" in diag and "error" not in diag["builder"]:
                b = diag["builder"]
                memory_count = b.get("memory_count", 0)
                memory_types = b.get("memory_by_type", {})
                # 预热后应能检索到记忆；若 0 轮预热且 memory=0，这不算失败（空数据库正常）
                if warmup_count > 0:
                    passed = memory_count > 0
                else:
                    passed = True  # 无预热时不检查 Builder
                    if memory_count == 0:
                        results.append(ModuleTestResult(
                            module_name="Builder",
                            passed=True,
                            details={
                                "memory_count": 0,
                                "memory_by_type": {},
                                "note": "无预热轮次，空数据库不判 fail",
                            },
                            sub_tests=[
                                {"name": "记忆检索", "passed": True, "count": 0, "note": "未测试（无预热）"},
                            ],
                        ))
                        # 跳过 Builder 主检查
                        pass
                if not (warmup_count == 0 and memory_count == 0):
                    results.append(ModuleTestResult(
                        module_name="Builder",
                        passed=passed,
                        details={
                            "memory_count": memory_count,
                            "memory_by_type": memory_types,
                        },
                        sub_tests=[
                            {"name": "记忆检索", "passed": passed, "count": memory_count},
                            {"name": "记忆类型分布", "passed": len(memory_types) > 0, "types": memory_types},
                        ],
                    ))

            # ── Optimizer Layer ──
            if "optimizer" in diag and "error" not in diag["optimizer"]:
                o = diag["optimizer"]
                compressed = o.get("compressed", False)
                token_before = o.get("token_before", 0)
                token_after = o.get("token_after", 0)
                reduction = token_before - token_after
                passed = compressed and reduction > 0
                results.append(ModuleTestResult(
                    module_name="Optimizer",
                    passed=passed,
                    details={
                        "compressed": compressed,
                        "token_before": token_before,
                        "token_after": token_after,
                        "token_reduced": reduction,
                    },
                    sub_tests=[
                        {"name": "压缩", "passed": passed, "ratio": o.get("compression_ratio", 0)},
                        {"name": "预算分配", "passed": o.get("token_budget_total", 0) > 0,
                         "budget": o.get("token_budget_total", 0)},
                    ],
                ))

            # ── Packager Layer ──
            if "packager" in diag and "error" not in diag["packager"]:
                pkg = diag["packager"]
                has_prompt = pkg.get("prompt_length_chars", 0) > 0
                has_sections = len(pkg.get("sections", [])) > 0
                passed = has_prompt and has_sections
                results.append(ModuleTestResult(
                    module_name="Packager",
                    passed=passed,
                    details={
                        "prompt_chars": pkg.get("prompt_length_chars", 0),
                        "sections": pkg.get("sections", []),
                    },
                    sub_tests=[
                        {"name": "Prompt 生成", "passed": has_prompt},
                        {"name": "Section 数量", "passed": has_sections, "sections": pkg.get("sections", [])},
                    ],
                ))

            # ── Feedback Layer ──
            if "feedback" in diag and "error" not in diag["feedback"]:
                fb = diag["feedback"]
                has_quality = fb.get("answer_quality", 0) > 0
                has_reward = fb.get("reward_score", 0) > 0
                # 无预热时放宽标准：只要 quality 存在即可（可能很低）
                if warmup_count == 0:
                    passed = True  # 无预热时不严格检查 Feedback
                else:
                    passed = has_quality and has_reward

                results.append(ModuleTestResult(
                    module_name="Feedback",
                    passed=passed,
                    details={
                        "answer_quality": fb.get("answer_quality", 0),
                        "reward_score": fb.get("reward_score", 0),
                        "cost_usd": fb.get("cost_usd", 0),
                    },
                    sub_tests=[
                        {"name": "质量评估", "passed": has_quality or warmup_count == 0,
                         "quality": fb.get("answer_quality", 0)},
                        {"name": "Reward", "passed": has_reward or warmup_count == 0,
                         "reward": fb.get("reward_score", 0)},
                    ],
                ))

            # ── 延迟分解 ──
            if "latency_breakdown" in diag:
                results.append(ModuleTestResult(
                    module_name="Performance",
                    passed=diag.get("total_latency_ms", 0) > 0,
                    details={
                        "total_ms": diag.get("total_latency_ms", 0),
                        "breakdown_ms": diag.get("latency_breakdown", {}),
                    },
                    sub_tests=[
                        {"name": name, "passed": True, "latency_ms": lat}
                        for name, lat in diag.get("latency_breakdown", {}).items()
                    ],
                ))

        finally:
            await agent.close()

        return results

    # ═══════════════════════════════════════════════════════════════
    # Pipeline Test — 全链路诊断输出
    # ═══════════════════════════════════════════════════════════════

    async def run_pipeline_test(
        self,
        user_input: str,
    ) -> tuple[str, dict, list[ModuleTestResult]]:
        """执行一次全 Pipeline 测试。

        Returns:
            (response, diagnostics, module_results)
        """
        agent, observer = self._create_memory_agent()

        try:
            response, diag = await observer.observe_run(user_input)
            module_results = await self.run_module_test(user_input)
            return response, diag, module_results
        finally:
            await agent.close()

    # ═══════════════════════════════════════════════════════════════
    # Memory Benchmark — SimpleAgent vs MemoryAgent 对比
    # ═══════════════════════════════════════════════════════════════

    async def run_memory_benchmark(
        self,
        test_case: TestCase,
    ) -> CaseResult:
        """运行一个完整的记忆对比测试用例。

        对每个问题:
            1. SimpleAgent 回答（无记忆）
            2. MemoryAgent + Observer 回答（有记忆 + 诊断）
            3. 多层评测
            4. 模块测试
        """
        print(f"\n{'=' * 60}")
        print(f"  Test Case: {test_case.id} — {test_case.description}")
        print(f"{'=' * 60}")

        simple = SimpleAgent(self.llm_client)
        memory, observer = self._create_memory_agent()

        case_result = CaseResult(
            case_id=test_case.id,
            description=test_case.description,
        )

        try:
            for q_idx, question in enumerate(test_case.questions):
                print(f"\n  Q{q_idx+1}/{len(test_case.questions)}: {question[:80]}...")

                # SimpleAgent
                resp_simple = await simple.chat(question)

                # MemoryAgent with diagnostics
                resp_memory, diag = await observer.observe_run(question)

                # 仅在最终回顾轮启用 LLM Judge（避免对数据录入轮误判）
                is_review_q = (q_idx == len(test_case.questions) - 1)
                eval_ground_truth = test_case.ground_truth if is_review_q else ""
                eval_expected_json = test_case.expected_json if is_review_q else None

                # 多层评测（有记忆）
                eval_result = await self.eval_engine.evaluate(
                    response=resp_memory,
                    question=question,
                    expected_keywords=test_case.expected_keywords_per_q[q_idx],
                    ground_truth=eval_ground_truth,
                    expected_json=eval_expected_json,
                )

                # 多层评测（无记忆）
                simple_eval = await self.eval_engine.evaluate(
                    response=resp_simple,
                    question=question,
                    expected_keywords=test_case.expected_keywords_per_q[q_idx],
                    ground_truth=eval_ground_truth,
                    expected_json=eval_expected_json,
                )

                round_diag = RoundDiagnostics(
                    round_idx=q_idx,
                    question=question,
                    diagnostics=diag,
                    response=resp_memory,
                    eval_result=eval_result,
                    simple_response=resp_simple,
                    simple_eval=simple_eval,
                )
                case_result.rounds.append(round_diag)

                # 打印简版结果
                kw = eval_result.keyword_score
                judge = eval_result.judge_score
                final_s = eval_result.final_score
                simple_final = simple_eval.final_score
                lat = diag.get("total_latency_ms", 0)
                print(f"    ├─ SimpleAgent: {simple_eval.keyword_score:.0%} kw / {simple_final:.1%} final")
                print(f"    └─ MemoryAgent: {kw:.0%} kw / {final_s:.1%} final  ({lat:.0f}ms)")
                if final_s > simple_final:
                    print(f"      ✅ 记忆系统生效: Δ={final_s - simple_final:.1%}")
                elif final_s < simple_final:
                    print(f"      ⚠️ 无记忆反而更好: Δ={simple_final - final_s:.1%}")

            # 计算平均分（所有轮次）
            eval_rounds = [r for r in case_result.rounds if r.eval_result]
            if eval_rounds:
                case_result.avg_keyword_score = sum(
                    r.eval_result.keyword_score for r in eval_rounds
                ) / len(eval_rounds)
                case_result.avg_judge_score = sum(
                    r.eval_result.judge_score for r in eval_rounds
                ) / len(eval_rounds)
                case_result.avg_final_score = sum(
                    r.eval_result.final_score for r in eval_rounds
                ) / len(eval_rounds)
                case_result.simple_avg_score = sum(
                    r.simple_eval.final_score for r in eval_rounds if r.simple_eval
                ) / len(eval_rounds)

            # 计算回顾轮专分（最后一轮 — 唯一真正测试记忆召回的轮次）
            if case_result.rounds:
                review = case_result.rounds[-1]
                if review.eval_result:
                    case_result.review_final_score = review.eval_result.final_score
                if review.simple_eval:
                    case_result.review_simple_score = review.simple_eval.final_score

                # 回顾轮对比摘要
                if review.eval_result and review.simple_eval:
                    r_final = case_result.review_final_score
                    r_simple = case_result.review_simple_score
                    delta = r_final - r_simple
                    direction = "✅ +" if delta > 0 else ("⚠️ " if delta < 0 else "= ")
                    print(f"\n  📊 Review Round: Memory={r_final:.0%}  Simple={r_simple:.0%}  Δ={direction}{delta:+.0%}")

            # 模块测试（用第一轮的诊断）
            if case_result.rounds:
                first_diag = case_result.rounds[0].diagnostics
                case_result.module_results = self._diagnostics_to_module_results(first_diag)

            case_result.passed = case_result.review_final_score >= 0.6

        finally:
            await memory.close()

        return case_result

    def _diagnostics_to_module_results(self, diag: dict) -> list[ModuleTestResult]:
        """从 diagnostics 中提取模块测试结果。"""
        results = []

        for module in ["intent", "collection", "builder", "optimizer", "packager", "feedback"]:
            if module in diag and "error" not in diag.get(module, {}):
                data = diag[module]
                results.append(ModuleTestResult(
                    module_name=module.capitalize(),
                    passed=True,
                    details=data,
                ))
            elif module in diag:
                results.append(ModuleTestResult(
                    module_name=module.capitalize(),
                    passed=False,
                    details=diag.get(module, {"error": "unknown"}),
                ))

        return results

    # ═══════════════════════════════════════════════════════════════
    # Retriever Benchmark — 检索质量验证
    # ═══════════════════════════════════════════════════════════════

    async def run_retriever_benchmark(self, query: str) -> dict:
        """运行检索器质量测试。"""
        agent, observer = self._create_memory_agent()

        try:
            _, diag = await observer.observe_run(query)
            builder = diag.get("builder", {})
            memory_items = builder.get("memory_items", [])
            memory_by_type = builder.get("memory_by_type", {})

            # 统计检索结果
            total_retrieved = len(memory_items)
            type_counts = memory_by_type

            return {
                "query": query,
                "total_retrieved": total_retrieved,
                "by_type": type_counts,
                "retrieved_items": memory_items[:10],  # 最多 10 条
                "latency_ms": diag.get("latency_breakdown", {}).get("builder", 0),
            }
        finally:
            await agent.close()

    # ═══════════════════════════════════════════════════════════════
    # Intent Benchmark — 意图分类验证
    # ═══════════════════════════════════════════════════════════════

    async def run_intent_benchmark(
        self,
        test_case: TestCase,
    ) -> dict:
        """运行意图分类验证测试。

        对每个问题，验证 Intent Layer 输出的意图是否匹配 expected_intent。

        Returns:
            dict with scores and details.
        """
        print(f"\n  Intent Test: {test_case.id} — {test_case.description}")
        agent, observer = self._create_memory_agent()

        intent_scores = []
        intent_details = []

        try:
            for q_idx, question in enumerate(test_case.questions):
                expected = test_case.expected_intent[q_idx] if test_case.expected_intent and q_idx < len(test_case.expected_intent) else None

                _, diag = await observer.observe_run(question)
                actual_intent = diag.get("intent", {}).get("intent", "unknown")

                if expected:
                    score, det = verify_intent(actual_intent, expected, question=question)
                else:
                    score, det = 0.5, {"note": "无期望意图"}

                intent_scores.append(score)
                intent_details.append({
                    "question": question[:60],
                    "expected": expected,
                    "actual": actual_intent,
                    "score": score,
                    "match": det.get("match", False),
                    "mapped_functional": det.get("mapped_functional", ""),
                    "inferred_from_text": det.get("inferred_from_text", ""),
                })

                match_icon = "✅" if det.get("match") else "❌"
                print(f"    Q{q_idx+1}: expected={expected:12s} system={actual_intent:16s} mapped={det.get('mapped_functional',''):12s} inferred={det.get('inferred_from_text',''):12s} {match_icon}")

            avg_score = sum(intent_scores) / len(intent_scores) if intent_scores else 0
            print(f"    Intent Accuracy: {avg_score:.1%}")

        finally:
            await agent.close()

        return {
            "case_id": test_case.id,
            "avg_intent_accuracy": round(avg_score, 3),
            "details": intent_details,
        }

    # ═══════════════════════════════════════════════════════════════
    # Reflection Test — 反思/分析能力验证
    # ═══════════════════════════════════════════════════════════════

    async def run_reflection_test(self) -> dict:
        """运行反思能力测试。

        构造需要分析原因的提问，验证 LLM 回复是否包含反思内容。
        """
        print(f"\n  Reflection Test — 验证失败→反思→改进循环")

        reflection_questions = [
            "为什么我的数据库连接总是超时？分析一下可能的原因",
            "昨天的系统部署失败了，帮我分析一下失败的原因和改进方案",
        ]

        agent, _ = self._create_memory_agent()

        scores = []

        try:
            for q_idx, question in enumerate(reflection_questions):
                resp = await agent.chat(question)
                score, det = verify_reflection(resp, expected_reflection=True)
                scores.append(score)

                print(f"    Q{q_idx+1}: reflection={det['has_reflection']}, improvement={det['has_improvement']} Score={score:.1%}")

            avg_score = sum(scores) / len(scores) if scores else 0
            print(f"    Reflection Avg: {avg_score:.1%}")

        finally:
            await agent.close()

        return {
            "avg_reflection_score": round(avg_score, 3),
            "details": [{"question": q, "score": s} for q, s in zip(reflection_questions, scores)],
        }

    # ═══════════════════════════════════════════════════════════════
    # Stress Test — Optimizer 压力测试
    # ═══════════════════════════════════════════════════════════════

    async def run_stress_test(self) -> dict:
        """运行 Optimizer 压力测试。

        注入大量事实（100+），验证:
        1. Builder 是否正确去重/排序
        2. Optimizer 是否压缩到预算内
        3. Token 预算分配是否合理
        """
        print(f"\n  Stress Test — Optimizer 大 Context 压力测试")

        # 构造 50 个事实的大输入
        facts = [f"指标{i}=值{i}" for i in range(50)]
        stress_input = "请记住以下所有监控指标：" + "，".join(facts[:20])
        stress_input2 = "再记住这些：" + "，".join(facts[20:40])
        stress_input3 = "最后这些：" + "，".join(facts[40:50])

        agent, observer = self._create_memory_agent()

        try:
            # 注入所有事实
            for inp in [stress_input, stress_input2, stress_input3]:
                await observer.observe_run(inp)

            # 查询所有指标
            resp, diag = await observer.observe_run("现在所有指标的值分别是多少？")

            optimizer_diag = diag.get("optimizer", {})
            token_before = optimizer_diag.get("token_before", 0)
            token_after = optimizer_diag.get("token_after", 0)
            compressed = optimizer_diag.get("compressed", False)

            score, det = verify_optimizer(
                token_before=token_before,
                token_after=token_after,
                budget_total=128000,
                expect_compression=True,
            )

            print(f"    Token Before: {token_before}")
            print(f"    Token After:  {token_after}")
            print(f"    Compressed:   {compressed}")
            print(f"    Compression:  {det.get('compression_ratio', 0):.1%}")
            print(f"    Score:        {score:.1%}")

        finally:
            await agent.close()

        return {
            "token_before": token_before,
            "token_after": token_after,
            "compressed": compressed,
            "compression_ratio": det.get("compression_ratio", 0),
            "optimizer_score": score,
        }

    # ═══════════════════════════════════════════════════════════════
    # 评分仪表盘
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_scoring_dashboard(results: dict[str, Any]) -> dict[str, Any]:
        """计算总体评分仪表盘。

        评分维度:
            - Intent: 意图分类准确率
            - Collection: Context 收集完整性
            - Builder: 记忆构建质量
            - Memory: 记忆对比得分
            - Recall: 检索召回质量
            - Compression: 压缩效果
            - Feedback: 评估质量
            - Tool: 工具调用
            - Pipeline: 端到端延迟

        Returns:
            dict with per-module scores and overall grade.
        """
        dashboard = {}

        # Intent Score
        intent_results = results.get("intent_benchmarks", [])
        if intent_results:
            dashboard["intent"] = sum(r["avg_intent_accuracy"] for r in intent_results) / len(intent_results)
        else:
            dashboard["intent"] = 0.0

        # Memory Score（使用回顾轮专分 — 唯一真正测试记忆召回的轮次）
        mem_benchmarks = results.get("memory_benchmarks", [])
        if mem_benchmarks:
            dashboard["memory"] = sum(m["review_final_score"] for m in mem_benchmarks) / len(mem_benchmarks)
        else:
            dashboard["memory"] = 0.0

        # Module scores
        module_tests = results.get("module_tests", [])
        module_scores = {"Collection": [], "Builder": [], "Feedback": [], "Optimizer": []}
        for mt in module_tests:
            for mod in mt.get("modules", []):
                name = mod.get("name", "")
                if name in module_scores:
                    module_scores[name].append(1.0 if mod.get("passed") else 0.0)

        for name, scores in module_scores.items():
            dashboard[name.lower()] = sum(scores) / len(scores) if scores else None  # None = 未测试

        # Retriever / Recall
        ret_results = results.get("retriever_benchmarks", [])
        if ret_results:
            recall_scores = []
            for r in ret_results:
                total = r.get("total_retrieved", 0)
                recall_scores.append(min(1.0, total / 5.0))
            dashboard["recall"] = sum(recall_scores) / len(recall_scores) if recall_scores else None
        else:
            dashboard["recall"] = None

        # Compression
        stress_results = results.get("stress_test", {})
        if stress_results:
            dashboard["compression"] = stress_results.get("optimizer_score", None)
        else:
            dashboard["compression"] = None

        # Reflection
        reflection_results = results.get("reflection_test", {})
        if reflection_results:
            dashboard["reflection"] = reflection_results.get("avg_reflection_score", None)
        else:
            dashboard["reflection"] = None

        # Pipeline
        pipeline_tests = results.get("pipeline_tests", [])
        if pipeline_tests:
            latencies = [p.get("latency_ms", 0) for p in pipeline_tests]
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            if avg_lat < 1000:
                dashboard["pipeline"] = 1.0
            elif avg_lat < 2000:
                dashboard["pipeline"] = 0.8
            elif avg_lat < 3000:
                dashboard["pipeline"] = 0.6
            else:
                dashboard["pipeline"] = max(0.3, 1.0 - avg_lat / 10000)
        else:
            dashboard["pipeline"] = None

        # Tool (requires explicit tool tests)
        dashboard["tool"] = None

        # 计算综合分 —— 只加权已测试的维度
        weights = {
            "intent": 0.10, "collection": 0.10, "builder": 0.10,
            "memory": 0.15, "recall": 0.10, "compression": 0.10,
            "feedback": 0.10, "reflection": 0.05, "pipeline": 0.10, "tool": 0.10,
        }

        weighted_sum = 0.0
        total_weight = 0.0
        for key, weight in weights.items():
            score = dashboard.get(key)
            if score is not None:  # 跳过未测试的维度
                weighted_sum += score * weight
                total_weight += weight
            else:
                dashboard[f"{key}_status"] = "未测试"

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        # 等级
        if overall >= 0.95:
            grade = "A+"
        elif overall >= 0.90:
            grade = "A"
        elif overall >= 0.80:
            grade = "B+"
        elif overall >= 0.70:
            grade = "B"
        elif overall >= 0.60:
            grade = "C+"
        elif overall >= 0.50:
            grade = "C"
        else:
            grade = "D"

        dashboard["overall"] = round(overall, 4)
        dashboard["grade"] = grade
        dashboard["weights"] = weights

        return dashboard

    # ═══════════════════════════════════════════════════════════════
    # 全量运行
    # ═══════════════════════════════════════════════════════════════

    async def run_all(
        self,
        test_cases: Optional[list[TestCase]] = None,
        intent_cases: Optional[list[TestCase]] = None,
        run_module: bool = True,
        run_pipeline: bool = True,
        run_memory: bool = True,
        run_intent: bool = True,
        run_reflection: bool = True,
        run_stress: bool = True,
        run_retriever: bool = True,
    ) -> dict[str, Any]:
        """运行完整的 Benchmark。"""
        from benchmark.datasets import MEMORY_TEST_CASES, INTENT_TEST_CASES

        test_cases = test_cases or MEMORY_TEST_CASES
        intent_cases = intent_cases or INTENT_TEST_CASES

        results = {
            "started_at": datetime.now().isoformat(),
            "module_tests": [],
            "pipeline_tests": [],
            "memory_benchmarks": [],
            "retriever_benchmarks": [],
            "intent_benchmarks": [],
            "reflection_test": {},
            "stress_test": {},
            "dashboard": {},
            "summary": {},
        }

        # Module Test
        if run_module:
            print("\n" + "█" * 60)
            print("  Module Test — 逐模块断言")
            print("█" * 60)
            for tc in test_cases[:3]:
                # 用前 3 个问题做预热，用第 4 个问题做正式测试
                warmup = tc.questions[1:4] if len(tc.questions) > 4 else tc.questions[1:min(len(tc.questions), 4)]
                test_q = tc.questions[min(4, len(tc.questions) - 1)]
                mod_results = await self.run_module_test(test_q, warmup_questions=warmup)
                results["module_tests"].append({
                    "case_id": tc.id,
                    "modules": [
                        {"name": m.module_name, "passed": m.passed, "details": m.details}
                        for m in mod_results
                    ],
                })
                passed_count = sum(1 for m in mod_results if m.passed)
                total_count = len(mod_results)
                print(f"  {tc.id}: {passed_count}/{total_count} modules passed")

        # Pipeline Test
        if run_pipeline:
            print("\n" + "█" * 60)
            print("  Pipeline Test — 全链路诊断")
            print("█" * 60)
            demo_input = "你好，请记住我的名字是小明，我喜欢绿色"
            resp, diag, mod_results = await self.run_pipeline_test(demo_input)
            results["pipeline_tests"].append({
                "input": demo_input,
                "response": resp[:200],
                "latency_ms": diag.get("total_latency_ms", 0),
                "breakdown": diag.get("latency_breakdown", {}),
                "modules": [
                    {"name": m.module_name, "passed": m.passed}
                    for m in mod_results
                ],
            })
            bd = diag.get("latency_breakdown", {})
            timeline = " → ".join(f"{k}={v:.0f}ms" for k, v in sorted(bd.items()))
            print(f"  Pipeline Timeline: {timeline}")
            print(f"  Total: {diag.get('total_latency_ms', 0):.0f}ms")

        # Memory Benchmark
        if run_memory:
            print("\n" + "█" * 60)
            print("  Memory Benchmark — SimpleAgent vs MemoryAgent")
            print("█" * 60)
            for tc in test_cases:
                case_result = await self.run_memory_benchmark(tc)
                results["memory_benchmarks"].append({
                    "case_id": tc.id,
                    "description": tc.description,
                    "avg_keyword_score": case_result.avg_keyword_score,
                    "avg_judge_score": case_result.avg_judge_score,
                    "avg_final_score": case_result.avg_final_score,
                    "simple_avg_score": case_result.simple_avg_score,
                    # 回顾轮专分（唯一真正测试记忆召回的轮次）
                    "review_final_score": case_result.review_final_score,
                    "review_simple_score": case_result.review_simple_score,
                    "passed": case_result.passed,
                    "round_count": len(case_result.rounds),
                })

        # Intent Benchmark
        if run_intent:
            print("\n" + "█" * 60)
            print("  Intent Benchmark — 意图分类验证")
            print("█" * 60)
            for tc in intent_cases:
                result = await self.run_intent_benchmark(tc)
                results["intent_benchmarks"].append(result)

        # Reflection Test
        if run_reflection:
            print("\n" + "█" * 60)
            print("  Reflection Test — 反思分析能力")
            print("█" * 60)
            result = await self.run_reflection_test()
            results["reflection_test"] = result

        # Stress Test
        if run_stress:
            print("\n" + "█" * 60)
            print("  Stress Test — Optimizer 压力测试")
            print("█" * 60)
            result = await self.run_stress_test()
            results["stress_test"] = result

        # Retriever Benchmark
        if run_retriever:
            print("\n" + "█" * 60)
            print("  Retriever Benchmark — 检索质量")
            print("█" * 60)
            for tc in test_cases[:3]:
                ret = await self.run_retriever_benchmark(tc.questions[0])
                results["retriever_benchmarks"].append(ret)
                by_type = ret.get("by_type", {})
                type_str = ", ".join(f"{k}={v}" for k, v in by_type.items())
                print(f"  {tc.id}: retrieved={ret['total_retrieved']} ({type_str})")

        # 评分仪表盘
        dashboard = self._compute_scoring_dashboard(results)
        results["dashboard"] = dashboard

        # 汇总（使用回顾轮专分计算记忆改善）
        mem_scores = [m["review_final_score"] for m in results["memory_benchmarks"]]
        simple_scores = [m["review_simple_score"] for m in results["memory_benchmarks"]]
        modules_passed = sum(
            1 for mt in results["module_tests"] for m in mt["modules"] if m["passed"]
        )
        modules_total = sum(
            len(mt["modules"]) for mt in results["module_tests"]
        )

        results["summary"] = {
            "memory_avg_final_score": sum(mem_scores) / len(mem_scores) if mem_scores else 0,
            "simple_avg_final_score": sum(simple_scores) / len(simple_scores) if simple_scores else 0,
            "memory_improvement": (
                sum(mem_scores) / len(mem_scores) - sum(simple_scores) / len(simple_scores)
            ) if mem_scores and simple_scores else 0,
            "module_pass_rate": (modules_passed / modules_total) if modules_total > 0 else 0,
            "total_test_cases": len(test_cases),
            "memory_test_cases_passed": sum(1 for m in results["memory_benchmarks"] if m["passed"]),
            "overall_score": dashboard.get("overall", 0),
            "grade": dashboard.get("grade", "N/A"),
        }

        self.results = results
        return results
