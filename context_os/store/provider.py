"""StoreProvider — 存储提供商 SPI。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from context_os.store.session import StoreSession


class StoreProvider(ABC):
    """存储提供商 SPI — 参考 DeerFlow Checkpointer 多后端设计。

    实现：
    - SQLiteStoreProvider — 默认嵌入式存储
    - MemoryStoreProvider — 测试用内存存储
    - PostgreSQLStoreProvider — 生产部署（预留）
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """提供商名称：sqlite / memory / postgresql"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """当前环境是否可用。"""
        ...

    @abstractmethod
    async def open_session(self) -> StoreSession:
        """打开一个存储会话。"""
        ...
