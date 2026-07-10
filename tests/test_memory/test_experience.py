"""测试 ExperienceMemory — 统一体验记忆层。"""

import pytest
from datetime import datetime, timedelta, timezone

from context_os.memory.store import SQLiteStore
from context_os.memory.experience import ExperienceMemory


@pytest.fixture
async def store():
    """创建内存 SQLite 存储（每测试用例独立）。"""
    s = SQLiteStore(db_path=":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def exp(store):
    """创建 ExperienceMemory 实例。"""
    return ExperienceMemory(store=store, user_id="test_user")


# ═══════════════════════════════════════════════════════════════
# 1. CRUD — 各子类型存储
# ═══════════════════════════════════════════════════════════════


class TestSaveEpisode:
    """episode 子类型存储。"""

    async def test_save_basic(self, exp):
        """基本 episode 保存。"""
        eid = await exp.save(
            experience_type="episode",
            scene="测试场景",
            action="执行了操作",
            result="成功",
            feedback="positive",
            tags=["test", "success"],
        )
        assert eid
        assert len(eid) == 32  # uuid hex

    async def test_record_episode_convenience(self, exp):
        """record_episode 便捷方法。"""
        eid = await exp.record_episode(
            scene="用户询问代码",
            action="Agent 生成代码",
            result="编译通过",
            feedback="positive",
            tags=["coding"],
        )
        assert eid
        results = await exp.recall_relevant(
            experience_type="episode", tags=["coding"], top_k=10,
        )
        assert len(results) == 1
        assert results[0]["scene"] == "用户询问代码"
        assert results[0]["experience_type"] == "episode"

    async def test_record_success(self, exp):
        """record_success 自动加 success 标签。"""
        eid = await exp.record_success(
            scene="部署成功",
            action="执行 deploy",
            result="部署完成",
            tags=["deploy"],
        )
        assert eid
        results = await exp.recall_by_tag("success", experience_type="episode")
        assert len(results) >= 1
        assert results[0]["feedback"] == "positive"

    async def test_record_failure(self, exp):
        """record_failure 自动加 failure 标签。"""
        eid = await exp.record_failure(
            scene="部署失败",
            action="执行 deploy",
            error="权限不足",
            tags=["deploy"],
        )
        assert eid
        results = await exp.recall_by_tag("failure", experience_type="episode")
        assert len(results) >= 1
        assert "Failed:" in results[0]["result"]
        assert results[0]["feedback"] == "negative"


class TestSaveReflection:
    """reflection 子类型存储。"""

    async def test_save_basic(self, exp):
        """基本 reflection 保存。"""
        eid = await exp.save(
            experience_type="reflection",
            task_type="coding",
            root_cause="未检查边界条件",
            lesson="编写单元测试覆盖边界",
            preventive_action="添加 CI 检查",
            tags=["coding", "lesson"],
        )
        assert eid

    async def test_record_reflection_convenience(self, exp):
        """record_reflection 便捷方法。"""
        eid = await exp.record_reflection(
            task_type="debugging",
            root_cause="未检查空指针",
            lesson="添加空值检查",
            preventive_action="lint 规则",
            success=False,
            tags=["debug"],
        )
        assert eid
        results = await exp.recall_relevant(
            experience_type="reflection", tags=["failure"], top_k=10,
        )
        assert len(results) == 1
        assert "debugging" in results[0]["task_type"]
        assert "空值检查" in results[0]["lesson"]


class TestSaveProcedure:
    """procedure 子类型存储。"""

    async def test_save_basic(self, exp):
        """基本 procedure 保存。"""
        eid = await exp.save(
            experience_type="procedure",
            proc_name="单元测试流程",
            steps_json='["1. 写测试", "2. 运行 pytest", "3. 检查覆盖率"]',
            total_count=5,
            proc_success_count=4,
            tags=["testing", "workflow"],
        )
        assert eid

    async def test_record_procedure_convenience(self, exp):
        """record_procedure 便捷方法。"""
        eid = await exp.record_procedure(
            name="代码审查流程",
            steps=["1. 读 diff", "2. 检查命名", "3. 运行测试", "4. 批准"],
            description="标准 CR 流程",
            tags=["cr", "workflow"],
            total_count=10,
            success_count=9,
        )
        assert eid
        results = await exp.recall_relevant(
            experience_type="procedure", tags=["cr"], top_k=10,
        )
        assert len(results) == 1
        assert results[0]["proc_name"] == "代码审查流程"
        # steps 已被 _row_to_dict 自动反序列化，直接读取列表
        steps = results[0]["steps"]
        assert isinstance(steps, list)
        assert len(steps) == 4


class TestSaveToolUsage:
    """tool_usage 子类型存储。"""

    async def test_save_basic(self, exp):
        """基本 tool_usage 保存。"""
        eid = await exp.save(
            experience_type="tool_usage",
            tool_name="search_code",
            tool_success=1,
            duration_ms=350,
            scenario="搜索 FastAPI 路由定义",
            input_preview="/api/users",
            output_preview="Found 3 matches",
            tags=["search", "fastapi"],
        )
        assert eid

    async def test_record_tool_usage_convenience(self, exp):
        """record_tool_usage 便捷方法（bool→int）。"""
        eid = await exp.record_tool_usage(
            tool_name="execute_shell",
            success=True,
            duration_ms=120,
            scenario="运行 pytest",
            input_preview="pytest tests/ -v",
            output_preview="42 passed",
            tags=["testing"],
        )
        assert eid
        results = await exp.recall_relevant(
            experience_type="tool_usage", top_k=10,
        )
        assert len(results) == 1
        assert results[0]["tool_success"] == 1
        assert results[0]["tool_name"] == "execute_shell"


# ═══════════════════════════════════════════════════════════════
# 2. 检索
# ═══════════════════════════════════════════════════════════════


class TestRecallByTag:
    """按标签检索。"""

    async def test_single_tag(self, exp):
        """单个标签检索。"""
        await exp.record_episode(
            scene="s1", action="a1", result="r1", tags=["python", "coding"],
        )
        await exp.record_episode(
            scene="s2", action="a2", result="r2", tags=["golang", "coding"],
        )
        results = await exp.recall_by_tag("python")
        assert len(results) >= 1
        assert all("python" in r.get("tags", []) for r in results)

    async def test_tag_with_type_filter(self, exp):
        """标签 + 类型联合筛选。"""
        await exp.record_episode(
            scene="s1", action="a1", result="r1", tags=["shared_tag"],
        )
        await exp.record_reflection(
            task_type="debugging", root_cause="bug", lesson="fix",
            tags=["shared_tag"],
        )
        results = await exp.recall_by_tag("shared_tag", experience_type="episode")
        assert len(results) == 1
        assert results[0]["experience_type"] == "episode"


class TestRecallRelevant:
    """多条件检索。"""

    async def test_type_filter(self, exp):
        """按子类型筛选。"""
        await exp.record_episode(scene="ep", action="a", result="r")
        await exp.record_reflection(
            task_type="coding", root_cause="r", lesson="l",
        )
        results = await exp.recall_relevant(experience_type="episode")
        assert len(results) == 1
        assert results[0]["experience_type"] == "episode"

    async def test_tags_filter(self, exp):
        """多标签 OR 匹配。"""
        await exp.record_episode(
            scene="s1", action="a1", result="r1", tags=["alpha"],
        )
        await exp.record_episode(
            scene="s2", action="a2", result="r2", tags=["beta"],
        )
        results = await exp.recall_relevant(
            experience_type="episode", tags=["alpha", "beta"],
        )
        assert len(results) == 2

    async def test_scenario_query(self, exp):
        """场景关键词模糊匹配。"""
        await exp.record_tool_usage(
            tool_name="search_code",
            success=True,
            scenario="搜索数据库连接代码",
        )
        await exp.record_tool_usage(
            tool_name="execute_shell",
            success=True,
            scenario="运行单元测试",
        )
        results = await exp.recall_relevant(
            experience_type="tool_usage", scenario_query="数据库",
        )
        assert len(results) == 1
        assert "数据库" in results[0]["scenario"]

    async def test_created_after(self, exp):
        """时间范围筛选。"""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        await exp.record_episode(scene="old", action="a", result="r")
        results = await exp.recall_relevant(
            experience_type="episode", created_after=future,
        )
        assert len(results) == 0

    async def test_top_k(self, exp):
        """返回数量限制。"""
        for i in range(10):
            await exp.record_episode(
                scene=f"scene_{i}", action=f"action_{i}", result=f"result_{i}",
            )
        results = await exp.recall_relevant(experience_type="episode", top_k=3)
        assert len(results) == 3


class TestRecallSimilar:
    """兼容旧 EpisodicMemory.recall_similar 接口。"""

    async def test_scene_match(self, exp):
        """场景关键词匹配。"""
        await exp.record_episode(
            scene="部署 Django 应用到 Kubernetes",
            action="执行 kubectl apply",
            result="部署成功",
            tags=["deploy"],
        )
        results = await exp.recall_similar("Django 应用")
        assert len(results) >= 1

    async def test_no_match(self, exp):
        """无匹配时返回空。"""
        results = await exp.recall_similar("不存在的场景")
        assert results == []


class TestGetRecentExperiences:
    """获取最近记录（兼容旧接口）。"""

    async def test_recent_all(self, exp):
        """获取最近的记录。"""
        await exp.record_episode(scene="1", action="a", result="r")
        await exp.record_reflection(task_type="t", root_cause="r", lesson="l")
        results = await exp.get_recent_experiences(top_k=10)
        assert len(results) == 2

    async def test_recent_by_type(self, exp):
        """按类型获取最近记录。"""
        await exp.record_episode(scene="1", action="a", result="r")
        await exp.record_tool_usage(
            tool_name="test", success=True, scenario="test",
        )
        results = await exp.get_recent_experiences(
            top_k=10, experience_type="tool_usage",
        )
        assert len(results) == 1
        assert results[0]["experience_type"] == "tool_usage"


# ═══════════════════════════════════════════════════════════════
# 3. 统计
# ═══════════════════════════════════════════════════════════════


class TestStats:
    """统计和工具聚合。"""

    async def test_get_stats_empty(self, exp):
        """空统计。"""
        stats = await exp.get_stats()
        assert stats["total_count"] == 0
        assert stats["by_type"] == {}
        assert stats["tool_stats"] == []

    async def test_get_stats_with_data(self, exp):
        """有数据时的统计。"""
        await exp.record_episode(scene="1", action="a", result="r")
        await exp.record_episode(scene="2", action="a2", result="r2")
        await exp.record_reflection(task_type="t", root_cause="r", lesson="l")
        await exp.record_tool_usage(
            tool_name="search", success=True, duration_ms=100,
            scenario="test",
        )
        await exp.record_tool_usage(
            tool_name="search", success=False, duration_ms=200,
            scenario="test2",
        )

        stats = await exp.get_stats()
        assert stats["total_count"] == 5
        assert stats["by_type"]["episode"] == 2
        assert stats["by_type"]["reflection"] == 1
        assert stats["by_type"]["tool_usage"] == 2

    async def test_get_latest_tool_stats(self, exp):
        """工具成功率实时聚合。"""
        await exp.record_tool_usage(
            tool_name="search", success=True, duration_ms=100,
            scenario="query1",
        )
        await exp.record_tool_usage(
            tool_name="search", success=False, duration_ms=200,
            scenario="query2",
        )
        await exp.record_tool_usage(
            tool_name="execute", success=True, duration_ms=50,
            scenario="cmd1",
        )

        stats = await exp.get_latest_tool_stats()
        assert len(stats) == 2  # search, execute

        search_stat = next(s for s in stats if s["tool_name"] == "search")
        assert search_stat["total_calls"] == 2
        assert search_stat["success_calls"] == 1
        assert search_stat["avg_duration_ms"] == 150.0  # (100+200)/2

        exec_stat = next(s for s in stats if s["tool_name"] == "execute")
        assert exec_stat["total_calls"] == 1
        assert exec_stat["success_calls"] == 1
        assert exec_stat["avg_duration_ms"] == 50.0

    async def test_get_latest_tool_stats_filter(self, exp):
        """按工具名筛选统计。"""
        await exp.record_tool_usage(
            tool_name="search", success=True, duration_ms=100,
            scenario="test",
        )
        await exp.record_tool_usage(
            tool_name="execute", success=True, duration_ms=50,
            scenario="test",
        )

        stats = await exp.get_latest_tool_stats(tool_name="search")
        assert len(stats) == 1
        assert stats[0]["tool_name"] == "search"

    async def test_get_stats_by_type(self, exp):
        """按指定类型获取统计。"""
        for i in range(3):
            await exp.record_episode(scene=f"s{i}", action=f"a{i}", result=f"r{i}")
        await exp.record_tool_usage(
            tool_name="t1", success=True, scenario="test",
        )

        stats = await exp.get_stats(experience_type="episode")
        assert stats["total_count"] == 3
        assert stats["by_type"] == {"episode": 3}


# ═══════════════════════════════════════════════════════════════
# 4. 更新与边界
# ═══════════════════════════════════════════════════════════════


class TestUpdateFeedback:
    """更新 episode 反馈。"""

    async def test_update(self, exp):
        """更新反馈。"""
        eid = await exp.record_episode(
            scene="s", action="a", result="r", feedback="positive",
        )
        ok = await exp.update_feedback(eid, "negative")
        assert ok

    async def test_update_nonexistent(self, exp):
        """更新不存在的记录返回 False。"""
        ok = await exp.update_feedback("nonexistent_id", "negative")
        assert not ok


class TestEdgeCases:
    """边界测试。"""

    async def test_invalid_experience_type(self, exp):
        """非法子类型抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid experience_type"):
            await exp.save(experience_type="invalid_type")

    async def test_multiple_users_isolation(self, store):
        """多用户数据隔离。"""
        exp_a = ExperienceMemory(store=store, user_id="user_a")
        exp_b = ExperienceMemory(store=store, user_id="user_b")

        await exp_a.record_episode(scene="a's scene", action="a", result="r")
        await exp_b.record_episode(scene="b's scene", action="b", result="r")

        a_results = await exp_a.recall_relevant(experience_type="episode")
        b_results = await exp_b.recall_relevant(experience_type="episode")

        assert len(a_results) == 1
        assert len(b_results) == 1
        assert a_results[0]["scene"] == "a's scene"
        assert b_results[0]["scene"] == "b's scene"

    async def test_metadata_storage(self, exp):
        """metadata 正确存取。"""
        eid = await exp.save(
            experience_type="episode",
            scene="s", action="a", result="r",
            metadata={"source": "test", "version": 2},
        )
        results = await exp.recall_relevant(experience_type="episode")
        assert results[0]["metadata"]["source"] == "test"
        assert results[0]["metadata"]["version"] == 2
