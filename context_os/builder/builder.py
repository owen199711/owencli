"""Context Builder — 组装 UnifiedContext。

编排 ContextSelector/ContextRouter/Collector/Memory，生成 UnifiedContext。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from context_os.builder.merger import ContextMerger
from context_os.collection.conversation import ConversationCollector
from context_os.collection.environment import EnvironmentCollector
from context_os.collection.identity import IdentityCollector
from context_os.core.logger import get_logger
from context_os.core.models import TaskSpec, UnifiedContext
from context_os.memory.long_term import LongTermMemory
from context_os.memory.working import WorkingMemory
from context_os.orchestrator.router import ContextFlag, ContextRouter
from context_os.orchestrator.selector import ContextSelector
from context_os.core.errors import ContextBuildError

logger = get_logger(__name__)


class ContextBuilder:
    """Context Builder — 组装 UnifiedContext。

    流程:
        1. selector.select(task) → flags
        2. router.route(task, flags) → routes
        3. 并行调用 collectors + memory.retrieve()
        4. merger.merge() + normalize() + deduplicate()
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
    ):
        self.selector = selector
        self.router = router
        self.identity = identity
        self.conversation = conversation
        self.environment = environment
        self.working_memory = working_memory
        self.long_term_memory = long_term_memory
        self.merger = merger or ContextMerger()
        logger.info("ContextBuilder initialized")

    async def build(self, task: TaskSpec) -> UnifiedContext:
        """构建完整的 UnifiedContext。

        Args:
            task: 已解析的 TaskSpec。

        Returns:
            构建好的 UnifiedContext。

        Raises:
            ContextBuildError: 构建过程中发生严重错误。
        """
        logger.info("Building context for task: %s (intent=%s)", task.id, task.intent.value)

        try:
            # Step 1: 选择需要哪些 Context
            flags = self.selector.select(task)
            logger.debug("Selected flags: %s", flags)

            # Step 2: 路由到收集器
            routes = self.router.route(task, flags)
            logger.debug("Routes: %d collectors", len(routes))

            # Step 3: 并行收集
            ctx = UnifiedContext()
            collector_map = {
                ContextFlag.IDENTITY: self.identity,
                ContextFlag.CONVERSATION: self.conversation,
                ContextFlag.ENVIRONMENT: self.environment,
            }

            # 按顺序收集：只含有 collector 的 route + 可选的 memory_task
            active_routes = [r for r in routes if r.flag in collector_map]
            collect_tasks = [collector_map[r.flag].collect() for r in active_routes]

            # 记忆检索（按 intent 动态适配）
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

                # 处理 collector 结果：按 flag 类型赋值到对应字段
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

                # 处理记忆检索结果（最后一个 task）
                if memory_task:
                    result = results[-1]
                    if isinstance(result, list):
                        ctx.memory = result
                        logger.debug("Retrieved %d memory items", len(result))

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
