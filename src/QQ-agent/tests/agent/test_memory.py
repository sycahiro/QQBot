import json

import pytest
from qqbot.agent.config import SettingsStore
from qqbot.agent.receiver import Receiver
from qqbot.agent.service import AgentService
from qqbot.storage.database import Database
from qqbot.storage.memory import MemoryStore
from qqbot.storage.messages import MessageStore
from qqbot.storage.sessions import SessionStore
from test_agent import ACCOUNT, OTHER, PEER, Connection, Model, packet, result, wait

GROUP = "group:99887766"
PRIVATE = f"private:{PEER}"


@pytest.fixture
def stores(tmp_path):
    db = Database(tmp_path / "data.sqlite3")
    yield db, MemoryStore(db), MessageStore(db)
    db.close()


def test_memory_delete_scopes_and_duplicate_contents(stores):
    _, memory, _ = stores
    memory.append(ACCOUNT, PRIVATE, PEER, "友", "喜欢编程")
    assert memory.append(ACCOUNT, PRIVATE, PEER, "友", "喜欢编程") == {
        "saved": False,
        "duplicate": True,
    }
    memory.append(ACCOUNT, GROUP, PEER, "群友甲", "喜欢聊天")
    memory.append(ACCOUNT, GROUP, OTHER, "群友乙", "喜欢画画")
    memory.append(OTHER, GROUP, PEER, "其他机器人", "独立记忆")
    assert memory.delete(ACCOUNT, GROUP, PEER) == 1
    assert memory.members(ACCOUNT, GROUP)[0]["userId"] == OTHER
    assert memory.members(ACCOUNT, PRIVATE)[0]["entries"][0]["content"] == "喜欢编程"
    assert memory.delete(ACCOUNT, GROUP) == 1
    assert memory.delete(ACCOUNT) == 1 and memory.chats(ACCOUNT) == []
    assert memory.members(OTHER, GROUP)[0]["entries"][0]["content"] == "独立记忆"


def test_private_member_and_failed_edit_preserve_existing_memory(stores):
    _, memory, _ = stores
    memory.replace(ACCOUNT, PRIVATE, PEER, "昵称", ["第一条", "第二条"])
    with pytest.raises(ValueError):
        memory.replace(ACCOUNT, PRIVATE, OTHER, "错误对象", ["不应保存"])
    with pytest.raises(ValueError):
        memory.replace(ACCOUNT, PRIVATE, PEER, "昵称", ["长" * 121])
    assert [e["content"] for e in memory.members(ACCOUNT, PRIVATE)[0]["entries"]] == [
        "第一条",
        "第二条",
    ]
    assert memory.replace(ACCOUNT, PRIVATE, PEER, "昵称", []) == 0
    assert memory.members(ACCOUNT, PRIVATE) == []


def test_chat_labels_and_memory_survive_archive_cleanup(stores):
    _, memory, messages = stores
    messages.ingest(ACCOUNT, packet())
    memory.append(ACCOUNT, PRIVATE, PEER, "友", "长期印象")
    assert memory.chats(ACCOUNT)[0] == {
        "chatKey": PRIVATE,
        "name": "群友",
        "count": 1,
        "members": 1,
    }
    messages.delete(ACCOUNT)
    assert memory.members(ACCOUNT, PRIVATE) and memory.chats(ACCOUNT)[0]["count"] == 1
    assert memory.chats(ACCOUNT)[0]["name"] == "群友"


def test_prompt_contains_only_relevant_members(stores):
    _, memory, _ = stores
    memory.append(ACCOUNT, GROUP, PEER, "甲", "喜欢编程")
    memory.append(ACCOUNT, GROUP, OTHER, "乙", "喜欢画画")
    text = memory.format(ACCOUNT, GROUP, {PEER})
    assert "喜欢编程" in text and "喜欢画画" not in text
    assert memory.format(OTHER, GROUP, {PEER}) == ""


def test_memory_tools_save_and_feed_next_run_without_background_model(stores):
    db, memory, messages = stores
    settings, sessions, model = SettingsStore(db), SessionStore(db), Model()
    settings.save(
        ACCOUNT,
        {"api": {"baseUrl": "http://model.test", "model": "test"}, "allow": {"private": [PEER]}},
    )
    first = result("memory_append", "finish")
    first["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(
        {"category": "memberImpression", "userId": PEER, "target": "群友", "content": "喜欢编程"}
    )
    model.responses = [first, result("finish")]
    service = AgentService(
        settings, messages, sessions, Connection(), model=model, memory=memory, debounce=0.01
    )
    try:
        receiver = Receiver(settings, messages, service)
        service.enable(ACCOUNT, True)
        receiver.receive(ACCOUNT, packet())
        wait(lambda: service.status()["active"] == 0 and len(sessions.list(ACCOUNT)) == 1)
        assert memory.members(ACCOUNT, PRIVATE)[0]["entries"][0]["content"] == "喜欢编程"
        receiver.receive(ACCOUNT, packet(2))
        wait(lambda: service.status()["active"] == 0 and len(sessions.list(ACCOUNT)) == 2)
        assert "喜欢编程" in model.calls[1][1]["content"] and len(model.calls) == 2
        with pytest.raises(ValueError):
            service._memory_tool(
                "memory_append",
                ACCOUNT,
                PRIVATE,
                {"category": "memberImpression", "userId": OTHER, "content": "错误"},
            )
    finally:
        service.close()


def test_schema_upgrade_keeps_existing_archive_and_configuration(tmp_path):
    db = Database(tmp_path / "data.sqlite3")
    messages, settings = MessageStore(db), SettingsStore(db)
    messages.ingest(ACCOUNT, packet())
    settings.save(ACCOUNT, {"api": {"model": "preserved"}})
    db.connection.execute("PRAGMA user_version=1")
    db.close()
    reopened = Database(tmp_path / "data.sqlite3")
    try:
        assert MessageStore(reopened).list_chats(ACCOUNT)[0]["count"] == 1
        assert SettingsStore(reopened).read(ACCOUNT)["api"]["model"] == "preserved"
        assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        reopened.close()
