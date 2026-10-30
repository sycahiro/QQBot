import json
import threading
from types import SimpleNamespace

import pytest

from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.diagnostics import read_log_entries
from QQBot.desktop.paths import DesktopPaths
from QQBot.desktop.resident import Residence
from QQBot.desktop.windows import SingleInstance


def test_log_identity_survives_duplicate_text_tail_shift_and_redaction(tmp_path):
    paths = DesktopPaths(tmp_path, tmp_path / "runtime")
    paths.logs.mkdir(parents=True)
    file = paths.logs / "desktop.log"
    file.write_bytes(b"same\n" * 205 + b"secret-key\n")
    before = read_log_entries(paths)
    masked = read_log_entries(paths, ["secret-key"])
    assert [item["id"] for item in masked] == [item["id"] for item in before]
    assert masked[-1]["text"] == "[密钥已隐藏]"
    assert len({item["id"] for item in before}) == 200
    with file.open("ab") as stream:
        stream.write(b"same\n")
    after = read_log_entries(paths)
    assert [item["id"] for item in before[1:]] == [item["id"] for item in after[:-1]]


def test_log_cutoff_discards_partial_credentials_and_bounds_bytes(tmp_path):
    paths = DesktopPaths(tmp_path, tmp_path / "runtime")
    paths.logs.mkdir(parents=True)
    key = "synthetic-key-" * 20
    file = paths.logs / "desktop.log"
    file.write_bytes(b"prefix" + key.encode() + b"\n" + b"x" * 65400 + b"\nlast\n")
    entries = read_log_entries(paths, [key])
    assert entries[-1]["text"] == "last"
    assert all(
        "synthetic-key" not in item["text"] and len(item["text"]) <= 2000 for item in entries
    )


def test_single_instance_owns_runtime_specific_focus_channel(tmp_path):
    first = SingleInstance(tmp_path, tmp_path / "one")
    second = SingleInstance(tmp_path, tmp_path / "two")
    duplicate = SingleInstance(tmp_path, tmp_path / "one")
    try:
        assert first.primary and second.primary and not duplicate.primary
        duplicate.request_focus()
        assert (tmp_path / "one/focus.request").exists()
        assert not (tmp_path / "two/focus.request").exists()
    finally:
        duplicate.close()
        second.close()
        first.close()


@pytest.mark.parametrize(
    "method,attribute,args",
    [
        ("get_resources", "_resources", ()),
        ("get_qq_status", "_connection", ()),
        ("get_qq_processes", "_discovery", ()),
        ("mark_ready", "_update", ()),
    ],
)
def test_public_bridge_unknown_errors_are_safe_structured_failures(
    tmp_path, method, attribute, args
):
    bridge = DesktopBridge(DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None)

    def fail(*args, **kwargs):
        raise OSError("synthetic-private-error")

    value = (
        fail
        if attribute == "_update"
        else SimpleNamespace(sample=fail, status=fail, list_processes=fail)
    )
    setattr(bridge, attribute, value)
    result = getattr(bridge, method)(*args)
    assert result["ok"] is False and result["error"]["code"] == "INTERNAL"
    assert "synthetic-private-error" not in json.dumps(result)


def test_residence_never_joins_tray_while_holding_callback_state_lock(tmp_path):
    callbacks = []

    class Tray:
        ready = False

        def __init__(self, icon, show, exit_app, theme):
            self.callback = exit_app

        def start(self):
            self.ready = True

        def close(self):
            worker = threading.Thread(target=self.callback)
            worker.start()
            worker.join(0.5)
            assert not worker.is_alive(), "tray callback blocked by resident state lock"
            self.ready = False
            callbacks.append(True)

    startup = SimpleNamespace(enabled=lambda: False, set=lambda value: None)
    resident = Residence(
        DesktopPaths(tmp_path, tmp_path / "runtime"), startup=startup, tray_factory=Tray
    )
    resident._window = SimpleNamespace(destroy=lambda: None)
    resident.save({"trayEnabled": True, "startup": False})
    resident.save({"trayEnabled": False, "startup": False})
    assert callbacks == [True]


def test_second_close_recovers_when_renderer_removed_its_close_handler(tmp_path):
    startup = SimpleNamespace(enabled=lambda: False, set=lambda value: None)
    resident = Residence(DesktopPaths(tmp_path, tmp_path / "runtime"), startup=startup)
    calls = []
    resident._window = SimpleNamespace(
        evaluate_js=lambda script: False, destroy=lambda: calls.append("exit")
    )
    resident._ui_ready = True
    resident._prompting = True
    resident._prompt_checked_at = 0
    assert resident.on_closing() is False
    resident._prompt_thread.join(1)
    assert calls == ["exit"] and resident._exiting and not resident._prompting
