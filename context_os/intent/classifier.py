"""意图分类器。

负责将用户自然语言输入归类为预定义的意图类型（IntentType）和目标类型（GoalType）。

使用策略:
    1. LLM 模式: 调用大模型进行语义分类，准确率更高。
    2. 降级模式: 基于关键词规则匹配，不依赖外部 LLM 服务。
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from context_os.core.logger import get_logger
from context_os.core.models import GoalType, IntentType

# 当前模块的 logger
logger = get_logger(__name__)


class IntentClassifier:
    """意图分类器。

    将用户输入解析为 (IntentType, GoalType, confidence) 三元组。

    Args:
        llm_client: 可选的大模型客户端，传入后使用 LLM 进行语义分类。
        fallback_mode: 降级模式，固定为 "regex"。
    """

    # ── 关键词规则映射表 ──
    # 每条规则对应一个 (IntentType, GoalType, 权重) 三元组
    _INTENT_RULES: list[tuple[list[str], IntentType, GoalType, float]] = [
        (["debug", "fix", "bug", "crash", "error", "issue", "修复", "错误", "异常"],
         IntentType.DEBUGGING, GoalType.FIX, 0.7),
        (["write", "create", "implement", "code", "generate", "编写", "创建", "实现"],
         IntentType.CODING, GoalType.GENERATE, 0.7),
        (["refactor", "重构", "重写", "优化"],
         IntentType.CODING, GoalType.REFACTOR, 0.7),
        (["search", "find", "lookup", "查询", "搜索", "查找"],
         IntentType.SEARCH, GoalType.EXPLAIN, 0.7),
        (["plan", "设计", "方案", "计划", "架构"],
         IntentType.PLANNING, GoalType.GENERATE, 0.7),
        (["explain", "what is", "什么是", "介绍", "解释", "how to"],
         IntentType.QA, GoalType.EXPLAIN, 0.7),
        (["summarize", "总结", "摘要", "概括"],
         IntentType.QA, GoalType.SUMMARIZE, 0.7),
        (["compare", "区别", "对比", "vs", "versus", "与"],
         IntentType.QA, GoalType.COMPARE, 0.7),
        (["analyze", "分析", "数据分析", "chart", "图表"],
         IntentType.DATA_ANALYSIS, GoalType.EXPLAIN, 0.7),
        (["workflow", "流程", "自动化", "pipeline"],
         IntentType.WORKFLOW, GoalType.GENERATE, 0.7),
    ]

    _CLASSIFY_PROMPT = """Classify the following user request into intent and goal categories.

Available intents: {intents}
Available goals: {goals}

Return ONLY valid JSON with fields: intent, goal, confidence
- intent: one of the available intents above
- goal: one of the available goals above
- confidence: float between 0 and 1

User: {user_input}

JSON:"""

    def __init__(self, llm_client: Optional[object] = None, fallback_mode: str = "regex"):
        """初始化分类器。

        Args:
            llm_client: 实现 BaseLLMClient 接口的客户端实例。
            fallback_mode: LLM 不可用时的降级策略，目前仅支持 "regex"。
        """
        self.llm_client = llm_client
        self.fallback_mode = fallback_mode
        logger.info(
            "IntentClassifier initialized (llm_client=%s, fallback=%s)",
            "available" if llm_client else "None",
            fallback_mode,
        )

    async def classify(self, user_input: str) -> Tuple[IntentType, GoalType, float]:
        """对用户输入进行意图分类。

        Args:
            user_input: 用户的自然语言输入。

        Returns:
            (IntentType, GoalType, confidence) 三元组。
        """
        logger.debug("Classifying input: \"%s\"", user_input[:100])

        if self.llm_client:
            try:
                logger.debug("Attempting LLM-based classification...")
                result = await self._classify_with_llm(user_input)
                logger.info(
                    "LLM classification: intent=%s, goal=%s, confidence=%.2f",
                    result[0].value, result[1].value, result[2],
                )
                return result
            except Exception as e:
                logger.warning("LLM classification failed, falling back to regex: %s", e)

        # 降级到关键词规则
        logger.debug("Fallback to regex-based classification")
        result = self._classify_with_rules(user_input)
        logger.info(
            "Regex classification: intent=%s, goal=%s, confidence=%.2f",
            result[0].value, result[1].value, result[2],
        )
        return result

    # ── Private Methods ──────────────────────────────────────────

    def _classify_with_rules(self, user_input: str) -> Tuple[IntentType, GoalType, float]:
        """使用关键词规则进行降级分类。

        遍历 _INTENT_RULES，统计匹配的关键词数量，取匹配最多的规则。
        如果没有任何规则匹配，默认返回 QA/EXPLAIN。

        Args:
            user_input: 用户输入字符串。

        Returns:
            (IntentType, GoalType, confidence)。
        """
        input_lower = user_input.lower()
        best_match: Optional[tuple[IntentType, GoalType, float]] = None
        best_score = 0

        for keywords, intent, goal, base_confidence in self._INTENT_RULES:
            match_count = sum(1 for kw in keywords if kw in input_lower)
            if match_count > 0:
                # 命中越多关键词，置信度越高，但不超过 base_confidence + 0.2
                score = min(base_confidence + match_count * 0.1, 0.95)
                if score > best_score:
                    best_score = score
                    best_match = (intent, goal, score)

        if best_match:
            return best_match

        # 默认兜底
        logger.debug("No rules matched, defaulting to QA/EXPLAIN")
        return IntentType.QA, GoalType.EXPLAIN, 0.5

    async def _classify_with_llm(self, user_input: str) -> Tuple[IntentType, GoalType, float]:
        """使用 LLM 进行语义分类。

        Args:
            user_input: 用户输入字符串。

        Returns:
            (IntentType, GoalType, confidence)。

        Raises:
            ValueError: LLM 返回格式异常时抛出。
        """
        prompt = self._CLASSIFY_PROMPT.format(
            intents=[e.value for e in IntentType],
            goals=[e.value for e in GoalType],
            user_input=user_input,
        )

        response = await self.llm_client.complete(
            prompt=prompt,
            response_format="json",
            max_tokens=200,
            temperature=0.3,
        )

        # 解析 LLM 返回的 JSON
        if isinstance(response, str):
            result = json.loads(response)
        else:
            result = response

        intent = IntentType(result["intent"])
        goal = GoalType(result["goal"])
        confidence = float(result.get("confidence", 0.8))

        return intent, goal, confidence
