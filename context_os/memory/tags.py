"""Experience 标签常量和工具函数。

Experience 支持多标签，一条记录可以同时拥有多个标签。
例如一条包含 SQL 工具的反思：["reflection", "tool_usage", "sql"]
"""

from __future__ import annotations


class ExperienceTag:
    """Experience 标签常量。"""

    EPISODE = "episode"
    REFLECTION = "reflection"
    PROCEDURE = "procedure"
    TOOL_USAGE = "tool_usage"

    ALL_CORE = [EPISODE, REFLECTION, PROCEDURE, TOOL_USAGE]

    # 扩展标签（非核心类型，用于更细粒度的分类）
    SQL = "sql"
    API = "api"
    DEBUGGING = "debugging"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    CONFIGURATION = "configuration"


def normalize_tag(tag: str) -> str:
    """将标签字符串规范化为小写下划线格式。

    Args:
        tag: 原始标签字符串。

    Returns:
        规范化后的标签。

    Examples:
        >>> normalize_tag("SQL Query")
        'sql_query'
        >>> normalize_tag("Tool Usage")
        'tool_usage'
    """
    return tag.lower().strip().replace(" ", "_").replace("-", "_")


def validate_tags(tags: list[str]) -> list[str]:
    """验证并规范化标签列表，过滤无效标签。

    Args:
        tags: 原始标签列表。

    Returns:
        规范化后的标签列表（去重、排序）。
    """
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        normalized = normalize_tag(tag)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return sorted(result)
