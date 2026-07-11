"""UnifiedRetriever + SourceAdapter 测试（Phase 8）。

覆盖:
    - ScoringEngine 统一评分
    - 5 个 SourceAdapter 的 search()
    - UnifiedRetriever 四步流程 (Search → Score → Merge → Rank)
    - 跨源去重
"""

import json
import math
import pytest
from datetime import datetime, timezone

from context_os.retriever.adapter import (
    RetrievedItem, LTMAdapter, ExperienceAdapter,
    KnowledgeAdapter, SessionAdapter, JournalAdapter,
)
from context_os.retriever.retriever import UnifiedRetriever
from context_os.retriever.scoring import ScoringEngine, SourceReliability, SourceWeight


# ═══════════════════════════════════════════════════════════
# Fake Dependencies
# ═══════════════════════════════════════════════════════════

class FakeLTM:
    def __init__(self):
        self._embedding_provider = None

    def detect_temporal_query(self, text):
        return False

    async def retrieve(self, query, top_k=10, intent=None, expand_history=False):
        return [
            {"content": "用户偏好 Python 语言", "metadata": {"source": "ltm", "fact_id": "user.preference"}, "score": 0.8, "embedding": None, "timestamp": "2024-01-01T00:00:00Z"},
            {"content": "项目使用 FastAPI 框架", "metadata": {"source": "ltm", "fact_id": "project.stack"}, "score": 0.6, "embedding": None, "timestamp": "2024-01-02T00:00:00Z"},
        ]


class FakeExpMemory:
    async def recall_relevant(self, scenario_query, top_k=10):
        return [
            {"scene": "部署 K8s 服务", "experience_type": "episode", "created_at": "2024-01-01T00:00:00Z", "tags": ["episode", "tool_usage"]},
        ]


class FakeSemanticMemory:
    async def query(self, concept, depth=1):
        return {
            "nodes": [{"name": "Python", "type": "language"}, {"name": "FastAPI", "type": "framework"}],
            "edges": [{"source": "FastAPI", "target": "Python", "relation": "built_on"}],
        }


class FakeSessionMemory:
    async def query_pending(self, query, top_k=10):
        return [
            {"content": "用户询问过 K8s 部署问题", "metadata": {"turn_number": 5}, "timestamp": "2024-01-01T00:00:00Z"},
        ]


class FakeJournalStore:
    async def query_pending(self, limit=10):
        return [
            {"raw_input": "帮我部署 K8s 集群", "task_intent": "coding", "status": "pending", "id": "j1", "created_at": "2024-01-01T00:00:00Z"},
        ]


# ═══════════════════════════════════════════════════════════
# ScoringEngine 测试
# ═══════════════════════════════════════════════════════════

class TestScoringEngine:
    def test_basic_score(self):
        """基本打分返回 0-1 之间。"""
        engine = ScoringEngine()
        score = engine.score(
            {"metadata": {"source_reliability": 0.8}, "relevance_score": 0.5, "timestamp": "2024-01-01T00:00:00Z"},
            semantic=0.7, bm25=0.5,
        )
        assert 0 <= score <= 1

    def test_source_reliability_constants(self):
        """source_reliability 常量正确。"""
        assert SourceReliability.USER_EXPLICIT == 1.0
        assert SourceReliability.CHANNEL_A_RULE == 1.0
        assert SourceReliability.DEFAULT == 0.5

    def test_source_weight_constants(self):
        """source_weight 常量正确。"""
        assert SourceWeight.LONG_TERM == 1.0
        assert SourceWeight.EXPERIENCE == 0.8
        assert SourceWeight.KNOWLEDGE == 0.6
        assert SourceWeight.JOURNAL == 0.4
        assert SourceWeight.SESSION == 0.3

    def test_time_decay_recent(self):
        """最近时间戳衰减值高。"""
        engine = ScoringEngine()
        now = datetime.now(timezone.utc).isoformat()
        score = engine.score(
            {"metadata": {}, "relevance_score": 0.5, "timestamp": now},
            source_reliability=0.8,
        )
        assert score > 0.25  # 最近的时间衰减应较高

    def test_time_decay_old(self):
        """旧时间戳衰减值低。"""
        engine = ScoringEngine()
        score = engine.score(
            {"metadata": {}, "relevance_score": 0.5, "timestamp": "2020-01-01T00:00:00Z"},
            source_reliability=0.8,
        )
        assert score < 0.3  # 很旧的时间衰减应较低

    def test_apply_source_weight(self):
        """跨源权重乘法。"""
        result = ScoringEngine.apply_source_weight(0.8, 0.5)
        assert result == pytest.approx(0.4)


# ═══════════════════════════════════════════════════════════
# SourceAdapter 测试
# ═══════════════════════════════════════════════════════════

