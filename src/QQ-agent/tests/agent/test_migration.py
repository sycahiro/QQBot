import json

from qqbot.agent.config import SettingsStore
from qqbot.storage.database import Database
from qqbot.storage.memory import MemoryStore
from qqbot.storage.messages import MessageStore
from qqbot.storage.migration import import_snapshot, snapshot
from qqbot.storage.sessions import SessionStore
from test_agent import ACCOUNT, OTHER, PEER


def source(tmp_path):
    root = tmp_path / "old"
    fixtures = {
        "config.json": {
            "api": {
                "baseUrl": "https://model.test/v1",
                "apiKey": "wrong-legacy",
                "model": "test",
                "provider": "chosen",
            },
            "dshProviderKeys": {"chosen": "chosen-secret"},
            "allow": {"groups": [], "private": [PEER]},
        },
        f"messages/private_{PEER}.json": {
            "chatKey": f"private:{PEER}",
            "messages": [
                {
                    "id": 1,
                    "mid": -1,
                    "ts": 1800000000000,
                    "senderId": PEER,
                    "senderName": "昵称",
                    "text": "你好",
                    "self": False,
                },
                {
                    "id": 2,
                    "mid": None,
                    "ts": 1800000001000,
                    "senderId": "self",
                    "senderName": "我",
                    "text": "你好呀",
                    "self": True,
                },
            ],
        },
        "sessions/old-id.json": {
            "id": "old-id",
            "chatKey": f"private:{PEER}",
            "startedAt": 1800000000000,
            "status": "running",
            "messages": [
                {"role": "assistant", "content": None},
                {
                    "toolCall": {
                        "name": "finish",
                        "args": {"summary": "结束"},
                        "result": '{"finished":true}',
                    }
                },
            ],
            "sent": [{"text": "历史发送记录"}],
            "usage": {"totalTokens": 99, "promptTokens": 90, "completionTokens": 9, "calls": 1},
        },
        f"memory/private_{PEER}/{PEER}.json": {
            "userId": PEER,
            "name": "昵称",
            "impressions": [{"content": "喜欢编程"}],
        },
    }
    for relative, payload in fixtures.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_import_preserves_source_and_is_idempotent_even_after_deletion(tmp_path):
    root = source(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*.json")}
    data = snapshot(root)
    database = Database(tmp_path / "new.sqlite3")
    try:
        report = import_snapshot(database, data, ACCOUNT, "source-identity")
        assert (
            report["messages"],
            report["sessions"],
            report["memories"],
            report["configuration"],
        ) == (2, 1, 1, 1)
        assert not report["skipped"]
        assert SettingsStore(database).read(ACCOUNT)["api"]["apiKey"] == "chosen-secret"
        assert MessageStore(database).messages(ACCOUNT, f"private:{PEER}")["items"][1]["self"]
        item = SessionStore(database).list(ACCOUNT)[0]
        assert item["status"] == "aborted" and item["usage"]["totalTokens"] == 99
        assert item["sent"][0]["verified"] is False
        detail = SessionStore(database).get(ACCOUNT, item["id"])
        assert len(detail["records"]) == 1 and detail["records"][0]["result"] == {"finished": True}
        second = import_snapshot(database, data, ACCOUNT, "source-identity")
        assert second["messages"] == second["sessions"] == second["memories"] == 0
        MessageStore(database).delete(ACCOUNT)
        MemoryStore(database).delete(ACCOUNT)
        SessionStore(database).delete(ACCOUNT)
        third = import_snapshot(database, data, ACCOUNT, "source-identity")
        assert third["messages"] == third["memories"] == third["sessions"] == 0
        assert MessageStore(database).list_chats(ACCOUNT) == []
        assert all(p.read_bytes() == raw for p, raw in before.items())
    finally:
        database.close()


def test_existing_configuration_and_other_accounts_remain_untouched(tmp_path):
    root = source(tmp_path)
    database = Database(tmp_path / "new.sqlite3")
    try:
        SettingsStore(database).save(
            ACCOUNT, {"api": {"model": "current", "apiKey": "current-key"}}
        )
        SettingsStore(database).save(OTHER, {"api": {"model": "other"}})
        report = import_snapshot(database, snapshot(root), ACCOUNT, "source-identity")
        assert report["configuration"] == 0
        assert SettingsStore(database).read(ACCOUNT)["api"]["apiKey"] == "current-key"
        assert SettingsStore(database).read(OTHER)["api"]["model"] == "other"
        assert MessageStore(database).list_chats(OTHER) == []
    finally:
        database.close()
