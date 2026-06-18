"""TaskSpec 解析器。

将 IntentClassifier 和 EntityExtractor 的结果组装为统一的 TaskSpec 对象。
TaskSpec 是整个 Pipeline 的输入标准格式，后续所有阶段都基于它工作。
"""

from __future__ import annotations

from context_os.core.logger import get_logger
from context_os.core.models import Constraint, TaskSpec
from context_os.intent.classifier import IntentClassifier
from context_os.intent.extractor import EntityExtractor

logger = get_logger(__name__)


class TaskParser:
    """任务解析器。

    协调 IntentClassifier 和 EntityExtractor，将用户输入转为 TaskSpec。

    Args:
        classifier: 意图分类器实例。
        extractor: 实体提取器实例。
    """

    def __init__(self, classifier: IntentClassifier, extractor: EntityExtractor):
        self.classifier = classifier
        self.extractor = extractor
        logger.info("TaskParser initialized")

    async def parse(self, user_input: str) -> TaskSpec:
        """将用户输入解析为结构化的 TaskSpec。

        执行流程:
            1. 意图分类 → IntentType + GoalType + confidence
            2. 实体提取 → 命名实体列表
            3. 工具推断 → 工具需求列表
            4. 知识推断 → 知识需求列表
            5. 组装 TaskSpec

        Args:
            user_input: 用户的自然语言输入。

        Returns:
            结构化的 TaskSpec 对象。
        """
        logger.info("Parsing user input: \"%s\"", user_input[:100])

        # Step 1: 意图分类
        logger.debug("Step 1/4: Classifying intent...")
        intent, goal, confidence = await self.classifier.classify(user_input)

        # Step 2: 实体提取
        logger.debug("Step 2/4: Extracting entities...")
        entities = self.extractor.extract_entities(user_input)

        # Step 3: 工具需求推断
        logger.debug("Step 3/4: Detecting tool requirements...")
        tools = self.extractor.extract_tool_requirements(user_input)

        # Step 4: 知识需求推断
        logger.debug("Step 4/4: Detecting knowledge requirements...")
        knowledge = self.extractor.extract_knowledge_requirements(user_input)

        # 组装 TaskSpec
        task_spec = TaskSpec(
            raw_input=user_input,
            intent=intent,
            goal=goal,
            entities=entities,
            constraint=Constraint(),
            tool_requirements=tools,
            knowledge_requirements=knowledge,
            confidence=confidence,
        )

        logger.info(
            "Parsed TaskSpec: id=%s, intent=%s, goal=%s, confidence=%.2f, "
            "entities=%d, tools=%d, knowledge=%d",
            task_spec.id,
            intent.value,
            goal.value,
            confidence,
            len(entities),
            len(tools),
            len(knowledge),
        )

        return task_spec
