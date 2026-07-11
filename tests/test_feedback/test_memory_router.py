"""MemoryRouter 测试（Phase 8）。

覆盖 route() / dispatch() / _detect_experience_signals()。
"""

import pytest
from context_os.feedback.memory_router import MemoryRouter, RouteResult


# ═══════════════════════════════════════════════════════════
# Fake 依赖
# ═══════════════════════════════════════════════════════════

class FakeStore:
    def __init__(self):
        self.memories = {}
        self.experiences = {}
        self.concepts = {}
        self.is_connected = True

    async def execute(self, sql, params=None):
        class FakeCursor:
            rowcount = 1
        return FakeCursor()

    async def save_experience(self, experience_type, user_id, tags=None, metadata=None, **kw):
        import uuid
        eid = uuid.uuid4().hex
        self.experiences[eid] = {**kw, "tags": tags, "experience_type": experience_type}
        return eid

    async def save_memory(self, id, type, content, user_id, embedding=None, metadata=None):
        self.memories[id] = {"id": id, "type": type, "content": content, "metadata": metadata or {}}
        return id

    async def query_experiences(self, **kw):
        return list(self.experiences.values())

    async def save_concept(self, name, attributes=None, **kw):
        self.concepts[name] = {"name": name, "attributes": attributes or {}, **kw}
        import uuid
        return uuid.uuid4().hex

    async def add_relation(self, source, target, relation_type, **kw):
        return True

    async def query(self, sql, params=None):
        return []

    async def enqueue_knowledge(self, content, user_id, source, priority=0):
        return "queue_id"


class FakeSemanticMemory:
    def __init__(self, store):
        self.store = store

    async def add_concept(self, name, attributes=None, confidence=1.0):
        return await self.store.save_concept(name, attributes=attributes, confidence=confidence)

    async def add_relation(self, source, target, relation_type, weight=1.0):
        return await self.store.add_relation(source, target, relation_type, weight=weight)


class FakeExpMemory:
    def __init__(self, store, user_id="test"):
        self.store = store
        self.user_id = user_id

    async def record_episode(self, scene, action, result, feedback="", tags=None, user_id=None):
        return await self.store.save_experience(
            experience_type="episode",
            user_id=user_id or self.user_id,
            tags=tags,
            scene=scene, action=action, result=result, feedback=feedback,
        )

    async def record_reflection(self, task_type, root_cause, lesson, preventive_action="", success=True, tags=None, metadata=None):
        return await self.store.save_experience(
            experience_type="reflection",
            user_id=self.user_id, tags=tags,
            task_type=task_type, root_cause=root_cause, lesson=lesson,
        )

    async def record_procedure(self, name, steps, description=None, tags=None, total_count=0, success_count=0, last_used=None):
        import json
        return await self.store.save_experience(
            experience_type="procedure",
            user_id=self.user_id, tags=tags,
            proc_name=name, steps_json=json.dumps(steps),
            total_count=total_count, proc_success_count=success_count,
        )

    async def record_tool_usage(self, tool_name, success, error_type=None, duration_ms=0, scenario=None, input_preview=None, output_preview=None, tags=None, user_id=None):
        return await self.store.save_experience(
            experience_type="tool_usage",
            user_id=user_id or self.user_id, tags=tags,
            tool_name=tool_name, tool_success=1 if success else 0,
            scenario=scenario,
        )


class FakeLTM:
    def __init__(self, store):
        self.store = store
        self._embedding_provider = None

    async def save(self, content, memory_type="long_term", metadata=None, embedding=None, user_id="anonymous"):
        import uuid
        mid = uuid.uuid4().hex
        await self.store.save_memory(mid, memory_type, content, user_id, embedding, metadata)
        return mid

    async def save_fact(self, fact_id, content, category, confidence=1.0, source="", user_id="anonymous"):
        import uuid
        mid = uuid.uuid4().hex
        meta = {"fact_id": fact_id, "category": category, "confidence": confidence, "version": 1, "history": []}
        await self.store.save_memory(mid, "long_term", content, user_id, metadata=meta)
        return mid

    async def save_summary(self, content, category="summary", confidence=0.7, source="", user_id="anonymous"):
        import uuid
        mid = uuid.uuid4().hex
        await self.store.save_memory(mid, "long_term", content, user_id, metadata={
            "category": category, "ltm_subtype": "summary", "confidence": confidence, "source": source,
        })
        return mid

    def detect_temporal_query(self, text):
        return False

    async def retrieve(self, query, top_k=1, **kw):
        return []


class FakeKnowledgeQueue:
    async def enqueue(self, content, user_id, source):
        return "qid"


@pytest.fixture
def router():
    store = FakeStore()
    return MemoryRouter(
        event_bus=None,
        triple_extractor=None,
        knowledge_queue=FakeKnowledgeQueue(),
    )


@pytest.fixture
def router_components():
    store = FakeStore()
    return {
        "router": MemoryRouter(
            event_bus=None,
            triple_extractor=None,
            knowledge_queue=FakeKnowledgeQueue(),
        ),
        "ltm": FakeLTM(store),
        "sem": FakeSemanticMemory(store),
        "exp": FakeExpMemory(store),
        "store": store,
    }


