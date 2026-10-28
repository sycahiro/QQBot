from qqbot.agent.config import SettingsStore
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore


def test_late_mutations_cannot_affect_newly_selected_account(tmp_path):
    class Selection:
        value = "12345678"

        def read(self):
            return self.value

    selection = Selection()

    class Connection:
        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": selection.value}}

    db = Database(tmp_path / "data.sqlite3")
    try:
        settings = SettingsStore(db)
        settings.save("87654321", {"api": {"model": "untouched"}})
        bridge = DesktopBridge(
            DesktopPaths(tmp_path, tmp_path),
            lambda **kwargs: None,
            selection=selection,
            connection=Connection(),
            messages=MessageStore(db),
            settings=settings,
        )
        assert bridge.save_bot_settings({"api": {"apiKey": "secret"}}, "12345678")["ok"]
        assert bridge.get_bot_settings()["config"]["api"]["apiKeyConfigured"]
        assert "apiKey" not in bridge.get_bot_settings()["config"]["api"]
        selection.value = "87654321"
        for result in [
            bridge.save_bot_settings({"api": {"model": "wrong"}}, "12345678"),
            bridge.delete_archive(None, "12345678"),
            bridge.delete_session(None, "12345678"),
        ]:
            assert result["ok"] is False and result["error"]["code"] == "INVALID_INPUT"
        assert settings.read("87654321")["api"]["model"] == "untouched"
        assert bridge.save_bot_settings({}, None)["ok"] is False
    finally:
        db.close()

def test_connecting_records_the_chosen_account_first(tmp_path):
    calls = []

    class Selection:
        def read(self):
            return None

    class Connection:
        def choose(self, target):
            calls.append(("choose", target["uin"]))
            return target["uin"]

        def connect(self, target):
            calls.append(("connect", target["uin"]))
            return {"state": "ready", "connected": True, "account": {"uin": target["uin"]}}

        def status(self):
            return {"state": "idle", "connected": False, "account": None}

    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **kwargs: None,
        selection=Selection(),
        connection=Connection(),
    )
    target = {"pid": 1, "processKey": "k", "uin": "12345678"}
    result = bridge.connect_qq_account(target)
    assert result["ok"] is True
    # 列表里点「连接」就等于选定账号，必须先落盘再连接。
    assert calls == [("choose", "12345678"), ("connect", "12345678")]

def test_connecting_records_the_chosen_account_first(tmp_path):
    calls = []

    class Selection:
        def read(self):
            return None

    class Connection:
        def choose(self, target):
            calls.append(("choose", target["uin"]))
            return target["uin"]

        def connect(self, target):
            calls.append(("connect", target["uin"]))
            return {"state": "ready", "connected": True, "account": {"uin": target["uin"]}}

        def status(self):
            return {"state": "idle", "connected": False, "account": None}

    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **kwargs: None,
        selection=Selection(),
        connection=Connection(),
    )
    target = {"pid": 1, "processKey": "k", "uin": "12345678"}
    result = bridge.connect_qq_account(target)
    assert result["ok"] is True
    # 列表里点「连接」就等于选定账号，必须先落盘再连接。
    assert calls == [("choose", "12345678"), ("connect", "12345678")]
