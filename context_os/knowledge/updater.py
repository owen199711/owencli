"""KnowledgeUpdater — 事件驱动的知识提取处理器。

从 KnowledgeQueue 消费待处理内容，通过 LLM 批量抽取三元组，
写入 SemanticMemory（concepts + relations）。

设计:
- 复用 BackgroundConceptWorker 的 LLM 提取逻辑
- 通过 EventBus 订阅 journal:created 事件（触发 dequeue）
- 2 分钟 debounce + 15 分钟定时兜底
- close() 时强制刷新 pending
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger

if TYPE_CHECKING:
    from context_os.events.bus import EventBus
    from context_os.feedback.triple_extractor import TripleExtractor
    from context_os.knowledge.queue import KnowledgeQueue
    from context_os.llm.client import BaseLLMClient
    from context_os.memory.semantic import SemanticMemory

logger = get_logger(__name__)

# ── 常量 ──
DEBOUNCE_SECONDS = 120         # 2 分钟 debounce
FALLBACK_SECONDS = 900         # 15 分钟兜底
PENDING_THRESHOLD = 10         # 事件驱动触发阈值（从 KnowledgeQueue 消费）
CLOSE_THRESHOLD = 5            # close() 时的最小 pending 数
MAX_BATCH_SIZE = 20            # 单次 LLM 调用处理上限


class KnowledgeUpdater:
    """知识提取处理器。

    替代 BackgroundConceptWorker 的 LTM 扫描模式，
    改为直接消费 KnowledgeQueue。

    使用方式:
        updater = KnowledgeUpdater(
            knowledge_queue=queue,
            triple_extractor=extractor,
            llm_client=client,
            semantic_memory=sem,
            event_bus=bus,
        )
        await updater.start()
        ...
        await updater.stop()
    """

    def __init__(
        self,
        knowledge_queue: "KnowledgeQueue",
        triple_extractor: "TripleExtractor",
        llm_client: "BaseLLMClient",
        semantic_memory: "SemanticMemory",
        event_bus: Optional["EventBus"] = None,
        debounce_seconds: int = DEBOUNCE_SECONDS,
        fallback_seconds: int = FALLBACK_SECONDS,
        pending_threshold: int = PENDING_THRESHOLD,
        close_threshold: int = CLOSE_THRESHOLD,
        max_batch_size: int = MAX_BATCH_SIZE,
    ):
        self._queue = knowledge_queue
        self._triple_extractor = triple_extractor
        self._llm = llm_client
        self._semantic = semantic_memory
        self._event_bus = event_bus

        self._debounce = debounce_seconds
        self._fallback = fallback_seconds
        self._threshold = pending_threshold
        self._close_threshold = close_threshold
        self._max_batch = max_batch_size

        # 状态
        self._event = asyncio.Event()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_process_time: float = 0.0

        # 订阅 EventBus（如果提供）
        if self._event_bus:
            self._event_bus.subscribe("journal:created", self._on_journal_created)

        logger.info(
            "KnowledgeUpdater init: debounce=%ds, fallback=%ds, "
            "threshold=%d, close_threshold=%d, max_batch=%d",
            debounce_seconds, fallback_seconds, pending_threshold,
            close_threshold, max_batch_size,
        )

    def start(self) -> None:
        """启动后台处理循环（同步，创建 async task）。"""
        if self._running:
            return
        self._running = True
        self._last_process_time = time.time()
        self._task = asyncio.ensure_future(self._worker_loop())
        logger.info("KnowledgeUpdater started")

    async def stop(self) -> None:
        """停止处理循环并强制刷新。"""
        if not self._running:
            return
        self._running = False
        self._event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=30)
            except asyncio.TimeoutError:
                logger.warning("KnowledgeUpdater stop timeout, cancelling")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        # 取消订阅
        if self._event_bus:
            self._event_bus.unsubscribe("journal:created", self._on_journal_created)

        # 强制刷新
        await self._flush_on_close()
        logger.info("KnowledgeUpdater stopped")

    def _on_journal_created(self, event: Any) -> None:
        """收到 JournalCreatedEvent 时发送处理信号。"""
        # 此方法在 EventBus 的 publish 上下文中被调用
        # 只设置信号，由 worker_loop 异步处理
        if self._running:
            self._event.set()
            logger.debug("KnowledgeUpdater signalled by journal:created")

    # ── 内部 ──

    async def _worker_loop(self) -> None:
        """主循环：事件驱动 + 定时兜底。"""
        while self._running:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=self._fallback)
            except asyncio.TimeoutError:
                logger.debug("KnowledgeUpdater fallback timer fired")
                await self._do_process(force=False, threshold=1)
                self._event.clear()
                continue

            self._event.clear()

            # Debounce: 等待 debounce 时间，期间新信号重置等待
            while self._running:
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=self._debounce)
                    self._event.clear()
                    logger.debug("KnowledgeUpdater: signal received, resetting debounce")
                    continue
                except asyncio.TimeoutError:
                    break

            if not self._running:
                break

            await self._do_process(force=False, threshold=self._threshold)

        logger.debug("KnowledgeUpdater loop exited")

    async def _do_process(
        self,
        force: bool = False,
        threshold: Optional[int] = None,
    ) -> int:
        """执行一次批量处理。

        Args:
            force: 强制执行。
            threshold: 触发阈值。

        Returns:
            处理的任务数。
        """
        if threshold is None:
            threshold = self._threshold

        try:
            # 从 KnowledgeQueue 取出待处理任务
            tasks = await self._queue.dequeue_batch(self._max_batch)
            if not tasks:
                logger.debug("KnowledgeUpdater: no pending tasks in queue")
                return 0

            if not force and len(tasks) < threshold:
                logger.debug(
                    "KnowledgeUpdater: pending=%d < threshold=%d, skipping",
                    len(tasks), threshold,
                )
                return 0

            logger.info(
                "KnowledgeUpdater: processing %d tasks (force=%s, threshold=%d)",
                len(tasks), force, threshold,
            )

            # 从概念内容中提取用户输入文本用于三元组抽取
            texts: list[dict[str, Any]] = []
            for t in tasks:
                content = t.get("content", "")
                if content.strip():
                    texts.append({"id": t["id"], "content": content, "user_id": t.get("user_id", "anonymous")})

            if not texts:
                # 标记所有为空完成
                for t in tasks:
                    await self._queue.mark_done(t["id"])
                return len(tasks)

            # LLM 批量抽取三元组
            triples = await self._extract_triples(texts)
            if not triples:
                logger.warning("KnowledgeUpdater: no triples extracted from %d texts", len(texts))
                for t in tasks:
                    await self._queue.mark_done(t["id"])
                return len(tasks)

            # 写入 Knowledge 层
            written = await self._write_to_knowledge(triples)

            # 标记完成
            for t in tasks:
                await self._queue.mark_done(t["id"])

            self._last_process_time = time.time()

            logger.info(
                "KnowledgeUpdater: done — %d tasks → %d triples → %d written",
                len(tasks), len(triples), written,
            )
            return len(tasks)

        except Exception as e:
            logger.error("KnowledgeUpdater batch processing failed: %s", e, exc_info=True)
            return 0

    async def _flush_on_close(self) -> int:
        """close() 时的强制刷新。"""
        total = 0
        try:
            tasks = await self._queue.dequeue_batch(self._max_batch)
            if tasks and len(tasks) >= self._close_threshold:
                logger.info(
                    "KnowledgeUpdater: flush on close — %d pending tasks",
                    len(tasks),
                )
                texts = [{"id": t["id"], "content": t.get("content", ""),
                          "user_id": t.get("user_id", "anonymous")} for t in tasks if t.get("content")]
                if texts:
                    triples = await self._extract_triples(texts)
                    if triples:
                        await self._write_to_knowledge(triples)
                for t in tasks:
                    await self._queue.mark_done(t["id"])
                total = len(tasks)
        except Exception as e:
            logger.warning("KnowledgeUpdater flush on close failed: %s", e)
        return total

    # ── LLM 抽取（复用 concept_worker 逻辑）──

    _CHANNEL_B_PROMPT_TMPL = """你是一个知识图谱构建助手。请从以下文本中提取出「主语-关系-宾语」三元组。

