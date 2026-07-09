"""Store — 存储层 SPI。

参考 Java: com.owencli.contextos.store.StoreProvider

多后端：SQLiteStore (默认)、内存 Store (测试用)、PostgreSQL (预留)
"""

from context_os.store.provider import StoreProvider
from context_os.store.session import StoreSession

__all__ = [
    "StoreProvider",
    "StoreSession",
]
