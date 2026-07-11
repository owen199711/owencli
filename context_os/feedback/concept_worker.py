"""后台概念抽取 Worker。

基于 LTM_WRITE_STRATEGY.md 第 4.4 节的设计，实现通道 B 的异步三元组抽取：

触发方式: 事件驱动 + 定时兜底（非固定轮询）
  - 事件驱动: 每次 concept_pending=true 写入后发送信号
  - 收到信号后启动 2 分钟 debounce 计时器
  - 2 分钟内无新信号 → 检查 pending 数量:
      pending ≥ 30 → 批量调 LLM 抽取三元组 → 写入 Knowledge → 清除标记
      pending < 30 → 不处理，等待下次信号
  - 距离上次批量处理超 15 分钟 → 强制处理（无论 pending 数量）
  - Pipeline.close() 时: pending ≥ 10 即触发批量抽取
  - 单次 LLM 调用处理上限: 50 条
  - 失败不影响主流程（标记不清除，下次重试）
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger

if TYPE_CHECKING:
    from context_os.llm.client import BaseLLMClient
    from context_os.memory.long_term import LongTermMemory
    from context_os.memory.semantic import SemanticMemory

# 运行时导入：概念质量验证
from context_os.feedback.triple_extractor import _is_valid_concept

logger = get_logger(__name__)

# 常量
DEBOUNCE_SECONDS = 120       # 2 分钟 debounce
FALLBACK_SECONDS = 900       # 15 分钟兜底
PENDING_THRESHOLD = 30       # 事件驱动触发的 pending 数量阈值
CLOSE_THRESHOLD = 10         # close() 时的 pending 数量阈值
MAX_BATCH_SIZE = 50          # 单次 LLM 调用处理上限


class BackgroundConceptWorker:
    """后台概念抽取 Worker。

    异步处理 LTM 中标记为 concept_pending 的记录，
    通过 LLM 批量抽取三元组并写入 Knowledge 层。

    Args:
        ltm: LongTermMemory 实例，用于查询概念待定记录。
        knowledge: SemanticMemory 实例，用于写入抽取的概念和关系。
        llm_client: LLM 客户端，用于通道 B 抽取。
        debounce_seconds: 信号驱动的 debounce 时间（秒），默认 120。
        fallback_seconds: 定时兜底间隔（秒），默认 900。
        pending_threshold: 事件驱动触发的最小 pending 数，默认 30。
        close_threshold: close() 时触发的最小 pending 数，默认 10。
        max_batch_size: 单次 LLM 调用处理上限，默认 50。
    """

    def __init__(
        self,
        ltm: "LongTermMemory",
        knowledge: "SemanticMemory",
        llm_client: "BaseLLMClient",
        debounce_seconds: int = DEBOUNCE_SECONDS,
        fallback_seconds: int = FALLBACK_SECONDS,
        pending_threshold: int = PENDING_THRESHOLD,
        close_threshold: int = CLOSE_THRESHOLD,
        max_batch_size: int = MAX_BATCH_SIZE,
    ):
        self._ltm = ltm
        self._knowledge = knowledge
        self._llm = llm_client
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
        self._pending_signal_count: int = 0

        logger.info(
            "BackgroundConceptWorker init: debounce=%ds, fallback=%ds, "
            "threshold=%d, close_threshold=%d, max_batch=%d",
            debounce_seconds, fallback_seconds, pending_threshold,
            close_threshold, max_batch_size,
        )

    def start(self) -> None:
        """启动后台 Worker。"""
        if self._running:
            return
        self._running = True
        self._last_process_time = time.time()
        self._task = asyncio.ensure_future(self._worker_loop())
        logger.info("BackgroundConceptWorker started")

    async def stop(self) -> None:
        """停止后台 Worker，并强制刷新 pending。"""
        if not self._running:
            return

        self._running = False
        self._event.set()  # 唤醒 worker 循环

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=30)
            except asyncio.TimeoutError:
                logger.warning("BackgroundConceptWorker stop timeout, cancelling")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        # 强制刷新：pending ≥ close_threshold 时触发
        await self._flush_on_close()
        logger.info("BackgroundConceptWorker stopped")

    def signal(self) -> None:
        """发送信号：有新的 concept_pending 记录写入。

        线程安全，可在任何 asyncio 上下文中调用。
        """
        if not self._running:
            return
        self._pending_signal_count += 1
        # 设置事件，唤醒 worker
        # 注意：Event.set() 即使已设置也是安全的
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._event.set)
        logger.debug(
            "ConceptWorker signalled (pending signals: %d)",
            self._pending_signal_count,
        )

    async def flush(self, force: bool = False, threshold: Optional[int] = None) -> int:
        """手动触发一次批量处理。

        Args:
            force: 是否强制执行（忽略 pending 数量阈值）。
            threshold: 触发的最小 pending 数（None 则使用默认值）。

        Returns:
            处理的记录数。
        """
        return await self._do_process(force=force, threshold=threshold)

    # ── Private ─────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """主循环：事件驱动 + 定时兜底。"""
        while self._running:
            try:
                # 等待事件，最多等 fallback_seconds
                await asyncio.wait_for(self._event.wait(), timeout=self._fallback)
            except asyncio.TimeoutError:
                # 兜底触发：超过 15 分钟无信号
                logger.debug("ConceptWorker fallback timer fired")
                await self._do_process(force=False, threshold=1)
                self._event.clear()
                continue

            # 收到信号
            self._event.clear()

            # Debounce: 等待 DEBOUNCE_SECONDS，期间有新信号则重置等待
            while self._running:
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=self._debounce)
                    # 有新信号 → 重置 debounce 计时器
                    self._event.clear()
                    logger.debug("ConceptWorker: signal received, resetting debounce")
                    continue
                except asyncio.TimeoutError:
                    # Debounce 到期 → 处理
                    break

            if not self._running:
                break

            await self._do_process(force=False, threshold=self._threshold)

        logger.debug("ConceptWorker loop exited")

    async def _do_process(
        self,
        force: bool = False,
        threshold: Optional[int] = None,
    ) -> int:
        """执行一次批量处理。

        Args:
            force: 强制执行（忽略阈值检查）。
            threshold: 触发阈值（默认使用 self._threshold）。

        Returns:
            处理的记录数。
        """
        if threshold is None:
            threshold = self._threshold

        try:
            # 查询 concept_pending 记录
            pending = await self._query_pending(self._max_batch)
            if not pending:
                logger.debug("ConceptWorker: no pending records")
                return 0

            if not force and len(pending) < threshold:
                logger.debug(
                    "ConceptWorker: pending=%d < threshold=%d, skipping",
                    len(pending), threshold,
                )
                return 0

            logger.info(
                "ConceptWorker: processing %d pending records (force=%s, threshold=%d)",
                len(pending), force, threshold,
            )

            # LLM 批量抽取三元组
            triples = await self._extract_triples(pending)
            if not triples:
                logger.warning("ConceptWorker: no triples extracted from %d records", len(pending))
                # 即使没有抽取到三元组，也清除 concept_pending 标记（避免死循环）
                await self._clear_pending(pending)
                return len(pending)

            # 写入 Knowledge 层
            written = await self._write_to_knowledge(triples)

            # 清除 concept_pending 标记
            await self._clear_pending(pending)

            self._last_process_time = time.time()
            self._pending_signal_count = 0

            logger.info(
                "ConceptWorker: done — %d records → %d triples → %d concepts/relations written",
                len(pending), len(triples), written,
            )
            return len(pending)

        except Exception as e:
            logger.error("ConceptWorker batch processing failed: %s", e, exc_info=True)
            # 失败不阻塞主流程，pending 标记不清除，下次重试
            return 0

    async def _flush_on_close(self) -> int:
        """close() 时的强制刷新。"""
        total = 0
        try:
            pending = await self._query_pending(self._max_batch)
            if pending and len(pending) >= self._close_threshold:
                logger.info(
                    "ConceptWorker: flush on close — %d pending records",
                    len(pending),
                )
                triples = await self._extract_triples(pending)
                if triples:
                    await self._write_to_knowledge(triples)
                await self._clear_pending(pending)
                total = len(pending)
        except Exception as e:
            logger.warning("ConceptWorker flush on close failed: %s", e)
        return total

    async def _query_pending(self, limit: int) -> list[dict[str, Any]]:
        """查询 LTM 中 concept_pending=true 的记录。

        Args:
            limit: 返回上限。

        Returns:
            待处理记录列表。
        """
        if not self._ltm.store.is_connected:
            return []

        # 查询 long_term 类型的记忆，筛选 metadata.concept_pending=True
        rows = await self._ltm.store.query(
            "SELECT * FROM memories "
            "WHERE type = 'long_term' "
            "AND user_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            [self._ltm.user_id, limit],
        )
        if not rows:
            return []

        results = []
        for r in rows:
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            if meta.get("concept_pending"):
                results.append(r)
        return results

    async def _extract_triples(
        self,
        records: list[dict[str, Any]],
    ) -> list[tuple[str, str, str]]:
        """通过 LLM 从 pending 记录中批量抽取三元组。

        Args:
            records: concept_pending 记录列表。

        Returns:
            三元组列表: [(subject, relation, object), ...]
        """
        # 构造批量抽取 prompt
        texts = []
        for i, r in enumerate(records):
            content = r.get("content", "").strip()
            if content:
                texts.append(f"[{i + 1}] {content}")

        combined = "\n".join(texts)
        if not combined.strip():
            return []

        prompt = _build_channel_b_prompt(combined, len(texts))

        try:
            response = await self._llm.complete(prompt)
            triples = _parse_channel_b_response(str(response))
            logger.debug(
                "Channel B LLM extraction: %d records → %d triples",
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
        """将三元组写入 Knowledge 层（concepts + relations）。

        写入前对概念名称进行质量验证，跳过无效概念。

        Args:
            triples: [(subject, relation, object), ...]

        Returns:
            写入的条目数（概念 + 关系）。
        """
        count = 0
        for subject, relation, obj in triples:
            try:
                # 质量过滤：跳过无效概念
                if not _is_valid_concept(subject, min_len=3) or not _is_valid_concept(obj, min_len=3):
                    continue
                if subject == obj:
                    continue

                # 确保概念存在
                await self._knowledge.add_concept(
                    name=subject,
                    attributes={"source": "channel_b"},  # LLM 抽取
                    confidence=0.7,
                )
                await self._knowledge.add_concept(
                    name=obj,
                    attributes={"source": "channel_b"},
                    confidence=0.7,
                )
                # 添加关系
                await self._knowledge.add_relation(
                    source=subject,
                    target=obj,
                    relation_type=relation,
                    weight=0.7,
                )
                count += 1
            except Exception as e:
                logger.debug("Failed to write triple (%s, %s, %s): %s", subject, relation, obj, e)

        return count

    async def _clear_pending(self, records: list[dict[str, Any]]) -> None:
        """清除 concept_pending 标记。

        将 metadata.concept_pending 设为 False。

        Args:
            records: 待清除的记录列表。
        """
        for r in records:
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(meta, dict):
                continue
            meta["concept_pending"] = False
            try:
                await self._ltm.store.save_memory(
                    id=r["id"],
                    type="long_term",
                    content=r.get("content", ""),
                    user_id=r.get("user_id", self._ltm.user_id),
                    metadata=meta,
                )
            except Exception as e:
                logger.debug("Failed to clear pending for %s: %s", r["id"], e)


# ── Prompt 模板 ───────────────────────────────────────────────

_CHANNEL_B_PROMPT_TMPL = """你是一个知识图谱构建助手。请从以下文本中提取出「主语-关系-宾语」三元组。

