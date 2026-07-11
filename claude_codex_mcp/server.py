"""Context-OS MCP Server.

Exposes the **complete** Context-OS memory pipeline as MCP tools for AI assistants
(Claude Code, Trae IDE, etc.) to read/write/search across:

  - Journal (write-ahead log, entry point for the full pipeline)
  - Long-Term Memory (persistent cross-session facts, summaries, preferences)
  - Experience Memory (episodes, reflections, procedures, tool usage)
  - Semantic Memory (knowledge graph: concepts and relations)
  - Session Memory (conversation session context)

Pipeline flow for writes:
    save_memory / log_turn → journal.append()
        → SQLite journal table (WAL)
        → EventBus.publish(JournalCreatedEvent)
            → JournalProcessor (Layer 1/2/3 write decision + MemoryRouter)
                → Session / LongTerm / Experience / Knowledge

Transport: stdio (default for Claude Code and Trae IDE integration).

Environment variables:
    DATABASE_URL / CONTEXT_OS_DB_PATH: SQLite database path (default ./data/context_os.db)
    CONTEXT_OS_USER_ID: user identifier (default "claude-codex")
    CONTEXT_OS_SESSION_ID: session identifier (auto-generated if not set)
    DEEPSEEK_API_KEY: DeepSeek API key for BackgroundConceptWorker (optional)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.memory.long_term import LongTermMemory
from context_os.memory.experience import ExperienceMemory
from context_os.memory.semantic import SemanticMemory
from context_os.memory.session_memory import SessionMemory
from context_os.memory.journal import JournalStore

# Event system
from context_os.events.bus import EventBus

# Feedback pipeline (complete write decision + routing chain)
from context_os.feedback.journal_processor import JournalProcessor
from context_os.feedback.concept_worker import BackgroundConceptWorker

# Unified Retriever (5-source concurrent search + unified scoring)
from context_os.retriever.retriever import UnifiedRetriever
from context_os.retriever.adapter import LTMAdapter, ExperienceAdapter, KnowledgeAdapter, SessionAdapter, JournalAdapter

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context as MCPContext


logger = get_logger(__name__)

# ── Global state (lazy-init) ──────────────────────────────────────────

_store: Optional[SQLiteStore] = None
_ltm: Optional[LongTermMemory] = None
_exp: Optional[ExperienceMemory] = None
_sem: Optional[SemanticMemory] = None
_stm: Optional[SessionMemory] = None  # Session memory for pending candidate buffer
_event_bus: Optional[EventBus] = None
_journal: Optional[JournalStore] = None
_journal_processor: Optional[JournalProcessor] = None
_concept_worker: Optional[BackgroundConceptWorker] = None
_llm_client: Optional[Any] = None
_retriever: Optional[UnifiedRetriever] = None
_round_count: int = 0
_lock = asyncio.Lock()


def _get_db_path() -> str:
    """Resolve the database path from environment variables."""
    return (
        os.environ.get("CONTEXT_OS_DB_PATH")
        or os.environ.get("DATABASE_URL")
        or "./data/context_os.db"
    )


def _get_user_id() -> str:
    """Resolve the user ID from environment variables."""
    return os.environ.get("CONTEXT_OS_USER_ID", "claude-codex")


def _get_session_id() -> str:
    """Resolve or generate a session ID."""
    return os.environ.get("CONTEXT_OS_SESSION_ID") or uuid.uuid4().hex[:12]


def _get_api_key() -> Optional[str]:
    """Get LLM API key for BackgroundConceptWorker (optional)."""
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")


async def _ensure_store() -> SQLiteStore:
    """Lazily initialize the complete memory pipeline.

    Sets up:
      1. SQLiteStore (connection + schema)
      2. Memory managers (LongTerm, Experience, Semantic, Session)
      3. EventBus (pub/sub for journal:created → JournalProcessor)
      4. JournalStore (WAL wrapper)
      5. JournalProcessor (subscribes to journal:created, drives 3-layer write decision)
      6. BackgroundConceptWorker (optional, requires DEEPSEEK_API_KEY)
    """
    global _store, _ltm, _exp, _sem, _stm
    global _event_bus, _journal, _journal_processor, _concept_worker, _llm_client, _retriever

    async with _lock:
        if _store is None:
            db_path = _get_db_path()
            logger.info("Initializing MCP store at %s", db_path)

            # ── Layer 1: Store ──
            _store = SQLiteStore(db_path=db_path)
            await _store.connect()

            user_id = _get_user_id()
            session_id = _get_session_id()

            # ── Layer 2: Memory managers ──
            _ltm = LongTermMemory(store=_store, user_id=user_id)
            _exp = ExperienceMemory(store=_store, user_id=user_id)
            _sem = SemanticMemory(store=_store, user_id=user_id)
            _stm = SessionMemory(session_id=session_id, store=_store)

            # ── Layer 3: EventBus ──
            _event_bus = EventBus()

            # ── Layer 4: Journal (WAL wrapper) ──
            _journal = JournalStore(store=_store, event_bus=_event_bus)

            # ── Layer 5: Optional LLM client ──
            api_key = _get_api_key()
            if api_key:
                try:
                    from context_os.llm.deepseek_client import DeepSeekClient

                    _llm_client = DeepSeekClient(api_key=api_key)
                    logger.info("LLM client initialized for BackgroundConceptWorker")
                except Exception as e:
                    logger.warning("Failed to init LLM client: %s", e)

            # ── Layer 6: JournalProcessor (core write pipeline) ──
            # Subscribes to journal:created on __init__.
            # When journal.append() publishes JournalCreatedEvent,
            # JournalProcessor._on_journal_created() runs:
            #   1. Zero-gate → Session Memory
            #   2. Layer 1 rule check → immediate route+dispatch
            #   3. Layer 1 miss → candidate buffer → batch Layer 2+3
            _journal_processor = JournalProcessor(
                event_bus=_event_bus,
                long_term_memory=_ltm,
                semantic_memory=_sem,
                experience_memory=_exp,
                session_memory=_stm,
                # knowledge_queue and concept_worker are optional for sync path
            )

            # ── Layer 7: Background Concept Worker (async knowledge extraction) ──
            if _llm_client:
                try:
                    _concept_worker = BackgroundConceptWorker(
                        ltm=_ltm,
                        knowledge=_sem,
                        llm_client=_llm_client,
                    )
                    _concept_worker.start()
                    logger.info("BackgroundConceptWorker started")
                except Exception as e:
                    logger.warning("Failed to start BackgroundConceptWorker: %s", e)
                    _concept_worker = None

            # ── Layer 8: UnifiedRetriever (5-source concurrent search + unified scoring) ──
            _retriever = UnifiedRetriever(
                adapters={
                    "long_term": LTMAdapter(_ltm),
                    "experience": ExperienceAdapter(_exp),
                    "knowledge": KnowledgeAdapter(_sem),
                    "session": SessionAdapter(_stm),
                    "journal": JournalAdapter(_journal),
                },
            )
            logger.info("UnifiedRetriever initialized with 5 sources")

            logger.info(
                "MCP memory pipeline ready: user=%s, session=%s, "
                "concept_worker=%s, journal_processor=active",
                user_id,
                session_id,
                bool(_concept_worker),
            )

    return _store


# ── FastMCP server ────────────────────────────────────────────────────

mcp = FastMCP(
    name="context-os",
    instructions=(
        "Context-OS 是一个 AI Agent 长期记忆系统，通过完整的 Journal -> WriteDecision -> MemoryRouter 链路管理记忆。\n\n"
        "## 写入流程（完整链路）\n"
        "- **log_turn**: 记录一轮对话（raw_input + raw_output）-> Journal WAL -> JournalProcessor -> 分层写入\n"
        "- **save_memory**: 保存记忆 -> Journal -> 自动路由到 LongTerm/Experience/Knowledge\n\n"
        "## 可用工具\n"
        "- **log_turn**: 记录对话turn，触发完整的记忆处理流程\n"
        "- **save_memory**: 保存长期记忆（走 Journal 写入链路）\n"
        "- **search_memory**: 在长期记忆、知识图谱、体验记录中综合搜索\n"
        "- **get_memory**: 按 ID 获取特定记忆\n"
        "- **list_recent_memories**: 查看最近的记忆\n"
        "- **search_experiences**: 搜索体验记录（经历、反思、流程、工具使用）\n"
        "- **query_knowledge_graph**: 查询知识图谱（概念和关系）\n"
        "- **get_memory_stats**: 获取记忆系统统计信息\n"
        "- **get_journal_entries**: 查询对话日志\n\n"
        "## 记忆类型\n"
        "- `long_term`: 跨会话持久记忆（偏好、项目上下文、决策、摘要）\n"
        "- `session`: 当前会话的短期记忆\n"
        "- `semantic`: 知识图谱（概念节点和关系）\n"
        "- `experience`: 体验记录（episode/reflection/procedure/tool_usage）\n"
        "- `journal`: 写前日志（每轮对话的原始输入输出）\n\n"
        "## 写入决策（3层闸门）\n"
        "- Layer 1: 规则必存（记住关键字、我叫X等显式记忆信号）\n"
        "- Layer 2: 新颖度过滤（embedding相似度比较）\n"
        "- Layer 3: 重要性评分（identity/state/task/cold_start/quality 五维）\n\n"
        "## 使用场景\n"
        "- 每轮对话结束后调用 log_turn(raw_input, raw_output) 记录\n"
        "- 用户说记住某事时，调用 save_memory 保存（自动走完整链路）\n"
        "- 用户问之前说过某事时，调用 search_memory 搜索\n"
        "- 任务完成后调用 search_experiences 找类似历史的解决方案\n"
        "- 需要了解项目知识结构时调用 query_knowledge_graph"
    ),
)


# ═══════════════════════════════════════════════════════════════════
# 写入工具（Journal 驱动）
# ═══════════════════════════════════════════════════════════════════


@mcp.tool(
    name="log_turn",
    description=(
        "记录一轮对话到 Context-OS 的 Journal（写前日志），触发完整的记忆处理链路。\n\n"
        "每次对话结束后调用此工具，将用户输入和 AI 回复一起记录。\n"
        "系统会自动通过 3 层写入决策 (Layer 1 规则 -> Layer 2 新颖度 -> Layer 3 重要性)\n"
        "决定是否持久化到长期记忆、体验记录或知识图谱。\n\n"
        "这是 Context-OS 记忆系统的核心入口 -- 所有持久化写入都通过 Journal WAL + EventBus 驱动。"
    ),
)
async def log_turn(
    raw_input: str,
    raw_output: str = "",
    task_intent: str = "QA",
    entities: Optional[str] = None,
) -> str:
    """记录一轮对话到 Journal WAL，触发完整记忆处理。

    Args:
        raw_input: 用户原始输入（本轮对话的用户消息）。
        raw_output: AI 助手的回复（本轮对话的 assistant 回复）。
        task_intent: 任务意图类型。可选: QA, CODING, DEBUGGING, PLANNING, SEARCH, WORKFLOW, AGENT, DATA_ANALYSIS。
                     默认 QA。
        entities: 可选，JSON 格式的实体字典，如 '{"language": "Python", "framework": "FastAPI"}'。

    Returns:
        操作结果，包含 journal_id 和 round 编号。
    """
    await _ensure_store()
    assert _journal is not None

    global _round_count
    _round_count += 1

    entities_dict: dict[str, Any] = {}
    if entities:
        try:
            entities_dict = json.loads(entities)
        except json.JSONDecodeError:
            return f"错误: entities 不是合法的 JSON: {entities}"

    journal_id = await _journal.append(
        user_id=_get_user_id(),
        session_id=_get_session_id(),
        round_id=_round_count,
        raw_input=raw_input,
        raw_output=raw_output,
        entities=entities_dict,
        task_intent=task_intent,
    )

    return (
        f"回合已记录. journal_id={journal_id}, round={_round_count}. "
        "完整记忆处理链路已触发: Journal → EventBus → JournalProcessor "
        "(Layer 1 规则检查 → 立即路由写入, Layer 2+3 批量处理将随后执行)。"
    )


@mcp.tool(
    name="save_memory",
    description=(
        "保存内容到 Context-OS 记忆系统，由系统自动判断是否真正需要持久化以及存储到哪里。\n\n"
        "调用此工具无需担心内容是否重要或包含关键词 -- 所有内容都统一经过完整的\n"
        "3 层写入决策 (Layer 1 规则 -> Layer 2 新颖度 -> Layer 3 重要性)，\n"
        "由系统自动路由到合适的存储目标 (LongTerm / Experience / Session / Knowledge)。\n\n"
        "处理流程:\n"
        "  1. 写入 Journal (写前日志) -- 零门槛，所有内容先记录\n"
        "  2. Session Memory -- 零门槛，当前会话上下文总是写入\n"
        "  3. Layer 1 规则检查 -- 自然关键字匹配（如用户说'我叫X'）\n"
        "  4. Layer 2+3 深度决策 -- 新颖度过滤 + 五维重要性评分\n"
        "  5. MemoryRouter -- 自动路由到 LongTerm / Experience / Knowledge\n\n"
        "适用场景：任何需要记录的信息 -- 用户偏好、项目约定、决策结论、\n"
        "代码片段、配置信息、任务摘要等。不用判断是否值得记，由系统决定。"
    ),
)
async def save_memory(
    content: str,
    category: Optional[str] = None,
    metadata: Optional[str] = None,
) -> str:
    """保存内容到记忆系统，由系统自动决策是否持久化及存储目标。

    所有内容统一走 Journal -> JournalProcessor -> MemoryRouter 链路，
    无需调用方判断内容重要性或包含什么关键词。

    Args:
        content: 要提交给记忆系统的内容。
        category: 可选分类标签，如 "user_preference", "project_context", "decision"。
        metadata: JSON 格式的附加元数据（可选）。

    Returns:
        处理结果摘要。
    """
    await _ensure_store()
    assert _journal is not None
    assert _journal_processor is not None

    meta_dict: dict[str, Any] = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            return f"错误: metadata 不是合法的 JSON: {metadata}"

    if category:
        meta_dict["category"] = category

    global _round_count
    _round_count += 1

    # 内容原样传入 Journal，不做任何关键词注入。
    # JournalProcessor 会自然地通过 3 层决策判断是否持久化:
    #   - Zero-gate: Session Memory 总是写入
    #   - Layer 1: 自然检测"记住"、"我叫X"等模式
    #   - Layer 2+3: 新颖度过滤 + 重要性评分（本节调用立即刷新）
    journal_id = await _journal.append(
        user_id=_get_user_id(),
        session_id=_get_session_id(),
        round_id=_round_count,
        raw_input=content,
        raw_output="",
        entities=meta_dict,
        task_intent="QA",
    )

    # 立即刷新 JournalProcessor 候选缓冲区，确保 Layer 2+3 即时执行
    flushed = await _journal_processor.flush(user_id=_get_user_id())

    return (
        f"内容已提交到记忆系统. journal_id={journal_id}, round={_round_count}, "
        f"batch_flushed={flushed}. "
        "完整链路已执行: Journal -> EventBus -> JournalProcessor "
        "(Session 零门槛 + Layer 1 规则检查 + Layer 2/3 深度决策) -> MemoryRouter。"
    )


# ═══════════════════════════════════════════════════════════════════
# 查询工具
# ═══════════════════════════════════════════════════════════════════


@mcp.tool(
    name="search_memory",
    description=(
        "综合搜索。搜索长期记忆、语义概念、体验记录、会话记忆和 Journal 日志，"
        "返回按相关性排序的结果。适用场景：用户问'还记得...吗'、'之前怎么处理的'、"
        "'有没有类似的经历'等需要回顾历史信息的查询。"
    ),
)
async def search_memory(
    query: str,
    memory_type: Optional[str] = None,
    top_k: int = 10,
) -> str:
    """综合搜索记忆系统。

    搜索 5 个来源：长期记忆、语义概念、体验记录、会话记忆、Journal 日志。
    使用 UnifiedRetriever 并发检索 + 统一评分 + 跨源去重。
    """
    await _ensure_store()
    assert _retriever is not None, "retriever not initialized"

    top_k = min(max(top_k, 1), 50)

    # Map memory_type to retriever source names
    source_map: dict[str, str] = {
        "long_term": "long_term",
        "semantic": "knowledge",
        "experience": "experience",
        "session": "session",
        "journal": "journal",
    }
    sources = [source_map[memory_type]] if memory_type and memory_type in source_map else None

    results = await _retriever.retrieve(query, top_k=top_k, sources=sources)

    if not results:
        return f'## 搜索结果: "{query}"\n\n未找到匹配的记忆。'

    # Group by source for display
    grouped: dict[str, list[str]] = {}
    for item in results:
        src = item.source
        if src not in grouped:
            grouped[src] = []
        content = item.content[:500] if item.content else ""
        score = item.score
        meta = item.metadata or {}
        tags = []

        if src == "long_term":
            cat = meta.get("category", "")
            subtype = meta.get("ltm_subtype", "")
            if cat:
                tags.append(f"category={cat}")
            if subtype:
                tags.append(f"type={subtype}")
        elif src == "experience":
            etype = meta.get("experience_type", "")
            if etype:
                tags.append(f"type={etype}")
            exp_tags = meta.get("exp_tags", [])
            if exp_tags:
                tags.append(f"tags={','.join(exp_tags[:3])}")
        elif src == "knowledge":
            ntype = meta.get("node_type", "")
            if ntype:
                tags.append(f"node={ntype}")
        elif src == "session":
            turn = meta.get("turn", "")
            if turn:
                tags.append(f"turn={turn}")
        elif src == "journal":
            intent = meta.get("task_intent", "")
            status = meta.get("status", "")
            if intent:
                tags.append(f"intent={intent}")
            if status:
                tags.append(f"status={status}")

        tag_str = f" [{', '.join(tags)}]" if tags else ""
        grouped[src].append(f"  - score={score:.3f}{tag_str} {content}")

    source_labels = {
        "long_term": "### 长期记忆",
        "experience": "### 体验记录",
        "knowledge": "### 知识图谱",
        "session": "### 会话记忆",
        "journal": "### Journal 日志",
    }

    parts = [f'## 搜索结果: "{query}"\n']
    for src, label in source_labels.items():
        items = grouped.get(src)
        if items:
            parts.append(label)
            parts.extend(items[:top_k])

    return "\n".join(parts)


@mcp.tool(
    name="get_memory",
    description=(
        "按 ID 获取特定的记忆条目及其完整内容。适用场景：search_memory 返回了结果但"
        "内容被截断时，可使用此工具获取完整内容；或在已知 memory ID 时直接获取。"
    ),
)
async def get_memory(memory_id: str) -> str:
    """获取特定记忆的完整内容。

    Args:
        memory_id: 记忆 ID（由 search_memory 或 list_recent_memories 返回）。

    Returns:
        记忆的完整 JSON 表示，或错误信息。
    """
    await _ensure_store()
    assert _store is not None

    try:
        record = await _store.get_memory(memory_id)
        if record is None:
            return f"未找到记忆: {memory_id}"

        # Format as readable output
        content = record.get("content", "") or ""
        mtype = record.get("type", "")
        timestamp = record.get("timestamp", "")
        relevance = record.get("relevance_score", 0)
        access = record.get("access_count", 0)
        meta = record.get("metadata", {})

        parts = [
            f"## 记忆详情: {memory_id}",
            f"- 类型: {mtype}",
            f"- 时间: {timestamp}",
            f"- 相关性: {relevance}",
            f"- 访问次数: {access}",
        ]
        if meta:
            parts.append(f"- 元数据: {json.dumps(meta, ensure_ascii=False)[:500]}")
        parts.append(f"\n### 内容\n{content}")
        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to get memory: %s", e)
        return f"获取失败: {e}"


@mcp.tool(
    name="list_recent_memories",
    description=(
        "查看最近保存的记忆列表。适用场景：了解当前用户存储了哪些信息、"
        "检查记忆状态、确认最近的记忆写入是否成功。"
    ),
)
async def list_recent_memories(
    memory_type: Optional[str] = None,
    limit: int = 20,
) -> str:
    """列出最近的记忆条目。

    Args:
        memory_type: 可选，筛选类型（"long_term", "session", "experience" 等）。
        limit: 返回数量上限（默认 20，最大 100）。

    Returns:
        记忆列表摘要。
    """
    await _ensure_store()
    assert _store is not None
    assert _ltm is not None

    limit = min(max(limit, 1), 100)

    try:
        results = await _store.query_memories(
            type=memory_type or "long_term",
            user_id=_get_user_id(),
            top_k=limit,
        )

        if not results:
            return f"没有找到{' ' + memory_type if memory_type else ''}类型的记忆。"

        parts = [f"## 最近记忆 ({len(results)} 条)\n"]
        for i, r in enumerate(results, 1):
            content = (r.get("content", "") or "")[:120]
            ts = r.get("timestamp", "")[:19]  # datetime only
            mem_id = r.get("id", "")[:12]
            meta = r.get("metadata", {}) or {}
            cat = meta.get("category", "") if isinstance(meta, dict) else ""
            cat_tag = f" [{cat}]" if cat else ""
            parts.append(f"{i}. `{mem_id}` {ts}{cat_tag} {content}")

        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to list memories: %s", e)
        return f"列出失败: {e}"


@mcp.tool(
    name="search_experiences",
    description=(
        "搜索 Context-OS 中的体验记录（经历、反思、工作流程、工具使用历史）。"
        "适用场景：查找类似任务的过往处理方式、检查工具使用成功率、"
        "回顾过往经验教训。"
    ),
)
async def search_experiences(
    experience_type: Optional[str] = None,
    tags: Optional[str] = None,
    scenario_query: Optional[str] = None,
    top_k: int = 10,
) -> str:
    """搜索体验记录。

    Args:
        experience_type: 可选，体验子类型。可选: "episode", "reflection", "procedure", "tool_usage"。
        tags: 可选，逗号分隔的标签列表（如 "success,debugging"）。
        scenario_query: 可选，场景关键词模糊匹配。
        top_k: 返回数量上限（默认 10，最大 50）。

    Returns:
        体验记录列表。
    """
    await _ensure_store()
    assert _exp is not None

    top_k = min(max(top_k, 1), 50)
    tag_list: Optional[list[str]] = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    try:
        results = await _exp.recall_relevant(
            experience_type=experience_type,
            tags=tag_list,
            scenario_query=scenario_query,
            top_k=top_k,
        )

        if not results:
            return "未找到匹配的体验记录。"

        parts = [f"## 体验记录 ({len(results)} 条)\n"]
        for i, r in enumerate(results, 1):
            etype = r.get("experience_type", "")
            eid = r.get("id", "")[:12]
            ts = r.get("created_at", "")[:19]

            if etype == "episode":
                summary = f"scene={r.get('scene', '')}, action={r.get('action', '')}"
            elif etype == "reflection":
                summary = f"lesson={r.get('lesson', '')}"
            elif etype == "procedure":
                summary = f"proc={r.get('proc_name', '')}"
            elif etype == "tool_usage":
                summary = (
                    f"tool={r.get('tool_name', '')}, "
                    f"success={r.get('tool_success', '')}"
                )
            else:
                summary = str(r.get("metadata", ""))

            exp_tags = r.get("tags", [])
            if isinstance(exp_tags, str):
                try:
                    exp_tags = json.loads(exp_tags)
                except (json.JSONDecodeError, TypeError):
                    exp_tags = []
            tag_str = " #" + " #".join(exp_tags) if exp_tags else ""

            parts.append(f"{i}. `{eid}` {ts} [{etype}]{tag_str} {summary[:200]}")

        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to search experiences: %s", e)
        return f"搜索失败: {e}"


@mcp.tool(
    name="query_knowledge_graph",
    description=(
        "查询 Context-OS 知识图谱中的概念和关系。适用场景：了解某个概念的相关知识、"
        "查看概念之间的关联关系、探索知识结构。"
    ),
)
async def query_knowledge_graph(
    concept: Optional[str] = None,
    depth: int = 1,
    limit: int = 20,
) -> str:
    """查询知识图谱。

    Args:
        concept: 起始概念名称。如果不指定，将列出最近的概念。
        depth: 图遍历深度（1=直接关联, 2=关联的关联, 默认 1）。
        limit: 概念列表数量上限（不指定 concept 时生效，默认 20）。

    Returns:
        图谱查询结果。
    """
    await _ensure_store()
    assert _sem is not None
    assert _store is not None

    depth = min(max(depth, 1), 3)

    try:
        if concept:
            # Query subgraph starting from this concept
            graph = await _sem.query(concept, depth=depth)
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])

            parts = [
                f"## 知识图谱: {concept} (depth={depth})",
                f"\n### 概念节点 ({len(nodes)})",
            ]
            for node in nodes[:30]:
                name = node.get("name", "")
                conf = node.get("confidence", "-")
                node_type = node.get("node_type", "triple")
                parts.append(f"- **{name}** (type={node_type}, conf={conf})")

            if edges:
                parts.append(f"\n### 关系 ({len(edges)})")
                for edge in edges[:30]:
                    parts.append(
                        f"- **{edge.get('source', '')}** "
                        f"--[{edge.get('type', '')}]--> "
                        f"**{edge.get('target', '')}** "
                        f"(weight={edge.get('weight', '-')})"
                    )

            if not nodes:
                parts.append(f"未找到概念 '{concept}'。")
        else:
            # List recent concepts
            concepts = await _store.query(
                "SELECT name, node_type, confidence, updated_at "
                "FROM concepts ORDER BY updated_at DESC LIMIT ?",
                [limit],
            )
            if not concepts:
                return (
                    "知识图谱中暂无概念。可以通过 save_memory 或 log_turn 积累知识后自动构建。"
                )
            parts = [f"## 知识图谱概念 ({len(concepts)} 条)\n"]
            for c in concepts:
                parts.append(
                    f"- **{c['name']}** "
                    f"(type={c.get('node_type', '-')}, "
                    f"conf={c.get('confidence', '-')})"
                )

        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to query knowledge graph: %s", e)
        return f"查询失败: {e}"


@mcp.tool(
    name="get_memory_stats",
    description=(
        "获取 Context-OS 记忆系统的整体统计信息。包括各类型记忆数量、"
        "知识图谱规模、Journal 条目数等。适用场景：了解记忆系统当前状态、"
        "确认数据是否正常积累。"
    ),
)
async def get_memory_stats() -> str:
    """获取记忆系统统计信息。

    Returns:
        记忆系统统计摘要。
    """
    await _ensure_store()
    assert _store is not None

    try:
        # Count by type from memories table
        mem_counts = await _store.query(
            "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
        )
        mem_by_type = {r["type"]: r["cnt"] for r in mem_counts}
        total_mem = sum(mem_by_type.values())

        # Concept count
        concept_count = await _store.query("SELECT COUNT(*) as cnt FROM concepts")
        total_concepts = concept_count[0]["cnt"] if concept_count else 0

        # Relation count
        rel_count = await _store.query(
            "SELECT COUNT(*) as cnt FROM concept_relations"
        )
        total_relations = rel_count[0]["cnt"] if rel_count else 0

        # Experience count by type
        exp_counts = await _store.query(
            "SELECT experience_type, COUNT(*) as cnt "
            "FROM experiences GROUP BY experience_type"
        )
        exp_by_type = {r["experience_type"]: r["cnt"] for r in exp_counts}
        total_exp = sum(exp_by_type.values())

        # Journal count
        journal_count = await _store.query("SELECT COUNT(*) as cnt FROM journal")
        total_journal = journal_count[0]["cnt"] if journal_count else 0

        # DB path
        db_path = _get_db_path()

        parts = [
            "## Context-OS 记忆系统统计",
            f"\n数据库: `{db_path}`",
            f"用户: `{_get_user_id()}`",
            f"会话: `{_get_session_id()}`",
            f"\n### 记忆 ({total_mem} 条)",
        ]
        for t, c in sorted(mem_by_type.items()):
            parts.append(f"- {t}: {c}")

        parts.append(f"\n### 体验记录 ({total_exp} 条)")
        for t, c in sorted(exp_by_type.items()):
            parts.append(f"- {t}: {c}")

        parts.append(f"\n### 知识图谱")
        parts.append(f"- 概念: {total_concepts}")
        parts.append(f"- 关系: {total_relations}")

        parts.append(f"\n### 其他")
        parts.append(f"- Journal 条目: {total_journal}")
        parts.append(
            f"- 后台 Worker: "
            f"JournalProcessor=active, "
            f"ConceptWorker={'running' if _concept_worker else 'disabled'}"
        )

        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        return f"获取统计失败: {e}"


@mcp.tool(
    name="get_journal_entries",
    description=(
        "查询 Context-OS 的对话日志（Journal）。Journal 记录了每轮对话的输入输出，"
        "可用于回顾对话历史、提取知识和理解上下文演变。适用场景：查看最近的对话记录、"
        "了解之前的交互内容。"
    ),
)
async def get_journal_entries(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 10,
    status: Optional[str] = None,
) -> str:
    """查询 Journal 对话日志。

    Args:
        user_id: 可选，按用户筛选（默认使用环境变量用户 ID）。
        session_id: 可选，按会话筛选。
        limit: 返回条目数量上限（默认 10，最大 50）。
        status: 可选，按处理状态筛选（pending/processing/processed/discarded）。

    Returns:
        Journal 条目摘要。
    """
    await _ensure_store()
    assert _store is not None

    limit = min(max(limit, 1), 50)
    uid = user_id or _get_user_id()

    try:
        conditions = ["1=1"]
        params: list[Any] = []

        if uid:
            conditions.append("user_id = ?")
            params.append(uid)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        results = await _store.query(
            f"SELECT * FROM journal WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            [*params, limit],
        )

        if not results:
            return "没有找到匹配的 Journal 条目。"

        parts = [f"## Journal 条目 ({len(results)} 条)\n"]
        for i, r in enumerate(results, 1):
            jid = r.get("id", "")[:12]
            ts = r.get("created_at", "")[:19]
            round_id = r.get("round_id", "")
            stat = r.get("status", "")
            intent = r.get("task_intent", "")
            raw_input = (r.get("raw_input", "") or "")[:120]
            raw_output = (r.get("raw_output", "") or "")[:120]

            parts.append(
                f"{i}. `{jid}` R{round_id} {ts} [{stat}] intent={intent}\n"
                f"   Q: {raw_input}\n"
                f"   A: {raw_output}"
            )

        return "\n".join(parts)

    except Exception as e:
        logger.error("Failed to query journal: %s", e)
        return f"查询失败: {e}"


# ── Cleanup helpers ──────────────────────────────────────────────────


async def _shutdown() -> None:
    """Gracefully shut down background workers and flush pending buffers."""
    global _concept_worker, _journal_processor

    if _concept_worker:
        logger.info("Stopping BackgroundConceptWorker...")
        await _concept_worker.stop()

    if _journal_processor:
        logger.info("Flushing JournalProcessor batch...")
        await _journal_processor.flush(user_id=_get_user_id())


# ── Entry point ──────────────────────────────────────────────────────


def create_server() -> FastMCP:
    """Create and return the MCP server instance (for programmatic use)."""
    return mcp


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    logger.info(
        "Starting Context-OS MCP Server (full pipeline: Journal → EventBus → "
        "JournalProcessor → MemoryRouter)"
    )
    mcp.run()


if __name__ == "__main__":
    main()