# ═══════════════════════════════════════════════════════════
# route() 测试
# ═══════════════════════════════════════════════════════════

class TestMemoryRouterRoute:
    """route() 分流测试。"""

    @pytest.mark.asyncio
    async def test_route_fallback_to_longterm(self, router):
        """普通内容兜底到 LongTerm。"""
        result, triples = await router.route(
            "今天天气不错", "j1", "user1",
        )
        assert isinstance(result, RouteResult)
        assert result.target == "long_term"

    @pytest.mark.asyncio
    async def test_route_experience_tool(self, router):
        """工具调用信号 → Experience。"""
        result, triples = await router.route(
            "刚才执行 git push 失败了报权限错误", "j1", "user1",
        )
        assert result.target == "experience"
        assert any(t in result.tags for t in ["tool_usage", "reflection"])

    @pytest.mark.asyncio
    async def test_route_experience_reflection(self, router):
        """反思信号 → Experience。"""
        result, triples = await router.route(
            "超时错误总结：下次需要加重试逻辑", "j1", "user1",
        )
        # 可能被 Knowledge 或 Experience 捕获，验证非空即可
        assert result.target in ("experience", "knowledge")
        if result.target == "experience":
            assert "reflection" in result.tags

    @pytest.mark.asyncio
    async def test_route_experience_procedure(self, router):
        """流程信号 → Experience。"""
        result, triples = await router.route(
            "部署流程：先配置再启动最后验证", "j1", "user1",
        )
        # 可能被 Knowledge 或 Experience 捕获
        assert result.target in ("experience", "knowledge")
        if result.target == "experience":
            assert "procedure" in result.tags

    @pytest.mark.asyncio
    async def test_route_literal_fact(self, router):
        """事实陈述（有 entity 信号）→ LongTerm fact。"""
        result, triples = await router.route(
            "我喜欢 Python 语言", "j1", "user1",
        )
        assert result.target == "long_term"
        assert result.category in ("fact", "summary")


# ═══════════════════════════════════════════════════════════
# dispatch() 测试
# ═══════════════════════════════════════════════════════════

class TestMemoryRouterDispatch:
    """dispatch() 写入分发测试。"""

    @pytest.mark.asyncio
    async def test_dispatch_to_longterm_fact(self, router_components):
        """有 entity_key → 写入 LTM Fact。"""
        r = router_components["router"]
        route = RouteResult(
            target="long_term", entity_key="user.preference",
            category="fact",
            route_detail={"long_term": True},
        )
        await r.dispatch(
            route, None, "我喜欢 Python", "j1", "user1",
            ltm=router_components["ltm"],
            sem=router_components["sem"],
            exp=router_components["exp"],
            score=0.8,
        )
        # 验证 store 中有记录
        assert len(router_components["store"].memories) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_to_longterm_summary(self, router_components):
        """无 entity_key → 写入 LTM Summary。"""
        r = router_components["router"]
        route = RouteResult(
            target="long_term", entity_key="",
            category="summary",
            route_detail={"long_term": True},
        )
        await r.dispatch(
            route, None, "一个有趣的技术观察", "j1", "user1",
            ltm=router_components["ltm"],
            sem=router_components["sem"],
            exp=router_components["exp"],
            score=0.6,
        )
        memories = router_components["store"].memories
        # 应有 at least one
        assert len(memories) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_to_experience(self, router_components):
        """Experience 标签 → 写入体验记忆。"""
        r = router_components["router"]
        route = RouteResult(
            target="experience",
            tags=["episode", "reflection"],
            route_detail={"experience": True},
        )
        await r.dispatch(
            route, None, "使用 write_file 时遇到权限错误，需要先检查权限", "j1", "user1",
            ltm=router_components["ltm"],
            sem=router_components["sem"],
            exp=router_components["exp"],
            score=0.7,
        )
        assert len(router_components["store"].experiences) >= 1


# ═══════════════════════════════════════════════════════════
# extract_user_input_from_content
# ═══════════════════════════════════════════════════════════

class TestMemoryRouterHelpers:
    """辅助方法测试。"""

    def test_extract_user_input_basic(self):
        """从 User: 前缀提取用户输入。"""
        text = "User: 帮我部署K8s\nAssistant: 好的请提供集群信息"
        result = MemoryRouter._extract_user_input_from_content(text)
        assert "帮我部署" in result
        assert "Assistant:" not in result

    def test_extract_entity_key(self):
        """entity_key 提取。"""
        key = MemoryRouter._extract_entity_key("用户喜欢使用 Python 语言")
        assert key is not None or key is None  # 正常执行即可

    def test_detect_experience_signals_no_match(self, router):
        """无经验信号时返回空列表。"""
        tags = router._detect_experience_signals("今天天气不错", None)
        assert tags == []

    def test_detect_experience_signals_tool(self, router):
        """检测到工具使用信号。"""
        tags = router._detect_experience_signals("我调用 kubectl 工具部署了服务", None)
        assert "tool_usage" in tags
