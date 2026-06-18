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

            collect_tasks = []
            for route in routes:
                collector = collector_map.get(route.flag)
                if collector:
                    collect_tasks.append(collector.collect())

            # 记忆检索
            memory_task = None
            if ContextFlag.MEMORY in flags:
                memory_task = asyncio.create_task(
                    self.long_term_memory.retrieve(task.raw_input, top_k=5)
                )
                collect_tasks.append(memory_task)

            if collect_tasks:
                results = await asyncio.gather(*collect_tasks, return_exceptions=True)

                # 处理收集结果
                result_idx = 0
                for route in routes:
                    collector = collector_map.get(route.flag)
                    if collector and result_idx < len(results):
                        result = results[result_idx]
                        if isinstance(result, Exception):
                            logger.warning("Collector %s failed: %s", type(collector).__name__, result)
                        elif isinstance(result, UnifiedContext):
                            ctx = self.merger.merge([ctx, result])
                        result_idx += 1

                # 处理记忆检索结果
                if memory_task and result_idx < len(results):
                    result = results[result_idx]
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
