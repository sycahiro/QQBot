import json

import pytest
from qqbot.agent.config import SettingsStore
from qqbot.agent.receiver import Receiver
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore

ACCOUNT, OTHER, PEER = "12345678", "87654321", "11223344"


@pytest.fixture
def stores(tmp_path):
    database = Database(tmp_path / "agent.sqlite3")
    yield database, MessageStore(database), SettingsStore(database)
    database.close()


def event(account=ACCOUNT, **changes):
    return {
        "post_type": "message",
        "self_id": account,
        "message_type": "private",
        "user_id": PEER,
        "sender": {"user_id": PEER, "nickname": "昵称"},
        "time": 1800000000,
        "message_id": -123,
        "message_seq": 7,
        "message": [{"type": "text", "data": {"text": "你好"}}],
    } | changes


def test_account_isolation_duplicates_sequence_and_missing_ids(stores):
    _, messages, _ = stores
    assert messages.ingest(ACCOUNT, event()) is not None
    assert messages.ingest(ACCOUNT, event()) is None
    messages.ingest(OTHER, event(OTHER))
    messages.ingest(ACCOUNT, event(message_seq=8))
    for _ in range(2):
        messages.ingest(ACCOUNT, event(message_id=None))
    assert messages.list_chats(ACCOUNT)[0]["count"] == 4
    assert messages.list_chats(OTHER)[0]["count"] == 1
    with pytest.raises(ValueError):
        messages.ingest(OTHER, event())
    assert messages.messages(ACCOUNT, f"private:{PEER}")["items"][0]["mid"] == "-123"


def test_self_sent_private_message_uses_target_instead_of_bot_as_chat(stores):
    _, messages, _ = stores
    messages.ingest(
        ACCOUNT,
        event(
            post_type="message_sent",
            user_id=ACCOUNT,
            target_id=PEER,
            sender={"user_id": ACCOUNT, "nickname": "机器人"},
        ),
    )
    assert messages.list_chats(ACCOUNT)[0]["chatKey"] == f"private:{PEER}"
    assert messages.messages(ACCOUNT, f"private:{PEER}")["items"][0]["self"] is True
    assert messages.list_chats(ACCOUNT)[0]["lastSenderName"] == "我"


def test_self_echo_fills_the_unknown_receipt_even_when_a_known_collision_precedes_it(stores):
    database, messages, _ = stores
    messages.ingest(
        ACCOUNT, event(post_type="message_sent", user_id=ACCOUNT, target_id=PEER, message_seq=7)
    )
    with database.connection as db:
        db.execute(
            """INSERT INTO messages(account,chat_key,mid,sequence,ts,sender_id,sender_name,body,segments,is_self,withdrawn,is_read)
            VALUES(?,?,?,'',1,?,'我','另一条回执','[]',1,0,1)""",
            (ACCOUNT, f"private:{PEER}", "-123", ACCOUNT),
        )
    assert (
        messages.ingest(
            ACCOUNT, event(post_type="message_sent", user_id=ACCOUNT, target_id=PEER, message_seq=8)
        )
        is None
    )
    sequences = [
        row[0] for row in database.connection.execute("SELECT sequence FROM messages ORDER BY id")
    ]
    assert sequences == ["7", "8"]
    assert (
        messages.ingest(
            ACCOUNT, event(post_type="message_sent", user_id=ACCOUNT, target_id=PEER, message_seq=8)
        )
        is None
    )
    assert database.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_archive_chat_preview_uses_latest_message_sender_and_body(stores):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event(message_type="group", group_id="99887766"))
    messages.ingest(
        ACCOUNT,
        event(
            message_type="group",
            group_id="99887766",
            message_id=2,
            user_id="22334455",
            sender={"user_id": "22334455", "card": "最新群名片"},
            message="最新内容",
        ),
    )
    summary = messages.list_chats(ACCOUNT)[0]
    assert summary["lastSenderName"] == "最新群名片" and summary["lastText"] == "最新内容"
    messages.recall(ACCOUNT, "group:99887766", 2)
    summary = messages.list_chats(ACCOUNT)[0]
    assert summary["lastSenderName"] == "最新群名片" and summary["lastText"] == "[已撤回] 最新内容"


def test_recall_retains_existing_and_late_archive_content_but_redacts_model_context(stores):
    database, messages, _ = stores
    content = [
        {"type": "text", "data": {"text": "保留的原文"}},
        {"type": "image", "data": {"url": "https://example.test/retained-image"}},
    ]
    first = messages.ingest(ACCOUNT, event(message=content))
    recall = {
        "post_type": "notice",
        "notice_type": "friend_recall",
        "self_id": ACCOUNT,
        "user_id": PEER,
        "message_id": -123,
    }
    messages.ingest(ACCOUNT, recall)
    late = messages.ingest(ACCOUNT, event(message_seq=9, message=content))
    messages.ingest(ACCOUNT, recall)  # Repeated notices must not erase retained data.
    key = f"private:{PEER}"
    rows = messages.messages(ACCOUNT, key)["items"]
    assert len(rows) == 2 and late["withdrawn"]
    assert all(
        item["withdrawn"] and item["read"] and item["text"] == "保留的原文[图片]" for item in rows
    )
    assert all(not item["hasImage"] for item in rows)
    assert all(
        json.loads(row[0]) == content
        for row in database.connection.execute("SELECT segments FROM messages")
    )
    context = messages.context(ACCOUNT, key)
    assert all(
        item["withdrawn"] and item["text"] == "[消息已撤回]" and item["segments"] == []
        for item in context
    )
    assert messages.list_chats(ACCOUNT)[0]["lastText"] == "[已撤回] 保留的原文[图片]"
    assert messages.archive_state(ACCOUNT)["unread"] == 0
    assert messages.claim(ACCOUNT, key, [first["id"], late["id"]], only_unread=False) == set()
    assert not messages.has_mid(ACCOUNT, key, -123)
    for reader in [messages.image_message, messages.message_detail]:
        with pytest.raises(ValueError, match="已撤回"):
            reader(ACCOUNT, key, -123)


