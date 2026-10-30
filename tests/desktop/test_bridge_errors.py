import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from QQBot.agent.global_settings import GlobalSettings
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths
from QQBot.qq.discovery import DiscoveryError
from QQBot.qq.selection import AccountSelection


def bridge(tmp_path, **kwargs):
    return DesktopBridge(DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None, **kwargs)


@pytest.mark.parametrize(
    "error", [KeyError("private-key"), IndexError(), TypeError(), OSError(), RuntimeError()]
)
def test_unexpected_business_errors_return_safe_structured_failure(tmp_path, error):
    instance = bridge(tmp_path)

    def fail():
        raise error

    result = instance._business(fail)
    assert result["error"]["code"] == "INTERNAL" and "private-key" not in json.dumps(result)


def test_storage_busy_and_cancellation_have_explicit_contract(tmp_path):
    instance = bridge(tmp_path)
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY

    def fail():
        raise error

    assert instance._business(fail)["error"]["code"] == "STORAGE_BUSY"

    def cancel():
        raise asyncio.CancelledError()

    assert instance._business(cancel)["error"]["code"] == "CANCELLED"


def test_corrupt_selection_hides_account_data_and_status_stays_readable(tmp_path, caplog):
    file = tmp_path / "account.json"
    file.write_text("broken", encoding="utf-8")
    connection = SimpleNamespace(
        status=lambda: {"state": "ready", "connected": True, "account": {"uin": "12345678"}}
    )
    instance = bridge(
        tmp_path,
        selection=AccountSelection(file),
        connection=connection,
        discovery=SimpleNamespace(list_processes=lambda: [{"pid": 101}]),
        agent=SimpleNamespace(
            status=lambda: pytest.fail("must not expose unverified account status")
        ),
    )
    assert instance.get_agent_status()["account"] is None
    assert instance.get_agent_status()["enabled"] is False
    assert instance.get_archives()["items"] == []
    discovered = instance.get_qq_processes()
    assert (
        discovered["ok"]
        and discovered["processes"] == [{"pid": 101}]
        and discovered["selectedUin"] is None
        and discovered["warning"]
    )
    assert sum("保存的账号选择无法读取" in record.message for record in caplog.records) == 1
    assert file.read_text() == "broken"


def test_logs_mask_all_global_keys_while_disconnected(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    global_settings = GlobalSettings(runtime)
    global_settings.profile(
        "global",
        "save",
        {
            "id": None,
            "name": "fixture",
            "api": {
                "baseUrl": "https://model.test/v1",
                "model": "test",
                "apiKey": "fixture-global-key",
            },
        },
    )
    instance = bridge(tmp_path, global_settings=global_settings)
    instance._paths.logs.mkdir(parents=True)
    (instance._paths.logs / "desktop.log").write_text("failed fixture-global-key", encoding="utf-8")
    result = instance.get_logs()
    assert result["ok"] and result["lines"] == ["failed [密钥已隐藏]"]


def test_selection_cache_reloads_on_atomic_replacement_and_never_accepts_corruption(
    tmp_path, monkeypatch
):
    from QQBot.desktop.paths import save_state

    file = tmp_path / "account.json"
    save_state(file, {"version": 1, "uin": "12345678"})
    selection = AccountSelection(file)
    assert selection.read() == "12345678"
    opened = []
    original = Path.open

    def counted(path, *args, **kwargs):
        if path == file:
            opened.append(True)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    for _ in range(10):
        assert selection.read() == "12345678"
    assert not opened
    save_state(file, {"version": 1, "uin": "87654321"})
    assert selection.read() == "87654321" and len(opened) == 1
    file.write_text("broken", encoding="utf-8")
    with pytest.raises(DiscoveryError):
        selection.read()
