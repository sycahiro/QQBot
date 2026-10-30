import json
import sys
from pathlib import Path

import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.frontend import FrontendDocument
from qqbot.desktop.paths import DesktopPaths, save_state
from qqbot.desktop.windows import SingleInstance

ROOT = Path(__file__).resolve().parents[4]


def test_atomic_state_and_live_desktop_information(tmp_path):
    paths = DesktopPaths(ROOT, tmp_path)
    changes = []
    bridge = DesktopBridge(paths, lambda **value: changes.append(value))
    assert {name for name in dir(bridge) if not name.startswith("_")} == {
        "get_bootstrap",
        "get_dependencies",
        "get_resources",
        "mark_ready",
        "window_control",
        "get_qq_processes",
        "get_qq_status",
        "connect_qq_account",
        "disconnect_qq_account",
        "get_archives",
        "get_archive_messages",
        "delete_archive",
        "get_bot_settings",
        "save_bot_settings",
        "get_agent_status",
        "set_auto_reply",
        "get_sessions",
        "get_session",
        "delete_session",
        "get_usage",
        "get_memory_chats",
        "get_memories",
        "save_memory",
        "delete_memory",
        "preview_memory",
        "apply_memory_preview",
        "get_logs",
        "get_diagnostics",
        "get_market",
        "open_market_page",
        "open_project_page",
        "get_model_list",
        "test_model_connection",
        "get_storage",
        "save_storage_settings",
        "cleanup_storage",
        "manage_model_profile",
        "test_web_search",
        "get_stickers",
        "get_sticker_preview",
        "save_sticker",
        "delete_sticker",
        "collect_sticker",
        "import_sticker",
        "expand_forward",
        "get_contacts",
        "process_archive",
        "stop_session",
        "rerun_session",
        "get_desktop_options",
        "save_desktop_options",
        "open_snowluma_webui",
        "get_webui_password_memo",
        "save_webui_password_memo",
        "get_snowluma_status",
        "start_snowluma",
        "stop_snowluma",
        "mark_archive_read",
        "save_theme",
        "resolve_window_close",
        "get_global_settings",
        "save_global_settings",
    }
    info = bridge.get_bootstrap()
    # 不写死小版本：换用 3.14 跑测试时这条不该失败。
    assert info["python"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")
    assert info["qqConnected"] is False and info["autoReply"] is False
    resources = bridge.get_resources()
    assert resources["memoryTotal"] > 0
    assert 0 <= resources["memoryPercent"] <= 100
    assert resources["appMemory"] > 0
    bridge.mark_ready()
    assert changes == [{"uiReady": True}]
    file = tmp_path / "state.json"
    save_state(file, {"phase": "starting"})
    save_state(file, {"phase": "stopped"})
    assert json.loads(file.read_text()) == {"phase": "stopped"}
    assert list(tmp_path.iterdir()) == [file]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop only")
def test_single_instance_requests_focus_and_releases_after_close(tmp_path):
    first = SingleInstance(tmp_path, tmp_path)
    second = None
    try:
        assert first.primary
        second = SingleInstance(tmp_path, tmp_path)
        assert not second.primary
        second.request_focus()
        assert (tmp_path / "focus.request").read_text() == "focus"
    finally:
        if second:
            second.close()
        first.close()
    third = SingleInstance(tmp_path, tmp_path)
    try:
        assert third.primary
    finally:
        third.close()


def test_startup_failure_remains_failed_and_cleanup_still_runs(tmp_path, monkeypatch):
    import qqbot.main as application

    closed = []

    class FailingFrontend:
        def __init__(self, *_):
            pass

        def prepare(self, *_):
            raise RuntimeError("compile failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(application, "FrontendDocument", FailingFrontend)
    with pytest.raises(RuntimeError, match="compile failed"):
        application.run_primary(DesktopPaths(ROOT, tmp_path))
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["phase"] == "failed" and state["uiReady"] is False
    assert state["frontendPid"] is None and "compile failed" in state["error"]
    assert state["frontendMode"] == "embedded" and "port" not in state
    assert closed == [True]


def test_cleanup_failure_never_skips_later_owned_resources_or_final_state():
    from qqbot.main import _cleanup

    closed = []

    def broken():
        closed.append("attachments")
        raise OSError("file locked")

    with pytest.raises(OSError, match="file locked"):
        _cleanup(
            [
                ("attachments", broken),
                ("engine", lambda: closed.append("engine")),
                ("database", lambda: closed.append("database")),
                ("state", lambda: closed.append("state")),
            ]
        )
    assert closed == ["attachments", "engine", "database", "state"]


def test_cleanup_preserves_original_startup_error():
    from qqbot.main import _cleanup

    closed = []

    def broken():
        raise OSError("cleanup failed")

    with pytest.raises(RuntimeError, match="original failure"):
        try:
            raise RuntimeError("original failure")
        finally:
            _cleanup([("attachments", broken), ("engine", lambda: closed.append(True))])
    assert closed == [True]


def test_snowluma_home_is_root_anchored_and_runtime_stays_isolated(tmp_path):
    # SnowLuma 服务家目录固定挂在根 data/ 下，不随 --runtime 漂移；py 状态仍在各自 runtime。
    assert DesktopPaths(ROOT, ROOT / "runtime").snowluma_home == ROOT / "data" / "services" / "snowluma"
    assert DesktopPaths(ROOT, tmp_path).snowluma_home == ROOT / "data" / "services" / "snowluma"
    assert DesktopPaths(ROOT, tmp_path).runtime == tmp_path


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop only")
def test_real_frontend_compiles_in_memory_and_exits_before_window_load(tmp_path):
    import re
    import subprocess

    document = FrontendDocument(DesktopPaths(ROOT, tmp_path))
    try:
        html = document.prepare("dark")
        assert document.process.poll() == 0
        assert (
            not re.search(r"<script[^>]+src=", html)
            and 'src="/src/' not in html
            and "/@vite/client" not in html
        )
        assert 'window.__QQBOT_THEME__="dark"' in html and "data:image/svg+xml;base64," in html
        assert len(html.encode()) < 1500000 and "<style>" in html and html.count("<body>") == 1
        # Parse the inline JS using Node; this catches HTML replacement-string
        # expansion corrupting bundled regex strings containing $&/$`/$'.
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        for script in scripts:
            result = subprocess.run(
                [str(document.paths.node), "--check", "--input-type=commonjs"],
                input=script,
                text=True,
                encoding="utf-8",
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert result.returncode == 0, result.stderr[:1000]
    finally:
        document.close()
