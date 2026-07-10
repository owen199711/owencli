"""Context Builder — 组装 UnifiedContext。

编排 ContextSelector/ContextRouter/Collector/Memory，生成 UnifiedContext。

Phase 4.4: 多源联合检索 — 从 4 个来源并行检索并合并。
"""

from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

from context_os.builder.merger import ContextMerger
from context_os.collection.conversation import ConversationCollector
from context_os.collection.environment import EnvironmentCollector
from context_os.collection.identity import IdentityCollector
from context_os.core.logger import get_logger
from context_os.core.models import (
    KnowledgeChunk, MemoryItem, TaskSpec, UnifiedContext,
)
from context_os.memory.long_term import LongTermMemory
from context_os.memory.working import WorkingMemory
from context_os.orchestrator.router import ContextFlag, ContextRouter
from context_os.orchestrator.selector import ContextSelector
from context_os.core.errors import ContextBuildError

if TYPE_CHECKING:
    from context_os.memory.experience import ExperienceMemory
    from context_os.memory.semantic import SemanticMemory
    from context_os.memory.session_memory import SessionMemory

logger = get_logger(__name__)

# ════════════════════════════════════════════════════════════════
# Phase 4.4 新旧策略开关
# ════════════════════════════════════════════════════════════════
USE_NEW_BUILDER = True

# 多源权重（遍历阶段五可拔出到配置）
_SOURCE_WEIGHTS = {
    "long_term": 1.0,
    "session_pending": 0.8,
    "experience": 0.6,
    "knowledge_concept": 0.5,
}


