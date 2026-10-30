import json
from types import SimpleNamespace

import pytest

from QQBot.desktop.contacts import read
from QQBot.desktop.paths import DesktopPaths
from QQBot.desktop.resident import DEFAULTS, Residence, UserStartup
from QQBot.qq.engine import EngineError


class Startup:
    def __init__(self):
        self.value = False
        self.writes = []

    def enabled(self):
        return self.value

    def set(self, value):
        self.value = value
        self.writes.append(value)


@pytest.mark.parametrize("text", ["{broken", "[]", '{"trayEnabled":"yes","startup":true}'])
def test_corrupt_residence_options_do_not_block_startup_or_overwrite_original(tmp_path, text):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    file = runtime / "settings" / "preferences.json"
    file.parent.mkdir(parents=True)
    file.write_text(text, encoding="utf-8")
    startup = Startup()
    resident = Residence(
        DesktopPaths(tmp_path, runtime), startup=startup, tray_factory=lambda *_: None
    )
    assert resident.read() == {**DEFAULTS, "trayReady": False} and not startup.writes
    assert file.read_text() == text
    resident.close()


class Event:
    def __iadd__(self, callback):
        return self


class Window:
    def __init__(self):
        self.calls = []
        self.events = SimpleNamespace(closing=Event(), shown=Event())

    def hide(self):
        self.calls.append("hide")

    def restore(self):
        self.calls.append("restore")

    def show(self):
        self.calls.append("show")

    def destroy(self):
        self.calls.append("destroy")

    def evaluate_js(self, script):
        self.calls.append("prompt")
        return True


class Tray:
    def __init__(self, icon, show, exit_app, theme):
        self.show = show
        self.exit = exit_app
        self.ready = False
        self.theme = theme

    def start(self):
        self.ready = True

    def close(self):
        self.ready = False


def fixture(tmp_path, factory=Tray):
    startup = Startup()
    window = Window()
    resident = Residence(
        DesktopPaths(tmp_path, tmp_path / "runtime"), startup=startup, tray_factory=factory
    )
    resident.attach(window)
    resident.mark_ready()
    return resident, startup, window


def test_default_close_asks_without_writing_startup_or_preferences(tmp_path):
    resident, startup, window = fixture(tmp_path)
    resident._on_shown()
    assert resident.read() == {**DEFAULTS, "trayReady": False}
    assert ask(resident) is False and window.calls == ["prompt"] and not startup.writes
    resident._prompt_thread.join(1)
    assert ask(resident) is False and window.calls == ["prompt"]
    resident.resolve_close("cancel")
    assert ask(resident) is False and window.calls == ["prompt", "prompt"]
    resident.resolve_close("exit")
    assert ask(resident) is True and window.calls[-1] == "destroy"
    assert not (tmp_path / "runtime" / "settings" / "preferences.json").exists()
    resident.close()


def test_close_to_tray_restore_exit_and_restart_persistence(tmp_path):
    resident, startup, window = fixture(tmp_path)
    options = {"trayEnabled": True, "startup": True}
    resident.save(options)
    assert startup.writes == [True] and resident.read()["trayReady"]
    assert ask(resident) is False and window.calls == ["prompt"]
    resident.resolve_close("hide")
    assert window.calls[-1] == "hide"
    resident._tray.show()
    assert window.calls[-2:] == ["restore", "show"]
    resident._tray.exit()
    assert ask(resident) is True and window.calls[-1] == "destroy"
    resident.close()
    reopened = Residence(
        DesktopPaths(tmp_path, tmp_path / "runtime"), startup=startup, tray_factory=Tray
    )
    reopened.attach(Window())
    reopened._on_shown()
    assert reopened.read() == {**options, "trayReady": True}
    reopened.close()


def test_tray_failure_or_dead_icon_never_hides_window_or_enables_startup(tmp_path):
    class Failing(Tray):
        def start(self):
            raise ValueError("托盘图标未就绪")

    resident, startup, window = fixture(tmp_path, Failing)
    with pytest.raises(ValueError):
        resident.save({"trayEnabled": True, "startup": True})
    assert ask(resident) is False and not startup.writes
    with pytest.raises(ValueError):
        resident.resolve_close("hide")
    assert "hide" not in window.calls
    resident.resolve_close("exit")
    assert ask(resident) is True
    resident, startup, window = fixture(tmp_path)
    resident.save({"trayEnabled": True, "startup": False})
    resident._tray.ready = False
    assert ask(resident) is False and window.calls == ["prompt"]
    resident.resolve_close("hide")
    assert resident.read()["trayReady"] and window.calls[-1] == "hide"
    resident.close()


def test_disable_tray_and_user_startup_and_rollback_failed_file_write(tmp_path, monkeypatch):
    resident, startup, _window = fixture(tmp_path)
    options = {"trayEnabled": True, "startup": True}
    resident.save(options)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("QQBot.desktop.resident.save_state", fail)
    with pytest.raises(OSError):
        resident.save(dict(DEFAULTS))
    assert resident.read() == {**options, "trayReady": True}
    assert json.loads((tmp_path / "runtime" / "settings" / "preferences.json").read_text()) == options
    monkeypatch.undo()
    resident.save(dict(DEFAULTS))
    assert resident._tray is None and startup.value is False and ask(resident) is False
    resident.close()


