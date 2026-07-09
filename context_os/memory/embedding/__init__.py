"""EmbeddingService — 可插拔嵌入引擎。

完全对齐 Java 版：
  - EmbeddingProvider ABC + cosine_similarity 静态方法
  - BM25 | CharNGram | API | Ollama | Disabled
  - EmbeddingServiceFactory: auto|local|api|ollama|disable
"""
from __future__ import annotations
import math, logging
from abc import ABC, abstractmethod
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

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b): return 0.0
        dot = nA = nB = 0.0
        for va, vb in zip(a, b):
            dot += va * vb; nA += va * va; nB += vb * vb
        denom = math.sqrt(nA) * math.sqrt(nB)
        return dot / denom if denom != 0 else 0.0

class DisabledProvider(EmbeddingProvider):
    @property
    def dim(self): return 0
    async def embed(self, text: str) -> list[float]: return []
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: return [[] for _ in texts]

class EmbeddingServiceFactory:
    MODES = {"bm25", "char_ngram", "api", "ollama", "disable", "auto"}

    def __init__(self, config=None): self.config = config or {}

    def create(self, mode: str = "auto") -> EmbeddingProvider:
        mode = mode.lower() if mode else "auto"
        logger.info("EmbeddingServiceFactory: mode=%s", mode)
        if mode == "api": return self._create_api()
        elif mode == "ollama": return self._create_ollama()
        elif mode == "disable": return DisabledProvider()
        elif mode == "char_ngram": return self._create_char_ngram()
        elif mode == "auto":
            try: return self._create_bm25()  # always available
            except: return DisabledProvider()
        else: return self._create_bm25()

    def _create_bm25(self):
        from context_os.memory.embedding.bm25_provider import BM25Provider
        return BM25Provider()

    def _create_char_ngram(self):
        from context_os.memory.embedding.char_ngram_provider import CharNGramProvider
        return CharNGramProvider()

    def _create_api(self):
        from context_os.memory.embedding.api_provider import APIProvider
        return APIProvider(
            endpoint=self.config.get("api_endpoint", "http://embedding-service:8080"),
            api_key=self.config.get("api_key", ""),
            model=self.config.get("api_model", "text-embedding-3-small"),
        )

    def _create_ollama(self):
        from context_os.memory.embedding.ollama_provider import OllamaProvider
        return OllamaProvider(
            endpoint=self.config.get("ollama_endpoint", "http://localhost:11434"),
            model=self.config.get("ollama_model", "nomic-embed-text"),
        )

# Module-level aliases
cosine_similarity = EmbeddingProvider.cosine_similarity

