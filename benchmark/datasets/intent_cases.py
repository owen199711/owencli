"""意图分类 Benchmark 测试用例。

专门验证 Context-OS Intent Layer 的意图分类能力。

测试覆盖:
    STORE_FACT  — 用户提供新信息
    UPDATE_FACT — 用户修改已有信息
    QUERY_FACT  — 用户查询已有信息
    SUMMARY     — 用户要求总结
    REFLECTION  — 用户要求反思/分析原因
    CALL_TOOL   — 用户要求调用工具
"""

from benchmark.datasets.memory_cases import TestCase

# ═══════════════════════════════════════════════════════════════════
# INT1: STORE_FACT 基础
# ═══════════════════════════════════════════════════════════════════

INT1 = TestCase(
    id="INT1",
    questions=[
        "帮我记住小明今年18岁",
        "帮我记住小明的身高是175cm",
        "帮我记住小明的爱好是打篮球",
        "帮我记住小红是班里的学习委员",
        "帮我记住小红的生日是3月15日",
    ],
    description="意图分类 - STORE_FACT：5 条信息存入",
    tags=["intent", "store"],
    expected_intent=["STORE_FACT"] * 5,
    expected_keywords_per_q=[
        ["小明", "18"],
        ["小明", "175"],
        ["小明", "篮球"],
        ["小红", "学习委员"],
        ["小红", "3月15"],
    ],
    expected_json={
        "小明_年龄": "18",
        "小明_身高": "175cm",
        "小明_爱好": "篮球",
        "小红_职务": "学习委员",
        "小红_生日": "3月15日",
    },
)

# ═══════════════════════════════════════════════════════════════════
# INT2: UPDATE_FACT 修改
# ═══════════════════════════════════════════════════════════════════

INT2 = TestCase(
    id="INT2",
    questions=[
        "帮我记住数据库连接池大小=10",
        "把连接池大小改成20",
        "把连接池大小改成50",
        "帮我记住超时时间=30秒",
        "把超时改成60秒",
    ],
    description="意图分类 - UPDATE_FACT：创建+修改交替",
    tags=["intent", "update"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "STORE_FACT", "UPDATE_FACT",
    ],
    expected_keywords_per_q=[
        ["连接池", "10"],
        ["20"],
        ["50"],
        ["超时", "30"],
        ["60"],
    ],
    expected_json={
        "连接池": "50",
        "超时": "60",
    },
)

# ═══════════════════════════════════════════════════════════════════
# INT3: QUERY_FACT 查询
# ═══════════════════════════════════════════════════════════════════

INT3 = TestCase(
    id="INT3",
    questions=[
        "帮我记住小明的年龄是18岁，身高175cm，爱好篮球",
        "小明今年多大了？",
        "小明的身高是多少？",
        "小明的爱好是什么？",
    ],
    description="意图分类 - QUERY_FACT：存储后查询",
    tags=["intent", "query"],
    expected_intent=[
        "STORE_FACT", "QUERY_FACT", "QUERY_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["18", "175", "篮球"],
        ["18"],
        ["175"],
        ["篮球"],
    ],
    expected_json={
        "小明_年龄": "18",
        "小明_身高": "175cm",
        "小明_爱好": "篮球",
    },
)

# ═══════════════════════════════════════════════════════════════════
# INT4: 混合意图
# ═══════════════════════════════════════════════════════════════════

INT4 = TestCase(
    id="INT4",
    questions=[
        "帮我记住服务器的状态：CPU=50%，内存=60%",
        "把CPU改成75%",
        "现在CPU是多少？",
        "帮我总结一下服务器的所有状态",
        "为什么CPU会从50%升到75%？分析一下可能的原因",
    ],
    description="意图分类 - 混合：STORE→UPDATE→QUERY→SUMMARY→REFLECTION",
    tags=["intent", "mixed"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "QUERY_FACT",
        "SUMMARY", "REFLECTION",
    ],
    expected_keywords_per_q=[
        ["CPU", "50", "内存", "60"],
        ["75"],
        ["75"],
        ["CPU", "内存"],
        ["分析", "原因"],
    ],
    expected_json={
        "CPU": "75%",
        "内存": "60%",
    },
)

# ═══════════════════════════════════════════════════════════════════
# INT5: CALL_TOOL 调用
# ═══════════════════════════════════════════════════════════════════

INT5 = TestCase(
    id="INT5",
    questions=[
        "帮我查一下数据库里的用户表",
        "执行SQL: SELECT * FROM users",
        "帮我发一封邮件给张三",
        "调用天气API查北京的天气",
    ],
    description="意图分类 - CALL_TOOL：4 种工具调用",
    tags=["intent", "tool"],
    expected_intent=[
        "CALL_TOOL", "CALL_TOOL", "CALL_TOOL", "CALL_TOOL",
    ],
    expected_keywords_per_q=[
        ["数据库", "用户表"],
        ["SELECT", "users"],
        ["邮件", "张三"],
        ["天气", "北京"],
    ],
    expected_json={
        "工具1": "查用户表",
        "工具2": "执行SQL",
        "工具3": "发邮件",
        "工具4": "查天气",
    },
)

INTENT_TEST_CASES = [INT1, INT2, INT3, INT4, INT5]

__all__ = ["INTENT_TEST_CASES"]
