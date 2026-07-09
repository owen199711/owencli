"""ConfigManager — 支持 mtime 热加载。"""
from __future__ import annotations
import logging, os, time, re, yaml
from pathlib import Path
from threading import Lock, Thread
from typing import Optional
from context_os.config.app_config import AppConfig, from_dict

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        self._path = Path(config_path)
        self._lock = Lock()
        self._current: Optional[AppConfig] = None
        self._last_modified: float = 0
        self._watcher_thread: Optional[Thread] = None
        self._running = False
        self._reload()

    def get(self) -> AppConfig:
        if self._current is None: self._reload()
        return self._current

    def check_for_update(self) -> bool:
        if not self._path.exists(): return False
        lm = self._path.stat().st_mtime
        if lm > self._last_modified:
            self._reload()
            return True
        return False

    def start_watching(self, interval_sec: int = 30) -> None:
        if self._running: return
        self._running = True
        self._watcher_thread = Thread(target=self._watch_loop, args=(interval_sec,), daemon=True)
        self._watcher_thread.start()
        logger.info("ConfigWatcher started: %s every %ds", self._path, interval_sec)

    def stop_watching(self) -> None:
        self._running = False

    def _reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                logger.warning("Config not found: %s, using defaults", self._path)
                self._current = AppConfig()
                self._current.loaded_at = time.time()
                return
            try:
                raw = self._path.read_text(encoding="utf-8")
                resolved = self._resolve_env_vars(raw)
                data = yaml.safe_load(resolved) or {}
                cfg = from_dict(data)
                cfg.loaded_at = time.time()
                self._current = cfg
                self._last_modified = self._path.stat().st_mtime
                logger.info("Config loaded: %s (%d bytes)", self._path, len(raw))
            except Exception as e:
                logger.error("Failed to load config: %s", e)

    def _watch_loop(self, interval_sec: int) -> None:
        while self._running:
            try:
                if self.check_for_update():
                    logger.info("Config hot-reloaded: %s", self._path)
            except Exception as e:
                logger.warning("Config watch error: %s", e)
            time.sleep(interval_sec)

    @staticmethod
    def _resolve_env_vars(value: str) -> str:
        _pat = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")
        def _rep(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        return _pat.sub(_rep, value)
