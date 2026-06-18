"""Context 路由器。

将 ContextSelector 选出的 ContextFlag 转换为具体的数据源路由列表。
每个路由指向一个收集器（Collector），按优先级排序。

数据流向:
    ContextFlag → ContextRoute (source + priority) → Collector
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from context_os.core.logger import get_logger
from context_os.core.models import TaskSpec
from context_os.orchestrator.selector import ContextFlag

logger = get_logger(__name__)


@dataclass
class ContextRoute:
    """一条路由记录。

    Attributes:
        source: 数据源标识，对应 Collector 的名称。
        flag: 关联的 ContextFlag 类型。
        priority: 优先级（0-100），越大越优先。
    """
    source: str
    flag: ContextFlag
    priority: int = 50


# ── 默认路由表 ──
# 每个 ContextFlag 到具体数据源的映射
DEFAULT_ROUTES: list[ContextRoute] = [
    # (source, flag, priority)
    ContextRoute("conversation_store", ContextFlag.CONVERSATION, priority=90),
    ContextRoute("identity_provider", ContextFlag.IDENTITY, priority=80),
    ContextRoute("memory_store", ContextFlag.MEMORY, priority=70),
    ContextRoute("knowledge_store", ContextFlag.KNOWLEDGE, priority=60),
    ContextRoute("env_provider", ContextFlag.ENVIRONMENT, priority=50),
    ContextRoute("tool_registry", ContextFlag.TOOLS, priority=40),
]


class ContextRouter:
    """Context 路由器。

    将 ContextFlag 组合转换为按优先级排列的路由列表。
    下游根据路由列表依次调用对应的 Collector。

    使用示例:
        router = ContextRouter()
        routes = router.route(task_spec, flags)
        for route in routes:
            collector = get_collector(route.source)
            await collector.collect(...)
    """

    def __init__(self):
        logger.info(
            "ContextRouter initialized with %d default routes",
            len(DEFAULT_ROUTES),
        )

    def route(self, task: TaskSpec, flags: ContextFlag) -> List[ContextRoute]:
        """将 ContextFlag 转换为路由列表。

        流程:
            1. 从默认路由表中筛选出 flags 中包含的条目。
            2. 按优先级降序排列。
            3. 返回排序后的路由列表。

        Args:
            task: 当前任务的 TaskSpec（用于可能的额外路由决策）。
            flags: ContextSelector 选择的 ContextFlag 组合。

        Returns:
            按优先级降序排列的路由列表。
        """
        logger.debug(
            "Routing context: flags=%s, task=%s",
            flags, task.id,
        )

        # 筛选 + 排序
        routes = sorted(
            [route for route in DEFAULT_ROUTES if route.flag in flags],
            key=lambda r: r.priority,
            reverse=True,
        )

        # 如果 Token 预算有限且路由过多，裁减低优先级路由
        if task.constraint.max_tokens and task.constraint.max_tokens < 16000:
            max_routes = 3 if task.constraint.max_tokens < 8000 else 5
            if len(routes) > max_routes:
                logger.info(
                    "Token budget limited (%d), reducing routes from %d to %d",
                    task.constraint.max_tokens, len(routes), max_routes,
                )
                routes = routes[:max_routes]

        logger.info(
            "Routing result: %d routes selected",
            len(routes),
        )
        for route in routes:
            logger.debug("  Route: source=%s, priority=%d", route.source, route.priority)

        return routes
