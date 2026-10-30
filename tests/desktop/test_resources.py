from types import SimpleNamespace

import psutil
import pytest

from QQBot.desktop import resources


def test_cpu_sampling_cache_and_windows_interrupt_accounting(monkeypatch):
    clock = [0.0]
    times = [SimpleNamespace(user=50, system=50, idle=100, interrupt=10, dpc=10)]
    monkeypatch.setattr(resources.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(resources.psutil, "cpu_times", lambda: times[0])
    monitor = resources.ResourceMonitor()
    assert monitor.sample()["cpuPercent"] is None  # No invented initial zero.
    clock[0] = 0.5
    assert monitor.sample()["cpuPercent"] is None  # Cached, no tiny-interval spikes.
    clock[0] = 2
    times[0] = SimpleNamespace(user=70, system=70, idle=160, interrupt=30, dpc=30)
    assert monitor.sample()["cpuPercent"] == pytest.approx(40)
    # Interrupt and DPC fields must not be counted a second time on Windows.
    clock[0] = 4
    times[0] = SimpleNamespace(user=1, system=1, idle=1)
    assert monitor.sample()["cpuPercent"] is None  # Reset counters are not usage.


def test_application_memory_is_own_tree_and_tolerates_child_exit(monkeypatch):
    class Child:
        def __init__(self, rss):
            self.rss = rss

        def memory_info(self):
            if self.rss is None:
                raise psutil.NoSuchProcess(99999999)
            return SimpleNamespace(rss=self.rss)

    class Parent(Child):
        def children(self, recursive):
            assert recursive is True
            return [Child(200), Child(None)]

    monkeypatch.setattr(resources.psutil, "Process", lambda: Parent(100))
    monitor = resources.ResourceMonitor()
    result = monitor.sample()
    assert result["appMemory"] == 300
    assert result["memoryUsed"] <= result["memoryTotal"]
