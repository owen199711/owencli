"""StoreSession — 存储会话接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class StoreSession(ABC):
    """存储会话 — 封装一次连接内的所有操作。

    涵盖 Memory、Episode、Concept、Fact 的统一存储。
    """

    @abstractmethod
    async def save_memory(
        self,
        id: str,
        type: str,
        content: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        metadata: Optional[dict] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str: ...

    @abstractmethod
    async def load_memory(self, id: str) -> Optional[dict]: ...

    @abstractmethod
    async def query_memories(
        self,
        type: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict]: ...

    @abstractmethod
    async def delete_memory(self, id: str) -> None: ...

    @abstractmethod
    async def save_episode(
        self,
        id: str,
        scene: str,
        action: str,
        result: str,
        feedback: str = "",
        tags: Optional[list[str]] = None,
        user_id: Optional[str] = None,
    ) -> str: ...

    @abstractmethod
    async def query_episodes(
        self, user_id: str, limit: int = 50
    ) -> list[dict]: ...

    @abstractmethod
    async def save_concept(
        self, id: str, name: str, description: str, user_id: Optional[str] = None
    ) -> str: ...

    @abstractmethod
    async def search_concepts(self, keyword: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def save_fact(
        self,
        id: str,
        content: str,
        category: str,
        confidence: float,
        user_id: Optional[str] = None,
    ) -> str: ...

    @abstractmethod
    async def query_facts(self, user_id: str, limit: int = 100) -> list[dict]: ...

    @abstractmethod
    async def flush(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
