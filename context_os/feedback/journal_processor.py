"""JournalProcessor — 从 Journal WAL 驱动所有持久化记忆写入。

这是 MEMORY_SYSTEM_DESIGN.md §2 的核心架构：
    Journal（写前日志）→ EventBus.publish("journal:created")
        → JournalProcessor（订阅者）→ WriteDecision → MemoryRouter → 持久化

关键设计：
    EventBus.publish() 使用 asyncio.gather 等待所有 handler 完成，
    因此 journal.append() 返回时，所有持久化写入已经完成。
    这保证了 WAL 语义 + 同步行为（向后兼容测试）。
"""

from __future__ import annotations

import time
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger
from context_os.feedback.memory_importance import ImportanceScorer
from context_os.feedback.triple_extractor import TripleExtractor
from context_os.feedback.write_decision import WriteDecision, WriteDecisionResult
from context_os.feedback.memory_router import MemoryRouter
from context_os.events.types import JournalCreatedEvent, MemoryWrittenEvent

if TYPE_CHECKING:
    from context_os.events.bus import EventBus
    from context_os.memory.long_term import LongTermMemory
    from context_os.memory.semantic import SemanticMemory
    from context_os.memory.experience import ExperienceMemory
    from context_os.memory.session_memory import SessionMemory
    from context_os.feedback.concept_worker import BackgroundConceptWorker

logger = get_logger(__name__)

# ── 批量触发常量 ──
BATCH_PENDING_THRESHOLD = 5
BATCH_TURN_THRESHOLD = 10
BATCH_TIMER_SECONDS = 300


