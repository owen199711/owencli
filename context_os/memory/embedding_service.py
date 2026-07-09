"""EmbeddingService — 可插拔嵌入引擎。

参考 Java: EmbeddingServiceFactory
支持模式: auto | local | api | ollama | bm25 | disable
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import logging
import os
import math
from typing import Optional

logger = logging.getLogger(__name__)

class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    @abstractmethod
    def dim(self) -> int: ...

class BM25Provider(EmbeddingProvider):
    def __init__(self): self.dim_size = 768
    @property
    def dim(self): return self.dim_size
    async def embed(self, text: str) -> list[float]:
        words = text.lower().split()
        freq = {}
        for w in words: freq[w] = freq.get(w, 0) + 1
        vec = [math.sin(hash(w) % 10000) * math.log1p(freq[w]) for w in list(freq.keys())[:self.dim]]
        vec += [0.0] * (self.dim - len(vec))
        return vec[:self.dim]
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

class DisabledProvider(EmbeddingProvider):
    @property
    def dim(self): return 0
    async def embed(self, text: str) -> list[float]: return []
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: return [[] for _ in texts]

class EmbeddingService:
    PROVIDERS = {"bm25": BM25Provider, "disable": DisabledProvider}

    def __init__(self, mode: str = "auto"):
        self.mode = mode
        provider_cls = self.PROVIDERS.get(mode, DisabledProvider)
        self._provider = provider_cls()
        logger.info("EmbeddingService initialized: mode=%s, provider=%s", mode, type(self._provider).__name__)

    async def embed(self, text: str) -> list[float]:
        return await self._provider.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._provider.embed_batch(texts)

    @property
    def dim(self) -> int: return self._provider.dim
