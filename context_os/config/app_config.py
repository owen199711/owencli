"""AppConfig — Python 版分层配置模型。

从 config.yaml 加载，支持 ${VAR:default} 环境变量替换。
参考 Java: com.owencli.contextos.core.config.model.AppConfig
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _resolve_env_vars(value: str) -> str:
    """替换 ${VAR:default} 环境变量引用。"""
    def _replacer(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, os.environ.get(var, default or ""))
    return _ENV_VAR_PATTERN.sub(_replacer, value)


def _resolve_recursively(obj: Any) -> Any:
    """递归解析对象中的字符串字段的环境变量。"""
    if isinstance(obj, str):
        return _resolve_env_vars(obj) if "$" in obj else obj
    elif isinstance(obj, dict):
        return {k: _resolve_recursively(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_recursively(v) for v in obj]
    return obj


# ── 数据类 ──


@dataclass
class MiddlewareDef:
    name: str = ""
    enabled: bool = True
    order: int = 0


@dataclass
class PipelineConfig:
    middlewares: list[MiddlewareDef] = field(default_factory=list)


@dataclass
class LlmConfig:
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    max_tokens: int = 4096


@dataclass
class EmbeddingConfig:
    mode: str = "auto"
    api_endpoint: str = "http://embedding-service:8080"
    api_key: str = ""
    api_model: str = "text-embedding-3-small"
    local_model: str = "bge-small.onnx"
    local_model_path: str = "./models/bge-small.onnx"
    ollama_endpoint: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"


@dataclass
class WorkingMemoryConfig:
    max_tokens: int = 32000


@dataclass
class ShortTermConfig:
    ttl_hours: int = 24


@dataclass
class LongTermConfig:
    max_items: int = 1000
    consolidation_interval_min: int = 60


@dataclass
class MemoryConfig:
    working_memory: WorkingMemoryConfig = field(default_factory=WorkingMemoryConfig)
    short_term: ShortTermConfig = field(default_factory=ShortTermConfig)
    long_term: LongTermConfig = field(default_factory=LongTermConfig)


@dataclass
class PostgresqlConfig:
    url: str = "jdbc:postgresql://localhost:5432/context_os"
    user: str = "app"
    password: str = "secret"


@dataclass
class StoreConfig:
    provider: str = "sqlite"
    db_path: str = "./data/context_os.db"
    postgresql: PostgresqlConfig = field(default_factory=PostgresqlConfig)


@dataclass
class TraceConfig:
    enabled: bool = True
    storage_dir: str = "./data/traces"


@dataclass
class AppConfig:
    """应用配置 — 与 Java AppConfig 结构一致。"""
    loaded_at: float = 0.0
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)


def _dict_to_middleware_def(d: dict) -> MiddlewareDef:
    return MiddlewareDef(
        name=d.get("name", ""),
        enabled=d.get("enabled", True),
        order=d.get("order", 0),
    )


def from_dict(data: dict) -> AppConfig:
    """从嵌套字典构造 AppConfig。"""
    ctx = data.get("context-os", data)

    cfg = AppConfig()

    # Pipeline
    pl = ctx.get("pipeline", {})
    cfg.pipeline = PipelineConfig(
        middlewares=[
            _dict_to_middleware_def(m)
            for m in pl.get("middlewares", [])
        ]
    )

    # LLM
    llm = ctx.get("llm", {})
    cfg.llm = LlmConfig(
        provider=llm.get("provider", "deepseek"),
        api_key=llm.get("api-key", llm.get("api_key", "")),
        model=llm.get("model", "deepseek-chat"),
        max_tokens=llm.get("max-tokens", llm.get("max_tokens", 4096)),
    )

    # Embedding
    emb = ctx.get("embedding", {})
    cfg.embedding = EmbeddingConfig(
        mode=emb.get("mode", "auto"),
        api_endpoint=emb.get("api", {}).get("endpoint", "http://embedding-service:8080"),
        api_key=emb.get("api", {}).get("api-key", ""),
        api_model=emb.get("api", {}).get("model", "text-embedding-3-small"),
        local_model=emb.get("local", {}).get("model", "bge-small.onnx"),
        local_model_path=emb.get("local", {}).get("model-path", emb.get("local", {})
                                                  .get("model_path", "./models/bge-small.onnx")),
        ollama_endpoint=emb.get("ollama", {}).get("endpoint", "http://localhost:11434"),
        ollama_model=emb.get("ollama", {}).get("model", "nomic-embed-text"),
    )

    # Memory
    mem = ctx.get("memory", {})
    cfg.memory = MemoryConfig(
        working_memory=WorkingMemoryConfig(
            max_tokens=mem.get("working-memory", mem.get("working_memory", {})).get(
                "max-tokens", mem.get("working-memory", mem.get("working_memory", {}))
                .get("max_tokens", 32000))
        ),
        short_term=ShortTermConfig(
            ttl_hours=mem.get("short-term", mem.get("short_term", {})).get(
                "ttl-hours", mem.get("short-term", mem.get("short_term", {}))
                .get("ttl_hours", 24))
        ),
        long_term=LongTermConfig(
            max_items=mem.get("long-term", mem.get("long_term", {})).get(
                "max-items", mem.get("long-term", mem.get("long_term", {}))
                .get("max_items", 1000)),
            consolidation_interval_min=mem.get("long-term", mem.get("long_term", {}))
                .get("consolidation-interval-min", mem.get("long-term", mem.get("long_term", {}))
                .get("consolidation_interval_min", 60)),
        ),
    )

    # Store
    st = ctx.get("store", {})
    cfg.store = StoreConfig(
        provider=st.get("provider", "sqlite"),
        db_path=st.get("db-path", st.get("db_path", "./data/context_os.db")),
        postgresql=PostgresqlConfig(
            url=st.get("postgresql", {}).get("url", "jdbc:postgresql://localhost:5432/context_os"),
            user=st.get("postgresql", {}).get("user", "app"),
            password=st.get("postgresql", {}).get("password", "secret"),
        ),
    )

    # Trace
    tr = ctx.get("trace", {})
    cfg.trace = TraceConfig(
        enabled=tr.get("enabled", True),
        storage_dir=tr.get("storage-dir", tr.get("storage_dir", "./data/traces")),
    )

    return cfg
