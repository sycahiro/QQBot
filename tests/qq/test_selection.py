import json

import pytest

from QQBot.qq.discovery import DiscoveryError
from QQBot.qq.selection import AccountSelection

TARGET = {"pid": 123, "processKey": "123:456789", "uin": "12345678"}


@pytest.mark.parametrize("uin", ["1234", "1234567890123", "1１２３４"])
def test_python_account_selection_matches_engine_length_and_ascii_rules(tmp_path, uin):
    from QQBot.storage.messages import account_id

    with pytest.raises(ValueError):
        account_id(uin)
    selection = AccountSelection(tmp_path / "account.json")
    with pytest.raises(DiscoveryError):
        selection.choose({**TARGET, "uin": uin}, Scanner())
    assert account_id("123456789012") == "123456789012"


class Scanner:
    def __init__(self, **changes):
        self.changes = changes

    def list_processes(self):
        return [
            {
                "pid": 123,
                "processKey": "123:456789",
                "identityReady": True,
                "account": {"uin": "12345678"},
            }
            | self.changes
        ]


def test_selection_survives_recreation_but_never_stores_process_or_login_data(tmp_path):
    file = tmp_path / "account.json"
    selection = AccountSelection(file)
    assert selection.read() is None
    assert selection.choose(TARGET, Scanner()) == TARGET["uin"]
    assert AccountSelection(file).read() == TARGET["uin"]
    assert json.loads(file.read_text()) == {"version": 1, "uin": TARGET["uin"]}
    assert AccountSelection(file).choose(None, Scanner()) is None
    assert AccountSelection(file).read() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"pid": 124},
        {"processKey": "123:999"},
        {"identityReady": False},
        {"account": {"uin": "87654321"}},
    ],
)
def test_stale_or_changed_account_cannot_replace_saved_selection(tmp_path, changes):
    file = tmp_path / "account.json"
    selection = AccountSelection(file)
    selection.choose(TARGET, Scanner())
    original = file.read_bytes()
    with pytest.raises(DiscoveryError) as failure:
        selection.choose(TARGET, Scanner(**changes))
    assert failure.value.code == "STALE_SELECTION"
    assert file.read_bytes() == original


def test_unreadable_configuration_is_reported_and_preserved(tmp_path):
    file = tmp_path / "account.json"
    file.write_bytes(b"broken")
    with pytest.raises(DiscoveryError, match="原文件已保留"):
        AccountSelection(file).read()
    assert file.read_bytes() == b"broken"


def test_failed_atomic_save_preserves_previous_choice(tmp_path, monkeypatch):
    from QQBot.qq import selection as module

    file = tmp_path / "account.json"
    choice = AccountSelection(file)
    choice.choose(TARGET, Scanner())
    original = file.read_bytes()

    def failed(*_):
        raise PermissionError("locked")

    monkeypatch.setattr(module, "save_state", failed)
    with pytest.raises(DiscoveryError) as failure:
        choice.choose(None, Scanner())
    assert failure.value.code == "SAVE_FAILED" and file.read_bytes() == original
