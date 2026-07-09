"""BM25EmbeddingService — BM25 关键词嵌入（对齐 Java BM25EmbeddingService）。

256 维向量 + 停用词 + IDF + TF 归一化 + 中英文 Token 提取
"""
from __future__ import annotations
import math, re
from context_os.memory.embedding import EmbeddingProvider

_STOP_WORDS = frozenset({
    "的","了","在","是","我","有","和","就","不","人","都","一","一个","上","也",
    "很","到","说","要","去","你","会","着","没有","看","好","自己","这",
    "the","a","an","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could",
    "should","may","might","shall","can","need","dare","ought",
})

class BM25Provider(EmbeddingProvider):
    DIM = 256

    def __init__(self):
        self._idf_cache = {}
        self._dim = self.DIM

    @property
    def dim(self): return self._dim

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip(): return []
        vec = [0.0] * self.DIM
        tokens = self._extract_tokens(text)
        tf_map = {}
        for t in tokens:
            if len(t) < 2 or t in _STOP_WORDS: continue
            tf_map[t] = tf_map.get(t, 0) + 1
        if not tf_map: return []
        max_tf = max(tf_map.values())
        for token, tf in tf_map.items():
            tf_norm = tf / (0.5 + 0.5 * tf / max_tf)
            h = abs(hash(token))
            idx1 = h % self.DIM
            idx2 = (h * 31 + 17) % self.DIM
            idf = self._get_idf(token)
            vec[idx1] += tf_norm * idf
            vec[idx2] += tf_norm * idf * 0.3
        norm = math.sqrt(sum(v*v for v in vec))
        if norm > 0: vec = [v/norm for v in vec]
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    def _extract_tokens(self, text: str) -> list[str]:
        tokens = []
        lower = text.lower()
        chinese = re.findall(r"[\u4e00-\u9fff]", lower)
        for i in range(len(chinese) - 1):
            tokens.append(chinese[i] + chinese[i+1])
        for word in re.split(r"[^a-z0-9]+", lower):
            if len(word) >= 2: tokens.append(word)
        return tokens

    def _get_idf(self, token: str) -> float:
        if token not in self._idf_cache:
            h = abs(hash(token))
            sim_df = 1.0 + (h % 100) / 100.0
            self._idf_cache[token] = math.log(1.0 + (1000.0 - sim_df) / sim_df)
        return self._idf_cache[token]
