"""Pipeline Observer — 逐步骤检测 Context-OS Pipeline 的中间状态。

Observer 替换 pipeline.run() 的调用方式，改为手动执行每个步骤并捕获
诊断信息，实现白盒测试。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from context_os.core.models import (
    EvalMetrics,
    LLMProvider,
    OptimizedContext,
    PackagedContext,
    TaskSpec,
    UnifiedContext,
)

from benchmark.metrics import PipelineMetrics, StepMetrics, estimate_tokens


class PipelineObserver:
    """Pipeline 观察器。

    手动执行 ContextOSPipeline 的每个步骤，捕获中间状态和性能指标。

    用法:
        observer = PipelineObserver(pipeline)
        response, diag = await observer.observe_run("用户输入")
        print(diag["intent"])  # 意图诊断
        print(diag["latency_breakdown"])  # 各步骤耗时
    """

    def __init__(self, pipeline):
        self.p = pipeline
        self.embedding_provider = getattr(pipeline, "_embedding_provider", None)

    async def observe_run(self, user_input: str) -> tuple[str, dict]:
        """执行一次带诊断的 Pipeline 运行。

        Args:
            user_input: 用户输入。

        Returns:
            (response, diagnostics) — response 是 LLM 回复文本，
            diagnostics 是包含所有中间状态的字典。
        """
        await self.p._ensure_store()
        self.p.conversation.add_turn(role="user", content=user_input)

        diag: dict[str, Any] = {
            "user_input": user_input,
            "latency_breakdown": {},
            "tokens": {},
        }
        metrics = PipelineMetrics()
        pipeline_start = time.time()

        # ── Step 1: Intent Understanding ──
        try:
            t0 = time.time()
            task = await self.p.task_parser.parse(user_input)
            lat = (time.time() - t0) * 1000
            diag["intent"] = {
                "latency_ms": round(lat, 1),
                "intent": task.intent.value,
                "goal": task.goal.value,
                "confidence": task.confidence,
                "entities": [e.model_dump() for e in task.entities],
                "entity_count": len(task.entities),
                "tool_requirements": len(task.tool_requirements),
                "knowledge_requirements": len(task.knowledge_requirements),
            }
            diag["latency_breakdown"]["intent"] = round(lat, 1)
            metrics.add_step(StepMetrics("intent", latency_ms=round(lat, 1)))
        except Exception as e:
            diag["intent"] = {"error": str(e)}
            diag["latency_breakdown"]["intent"] = -1

        # ── Step 2: Context Builder (Collection + Builder) ──
        try:
            t0 = time.time()
            unified = await self.p.builder.build(task)
            lat = (time.time() - t0) * 1000
            memory_type_counts: dict[str, int] = {}
            memory_items_info = []
            for m in unified.memory:
                t = m.type.value if hasattr(m.type, "value") else str(m.type)
                memory_type_counts[t] = memory_type_counts.get(t, 0) + 1
                memory_items_info.append({
                    "type": t,
                    "content": m.content[:80],
                    "relevance": round(m.relevance_score, 3),
                })
            diag["collection"] = {
                "latency_ms": round(lat, 1),
                "identity_present": unified.identity is not None,
                "conversation_turns": len(unified.conversation.history)
                if unified.conversation and unified.conversation.history
                else 0,
                "environment_present": unified.environment is not None,
            }
            diag["builder"] = {
                "latency_ms": round(lat, 1),
                "memory_count": len(unified.memory),
                "knowledge_count": len(unified.knowledge),
                "tool_count": len(unified.tools),
                "memory_by_type": memory_type_counts,
                "memory_items": memory_items_info,
            }
            diag["latency_breakdown"]["builder"] = round(lat, 1)
            metrics.add_step(StepMetrics("builder", latency_ms=round(lat, 1)))
        except Exception as e:
            diag["collection"] = {"error": str(e)}
            diag["builder"] = {"error": str(e)}
            diag["latency_breakdown"]["builder"] = -1
            unified = UnifiedContext()

        # ── Step 3: Optimizer ──
        try:
            raw_memory_count = len(unified.memory)
            raw_knowledge_count = len(unified.knowledge)
            raw_conv_turns = len(unified.conversation.history) if unified.conversation and unified.conversation.history else 0

            t0 = time.time()
            # 估算优化前 token
            token_before = estimate_tokens(str(unified.model_dump() if hasattr(unified, 'model_dump') else unified))
            optimized = await self.p.optimizer.optimize(unified, task)
            lat = (time.time() - t0) * 1000
            token_after = estimate_tokens(str(optimized.context.model_dump() if hasattr(optimized.context, 'model_dump') else optimized.context))

            diag["optimizer"] = {
                "latency_ms": round(lat, 1),
                "compressed": optimized.compressed,
                "token_before": token_before,
                "token_after": token_after,
                "token_reduced": token_before - token_after,
                "compression_ratio": round(1.0 - (token_after / token_before), 3) if token_before > 0 else 0,
                "token_budget_total": optimized.token_usage.total,
                "token_budget_used": optimized.token_usage.used,
                "token_breakdown": optimized.token_usage.breakdown,
                "before_memory_count": raw_memory_count,
                "after_memory_count": len(optimized.context.memory),
                "before_knowledge_count": raw_knowledge_count,
                "after_knowledge_count": len(optimized.context.knowledge),
            }
            diag["latency_breakdown"]["optimizer"] = round(lat, 1)
            metrics.add_step(StepMetrics("optimizer", latency_ms=round(lat, 1)))
        except Exception as e:
            diag["optimizer"] = {"error": str(e)}
            diag["latency_breakdown"]["optimizer"] = -1
            optimized = None  # 防止后续步骤 NameError

        # ── Step 4: Packager ──
        try:
            if optimized is None:
                raise ValueError("optimizer step failed, skipping packager")
            t0 = time.time()
            packaged = self.p.packager.pack(optimized, self.p.provider)
            lat = (time.time() - t0) * 1000
            diag["packager"] = {
                "latency_ms": round(lat, 1),
                "prompt_length_chars": len(packaged.raw_prompt),
                "prompt_tokens_est": estimate_tokens(packaged.raw_prompt),
                "sections": list(packaged.sections.keys()),
                "section_lengths": {
                    k: len(v) for k, v in packaged.sections.items()
                },
            }
            # 存储最终 prompt 内容用于调试
            diag["packager"]["prompt_preview"] = packaged.raw_prompt[:500]
            diag["latency_breakdown"]["packager"] = round(lat, 1)
            metrics.add_step(StepMetrics("packager", latency_ms=round(lat, 1),
                                          input_tokens=estimate_tokens(packaged.raw_prompt)))
        except Exception as e:
            diag["packager"] = {"error": str(e)}
            diag["latency_breakdown"]["packager"] = -1
            packaged = None  # 防止后续步骤 NameError

        # ── Step 5: LLM Inference ──
        try:
            if packaged is None:
                raise ValueError("packager step failed, skipping LLM inference")
            t0 = time.time()
            llm_response = await self.p.llm_client.complete(packaged.raw_prompt)
            lat = (time.time() - t0) * 1000
            diag["llm"] = {
                "latency_ms": round(lat, 1),
                "response": str(llm_response),
                "response_length_chars": len(str(llm_response)),
                "response_tokens_est": estimate_tokens(str(llm_response)),
            }
            diag["latency_breakdown"]["llm"] = round(lat, 1)
            metrics.add_step(StepMetrics("llm", latency_ms=round(lat, 1),
                                          output_tokens=estimate_tokens(str(llm_response))))
        except Exception as e:
            diag["llm"] = {"error": str(e), "response": ""}
            diag["latency_breakdown"]["llm"] = -1
            llm_response = ""

        response_text = str(llm_response)
        self.p.conversation.add_turn(role="assistant", content=response_text[:500])

        # ── Step 6: Feedback & Memory Update ──
        try:
            if packaged is None:
                raise ValueError("packager step failed, skipping feedback")
            t0 = time.time()
            token_estimate = estimate_tokens(packaged.raw_prompt) + estimate_tokens(response_text)
            metrics_result = await self.p.evaluator.evaluate(
                packed=packaged,
                llm_response=response_text,
                latency_ms=diag["llm"].get("latency_ms", 0),
                token_count=token_estimate,
            )
            # Journal 驱动持久化（替代旧 memory_updater 路径）
            candidate_text = (
                f"User: {task.raw_input}\n"
                f"Assistant: {response_text[:500]}"
            )
            self.p.working_memory.push(
                candidate_text,
                metadata={"intent": task.intent.value, "round": self.p._round_count + 1},
            )
            self.p._round_count += 1
            await self.p.journal.append(
                user_id=self.p.user_id,
                session_id=self.p.session_id,
                round_id=self.p._round_count,
                raw_input=task.raw_input,
                raw_output=response_text[:2000],
                entities={e.type: e.value for e in task.entities} if task.entities else {},
                task_intent=task.intent.value,
                metadata={
                    "task_importance": metrics_result.task_importance,
                    "reward_score": metrics_result.reward_score,
                    "answer_quality": metrics_result.answer_quality,
                },
            )
            lat = (time.time() - t0) * 1000
            diag["feedback"] = {
                "latency_ms": round(lat, 1),
                "answer_quality": metrics_result.answer_quality,
                "reward_score": metrics_result.reward_score,
                "success": metrics_result.success,
                "hallucination_score": metrics_result.hallucination_score,
                "cost_usd": metrics_result.cost_usd,
            }
            diag["latency_breakdown"]["feedback"] = round(lat, 1)
            metrics.add_step(StepMetrics("feedback", latency_ms=round(lat, 1)))
        except Exception as e:
            diag["feedback"] = {"error": str(e)}
            diag["latency_breakdown"]["feedback"] = -1

        # ── 汇总 ──
        total_lat = (time.time() - pipeline_start) * 1000
        diag["total_latency_ms"] = round(total_lat, 1)
        diag["metrics"] = metrics
        metrics.total_latency_ms = round(total_lat, 1)
        metrics.total_prompt_tokens = estimate_tokens(packaged.raw_prompt) if packaged is not None else 0
        metrics.total_completion_tokens = estimate_tokens(response_text)

        return response_text, diag
