"""MemoryRouter — 记忆分流路由器。

从 MemoryUpdater 中独立出来，负责：
1. route(): 检测内容特征 → 决定写入目标（Knowledge / Experience / LongTerm）
2. dispatch(): 执行实际的持久化写入
3. _detect_experience_signals(): Experience 多标签检测
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from context_os.core.logger import get_logger
from context_os.feedback.triple_extractor import TripleExtractor, TripleExtractResult, _is_valid_concept

if TYPE_CHECKING:
    from context_os.events.bus import EventBus
    from context_os.feedback.write_decision import WriteDecisionResult
    from context_os.memory.experience import ExperienceMemory
    from context_os.memory.long_term import LongTermMemory
    from context_os.memory.semantic import SemanticMemory
    from context_os.core.models import TaskSpec

logger = get_logger(__name__)


@dataclass
class RouteResult:
    """route() 的返回结果。"""

    target: str  # "long_term" | "experience" | "knowledge"
    tags: list[str] = field(default_factory=list)
    entity_key: str = ""
    category: str = ""  # "fact" | "summary"（LongTerm）
    route_detail: dict[str, bool] = field(default_factory=dict)


class MemoryRouter:
    """记忆分流路由器（Phase 3）。

    职责:
    1. classify_and_route(): 判定内容应存入哪个持久层
    2. dispatch(): 执行实际写入操作

    使用方式:
        router = MemoryRouter(event_bus=bus)
        route_result = await router.route(content, journal_id, user_id,
                                          ltm=ltm, exp=exp, sem=sem)
    """

    def __init__(
        self,
        event_bus: Optional["EventBus"] = None,
        triple_extractor: Optional[TripleExtractor] = None,
        knowledge_queue: Optional[Any] = None,
        concept_worker: Optional[Any] = None,
    ) -> None:
        self._event_bus = event_bus
        self._triple_extractor = triple_extractor or TripleExtractor()
        self._knowledge_queue = knowledge_queue
        self._concept_worker = concept_worker

    async def route(
        self,
        content: str,
        journal_id: str,
        user_id: str,
        task: Optional["TaskSpec"] = None,
    ) -> tuple[RouteResult, Optional[TripleExtractResult]]:
        """信息性质分流。

        按优先级判断:
            1. 含概念关系信号 → Knowledge
            2. 含经历/反思/流程/工具信号 → Experience
            3. 兜底 → LongTerm

        Args:
            content: 待分流的文本。
            journal_id: 关联 Journal 记录 ID。
            user_id: 用户 ID。
            task: 原始任务。

        Returns:
            (RouteResult, optional TripleExtractResult)
        """
        # 1. Knowledge 信号 — 只从用户输入提取三元组
        extract_text = self._extract_user_input_from_content(content, task)
        triple_result = self._triple_extractor.extract(extract_text)

        if triple_result.should_store_knowledge:
            # Channel A 命中 → 直接写入 Knowledge
            logger.info(
                "Route → Knowledge (Channel A): %d triples",
                len(triple_result.triples),
            )
            return RouteResult(
                target="knowledge",
                route_detail={"knowledge": True, "experience": False, "long_term": False},
            ), triple_result

        if triple_result.should_pend_concept:
            # Channel B 触发 → 暂存 LTM 并标记 concept_pending
            logger.info(
                "Route → Knowledge (Channel B): concept_pending, score=%.2f",
                triple_result.channel_b_score,
            )
            return RouteResult(
                target="knowledge",
                route_detail={"knowledge": True, "experience": False, "long_term": True},
            ), triple_result

        # 2. Experience 信号（多标签）
        exp_tags = self._detect_experience_signals(content, task)
        if exp_tags:
            logger.info("Route → Experience: tags=%s", exp_tags)
            return RouteResult(
                target="experience",
                tags=exp_tags,
                route_detail={"knowledge": False, "experience": True, "long_term": False},
            ), triple_result

        # 3. 兜底 → LongTerm
        entity_key = self._extract_entity_key(content)
        logger.debug("Route → LongTerm (fallback), entity_key=%s", entity_key)
        return RouteResult(
            target="long_term",
            entity_key=entity_key,
            category="fact" if entity_key else "summary",
            route_detail={"knowledge": False, "experience": False, "long_term": True},
        ), triple_result

    async def dispatch(
        self,
        route_result: RouteResult,
        triple_result: Optional[TripleExtractResult],
        content: str,
        journal_id: str,
        user_id: str,
        ltm: "LongTermMemory",
        sem: Optional["SemanticMemory"] = None,
        exp: Optional["ExperienceMemory"] = None,
        score: float = 0.0,
    ) -> None:
        """执行写入。

        Args:
            route_result: 路由结果。
            triple_result: 三元组提取结果（可选）。
            content: 待写入内容。
            journal_id: Journal 记录 ID。
            user_id: 用户 ID。
            ltm: LongTermMemory 实例。
            sem: SemanticMemory 实例。
            exp: ExperienceMemory 实例。
            score: 写入决策分数。
        """
        metadata: dict[str, Any] = {
            "source": "write_decision",
            "score": score,
        }
        if route_result.entity_key:
            metadata["entity_key"] = route_result.entity_key

        route = route_result.route_detail

        # Knowledge (Channel A: 直接写入)
        if route.get("knowledge") and triple_result and triple_result.should_store_knowledge:
            if sem:
                for triple in triple_result.triples:
                    if not _is_valid_concept(triple.subject) or not _is_valid_concept(triple.obj):
                        continue
                    if triple.subject == triple.obj:
                        continue
                    try:
                        await sem.add_concept(
                            name=triple.subject,
                            attributes={"source": "channel_a"},
                            confidence=triple.confidence,
                        )
                        await sem.add_concept(
                            name=triple.obj,
                            attributes={"source": "channel_a"},
                            confidence=triple.confidence,
                        )
                        await sem.add_relation(
                            source=triple.subject,
                            target=triple.obj,
                            relation_type=triple.relation,
                            weight=triple.confidence,
                        )
                    except Exception as e:
                        logger.debug("Knowledge write failed: %s", e)

        # Knowledge (Channel B: 暂存 LTM → enqueue)
        if route.get("knowledge") and route.get("long_term"):
            metadata["concept_pending"] = True
            await ltm.save(
                content=content,
                memory_type="long_term",
                metadata=metadata,
                user_id=user_id,
            )
            if self._knowledge_queue:
                await self._knowledge_queue.enqueue(
                    content=content, user_id=user_id, source="channel_b",
                )
            elif self._concept_worker:
                self._concept_worker.signal()
            return

        # Experience
        if route.get("experience") and exp:
            await self._save_to_experience(
                content, route_result.tags, metadata, user_id, exp,
            )

        # LongTerm (兜底)
        if route.get("long_term"):
            if route_result.entity_key:
                # Fact 路径：有 entity_key → 版本化存储
                await ltm.save_fact(
                    fact_id=route_result.entity_key,
                    content=content,
                    category="entity_fact",
                    confidence=score,
                    source="write_decision",
                    user_id=user_id,
                )
                logger.info(
                    "LTM Fact saved: entity_key=%s, score=%.3f",
                    route_result.entity_key, score,
                )
            else:
                # Summary 路径：无 entity_key → embedding 去重存储
                summary_id = await ltm.save_summary(
                    content=content,
                    category="summary",
                    confidence=score,
                    source="write_decision",
                    user_id=user_id,
                )
                if summary_id:
                    logger.info("LTM Summary saved: id=%s, score=%.3f", summary_id, score)
                else:
                    logger.debug("LTM Summary deduplicated, skipped")

    # ── Experience 信号检测（多标签）──

    def _detect_experience_signals(
        self,
        content: str,
        task: Optional["TaskSpec"] = None,
    ) -> list[str]:
        """检测 Experience 信号，返回多标签列表。

        Returns:
            标签列表，如 ["episode", "reflection"]；无信号返回空列表。
        """
        ct = content.lower()
        tags: list[str] = []

        # Tool usage signal
        if re.search(r"(?:用|调用|使用|call|use|invoke).{0,10}(?:工具|函数|API|tool|function|api|read_file|write_file|\w+\(\))", ct):
            tags.append("tool_usage")

        # Reflection signal
        if re.search(r"(?:失败|错误|超时|重试|bug|error|fail|timeout|retry|lesson|教训|原因|root\s*cause)", ct):
            tags.append("reflection")

        # Procedure signal
        if re.search(r"(?:步骤|流程|第一步|第二步|先.*再.*最后|step|procedure|workflow)", ct):
            tags.append("procedure")

        # Episode signal
        if task and re.search(r"(?:做了|处理了|完成了|executed|processed|handled|完成了)", ct):
            tags.append("episode")

        return tags

    # ── entity_key 提取 ──

    @staticmethod
    def _extract_entity_key(content: str) -> Optional[str]:
        """从内容提取 entity_key（简化版，完整版在 WriteDecision 中）。"""
        # 尝试从 User: 部分提取
        is_pattern = re.compile(
            r"(?:是|叫|叫做|住在|喜欢|偏好|讨厌|在|住|is|likes?|prefers?|hates?|live\s+in)"
        )
        if is_pattern.search(content[:200]):
            return "user.attribute"
        return None

    # ── Experience 写入 ──

    async def _save_to_experience(
        self,
        content: str,
        tags: list[str],
        metadata: dict,
        user_id: str,
        exp: "ExperienceMemory",
    ) -> None:
        """将内容写入 Experience 层，按标签分发。"""
        try:
            for tag in tags:
                if tag == "episode":
                    await exp.record_episode(
                        scene=content[:200],
                        action="auto_routed",
                        result=content[:500],
                        tags=["auto_routed"],
                        user_id=user_id,
                    )
                elif tag == "reflection":
                    await exp.record_reflection(
                        task_type="auto_routed",
                        root_cause=content[:200],
                        lesson=content[:500],
                        tags=["auto_routed"],
                    )
                elif tag == "procedure":
                    await exp.record_procedure(
                        name=f"auto_{user_id}_{int(time.time())}",
                        steps=[content[:500]],
                        tags=["auto_routed"],
                    )
                elif tag == "tool_usage":
                    await exp.record_tool_usage(
                        tool_name="auto_routed",
                        success=True,
                        scenario=content[:200],
                        tags=["auto_routed"],
                    )
        except Exception as e:
            logger.debug("Experience write failed (%s): %s", tags, e)

    # ── 用户输入提取 ──

    @staticmethod
    def _extract_user_input_from_content(
        content: str,
        task: Optional["TaskSpec"] = None,
    ) -> str:
        """从候选内容文本中提取用户输入部分。"""
        if task and task.raw_input:
            return task.raw_input

        assistant_idx = content.find("\nAssistant:")
        if assistant_idx >= 0:
            user_part = content[:assistant_idx]
        else:
            user_part = content

        if user_part.startswith("User: "):
            user_part = user_part[6:]

        return user_part.strip()
