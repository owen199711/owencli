#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Embedding Service 一键部署脚本
# 
# 用法:
#   1. 将此文件传到目标服务器
#   2. chmod +x setup.sh && bash setup.sh
#
# 此脚本自包含 app.py + requirements.txt，无需额外下载。
# ═══════════════════════════════════════════════════════════════

set -e

# ── 配置 ──────────────────────────────────────────────────────
SERVICE_PORT="${SERVICE_PORT:-10305}"
DEPLOY_DIR="/data/idata/embeding"
LOG_DIR="/data/log/idata/embeding"
MODEL_NAME="${EMBEDDING_MODEL:-all-MiniLM-L6-v2}"

echo "========================================"
echo "  Embedding Service Setup"
echo "  Model:   $MODEL_NAME"
echo "  Port:    $SERVICE_PORT"
echo "  Deploy:  $DEPLOY_DIR"
echo "  Log:     $LOG_DIR"
echo "========================================"

# ── 1. 创建目录 ─────────────────────────────────────────────
echo "[1/5] Creating directories..."
mkdir -p "$DEPLOY_DIR"
mkdir -p "$LOG_DIR"

# ── 2. 写入 app.py ───────────────────────────────────────────
echo "[2/5] Writing app.py..."
cat > "${DEPLOY_DIR}/app.py" << 'PYEOF'
"""Embedding Service — 语义向量生成服务。

OpenAI 兼容格式，供 APIProvider 调用。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── 模块加载时直接下载模型（避免 httpx client 在 async 中被关闭） ──
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
    """OpenAI 兼容路径。"""
    return await embed(req)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", "10305"))
    # 单 worker 避免 huggingface_hub httpx client fork 后关闭的问题
    uvicorn.run("app:app", host="0.0.0.0", port=port, workers=1)
PYEOF

# ── 3. 写入 requirements.txt ─────────────────────────────────
echo "[3/5] Writing requirements.txt..."
cat > "${DEPLOY_DIR}/requirements.txt" << 'TXTEOF'
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sentence-transformers>=2.2.0
numpy>=1.24.0
TXTEOF

# ── 4. 安装依赖 ─────────────────────────────────────────────
echo "[4/5] Installing Python packages..."

# 优先升级 pip（很多 SSL 问题是 pip 版本过旧导致）
pip3 install --upgrade pip -q 2>/dev/null || true

# 定义多个镜像源，按优先级尝试
PIP_ARGS="-q --upgrade"
PACKAGES="fastapi uvicorn sentence-transformers numpy"

try_install() {
    local label="$1"
    shift
    echo "  Trying $label ..."
    if pip3 install $PIP_ARGS $PACKAGES "$@" 2>/dev/null; then
        echo "  ✅ $label succeeded"
        return 0
    fi
    echo "  ❌ $label failed"
    return 1
}

# 依次尝试以下源
try_install "PyPI direct" \
    --trusted-host pypi.org \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org && INSTALL_OK=1

if [ -z "$INSTALL_OK" ]; then
    try_install "Tsinghua HTTPS" \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn && INSTALL_OK=1
fi

if [ -z "$INSTALL_OK" ]; then
    try_install "Tsinghua HTTP (no SSL)" \
        -i http://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn && INSTALL_OK=1
fi

if [ -z "$INSTALL_OK" ]; then
    try_install "Aliyun" \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com && INSTALL_OK=1
fi

if [ -z "$INSTALL_OK" ]; then
    try_install "USTC" \
        -i https://pypi.mirrors.ustc.edu.cn/simple/ \
        --trusted-host pypi.mirrors.ustc.edu.cn && INSTALL_OK=1
fi

if [ -z "$INSTALL_OK" ]; then
    echo ""
    echo "  ❌ 所有镜像源均无法连接。"
    echo "  请在服务器上手动安装依赖后重新运行："
    echo "    pip3 install fastapi uvicorn sentence-transformers numpy"
    echo "  然后: bash /tmp/setup.sh"
    echo ""
    exit 1
fi

# ── 5. 启动服务 ─────────────────────────────────────────────
echo "[5/5] Starting service..."

# 检查端口并杀掉旧进程
PORT_PID=$(lsof -ti:"$SERVICE_PORT" 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "  Killing old process on port $SERVICE_PORT: PID=$PORT_PID"
    kill -9 "$PORT_PID" 2>/dev/null || true
    sleep 2
fi

# 后台启动
cd "$DEPLOY_DIR"

# HuggingFace 镜像（国内网络加速）
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

nohup python3 app.py > "$LOG_DIR/service.log" 2>&1 &
SERVICE_PID=$!

# 等待启动并验证
echo "  Waiting for service to start..."
for i in $(seq 1 12); do
    sleep 2
    if curl -s "http://127.0.0.1:$SERVICE_PORT/health" > /dev/null 2>&1; then
        echo "  ✅ Service is healthy (PID=$SERVICE_PID)"
        break
    fi
    if [ "$i" -eq 12 ]; then
        echo "  ❌ Service failed to start. Last 20 lines of log:"
        tail -20 "$LOG_DIR/service.log"
        exit 1
    fi
    echo "  Waiting... ($i/12)"
done

# ── 完成 ─────────────────────────────────────────────────────
HOST_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo "  ✅ Deployment complete!"
echo "  API:     http://${HOST_IP}:${SERVICE_PORT}"
echo "  Health:  http://${HOST_IP}:${SERVICE_PORT}/health"
echo "  Embed:   POST http://${HOST_IP}:${SERVICE_PORT}/embeddings"
echo "  Log:     ${LOG_DIR}/service.log"
echo "========================================"
