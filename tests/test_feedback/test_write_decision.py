"""WriteDecision 测试（Phase 8）。

覆盖 Layer 1 (规则必存), Layer 2 (新颖度过滤), Layer 3 (重要性评分)。
"""

import pytest
from context_os.feedback.write_decision import WriteDecision, WriteDecisionResult


class FakeStore:
    """轻量 fake SQLiteStore，用于隔离 LTM 的 store 依赖。"""
    def __init__(self):
        self.memories: dict[str, dict] = {}
        self.is_connected = True
    async def connect(self): pass
    async def execute(self, sql, params=None):
        pass
    async def query_memories(self, type=None, user_id=None, top_k=10, query_text=None):
        return []
    async def save_memory(self, id, type, content, user_id, embedding=None, metadata=None):
        self.memories[id] = {"id": id, "type": type, "content": content, "embedding": embedding, "metadata": metadata or {}}
        return id
    async def delete_memory(self, id):
        self.memories.pop(id, None)
        return True
    async def get_memory(self, id):
        return self.memories.get(id)
    async def query(self, sql, params=None):
        return []
    async def cleanup_journal(self):
        return 0
    async def query_experiences(self, **kw):
        return []


class FakeEmbeddingProvider:
    """Fake embedding provider 返回固定长度向量。"""
    def __init__(self, dim=128):
        self.dim = dim
    async def embed(self, text):
        import hashlib
        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        import random
        rng = random.Random(h)
        return [rng.random() for _ in range(self.dim)]
    async def embed_batch(self, texts):
        results = []
        for t in texts:
            results.append(await self.embed(t))
        return results


class FakeLTM:
    """轻量 fake LongTermMemory，无需真实 SQLite。"""
    def __init__(self, store=None):
        self.store = store or FakeStore()
        self._embedding_provider = None

    def detect_temporal_query(self, text):
        return False

    async def retrieve(self, query, top_k=10, **kw):
        return []

    async def save(self, content, memory_type="long_term", metadata=None, embedding=None, user_id="anonymous"):
        import uuid
        mid = uuid.uuid4().hex
        await self.store.save_memory(mid, memory_type, content, user_id, embedding, metadata)
        return mid

    @staticmethod
    def _cosine_similarity(a, b):
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = nA = nB = 0.0
        for va, vb in zip(a, b):
            dot += va * vb
            nA += va * va
            nB += vb * vb
        denom = (nA ** 0.5) * (nB ** 0.5)
        return dot / denom if denom != 0 else 0.0


@pytest.fixture
def fake_ltm():
    return FakeLTM()


@pytest.fixture
def write_decision(fake_ltm):
    return WriteDecision(ltm=fake_ltm)


@pytest.fixture
def write_decision_with_emb(fake_ltm):
    fake_ltm._embedding_provider = FakeEmbeddingProvider()
    return WriteDecision(ltm=fake_ltm)


# ═══════════════════════════════════════════════════════════
# Layer 1: 规则必存
# ═══════════════════════════════════════════════════════════

class TestWriteDecisionLayer1:
    """Layer 1 测试：规则必存检测。"""

    def test_explicit_memory_keyword_remember(self, write_decision):
        """"记住" 关键词触发 Layer 1 通过。"""
        result = write_decision._layer1_rule_check(
            "记住我叫小明", task=None, response="好的", metrics=None,
        )
        assert result.should_store is True
        assert result.layer1_rule_hit is True
        assert result.score == 1.0

    def test_explicit_memory_keyword_record(self, write_decision):
        """'记录' 关键词触发 Layer 1 通过。"""
        result = write_decision._layer1_rule_check(
            "记录一下：用户偏好 Python", task=None, response="", metrics=None,
        )
        assert result.should_store is True
        assert result.layer1_rule_hit is True

    def test_explicit_memory_keyword_save(self, write_decision):
        """'保存' 关键词触发 Layer 1。"""
        result = write_decision._layer1_rule_check(
            "保存：数据库连接地址是 10.0.0.1", task=None, response="", metrics=None,
        )
        assert result.should_store is True

    def test_kv_pattern_name(self, write_decision):
        """KV 键值对 "我叫X" 模式触发 Layer 1。"""
        result = write_decision._layer1_rule_check(
            "我叫小明，今年25岁", task=None, response="", metrics=None,
        )
        assert result.should_store is True
        assert len(result.candidates) > 0

    def test_kv_pattern_location(self, write_decision):
        """KV 键值对 "我住在Y" 模式触发 Layer 1。"""
        result = write_decision._layer1_rule_check(
            "我住在北京朝阳区", task=None, response="", metrics=None,
        )
        assert result.should_store is True

    def test_no_layer1_match(self, write_decision):
        """普通语句不触发 Layer 1。"""
        result = write_decision._layer1_rule_check(
            "今天天气不错", task=None, response="", metrics=None,
        )
        assert result.should_store is False

    def test_conclusion_pattern(self, write_decision):
        """任务关键结论触发 Layer 1。"""
        from context_os.core.models import TaskSpec, IntentType, GoalType, EvalMetrics
        task = TaskSpec(
            raw_input="查询余额", intent=IntentType.QA, goal=GoalType.EXPLAIN, confidence=0.8,
        )
        result = write_decision._layer1_rule_check(
            "查询余额", task=task, response="余额为 10.5 万元", metrics=EvalMetrics(),
        )
        assert result.should_store is True
        assert "task.conclusion" in (result.entity_key or "")


