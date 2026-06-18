from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """Base class for context collectors.

    Each collector is responsible for fetching data from a specific source
    (e.g. identity provider, environment, conversation history).
    """

    @abstractmethod
    async def collect(self) -> dict[str, Any]:
        """Collect data from the source and return as a dictionary."""
        ...


class BaseMemoryStore(ABC):
    """Base class for memory storage backends."""

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve memory items relevant to the query."""
        ...

    @abstractmethod
    async def store(self, item: dict[str, Any]) -> None:
        """Store a memory item."""
        ...

    @abstractmethod
    async def delete(self, item_id: str) -> None:
        """Delete a memory item by ID."""
        ...


class BasePromptAdapter(ABC):
    """Base class for LLM prompt adapters.

    Transforms an optimized context into a provider-specific prompt format.
    """

    provider: str

    @abstractmethod
    def pack(self, context: Any) -> str:
        """Pack the context into a provider-specific prompt string."""
        ...


class BaseLLMClient(ABC):
    """Base class for LLM API clients."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: str | None = None,
    ) -> str | dict[str, Any]:
        """Send a completion request to the LLM."""
        ...
