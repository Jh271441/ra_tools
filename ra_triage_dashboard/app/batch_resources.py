"""Opt-in Linux Batch limits, configured only by the service operator.

RSS and scratch are sampled stop thresholds, not kernel quotas. The worker
launcher additionally applies a hard per-process address-space limit.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import signal
import threading
from pathlib import Path


class BatchResourceGuard:
    def __init__(self, cache: Path):
        self.cache = cache.resolve()
        self.enabled = os.getenv("DASHBOARD_BATCH_RESOURCE_GUARD", "false").lower() == "true"
        self.error = ""
        self.process = None
        self.lock = None
        self.thread = None
        self.done = threading.Event()
        self.limits = {}
        if self.enabled:
            for name in ("RSS_BYTES", "ADDRESS_SPACE_BYTES", "SCRATCH_BYTES", "MIN_FREE_BYTES", "MAX_WORKERS"):
                try:
                    value = int(os.environ[f"DASHBOARD_BATCH_{name}"])
                except (KeyError, ValueError):
                    raise RuntimeError(f"DASHBOARD_BATCH_{name} 必须显式配置为正整数。") from None
                if value <= 0 or (name == "MAX_WORKERS" and value > 4):
                    raise RuntimeError(f"DASHBOARD_BATCH_{name} 超出允许范围。")
                self.limits[name] = value

    def __enter__(self):
        if not self.enabled:
            return self
        if not Path("/proc/self/stat").is_file():
            raise RuntimeError("Batch 资源限制需要 Linux /proc。")
        self.cache.mkdir(parents=True, exist_ok=True)
        self.lock = (self.cache / ".worker-resource.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_disk()
            if self.error:
                raise RuntimeError(self.error)
        except Exception:
            self.lock.close()
            self.lock = None
            raise
        return self

    def environment(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        temporary = self.cache / ".worker-tmp"
        temporary.mkdir(mode=0o700, exist_ok=True)
        if temporary.is_symlink():
            raise RuntimeError("Batch 临时目录不能是符号链接。")
        return {
            "TMPDIR": str(temporary),
            "DASHBOARD_BATCH_MAX_WORKERS": str(self.limits["MAX_WORKERS"]),
            "DASHBOARD_BATCH_ADDRESS_SPACE_KIB": str(max(1, self.limits["ADDRESS_SPACE_BYTES"] // 1024)),
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }

    def _check_disk(self):
        total = 0
        def onerror(error):
            raise error

        for directory, _, names in os.walk(self.cache, followlinks=False, onerror=onerror):
            for name in names:
                try:
                    total += (Path(directory) / name).lstat().st_size
                except FileNotFoundError:
                    pass  # A worker can remove its temporary file during sampling.
                if total > self.limits["SCRATCH_BYTES"]:
                    self.error = "Batch scratch 超过服务预算，已停止任务；需清理缓存后重试。"
                    return
        if shutil.disk_usage(self.cache).free < self.limits["MIN_FREE_BYTES"]:
            self.error = "Batch 磁盘可用空间低于保留阈值，已停止任务。"

    @staticmethod
    def group_rss(group: int) -> int:
        pages = 0
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == group:
                    pages += int(fields[21])
            except (FileNotFoundError, ProcessLookupError):
                pass
        return pages * os.sysconf("SC_PAGE_SIZE")

    def start(self, process):
        if not self.enabled:
            return
        self.process = process

        def monitor():
            while not self.done.wait(0.5):
                try:
                    if self.group_rss(process.pid) > self.limits["RSS_BYTES"]:
                        self.error = "Batch worker 进程组内存超过服务预算，已终止。"
                    if not self.error:
                        self._check_disk()
                except Exception:
                    self.error = "Batch 资源监测失败，已停止任务。"
                if self.error:
                    self._kill()
                    return

        self.thread = threading.Thread(target=monitor, name="batch-resource-guard", daemon=True)
        self.thread.start()

    def _kill(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def __exit__(self, exc_type, exc, traceback):
        self.done.set()
        if self.thread is not None:
            self.thread.join()
        self._kill()  # Also reap worker descendants that outlive their parent.
        if self.enabled and not self.error:
            try:
                self._check_disk()
            except Exception:
                self.error = "Batch 资源监测失败，已停止任务。"
        if self.lock is not None:
            self.lock.close()
        if self.error:
            raise RuntimeError(self.error) from None
