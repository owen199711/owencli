"""Environment Collector - 系统环境信息收集器。

收集 Agent 运行时的环境上下文，包括：
    - 操作系统类型
    - 当前工作目录
    - Git 分支和仓库信息
    - 运行时环境（Python 版本、CPU 架构等）
    - MCP 服务器配置
    - 关键环境变量

这些信息帮助 LLM 理解运行环境，在编码和调试任务中尤为重要。
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

from context_os.core.base import BaseCollector
from context_os.core.logger import get_logger
from context_os.core.models import EnvironmentContext

logger = get_logger(__name__)


class EnvironmentCollector(BaseCollector):
    """系统环境信息收集器。

    每次 collect() 调用时实时采集当前系统状态。

    Args:
        mcp_servers: 预配置的 MCP 服务器地址映射（名称 → URL）。
    """

    def __init__(self, mcp_servers: Optional[dict[str, str]] = None):
        self.mcp_servers = mcp_servers or {}
        logger.info(
            "EnvironmentCollector initialized (mcp_servers=%d)",
            len(self.mcp_servers),
        )

    async def collect(self) -> EnvironmentContext:
        """收集当前系统环境信息。

        执行流程:
            1. 检测操作系统和运行时。
            2. 获取工作目录。
            3. 尝试获取 Git 信息（静默失败，不阻断流程）。
            4. 收集关键环境变量。
            5. 注入预配置的 MCP 服务器。

        Returns:
            EnvironmentContext 对象。
        """
        logger.debug("Collecting environment context...")

        # Step 1: 操作系统和运行时
        os_name = platform.system()
        logger.debug("OS detected: %s", os_name)

        runtime = {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
        }
        logger.debug("Runtime info: %s", runtime)

        # Step 2: 工作目录
        cwd = os.getcwd()
        logger.debug("Working directory: %s", cwd)

        # Step 3: Git 信息
        git_branch = self._get_git_branch()
        git_repo = self._get_git_remote()

        # Step 4: 关键环境变量
        env_vars = self._collect_env_vars()

        # Step 5: 构建 EnvironmentContext
        context = EnvironmentContext(
            os=os_name,
            working_directory=cwd,
            git_branch=git_branch,
            git_repo=git_repo,
            runtime=runtime,
            mcp_servers=dict(self.mcp_servers),
            env_vars=env_vars,
        )

        logger.info(
            "Environment collected: os=%s, git_branch=%s, git_repo=%s, runtime=%s",
            os_name,
            git_branch,
            git_repo,
            runtime.get("python_version"),
        )

        return context

    # ── Private Methods ──────────────────────────────────────────

    @staticmethod
    def _get_git_branch() -> Optional[str]:
        """获取当前 Git 分支名。

        静默失败，如果不在 Git 仓库中或 Git 不可用则返回 None。

        Returns:
            分支名或 None。
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                logger.debug("Git branch: %s", branch)
                return branch
        except FileNotFoundError:
            logger.debug("Git not found in PATH")
        except subprocess.TimeoutExpired:
            logger.warning("Git command timed out")
        except Exception as e:
            logger.debug("Failed to get git branch: %s", e)

        return None

    @staticmethod
    def _get_git_remote() -> Optional[str]:
        """获取当前 Git 远程仓库 URL。

        Returns:
            远程仓库 URL 或 None。
        """
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                repo = result.stdout.strip()
                logger.debug("Git remote: %s", repo)
                return repo
        except Exception:
            pass

        return None

    @staticmethod
    def _collect_env_vars() -> dict[str, str]:
        """收集对 Agent 有用的关键环境变量。

        只收集明确允许的环境变量，避免泄漏敏感信息。

        Returns:
            环境变量键值对。
        """
        # 允许收集的环境变量白名单
        allowed_prefixes = [
            "PATH", "HOME", "USER", "SHELL", "TERM",
            "LANG", "LC_", "LOG_LEVEL",
        ]
        vars = {}

        for key, value in os.environ.items():
            if any(key.startswith(prefix) for prefix in allowed_prefixes):
                vars[key] = value

        logger.debug("Collected %d environment variables", len(vars))
        return vars
