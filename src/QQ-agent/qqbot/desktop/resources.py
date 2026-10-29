"""Windows 主机资源采样；只读取本机及本应用进程树，不管理其他进程。"""

import os
import platform
import threading
import time
import winreg

import psutil


def processor_name():
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        return platform.processor() or "处理器信息暂不可用"


class ResourceMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = psutil.Process()
        self._hostname = platform.node()
        self._processor = processor_name()
        self._cores = os.cpu_count() or 1
        self._previous = psutil.cpu_times()
        self._sampled_at = time.monotonic()
        self._cached_at = 0.0
        self._cached = None

    def sample(self):
        with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < 1:
                return self._cached
            current = psutil.cpu_times()
            # Windows interrupt/DPC times are included in system time already.
            busy = (current.user - self._previous.user) + (current.system - self._previous.system)
            idle = current.idle - self._previous.idle
            total = busy + idle
            cpu = (
                round(max(0, min(100, busy / total * 100)), 1)
                if total > 0 and busy >= 0 and idle >= 0 and now - self._sampled_at >= 0.25
                else None
            )
            memory = psutil.virtual_memory()
            app_memory = 0
            try:
                children = self._process.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []
            for process in [self._process, *children]:
                try:
                    app_memory += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # A renderer may exit between discovery and the memory read.
                    continue
            self._cached = {
                "hostname": self._hostname,
                "cpuModel": self._processor,
                "logicalCores": self._cores,
                "cpuPercent": cpu,
                "memoryTotal": memory.total,
                "memoryUsed": memory.total - memory.available,
                "memoryPercent": memory.percent,
                "appMemory": app_memory,
            }
            self._cached_at = now
            if now - self._sampled_at >= 0.25:
                self._previous, self._sampled_at = current, now
            return self._cached
