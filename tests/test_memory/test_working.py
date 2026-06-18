"""测试 WorkingMemory。"""

import pytest
from context_os.memory.working import WorkingMemory


class TestWorkingMemory:
    """WorkingMemory 测试。"""

    @pytest.fixture
    def wm(self):
        return WorkingMemory(max_tokens=100)

    def test_push_and_get(self, wm):
        """推入和获取。"""
        wm.push("hello")
        assert wm.item_count == 1
        recent = wm.get_recent(1)
        assert len(recent) == 1
        assert recent[0].content == "hello"

    def test_empty_working_memory(self, wm):
        """空记忆行为。"""
        assert wm.item_count == 0
        assert wm.get_recent(10) == []
        assert wm.peek() is None
        assert wm.pop() is None

    def test_eviction_when_exceed_budget(self, wm):
        """超过 Token 预算时淘汰。"""
        wm.push("a" * 400)  # 约 100 tokens，刚超限
        wm.push("b")
        # 第一条应该被淘汰
        assert wm.item_count == 1
        assert wm.peek().content == "b"

    def test_push_multi(self, wm):
        """批量推入。"""
        items = wm.push_multi([("a", None), ("b", None)])
        assert len(items) == 2
        assert wm.item_count == 2

    def test_clear(self, wm):
        """清空。"""
        wm.push("test")
        assert wm.item_count == 1
        wm.clear()
        assert wm.item_count == 0

    def test_find(self, wm):
        """关键词搜索。"""
        wm.push("hello world")
        wm.push("python programming")
        results = wm.find("python")
        assert len(results) == 1
        assert "python" in results[0].content
