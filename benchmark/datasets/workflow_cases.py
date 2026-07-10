"""工作流 Benchmark 测试用例。

验证 Context-OS 的多步骤任务编排和状态追踪能力。
"""

from benchmark.datasets.memory_cases import TestCase

WORKFLOW_TEST_CASES = [
    TestCase(
        id="W1",
        questions=[
            "步骤1：创建一个新项目叫做 my-app，使用 React 模板",
            "步骤2：为 my-app 添加用户登录功能",
            "步骤3：部署 my-app 到生产环境",
            "请问 my-app 项目完成了哪几个步骤？当前状态是什么？",
        ],
        description="工作流 - 3 步骤项目创建+状态追踪",
        tags=["workflow", "multi_step"],
        expected_keywords_per_q=[
            ["创建", "my-app", "React"],
            ["添加", "登录"],
            ["部署", "生产"],
            ["创建", "登录", "部署", "完成"],
        ],
        ground_truth="步骤1:创建完成 步骤2:添加登录完成 步骤3:部署完成 三个步骤全部完成",
    ),
]

__all__ = ["WORKFLOW_TEST_CASES"]
