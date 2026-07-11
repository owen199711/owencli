"""Pipeline 集成测试（Phase 8）。

验证 ContextOSPipeline 各组件正确组装:
    - EventBus / Journal / Retriever / KnowledgeUpdater / MaintenanceWorker
    - 向后兼容属性
    - async context manager
"""

import pytest
import pytest_asyncio
import asyncio

from context_os.core.models import LLMProvider
from context_os.entry import ContextOSPipeline


class MockLLM:
    """Mock LLM 客户端。"""
    def __init__(self, response="mock response"):
        self.response = response

    async def complete(self, prompt, **kwargs):
        return self.response


@pytest.fixture
def mock_llm():
    return MockLLM()


def _create_pipeline(mock_llm, tmp_path, **kwargs):
    """同步创建 pipeline 的辅助函数。"""
    db_path = str(tmp_path / "test_pipeline.db")
    return ContextOSPipeline(
        llm_client=mock_llm,
        provider=LLMProvider.OPENAI,
        db_path=db_path,
        user_id="test_user",
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════
# 组件组装 (async fixture)
# ═══════════════════════════════════════════════════════════

class TestPipelineAssembly:
    """验证 Pipeline 各组件正确组装。"""

    @pytest.mark.asyncio
    async def test_store_created(self, mock_llm, tmp_path):
        """存储层已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.store is not None

    @pytest.mark.asyncio
    async def test_event_bus_created(self, mock_llm, tmp_path):
        """EventBus 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.event_bus is not None

    @pytest.mark.asyncio
    async def test_journal_created(self, mock_llm, tmp_path):
        """JournalStore 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.journal is not None

    @pytest.mark.asyncio
    async def test_retriever_created(self, mock_llm, tmp_path):
        """UnifiedRetriever 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.retriever is not None

    @pytest.mark.asyncio
    async def test_retriever_has_adapters(self, mock_llm, tmp_path):
        """Retriever 有 5 个 adapter。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert len(p.retriever._adapters) == 5
        assert "long_term" in p.retriever._adapters
        assert "experience" in p.retriever._adapters
        assert "knowledge" in p.retriever._adapters
        assert "session" in p.retriever._adapters
        assert "journal" in p.retriever._adapters

    @pytest.mark.asyncio
    async def test_knowledge_updater_created(self, mock_llm, tmp_path):
        """KnowledgeUpdater 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.knowledge_updater is not None

    @pytest.mark.asyncio
    async def test_concept_worker_created(self, mock_llm, tmp_path):
        """BackgroundConceptWorker 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.concept_worker is not None

    @pytest.mark.asyncio
    async def test_maintenance_worker_created(self, mock_llm, tmp_path):
        """MaintenanceWorker 已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.maintenance is not None

    @pytest.mark.asyncio
    async def test_builder_created_with_retriever(self, mock_llm, tmp_path):
        """ContextBuilder 已注入 retriever。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.builder.retriever is not None

    @pytest.mark.asyncio
    async def test_all_memory_types_created(self, mock_llm, tmp_path):
        """所有 5 种记忆类型已创建。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.working_memory is not None
        assert p.short_term_memory is not None
        assert p.long_term_memory is not None
        assert p.semantic_memory is not None
        assert p.experience_memory is not None


# ═══════════════════════════════════════════════════════════
# 向后兼容属性
# ═══════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """向后兼容属性测试。"""

    @pytest.mark.asyncio
    async def test_session_memory_alias(self, mock_llm, tmp_path):
        """session_memory 属性返回 short_term_memory。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.session_memory is p.short_term_memory

    @pytest.mark.asyncio
    async def test_episodic_memory_alias(self, mock_llm, tmp_path):
        """episodic_memory 属性返回 experience_memory（带 DeprecationWarning）。"""
        import warnings
        p = _create_pipeline(mock_llm, tmp_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            mem = p.episodic_memory
            assert mem is p.experience_memory
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)


# ═══════════════════════════════════════════════════════════
# Async Context Manager
# ═══════════════════════════════════════════════════════════

class TestAsyncContextManager:
    """async with 支持测试。"""

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_llm, tmp_path):
        """async with 正常执行和关闭。"""
        db_path = str(tmp_path / "test_cm.db")
        async with ContextOSPipeline(
            llm_client=mock_llm,
            provider=LLMProvider.OPENAI,
            db_path=db_path,
            user_id="test_user",
        ) as p:
            assert p is not None
            assert p.store is not None
        # 退出后 maintenance stopped
        assert p.maintenance._running is False


# ═══════════════════════════════════════════════════════════
# Session ID
# ═══════════════════════════════════════════════════════════

class TestSessionId:
    """Session ID 生成。"""

    @pytest.mark.asyncio
    async def test_auto_generated_session_id(self, mock_llm, tmp_path):
        """自动生成 session_id。"""
        p = _create_pipeline(mock_llm, tmp_path)
        assert p.session_id is not None
        assert len(p.session_id) == 12

    @pytest.mark.asyncio
    async def test_custom_session_id(self, mock_llm, tmp_path):
        """自定义 session_id。"""
        p = _create_pipeline(mock_llm, tmp_path, session_id="my-custom-session")
        assert p.session_id == "my-custom-session"


# ═══════════════════════════════════════════════════════════
# run() 端到端（跳过 LLM 调用）
# ═══════════════════════════════════════════════════════════

class TestPipelineRun:
    """Pipeline.run() 端到端测试。"""

    @pytest.mark.asyncio
    async def test_run_returns_dict(self, mock_llm, tmp_path):
        """run() 返回 dict 结构。"""
        p = _create_pipeline(mock_llm, tmp_path)
        result = await p.run("Hello, how are you?")
        assert isinstance(result, dict)
        assert "response" in result
        assert "metrics" in result
        assert "trace_id" in result
        assert "task_spec" in result
        assert "latency_ms" in result
        assert result["response"] == "mock response"

    @pytest.mark.asyncio
    async def test_run_records_conversation(self, mock_llm, tmp_path):
        """run() 记录对话轮次。"""
        p = _create_pipeline(mock_llm, tmp_path)
        await p.run("question 1?")
        turns = p.conversation.history
        assert len(turns) >= 2  # user + assistant

    @pytest.mark.asyncio
    async def test_close_cleanup(self, mock_llm, tmp_path):
        """close() 正常清理。"""
        p = _create_pipeline(mock_llm, tmp_path)
        await p.run("test")
        await p.close()
        assert p.maintenance._running is False
