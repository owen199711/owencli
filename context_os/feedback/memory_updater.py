"""记忆更新器。

在每次 Pipeline 执行后，根据结果更新各层记忆。
"""

from __future__ import annotations

from typing import Optional

from context_os.core.logger import get_logger
from context_os.core.models import EvalMetrics, TaskSpec
from context_os.memory.episodic import EpisodicMemory
from context_os.memory.long_term import LongTermMemory
from context_os.memory.semantic import SemanticMemory
from context_os.memory.short_term import ShortTermMemory
from context_os.memory.working import WorkingMemory

logger = get_logger(__name__)


class MemoryUpdater:
    """记忆更新器。

    根据任务执行结果，自动更新所有记忆层级。
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        short_term_memory: ShortTermMemory,
        long_term_memory: LongTermMemory,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
    ):
        self.wm = working_memory
        self.stm = short_term_memory
        self.ltm = long_term_memory
        self.epm = episodic_memory
        self.sem = semantic_memory
        logger.info("MemoryUpdater initialized")

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

        # 1. 工作记忆：记录当前轮次
        self.wm.push(
            content=f"User: {task.raw_input}\nAssistant: {response[:500]}",
            metadata={"task_id": task.id, "role": "conversation"},
        )

        # 2. 短期记忆：记录任务完成
        await self.stm.add_task_completion(
            task_name=f"{task.intent.value}: {task.raw_input[:50]}",
            result=response[:200],
            user_id=user_id,
        )

        # 3. 长期记忆：高质量回答 + 状态更新无条件存储
        store_ltm = metrics.reward_score >= 0.7
        # 状态更新类任务（AGENT intent）始终存储原始数据
        is_state_update = task.intent.value in ("agent", "coding", "workflow")
        if is_state_update:
            store_ltm = True  # 无条件存储状态变更数据

        if store_ltm:
            # 状态更新：存原文（不加 "Task:" 包装，便于检索时匹配）
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

        # 4. 情景记忆：记录成功/失败经验
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

        # 5. 语义记忆：从高频模式中抽象
        recent_episodes = await self.epm.get_recent_experiences(top_k=20)
        await self.sem.abstract_from_episodes(recent_episodes)

        logger.info("Memory update complete for task: %s", task.id)

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
        # 短期记忆：记录纠正
        await self.stm.add(
            content=f"User correction for {task_id}: {user_correction}",
            metadata={"category": "correction", "task_id": task_id},
            user_id=user_id,
        )
        logger.info("User feedback recorded: task=%s", task_id)
