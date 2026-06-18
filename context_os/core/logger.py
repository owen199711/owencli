"""Context-OS 统一日志工具。

所有模块使用此工具获取 logger，确保日志格式统一。
用法:
    from context_os.core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("...")
"""

import logging
import sys
from typing import Optional


# 全局日志格式
DEFAULT_FORMAT = (
    "[%(asctime)s] %(levelname)-8s %(name)s | "
    "%(filename)s:%(lineno)d | %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(
    name: str,
    level: Optional[int] = None,
    fmt: Optional[str] = None,
) -> logging.Logger:
    """获取统一配置的 logger。

    Args:
        name: Logger 名称，通常传入 __name__。
        level: 日志级别，默认从环境变量 LOG_LEVEL 读取，未设置则用 INFO。
        fmt: 日志格式，默认使用 DEFAULT_FORMAT。

    Returns:
        配置好的 Logger 实例。
    """
    logger = logging.getLogger(name)

    # 只有在没有 handler 时才添加，避免重复
    if not logger.handlers:
        logger.setLevel(level or _resolve_level())

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            fmt or DEFAULT_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT,
        ))
        logger.addHandler(handler)

    return logger


def _resolve_level() -> int:
    """从环境变量或默认值解析日志级别。"""
    import os
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    return level_map.get(os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