def test_invalid_options_never_change_startup(tmp_path):
    resident, startup, _window = fixture(tmp_path)
    for options in [
        {},
        {**DEFAULTS, "other": False},
        {**DEFAULTS, "startup": 1},
        {**DEFAULTS, "closeToTray": True},
    ]:
        with pytest.raises(ValueError):
            resident.save(options)
    assert not startup.writes


def test_hide_on_demand_does_not_change_preferences_and_old_silent_hide_is_ignored(tmp_path):
    paths = DesktopPaths(tmp_path, tmp_path / "runtime")
    paths.runtime.mkdir()
    (paths.runtime / "settings").mkdir(parents=True)
    (paths.runtime / "settings" / "preferences.json").write_text(
        json.dumps({"trayEnabled": False, "closeToTray": True, "startup": False})
    )
    resident = Residence(paths, startup=Startup(), tray_factory=Tray)
    window = Window()
    resident.attach(window)
    resident.mark_ready()
    assert resident.read() == {**DEFAULTS, "trayReady": False}
    assert ask(resident) is False and window.calls == ["prompt"]
    resident.resolve_close("hide")
    assert resident.read() == {**DEFAULTS, "trayReady": True}
    assert json.loads((paths.runtime / "settings" / "preferences.json").read_text())["closeToTray"] is True
    with pytest.raises(ValueError):
        resident.resolve_close("exit")
    resident.close()


def test_unloaded_or_broken_dialog_can_still_close(tmp_path):
    resident, _, window = fixture(tmp_path)
    resident._ui_ready = False
    assert ask(resident) is True and not window.calls
    resident.mark_ready()
    window.evaluate_js = lambda _: False
    assert ask(resident) is False
    resident._prompt_thread.join(1)
    assert resident._exiting and window.calls == ["destroy"]
    resident, _, window = fixture(tmp_path)

    def fail(_):
        raise RuntimeError("renderer unavailable")

    window.evaluate_js = fail
    assert ask(resident) is False
    resident._prompt_thread.join(1)
    assert resident._exiting and window.calls == ["destroy"]
    with pytest.raises(ValueError):
        resident.resolve_close("other")
    resident.close()


def test_startup_command_quotes_source_paths_and_is_project_specific(tmp_path):
    paths = DesktopPaths(tmp_path / "path with spaces", tmp_path / "runtime")
    startup = UserStartup(paths)
    assert "pythonw.exe" in startup.command and "--port" not in startup.command
    assert " --no-dialog" in startup.command and " -B " in startup.command
    assert '"' + str(paths.root / "src" / "DesktopShell" / "start.py") + '"' in startup.command
    assert startup.name != UserStartup(DesktopPaths(tmp_path / "other", tmp_path / "runtime")).name


def test_contacts_native_queries_normalize_dedupe_and_preserve_remarks():
    class Connection:
        def __init__(self):
            self.calls = []

        def invoke(self, action, *, expected_account):
            self.calls.append((action, expected_account))
            rows = (
                [
                    {"group_id": 123, "group_name": "测试群"},
                    {"group_id": "bad"},
                    {"group_id": 123, "group_name": "群名更新"},
                ]
                if action == "get_group_list"
                else [
                    {"user_id": 456, "nickname": "昵称", "remark": "备注"},
                    {"user_id": False},
                    {"user_id": 789, "nickname": "另一位"},
                ]
            )
            return {"status": "ok", "data": rows}

    connection = Connection()
    contacts = read(connection, "12345678")
    assert contacts["groups"] == [{"id": "123", "name": "群名更新"}]
    assert {"id": "456", "name": "备注"} in contacts["private"] and len(contacts["private"]) == 2
    assert connection.calls == [("get_group_list", "12345678"), ("get_friend_list", "12345678")]


def test_contacts_failed_query_does_not_return_partial_list():
    class Connection:
        def invoke(self, *args, **kwargs):
            return {"status": "failed", "data": []}

    with pytest.raises(EngineError, match="联系人列表"):
        read(Connection(), "12345678")


def ask(resident):
    result = resident.on_closing()
    if resident._prompt_thread:
        resident._prompt_thread.join(1)
    return result


def test_close_dispatch_does_not_wait_for_renderer_on_native_ui_thread(tmp_path):
    import threading

    resident, _, window = fixture(tmp_path)
    reached = threading.Event()
    release = threading.Event()

    def evaluate(_):
        reached.set()
        assert release.wait(2)
        return True

    window.evaluate_js = evaluate
    try:
        assert resident.on_closing() is False
        assert reached.wait(1)
        assert resident._prompt_thread.is_alive()
    finally:
        release.set()
        resident._prompt_thread.join(2)
        resident.close()
