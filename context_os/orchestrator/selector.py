"""动态上下文选择器。

根据 TaskSpec 中的意图类型（IntentType），动态决定本次请求需要收集
哪些维度的 Context。避免每次都加载全部上下文，减少 Token 浪费。

核心思想：
    - QA 类任务 → 只需要对话历史和知识
    - Coding 类 → 需要身份、环境、记忆、工具等全部上下文
    - Search 类 → 只需要知识
"""

from __future__ import annotations

from enum import Flag, auto

from context_os.core.logger import get_logger
from context_os.core.models import IntentType, TaskSpec

logger = get_logger(__name__)


class ContextFlag(Flag):
    """上下文类型标志位。

    使用 Flag 枚举，支持按位组合（如 IDENTITY | CONVERSATION）。
    """
    IDENTITY = auto()         # 用户身份信息
    CONVERSATION = auto()     # 对话历史
    ENVIRONMENT = auto()      # 系统环境
    MEMORY = auto()           # 记忆系统
    KNOWLEDGE = auto()        # 外部知识
    TOOLS = auto()            # 工具上下文


# ── 意图 → 所需 Context 映射表 ──
# 每种意图类型对应一个 ContextFlag 组合
INTENT_CONTEXT_MAP: dict[IntentType, ContextFlag] = {
    IntentType.QA:            ContextFlag.CONVERSATION | ContextFlag.KNOWLEDGE,
    IntentType.CODING:        (
        ContextFlag.IDENTITY | ContextFlag.CONVERSATION
        | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
        | ContextFlag.TOOLS
    ),
    IntentType.DEBUGGING:     (
        ContextFlag.IDENTITY | ContextFlag.CONVERSATION
        | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
        | ContextFlag.KNOWLEDGE | ContextFlag.TOOLS
    ),
    IntentType.PLANNING:      ContextFlag.CONVERSATION | ContextFlag.MEMORY | ContextFlag.KNOWLEDGE,
    IntentType.SEARCH:        ContextFlag.KNOWLEDGE,
    IntentType.WORKFLOW:      ContextFlag.CONVERSATION | ContextFlag.ENVIRONMENT | ContextFlag.TOOLS,
    IntentType.AGENT:         (
        ContextFlag.IDENTITY | ContextFlag.CONVERSATION
        | ContextFlag.ENVIRONMENT | ContextFlag.MEMORY
        | ContextFlag.KNOWLEDGE | ContextFlag.TOOLS
    ),
    IntentType.DATA_ANALYSIS: ContextFlag.CONVERSATION | ContextFlag.ENVIRONMENT | ContextFlag.TOOLS,
}


class ContextSelector:
    """动态上下文选择器。

    根据 TaskSpec 决策需要收集哪些 Context。

    使用示例:
        selector = ContextSelector()
        flags = selector.select(task_spec)
    """

    # Token 预算阈值：低于此值时裁减低优先级 Context
    TIGHT_TOKEN_THRESHOLD = 8000

    def __init__(self):
        logger.info(
            "ContextSelector initialized with %d intent mappings",
            len(INTENT_CONTEXT_MAP),
        )

    def select(self, task: TaskSpec) -> ContextFlag:
        """根据 TaskSpec 选择需要的 Context 类型。

        执行流程:
            1. 从映射表中查找当前意图对应的默认 ContextFlag。
            2. 如果 Token 预算紧张，裁减低优先级 Context (MEMORY, ENVIRONMENT)。
            3. 根据领域信息做进一步调整。

        Args:
            task: 已解析的 TaskSpec。

        Returns:
            组合后的 ContextFlag。
        """
        logger.debug(
            "Selecting context for task: intent=%s, goal=%s",
            task.intent.value, task.goal.value,
        )

        # Step 1: 获取默认 flags
        flags = INTENT_CONTEXT_MAP.get(task.intent, ContextFlag.CONVERSATION)
        logger.debug("Default flags for %s: %s", task.intent.value, flags)

        # Step 2: Token 预算紧张时裁减
        if task.constraint.max_tokens and task.constraint.max_tokens < self.TIGHT_TOKEN_THRESHOLD:
            logger.info(
                "Token budget tight (%d < %d), removing low-priority contexts",
                task.constraint.max_tokens,
                self.TIGHT_TOKEN_THRESHOLD,
            )
            flags &= ~ContextFlag.MEMORY
            flags &= ~ContextFlag.ENVIRONMENT
            logger.debug("Flags after pruning: %s", flags)

        # Step 3: 领域调整
        if task.domain == "simple_qa":
            # 简单的问答不需要工具上下文
            flags &= ~ContextFlag.TOOLS
            logger.debug("Domain is simple_qa, removed TOOLS flag")

        logger.info(
            "Context selection complete: %s (intent=%s, domain=%s)",
            flags, task.intent.value, task.domain,
        )
        return flags
