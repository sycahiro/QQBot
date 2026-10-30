from types import SimpleNamespace

import pytest

from QQBot.desktop.frontend import _with_theme
from QQBot.main import _watch_window


def test_watchdog_recovers_after_prune_and_window_errors_without_losing_focus_request(tmp_path):
    file = tmp_path / "focus.request"
    file.write_text("fixture")
    calls = []
    iterations = []

    class Stop:
        def wait(self, delay):
            iterations.append(delay)
            return len(iterations) > 2

    class Storage:
        count = 0

        def sweep(self):
            self.count += 1
            if self.count == 1:
                raise OSError("temporary sweep error")

    class Window:
        count = 0

        def restore(self):
            self.count += 1
            if self.count == 1:
                raise RuntimeError("temporary window error")
            calls.append("restore")

        def show(self):
            calls.append("show")

    storage = Storage()
    window = Window()
    _watch_window(
        SimpleNamespace(runtime=tmp_path),
        window,
        SimpleNamespace(_storage=storage),
        Stop(),
    )
    assert (
        storage.count == 2
        and window.count == 2
        and calls == ["restore", "show"]
        and not file.exists()
    )
    assert iterations == [0.25, 0.5, 0.25]


def test_theme_injection_accepts_head_attributes_and_rejects_missing_or_duplicate_heads():
    html = _with_theme(
        '<!doctype html><html><HEAD data-test="yes"></HEAD><body>$&</body></html>', "dark"
    )
    assert (
        '<HEAD data-test="yes"><script>window.__QQBOT_THEME__="dark";</script>' in html
        and "$&" in html
    )
    for invalid in ("<!doctype html><body></body>", "<head></head><head></head>"):
        with pytest.raises(RuntimeError, match="head"):
            _with_theme(invalid, "light")
