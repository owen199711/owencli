"""记忆更新器。

在每次 Pipeline 执行后，根据结果更新各层记忆。

Phase 3: 实现统一写入决策（三层闸门 + 分流存储）

新旧策略可通过 USE_NEW_STRATEGY 开关切换，直到阶段五才删除旧分支。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger
from context_os.core.models import EvalMetrics, TaskSpec
from context_os.memory.episodic import EpisodicMemory
from context_os.memory.experience import ExperienceMemory
from context_os.memory.long_term import LongTermMemory
from context_os.memory.semantic import SemanticMemory
from context_os.memory.session_memory import SessionMemory
from context_os.memory.working import WorkingMemory
from context_os.feedback.memory_importance import ImportanceScorer, ImportanceScore
from context_os.feedback.triple_extractor import TripleExtractor, TripleExtractResult

if TYPE_CHECKING:
    from context_os.feedback.concept_worker import BackgroundConceptWorker

logger = get_logger(__name__)

# ════════════════════════════════════════════════════════════════
# 新旧策略开关（阶段五删除此开关和旧逻辑）
# ════════════════════════════════════════════════════════════════
USE_NEW_STRATEGY = True

# ── Layer 1 常量 ──────────────────────────────────────────────
_EXPLICIT_MEMORY_KEYWORDS = re.compile(
    r"记住|记录|设置为|保存|不要忘记|务必记住|务必|"
    r"remember|save|set\s+to|don'?t\s+forget|keep\s+in\s+mind",
    re.IGNORECASE,
)

# KV 提取模式: 主语+是/住/在/喜欢/偏好/叫+宾语
_KV_PATTERNS = [
    re.compile(r"(?P<entity>.{1,20}?)(?:是|住在|叫|叫做|在|住|喜欢|偏好|讨厌|的)(?P<value>.{1,40}?)(?:[，。,.]|$)"),
    re.compile(r"(?P<entity>.{1,20}?)\s*(?:is\s+called|is|live\s+in|likes?|prefers?|hates?)\s+(?P<value>.{1,40}?)(?:[.,]|$)"),
]

# 任务结论模式: LLM 回复中的结构化结论
_CONCLUSION_PATTERNS = re.compile(
    r"(?:余额为|总额为|结果为|总计为|余额|总计|合计|最终)"
    r"[\s\d.,]+(?:元|个|人|次|万)",
    re.IGNORECASE,
)

# ── 批量触发常量 ──────────────────────────────────────────────
BATCH_SIZE_THRESHOLD = 5   # 候选区 ≥ 5 条触发
BATCH_TURN_THRESHOLD = 10  # 对话轮次 ≥ 10 触发
BATCH_TIMER_SECONDS = 300  # 距上次批量写入 > 5 分钟触发

# ── 实体类型推断模式 ──────────────────────────────────────────
_ENTITY_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"我|my|i\b"), "user"),
    (re.compile(r"你|you\b"), "agent"),
    (re.compile(r"公司|团队|组织|company|team|org"), "org"),
    (re.compile(r"服务器|主机|server|host"), "host"),
    (re.compile(r"项目|仓库|project|repo"), "project"),
    (re.compile(r"文件|文档|file|doc"), "file"),
]


@dataclass
class WriteDecisionResult:
    """write_decision() 的返回结果。"""

    should_store: bool
    score: float
    candidates: list[dict[str, Any]] = field(default_factory=list)
    layer1_rule_hit: bool = False
    layer2_novelty_pass: bool = False
    layer3_score_detail: Optional[ImportanceScore] = None
    entity_key: Optional[str] = None
    triple_result: Optional[TripleExtractResult] = None


class MemoryUpdater:
    """记忆更新器（门卫 + 调度员）。

    Phase 3 架构:
        MemoryUpdater.update_from_task()
          ├─ Working.push()           ← 每轮自动（无门槛）
          ├─ Session.save()           ← 每轮自动（无门槛）
          │
          ├─ write_decision()         ← 统一闸门（三层判断）
          └─ if should_store:
               ├─ classify_and_route()  ← 分流到 3 个持久层
               └─ dispatch_to_stores()
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        short_term_memory: SessionMemory,
        long_term_memory: LongTermMemory,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        experience_memory: Optional[ExperienceMemory] = None,
        # ── Phase 3 新增依赖 ──
        importance_scorer: Optional[ImportanceScorer] = None,
        triple_extractor: Optional[TripleExtractor] = None,
        concept_worker: Optional["BackgroundConceptWorker"] = None,
    ):
        self.wm = working_memory
        self.stm = short_term_memory
        self.ltm = long_term_memory
        self.epm = episodic_memory
        self.sem = semantic_memory
        self.exp = experience_memory

        # Phase 3 新增
        self._importance = importance_scorer or ImportanceScorer()
        self._triple_extractor = triple_extractor or TripleExtractor()
        self._concept_worker = concept_worker

        # 状态追踪
        self._turn_count: int = 0
        self._last_batch_time: float = time.time()

        logger.info(
            "MemoryUpdater initialized (new_strategy=%s, has_concept_worker=%s)",
            USE_NEW_STRATEGY, concept_worker is not None,
        )

    # ── 主入口 ─────────────────────────────────────────────────

    async def update_from_task(
        self,
        task: TaskSpec,
        response: str,
        metrics: EvalMetrics,
        user_id: str = "anonymous",
    ) -> None:
        """根据任务执行结果更新所有记忆层级。

        Args:
            task: 原始任务。
            response: LLM 的回复。
            metrics: 评估指标。
            user_id: 用户 ID。
        """
        logger.info("Updating memory from task: %s", task.id)
        self._turn_count += 1

        # ── 无门槛层：Working & Session（新旧策略都执行） ──
        self._update_working(task, response)
        await self._update_session(task, response, user_id)

        if USE_NEW_STRATEGY:
            await self._update_persistent_new(task, response, metrics, user_id)
        else:
            await self._update_persistent_old(task, response, metrics, user_id)

        logger.info("Memory update complete for task: %s", task.id)

    # ════════════════════════════════════════════════════════════
    # 新策略（Phase 3）
    # ════════════════════════════════════════════════════════════

    async def _update_persistent_new(
        self,
        task: TaskSpec,
        response: str,
        metrics: EvalMetrics,
        user_id: str,
    ) -> None:
        """Phase 3 持久层写入：候选缓冲 + 批量触发 + 统一决策 + 分流。"""
        # 组合候选文本
        candidate_text = self._build_candidate_text(task, response, metrics)

        # Layer 1 立即判断
        layer1_result = self._layer1_rule_check(candidate_text, task, response, metrics)

        if layer1_result.should_store:
            # Layer 1 命中 → 立即通过，跳过 Layer 2/3
            logger.info(
                "Layer 1 rule hit: should_store=True, score=%.3f, entity_key=%s",
                layer1_result.score, layer1_result.entity_key,
            )
            await self._dispatch_to_stores(
                task, response, metrics, layer1_result, user_id,
            )
            return

        # Layer 1 未命中 → 推入候选缓冲区，检查批量触发条件
        pending_id = await self.stm.add_pending_candidate(
            content=candidate_text,
            entities={
                "task_id": task.id,
                "intent": task.intent.value,
                "raw_input": task.raw_input[:100],
            },
            turn_number=self._turn_count,
            user_id=user_id,
        )
        logger.debug("Candidate buffered: id=%s, turn=%d", pending_id, self._turn_count)

        # 检查批量触发
        should_flush = await self._check_batch_trigger()
        if should_flush:
            await self._flush_candidate_buffer(user_id)

    async def _flush_candidate_buffer(self, user_id: str) -> int:
        """批量处理候选缓冲区中的 pending 记录。

        Returns:
            处理的记录数。
        """
        pending = await self.stm.query_pending(top_k=50)
        if not pending:
            return 0

        logger.info("Flushing candidate buffer: %d pending", len(pending))
        processed = 0

        for record in pending:
            content = record.get("content", "")
            if not content:
                continue

            # 标记为 processing
            await self.stm.update_pending_status(record["id"], "processing")

            # Layer 2 + Layer 3 判断
            result = await self.write_decision(content, user_id=user_id)

            if result.should_store:
                await self._dispatch_to_stores_from_content(
                    content, result, user_id,
                )
                await self.stm.update_pending_status(record["id"], "written")
            else:
                await self.stm.update_pending_status(record["id"], "discarded")

            processed += 1

        self._last_batch_time = time.time()
        logger.info("Batch flush done: %d processed, %d to stores", processed, processed)
        return processed

    # ── 统一写入决策 ───────────────────────────────────────────

    async def write_decision(
        self,
        content: str,
        *,
        task: Optional[TaskSpec] = None,
        response: str = "",
        metrics: Optional[EvalMetrics] = None,
        user_id: str = "anonymous",
    ) -> WriteDecisionResult:
        """三层写入决策（3.1~3.3）。

        Args:
            content: 候选内容文本。
            task: 原始任务（可选）。
            response: LLM 回复（可选）。
            metrics: 评估指标（可选）。
            user_id: 用户 ID。

        Returns:
            WriteDecisionResult。
        """
        # ── Layer 1: 规则必存 ──
        layer1 = self._layer1_rule_check(content, task, response, metrics or EvalMetrics())
        if layer1.should_store:
            return layer1

        # ── Layer 2: 新颖度过滤 ──
        layer2_pass, entity_key = await self._layer2_novelty_check(content, user_id)
        if not layer2_pass:
            logger.debug("Layer 2 novelty failed for: %s...", content[:60])
            return WriteDecisionResult(
                should_store=False,
                score=0.0,
                layer2_novelty_pass=False,
            )

        # ── Layer 3: 重要性评分 ──
        if metrics is None:
            metrics = EvalMetrics()

        ltm_count = 0
        if self.ltm.store.is_connected:
            rows = await self.ltm.store.query(
                "SELECT COUNT(*) as cnt FROM memories "
                "WHERE type = 'long_term' AND user_id = ?",
                [user_id],
            )
            if rows:
                ltm_count = rows[0].get("cnt", 0)

        importance = self._importance.score(
            content=content,
            task_intent=task.intent.value if task else "",
            task_importance=getattr(metrics, "task_importance", 0.5),
            reward_score=metrics.reward_score,
            ltm_count=ltm_count,
        )

        should_store = importance.overall >= self._importance.pass_threshold
        logger.debug(
            "Layer 3 scored: overall=%.3f, should_store=%s, "
            "identity=%.3f, state=%.3f, task=%.3f, cold_start=%.3f, quality=%.3f",
            importance.overall, should_store,
            importance.identity, importance.state,
            importance.task, importance.cold_start, importance.quality,
        )

        return WriteDecisionResult(
            should_store=should_store,
            score=importance.overall,
            layer1_rule_hit=False,
            layer2_novelty_pass=True,
            layer3_score_detail=importance,
            entity_key=entity_key,
        )

    # ── Layer 1: 规则必存 ─────────────────────────────────────

    def _layer1_rule_check(
        self,
        content: str,
        task: Optional[TaskSpec],
        response: str,
        metrics: EvalMetrics,
    ) -> WriteDecisionResult:
        """Layer 1 规则必存检测。

        检测条件（任一命中即通过）:
            1. 显式记忆指令（"记住"、"记录"、"保存"）
            2. KV 键值对模式（"我叫X"、"我住在Y"）
            3. 任务关键结论（LLM 回复中的结构化数值结论）
        """
        # 条件 1: 显式记忆指令
        if _EXPLICIT_MEMORY_KEYWORDS.search(content):
            entity_key = self._normalize_entity_key(content)
            logger.info("Layer 1: explicit memory command detected")
            return WriteDecisionResult(
                should_store=True,
                score=1.0,
                layer1_rule_hit=True,
                entity_key=entity_key,
            )

        # 条件 2: KV 键值对模式
        kv_pairs = self._extract_kv_pairs(content)
        if kv_pairs:
            entity_key = self._normalize_entity_key(content)
            logger.info("Layer 1: KV pairs detected — %s", kv_pairs)
            return WriteDecisionResult(
                should_store=True,
                score=1.0,
                layer1_rule_hit=True,
                entity_key=entity_key,
                candidates=[kv_pairs],
            )

        # 条件 3: 任务关键结论
        if response and _CONCLUSION_PATTERNS.search(response):
            entity_key = f"task.conclusion.{task.intent.value if task else 'unknown'}"
            logger.info("Layer 1: task conclusion detected")
            return WriteDecisionResult(
                should_store=True,
                score=0.9,
                layer1_rule_hit=True,
                entity_key=entity_key,
            )

        return WriteDecisionResult(should_store=False, score=0.0)

    # ── Layer 2: 新颖度过滤 ───────────────────────────────────

    async def _layer2_novelty_check(
        self,
        content: str,
        user_id: str,
    ) -> tuple[bool, Optional[str]]:
        """Layer 2 新颖度过滤（3.3 包含实体值对比）。

        Args:
            content: 候选内容。
            user_id: 用户 ID。

        Returns:
            (passed, entity_key)
        """
        # 无 embedding provider 时跳过 Layer 2
        if self.ltm._embedding_provider is None:
            logger.debug("Layer 2 skipped: no embedding provider")
            return True, None

        # 获取现有 LTM
        existing = await self.ltm.retrieve(content, top_k=10)
        if not existing:
            # 无现有记忆 → 高新颖 → 通过
            return True, None

        try:
            query_emb = await self.ltm._embedding_provider.embed(content)
        except Exception:
            logger.warning("Layer 2: embedding failed, skipping")
            return True, None

        max_sim = 0.0
        best_match = None
        for item in existing:
            stored_emb = getattr(item, "embedding", None) or item.get("embedding")
            if not stored_emb:
                continue
            sim = self.ltm._cosine_similarity(query_emb, stored_emb)
            if sim > max_sim:
                max_sim = sim
                best_match = item

        logger.debug("Layer 2: max_similarity=%.3f", max_sim)

        # 低于 0.3 → 高新颖 → 通过
        if max_sim < 0.3:
            return True, None

        # 高于 0.9 → 进入实体值对比
        if max_sim > 0.9 and best_match is not None:
            return self._entity_value_compare(content, best_match)

        # 0.3 ~ 0.9 → 正常通过
        return True, None

    def _entity_value_compare(
        self,
        content: str,
        existing: Any,
    ) -> tuple[bool, Optional[str]]:
        """Layer 2 实体值对比（3.3）。

        高相似（>0.9）时，提取候选和已存记忆中的 entity-value 键值对对比:
            - 实体相同但值不同 → 更新（通过）
            - 实体相同且值相同 → 重复（丢弃）
            - 无法提取实体 → 视为重复（丢弃）

        Args:
            content: 候选文本。
            existing: 匹配到的已存记忆（MemoryItem 或 dict）。

        Returns:
            (passed, entity_key)
        """
        existing_content = ""
        if hasattr(existing, "content"):
            existing_content = existing.content
        elif isinstance(existing, dict):
            existing_content = existing.get("content", "")
        else:
            existing_content = str(existing)

        # 提取两边实体-值
        new_kv = self._extract_kv_pairs(content)
        old_kv = self._extract_kv_pairs(existing_content)

        # 规范化 entity_key
        entity_key = self._normalize_entity_key(content) or self._normalize_entity_key(existing_content)

        if not new_kv or not old_kv:
            # 无法提取实体 → 视为重复，丢弃
            logger.debug(
                "Layer 2 entity compare: no entities extracted — treating as duplicate"
            )
            return False, entity_key

        # 对比：检查是否有 key 相同但 value 不同的
        has_update = False
        has_match = False
        for key, new_val in new_kv.items():
            old_val = old_kv.get(key)
            if old_val is not None:
                if old_val != new_val:
                    # 实体相同，值不同 → 更新
                    logger.info(
                        "Layer 2 entity compare: '%s' changed from '%s' to '%s' → UPDATE",
                        key, old_val, new_val,
                    )
                    has_update = True
                else:
                    # 实体相同，值相同 → 重复
                    has_match = True
            else:
                # 新实体 → 通过
                has_update = True

        if has_update:
            return True, entity_key

        if has_match and not has_update:
            logger.debug("Layer 2 entity compare: all entities unchanged → DUPLICATE")
            return False, entity_key

        return False, entity_key

    # ── 分流存储 ───────────────────────────────────────────────

    async def classify_and_route(
        self,
        content: str,
        result: WriteDecisionResult,
        task: Optional[TaskSpec] = None,
    ) -> dict[str, bool]:
        """信息性质分流（3.2）。

        按优先级判断:
            1. 含概念关系信号 → Knowledge
            2. 含经历/反思/流程/工具信号 → Experience
            3. 兜底 → LongTerm

        Args:
            content: 待分流的文本。
            result: write_decision() 的结果。
            task: 原始任务。

        Returns:
            {"knowledge": bool, "experience": bool, "long_term": bool}
        """
        route = {"knowledge": False, "experience": False, "long_term": True}

        # 1. Knowledge 信号
        triple_result = self._triple_extractor.extract(content)
        result.triple_result = triple_result

        if triple_result.should_store_knowledge:
            # 通道 A 命中 → 直接写入 Knowledge
            route["knowledge"] = True
            route["long_term"] = False  # Knowledge 优先
            logger.info(
                "Route → Knowledge (Channel A): %d triples",
                len(triple_result.triples),
            )
            return route

        if triple_result.should_pend_concept:
            # 通道 B 触发 → 暂存 LTM 并标记 concept_pending
            route["knowledge"] = True  # 最终目标是 Knowledge
            route["long_term"] = True  # 但先通过 LTM 暂存
            logger.info(
                "Route → Knowledge (Channel B): concept_pending, score=%.2f",
                triple_result.channel_b_score,
            )
            return route

        # 2. Experience 信号
        exp_signal = self._detect_experience_signal(content, task)
        if exp_signal:
            route["experience"] = True
            logger.info("Route → Experience: signal=%s", exp_signal)
            return route

        # 3. 兜底 → LongTerm
        logger.debug("Route → LongTerm (fallback)")
        return route

    def _detect_experience_signal(
        self,
        content: str,
        task: Optional[TaskSpec] = None,
    ) -> Optional[str]:
        """检测 Experience 信号。

        返回子类型名（episode/reflection/procedure/tool_usage）或 None。
        """
        ct = content.lower()

        # Tool usage signal
        if re.search(r"(?:用|调用|使用|call|use|invoke).{0,10}(?:工具|函数|API|tool|function|api|read_file|write_file|\w+\(\))", ct):
            return "tool_usage"

        # Reflection signal (错误/教训)
        if re.search(r"(?:失败|错误|超时|重试|bug|error|fail|timeout|retry|lesson|教训|原因|root\s*cause)", ct):
            return "reflection"

        # Procedure signal
        if re.search(r"(?:步骤|流程|第一步|第二步|先.*再.*最后|step|procedure|workflow)", ct):
            return "procedure"

        # Episode signal (事件叙述)
        if task and re.search(r"(?:做了|处理了|完成了|executed|processed|handled|完成了)", ct):
            return "episode"

        return None

    async def _dispatch_to_stores(
        self,
        task: TaskSpec,
        response: str,
        metrics: EvalMetrics,
        result: WriteDecisionResult,
        user_id: str,
    ) -> None:
        """Layer 1 命中时的立即分发（跳过候选缓冲）。"""
        content = self._build_candidate_text(task, response, metrics)
        await self._dispatch_to_stores_from_content(content, result, user_id)

    async def _dispatch_to_stores_from_content(
        self,
        content: str,
        result: WriteDecisionResult,
        user_id: str,
    ) -> None:
        """按分流结果写入各持久层。

        Args:
            content: 待存储内容。
            result: write_decision 结果（含 classify_and_route）。
            user_id: 用户 ID。
        """
        route = result.route if hasattr(result, 'route') else None
        if route is None:
            route = await self.classify_and_route(content, result)
            result.route = route

        metadata: dict[str, Any] = {
            "source": "write_decision",
            "score": result.score,
        }
        if result.entity_key:
            metadata["entity_key"] = result.entity_key

        # Knowledge
        if route.get("knowledge") and result.triple_result:
            for triple in result.triple_result.triples:
                try:
                    await self.sem.add_concept(
                        name=triple.subject,
                        attributes={"source": "channel_a"},
                        confidence=triple.confidence,
                    )
                    await self.sem.add_concept(
                        name=triple.obj,
                        attributes={"source": "channel_a"},
                        confidence=triple.confidence,
                    )
                    await self.sem.add_relation(
                        source=triple.subject,
                        target=triple.obj,
                        relation_type=triple.relation,
                        weight=triple.confidence,
                    )
                except Exception as e:
                    logger.debug("Knowledge write failed: %s", e)

        # route["knowledge"] True + concept_pending → 暂存 LTM 并标记
        if route.get("knowledge") and route.get("long_term"):
            metadata["concept_pending"] = True
            await self.ltm.save(
                content=content,
                memory_type="long_term",
                metadata=metadata,
                user_id=user_id,
            )
            if self._concept_worker:
                self._concept_worker.signal()
            return

        # Experience
        if route.get("experience") and self.exp:
            exp_type = self._detect_experience_signal(content)
            if exp_type:
                exp_meta = dict(metadata)
                exp_meta["auto_routed"] = True
                await self._save_to_experience(content, exp_type, exp_meta, user_id)

        # LongTerm (兜底)
        if route.get("long_term"):
            # 检查是否需要更新已有事实（entity_key 去重）
            if result.entity_key:
                existing = await self.ltm.get_fact(result.entity_key, user_id)
                if existing:
                    # 更新已有事实
                    try:
                        # 使用 save_fact 做版本化更新
                        # 构造 metadata
                        ltm_meta = dict(metadata)
                        ltm_meta.update({
                            "fact_id": result.entity_key,
                            "version": (existing.get("metadata", {}).get("version", 1) + 1),
                        })
                        await self.ltm.save_fact(
                            fact_id=result.entity_key,
                            content=content,
                            category="entity_fact",
                            confidence=result.score,
                            source="write_decision",
                            user_id=user_id,
                        )
                        logger.info(
                            "LTM fact updated: entity_key=%s, score=%.3f",
                            result.entity_key, result.score,
                        )
                        return
                    except Exception as e:
                        logger.debug("LTM fact update failed: %s", e)

            await self.ltm.save(
                content=content,
                memory_type="long_term",
                metadata=metadata,
                user_id=user_id,
            )

    async def _save_to_experience(
        self,
        content: str,
        exp_type: str,
        metadata: dict,
        user_id: str,
    ) -> None:
        """将内容写入 Experience 层，按子类型分发。"""
        if not self.exp:
            return
        try:
            if exp_type == "episode":
                await self.exp.record_episode(
                    scene=content[:200],
                    action="auto_routed",
                    result=content[:500],
                    tags=["auto_routed"],
                    user_id=user_id,
                )
            elif exp_type == "reflection":
                await self.exp.record_reflection(
                    task_type="auto_routed",
                    root_cause=content[:200],
                    lesson=content[:500],
                    tags=["auto_routed"],
                )
            elif exp_type == "procedure":
                await self.exp.record_procedure(
                    name=f"auto_{user_id}_{int(time.time())}",
                    steps=[content[:500]],
                    tags=["auto_routed"],
                )
            elif exp_type == "tool_usage":
                await self.exp.record_tool_usage(
                    tool_name="auto_routed",
                    success=True,
                    scenario=content[:200],
                    tags=["auto_routed"],
                )
        except Exception as e:
            logger.debug("Experience write failed (%s): %s", exp_type, e)

    # ── 批量触发检测 ───────────────────────────────────────────

    async def _check_batch_trigger(self) -> bool:
        """检查是否应触发批量写入（3.7）。"""
        # 条件 1: 候选区 ≥ BATCH_SIZE_THRESHOLD 条
        pending_count = await self.stm.get_pending_count()
        if pending_count >= BATCH_SIZE_THRESHOLD:
            logger.info("Batch trigger: pending=%d >= threshold=%d", pending_count, BATCH_SIZE_THRESHOLD)
            return True

        # 条件 2: 对话轮次 ≥ BATCH_TURN_THRESHOLD
        if self._turn_count >= BATCH_TURN_THRESHOLD and pending_count > 0:
            logger.info("Batch trigger: turn=%d >= threshold=%d, pending=%d",
                        self._turn_count, BATCH_TURN_THRESHOLD, pending_count)
            return True

        # 条件 3: 距上次批量写入 > 5 分钟
        elapsed = time.time() - self._last_batch_time
        if elapsed > BATCH_TIMER_SECONDS and pending_count > 0:
            logger.info("Batch trigger: timer=%ds >= threshold=%ds, pending=%d",
                        int(elapsed), BATCH_TIMER_SECONDS, pending_count)
            return True

        return False

    def get_batch_stats(self) -> dict[str, Any]:
        """获取批量写入统计（供入口层使用）。"""
        return {
            "turn_count": self._turn_count,
            "last_batch_time": self._last_batch_time,
            "batch_size_threshold": BATCH_SIZE_THRESHOLD,
            "batch_turn_threshold": BATCH_TURN_THRESHOLD,
            "batch_timer_seconds": BATCH_TIMER_SECONDS,
        }

    # ════════════════════════════════════════════════════════════
    # 辅助方法
    # ════════════════════════════════════════════════════════════

    def _build_candidate_text(
        self,
        task: TaskSpec,
        response: str,
        metrics: EvalMetrics,
    ) -> str:
        """构建候选内容文本（用于写入选评估）。"""
        return f"User: {task.raw_input}\nAssistant: {response[:500]}"

    def _extract_kv_pairs(self, text: str) -> dict[str, str]:
        """从文本中提取 KV 键值对（Layer 1 使用）。"""
        result: dict[str, str] = {}
        for pattern in _KV_PATTERNS:
            for match in pattern.finditer(text):
                entity = match.group("entity").strip(" \"'""'，。；：")
                value = match.group("value").strip(" \"'""'，。；：。")
                if entity and value:
                    # 使用完整文本进行 attribute 推断
                    normalized_key = self._normalize_entity_key(text)
                    if normalized_key:
                        result[normalized_key] = value
        return result

    def _normalize_entity_key(self, text: str) -> Optional[str]:
        """entity_key 归一化（3.8）。

        格式: {实体类型}.{属性}.{标识}

        示例:
            "我叫小明"   → entity_key="user.name"
            "我在北京"   → entity_key="user.location"
            "公司在北京" → entity_key="org.location"

        Args:
            text: 输入文本（实体名或完整文本）。

        Returns:
            归一化的 entity_key，或 None。
        """
        # 先从文本中提取实体名
        entity_str = text
        # 尝试从 KV 模式提取实体部分
        for pattern in _KV_PATTERNS:
            match = pattern.search(text)
            if match:
                entity_str = match.group("entity").strip(" \"'""'，。；：")
                break

        # 属性推断
        attr = "attribute"
        entity_lower = entity_str.lower()
        full_lower = text.lower()

        if re.search(r"(?:叫|名字|name)", full_lower):
            attr = "name"
        elif re.search(r"(?:在|住|住在|location|address|地址)", full_lower):
            attr = "location"
        elif re.search(r"(?:喜欢|偏好|讨厌|prefer|like|hate)", full_lower):
            attr = "preference"
        elif re.search(r"(?:余额|金额|balance|amount)", full_lower):
            attr = "balance"
        elif re.search(r"(?:邮件|邮箱|email)", full_lower):
            attr = "email"
        elif re.search(r"(?:电话|手机|phone|mobile)", full_lower):
            attr = "phone"
        elif re.search(r"(?:角色|职位|role|position|title)", full_lower):
            attr = "role"

        # 实体类型推断
        entity_type = "entity"
        for pattern, etype in _ENTITY_TYPE_PATTERNS:
            if pattern.search(full_lower):
                entity_type = etype
                break

        return f"{entity_type}.{attr}"

    # ── 无门槛层 ───────────────────────────────────────────────

    def _update_working(self, task: TaskSpec, response: str) -> None:
        """更新 Working Memory（每轮自动）。"""
        self.wm.push(
            content=f"User: {task.raw_input}\nAssistant: {response[:500]}",
            metadata={"task_id": task.id, "role": "conversation"},
        )

    async def _update_session(
        self,
        task: TaskSpec,
        response: str,
        user_id: str,
    ) -> None:
        """更新 Session Memory（每轮自动）。"""
        await self.stm.add_task_completion(
            task_name=f"{task.intent.value}: {task.raw_input[:50]}",
            result=response[:200],
            user_id=user_id,
        )

    # ════════════════════════════════════════════════════════════
    # 旧策略（保留，阶段五删除）
    # ════════════════════════════════════════════════════════════

    async def _update_persistent_old(
        self,
        task: TaskSpec,
        response: str,
        metrics: EvalMetrics,
        user_id: str,
    ) -> None:
        """旧策略：各层独立判断写入。"""
        # 长期记忆
        store_ltm = metrics.reward_score >= 0.7
        is_state_update = task.intent.value in ("agent", "coding", "workflow")
        if is_state_update:
            store_ltm = True

        if store_ltm:
            ltm_content = task.raw_input if is_state_update else (
                f"Task: {task.raw_input}\nResolution: {response[:500]}"
            )
            await self.ltm.save(
                content=ltm_content,
                memory_type="long_term",
                metadata={
                    "category": "state_update" if is_state_update else "task_resolution",
                    "intent": task.intent.value,
                    "reward": metrics.reward_score,
                    "task_id": task.id,
                },
                user_id=user_id,
            )

        # 情景记忆
        if metrics.success:
            await self.epm.record_success(
                scene=f"User requested: {task.raw_input[:100]}",
                action=f"Agent responded with {task.intent.value} intent",
                result=response[:200],
                tags=[task.intent.value, "auto_logged"],
            )
        else:
            await self.epm.record_failure(
                scene=f"User requested: {task.raw_input[:100]}",
                action=f"Attempted {task.intent.value}",
                error=response[:200],
                tags=[task.intent.value, "auto_logged"],
            )

        # 语义记忆
        recent_episodes = await self.epm.get_recent_experiences(top_k=20)
        await self.sem.abstract_from_episodes(recent_episodes)

    # ── 用户反馈 ───────────────────────────────────────────────

    async def record_user_feedback(
        self,
        task_id: str,
        user_correction: str,
        user_id: str = "anonymous",
    ) -> None:
        """记录用户的纠正反馈。

        Args:
            task_id: 任务 ID。
            user_correction: 用户的纠正内容。
            user_id: 用户 ID。
        """
        await self.stm.add(
            content=f"User correction for {task_id}: {user_correction}",
            metadata={"category": "correction", "task_id": task_id},
            user_id=user_id,
        )
        logger.info("User feedback recorded: task=%s", task_id)
