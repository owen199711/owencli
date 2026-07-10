"""情景记忆（Episodic Memory）。

Agent 对过去经历的"故事化"记录，记录了在什么场景下发生了什么、结果如何。
这些记录帮助 Agent:
    - 避免重复犯同样的错误
    - 从过去的成功经验中快速找到解决方案
    - 根据历史用户反馈调整行为
"""

from __future__ import annotations

from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)


class EpisodicMemory:
    """情景记忆 — 过去经历的记录。

    Args:
        store: PostgreSQL 存储层实例。
        user_id: 默认用户 ID。
    """

    def __init__(self, store: SQLiteStore, user_id: str = "anonymous"):
        self.store = store
        self.user_id = user_id
        logger.info("EpisodicMemory initialized")

    async def record(
        self,
        scene: str,
        action: str,
        result: str,
        feedback: str = "",
        related_files: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """记录一条情景记忆。

        记录完整的"场景-行动-结果"链。

        Args:
            scene: 场景描述（什么情况下发生的）。
            action: 采取的行动（Agent 做了什么）。
            result: 结果（成功/失败/效果如何）。
            feedback: 用户反馈（如果有的话）。
            related_files: 关联的文件路径列表。
            tags: 标签，便于后续检索。
            user_id: 用户 ID。

        Returns:
            情景记忆 ID。
        """
        ep_id = await self.store.save_episode(
            scene=scene,
            action=action,
            result=result,
            feedback=feedback,
            related_files=related_files,
            tags=tags,
            user_id=user_id or self.user_id,
        )
        logger.debug(
            "Episode recorded: id=%s, scene='%s', feedback=%s, tags=%s",
            ep_id, scene[:60], feedback or "none", tags,
        )
        return ep_id

    async def record_success(
        self,
        scene: str,
        action: str,
        result: str,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> str:
        """快捷方法：记录成功经验。

        Args:
            scene: 场景描述。
            action: 采取的行动。
            result: 成功的具体效果。
            tags: 标签。
            related_files: 关联文件。

        Returns:
            情景记忆 ID。
        """
        return await self.record(
            scene=scene,
            action=action,
            result=result,
            feedback="positive",
            tags=(tags or []) + ["success"],
            related_files=related_files,
        )

    async def record_failure(
        self,
        scene: str,
        action: str,
        error: str,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> str:
        """快捷方法：记录失败经验。

        Args:
            scene: 场景描述。
            action: 尝试的行动。
            error: 错误详情。
            tags: 标签。
            related_files: 关联文件。

        Returns:
            情景记忆 ID。
        """
        return await self.record(
            scene=scene,
            action=action,
            result=f"Failed: {error}",
            feedback="negative",
            tags=(tags or []) + ["failure"],
            related_files=related_files,
        )

    async def recall_similar(
        self,
        scene_query: str,
        top_k: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """检索相似场景的情景记忆。

        支持按标签筛选和关键词匹配。

        Args:
            scene_query: 场景查询文本。
            top_k: 返回上限。
            tags: 按标签筛选。

        Returns:
            情景记忆字典列表。
        """
        results = await self.store.query_episodes(
            tags=tags,
            user_id=self.user_id,
            top_k=top_k,
        )
        logger.debug(
            "Episode recall: query='%s...', tags=%s, results=%d",
            scene_query[:50], tags, len(results),
        )
        return results

    async def recall_by_tag(self, tag: str, top_k: int = 10) -> list[dict[str, Any]]:
        """按标签检索情景记忆。

        Args:
            tag: 标签名。
            top_k: 返回上限。

        Returns:
            情景记忆字典列表。
        """
        return await self.store.query_episodes(
            tags=[tag],
            user_id=self.user_id,
            top_k=top_k,
        )

    async def get_recent_experiences(self, top_k: int = 10) -> list[dict[str, Any]]:
        """获取最近的经历记录。

        Args:
            top_k: 返回上限。

        Returns:
            情景记忆字典列表。
        """
        results = await self.store.query_episodes(
            user_id=self.user_id,
            top_k=top_k,
        )
        logger.debug("Recent experiences: %d results", len(results))
        return results

    async def update_feedback(self, episode_id: str, feedback: str) -> bool:
        """更新某条情景记忆的用户反馈。

        例如用户后续对 Agent 的纠正，需要更新到原记录中。

        Args:
            episode_id: 情景记忆 ID。
            feedback: 新的反馈内容。

        Returns:
            是否更新成功。
        """
        if not self.store.is_connected:
            return False

        cursor = await self.store.execute(
            "UPDATE episodes SET feedback = ? WHERE id = ?",
            [feedback, episode_id],
        )
        success = cursor.rowcount > 0
        if success:
            logger.debug("Episode feedback updated: id=%s", episode_id)
        return success