核心原则：
1. 主语和宾语必须是完整的语义实体（人名、组织、技术术语、数值、事件等），不能是文本碎片或单个字。
2. 只提取明确表达的关系，不要编造或推测。
3. 每条输入文本可能产生 0 个或多个三元组。

关系类型（只能从以下选择）：
  - 是 / 属于 / 包含 / 基于 / 依赖 / 使用 / 调用 / 实现 / 产出 / 导致 / 协作

实体命名规范：
  - 人名用全名或简称（如 "Alice", "Bob", "Charlie"）
  - 技术术语用标准名称（如 "PostgreSQL", "React", "Docker"）
  - 数值信息附带单位（如 "3000元", "50%", "15ms"）
  - 组织/项目名用完整名称（如 "Alpha项目", "创业团队"）

正确示例 ✓：
  [{{"subject": "Alpha项目", "relation": "使用", "object": "React"}},
   {{"subject": "Bob", "relation": "协作", "object": "Alice"}},
   {{"subject": "服务器", "relation": "包含", "object": "CPU"}},
   {{"subject": "Alice", "relation": "支付", "object": "200元"}}]

错误示例 ✗（不要输出这样的碎片）：
  [{{"subject": "的", "relation": "是", "object": "在"}},
   {{"subject": "J", "relation": "使用", "object": "a"}},
   {{"subject": "L bash psql", "relation": "使用", "object": "r"}}]

输出格式（JSON 数组）：
[
  {{"subject": "主实体", "relation": "关系类型", "object": "宾实体"}},
  ...
]

输入文本 ({count} 条)：
{texts}

请只输出 JSON 数组，不要包含其他内容。"""


def _build_channel_b_prompt(combined_text: str, count: int) -> str:
    """构造通道 B 的 LLM prompt。"""
    return _CHANNEL_B_PROMPT_TMPL.format(texts=combined_text, count=count)


def _parse_channel_b_response(response: str) -> list[tuple[str, str, str]]:
    """解析 LLM 返回的三元组 JSON。"""
    import re as _re

    # 尝试提取 JSON 数组
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