核心原则：
1. 主语和宾语必须是完整的语义实体（人名、组织、技术术语、数值、事件等），不能是文本碎片或单个字。
2. 只提取明确表达的关系，不要编造或推测。
3. 每条输入文本可能产生 0 个或多个三元组。

关系类型（只能从以下选择）：
  - 是 / 属于 / 包含 / 基于 / 依赖 / 使用 / 调用 / 实现 / 产出 / 导致 / 协作

实体命名规范：
  - 人名用全名或简称
  - 技术术语用标准名称（如 "PostgreSQL", "React", "Docker"）
  - 数值信息附带单位（如 "3000元", "50%", "15ms"）
  - 组织/项目名用完整名称

输出格式（JSON 数组）：
[
  {{"subject": "主实体", "relation": "关系类型", "object": "宾实体"}},
  ...
]

输入文本 ({count} 条)：
{texts}

请只输出 JSON 数组，不要包含其他内容。"""

    async def _extract_triples(
        self,
        texts: list[dict[str, Any]],
    ) -> list[tuple[str, str, str]]:
        """通过 LLM 批量抽取三元组。"""
        lines = []
        for i, t in enumerate(texts):
            content = t["content"].strip()
            if content:
                lines.append(f"[{i + 1}] {content}")

        combined = "\n".join(lines)
        if not combined.strip():
            return []

        prompt = self._CHANNEL_B_PROMPT_TMPL.format(
            texts=combined, count=len(lines),
        )

        try:
            response = await self._llm.complete(prompt)
            triples = _parse_channel_b_response(str(response))
            logger.debug(
                "Channel B LLM extraction: %d texts → %d triples",
                len(texts), len(triples),
            )
            return triples
        except Exception as e:
            logger.warning("Channel B LLM extraction failed: %s", e)
            return []

    async def _write_to_knowledge(
        self,
        triples: list[tuple[str, str, str]],
    ) -> int:
        """将三元组写入 SemanticMemory（concepts + relations）。"""
        from context_os.feedback.triple_extractor import _is_valid_concept

        count = 0
        for subject, relation, obj in triples:
            try:
                if not _is_valid_concept(subject, min_len=3) or not _is_valid_concept(obj, min_len=3):
                    continue
                # 纯数字检查
                if subject.strip().isdigit() or obj.strip().isdigit():
                    continue
                if subject == obj:
                    continue

                await self._semantic.add_concept(
                    name=subject,
                    attributes={"source": "channel_b"},
                    confidence=0.7,
                )
                await self._semantic.add_concept(
                    name=obj,
                    attributes={"source": "channel_b"},
                    confidence=0.7,
                )
                await self._semantic.add_relation(
                    source=subject,
                    target=obj,
                    relation_type=relation,
                    weight=0.7,
                )
                count += 1
            except Exception as e:
                logger.debug("Failed to write triple (%s, %s, %s): %s", subject, relation, obj, e)

        return count


def _parse_channel_b_response(response: str) -> list[tuple[str, str, str]]:
    """解析 LLM 返回的三元组 JSON。"""
    import json
    import re as _re

    match = _re.search(r"\[.*\]", response, _re.DOTALL)
    if not match:
        return []

    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        s = str(item.get("subject", "")).strip()
        r = str(item.get("relation", "")).strip()
        o = str(item.get("object", "")).strip()
        if s and r and o:
            result.append((s, r, o))
    return result
