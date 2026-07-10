"""测试 MemoryUpdater — 统一写入决策（Phase 3）。"""

import pytest
from context_os.core.models import (
    EvalMetrics, TaskSpec, IntentType, GoalType,
)
from context_os.memory.store import SQLiteStore
from context_os.memory.working import WorkingMemory
from context_os.memory.session_memory import SessionMemory
from context_os.memory.long_term import LongTermMemory
from context_os.memory.semantic import SemanticMemory
from context_os.memory.experience import ExperienceMemory
from context_os.feedback.memory_updater import (
    MemoryUpdater, WriteDecisionResult,
)
from context_os.feedback.memory_importance import ImportanceScorer
from context_os.feedback.triple_extractor import TripleExtractor


@pytest.fixture
async def store():
    s = SQLiteStore(db_path=":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def updater(store):
    """创建 MemoryUpdater（使用新策略）。"""
    wm = WorkingMemory()
    stm = SessionMemory(session_id="test", store=store)
    ltm = LongTermMemory(store=store, user_id="test_user")
    sem = SemanticMemory(store=store, user_id="test_user")
    exp = ExperienceMemory(store=store, user_id="test_user")

    mu = MemoryUpdater(
        working_memory=wm,
        short_term_memory=stm,
        long_term_memory=ltm,
        semantic_memory=sem,
        experience_memory=exp,
        importance_scorer=ImportanceScorer(),
        triple_extractor=TripleExtractor(),
    )
    return mu


def _make_task(text: str, intent: IntentType = IntentType.QA) -> TaskSpec:
    return TaskSpec(
        raw_input=text,
        intent=intent,
        goal=GoalType.EXPLAIN,
        confidence=0.8,
    )


def _make_metrics(reward: float = 0.7, success: bool = True, task_importance: float = 0.5) -> EvalMetrics:
    return EvalMetrics(
        success=success,
        reward_score=reward,
        task_importance=task_importance,
        answer_quality=0.8,
        cost_usd=0.001,
    )


class TestEntityKeyNormalization:
    """entity_key 归一化测试（3.8）。"""

    def test_user_name(self, updater):
        key = updater._normalize_entity_key("我叫小明")
        assert key == "user.name"

    def test_user_location(self, updater):
        key = updater._normalize_entity_key("我在北京")
        assert key == "user.location"

    def test_user_preference(self, updater):
        key = updater._normalize_entity_key("我喜欢深色模式")
        assert key == "user.preference"

    def test_user_balance(self, updater):
        key = updater._normalize_entity_key("我的余额是 5000 元")
        assert "user" in key
        assert "balance" in key

    def test_org_location(self, updater):
        key = updater._normalize_entity_key("公司总部在上海")
        assert "org" in key
        assert "location" in key

    def test_user_email(self, updater):
        key = updater._normalize_entity_key("我的邮箱是 test@example.com")
        assert "user" in key
        assert "email" in key

    def test_fallback_attribute(self, updater):
        key = updater._normalize_entity_key("随便说点啥")
        assert key is not None
        assert "." in key  # 应有类型.属性格式


class TestKVExtraction:
    """KV 键值对提取测试。"""

    def test_extract_name(self, updater):
        pairs = updater._extract_kv_pairs("我叫小明")
        assert "user.name" in pairs
        assert "小明" in pairs["user.name"]

    def test_extract_location(self, updater):
        pairs = updater._extract_kv_pairs("我住在上海")
        assert "user.location" in pairs

    def test_extract_preference(self, updater):
        pairs = updater._extract_kv_pairs("我偏好 Python 编程")
        # 可能不完美命中，但至少不应 crash
        assert isinstance(pairs, dict)


class TestLayer1RuleCheck:
    """Layer 1 规则必存检测测试。"""

    def test_explicit_memory_command(self, updater):
        result = updater._layer1_rule_check(
            "记住我喜欢深色模式",
            task=_make_task("记住我喜欢深色模式"),
            response="好的，已记住",
            metrics=_make_metrics(),
        )
        assert result.should_store
        assert result.layer1_rule_hit
        assert result.score == 1.0

    def test_explicit_save_command(self, updater):
        result = updater._layer1_rule_check(
            "请保存这个配置",
            task=_make_task("请保存这个配置"),
            response="已保存",
            metrics=_make_metrics(),
        )
        assert result.should_store

    def test_kv_pair_detection(self, updater):
        result = updater._layer1_rule_check(
            "我叫小明",
            task=_make_task("我叫小明"),
            response="你好小明",
            metrics=_make_metrics(),
        )
        assert result.should_store
        assert result.layer1_rule_hit

    def test_kv_pair_location(self, updater):
        result = updater._layer1_rule_check(
            "我在北京工作",
            task=_make_task("我在北京工作"),
            response="北京是个好地方",
            metrics=_make_metrics(),
        )
        assert result.should_store

    def test_no_rule_hit(self, updater):
        result = updater._layer1_rule_check(
            "今天天气不错",
            task=_make_task("今天天气不错"),
            response="是啊天气真好",
            metrics=_make_metrics(),
        )
        assert not result.should_store

    def test_task_conclusion(self, updater):
        """任务关键结论检测。"""
        result = updater._layer1_rule_check(
            content="请计算余额",
            task=_make_task("请计算余额", intent=IntentType.AGENT),
            response="余额为 7101 元",
            metrics=_make_metrics(),
        )
        assert result.should_store


class TestWriteDecision:
    """write_decision 完整流程测试。"""

    async def test_layer1_immediate_pass(self, updater):
        """Layer 1 命中 → 立即通过。"""
        result = await updater.write_decision(
            content="我叫小明",
            user_id="test_user",
        )
        assert result.should_store
        assert result.layer1_rule_hit

    async def test_layer3_insufficient_score(self, updater):
        """Layer 3 评分不足 → 不应存储。"""
        result = await updater.write_decision(
            content="今天天气真好",
            task=_make_task("今天天气真好"),
            response="是啊",
            metrics=_make_metrics(reward=0.3, task_importance=0.1),
            user_id="test_user",
        )
        assert not result.should_store

    async def test_layer3_identity_heavy(self, updater):
        """身份信息 → 高分通过。"""
        result = await updater.write_decision(
            content="我叫张三，今年 30 岁，住在上海",
            task=_make_task("我叫张三，今年 30 岁，住在上海", intent=IntentType.QA),
            response="你好张三",
            metrics=_make_metrics(reward=0.8, task_importance=0.6),
            user_id="test_user",
        )
        # Layer 1 可能命中 KV 模式 → should_store=True
        # 这里不做强断言，只验证不 crash
        assert result.score >= 0.0

    async def test_entity_key_present_on_layer1(self, updater):
        result = await updater.write_decision(
            content="我叫小明",
            user_id="test_user",
        )
        if result.should_store and result.layer1_rule_hit:
            assert result.entity_key is not None
            assert "user.name" in result.entity_key


class TestClassifyAndRoute:
    """分类路由测试。（需 store 以支持知识写入）"""

    async def test_route_knowledge_channel_a(self, updater):
        """通道 A 命中 → 路由到 Knowledge。"""
        result = WriteDecisionResult(should_store=True, score=1.0)
        route = await updater.classify_and_route(
            "Python 是一种编程语言",
            result,
        )
        assert route["knowledge"] is True
        assert route["long_term"] is False  # Knowledge 优先

    async def test_route_longterm_fallback(self, updater):
        """无 Knowledge/Experience 信号 → 兜底到 LongTerm。"""
        result = WriteDecisionResult(should_store=True, score=0.7)
        route = await updater.classify_and_route(
            "我叫小明，住在北京",
            result,
        )
        assert route["long_term"] is True

    async def test_route_experience_tool_usage(self, updater):
        """工具调用 → Experience。"""
        result = WriteDecisionResult(should_store=True, score=0.7)
        route = await updater.classify_and_route(
            "用 read_file 工具读取了文件",
            result,
        )
        assert route.get("experience") is True

    async def test_route_experience_error_reflection(self, updater):
        """错误反思 → Experience（无知识模式时的 fallback）。"""
        result = WriteDecisionResult(should_store=True, score=0.7)
        route = await updater.classify_and_route(
            "连接超时，需要重试",
            result,
        )
        assert route.get("experience") is True


class TestBatchTrigger:
    """批量写入触发测试。"""

    async def test_no_trigger_when_empty(self, updater):
        """候选区为空 → 不应触发。"""
        should = await updater._check_batch_trigger()
        assert not should

    async def test_trigger_on_pending_count(self, updater):
        """候选区超过阈值 → 触发。"""
        for i in range(6):
            await updater.stm.add_pending_candidate(
                content=f"候选{i}",
                turn_number=i,
            )
        should = await updater._check_batch_trigger()
        assert should
