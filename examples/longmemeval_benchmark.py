"""LongMemEval 基准测试 — 在公开长期记忆数据集上评估 Context-OS。

数据集: https://huggingface.co/datasets/xiaowu0162/longmemeval
论文:  LongMemEval: Benchmarking Chat Assistants on Long-Term
       Interactive Memory (ICLR 2025)

数据集结构:
    - 500 个评估实例
    - 6 种问题类型: single-session-user/assistant/preference,
      multi-session, temporal-reasoning, knowledge-update
    - 每个实例包含 haystack_sessions (多轮历史对话) + question + answer

评估流程:
    对每个实例:
        1. 把 haystack_sessions 逐个喂给 agent（模拟多 session 对话）
        2. 然后问 question
        3. 对比 agent 回复和标准 answer

运行:
    python examples/longmemeval_benchmark.py
    python examples/longmemeval_benchmark.py --max-eval 20  # 只跑前 20 题
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════
# Agent 封装 — 复用 memory_comparison 的实现
# ═══════════════════════════════════════════════════════════════════

class SimpleAgent:
    """无记忆 Agent — 简单拼接对话历史。"""

    def __init__(self, llm_client: Any, max_history_turns: int = 10):
        self.llm_client = llm_client
        self.max_history_turns = max_history_turns
        self.history: list[dict] = []

    async def ingest_session(self, turns: list[dict]) -> None:
        """摄入一个 session 的对话。"""
        for t in turns:
            self.history.append({"role": t["role"], "content": t["content"]})

    async def answer(self, question: str) -> str:
        """根据历史回答问题。"""
        # 只保留最后 N 轮
        recent = self.history[-self.max_history_turns:]
        ctx_lines = [f"{h['role']}: {h['content']}" for h in recent]
        prompt = (
            "You are a helpful assistant. Based on the conversation history below, "
            "answer the user's question concisely.\n\n"
            "Conversation history:\n" + "\n".join(ctx_lines) +
            f"\n\nQuestion: {question}\nAnswer:"
        )
        resp = await self.llm_client.complete(prompt, max_tokens=500)
        return str(resp).strip()

    def reset(self) -> None:
        self.history.clear()


class MemoryAgent:
    """Context-OS 完整记忆系统 Agent。"""

    def __init__(self, llm_client: Any, db_path: Optional[str] = None, inspect: bool = False):
        from context_os.pipeline import ContextOSPipeline
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

        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        self.pipeline = ContextOSPipeline(
            llm_client=llm_client,
            provider=provider,
            db_path=db_path,
            session_id=f"lme-{ts}",
            user_id="lme-test",
        )
        self._initialized = False
        self._inspect = inspect
        self._suppress_inspect = False  # ingest 时设为 True 避免刷屏
        # 用于存储中间状态的钩子
        self._last_ltm_results: list = []
        self._last_unified_context = None
        self._last_optimized_context = None
        self._last_packaged_context = None
        self._last_task = None

    async def _ensure(self) -> None:
        if not self._initialized:
            await self.pipeline._ensure_store()
            # 安装钩子：在 inspect 模式下捕获中间状态
            if self._inspect:
                self._install_hooks()
            self._initialized = True

    def _install_hooks(self) -> None:
        """在 pipeline 上安装钩子，捕获中间状态。"""
        store = self.pipeline.store

        # 钩子1：捕获 LTM 检索结果
        original_retrieve = self.pipeline.long_term_memory.retrieve

        async def hooked_retrieve(query, top_k=5, memory_type=None, embedding=None):
            items = await original_retrieve(query, top_k, memory_type, embedding)
            self._last_ltm_results = items
            return items

        self.pipeline.long_term_memory.retrieve = hooked_retrieve

        # 钩子2：捕获 UnifiedContext、OptimizedContext、PackagedContext
        original_run = self.pipeline.run

        async def hooked_run(user_input):
            await self.pipeline._ensure_store()
            self.pipeline.conversation.add_turn(role="user", content=user_input)
            from context_os.pipeline import time as _time
            tracer_id = self.pipeline.tracer.start(task_id="", raw_input=user_input)
            pstart = _time.time()

            try:
                # Step 1: Intent
                task = await self.pipeline.task_parser.parse(user_input)

                # Step 2: Build
                unified = await self.pipeline.builder.build(task)
                self._last_unified_context = unified
                self._last_task = task

                # ▶ 打印中间状态（仅 answer 阶段打印，ingest 时不刷屏）
                if not self._suppress_inspect:
                    print()
                    print("═" * 100)
                    print(f"  ▶ [INSPECT] 原始上下文 (UnifiedContext)")
                    print(f"  ▶ 用户问题: {user_input}")
                    print(f"  ▶ TaskSpec: intent={task.intent.value}, goal={task.goal.value}")
                    print(f"  ▶ 身份: {'✅' if unified.identity else '❌'}  "
                          f"对话: {f'{len(unified.conversation.history)}轮' if unified.conversation else '❌'}  "
                          f"环境: {'✅' if unified.environment else '❌'}")
                    if unified.memory:
                        print(f"  ▶ 检索到的记忆 (LTM): {len(unified.memory)} 条")
                        for i, m in enumerate(unified.memory):
                            print(f"    [{i+1}] type={m.type.value} score={m.relevance_score:.3f}")
                            print(f"        content: {m.content[:500]}")
                    else:
                        print(f"  ▶ 检索到的记忆 (LTM): 未检索到记忆 (共 {len(self._last_ltm_results)} 条)")
                    print()

                # Step 3: Optimize
                optimized = await self.pipeline.optimizer.optimize(unified, task)
                self._last_optimized_context = optimized

                # Step 4: Pack
                packaged = self.pipeline.packager.pack(optimized, self.pipeline.provider)
                self._last_packaged_context = packaged

                # ▶ 打印最终 prompt（仅 answer 阶段）
                if not self._suppress_inspect:
                    print(f"  ▶ [INSPECT] 最终 Prompt (发送给 LLM)")
                    print(f"  ▶ 长度: {len(packaged.raw_prompt)} chars")
                    print(f"  ▶ sections: {list(packaged.sections.keys())}")
                    for sec_name, sec_content in packaged.sections.items():
                        print(f"    ┌─ [{sec_name}] ──")
                        for line in sec_content.split("\n"):
                            print(f"    │ {line}")
                        print(f"    └─")
                    print()

                # Step 5: LLM
                llm_response = await self.pipeline.llm_client.complete(packaged.raw_prompt)
                llm_latency = (_time.time() - pstart) * 1000

                # 记录 assistant 回复（必须，否则 ConversationCollector 没有 assistant 记录）
                self.pipeline.conversation.add_turn(role="assistant", content=str(llm_response)[:500])

                # Step 6: Feedback + 记忆更新（必须，否则 ingest 的数据不会写入 LTM）
                token_estimate = optimized.token_usage.used or len(packaged.raw_prompt) // 4
                metrics = await self.pipeline.evaluator.evaluate(
                    packed=packaged,
                    llm_response=str(llm_response),
                    latency_ms=llm_latency,
                    token_count=token_estimate,
                )
                await self.pipeline.memory_updater.update_from_task(
                    task=task,
                    response=str(llm_response),
                    metrics=metrics,
                    user_id=self.pipeline.user_id,
                )
                self.pipeline.tracer.finish(success=metrics.success)

                result = {
                    "response": str(llm_response),
                    "trace_id": tracer_id,
                    "task_spec": task.model_dump(),
                    "latency_ms": round(llm_latency, 1),
                }
                return result

            except Exception as e:
                self.pipeline.tracer.finish(success=False)
                raise

        self.pipeline.run = hooked_run

    async def ingest_session(self, turns: list[dict]) -> None:
        """把 session 中的每个 user turn 作为独立输入喂给 pipeline。

        这样 LTM 会自动积累关键信息。
        """
        await self._ensure()
        self._suppress_inspect = True  # ingest 时不打印
        for t in turns:
            if t["role"] == "user":
                try:
                    await self.pipeline.run(t["content"])
                except Exception:
                    pass
        self._suppress_inspect = False

    async def answer(self, question: str) -> str:
        await self._ensure()
        try:
            result = await self.pipeline.run(question)
            if self._inspect:
                print()
                print(f"  ▶ [INSPECT] LLM 回复:")
                print(f"    {result['response'][:500]}")
                print("═" * 100)
            return str(result["response"]).strip()
        except Exception as e:
            return f"[ERROR] {e}"

    async def close(self) -> None:
        if self._initialized:
            await self.pipeline.close()


# ═══════════════════════════════════════════════════════════════════
# 评估指标
# ═══════════════════════════════════════════════════════════════════

def normalize_text(s: str) -> str:
    """小写 + 去标点 + 压缩空白。"""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def keyword_overlap_score(hypothesis: str, answer: str) -> float:
    """关键词召回率：标准答案的词有多少出现在 hypothesis 中。

    这是一种快速的粗评估，LongMemEval 官方使用 GPT-4 作为 LLM Judge，
    我们这里使用关键词召回作为近似。
    """
    hyp_norm = normalize_text(hypothesis)
    ans_norm = normalize_text(answer)

    # 提取答案中的实词（去掉停用词和单字符）
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "on", "at", "for", "and", "or", "but",
        "this", "that", "it", "as", "by", "with", "from", "not",
        "he", "she", "they", "we", "you", "i", "his", "her", "their",
    }
    ans_tokens = [t for t in ans_norm.split() if t not in stop_words and len(t) > 1]

    if not ans_tokens:
        return 1.0 if hyp_norm else 0.0

    hits = sum(1 for t in ans_tokens if t in hyp_norm)
    return hits / len(ans_tokens)


def is_correct(hypothesis: str, answer: str, threshold: float = 0.5) -> bool:
    """是否正确：关键词召回率 >= threshold。"""
    return keyword_overlap_score(hypothesis, answer) >= threshold


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

async def run_benchmark(
    data_path: str,
    llm_client: Any,
    db_path: Optional[str],
    max_eval: int,
    output_dir: str = "results",
    skip_simple: bool = False,
    inspect: bool = False,
):
    """在 LongMemEval 上运行基准测试。

    Args:
        data_path: 数据集路径。
        llm_client: LLM 客户端。
        db_path: SQLite 路径。
        max_eval: 最多评估的实例数（0 = 全部）。
        output_dir: 输出目录。
        skip_simple: 是否跳过 SimpleAgent（节省时间）。
    """
    # 加载数据
    print(f"Loading data from: {data_path}")
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if max_eval > 0:
        data = data[:max_eval]
    print(f"Evaluating {len(data)} instances")

    # 初始化 agents
    memory_agent = MemoryAgent(llm_client, db_path, inspect=inspect)
    simple_agent = None if skip_simple else SimpleAgent(llm_client)

    # 按 question_type 分组统计
    results_by_type: dict[str, dict[str, int]] = {}
    all_results = []
    t_start = time.time()

    for idx, inst in enumerate(data):
        qid = inst["question_id"]
        qtype = inst["question_type"]
        question = inst["question"]
        answer = inst["answer"]
        sessions = inst["haystack_sessions"]

        print(
            f"\r[{idx+1}/{len(data)}] {qtype:30s} "
            f"({len(sessions)} sessions)...",
            end="", flush=True,
        )

        # ── Agent B: MemoryAgent ──
        try:
            memory_agent.pipeline.conversation._history.clear()
        except Exception:
            pass
        for session in sessions:
            await memory_agent.ingest_session(session)
        resp_b = await memory_agent.answer(question)
        score_b = keyword_overlap_score(resp_b, answer)
        correct_b = is_correct(resp_b, answer)

        # ── Agent A: SimpleAgent ──
        score_a = 0.0
        correct_a = False
        if simple_agent:
            simple_agent.reset()
            for session in sessions:
                await simple_agent.ingest_session(session)
            resp_a = await simple_agent.answer(question)
            score_a = keyword_overlap_score(resp_a, answer)
            correct_a = is_correct(resp_a, answer)

        # 统计
        if qtype not in results_by_type:
            results_by_type[qtype] = {"total": 0, "correct_a": 0, "correct_b": 0, "score_a": 0.0, "score_b": 0.0}
        results_by_type[qtype]["total"] += 1
        results_by_type[qtype]["correct_a"] += int(correct_a)
        results_by_type[qtype]["correct_b"] += int(correct_b)
        results_by_type[qtype]["score_a"] += score_a
        results_by_type[qtype]["score_b"] += score_b

        all_results.append({
            "question_id": qid,
            "question_type": qtype,
            "question": question[:100],
            "answer": answer[:100],
            "hypothesis_simple": (resp_a[:200] if simple_agent else ""),
            "hypothesis_memory": resp_b[:200],
            "score_a": round(score_a, 3),
            "score_b": round(score_b, 3),
            "correct_a": correct_a,
            "correct_b": correct_b,
        })

    elapsed = time.time() - t_start
    await memory_agent.close()

    # ── 输出报告 ──
    print("\n")
    print("=" * 90)
    print("  LongMemEval 基准测试报告")
    print("=" * 90)
    print(f"  数据集:    {Path(data_path).name}")
    print(f"  实例数:    {len(data)}")
    print(f"  LLM:       {type(llm_client).__name__}")
    print(f"  耗时:      {elapsed/60:.1f} 分钟")
    print("-" * 90)
    print(
        f"  {'类型':<32s} {'数量':>4s} "
        f"{'Simple准确率':>14s} {'Memory准确率':>14s} "
        f"{'Simple F1':>10s} {'Memory F1':>10s}"
    )
    print("-" * 90)

    total_a = total_b = 0
    total_score_a = total_score_b = 0.0
    total_count = 0

    for qtype, stats in sorted(results_by_type.items()):
        n = stats["total"]
        acc_a = stats["correct_a"] / n if n else 0
        acc_b = stats["correct_b"] / n if n else 0
        avg_a = stats["score_a"] / n if n else 0
        avg_b = stats["score_b"] / n if n else 0
        print(
            f"  {qtype:<32s} {n:>4d} "
            f"{acc_a:>13.1%} {acc_b:>13.1%} "
            f"{avg_a:>10.3f} {avg_b:>10.3f}"
        )
        total_a += stats["correct_a"]
        total_b += stats["correct_b"]
        total_score_a += stats["score_a"]
        total_score_b += stats["score_b"]
        total_count += n

    print("-" * 90)
    print(
        f"  {'TOTAL':<32s} {total_count:>4d} "
        f"{total_a/total_count:>13.1%} {total_b/total_count:>13.1%} "
        f"{total_score_a/total_count:>10.3f} {total_score_b/total_count:>10.3f}"
    )
    print("=" * 90)

    delta_acc = (total_b - total_a) / total_count if total_count else 0
    delta_f1 = (total_score_b - total_score_a) / total_count if total_count else 0
    print(f"  准确率提升: {delta_acc:+.1%}")
    print(f"  F1 提升:    {delta_f1:+.3f}")
    print("=" * 90)

    # 保存结果
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(output_dir, f"longmemeval_result_{ts}.json")
    summary = {
        "dataset": Path(data_path).name,
        "num_instances": total_count,
        "duration_minutes": round(elapsed / 60, 1),
        "llm": type(llm_client).__name__,
        "by_type": {
            qt: {
                "count": s["total"],
                "acc_simple": round(s["correct_a"] / s["total"], 3) if s["total"] else 0,
                "acc_memory": round(s["correct_b"] / s["total"], 3) if s["total"] else 0,
                "f1_simple": round(s["score_a"] / s["total"], 3) if s["total"] else 0,
                "f1_memory": round(s["score_b"] / s["total"], 3) if s["total"] else 0,
            }
            for qt, s in sorted(results_by_type.items())
        },
        "overall": {
            "acc_simple": round(total_a / total_count, 3),
            "acc_memory": round(total_b / total_count, 3),
            "f1_simple": round(total_score_a / total_count, 3),
            "f1_memory": round(total_score_b / total_count, 3),
            "delta_acc": round(delta_acc, 3),
            "delta_f1": round(delta_f1, 3),
        },
        "details": all_results,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {out_file}")

    # 输出 jsonl 供官方评估脚本使用
    jsonl_simple = os.path.join(output_dir, f"lme_simple_{ts}.jsonl")
    jsonl_memory = os.path.join(output_dir, f"lme_memory_{ts}.jsonl")
    with open(jsonl_simple, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps({
                "question_id": r["question_id"],
                "hypothesis": r["hypothesis_simple"],
            }, ensure_ascii=False) + "\n")
    with open(jsonl_memory, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps({
                "question_id": r["question_id"],
                "hypothesis": r["hypothesis_memory"],
            }, ensure_ascii=False) + "\n")
    print(f"SimpleAgent JSONL: {jsonl_simple}")
    print(f"MemoryAgent JSONL: {jsonl_memory}")
    print("\n使用官方评估脚本（需要 GPT-4o API Key）:")
    print(f"  python LongMemEval/src/evaluation/evaluate_qa.py gpt-4o {jsonl_memory} data/longmemeval/longmemeval_oracle")


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="LongMemEval 基准测试")
    parser.add_argument(
        "--data", default="data/longmemeval/longmemeval_oracle",
        help="数据集路径（默认 oracle 版本）",
    )
    parser.add_argument(
        "--max-eval", type=int, default=20,
        help="最多评估的实例数（默认 20；0 = 全部 500 题）",
    )
    parser.add_argument(
        "--skip-simple", action="store_true",
        help="跳过 SimpleAgent（只测 MemoryAgent）",
    )
    parser.add_argument(
        "--output-dir", default="results",
        help="结果输出目录",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="显示每一步的详细输入输出（设置 LOG_LEVEL=DEBUG）",
    )
    parser.add_argument(
        "--inspect", action="store_true",
        help="打印每一步的完整输入/输出/召回内容（包括完整 prompt 和 LTM 检索结果）",
    )
    args = parser.parse_args()

    # 启用详细日志
    if args.verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"
        print("详细模式: 将显示 DEBUG 级别日志")

    # 选择 LLM
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    db_path = os.environ.get("DATABASE_URL", "data/longmemeval.db")

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
        print("错误: 未检测到 API Key")
        print("设置: $env:DEEPSEEK_API_KEY='sk-xxx'")
        return

    asyncio.run(run_benchmark(
        data_path=args.data,
        llm_client=llm,
        db_path=db_path,
        max_eval=args.max_eval,
        output_dir=args.output_dir,
        skip_simple=args.skip_simple,
        inspect=args.inspect,
    ))


if __name__ == "__main__":
    main()