class TestSourceAdapters:
    @pytest.mark.asyncio
    async def test_ltm_adapter(self):
        """LTMAdapter 正常检索。"""
        adapter = LTMAdapter(FakeLTM())
        items = await adapter.search("Python", top_k=5)
        assert len(items) >= 1
        assert items[0].source == "long_term"
        assert isinstance(items[0].content, str)

    @pytest.mark.asyncio
    async def test_ltm_adapter_source_weight(self):
        """LTMAdapter 权重最高。"""
        adapter = LTMAdapter(FakeLTM())
        assert adapter.source_weight == 1.0

    @pytest.mark.asyncio
    async def test_experience_adapter(self):
        """ExperienceAdapter 正常检索。"""
        adapter = ExperienceAdapter(FakeExpMemory())
        items = await adapter.search("deploy", top_k=5)
        assert len(items) >= 1
        assert items[0].source == "experience"

    @pytest.mark.asyncio
    async def test_knowledge_adapter(self):
        """KnowledgeAdapter 返回节点和边。"""
        adapter = KnowledgeAdapter(FakeSemanticMemory())
        items = await adapter.search("Python", top_k=5)
        assert len(items) >= 2  # nodes + edges
        assert all(i.source == "knowledge" for i in items)

    @pytest.mark.asyncio
    async def test_session_adapter(self):
        """SessionAdapter 正常检索。"""
        adapter = SessionAdapter(FakeSessionMemory())
        items = await adapter.search("K8s", top_k=5)
        assert len(items) >= 1
        assert items[0].source == "session"

    @pytest.mark.asyncio
    async def test_journal_adapter(self):
        """JournalAdapter 正常检索。"""
        adapter = JournalAdapter(FakeJournalStore())
        items = await adapter.search("deploy", top_k=5)
        assert len(items) >= 1
        assert items[0].source == "journal"


# ═══════════════════════════════════════════════════════════
# UnifiedRetriever 测试
# ═══════════════════════════════════════════════════════════

class TestUnifiedRetriever:
    @pytest.fixture
    def retriever(self):
        return UnifiedRetriever(
            adapters={
                "long_term": LTMAdapter(FakeLTM()),
                "experience": ExperienceAdapter(FakeExpMemory()),
                "knowledge": KnowledgeAdapter(FakeSemanticMemory()),
                "session": SessionAdapter(FakeSessionMemory()),
                "journal": JournalAdapter(FakeJournalStore()),
            },
            scoring=ScoringEngine(),
            default_top_k=10,
        )

    @pytest.mark.asyncio
    async def test_retrieve_all_sources(self, retriever):
        """全部源检索正常返回。"""
        items = await retriever.retrieve("Python K8s", top_k=15)
        assert len(items) > 0
        for item in items:
            assert isinstance(item, RetrievedItem)
            assert item.content
            assert item.source
            assert 0 <= item.score <= 1

    @pytest.mark.asyncio
    async def test_retrieve_specific_sources(self, retriever):
        """按指定源检索。"""
        items = await retriever.retrieve(
            "Python", top_k=5, sources=["long_term", "knowledge"],
        )
        sources = {i.source for i in items}
        assert sources <= {"long_term", "knowledge"}

    @pytest.mark.asyncio
    async def test_retrieve_top_k_enforced(self, retriever):
        """top_k 限制生效。"""
        items = await retriever.retrieve("test", top_k=3)
        assert len(items) <= 3

    @pytest.mark.asyncio
    async def test_retrieve_sorted_by_score(self, retriever):
        """结果按分数降序排列。"""
        items = await retriever.retrieve("Python", top_k=10)
        for i in range(len(items) - 1):
            assert items[i].score >= items[i + 1].score

    def test_deduplicate_content(self, retriever):
        """内容精确去重。"""
        items = [
            RetrievedItem(content="相同内容", source="long_term", score=0.8, metadata={"id": "1"}),
            RetrievedItem(content="相同内容", source="session", score=0.3, metadata={"id": "2"}),
        ]
        deduped = retriever._deduplicate(items)
        assert len(deduped) == 1
        assert deduped[0].score == 0.8  # 保留高分的

    def test_deduplicate_entity_key(self, retriever):
        """同 entity_key 去重。"""
        items = [
            RetrievedItem(content="内容A", source="long_term", score=0.8, metadata={"entity_key": "user.name", "id": "1"}),
            RetrievedItem(content="内容B", source="session", score=0.3, metadata={"entity_key": "user.name", "id": "2"}),
        ]
        deduped = retriever._deduplicate(items)
        # entity_key 去重保留高分
        scores = [i.score for i in deduped]
        assert 0.8 in scores

    def test_deduplicate_semantic(self, retriever):
        """语义去重（有 embedding 时）。"""
        items = [
            RetrievedItem(content="内容A", source="long_term", score=0.9, metadata={"id": "1"}, embedding=[0.1, 0.2, 0.3]),
            RetrievedItem(content="内容B", source="session", score=0.4, metadata={"id": "2"}, embedding=[0.1, 0.2, 0.3]),
        ]
        deduped = retriever._deduplicate(items)
        # 相同 embedding → semantic dedup → 保留高分
        assert len(deduped) == 1
        assert deduped[0].score == 0.9

    def test_cosine_similarity(self):
        """余弦相似度计算正确。"""
        sim = UnifiedRetriever._cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert sim == pytest.approx(1.0)

        sim2 = UnifiedRetriever._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim2 == pytest.approx(0.0)

    def test_cosine_similarity_mismatched(self):
        """不同长度返回 0。"""
        sim = UnifiedRetriever._cosine_similarity([1.0], [1.0, 0.0])
        assert sim == 0.0