# ═══════════════════════════════════════════════════════════
# Layer 2: 新颖度过滤
# ═══════════════════════════════════════════════════════════

class TestWriteDecisionLayer2:
    """Layer 2 测试：新颖度过滤。"""

    @pytest.mark.asyncio
    async def test_skip_no_embedding_provider(self, write_decision):
        """无 embedding provider 时跳过 Layer 2。"""
        passed, ek = await write_decision._layer2_novelty_check("test", "user")
        assert passed is True

    @pytest.mark.asyncio
    async def test_pass_when_no_existing(self, write_decision_with_emb):
        """无现有记忆时 Layer 2 通过。"""
        passed, ek = await write_decision_with_emb._layer2_novelty_check("new content", "user")
        assert passed is True

    @pytest.mark.asyncio
    async def test_entity_value_compare_all_unchanged(self, write_decision_with_emb):
        """所有实体值不变时 Layer 2 拒绝（重复内容）。"""
        result = write_decision_with_emb._entity_value_compare(
            "我叫小明，住在北京",
            {"content": "我叫小明，住在北京"},
        )
        passed, _ = result
        assert passed is False

    @pytest.mark.asyncio
    async def test_entity_value_compare_update(self, write_decision_with_emb):
        """实体值变更时 Layer 2 通过。"""
        result = write_decision_with_emb._entity_value_compare(
            "我叫小明，住在上海",
            {"content": "我叫小明，住在北京"},
        )
        passed, _ = result
        assert passed is True

    @pytest.mark.asyncio
    async def test_entity_value_compare_no_kv(self, write_decision_with_emb):
        """无法提取 KV 时 Layer 2 拒绝。"""
        result = write_decision_with_emb._entity_value_compare(
            "今天天气好",
            {"content": "昨天天气差"},
        )
        passed, _ = result
        assert passed is False


# ═══════════════════════════════════════════════════════════
# Layer 3: 重要性评分
# ═══════════════════════════════════════════════════════════

class TestWriteDecisionLayer3:
    """Layer 3 测试：重要性评分。"""

    def test_importance_score_returned(self, write_decision):
        """Layer 3 返回 ImportanceScore 结构。"""
        from context_os.core.models import EvalMetrics
        score = write_decision._layer3_importance_score(
            "用户喜欢使用 VSCode 编辑器",
            user_id="user1",
            task_intent="coding",
            metrics=EvalMetrics(reward_score=0.8),
        )
        assert score is not None
        assert 0 <= score.overall <= 1

    def test_identity_content_scores_higher(self, write_decision):
        """身份相关内容得分应较高。"""
        from context_os.core.models import EvalMetrics
        score1 = write_decision._layer3_importance_score(
            "我叫张三，是一名后端工程师",
            user_id="user1",
            task_intent="coding",
            metrics=EvalMetrics(reward_score=0.7),
        )
        score2 = write_decision._layer3_importance_score(
            "今天天气不错",
            user_id="user1",
            task_intent="qa",
            metrics=EvalMetrics(reward_score=0.7),
        )
        assert score1.identity >= score2.identity


# ═══════════════════════════════════════════════════════════
# 完整 decide()
# ═══════════════════════════════════════════════════════════

class TestWriteDecisionDecide:
    """完整 decide() 端到端测试。"""

    @pytest.mark.asyncio
    async def test_decide_memory_keyword(self, write_decision):
        """'记住' 关键词直接通过三层决策。"""
        result = await write_decision.decide("记住我叫张三", user_id="test")
        assert isinstance(result, WriteDecisionResult)
        assert result.should_store is True
        assert result.layer1_rule_hit is True

    @pytest.mark.asyncio
    async def test_decide_trivial_content(self, write_decision):
        """琐碎内容可能不通过 Layer 3。"""
        result = await write_decision.decide(
            "嗯好", user_id="test", task_intent="qa",
        )
        assert isinstance(result, WriteDecisionResult)
        # 不应存储琐碎内容
        assert result.should_store is False

    @pytest.mark.asyncio
    async def test_decide_kv_pattern(self, write_decision):
        """KV 模式直接通过。"""
        result = await write_decision.decide(
            "我使用的语言是 Python", user_id="test",
        )
        assert result.should_store is True

    @pytest.mark.asyncio
    async def test_extract_kv_pairs(self, write_decision):
        """提取 KV 对。"""
        pairs = write_decision._extract_kv_pairs("我叫小明，住在北京")
        assert isinstance(pairs, dict)

    def test_normalize_entity_key(self, write_decision):
        """entity_key 归一化。"""
        key = write_decision._normalize_entity_key("我叫小明")
        assert key is not None
        assert "name" in key
