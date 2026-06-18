"""执行轨迹记录器。

记录完整 Pipeline 执行过程，用于 Debug、Replay、评估。
"""

from __future__ import annotations

import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from context_os.core.logger import get_logger
from context_os.core.models import Trace, TraceStep

logger = get_logger(__name__)


class Tracer:
    """执行轨迹记录器。

    记录每个步骤的输入、输出、耗时，最后输出到 JSON 文件。

    Args:
        storage_dir: 轨迹文件存储目录。
    """

    def __init__(self, storage_dir: str = "./data/traces"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current: Optional[Trace] = None
        self._step_timer: float = 0.0
        logger.info("Tracer initialized: storage=%s", self.storage_dir)

    def start(self, task_id: str, raw_input: str) -> str:
        """开始一个新的轨迹记录。

        Args:
            task_id: 任务 ID。
            raw_input: 原始用户输入。

        Returns:
            轨迹 ID。
        """
        self._current = Trace(task_id=task_id, raw_input=raw_input)
        logger.debug("Trace started: id=%s, task=%s", self._current.id, task_id)
        return self._current.id

    def step_begin(self, step_name: str) -> TraceStep:
        """记录一个步骤的开始。

        Args:
            step_name: 步骤名称。

        Returns:
            创建的 TraceStep。
        """
        self._step_timer = time.time()
        step = TraceStep(
            step_name=step_name,
            duration_ms=0.0,
            input_preview="",
            output_preview="",
        )
        logger.debug("Step begin: %s", step_name)
        return step

    def step_end(self, step: TraceStep, input_text: str, output_text: str) -> None:
        """记录一个步骤的结束。

        Args:
            step: step_begin 返回的 TraceStep。
            input_text: 输入预览。
            output_text: 输出预览。
        """
        step.duration_ms = (time.time() - self._step_timer) * 1000
        step.input_preview = input_text[:200]
        step.output_preview = output_text[:200]
        if self._current:
            self._current.steps.append(step)
            self._current.total_latency_ms += step.duration_ms
        logger.debug(
            "Step end: %s, duration=%.0fms, total=%.0fms",
            step.step_name, step.duration_ms,
            self._current.total_latency_ms if self._current else 0,
        )

    def finish(self, success: bool) -> None:
        """完成轨迹记录并保存。

        Args:
            success: 是否成功。
        """
        if not self._current:
            return
        self._current.success = success
        self._save(self._current)
        logger.info(
            "Trace finished: id=%s, success=%s, total_latency=%.0fms, steps=%d",
            self._current.id, success, self._current.total_latency_ms,
            len(self._current.steps),
        )
        self._current = None

    def _save(self, trace: Trace) -> None:
        """保存轨迹到 JSON 文件。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trace_{trace.id}_{timestamp}.json"
        path = self.storage_dir / filename
        path.write_text(trace.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("Trace saved: %s", path)
