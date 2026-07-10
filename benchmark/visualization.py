"""Context 可视化工具 — Pipeline Timeline 和 Context 分布图。

输出纯文本可视化（适用于控制台和报告）。
"""

from __future__ import annotations

from typing import Any, Optional


def format_timeline(
    breakdown: dict[str, float],
    total_ms: float,
    width: int = 50,
) -> str:
    """生成 Pipeline Timeline 文本可视化。

    Intent ──────12ms ███
    Collection ────────25ms �███████

    Args:
        breakdown: {step_name: latency_ms}
        total_ms: 总延迟。
        width: 最大条宽度。

    Returns:
        格式化后的文本。
    """
    if not breakdown:
        return "  (no timing data)"

    max_lat = max(breakdown.values()) if breakdown else 1
    lines = []

    # 按步骤排序
    step_order = [
        "intent", "builder", "collection", "optimizer",
        "packager", "llm", "feedback",
    ]
    seen = set()
    for step in step_order:
        if step in breakdown:
            lat = breakdown[step]
            bar_len = max(1, int((lat / max_lat) * width))
            bar = "█" * bar_len
            name = step.ljust(12)
            lines.append(f"  {name} ── {lat:6.0f}ms {bar}")
            seen.add(step)

    # 不在顺序中的步骤
    for step, lat in sorted(breakdown.items()):
        if step not in seen:
            bar_len = max(1, int((lat / max_lat) * width))
            bar = "█" * bar_len
            name = step.ljust(12)
            lines.append(f"  {name} ── {lat:6.0f}ms {bar}")

    lines.append(f"  {'Total':12s} ── {total_ms:6.0f}ms")
    return "\n".join(lines)


def format_context_bars(
    context_counts: dict[str, int],
    max_width: int = 40,
) -> str:
    """生成 Context 分布柱状图文本。

    Working   ■■■■■■■  7
    Fact      ■■■■■■■■■■■■  12
    Semantic  ■■■■■■  6

    Args:
        context_counts: {type_name: count}
        max_width: 最大条宽度。

    Returns:
        格式化后的文本。
    """
    if not context_counts:
        return "  (no context data)"

    max_count = max(context_counts.values()) if context_counts else 1
    lines = []

    for name, count in sorted(context_counts.items(), key=lambda x: -x[1]):
        bar_len = max(1, int((count / max_count) * max_width))
        bar = "■" * bar_len
        label = name.ljust(12)
        lines.append(f"  {label} {bar} {count}")

    return "\n".join(lines)


def format_module_result(
    module_name: str,
    passed: bool,
    details: Optional[dict] = None,
) -> str:
    """格式化单个模块测试结果。"""
    icon = "✅" if passed else "❌"
    lines = [f"  {icon} {module_name}"]

    if details:
        for key, value in details.items():
            if key == "issues" and isinstance(value, list):
                for issue in value:
                    lines.append(f"       ⚠️  {issue}")
            elif key not in ("issues",):
                lines.append(f"       {key}: {value}")

    return "\n".join(lines)


def format_prompt_preview(prompt: str, max_chars: int = 200) -> str:
    """格式化 Prompt 预览。"""
    if len(prompt) <= max_chars:
        return f"  {prompt}"
    return f"  {prompt[:max_chars]}...\n  ...({len(prompt) - max_chars} more chars)"


def print_module_diagnostics(diag: dict):
    """打印完整的分层诊断信息。"""
    print()
    print("=" * 70)

    # Intent Layer
    if "intent" in diag and "error" not in diag["intent"]:
        intent = diag["intent"]
        print(f"  Intent Layer  ({intent.get('latency_ms', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        print(f"    Intent:     {intent.get('intent', '?')}")
        print(f"    Goal:       {intent.get('goal', '?')}")
        print(f"    Confidence: {intent.get('confidence', 0):.2f}")
        entities = intent.get("entities", [])
        if entities:
            parts = [f"{e.get('type','?')}={e.get('value','?')}" for e in entities[:5]]
            print(f"    Entities:   {', '.join(parts)}")
        print()

    # Collection Layer
    if "collection" in diag and "error" not in diag["collection"]:
        col = diag["collection"]
        print(f"  Collection Layer  ({diag.get('latency_breakdown', {}).get('builder', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        print(f"    Conversation: {col.get('conversation_turns', 0)} turns")
        print(f"    Identity:     {'yes' if col.get('identity_present') else 'no'}")
        print(f"    Environment:  {'yes' if col.get('environment_present') else 'no'}")
        print()

    # Builder Layer
    if "builder" in diag and "error" not in diag["builder"]:
        b = diag["builder"]
        by_type = b.get("memory_by_type", {})
        items = b.get("memory_items", [])
        print(f"  Builder Layer")
        print(f"  {'─' * 50}")
        print(f"    Memory Count: {b.get('memory_count', 0)} ({len(by_type)} types)")
        if by_type:
            for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
                print(f"      {t}: {c}")
        if items:
            print(f"    Items (top {min(len(items), 3)}):")
            for item in items[:3]:
                print(f"      [{item.get('type','?')}] {item.get('content','')[:60]}")
        print()

    # Optimizer Layer
    if "optimizer" in diag and "error" not in diag["optimizer"]:
        o = diag["optimizer"]
        print(f"  Optimizer Layer  ({o.get('latency_ms', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        ratio = o.get("compression_ratio", 0)
        print(f"    Before:       {o.get('token_before', 0)} tokens")
        print(f"    After:        {o.get('token_after', 0)} tokens")
        print(f"    Reduction:    {o.get('token_reduced', 0)} tokens ({ratio:.0%})")
        print(f"    Budget:       {o.get('token_budget_total', 0)} total, {o.get('token_budget_used', 0)} used")
        print()

    # Packager Layer
    if "packager" in diag and "error" not in diag["packager"]:
        pkg = diag["packager"]
        print(f"  Packager Layer  ({pkg.get('latency_ms', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        print(f"    Prompt:       {pkg.get('prompt_length_chars', 0)} chars (~{pkg.get('prompt_tokens_est', 0)} tokens)")
        sections = pkg.get("sections", [])
        if sections:
            print(f"    Sections:     {', '.join(sections)}")
        print()

    # LLM Layer
    if "llm" in diag and "error" not in diag["llm"]:
        llm = diag["llm"]
        print(f"  LLM Inference  ({llm.get('latency_ms', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        print(f"    Response:     {llm.get('response', '')[:150]}")
        print()

    # Feedback Layer
    if "feedback" in diag and "error" not in diag["feedback"]:
        fb = diag["feedback"]
        print(f"  Feedback Layer  ({fb.get('latency_ms', 0):.0f}ms)")
        print(f"  {'─' * 50}")
        print(f"    Quality:      {fb.get('answer_quality', 0):.2f}")
        print(f"    Reward:       {fb.get('reward_score', 0):.2f}")
        print(f"    Success:      {'yes' if fb.get('success') else 'no'}")
        print(f"    Cost:         ${fb.get('cost_usd', 0):.6f}")

    # Performance Breakdown
    breakdown = diag.get("latency_breakdown", {})
    total = diag.get("total_latency_ms", 0)
    if breakdown:
        print(f"\n  {'─' * 50}")
        print(format_timeline(breakdown, total))
        print(f"  Pipeline Total: {total:.0f}ms")

    print("=" * 70)
    print()
