"""性能指标统计 — 收集和汇总测试过程中的各项指标。

支持:
    - Latency: 各模块延迟
    - Tokens: Prompt / Completion Token 数
    - Cost: USD 成本估算
    - 统计汇总: 平均值 / 最大值 / 最小值 / P50 / P95
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepMetrics:
    """单步指标。"""
    step_name: str
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineMetrics:
    """单次 Pipeline 执行的完整指标。"""
    steps: list[StepMetrics] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    timestamp: Optional[str] = None

    def add_step(self, step: StepMetrics):
        self.steps.append(step)

    def step_latency(self, name: str) -> float:
        for s in self.steps:
            if s.step_name == name:
                return s.latency_ms
        return 0.0

    @property
    def step_names(self) -> list[str]:
        return [s.step_name for s in self.steps]


class MetricsCollector:
    """全局指标收集器，汇总所有测试例的指标。"""

    def __init__(self):
        self._all_metrics: list[PipelineMetrics] = []
        self._step_latencies: dict[str, list[float]] = defaultdict(list)
        self._step_tokens: dict[str, list[int]] = defaultdict(list)

    def add(self, metrics: PipelineMetrics):
        self._all_metrics.append(metrics)
        for step in metrics.steps:
            self._step_latencies[step.step_name].append(step.latency_ms)
            if step.input_tokens > 0:
                self._step_tokens[f"{step.step_name}_input"].append(step.input_tokens)
            if step.output_tokens > 0:
                self._step_tokens[f"{step.step_name}_output"].append(step.output_tokens)

    @property
    def count(self) -> int:
        return len(self._all_metrics)

    @staticmethod
    def _stats(values: list[float]) -> dict:
        if not values:
            return {"min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "count": 0}
        sorted_v = sorted(values)
        n = len(sorted_v)
        return {
            "min": round(min(sorted_v), 1),
            "max": round(max(sorted_v), 1),
            "avg": round(sum(sorted_v) / n, 1),
            "p50": round(sorted_v[int(n * 0.50)], 1),
            "p95": round(sorted_v[int(n * 0.95)], 1),
            "count": n,
        }

    def latency_summary(self) -> dict[str, dict]:
        """返回各步骤的延迟统计。"""
        return {
            step: self._stats(lats)
            for step, lats in sorted(self._step_latencies.items())
        }

    def token_summary(self) -> dict[str, dict]:
        """返回 Token 统计。"""
        return {
            key: self._stats([float(v) for v in vals])
            for key, vals in sorted(self._step_tokens.items())
        }

    def total_cost(self) -> float:
        return sum(m.total_cost_usd for m in self._all_metrics)

    def summary(self) -> dict:
        """完整的汇总报告。"""
        total_lat = sum(m.total_latency_ms for m in self._all_metrics)
        return {
            "total_runs": self.count,
            "total_latency_ms": round(total_lat, 1),
            "avg_latency_ms": round(total_lat / self.count, 1) if self.count > 0 else 0,
            "total_cost_usd": round(self.total_cost(), 6),
            "latency_breakdown": self.latency_summary(),
            "token_breakdown": self.token_summary(),
        }


# ═══════════════════════════════════════════════════════════════════
# Token / Cost 估算工具
# ═══════════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """粗略估算文本的 Token 数（中英文混合）。"""
    if not text:
        return 0
    # 英文按 4 字符 1 token，中文按 1.5 字符 1 token 估算
    en_chars = sum(1 for c in text if c.isascii() and c.isprintable())
    cn_chars = len(text) - en_chars
    return int(en_chars / 4 + cn_chars / 1.5 + 0.5)


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "deepseek",
) -> float:
    """估算 LLM 调用成本（USD）。

    参考价格 (per 1M tokens):
    - DeepSeek:   $0.27 input / $1.10 output
    - Claude Sonnet 4: $3.00 input / $15.00 output
    """
    rates = {
        "deepseek": (0.27, 1.10),
        "claude": (3.00, 15.00),
        "openai": (2.50, 10.00),
    }
    input_rate, output_rate = rates.get(model, rates["deepseek"])
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
