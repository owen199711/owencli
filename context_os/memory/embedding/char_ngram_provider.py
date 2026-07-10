"""CharNGramEmbeddingService — 中文二元组 + 英文三元组嵌入（对齐 Java CharNGramEmbeddingService）。

256 维向量，零依赖，纯算法。
"""
from __future__ import annotations
import hashlib
import math
import re
from context_os.memory.embedding import EmbeddingProvider


def _deterministic_hash(s: str) -> int:
    """确定性散列，不受 PYTHONHASHSEED 影响，跨进程可复现。"""
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big")


class CharNGramProvider(EmbeddingProvider):
    DIM = 256

    @property
    def dim(self): return self.DIM

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip(): return []
        vec = [0.0] * self.DIM
        cleaned = re.sub(r"\s+", "", text)
        # 中文二元组
        for i in range(len(cleaned) - 1):
            c1, c2 = ord(cleaned[i]), ord(cleaned[i+1])
            if self._is_chinese(c1) and self._is_chinese(c2):
                idx = (c1 * 31 + c2) & 0x7FFFFFFF % self.DIM
                vec[idx] += 1.0
        # 中文单字
        for i in range(len(cleaned)):
            ch = ord(cleaned[i])
            if self._is_chinese(ch):
                idx = (ch * 17) & 0x7FFFFFFF % self.DIM
                vec[idx] += 0.5
        # 英文三元组 + 完整词
        lower = text.lower()
        words = [w for w in re.split(r"[^a-zA-Z0-9]+", lower) if len(w) >= 2]
        for word in words:
            for i in range(len(word) - 2):
                tri = word[i:i+3]
                idx = _deterministic_hash(tri) % self.DIM
                vec[idx] += 1.0
            idx = _deterministic_hash(word) % self.DIM
            vec[idx] += 0.8
        # Log(1+freq) 归一化
        for i in range(self.DIM):
            if vec[i] > 0: vec[i] = math.log1p(vec[i])
        norm = math.sqrt(sum(v*v for v in vec))
        if norm > 0: vec = [v/norm for v in vec]
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    @staticmethod
    def _is_chinese(cp: int) -> bool: return 0x4E00 <= cp <= 0x9FFF
