"""RAG（检索增强生成）Benchmark 测试用例。

验证 Context-OS 的知识检索和 Context 注入能力。
"""

from benchmark.datasets.memory_cases import TestCase

# ═══════════════════════════════════════════════════════════════════
# R1: 知识问答
# ═══════════════════════════════════════════════════════════════════

R1 = TestCase(
    id="R1",
    questions=[
        "什么是 Ebbinghaus 遗忘曲线？",
        "根据遗忘曲线，20 分钟后的记忆保留率是多少？",
        "间隔复习的最佳时间间隔是多久？",
        "请总结 Ebbinghaus 遗忘曲线的核心发现和实际应用",
    ],
    description="RAG - 知识检索: Ebbinghaus 遗忘曲线知识问答",
    tags=["rag", "knowledge"],
    expected_intent=[
        "QUERY_FACT", "QUERY_FACT", "QUERY_FACT", "SUMMARY",
    ],
    expected_keywords_per_q=[
        ["Ebbinghaus", "遗忘曲线", "记忆"],
        ["20", "58%"],
        ["间隔", "复习"],
        ["Ebbinghaus", "遗忘曲线", "58%", "间隔", "复习"],
    ],
    expected_json={
        "概念": "Ebbinghaus遗忘曲线",
        "20分钟保留率": "58%",
        "核心方法": "间隔复习",
    },
)

# ═══════════════════════════════════════════════════════════════════
# R2: 多文档检索
# ═══════════════════════════════════════════════════════════════════

R2 = TestCase(
    id="R2",
    questions=[
        "Python 中列表和元组的区别是什么？",
        "Python 的装饰器有什么用？",
        "Python 的 GIL 是什么？",
    ],
    description="RAG - 多文档: Python 编程知识检索",
    tags=["rag", "programming"],
    expected_intent=[
        "QUERY_FACT", "QUERY_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["列表", "元组", "区别"],
        ["装饰器"],
        ["GIL"],
    ],
    expected_json={
        "Q1": "列表可变/元组不可变",
        "Q2": "装饰器增强函数",
        "Q3": "全局解释器锁",
    },
)

# ═══════════════════════════════════════════════════════════════════
# R3: 混合检索（准确数字+概念）
# ═══════════════════════════════════════════════════════════════════

R3 = TestCase(
    id="R3",
    questions=[
        "Redis 的默认端口是多少？",
        "Redis 支持哪些数据结构？",
        "Redis 的持久化方式有哪些？",
        "Redis 的主从复制原理是什么？",
    ],
    description="RAG - 混合检索: Redis 知识（含精确数字+概念）",
    tags=["rag", "database"],
    expected_intent=[
        "QUERY_FACT", "QUERY_FACT", "QUERY_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["6379"],
        ["String", "Hash", "List", "Set"],
        ["RDB", "AOF"],
        ["主从", "复制"],
    ],
    expected_json={
        "默认端口": "6379",
        "数据结构": "String/Hash/List/Set",
        "持久化": "RDB/AOF",
    },
)

RAG_TEST_CASES = [R1, R2, R3]

__all__ = ["RAG_TEST_CASES"]
