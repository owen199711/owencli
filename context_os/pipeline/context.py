"""Pipeline 执行上下文 — 在 Middleware Chain 中传递状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from context_os.core.models import (
    EvalMetrics,
    LLMProvider,
    OptimizedContext,
    PackagedContext,
    TaskSpec,
    UnifiedContext,
)


@dataclass
class PipelineContext:
    """Pipeline 执行上下文 — 替代旧版大量方法参数传递。

    每个 Middleware 从这里读取输入、写入输出。
    """

    # ── 输入 ──
    user_input: str
    session_id: str
    user_id: str = "anonymous"
    provider: LLMProvider = LLMProvider.CLAUDE

    # ── 共享组件（由 PipelineEngine 注入） ──
    shared_components: dict[str, Any] = field(default_factory=dict)

    # ── 阶段输出（由 Middleware 填充） ──
    task_spec: Optional[TaskSpec] = None
    unified_context: Optional[UnifiedContext] = None
    optimized_context: Optional[OptimizedContext] = None
    packaged_context: Optional[PackagedContext] = None
    policy_directive: Optional[dict] = None
    llm_response: str = ""
    metrics: Optional[EvalMetrics] = None
    memory_update_result: Optional[dict] = None

    # ── 运行时 ──
    cancelled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_result: Optional[dict[str, Any]] = None

    def get_component(self, key: str) -> Any:
        return self.shared_components.get(key)
