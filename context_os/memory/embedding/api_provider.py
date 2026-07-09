"""APIEmbeddingService — HTTP 远程嵌入（对齐 Java APIEmbeddingService）。

OpenAI-compatible API 格式。
"""
from __future__ import annotations
import json, logging
from context_os.memory.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

class APIProvider(EmbeddingProvider):
    def __init__(self, endpoint: str, api_key: str = "", model: str = "text-embedding-3-small"):
        self.endpoint = endpoint.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self._dim = 0
        logger.info("APIProvider: endpoint=%s, model=%s", endpoint, model)

    @property
    def dim(self): return self._dim

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip(): return []
        import aiohttp
        headers = {"Content-Type": "application/json"}
        if self.api_key: headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.endpoint, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("API embedding failed: status=%d, body=%s", resp.status, body[:200])
                        return []
                    data = await resp.json()
                    return self._parse(data)
        except Exception as e:
            logger.warning("API embedding error: %s", e)
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    def _parse(self, data: dict) -> list[float]:
        try:
            emb = data.get("data", [{}])[0].get("embedding") or data.get("vector")
            if emb: self._dim = len(emb)
            return emb or []
        except: return []
