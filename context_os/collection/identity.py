"""Identity Collector - 用户身份信息收集器。

从注入的 UserProfile 或环境变量中读取用户身份信息。
包括用户角色、权限、语言偏好、技能等级等。

每个 Collector 都继承 BaseCollector，采用统一的 collect() 接口。
"""

from __future__ import annotations

import os
from typing import Optional

from context_os.core.base import BaseCollector
from context_os.core.logger import get_logger
from context_os.core.models import UserProfile

logger = get_logger(__name__)


class IdentityCollector(BaseCollector):
    """用户身份信息收集器。

    收集策略:
        1. 优先使用构造时注入的 UserProfile（允许外部注入测试数据或手动配置）。
        2. 如果没有注入，从环境变量读取默认值。

    Args:
        user_profile: 可选的用户画像，不传则从环境变量读取。
    """

    # 环境变量到 UserProfile 字段的映射
    _ENV_MAPPING: dict[str, str] = {
        "USER_ID": "user_id",
        "USER_ROLE": "role",
        "USER_PERMISSION": "permission",
        "USER_LANGUAGE": "language",
        "USER_SKILL_LEVEL": "skill_level",
        "ORG_NAME": "organization",
        "TENANT_ID": "tenant",
        "TEAM_NAME": "team",
    }

    def __init__(self, user_profile: Optional[UserProfile] = None):
        self.user_profile = user_profile
        if user_profile:
            logger.info(
                "IdentityCollector initialized with injected profile: user_id=%s, role=%s",
                user_profile.user_id,
                user_profile.role,
            )
        else:
            logger.info("IdentityCollector initialized (will read from env)")

    async def collect(self) -> UserProfile:
        """收集用户身份信息。

        Returns:
            填充了身份信息的 UserProfile 对象。
        """
        logger.debug("Collecting identity context...")

        if self.user_profile:
            logger.info("Using injected user profile")
            return self.user_profile

        # 从环境变量读取
        logger.debug("Reading identity from environment variables")
        profile = UserProfile(
            user_id=os.getenv("USER_ID", "anonymous"),
            role=os.getenv("USER_ROLE", "developer"),
            permission=os.getenv("USER_PERMISSION", "readonly"),
            language=os.getenv("USER_LANGUAGE", "zh-CN"),
            skill_level=os.getenv("USER_SKILL_LEVEL", "intermediate"),
            organization=os.getenv("ORG_NAME"),
            tenant=os.getenv("TENANT_ID"),
            team=os.getenv("TEAM_NAME"),
        )

        logger.info(
            "Identity collected: user_id=%s, role=%s, language=%s",
            profile.user_id,
            profile.role,
            profile.language,
        )
        return profile
