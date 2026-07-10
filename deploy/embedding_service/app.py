"""Embedding Service — 语义向量生成服务。

OpenAI 兼容格式，供 APIProvider 调用。
模型: all-MiniLM-L6-v2 (384维, 轻量级, 速度快)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── 日志配置 ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("embedding_service")

# ── 加载模型 ───────────────────────────────────────────────────
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
logger.info("Loading model: %s ...", MODEL_NAME)
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    logger.info("Model loaded: dim=%d, device=%s", dim, model.device)
except Exception as e:
    logger.error("Failed to load model: %s", e)
    raise

# ── FastAPI 应用 ───────────────────────────────────────────────
app = FastAPI(title="Embedding Service", version="1.0.0")


class EmbeddingRequest(BaseModel):
    model: str = MODEL_NAME
    input: str


class EmbeddingResponse(BaseModel):
    data: list[dict[str, Any]]
    model: str
    usage: dict[str, int]


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "dim": dim}


@app.post("/embeddings", response_model=EmbeddingResponse)
async def embed(req: EmbeddingRequest):
    text = req.input
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Empty input text")

    try:
        emb = model.encode(text).tolist()
        token_count = len(text.split())
        return EmbeddingResponse(
            data=[{"embedding": emb, "index": 0}],
            model=req.model,
            usage={"prompt_tokens": token_count, "total_tokens": token_count},
        )
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def embed_v1(req: EmbeddingRequest):
    """OpenAI 标准 /v1/embeddings 路径兼容。"""
    return await embed(req)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", "10306"))
    # 单 worker 避免 huggingface_hub httpx client fork 后关闭的问题
    uvicorn.run("app:app", host="0.0.0.0", port=port, workers=1)
