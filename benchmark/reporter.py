"""报告生成器 — 将 Benchmark 结果输出为 JSON 和 HTML 格式。

HTML 报告包含:
    - 模块测试 PASS/FAIL 矩阵
    - Memory Benchmark 分数和对比
    - Pipeline Timeline 可视化
    - Scoring 汇总
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from typing import Any, Optional


def _h(value: Any, default: str = "?") -> str:
    """HTML 转义文本值，防止标签注入。"""
    s = str(value) if value else default
    return html.escape(s, quote=False)


class ReportGenerator:
    """Benchmark 报告生成器。"""

    def __init__(self, output_dir: str = "benchmark/reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ═══════════════════════════════════════════════════════════════
    # JSON 报告
    # ═══════════════════════════════════════════════════════════════

    def generate_json(self, results: dict[str, Any]) -> str:
        """生成 JSON 报告文件。

        Returns:
            文件路径。
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_report_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        return filepath

    # ═══════════════════════════════════════════════════════════════
    # HTML 报告
    # ═══════════════════════════════════════════════════════════════

    def generate_html(self, results: dict[str, Any]) -> str:
        """生成 HTML 报告文件。

        Returns:
            文件路径。
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_report_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)

        summary = results.get("summary", {})
        mem_benchmarks = results.get("memory_benchmarks", [])

        # 构建模块测试矩阵
        module_rows = ""
        for mt in results.get("module_tests", []):
            for mod in mt.get("modules", []):
                status = "✅" if mod.get("passed") else "❌"
                module_rows += f"""
                <tr>
                    <td>{_h(mt.get("case_id"))}</td>
                    <td>{_h(mod.get("name"))}</td>
                    <td>{status}</td>
                </tr>"""

        # 构建 Memory Benchmark 表格
        mem_rows = ""
        for mb in mem_benchmarks:
            mem_rows += f"""
            <tr>
                <td>{_h(mb.get("case_id"))}</td>
                <td>{_h(mb.get("description", ""))[:50]}</td>
                <td>{mb.get("simple_avg_score", 0):.1%}</td>
                <td>{mb.get("avg_keyword_score", 0):.1%}</td>
                <td>{mb.get("avg_judge_score", 0):.1%}</td>
                <td>{mb.get("avg_final_score", 0):.1%}</td>
                <td>{"✅" if mb.get("passed") else "❌"}</td>
            </tr>"""

        # Pipeline 延迟分解
        pipeline_info = ""
        for pt in results.get("pipeline_tests", []):
            bd = pt.get("breakdown", {})
            timeline_bars = ""
            for step, lat in sorted(bd.items()):
                bar_len = max(1, int(lat / 10))
                bar = "█" * min(bar_len, 50)
                timeline_bars += f"<div>{_h(step)}: {bar} {lat:.0f}ms</div>"
            pipeline_info = f"""
            <div class="section">
                <h3>Pipeline: {_h(pt.get('input', ''))[:60]}</h3>
                <div class="timeline">{timeline_bars}</div>
                <p>Total: {pt.get('latency_ms', 0):.0f}ms</p>
            </div>"""

        # 检索质量
        retriever_info = ""
        for rb in results.get("retriever_benchmarks", []):
            by_type = rb.get("by_type", {})
            type_str = ", ".join(f"{k}={v}" for k, v in by_type.items())
            retriever_info += f"""
            <div>query: {_h(rb.get('query', ''))[:60]} → retrieved={rb.get('total_retrieved', 0)} ({type_str})</div>"""

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Context-OS Benchmark Report</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           max-width: 1000px; margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }}
    h1 {{ color: #58a6ff; border-bottom: 2px solid #30363d; padding-bottom: 10px; }}
    h2 {{ color: #8b949e; margin-top: 30px; }}
    h3 {{ color: #c9d1d9; }}
    .score {{ font-size: 2em; font-weight: bold; text-align: center; padding: 20px; }}
    .grade-A {{ color: #3fb950; }}
    .grade-B {{ color: #d29922; }}
    .grade-C {{ color: #f85149; }}
    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
    th, td {{ border: 1px solid #30363d; padding: 8px 12px; text-align: left; }}
    th {{ background: #161b22; color: #8b949e; }}
    tr:nth-child(even) {{ background: #161b22; }}
    .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin: 20px 0; }}
    .summary-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; text-align: center; }}
    .summary-card .value {{ font-size: 1.5em; font-weight: bold; }}
    .summary-card .label {{ font-size: 0.8em; color: #8b949e; }}
    .timeline {{ background: #161b22; padding: 10px; border-radius: 8px; font-family: monospace; }}
    .timeline div {{ margin: 3px 0; }}
    .section {{ margin: 20px 0; padding: 15px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; }}
    .footer {{ margin-top: 30px; text-align: center; color: #484f58; font-size: 0.8em; }}
</style>
</head>
<body>
<h1>🧪 Context-OS Benchmark Report</h1>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="score grade-{self._grade(summary.get('memory_avg_final_score', 0))}">
    Overall Score: {summary.get('memory_avg_final_score', 0):.1%}
</div>

<div class="summary-grid">
    <div class="summary-card">
        <div class="value grade-{self._grade(summary.get('memory_avg_final_score', 0))}">{summary.get('memory_avg_final_score', 0):.1%}</div>
        <div class="label">Memory Accuracy</div>
    </div>
    <div class="summary-card">
        <div class="value">{summary.get('module_pass_rate', 0):.0%}</div>
        <div class="label">Module Pass Rate</div>
    </div>
    <div class="summary-card">
        <div class="value" style="color: {'#3fb950' if summary.get('memory_improvement', 0) > 0 else '#d29922'}">
            {summary.get('memory_improvement', 0):+.1%}</div>
        <div class="label">vs SimpleAgent</div>
    </div>
</div>

<h2>Module Tests</h2>
<table>
<tr><th>Case</th><th>Module</th><th>Status</th></tr>
{module_rows}
</table>

<h2>Pipeline Test</h2>
{pipeline_info}

<h2>Memory Benchmark</h2>
<table>
<tr><th>Case</th><th>Description</th><th>Simple</th><th>Keyword</th><th>Judge</th><th>Final</th><th>Pass</th></tr>
{mem_rows}
</table>

<h2>Retriever Benchmark</h2>
<div class="section">{retriever_info}</div>

<div class="footer">Context-OS Benchmark Framework</div>
</body>
</html>"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        return filepath

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 0.90:
            return "A"
        elif score >= 0.70:
            return "B"
        else:
            return "C"

    # ═══════════════════════════════════════════════════════════════
    # 控制台报告
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def print_console_summary(results: dict[str, Any]):
        """打印控制台汇总报告。"""
        summary = results.get("summary", {})
        mem_benchmarks = results.get("memory_benchmarks", [])
        module_tests = results.get("module_tests", [])

        print()
        print("=" * 60)
        print("  Context-OS Benchmark Summary")
        print("=" * 60)

        # Modules
        if module_tests:
            print(f"\n  ── Module Tests ──")
            for mt in module_tests:
                for mod in mt.get("modules", []):
                    status = "✅" if mod.get("passed") else "❌"
                    name = mod.get("name", "?")
                    if name != "Performance":
                        print(f"  {status} {mt.get('case_id', '?')}: {name}")

        # Memory
        if mem_benchmarks:
            print(f"\n  ── Memory Benchmark ──")
            print(f"  {'Case':6s} │ {'Simple':8s} │ {'Keyword':8s} │ {'Judge':8s} │ {'Final':8s} │ Pass")
            print(f"  {'─'*6}┼{'─'*10}┼{'─'*10}┼{'─'*10}┼{'─'*10}┼{'─'*6}")
            for mb in mem_benchmarks:
                status = "✅" if mb.get("passed") else "❌"
                print(f"  {mb.get('case_id', '?'):6s} │ {mb.get('simple_avg_score', 0):.0%}     │ "
                      f"{mb.get('avg_keyword_score', 0):.0%}     │ {mb.get('avg_judge_score', 0):.0%}     │ "
                      f"{mb.get('avg_final_score', 0):.0%}     │ {status}")

        # Intent
        intent_results = results.get("intent_benchmarks", [])
        if intent_results:
            print(f"\n  ── Intent Benchmark ──")
            for ir in intent_results:
                print(f"  {ir.get('case_id', '?'):6s}: Accuracy={ir.get('avg_intent_accuracy', 0):.1%}")

        # Scoring Dashboard
        dashboard = results.get("dashboard", {})
        if dashboard:
            print(f"\n  ── Scoring Dashboard ──")
            modules_to_show = ["intent", "collection", "builder", "memory", "recall",
                               "compression", "feedback", "reflection", "tool", "pipeline"]
            for mod in modules_to_show:
                score = dashboard.get(mod)
                if score is None:
                    print(f"  {mod:12s}   N/A   (未测试)")
                else:
                    bar = "█" * int(score * 30)
                    print(f"  {mod:12s} {score:5.1%} {bar}")
            print(f"  {'─' * 50}")
            grade = dashboard.get('grade', 'N/A')
            overall = dashboard.get('overall', 0)
            print(f"  {'Overall':12s} {overall:.1%}  Grade: {grade}")

        # Scores
        print(f"\n  ── Summary ──")
        print(f"  Memory Accuracy:       {summary.get('memory_avg_final_score', 0):.1%}")
        print(f"  SimpleAgent:           {summary.get('simple_avg_final_score', 0):.1%}")
        print(f"  Improvement:           {summary.get('memory_improvement', 0):+.1%}")
        print(f"  Module Pass Rate:      {summary.get('module_pass_rate', 0):.0%}")
        print(f"  Tests Passed:          {summary.get('memory_test_cases_passed', 0)}/{summary.get('total_test_cases', 0)}")
        print(f"  Overall Score:         {summary.get('overall_score', 0):.1%}  ({summary.get('grade', 'N/A')})")

        print()
        print("=" * 60)
