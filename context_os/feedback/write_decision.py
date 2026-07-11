"""WriteDecision — 三层写入决策闸门。

从 MemoryUpdater 中独立出来，可单元测试。
Layer 1: 规则必存 → Layer 2: 新颖度过滤 → Layer 3: 重要性评分
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger
from context_os.core.models import EvalMetrics, TaskSpec
from context_os.feedback.memory_importance import ImportanceScorer, ImportanceScore

if TYPE_CHECKING:
    from context_os.events.bus import EventBus
    from context_os.memory.long_term import LongTermMemory

logger = get_logger(__name__)

# ── Layer 1 常量 ──────────────────────────────────────────────

_EXPLICIT_MEMORY_KEYWORDS = re.compile(
    r"记住|记录|设置为|保存|不要忘记|务必记住|务必|"
    r"remember|save|set\s+to|don'?t\s+forget|keep\s+in\s+mind",
    re.IGNORECASE,
)

_KV_PATTERNS = [
    re.compile(r"(?P<entity>.{1,20}?)(?:是|住在|叫|叫做|在|住|喜欢|偏好|讨厌|的)(?P<value>.{1,40}?)(?:[，。,.]|$)"),
    re.compile(r"(?P<entity>.{1,20}?)\s*(?:is\s+called|is|live\s+in|likes?|prefers?|hates?)\s+(?P<value>.{1,40}?)(?:[.,]|$)"),
]

_CONCLUSION_PATTERNS = re.compile(
    r"(?:余额为|总额为|结果为|总计为|余额|总计|合计|最终)"
    r"[\s\d.,]+(?:元|个|人|次|万)",
    re.IGNORECASE,
)

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
    # Phase 3.2 路由信息（由 MemoryRouter 填充）
    route: Optional[dict[str, bool]] = None
    triple_result: Optional[Any] = None


class WriteDecision:
    """三层写入决策闸门。

    从 MemoryUpdater 中独立，可独立测试。

    使用方式:
        decision = WriteDecision(ltm=ltm, scorer=scorer, event_bus=bus)
        result = await decision.decide(content, user_id, task_intent="qa")
    """

    def __init__(
        self,
        ltm: "LongTermMemory",
        scorer: Optional[ImportanceScorer] = None,
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self._ltm = ltm
        self._scorer = scorer or ImportanceScorer()
        self._event_bus = event_bus

    async def decide(
        self,
        content: str,
        user_id: str = "anonymous",
        task_intent: str = "",
        task: Optional[TaskSpec] = None,
        response: str = "",
        metrics: Optional[EvalMetrics] = None,
        turn_count: int = 0,
    ) -> WriteDecisionResult:
        """三层写入决策（Layer 1 → Layer 2 → Layer 3）。

        Args:
            content: 候选内容文本。
            user_id: 用户 ID。
            task_intent: 任务意图字符串。
            task: 原始任务。
            response: LLM 回复。
            metrics: 评估指标。
            turn_count: 对话轮次。

        Returns:
            WriteDecisionResult。
        """
        # ── Layer 1: 规则必存 ──
        layer1 = self._layer1_rule_check(
            content, task, response, metrics or EvalMetrics(),
        )
        if layer1.should_store:
            return layer1

        # ── Layer 2: 新颖度过滤 ──
        layer2_pass, entity_key = await self._layer2_novelty_check(content, user_id)
        if not layer2_pass:
            logger.debug("Layer 2 novelty failed for: %s...", content[:60])
            return WriteDecisionResult(
                should_store=False, score=0.0, layer2_novelty_pass=False,
            )

        # ── Layer 3: 重要性评分 ──
        score = self._layer3_importance_score(
            content=content, user_id=user_id, task_intent=task_intent,
            metrics=metrics or EvalMetrics(),
        )
        should_store = score.overall >= self._scorer.pass_threshold

        logger.debug(
            "Layer 3 scored: overall=%.3f, should_store=%s, "
            "identity=%.3f, state=%.3f, task=%.3f, cold_start=%.3f, quality=%.3f",
            score.overall, should_store,
            score.identity, score.state,
            score.task, score.cold_start, score.quality,
        )

        return WriteDecisionResult(
            should_store=should_store,
            score=score.overall,
            layer1_rule_hit=False,
            layer2_novelty_pass=True,
            layer3_score_detail=score,
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
                should_store=True, score=1.0, layer1_rule_hit=True,
                entity_key=entity_key,
            )

        # 条件 2: KV 键值对模式
        kv_pairs = self._extract_kv_pairs(content)
        if kv_pairs:
            entity_key = self._normalize_entity_key(content)
            logger.info("Layer 1: KV pairs detected — %s", kv_pairs)
            return WriteDecisionResult(
                should_store=True, score=1.0, layer1_rule_hit=True,
                entity_key=entity_key, candidates=[kv_pairs],
            )

        # 条件 3: 任务关键结论
        if response and _CONCLUSION_PATTERNS.search(response):
            entity_key = f"task.conclusion.{task.intent.value if task else 'unknown'}"
            logger.info("Layer 1: task conclusion detected")
            return WriteDecisionResult(
                should_store=True, score=0.9, layer1_rule_hit=True,
                entity_key=entity_key,
            )

        return WriteDecisionResult(should_store=False, score=0.0)

    # ── Layer 2: 新颖度过滤 ───────────────────────────────────

    async def _layer2_novelty_check(
        self,
        content: str,
        user_id: str,
    ) -> tuple[bool, Optional[str]]:
        """Layer 2 新颖度过滤（含实体值对比）。

        Args:
            content: 候选内容。
            user_id: 用户 ID。

        Returns:
            (passed, entity_key)
        """
        # 无 embedding provider 时跳过 Layer 2
        if self._ltm._embedding_provider is None:
            logger.debug("Layer 2 skipped: no embedding provider")
            return True, None

        existing = await self._ltm.retrieve(content, top_k=10)
        if not existing:
            return True, None

        try:
            query_emb = await self._ltm._embedding_provider.embed(content)
        except Exception:
            logger.warning("Layer 2: embedding failed, skipping")
            return True, None

        max_sim = 0.0
        best_match = None
        for item in existing:
            stored_emb = getattr(item, "embedding", None) or item.get("embedding")
            if not stored_emb:
                continue
            sim = self._ltm._cosine_similarity(query_emb, stored_emb)
            if sim > max_sim:
                max_sim = sim
                best_match = item

        logger.debug("Layer 2: max_similarity=%.3f", max_sim)

        if max_sim < 0.3:
            return True, None

        if max_sim > 0.9 and best_match is not None:
            return self._entity_value_compare(content, best_match)

        return True, None

    def _entity_value_compare(
        self,
        content: str,
        existing: Any,
    ) -> tuple[bool, Optional[str]]:
        """Layer 2 实体值对比。

        高相似（>0.9）时，提取候选和已存记忆中的 entity-value 键值对对比。
        """
        existing_content = ""
        if hasattr(existing, "content"):
            existing_content = existing.content
        elif isinstance(existing, dict):
            existing_content = existing.get("content", "")
        else:
            existing_content = str(existing)

        new_kv = self._extract_kv_pairs(content)
        old_kv = self._extract_kv_pairs(existing_content)

        entity_key = (
            self._normalize_entity_key(content)
            or self._normalize_entity_key(existing_content)
        )

        if not new_kv or not old_kv:
            logger.debug("Layer 2 entity compare: no entities — treating as duplicate")
            return False, entity_key

        has_update = False
        has_match = False
        for key, new_val in new_kv.items():
            old_val = old_kv.get(key)
            if old_val is not None:
                if old_val != new_val:
                    logger.info(
                        "Layer 2 entity compare: '%s' changed from '%s' to '%s' → UPDATE",
                        key, old_val, new_val,
                    )
                    has_update = True
                else:
                    has_match = True
            else:
                has_update = True

        if has_update:
            return True, entity_key

        if has_match and not has_update:
            logger.debug("Layer 2 entity compare: all entities unchanged → DUPLICATE")
            return False, entity_key

        return False, entity_key

    # ── Layer 3: 重要性评分 ───────────────────────────────────

    def _layer3_importance_score(
        self,
        content: str,
        user_id: str,
        task_intent: str,
        metrics: EvalMetrics,
    ) -> ImportanceScore:
        """Layer 3 重要性评分（委托给 ImportanceScorer）。"""
        return self._scorer.score(
            content=content,
            task_intent=task_intent,
            task_importance=getattr(metrics, "task_importance", 0.5),
            reward_score=metrics.reward_score,
            ltm_count=0,  # 调用方传入
        )

    # ── 实体提取辅助 ──────────────────────────────────────────

    def _extract_kv_pairs(self, text: str) -> dict[str, str]:
        """从文本中提取 KV 键值对。"""
        result: dict[str, str] = {}
        for pattern in _KV_PATTERNS:
            for match in pattern.finditer(text):
                entity = match.group("entity").strip(" \"'""'，。；：")
                value = match.group("value").strip(" \"'""'，。；：。")
                if entity and value:
                    normalized_key = self._normalize_entity_key(text)
                    if normalized_key:
                        result[normalized_key] = value
        return result

    def _normalize_entity_key(self, text: str) -> Optional[str]:
        """entity_key 归一化。

        格式: {实体类型}.{属性}

        示例:
            "我叫小明"   → entity_key="user.name"
            "我在北京"   → entity_key="user.location"
        """
        entity_str = text
        for pattern in _KV_PATTERNS:
            match = pattern.search(text)
            if match:
                entity_str = match.group("entity").strip(" \"'""'，。；：")
                break

        attr = "attribute"
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

        entity_type = "entity"
        for pattern, etype in _ENTITY_TYPE_PATTERNS:
            if pattern.search(full_lower):
                entity_type = etype
                break

        return f"{entity_type}.{attr}"
