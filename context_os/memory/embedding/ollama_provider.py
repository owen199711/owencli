"""OllamaEmbeddingService — Ollama 本地 API 嵌入（对齐 Java OllamaEmbeddingService）。

POST http://localhost:11434/api/embeddings
"""
from __future__ import annotations
import json, logging
from context_os.memory.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

class OllamaProvider(EmbeddingProvider):
    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self.endpoint = endpoint.rstrip("/") + "/api/embeddings"
        self.model = model
        self._dim = 0
        logger.info("OllamaProvider: endpoint=%s, model=%s", endpoint, model)

    @property
    def dim(self): return self._dim

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip(): return []
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not installed, Ollama unavailable")
            return []
        payload = {"model": self.model, "prompt": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.endpoint, json=payload, timeout=30) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("Ollama failed: status=%d, body=%s", resp.status, body[:200])
                        return []
                    data = await resp.json()
                    emb = data.get("embedding", [])
                    if emb: self._dim = len(emb)
                    return emb
        except Exception as e:
            logger.warning("Ollama error: %s", e)
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]
