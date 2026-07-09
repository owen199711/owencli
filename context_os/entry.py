"""Context-OS 主 Pipeline 编排入口。

将 Intent → Orchestrator → Collection → Builder → Optimizer → Packager → LLM → Feedback
串联为完整的执行链路。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from context_os.builder.builder import ContextBuilder
from context_os.collection.conversation import ConversationCollector
from context_os.collection.environment import EnvironmentCollector
from context_os.collection.identity import IdentityCollector
from context_os.core.errors import ContextBuildError, ContextOSError
from context_os.core.logger import get_logger
from context_os.core.models import (
    LLMProvider,
    OptimizedContext,
    PackagedContext,
    TaskSpec,
    UnifiedContext,
)
from context_os.feedback.evaluator import QualityEvaluator
from context_os.feedback.memory_updater import MemoryUpdater
from context_os.feedback.tracer import Tracer
from context_os.intent.classifier import IntentClassifier
from context_os.intent.extractor import EntityExtractor
from context_os.intent.parser import TaskParser
from context_os.llm.client import BaseLLMClient
from context_os.memory.episodic import EpisodicMemory
from context_os.memory.long_term import LongTermMemory
from context_os.memory.semantic import SemanticMemory
from context_os.memory.short_term import ShortTermMemory
from context_os.memory.store import SQLiteStore
from context_os.memory.working import WorkingMemory
from context_os.optimizer.budget import TokenBudgetAllocator
from context_os.optimizer.compressor import ContextCompressor
from context_os.optimizer.optimizer import ContextOptimizer
from context_os.optimizer.ranker import RelevanceRanker
from context_os.orchestrator.router import ContextRouter
from context_os.orchestrator.selector import ContextSelector
from context_os.packager.packager import ContextPackager

logger = get_logger(__name__)


class ContextOSPipeline:
    """Context-OS 主 Pipeline。

    使用示例:
        pipeline = ContextOSPipeline(llm_client=my_client)
        result = await pipeline.run("帮我分析 K8s 集群")
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        provider: LLMProvider = LLMProvider.CLAUDE,
        db_path: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
        embedding_provider: Optional[Any] = None,
    ):
        """初始化 Pipeline。

        Args:
            llm_client: LLM 客户端。
            provider: LLM 提供商。
            db_path: SQLite 数据库文件路径。默认从 DATABASE_URL 环境变量读取。
            session_id: Session ID（自动生成）。
            user_id: 用户 ID。
            embedding_provider: 语义嵌入引擎（可选）。提供后 LTM 可做向量检索。
        """
        import uuid
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.user_id = user_id
        self.provider = provider
        self._embedding_provider = embedding_provider

        # ── 存储层 ──
        self.store = SQLiteStore(db_path=db_path)
        self._store_connected = False

        # ── Intent ──
        classifier = IntentClassifier(llm_client=llm_client)
        extractor = EntityExtractor()
        self.task_parser = TaskParser(classifier=classifier, extractor=extractor)

        # ── Orchestrator ──
        selector = ContextSelector()
        router = ContextRouter()

        # ── Collection ──
        identity = IdentityCollector()
        self.conversation = ConversationCollector()
        environment = EnvironmentCollector()

        # ── Memory ──
        self.working_memory = WorkingMemory()
        self.short_term_memory = ShortTermMemory(
            session_id=self.session_id,
            store=self.store,
        )
        self.long_term_memory = LongTermMemory(
            store=self.store,
            user_id=user_id,
            embedding_provider=self._embedding_provider,
        )
        self.episodic_memory = EpisodicMemory(
            store=self.store,
            user_id=user_id,
        )
        self.semantic_memory = SemanticMemory(
            store=self.store,
            user_id=user_id,
        )

        # ── Builder ──
        self.builder = ContextBuilder(
            selector=selector,
            router=router,
            identity=identity,
            conversation=self.conversation,
            environment=environment,
            working_memory=self.working_memory,
            long_term_memory=self.long_term_memory,
        )

        # ── Optimizer ──
        ranker = RelevanceRanker()
        compressor = ContextCompressor(llm_client=llm_client)
        budget = TokenBudgetAllocator()
        self.optimizer = ContextOptimizer(
            ranker=ranker,
            compressor=compressor,
            budget=budget,
        )

        # ── Packager ──
        self.packager = ContextPackager()

        # ── Feedback ──
        self.evaluator = QualityEvaluator(llm_client=llm_client)
        self.tracer = Tracer()
        self.memory_updater = MemoryUpdater(
            working_memory=self.working_memory,
            short_term_memory=self.short_term_memory,
            long_term_memory=self.long_term_memory,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
        )

        # ── LLM ──
        self.llm_client = llm_client

        logger.info(
            "ContextOSPipeline initialized: session=%s, user=%s, provider=%s",
            self.session_id, user_id, provider.value,
        )

    async def _ensure_store(self) -> None:
        """确保 SQLite 已连接（懒连接）。"""
        if not self._store_connected:
            await self.store.connect()
            self._store_connected = True

    async def run(self, user_input: str) -> dict[str, Any]:
        """执行完整的 Context Pipeline。

        执行流程:
            1. Intent Understanding → TaskSpec
            2. Context Builder → UnifiedContext
            3. Context Optimizer → OptimizedContext
            4. Context Packager → PackagedContext
            5. LLM Inference → Response
            6. Feedback → 评估 + 更新记忆 + 记录轨迹

        Args:
            user_input: 用户输入文本。

        Returns:
            dict with keys: response, metrics, trace_id, task_spec, latency_ms。
        """
        # 确保存储
        await self._ensure_store()

        # 记录对话轮次
        self.conversation.add_turn(role="user", content=user_input)

        # 开启 Trace
        tracer_id = self.tracer.start(task_id="", raw_input=user_input)
        logger.info("========== Pipeline start ==========")
        logger.info("input: %s...", user_input[:120])

        pipeline_start = time.time()

        try:
            # ── Step 1: Intent Understanding ──
            self.tracer.step_begin("intent_understanding")
            t0 = time.time()
            task: TaskSpec = await self.task_parser.parse(user_input)
            logger.info(
                "Step 1 (意图理解): ──────────────────────────────\n"
                "  line: 解析用户输入 → TaskSpec\n"
                "  input: %s...\n"
                "  output: intent=%s, goal=%s, confidence=%.2f, entities=%d, tool_reqs=%d, knowledge_reqs=%d",
                user_input[:80],
                task.intent.value, task.goal.value, task.confidence,
                len(task.entities), len(task.tool_requirements), len(task.knowledge_requirements),
            )

            # ── Step 2: Context Building ──
            self.tracer.step_begin("context_building")
            t0 = time.time()
            unified: UnifiedContext = await self.builder.build(task)
            logger.info(
                "Step 2 (上下文构建): ──────────────────────────\n"
                "  line: 并行收集身份/对话/环境/记忆 → UnifiedContext\n"
                "  input: task_id=%s\n"
                "  output: identity=%s, conversation=%s, environment=%s, memory=%d, knowledge=%d",
                task.id,
                "yes" if unified.identity else "no",
                f"{len(unified.conversation.history) if unified.conversation else 0}turns" if unified.conversation else "no",
                "yes" if unified.environment else "no",
                len(unified.memory), len(unified.knowledge),
            )

            # ── Step 3: Context Optimization ──
            self.tracer.step_begin("context_optimization")
            t0 = time.time()
            optimized: OptimizedContext = await self.optimizer.optimize(unified, task)
            logger.info(
                "Step 3 (上下文优化): ──────────────────────────\n"
                "  line: 排序记忆 → 压缩对话 → 分配预算 → OptimizedContext\n"
                "  input: memories=%d, knowledge=%d, conv_turns=%d\n"
                "  output: compressed=%s, budget=%d, used=%d",
                len(unified.memory), len(unified.knowledge),
                len(unified.conversation.history) if unified.conversation else 0,
                optimized.compressed,
                optimized.token_usage.total,
                optimized.token_usage.used or 0,
            )

            # ── Step 4: Context Packaging ──
            self.tracer.step_begin("context_packaging")
            t0 = time.time()
            packaged: PackagedContext = self.packager.pack(optimized, self.provider)
            logger.info(
                "Step 4 (Prompt 打包): ─────────────────────────\n"
                "  line: 按 provider 格式拼接 sections → PackagedContext\n"
                "  input: provider=%s, sections=%d\n"
                "  output: prompt_len=%d chars, section_keys=%s",
                self.provider.value,
                len(unified.memory) + len(unified.knowledge),
                len(packaged.raw_prompt),
                list(packaged.sections.keys()),
            )

            # ── Step 5: LLM Inference ──
            s5 = self.tracer.step_begin("llm_inference")
            t0 = time.time()
            llm_response = await self.llm_client.complete(packaged.raw_prompt)
            llm_latency = (time.time() - t0) * 1000
            self.tracer.step_end(s5, packaged.raw_prompt[:200], str(llm_response)[:300])
            logger.info(
                "Step 5 (LLM 推理): ────────────────────────────\n"
                "  line: 调用 %s API\n"
                "  input: %d chars → model=%s\n"
                "  output: latency=%.0fms, response_len=%d chars",
                type(self.llm_client).__name__,
                len(packaged.raw_prompt),
                getattr(self.llm_client, 'model', 'default'),
                llm_latency,
                len(str(llm_response)),
            )

            # 记录 assistant 回复
            self.conversation.add_turn(role="assistant", content=str(llm_response)[:500])

            # ── Step 6: Feedback ──
            step = self.tracer.step_begin("feedback")
            t0 = time.time()
            token_estimate = optimized.token_usage.used or len(packaged.raw_prompt) // 4
            metrics = await self.evaluator.evaluate(
                packed=packaged,
                llm_response=str(llm_response),
                latency_ms=llm_latency,
                token_count=token_estimate,
            )
            self.tracer.step_end(step, packaged.raw_prompt[:100], metrics.model_dump_json())

            # 更新记忆
            await self.memory_updater.update_from_task(
                task=task,
                response=str(llm_response),
                metrics=metrics,
                user_id=self.user_id,
            )

            self.tracer.finish(success=metrics.success)

            total_latency = (time.time() - pipeline_start) * 1000
            logger.info(
                "Step 6 (反馈 & 记忆更新): ────────────────────\n"
                "  line: 评估质量 → 写入 Working/LTM/Episodic/Semantic\n"
                "  input: response=%s...\n"
                "  output: quality=%.3f, cost=$%.5f, success=%s, reward=%.3f",
                str(llm_response)[:80],
                metrics.answer_quality, metrics.cost_usd, metrics.success, metrics.reward_score,
            )
            logger.info(
                "========== Pipeline end: success=%s, total=%.0fms ==========",
                metrics.success, total_latency,
            )

            return {
                "response": str(llm_response),
                "metrics": metrics.model_dump(),
                "trace_id": tracer_id,
                "task_spec": task.model_dump(),
                "latency_ms": round(total_latency, 1),
            }

        except ContextBuildError as e:
            logger.error("Context build failed: %s", e)
            self.tracer.finish(success=False)
            raise

        except ContextOSError as e:
            logger.error("Pipeline error: %s", e, exc_info=True)
            self.tracer.finish(success=False)
            raise

        except Exception as e:
            logger.error("Unexpected pipeline error: %s", e, exc_info=True)
            self.tracer.finish(success=False)
            raise ContextOSError(f"Pipeline execution failed: {e}") from e

    async def close(self) -> None:
        """关闭 Pipeline，释放资源。"""
        await self.store.close()
        logger.info("Pipeline closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
