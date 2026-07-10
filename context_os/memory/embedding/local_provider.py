"""LocalEmbeddingProvider — 本地 sentence-transformers 语义嵌入。

无需部署远程服务，直接在本机加载模型进行计算。
"""

from __future__ import annotations

import logging
from typing import Optional

from context_os.memory.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)


class LocalEmbeddingProvider(EmbeddingProvider):
    """使用本地 sentence-transformers 模型生成语义向量。"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dim = 0

    def _ensure_model(self):
        if self._model is not None:
            return
        logger.info("Loading local embedding model: %s ...", self._model_name)
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        logger.info("Model loaded: dim=%d, device=%s", self._dim, self._model.device)

    @property
    def dim(self) -> int:
        self._ensure_model()
        return self._dim

    async def embed(self, text: str) -> list[float]:
        self._ensure_model()
        return self._model.encode(text).tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        if not texts:
            return []
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]