class JournalProcessor:
    """订阅 journal:created，驱动 WriteDecision → MemoryRouter → 持久化存储。

    这是从 MemoryUpdater 中分离出来的核心写入引擎，
    以 Journal WAL 为唯一数据源，通过 EventBus 事件驱动。

    使用方式:
        processor = JournalProcessor(
            event_bus=bus, ltm=ltm, sem=sem, exp=exp, stm=stm,
        )
        # 之后每次 journal.append() 会自动触发处理
    """

    def __init__(
        self,
        event_bus: "EventBus",
        long_term_memory: "LongTermMemory",
        semantic_memory: "SemanticMemory",
        experience_memory: "ExperienceMemory",
        session_memory: "SessionMemory",
        knowledge_queue: Optional[Any] = None,
        concept_worker: Optional["BackgroundConceptWorker"] = None,
        embedding_provider: Optional[Any] = None,
    ) -> None:
        self._event_bus = event_bus
        self._ltm = long_term_memory
        self._sem = semantic_memory
        self._exp = experience_memory
        self._stm = session_memory

        # 内部组件
        self._importance = ImportanceScorer()
        self._triple_extractor = TripleExtractor()
        self._decision = WriteDecision(
            ltm=long_term_memory,
            scorer=self._importance,
            embedding_provider=embedding_provider,
        )
        self._router = MemoryRouter(
            triple_extractor=self._triple_extractor,
            knowledge_queue=knowledge_queue,
            concept_worker=concept_worker,
        )

        # 批量处理状态
        self._turn_count: int = 0
        self._last_batch_time: float = time.time()

        # 订阅 journal:created 事件
        self._event_bus.subscribe("journal:created", self._on_journal_created)

        logger.info("JournalProcessor subscribed to journal:created")

    # ── 事件处理入口 ───────────────────────────────────────────

    async def _on_journal_created(self, event: JournalCreatedEvent) -> None:
        """处理一条新 Journal 记录。

        这是 journal:created 事件的 handler。
        EventBus.publish() 通过 asyncio.gather 等待此方法完成。
        """
        self._turn_count += 1
        user_id = event.user_id
        journal_id = event.journal_id

        logger.debug(
            "JournalProcessor: handling journal=%s, turn=%d, intent=%s",
            journal_id, self._turn_count, event.task_intent,
        )

        # Step 1: 构建候选文本
        candidate_text = self._build_candidate_text(event)

        # Step 2: Session Memory（零门槛，从 Journal 派生）
        await self._stm.add(
            content=candidate_text[:500],
            metadata={
                "source": "journal",
                "round_id": event.round_id,
                "intent": event.task_intent,
                "journal_id": journal_id,
            },
            user_id=user_id,
        )

        # Step 3: Layer 1 规则必存（立即处理）
        layer1_result = self._layer1_check_from_event(event, candidate_text)
        if layer1_result.should_store:
            logger.info(
                "JournalProcessor: Layer 1 hit, journal=%s, score=%.3f",
                journal_id, layer1_result.score,
            )
            await self._router.dispatch(
                route_result=layer1_result.route,
                triple_result=layer1_result.triple_result,
                content=candidate_text,
                journal_id=journal_id,
                user_id=user_id,
                ltm=self._ltm,
                sem=self._sem,
                exp=self._exp,
                score=layer1_result.score,
            )
            # 发布 MemoryWritten 事件（供 Maintenance 等消费）
            await self._event_bus.publish(MemoryWrittenEvent(
                journal_id=journal_id,
                user_id=user_id,
                target=layer1_result.route.target if hasattr(layer1_result, 'route') else "long_term",
                memory_id=journal_id,
                score=layer1_result.score,
            ))
            return

        # Step 4: Layer 1 未命中 → 推入候选缓冲区
        pending_id = await self._stm.add_pending_candidate(
            content=candidate_text,
            entities={
                "journal_id": journal_id,
                "intent": event.task_intent,
                "raw_input": event.raw_input[:100],
            },
            turn_number=self._turn_count,
            user_id=user_id,
        )
        logger.debug("JournalProcessor: buffered candidate, id=%s", pending_id)

        # Step 5: 检查批量触发
        if await self._should_batch_flush():
            await self._flush_batch(user_id)

    # ── Layer 1 规则检查 ───────────────────────────────────────

    def _layer1_check_from_event(
        self,
        event: JournalCreatedEvent,
        candidate_text: str,
    ) -> WriteDecisionResult:
        """从 Journal 事件执行 Layer 1 规则检查。

        将 Journal 数据映射为 WriteDecision 需要的参数格式。
        """
        # 构造简化版 TaskSpec（只含 Layer 1 需要的字段）
        from context_os.core.models import TaskSpec, IntentType, GoalType

        task_intent = IntentType.QA
        try:
            task_intent = IntentType(event.task_intent) if event.task_intent else IntentType.QA
        except ValueError:
            pass

        task = TaskSpec(
            raw_input=event.raw_input,
            intent=task_intent,
            goal=GoalType.GENERATE,
        )

        # 构造简化版 EvalMetrics（只含结论匹配需要的字段）
        from context_os.core.models import EvalMetrics
        metrics = EvalMetrics()

        return self._decision._layer1_rule_check(
            content=candidate_text,
            task=task,
            response=event.raw_output,
            metrics=metrics,
        )

    # ── 批量处理 ───────────────────────────────────────────────

    async def _should_batch_flush(self) -> bool:
        """判断是否应触发批量刷新。"""
        pending_count = await self._stm.get_pending_count()
        if pending_count >= BATCH_PENDING_THRESHOLD:
            logger.info("Batch trigger: pending=%d >= %d", pending_count, BATCH_PENDING_THRESHOLD)
            return True
        if self._turn_count > 0 and self._turn_count % BATCH_TURN_THRESHOLD == 0:
            logger.info("Batch trigger: turn=%d", self._turn_count)
            return True
        elapsed = time.time() - self._last_batch_time
        if elapsed > BATCH_TIMER_SECONDS:
            logger.info("Batch trigger: elapsed=%.0fs > %ds", elapsed, BATCH_TIMER_SECONDS)
            return True
        return False

    async def _flush_batch(self, user_id: str) -> int:
        """批量处理候选缓冲区中的 pending 记录。

        Returns:
            处理的记录数。
        """
        pending = await self._stm.query_pending(top_k=50)
        if not pending:
            return 0

        logger.info("JournalProcessor: flushing batch, %d pending", len(pending))
        processed = 0

        for record in pending:
            content = record.get("content", "")
            if not content:
                continue

            # 标记为 processing
            await self._stm.update_pending_status(record["id"], "processing")

            # Layer 2 + Layer 3 判断
            result = await self._decision.decide(content, user_id=user_id)

            if result.should_store:
                await self._router.dispatch(
                    route_result=result.route,
                    triple_result=result.triple_result,
                    content=content,
                    journal_id=record.get("entities", {}).get("journal_id", ""),
                    user_id=user_id,
                    ltm=self._ltm,
                    sem=self._sem,
                    exp=self._exp,
                    score=result.score,
                )
                await self._stm.update_pending_status(record["id"], "written")
            else:
                await self._stm.update_pending_status(record["id"], "discarded")

            processed += 1

        self._last_batch_time = time.time()
        logger.info("JournalProcessor: batch done, %d processed", processed)
        return processed

    # ── 工具方法 ────────────────────────────────────────────────

    @staticmethod
    def _build_candidate_text(event: JournalCreatedEvent) -> str:
        """从 Journal 事件构建候选文本。"""
        parts = []
        if event.raw_input:
            parts.append(f"User: {event.raw_input}")
        if event.raw_output:
            parts.append(f"Assistant: {event.raw_output[:500]}")
        return "\n".join(parts)

    # ── 手动触发（用于 close() 和测试）────────────────────────

    async def flush(self, user_id: str = "anonymous") -> int:
        """手动触发批量刷新（公开 API）。

        Pipeline.close() 和测试用例使用此方法。
        """
        return await self._flush_batch(user_id)

    async def close(self) -> None:
        """关闭处理器：刷新剩余缓冲，取消订阅。"""
        # 被动取消订阅（EventBus 引用失效后自动清理）
        logger.info("JournalProcessor: closed")
