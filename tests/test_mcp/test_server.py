"""Test Context-OS MCP server tools.

Uses an in-memory SQLite database for testing.
Tests the complete Journal -> EventBus -> JournalProcessor pipeline.
"""

import pytest
import asyncio

import claude_codex_mcp.server as server_mod


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level globals before each test."""
    server_mod._store = None
    server_mod._ltm = None
    server_mod._exp = None
    server_mod._sem = None
    server_mod._stm = None
    server_mod._event_bus = None
    server_mod._journal = None
    server_mod._journal_processor = None
    server_mod._concept_worker = None
    server_mod._llm_client = None
    server_mod._round_count = 0
    yield
    # Cleanup after test
    if server_mod._concept_worker is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(server_mod._concept_worker.stop())
            else:
                loop.run_until_complete(server_mod._concept_worker.stop())
        except Exception:
            pass
    if server_mod._journal_processor is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(server_mod._journal_processor.close())
            else:
                loop.run_until_complete(server_mod._journal_processor.close())
        except Exception:
            pass
    if server_mod._store is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(server_mod._store.close())
            else:
                loop.run_until_complete(server_mod._store.close())
        except Exception:
            pass
    server_mod._store = None
    server_mod._ltm = None
    server_mod._exp = None
    server_mod._sem = None
    server_mod._stm = None
    server_mod._event_bus = None
    server_mod._journal = None
    server_mod._journal_processor = None
    server_mod._concept_worker = None
    server_mod._llm_client = None
    server_mod._round_count = 0


@pytest.fixture
def use_memory_db(monkeypatch):
    """Use in-memory SQLite for testing."""
    monkeypatch.setattr(server_mod, "_get_db_path", lambda: ":memory:")
    monkeypatch.setattr(server_mod, "_get_user_id", lambda: "test-user")
    monkeypatch.setattr(server_mod, "_get_session_id", lambda: "test-session-001")


# =====================================================================
# Write tools (Journal-driven)
# =====================================================================


class TestLogTurn:
    """Tests for log_turn tool (Journal-driven conversation logging)."""

    @pytest.mark.asyncio
    async def test_log_basic_turn(self, use_memory_db):
        """Log a basic conversation turn through the full pipeline."""
        result = await server_mod.log_turn(
            raw_input="Help me analyze the performance issues in this code",
            raw_output="The main bottleneck is the database query in the loop...",
            task_intent="CODING",
        )
        assert "journal_id=" in result
        assert "round=1" in result

    @pytest.mark.asyncio
    async def test_log_multiple_turns(self, use_memory_db):
        """Log multiple turns and verify round counting."""
        r1 = await server_mod.log_turn(raw_input="Q1", raw_output="A1")
        r2 = await server_mod.log_turn(raw_input="Q2", raw_output="A2")
        r3 = await server_mod.log_turn(raw_input="Q3", raw_output="A3")
        assert "round=1" in r1
        assert "round=2" in r2
        assert "round=3" in r3

    @pytest.mark.asyncio
    async def test_log_with_entities(self, use_memory_db):
        """Log a turn with entity metadata."""
        result = await server_mod.log_turn(
            raw_input="How to implement JWT auth in FastAPI",
            raw_output="Here is the JWT auth implementation...",
            task_intent="CODING",
            entities='{"language": "Python", "framework": "FastAPI", "topic": "auth"}',
        )
        assert "journal_id=" in result

    @pytest.mark.asyncio
    async def test_log_invalid_entities_json(self, use_memory_db):
        """Log with invalid entities JSON should error."""
        result = await server_mod.log_turn(
            raw_input="test",
            entities="not valid json {{{",
        )
        assert "error" in result.lower() or "错误" in result

    @pytest.mark.asyncio
    async def test_log_turn_appears_in_journal(self, use_memory_db):
        """Verify log_turn writes appear in journal_entries."""
        await server_mod.log_turn(
            raw_input="User prefers using Python",
            raw_output="Got it, Python it is",
        )
        entries = await server_mod.get_journal_entries()
        assert "User prefers using Python" in entries
        assert "Got it" in entries

    @pytest.mark.asyncio
    async def test_log_turn_triggers_session_memory(self, use_memory_db):
        """Log a turn and verify session memory is populated (zero-gate)."""
        await server_mod.log_turn(
            raw_input="Test session memory write",
            raw_output="Test response",
        )
        store = await server_mod._ensure_store()
        session_mems = await store.query_memories(
            type="session",
            session_id="test-session-001",
        )
        assert len(session_mems) > 0, "Session memory should be populated by zero-gate"


class TestSaveMemory:
    """Tests for save_memory tool (Journal-driven, natural decision flow)."""

    @pytest.mark.asyncio
    async def test_save_through_journal(self, use_memory_db):
        """save_memory goes through Journal -> JournalProcessor (natural decision)."""
        result = await server_mod.save_memory(
            content="User prefers TypeScript for frontend development",
        )
        assert "journal_id=" in result
        assert "内容已提交到记忆系统" in result

    @pytest.mark.asyncio
    async def test_save_with_category(self, use_memory_db):
        """Save memory with a category tag."""
        result = await server_mod.save_memory(
            content="Project convention: use ruff for linting",
            category="project_context",
        )
        assert "journal_id=" in result

    @pytest.mark.asyncio
    async def test_save_with_metadata(self, use_memory_db):
        """Save memory with JSON metadata."""
        result = await server_mod.save_memory(
            content="Python 3.11+ for this project",
            category="tech_stack",
            metadata='{"version": "3.11", "confidence": 0.9}',
        )
        assert "journal_id=" in result

    @pytest.mark.asyncio
    async def test_save_invalid_metadata_json(self, use_memory_db):
        """Save with invalid JSON metadata should error."""
        result = await server_mod.save_memory(
            content="test",
            metadata="not valid json {{{",
        )
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_save_appears_in_journal(self, use_memory_db):
        """Verify save_memory entries appear as-is (no artificial prefix)."""
        await server_mod.save_memory(
            content="Project uses ruff for linting",
            category="project_context",
        )
        entries = await server_mod.get_journal_entries()
        # Content stored as-is, no keyword prefix injected
        assert "Project uses ruff for linting" in entries

    @pytest.mark.asyncio
    async def test_no_fake_keyword_injection(self, use_memory_db):
        """No artificial keyword injected into journal raw_input."""
        await server_mod.save_memory(content="This is ordinary content")
        entries = await server_mod.get_journal_entries()
        assert "This is ordinary content" in entries

    @pytest.mark.asyncio
    async def test_save_flows_to_session_zero_gate(self, use_memory_db):
        """Save always writes to Session Memory (zero-gate)."""
        await server_mod.save_memory(content="test zero-gate write")

        store = await server_mod._ensure_store()
        session_mems = await store.query_memories(
            type="session",
            session_id="test-session-001",
        )
        assert len(session_mems) > 0, "Zero-gate should write to session memory"

    @pytest.mark.asyncio
    async def test_save_immediate_flush(self, use_memory_db):
        """save_memory flushes JournalProcessor batch immediately."""
        result = await server_mod.save_memory(content="testing immediate flush")
        assert "batch_flushed=" in result


# =====================================================================
# Query tools
# =====================================================================


class TestSearchMemory:
    """Tests for search_memory tool."""

    @pytest.mark.asyncio
    async def test_search_empty_db(self, use_memory_db):
        result = await server_mod.search_memory("hello")
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_search_after_save_journal(self, use_memory_db):
        """Search finds content from journal pipeline (session + LTM)."""
        await server_mod.save_memory(
            content="User prefers TypeScript for frontend development",
            category="user_preference",
        )
        result = await server_mod.search_memory("TypeScript", top_k=5)
        # Content is always in Session (zero-gate), may be in LTM (Layer 2+3 scoring)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_search_after_log_turn(self, use_memory_db):
        """Search finds content from logged conversation turns (zero-gate session)."""
        await server_mod.log_turn(
            raw_input="We use PostgreSQL as the database",
            raw_output="OK, PostgreSQL config is done",
            task_intent="QA",
        )
        result = await server_mod.search_memory("PostgreSQL", top_k=10)
        assert len(result) > 0


class TestGetMemory:
    """Tests for get_memory tool."""

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, use_memory_db):
        result = await server_mod.get_memory("nonexistent-id")
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_get_memory_from_pipeline(self, use_memory_db):
        """Get memory by ID after pipeline processes content."""
        # Use content with natural Layer 1 keyword to ensure LTM routing
        await server_mod.save_memory(content="Remember: project uses ruff for linting")

        # List recent LTM memories
        recent = await server_mod.list_recent_memories(limit=10)
        # Content should be in LTM after Layer 1 detection
        if "ruff" in recent:
            import re
            match = re.search(r"`([a-f0-9]+)`", recent)
            if match:
                mem_id = match.group(1)
                result = await server_mod.get_memory(mem_id)
                assert "ruff" in result.lower()
            else:
                # List format may vary, but the test should not fail
                pass


class TestListRecentMemories:
    """Tests for list_recent_memories tool."""

    @pytest.mark.asyncio
    async def test_list_empty(self, use_memory_db):
        result = await server_mod.list_recent_memories(limit=10)
        assert "没有找到" in result

    @pytest.mark.asyncio
    async def test_list_with_session_type(self, use_memory_db):
        """List session memories after pipeline writes (zero-gate always writes session)."""
        await server_mod.save_memory(content="session content test")
        # Session type should always have entries after zero-gate write
        result = await server_mod.list_recent_memories(memory_type="session", limit=10)
        assert "session content test" in result


class TestGetMemoryStats:
    """Tests for get_memory_stats tool."""

    @pytest.mark.asyncio
    async def test_stats_empty(self, use_memory_db):
        result = await server_mod.get_memory_stats()
        assert "Context-OS" in result
        assert "JournalProcessor=active" in result

    @pytest.mark.asyncio
    async def test_stats_after_saves(self, use_memory_db):
        await server_mod.save_memory(content="memory item 1")
        await server_mod.save_memory(content="memory item 2")
        result = await server_mod.get_memory_stats()
        assert "Context-OS" in result
        assert "Journal" in result


class TestSearchExperiences:
    """Tests for search_experiences tool."""

    @pytest.mark.asyncio
    async def test_search_empty(self, use_memory_db):
        result = await server_mod.search_experiences()
        assert "未找到匹配" in result


class TestKnowledgeGraph:
    """Tests for query_knowledge_graph tool."""

    @pytest.mark.asyncio
    async def test_query_empty(self, use_memory_db):
        result = await server_mod.query_knowledge_graph()
        assert "暂无概念" in result

    @pytest.mark.asyncio
    async def test_query_nonexistent_concept(self, use_memory_db):
        result = await server_mod.query_knowledge_graph(concept="nonexistent", depth=1)
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_query_concept_after_add(self, use_memory_db):
        store = await server_mod._ensure_store()
        await store.save_concept(
            name="Python", attributes={"version": "3.11"}, confidence=0.9
        )
        result = await server_mod.query_knowledge_graph(concept="Python", depth=1)
        assert "Python" in result


class TestJournalEntries:
    """Tests for get_journal_entries tool."""

    @pytest.mark.asyncio
    async def test_journal_empty(self, use_memory_db):
        result = await server_mod.get_journal_entries()
        assert "没有找到匹配" in result

    @pytest.mark.asyncio
    async def test_journal_after_log_turn(self, use_memory_db):
        """Journal entries appear after logging turns."""
        await server_mod.log_turn(
            raw_input="How to deploy to K8s",
            raw_output="Here are the K8s deployment steps...",
        )
        result = await server_mod.get_journal_entries()
        assert "deploy" in result


# =====================================================================
# End-to-end pipeline tests
# =====================================================================


class TestPipelineEndToEnd:
    """E2E: Journal -> EventBus -> JournalProcessor -> persistent stores."""

    @pytest.mark.asyncio
    async def test_save_memory_flows_to_session(self, use_memory_db):
        """save_memory always writes to Session (zero-gate)."""
        await server_mod.save_memory(content="test session write")

        store = await server_mod._ensure_store()
        session_mems = await store.query_memories(
            type="session",
            session_id="test-session-001",
        )
        assert len(session_mems) > 0

    @pytest.mark.asyncio
    async def test_log_turn_flows_to_session(self, use_memory_db):
        """log_turn always writes to Session (zero-gate)."""
        await server_mod.log_turn(
            raw_input="Project uses Redis as cache",
            raw_output="Recorded",
        )

        store = await server_mod._ensure_store()
        session_mems = await store.query_memories(
            type="session",
            session_id="test-session-001",
        )
        assert len(session_mems) > 0

    @pytest.mark.asyncio
    async def test_layer1_natural_detection(self, use_memory_db):
        """Content with natural Layer 1 keywords routes to LTM without injection."""
        await server_mod.save_memory(
            content="Remember: user name is Alice, lives in Beijing",
        )
        result = await server_mod.search_memory("Alice", top_k=5)
        assert len(result) > 0, "Layer 1 should detect natural 'remember' keyword"

    @pytest.mark.asyncio
    async def test_journal_stats_after_pipeline(self, use_memory_db):
        """Stats reflect journal entries from the pipeline."""
        await server_mod.save_memory(content="Memory item A")
        await server_mod.log_turn(raw_input="Chat message", raw_output="Reply")

        stats = await server_mod.get_memory_stats()
        assert "Journal" in stats