def test_group_recall_marks_only_matching_account_and_group_even_outside_allowlist(stores):
    _, messages, settings = stores
    group = "99887766"
    other_group = "99887777"
    for account, target in [(ACCOUNT, group), (ACCOUNT, other_group), (OTHER, group)]:
        messages.ingest(account, event(account, message_type="group", group_id=target))
    Receiver(settings, messages).receive(
        ACCOUNT,
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "self_id": ACCOUNT,
            "group_id": group,
            "user_id": PEER,
            "operator_id": "22334455",
            "message_id": -123,
        },
    )
    item = messages.messages(ACCOUNT, f"group:{group}")["items"][0]
    assert item["withdrawn"] and item["read"] and item["text"] == "你好"
    assert item["senderName"] == "昵称" and item["ts"] == 1800000000000
    assert not messages.messages(ACCOUNT, f"group:{other_group}")["items"][0]["withdrawn"]
    assert not messages.messages(OTHER, f"group:{group}")["items"][0]["withdrawn"]


def test_pagination_names_and_delete_are_account_scoped(stores):
    _, messages, _ = stores
    for number in range(7):
        messages.ingest(ACCOUNT, event(message_id=number + 1))
    messages.ingest(OTHER, event(OTHER))
    messages.set_names(ACCOUNT, {f"private:{PEER}": "新昵称"})
    assert messages.list_chats(ACCOUNT)[0]["name"] == "新昵称"
    first = messages.messages(ACCOUNT, f"private:{PEER}", limit=3)
    second = messages.messages(ACCOUNT, f"private:{PEER}", before=first["nextBefore"], limit=3)
    assert first["hasMore"] and second["hasMore"]
    assert {item["id"] for item in first["items"]}.isdisjoint(
        item["id"] for item in second["items"]
    )
    assert messages.delete(ACCOUNT) == 7 and messages.list_chats(ACCOUNT) == []
    assert messages.list_chats(OTHER)[0]["count"] == 1
    with pytest.raises(ValueError):
        messages.delete(OTHER, "private:1 OR 1=1")


def test_settings_are_isolated_and_secrets_are_write_only_to_ui(stores):
    _, _, settings = stores
    settings.save(ACCOUNT, {"api": {"apiKey": "private-test-key", "model": "test"}})
    public = settings.read(ACCOUNT, public=True)
    assert "apiKey" not in public["api"] and public["api"]["apiKeyConfigured"] is True
    settings.save(ACCOUNT, {"persona": {"roleText": "新人设"}})
    assert settings.read(ACCOUNT)["api"]["apiKey"] == "private-test-key"
    assert settings.read(OTHER)["api"]["apiKey"] == ""
    settings.save(ACCOUNT, {"api": {"apiKey": ""}})
    assert settings.read(ACCOUNT, public=True)["api"]["apiKeyConfigured"] is False


@pytest.mark.parametrize(
    "patch",
    [
        {"api": {"temperature": float("nan")}},
        {"api": {"baseUrl": "file:///private"}},
        {"allow": {"groups": ["../escape"]}},
        {"api": {"unknown": 1}},
        {"contextLimit": True},
    ],
)
def test_invalid_configuration_does_not_overwrite_existing_settings(stores, patch):
    _, _, settings = stores
    before = settings.read(ACCOUNT)
    with pytest.raises(ValueError):
        settings.save(ACCOUNT, patch)
    assert settings.read(ACCOUNT) == before


def test_receiver_preserves_original_allow_and_deny_admission(stores):
    _, messages, settings = stores
    receiver = Receiver(settings, messages)
    assert receiver.receive(ACCOUNT, event()) is None  # Empty allowlist is closed.
    settings.save(ACCOUNT, {"allow": {"private": [PEER]}})
    assert receiver.receive(ACCOUNT, event()) is not None
    settings.save(ACCOUNT, {"deny": {"private": [PEER]}})
    assert receiver.receive(ACCOUNT, event(message_id=2)) is None
    # Removing the whitelist does not prevent marking an archived message recalled.
    receiver.receive(
        ACCOUNT,
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "self_id": ACCOUNT,
            "user_id": PEER,
            "message_id": -123,
        },
    )
    assert messages.messages(ACCOUNT, f"private:{PEER}")["items"][0]["withdrawn"] is True
