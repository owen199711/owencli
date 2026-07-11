"""MaintenanceWorker — 定时维护调度器。

五维生命周期管理:
    Merge / Forget / Decay / Archive / Summarize + Journal 清理

依赖 Phase 2 (Journal), Phase 5 (LongTerm Fact/Summary).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore

logger = get_logger(__name__)


@dataclass
class ScheduleConfig:
    """维护任务调度配置（秒）。"""

    merge_interval: int = 3600       # 1 小时
    forget_interval: int = 86400     # 24 小时
    decay_interval: int = 21600      # 6 小时
    archive_interval: int = 604800   # 7 天
    summarize_interval: int = 86400  # 24 小时
    journal_cleanup_interval: int = 86400  # 24 小时


class MaintenanceWorker:
    """维护工作器 — 定时触发各类维护任务。

    使用方式:
        worker = MaintenanceWorker(ltm=..., store=..., experience=...)
        worker.start()
        ...
        await worker.stop()

    任务调度:
        merge         每 1h:   精确/语义/实体/Experience 合并；Fact history>10 截断
        forget        每 24h:  TTL 过期 + 低价值清理 + 纠正标记
        decay         每 6h:   relevance_score 衰减；Summary 更快的半衰期
        archive       每 7d:   >180 天的冷数据归档
        summarize     每 24h:  同 session Summary 合并；同 entity 时间线
        journal       每 24h:  processed>30d 删除；总量>10000 裁剪
    """

    def __init__(
        self,
        ltm: Any,
        store: SQLiteStore,
        experience: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        schedule: Optional[ScheduleConfig] = None,
    ) -> None:
        from context_os.maintenance.archive import ArchiveTask
        from context_os.maintenance.decay import DecayTask
        from context_os.maintenance.forget import ForgetTask
        from context_os.maintenance.merge import MergeTask
        from context_os.maintenance.summarizer import SummarizeTask

        self._ltm = ltm
        self._store = store
        self._experience = experience
        self._event_bus = event_bus
        self._schedule = schedule or ScheduleConfig()

        self._merge = MergeTask(ltm=ltm, store=store, experience=experience)
        self._forget = ForgetTask(ltm=ltm, store=store, experience=experience)
        self._decay = DecayTask(ltm=ltm, store=store, experience=experience)
        self._archive = ArchiveTask(ltm=ltm, store=store, experience=experience)
        self._summarize = SummarizeTask(ltm=ltm, store=store, experience=experience)

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_runs: dict[str, float] = {}

        logger.info(
            "MaintenanceWorker initialized (merge=%ds, forget=%ds, decay=%ds, "
            "archive=%ds, summarize=%ds, journal=%ds)",
            self._schedule.merge_interval,
            self._schedule.forget_interval,
            self._schedule.decay_interval,
            self._schedule.archive_interval,
            self._schedule.summarize_interval,
            self._schedule.journal_cleanup_interval,
        )

    # ── 生命周期 ────────────────────────────────────────────

    def start(self) -> None:
        """启动维护工作器（同步入口，创建后台 asyncio task）。"""
        if self._running:
            logger.warning("MaintenanceWorker already running")
            return

        self._running = True
        self._task = asyncio.ensure_future(self._worker_loop())
        logger.info("MaintenanceWorker started")

    async def stop(self) -> None:
        """停止维护工作器。"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MaintenanceWorker stopped")

    # ── 主循环 ──────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """后台维护循环。"""
        tick = 60  # 每秒检查一次调度
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Maintenance tick failed", exc_info=True)

            # 分步 sleep，便于快速退出
            for _ in range(tick):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _tick(self) -> None:
        """单次调度检查。"""
        now = time.time()

        # 检查各任务是否需要执行
        await self._maybe_run("merge", self._schedule.merge_interval, now)
        await self._maybe_run("forget", self._schedule.forget_interval, now)
        await self._maybe_run("decay", self._schedule.decay_interval, now)
        await self._maybe_run("archive", self._schedule.archive_interval, now)
        await self._maybe_run("summarize", self._schedule.summarize_interval, now)
        await self._maybe_run("journal_cleanup", self._schedule.journal_cleanup_interval, now)

    async def _maybe_run(self, name: str, interval: int, now: float) -> None:
        """按间隔调度运行任务。"""
        last = self._last_runs.get(name, 0)
        if now - last < interval:
            return

        self._last_runs[name] = now
        logger.debug("Maintenance: running %s...", name)

        try:
            if name == "merge":
                await self._merge.run()
            elif name == "forget":
                await self._forget.run()
            elif name == "decay":
                await self._decay.run()
            elif name == "archive":
                await self._archive.run()
            elif name == "summarize":
                await self._summarize.run()
            elif name == "journal_cleanup":
                await self._store.cleanup_journal()
        except Exception:
            logger.warning("Maintenance task '%s' failed", name, exc_info=True)

    # ── 手动触发（调试用） ──────────────────────────────────

    async def run_merge(self) -> int:
        """手动触发 Merge。"""
        return await self._merge.run()

    async def run_forget(self) -> int:
        """手动触发 Forget。"""
        return await self._forget.run()

    async def run_decay(self) -> int:
        """手动触发 Decay。"""
        return await self._decay.run()

    async def run_archive(self) -> int:
        """手动触发 Archive。"""
        return await self._archive.run()

    async def run_summarize(self) -> int:
        """手动触发 Summarize。"""
        return await self._summarize.run()

    async def run_journal_cleanup(self) -> int:
        """手动触发 Journal 清理。"""
        return await self._store.cleanup_journal()
