"""统一体验记忆（Experience Memory）。

合并原 EpisodicMemory / ReflectionMemory / ProceduralMemory / ToolExperienceMemory
为单一 `experiences` 表，用 `experience_type` 区分子类型。

提供统一的 CRUD、标签检索、场景匹配、实时工具统计聚合。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.memory.tags import validate_tags

logger = get_logger(__name__)


class ExperienceMemory:
    """统一体验记忆 — 合并 4 种子类型。

    子类型:
        - episode:   经历记录（原 EpisodicMemory）
        - reflection: 反思记录（原 ReflectionMemory）
        - procedure:  工作流程（原 ProceduralMemory）
        - tool_usage: 工具使用（原 ToolExperienceMemory）

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("ExperienceMemory initialized (user=%s)", user_id)

    # ── 通用存储 ───────────────────────────────────────────────

    async def save(
        self,
        experience_type: str,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        **kwargs: Any,
    ) -> str:
        """保存一条体验记录（通用入口）。

        根据 experience_type 自动填充对应字段。

        Args:
            experience_type: 'episode' | 'reflection' | 'procedure' | 'tool_usage'.
            tags: 标签列表。
            metadata: 附加元数据。
            **kwargs: 各子类型特有字段。

        Returns:
            记录 ID。
        """
        valid_types = ("episode", "reflection", "procedure", "tool_usage")
        if experience_type not in valid_types:
            raise ValueError(
                f"Invalid experience_type '{experience_type}'. Must be one of {valid_types}"
            )

        exp_id = await self.store.save_experience(
            experience_type=experience_type,
            user_id=kwargs.pop("user_id", self.user_id),
            tags=tags,
            metadata=metadata,
            **kwargs,
        )
        logger.debug("%s saved: id=%s", experience_type, exp_id)
        return exp_id

    async def record(
        self,
        tags: list[str],
        metadata: Optional[dict] = None,
        **kwargs: Any,
    ) -> str:
        """多标签记录（Phase 4）。

        根据 tags 自动推断 experience_type（取第一个核心标签），
        所有标签经过规范化后存储。

        Args:
            tags: 标签列表（支持多标签，如 ["reflection", "tool_usage"]）。
            metadata: 附加元数据。
            **kwargs: 各子类型特有字段。

        Returns:
            记录 ID。
        """
        normalized = validate_tags(tags)
        if not normalized:
            return ""

        # 确定主类型：优先使用核心标签
        exp_type = "episode"  # 默认
        core_order = ("reflection", "tool_usage", "procedure", "episode")
        for ct in core_order:
            if ct in normalized:
                exp_type = ct
                break

        return await self.store.save_experience(
            experience_type=exp_type,
            user_id=kwargs.pop("user_id", self.user_id),
            tags=normalized,
            metadata=metadata,
            **kwargs,
        )

    # ── 子类型便捷方法 ─────────────────────────────────────────

    async def record_episode(
        self,
        scene: str,
        action: str,
        result: str,
        feedback: str = "",
        tags: Optional[list[str]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """记录一条经历（原 EpisodicMemory.record）。"""
        return await self.save(
            experience_type="episode",
            scene=scene,
            action=action,
            result=result,
            feedback=feedback,
            tags=tags,
            user_id=user_id or self.user_id,
        )

    async def record_success(
        self,
        scene: str,
        action: str,
        result: str,
        tags: Optional[list[str]] = None,
    ) -> str:
        """记录成功经验（快捷方法）。"""
        return await self.save(
            experience_type="episode",
            scene=scene,
            action=action,
            result=result,
            feedback="positive",
            tags=(tags or []) + ["success"],
        )

    async def record_failure(
        self,
        scene: str,
        action: str,
        error: str,
        tags: Optional[list[str]] = None,
    ) -> str:
        """记录失败经验（快捷方法）。"""
        return await self.save(
            experience_type="episode",
            scene=scene,
            action=action,
            result=f"Failed: {error}",
            feedback="negative",
            tags=(tags or []) + ["failure"],
        )

    async def record_reflection(
        self,
        task_type: str,
        root_cause: str,
        lesson: str,
        preventive_action: str = "",
        success: bool = True,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """记录一条反思（原 ReflectionMemory）。"""
        full_tags = (tags or []) + ["reflection"]
        if success:
            full_tags.append("success")
        else:
            full_tags.append("failure")
        return await self.save(
            experience_type="reflection",
            task_type=task_type,
            root_cause=root_cause,
            lesson=lesson,
            preventive_action=preventive_action,
            tags=full_tags,
            metadata=metadata,
        )

    async def record_procedure(
        self,
        name: str,
        steps: list[str],
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        total_count: int = 0,
        success_count: int = 0,
        last_used: Optional[str] = None,
    ) -> str:
        """记录或更新一个工作流程（原 ProceduralMemory）。

        Args:
            name: 流程名称。
            steps: 步骤列表。
            description: 流程描述（写入 metadata）。
            tags: 标签。
            total_count: 总执行次数。
            success_count: 成功次数。
            last_used: 最后使用时间（ISO 8601）。
        """
        import json
        return await self.save(
            experience_type="procedure",
            proc_name=name,
            steps_json=json.dumps(steps, ensure_ascii=False),
            total_count=total_count,
            proc_success_count=success_count,
            last_used=last_used or datetime.now(timezone.utc).isoformat(),
            tags=tags,
            metadata={"description": description} if description else None,
        )

    async def record_tool_usage(
        self,
        tool_name: str,
        success: bool,
        error_type: Optional[str] = None,
        duration_ms: int = 0,
        scenario: Optional[str] = None,
        input_preview: Optional[str] = None,
        output_preview: Optional[str] = None,
        tags: Optional[list[str]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """记录一次工具调用（原 ToolExperienceMemory）。

        Args:
            tool_name: 工具名。
            success: 是否成功。
            error_type: 失败时的错误类型。
            duration_ms: 耗时（毫秒）。
            scenario: 调用场景。
            input_preview: 输入预览。
            output_preview: 输出预览。
            tags: 标签。
            user_id: 用户 ID。
        """
        return await self.save(
            experience_type="tool_usage",
            tool_name=tool_name,
            tool_success=1 if success else 0,
            error_type=error_type,
            duration_ms=duration_ms,
            scenario=scenario,
            input_preview=input_preview,
            output_preview=output_preview,
            tags=tags,
            user_id=user_id or self.user_id,
        )

    # ── 检索 ───────────────────────────────────────────────────

    async def recall_by_tag(
        self,
        tag: str,
        experience_type: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """按标签检索体验记录。

        Args:
            tag: 标签名。
            experience_type: 可选，限定子类型。
            top_k: 返回上限。

        Returns:
            体验记录字典列表。
        """
        results = await self.store.query_experiences(
            experience_type=experience_type,
            user_id=self.user_id,
            tags=[tag],
            top_k=top_k,
        )
        logger.debug("Recall by tag '%s': %d results", tag, len(results))
        return results

    async def recall_relevant(
        self,
        experience_type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        scenario_query: Optional[str] = None,
        top_k: int = 20,
        created_after: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """多条件检索体验记录。

        Args:
            experience_type: 按子类型筛选。
            tags: 按标签筛选（OR 匹配）。
            scenario_query: 按场景关键词模糊匹配。
            top_k: 返回上限。
            created_after: 只返回此时间之后的记录（ISO 8601）。

        Returns:
            体验记录字典列表。
        """
        results = await self.store.query_experiences(
            experience_type=experience_type,
            user_id=self.user_id,
            tags=tags,
            scenario_query=scenario_query,
            top_k=top_k,
            created_after=created_after,
        )
        logger.info(
            "Recall relevant: type=%s, tags=%s, scenario='%s', results=%d",
            experience_type, tags, scenario_query or "none", len(results),
        )
        return results

    async def recall_similar(
        self,
        scene_query: str,
        top_k: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """检索相似场景的 episode 记录（兼容旧 EpisodicMemory 接口）。

        Args:
            scene_query: 场景查询文本。
            top_k: 返回上限。
            tags: 按标签筛选。

        Returns:
            体验记录字典列表。
        """
        results = await self.store.query_experiences(
            experience_type="episode",
            user_id=self.user_id,
            tags=tags,
            scene_query=scene_query,
            top_k=top_k,
        )
        logger.debug(
            "Episode recall: query='%s...', tags=%s, results=%d",
            scene_query[:50], tags, len(results),
        )
        return results

    async def get_recent_experiences(
        self,
        top_k: int = 10,
        experience_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取最近的体验记录（兼容旧 EpisodicMemory.get_recent_experiences）。

        Args:
            top_k: 返回上限。
            experience_type: 可选，限定子类型。

        Returns:
            体验记录字典列表。
        """
        results = await self.store.query_experiences(
            experience_type=experience_type,
            user_id=self.user_id,
            top_k=top_k,
        )
        logger.debug("Recent experiences: %d results", len(results))
        return results

    # ── 统计 ───────────────────────────────────────────────────

    async def get_stats(
        self,
        experience_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取体验统计摘要。

        Args:
            experience_type: 可选，按子类型筛选。

        Returns:
            {
                "total_count": int,
                "by_type": {"episode": n, "reflection": n, ...},
                "tool_stats": [...] (仅 tool_usage 有数据)
            }
        """
        if not self.store.is_connected:
            return {"total_count": 0, "by_type": {}, "tool_stats": []}

        # 按类型计数
        type_sql = (
            "SELECT experience_type, COUNT(*) as cnt "
            "FROM experiences WHERE user_id = ? "
            + ("AND experience_type = ?" if experience_type else "")
            + " GROUP BY experience_type"
        )
        type_params: list[Any] = [self.user_id]
        if experience_type:
            type_params.append(experience_type)

        type_rows = await self.store.query(type_sql, type_params)
        by_type = {r["experience_type"]: r["cnt"] for r in type_rows}
        total = sum(by_type.values())

        # 工具统计
        tool_stats = await self.store.get_tool_stats(user_id=self.user_id)

        logger.debug(
            "Experience stats: total=%d, by_type=%s, tools=%d",
            total, by_type, len(tool_stats),
        )
        return {
            "total_count": total,
            "by_type": by_type,
            "tool_stats": tool_stats,
        }

    async def get_latest_tool_stats(
        self,
        tool_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """实时获取工具使用成功率统计。

        Args:
            tool_name: 可选，按工具名筛选。

        Returns:
            [{tool_name, user_id, total_calls, success_calls, avg_duration_ms, last_used}, ...]
        """
        results = await self.store.get_tool_stats(
            user_id=self.user_id,
            tool_name=tool_name,
        )
        logger.debug("Tool stats for '%s': %d tools", tool_name or "all", len(results))
        return results

    # ── 更新反馈 ───────────────────────────────────────────────

    async def update_feedback(self, episode_id: str, feedback: str) -> bool:
        """更新某条 episode 的用户反馈（兼容旧 EpisodicMemory 接口）。

        Args:
            episode_id: 体验记录 ID。
            feedback: 新的反馈内容。

        Returns:
            是否更新成功。
        """
        if not self.store.is_connected:
            return False

        cursor = await self.store.execute(
            "UPDATE experiences SET feedback = ?, updated_at = ? WHERE id = ?",
            [feedback, datetime.now(timezone.utc).isoformat(), episode_id],
        )
        success = cursor.rowcount > 0
        if success:
            logger.debug("Experience feedback updated: id=%s", episode_id)
        return success