class ContextBuilder:
    """Context Builder — 组装 UnifiedContext。

    Phase 4.4 新流程（USE_NEW_BUILDER=True）:
        1. selector.select(task) → flags
        2. router.route(task, flags) → routes
        3. 并行收集: collectors + 4 源记忆检索 (LTM/Session/Experience/Knowledge)
        4. merger.normalize() → deduplicate() → 源权重合并

    旧流程（USE_NEW_BUILDER=False）:
        1-3. 同上（仅 LTM 单源）
        4. merger.normalize() + deduplicate()
    """

    def __init__(
        self,
        selector: ContextSelector,
        router: ContextRouter,
        identity: IdentityCollector,
        conversation: ConversationCollector,
        environment: EnvironmentCollector,
        working_memory: WorkingMemory,
        long_term_memory: LongTermMemory,
        merger: Optional[ContextMerger] = None,
        # ── Phase 4.4 新增 ──
        session_memory: Optional["SessionMemory"] = None,
        experience_memory: Optional["ExperienceMemory"] = None,
        semantic_memory: Optional["SemanticMemory"] = None,
    ):
        self.selector = selector
        self.router = router
        self.identity = identity
        self.conversation = conversation
        self.environment = environment
        self.working_memory = working_memory
        self.long_term_memory = long_term_memory
        self.merger = merger or ContextMerger()

        # Phase 4.4 新增
        self.session_memory = session_memory
        self.experience_memory = experience_memory
        self.semantic_memory = semantic_memory

        logger.info(
            "ContextBuilder initialized (new_builder=%s, has_session=%s, "
            "has_experience=%s, has_semantic=%s)",
            USE_NEW_BUILDER,
            session_memory is not None,
            experience_memory is not None,
            semantic_memory is not None,
        )

    async def build(self, task: TaskSpec) -> UnifiedContext:
        """构建完整的 UnifiedContext。"""
        logger.info("Building context for task: %s (intent=%s)", task.id, task.intent.value)

        if USE_NEW_BUILDER:
            return await self._build_new(task)
        else:
            return await self._build_old(task)

    # ════════════════════════════════════════════════════════════
    # 新流程（Phase 4.4）
    # ════════════════════════════════════════════════════════════

    async def _build_new(self, task: TaskSpec) -> UnifiedContext:
        """多源联合检索 + 合并。"""
        try:
            flags = self.selector.select(task)
            logger.debug("Selected flags: %s", flags)

            routes = self.router.route(task, flags)
            logger.debug("Routes: %d collectors", len(routes))

            ctx = UnifiedContext()
            collector_map = {
                ContextFlag.IDENTITY: self.identity,
                ContextFlag.CONVERSATION: self.conversation,
                ContextFlag.ENVIRONMENT: self.environment,
            }

            active_routes = [r for r in routes if r.flag in collector_map]
            collect_tasks = [collector_map[r.flag].collect() for r in active_routes]

            # ── 4 源并行检索 ──
            if ContextFlag.MEMORY in flags:
                # LTM
                # Phase 4.5: 自动检测时间回溯查询
                expand = self.long_term_memory.detect_temporal_query(task.raw_input)
                ltm_task = asyncio.create_task(
                    self.long_term_memory.retrieve(
                        task.raw_input,
                        top_k=25,
                        intent=task.intent.value,
                        expand_history=expand,
                    )
                )
                collect_tasks.append(ltm_task)

                # Session pending
                session_task = None
                if self.session_memory:
                    session_task = asyncio.create_task(
                        self.session_memory.query_pending(query=task.raw_input, top_k=10)
                    )
                    collect_tasks.append(session_task)

                # Experience
                exp_task = None
                if self.experience_memory:
                    exp_task = asyncio.create_task(
                        self.experience_memory.recall_relevant(
                            scenario_query=task.raw_input, top_k=10,
                        )
                    )
                    collect_tasks.append(exp_task)

                # Knowledge (concepts)
                kw_task = None
                if self.semantic_memory and hasattr(self.semantic_memory, 'query'):
                    kw_task = asyncio.create_task(
                        self.semantic_memory.query(concept=task.raw_input[:50], depth=1)
                    )
                    collect_tasks.append(kw_task)

            if collect_tasks:
                results = await asyncio.gather(*collect_tasks, return_exceptions=True)

                # 处理 collector 结果
                for idx, route in enumerate(active_routes):
                    if idx >= len(results):
                        break
                    result = results[idx]
                    if isinstance(result, Exception):
                        logger.warning(
                            "Collector %s failed: %s",
                            type(collector_map[route.flag]).__name__, result,
                        )
                        continue
                    if route.flag == ContextFlag.IDENTITY and result:
                        ctx.identity = result
                    elif route.flag == ContextFlag.CONVERSATION and result:
                        ctx.conversation = result
                    elif route.flag == ContextFlag.ENVIRONMENT and result:
                        ctx.environment = result

                # 处理记忆检索结果
                result_idx = len(active_routes)  # 第一个记忆任务是 collectors 之后的

                mem_list: list[MemoryItem] = []
                kw_list: list[KnowledgeChunk] = []

                # LTM 结果
                if ltm_task:
                    ltm_result = results[result_idx]
                    result_idx += 1
                    if isinstance(ltm_result, list):
                        for m in ltm_result:
                            if isinstance(m, MemoryItem):
                                m.metadata["source"] = "long_term"
                                m.metadata["source_weight"] = _SOURCE_WEIGHTS["long_term"]
                                mem_list.append(m)
                        logger.debug("LTM retrieved: %d items", len(ltm_result))

                # Session pending 结果
                if session_task:
                    sess_result = results[result_idx]
                    result_idx += 1
                    if isinstance(sess_result, list):
                        for s in sess_result:
                            if isinstance(s, dict):
                                item = MemoryItem(
                                    type="session",
                                    content=s.get("content", ""),
                                    metadata={
                                        "source": "session_pending",
                                        "source_weight": _SOURCE_WEIGHTS["session_pending"],
                                        "turn": s.get("metadata", {}).get("turn_number", 0),
                                    },
                                )
                                mem_list.append(item)
                        logger.debug("Session pending: %d items", len(sess_result))

                # Experience 结果
                if exp_task:
                    exp_result = results[result_idx]
                    result_idx += 1
                    if isinstance(exp_result, list):
                        for e in exp_result:
                            if isinstance(e, dict):
                                item = MemoryItem(
                                    type="experience",
                                    content=e.get("scene", "") or str(e),
                                    metadata={
                                        "source": "experience",
                                        "source_weight": _SOURCE_WEIGHTS["experience"],
                                        "exp_type": e.get("experience_type", "unknown"),
                                    },
                                )
                                mem_list.append(item)
                        logger.debug("Experience: %d items", len(exp_result))

                # Knowledge 结果
                if kw_task:
                    kw_result = results[result_idx]
                    result_idx += 1
                    if isinstance(kw_result, dict):
                        nodes = kw_result.get("nodes", [])
                        edges = kw_result.get("edges", [])
                        for n in nodes:
                            kw_list.append(KnowledgeChunk(
                                source="knowledge_graph",
                                content=str(n),
                                score=_SOURCE_WEIGHTS["knowledge_concept"],
                            ))
                        for e in edges:
                            kw_list.append(KnowledgeChunk(
                                source="knowledge_graph",
                                content=str(e),
                                score=_SOURCE_WEIGHTS["knowledge_concept"] * 0.8,
                            ))
                        logger.debug(
                            "Knowledge: %d nodes + %d edges",
                            len(nodes), len(edges),
                        )

                # 合并记忆：按 source_weight 排序
                mem_list.sort(
                    key=lambda x: x.metadata.get("source_weight", 0.5),
                    reverse=True,
                )
                ctx.memory = mem_list
                ctx.knowledge = kw_list

            # Step 4: 归一化 + 去重
            ctx = self.merger.normalize(ctx)
            ctx = self.merger.deduplicate(ctx)

            logger.info(
                "Context built: memory=%d, knowledge=%d, tools=%d",
                len(ctx.memory), len(ctx.knowledge), len(ctx.tools),
            )
            return ctx

        except Exception as e:
            logger.error("Context build failed: %s", e, exc_info=True)
            raise ContextBuildError(f"Failed to build context: {e}") from e

    # ════════════════════════════════════════════════════════════
    # 旧流程（保留，阶段五删除）
    # ════════════════════════════════════════════════════════════

    async def _build_old(self, task: TaskSpec) -> UnifiedContext:
        """旧流程：仅 LTM 单源检索。"""
        try:
            flags = self.selector.select(task)
            logger.debug("Selected flags: %s", flags)
            routes = self.router.route(task, flags)
            logger.debug("Routes: %d collectors", len(routes))

            ctx = UnifiedContext()
            collector_map = {
                ContextFlag.IDENTITY: self.identity,
                ContextFlag.CONVERSATION: self.conversation,
                ContextFlag.ENVIRONMENT: self.environment,
            }

            active_routes = [r for r in routes if r.flag in collector_map]
            collect_tasks = [collector_map[r.flag].collect() for r in active_routes]

            memory_task = None
            if ContextFlag.MEMORY in flags:
                memory_task = asyncio.create_task(
                    self.long_term_memory.retrieve(
                        task.raw_input, top_k=25, intent=task.intent.value,
                    )
                )
                collect_tasks.append(memory_task)

            if collect_tasks:
                results = await asyncio.gather(*collect_tasks, return_exceptions=True)

                for idx, route in enumerate(active_routes):
                    if idx >= len(results):
                        break
                    result = results[idx]
                    if isinstance(result, Exception):
                        logger.warning(
                            "Collector %s failed: %s",
                            type(collector_map[route.flag]).__name__, result,
                        )
                        continue
                    if route.flag == ContextFlag.IDENTITY and result:
                        ctx.identity = result
                    elif route.flag == ContextFlag.CONVERSATION and result:
                        ctx.conversation = result
                    elif route.flag == ContextFlag.ENVIRONMENT and result:
                        ctx.environment = result

                if memory_task:
                    result = results[-1]
                    if isinstance(result, list):
                        ctx.memory = result
                        logger.debug("Retrieved %d memory items", len(result))

            ctx = self.merger.normalize(ctx)
            ctx = self.merger.deduplicate(ctx)

            logger.info(
                "Context built: memory=%d, knowledge=%d, tools=%d",
                len(ctx.memory), len(ctx.knowledge), len(ctx.tools),
            )
            return ctx

        except Exception as e:
            logger.error("Context build failed: %s", e, exc_info=True)
            raise ContextBuildError(f"Failed to build context: {e}") from e
