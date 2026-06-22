"""实体与参数提取器。

从用户输入中提取:
- 命名实体（如集群名、命名空间、Pod 名称等）
- 工具需求（推断完成该任务需要哪些工具）
- 知识需求（推断需要检索哪些领域的知识）

降级方案使用正则表达式匹配，也可对接 NER 模型或 LLM。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from context_os.core.logger import get_logger
from context_os.core.models import Entity, KnowledgeRequirement, ToolRequirement

logger = get_logger(__name__)


class EntityExtractor:
    """实体与参数提取器。

    负责从自然语言输入中提取结构化信息。
    """

    # ── 常见工具名模式 ──
    _TOOL_PATTERNS: List[Tuple[str, List[str], str]] = [
        # (工具名, 关键词列表, 权限)
        ("kubectl", ["kubectl", "k8s", "kubernetes", "集群", "cluster", "pod"], "readonly"),
        ("git", ["git", "commit", "push", "branch", "仓库"], "write"),
        ("npm", ["npm", "node", "package", "依赖"], "readonly"),
        ("pip", ["pip", "python", "requirements"], "readonly"),
        ("docker", ["docker", "container", "镜像", "镜像"], "readonly"),
        ("sql", ["sql", "database", "数据库", "mysql", "postgres"], "readonly"),
    ]

    # ── 领域关键词模式 ──
    _DOMAIN_PATTERNS: List[Tuple[str, List[str]]] = [
        ("kubernetes", ["k8s", "kubernetes", "集群", "pod", "container"]),
        ("python", ["python", "flask", "fastapi", "django"]),
        ("javascript", ["javascript", "js", "react", "vue", "node", "typescript"]),
        ("database", ["sql", "database", "数据库", "mysql", "postgres", "redis"]),
        ("devops", ["devops", "ci/cd", "jenkins", "github action", "deploy"]),
    ]

    # ── 通用实体提取模式 ──
    _ENTITY_PATTERNS: Dict[str, str] = {
        "cluster": r"(?:集群|cluster)[=:：\s]*([\w-]+)",
        "namespace": r"(?:命名空间|namespace)[=:：\s]*([\w-]+)",
        "pod": r"(?:pod|容器)[=:：\s]*([\w-]+)",
        "file": r"(?:文件|file)[=:：\s]*([\w./\\-]+)",
        "branch": r"(?:分支|branch)[=:：\s]*([\w./-]+)",
    }

    def __init__(self, llm_client: Optional[object] = None):
        """初始化提取器。

        Args:
            llm_client: 可选的大模型客户端，传入后可用于更精确的提取。
        """
        self.llm_client = llm_client
        logger.info(
            "EntityExtractor initialized (llm_client=%s)",
            "available" if llm_client else "None",
        )

    def extract_entities(self, user_input: str, domain: str = "") -> List[Entity]:
        """从输入中提取命名实体。

        先尝试正则匹配已知模式，再尝试提取未命名的 "名词-值" 对。

        Args:
            user_input: 用户输入字符串。
            domain: 可选的领域名称，帮助筛选实体类型。

        Returns:
            提取到的实体列表。
        """
        entities: List[Entity] = []
        input_lower = user_input.lower()

        # 遍历已知实体模式进行匹配
        for entity_type, pattern in self._ENTITY_PATTERNS.items():
            matches = re.finditer(pattern, input_lower)
            for match in matches:
                value = match.group(1).strip()
                entity = Entity(type=entity_type, value=value)
                entities.append(entity)
                logger.debug("Extracted entity: type=%s, value=%s", entity_type, value)

        # 尝试提取通用类型的实体（如服务名、模块名）
        self._extract_generic_entities(user_input, entities)

        if entities:
            logger.info("Extracted %d entities from input", len(entities))
        else:
            logger.debug("No entities extracted from input")

        return entities

    def extract_tool_requirements(self, user_input: str) -> List[ToolRequirement]:
        """推断完成任务需要哪些工具。

        Args:
            user_input: 用户输入字符串。

        Returns:
            工具需求列表。
        """
        tools: List[ToolRequirement] = []
        input_lower = user_input.lower()

        for tool_name, keywords, permission in self._TOOL_PATTERNS:
            if any(kw in input_lower for kw in keywords):
                tool = ToolRequirement(name=tool_name, required=False, permission=permission)
                tools.append(tool)
                logger.debug("Detected tool requirement: %s (permission=%s)", tool_name, permission)

        if tools:
            logger.info("Detected %d tool requirements", len(tools))
        else:
            logger.debug("No tool requirements detected")

        return tools

    def extract_knowledge_requirements(self, user_input: str) -> List[KnowledgeRequirement]:
        """推断需要检索哪些领域的知识。

        Args:
            user_input: 用户输入字符串。

        Returns:
            知识需求列表。
        """
        requirements: List[KnowledgeRequirement] = []
        input_lower = user_input.lower()

        for domain, keywords in self._DOMAIN_PATTERNS:
            if any(kw in input_lower for kw in keywords):
                req = KnowledgeRequirement(domain=domain, query=user_input[:200], top_k=5)
                requirements.append(req)
                logger.debug("Detected knowledge requirement: domain=%s", domain)

        if requirements:
            logger.info("Detected %d knowledge requirements", len(requirements))
        else:
            logger.debug("No knowledge requirements detected")

        return requirements

    # ── Private Methods ──────────────────────────────────────────

    @staticmethod
    def _extract_generic_entities(user_input: str, entities: List[Entity]) -> None:
        """尝试提取通用类型实体（如被引号包裹的特定名词）。

        Args:
            user_input: 用户输入。
            entities: 结果追加到该列表中。
        """
        # 提取引号中的内容作为通用实体
        # 用 triple-quote 避免内部双引号冲突
        quoted = re.findall(r"""["'`]([\w./\\-]+)["'`]""", user_input)
        for q in quoted:
            # 避免重复
            if not any(e.value == q for e in entities):
                entity = Entity(type="reference", value=q)
                entities.append(entity)
                logger.debug("Extracted generic entity: reference=%s", q)
