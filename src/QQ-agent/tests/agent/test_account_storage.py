import sqlite3

import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.accounts import AccountStorage, account_directory
from test_storage import ACCOUNT, OTHER, PEER, event


def test_account_files_are_lazy_and_physically_separate(tmp_path):
    storage = AccountStorage(tmp_path / "accounts")
    assert not (tmp_path / "accounts").exists()
    try:
        for account in (ACCOUNT, OTHER):
            storage.settings.save(account, {"api": {"model": account}})
            storage.messages.ingest(account, event(account))
            storage.memory.append(account, f"private:{PEER}", PEER, "昵称", account)
            session = storage.sessions.start(account, f"private:{PEER}", "昵称", "test", "你好")
            session["status"] = "noreply"
            storage.sessions.save(session)
        assert storage.settings.read(ACCOUNT)["api"]["model"] == ACCOUNT
        assert storage.settings.read(OTHER)["api"]["model"] == OTHER
        for account in (ACCOUNT, OTHER):
            with sqlite3.connect(tmp_path / "accounts" / account / "agent.sqlite3") as db:
                for table in ("settings", "messages", "memories", "sessions"):
                    assert db.execute(f"SELECT DISTINCT account FROM {table}").fetchall() == [
                        (account,)
                    ]
    finally:
        storage.close()
    reopened = AccountStorage(tmp_path / "accounts")
    try:
        assert reopened.settings.read(ACCOUNT)["api"]["model"] == ACCOUNT
    finally:
        reopened.close()


@pytest.mark.parametrize("account", ["../outside", "12345/../../outside", None, True, "0123456"])
def test_account_directory_rejects_non_uin_paths(tmp_path, account):
    with pytest.raises(ValueError):
        account_directory(tmp_path / "accounts", account)
    assert not list(tmp_path.iterdir())


def test_disconnected_selection_does_not_load_or_expose_account_data(tmp_path):
    class Selection:
        value = ACCOUNT

        def read(self):
            return self.value

    class Connection:
        connected = False
        account = ACCOUNT

        def status(self):
            return {
                "connected": self.connected,
                "state": "ready" if self.connected else "disconnected",
                "account": {"uin": self.account},
            }

    selection, connection = Selection(), Connection()
    storage = AccountStorage(tmp_path / "accounts")
    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **kwargs: None,
        selection=selection,
        connection=connection,
        settings=storage.settings,
        messages=storage.messages,
        sessions=storage.sessions,
        memory=storage.memory,
    )
    try:
        for read in (bridge.get_archives, bridge.get_sessions, bridge.get_memory_chats):
            assert read()["items"] == []
        assert bridge.get_bot_settings()["config"] is None and bridge.get_usage()["usage"] is None
        assert bridge.get_diagnostics()["configuration"] is None
        assert not bridge.save_bot_settings({"api": {"model": "wrong"}}, ACCOUNT)["ok"]
        assert (
            not bridge.get_model_list(ACCOUNT)["ok"]
            and not bridge.test_model_connection(ACCOUNT)["ok"]
        )
        assert not (tmp_path / "accounts").exists()
        connection.connected = True
        assert bridge.save_bot_settings({"api": {"model": "one"}}, ACCOUNT)["ok"]
        selection.value = OTHER
        assert bridge.get_bot_settings()["config"] is None
        assert not bridge.save_bot_settings({"api": {"model": "wrong"}}, ACCOUNT)["ok"]
        connection.account = OTHER
        assert bridge.save_bot_settings({"api": {"model": "two"}}, OTHER)["ok"]
        assert bridge.get_bot_settings()["config"]["api"]["model"] == "two"
        assert bridge.get_bot_settings(OTHER)["config"]["api"]["model"] == "two"
        assert not bridge.get_bot_settings(ACCOUNT)["ok"]
        assert storage.settings.read(ACCOUNT)["api"]["model"] == "one"
        connection.connected = False
        assert bridge.get_bot_settings()["config"] is None and bridge.get_sessions()["items"] == []
    finally:
        storage.close()
