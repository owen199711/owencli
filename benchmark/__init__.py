"""Context-OS Benchmark Framework.

一套完整的基准测试框架，用于验证 Context-OS 每个模块的正确性和性能。

架构:
    run.py → BenchmarkRunner → ModuleTest / PipelineTest / MemoryTest / RetrieverTest
                                        ↓
                                EvaluationEngine
                                        ↓
                                JSON / HTML Report

用法:
    python -m benchmark.run                         # 完整 Benchmark
    python -m benchmark.run --module intent         # 只测 Intent Layer
    python -m benchmark.run --module pipeline       # 只测 Pipeline
    python -m benchmark.run --output ./my_report    # 自定义输出目录
"""

from benchmark.benchmark_runner import BenchmarkRunner
from benchmark.observer import PipelineObserver
from benchmark.evaluator import EvaluationEngine
from benchmark.reporter import ReportGenerator
from benchmark.datasets.memory_cases import TestCase

__all__ = [
    "BenchmarkRunner",
    "PipelineObserver",
    "EvaluationEngine",
    "ReportGenerator",
    "TestCase",
]
