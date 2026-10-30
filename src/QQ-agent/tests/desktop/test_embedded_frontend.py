import json
import threading
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from qqbot.desktop.appearance import Appearance
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.frontend import FrontendDocument
from qqbot.desktop.paths import DesktopPaths

ROOT = Path(__file__).resolve().parents[4]


def source(tmp_path, code):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "prepare.mjs").write_text(code, encoding="utf-8")
    paths = DesktopPaths(ROOT, tmp_path / "runtime")
    return SimpleNamespace(
        node=paths.node, frontend=frontend, runtime=paths.runtime, logs=paths.logs
    )


@pytest.mark.parametrize(
    "code",
    [
        'process.stdout.write("not-json")',
        'process.stdout.write(JSON.stringify({html:"bad"}))',
        'process.stdout.write(JSON.stringify({html:"<!doctype html>"+"x".repeat(1600000)}))',
        "process.exit(2)",
        'process.stdout.write("x".repeat(9*1024*1024))',
    ],
)
def test_invalid_failed_and_oversized_compiler_results_leave_no_child(tmp_path, code):
    document = FrontendDocument(source(tmp_path, code))
    with pytest.raises(RuntimeError):
        document.prepare()
    assert document.process.poll() is not None and document.html is None
    assert document._reader is None or not document._reader.is_alive()
    document.close()


def test_compile_timeout_kills_and_drains_only_owned_child(tmp_path):
    document = FrontendDocument(source(tmp_path, "setInterval(()=>{},1000)"))
    with pytest.raises(RuntimeError, match="超时"):
        document.prepare(timeout=0.1)
    assert document.process.poll() is not None and not document._reader.is_alive()


def test_actual_compile_process_never_listens_and_writes_no_dist(tmp_path):
    document = FrontendDocument(DesktopPaths(ROOT, tmp_path))
    done = threading.Event()
    found = []

    def sample():
        while not done.wait(0.01):
            child = document.process
            if not child:
                continue
            try:
                for item in psutil.Process(child.pid).net_connections(kind="inet"):
                    if item.status == psutil.CONN_LISTEN:
                        found.append(item.laddr)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    try:
        page = document.prepare()
        assert document.process.poll() == 0 and '<div id="root">' in page
        assert not found and not (ROOT / "src/DesktopShell/frontend/dist").exists()
        assert list(tmp_path.iterdir()) == [tmp_path / "logs"]
        assert (document.paths.logs / "frontend.log").exists()
    finally:
        done.set()
        watcher.join(timeout=2)
        document.close()


def test_theme_is_local_validated_and_survives_reopen_without_browser_storage(tmp_path):
    file = tmp_path / "settings" / "appearance.json"
    appearance = Appearance(file)
    assert appearance.read() == "system"
    bridge = DesktopBridge(DesktopPaths(ROOT, tmp_path), lambda **_: None)
    assert bridge.save_theme("dark") == {"ok": True, "theme": "dark"}
    assert Appearance(file).read() == "dark"
    for invalid in [None, True, "../outside", {}, "blue"]:
        assert not bridge.save_theme(invalid)["ok"]
        assert appearance.read() == "dark"
    assert bridge.save_theme("system")["ok"]
    assert json.loads(file.read_text()) == {"theme": "system"}
    bridge._reviews.close()


def test_main_passes_html_and_disables_framework_server(tmp_path, monkeypatch):
    import qqbot.main as application
    import webview

    records = {}

    class Document:
        def __init__(self, *_):
            pass

        def prepare(self, theme):
            records["theme"] = theme
            return "<!doctype html><p>fixture</p>"

        def close(self):
            records["closed"] = True

    class Discovery:
        def __init__(self, *_):
            pass

        def close(self):
            pass

    class Connection:
        def __init__(self, *_, **kw):
            pass

        def close(self):
            pass

    class Event:
        def __iadd__(self, callback):
            return self

    class Window:
        events = SimpleNamespace(
            shown=Event(), closed=Event(), closing=Event(), before_show=Event()
        )

    def create(title, url=None, **kwargs):
        records.update(
            url=url, html=kwargs.get("html"), width=kwargs["width"], height=kwargs["height"]
        )
        return Window()

    def start(**kwargs):
        assert kwargs["http_server"] is False
        records["started"] = True

    monkeypatch.setattr(application, "FrontendDocument", Document)
    monkeypatch.setattr(application, "SnowLumaDiscovery", Discovery)
    monkeypatch.setattr(application, "QqConnection", Connection)
    monkeypatch.setattr(webview, "create_window", create)
    monkeypatch.setattr(webview, "start", start)
    assert application.run_primary(DesktopPaths(ROOT, tmp_path)) == 0
    assert records["url"] is None and records["html"].startswith("<!doctype html>")
    assert records["closed"] and records["started"]
    assert (records["width"], records["height"]) == (1520, 980)
    state = json.loads((tmp_path / "state" / "app.json").read_text())
    assert (
        state["phase"] == "stopped" and state["frontendMode"] == "embedded" and "port" not in state
    )
