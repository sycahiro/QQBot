import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore
from test_storage import ACCOUNT, OTHER, PEER, event
from test_storage import stores as stores


def test_search_matches_body_nickname_and_number_in_current_chat_only(stores):
    _, messages, _ = stores
    key = f"private:{PEER}"
    messages.ingest(
        ACCOUNT,
        event(message_id=1, message=[{"type": "text", "data": {"text": "下午喝 Apple 奶茶"}}]),
    )
    messages.ingest(
        ACCOUNT,
        event(message_id=2, sender={"user_id": PEER, "nickname": "苹果同学"}, message="今晚吃饭"),
    )
    messages.ingest(OTHER, event(OTHER, message_id=3, message="苹果"))
    messages.ingest(
        ACCOUNT, event(message_id=4, message_type="group", group_id=99887766, message="苹果")
    )
    assert messages.messages(ACCOUNT, key, query="APPle")["items"][0]["mid"] == "1"
    assert messages.messages(ACCOUNT, key, query=" 苹果 ")["items"][0]["mid"] == "2"
    assert messages.messages(ACCOUNT, key, query=PEER)["totalMatches"] == 2
    assert messages.messages(ACCOUNT, key, query="奶茶")["totalMatches"] == 1
    assert messages.messages(ACCOUNT, key, query="不匹配")["items"] == []


@pytest.mark.parametrize("query", ["%", "_", "\\", "' OR 1=1 --", "[图片]"])
def test_search_is_literal_and_never_sql_wildcards(stores, query):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event(message_id=1, message="字面内容 " + query))
    messages.ingest(ACCOUNT, event(message_id=2, message="其他内容"))
    found = messages.messages(ACCOUNT, f"private:{PEER}", query=query)
    assert found["totalMatches"] == 1 and found["items"][0]["mid"] == "1"


def test_archive_search_includes_retained_recalled_text_but_never_media_urls(stores):
    _, messages, _ = stores
    key = f"private:{PEER}"
    messages.ingest(
        ACCOUNT,
        event(
            message_id=1,
            message=[
                {
                    "type": "image",
                    "data": {
                        "url": "https://example.test/private-ticket",
                        "file": "hidden-filename",
                    },
                }
            ],
        ),
    )
    messages.ingest(ACCOUNT, event(message_id=2, message="撤回前的秘密"))
    messages.recall(ACCOUNT, key, 2)
    for query in ["private-ticket", "hidden-filename"]:
        assert messages.messages(ACCOUNT, key, query=query)["totalMatches"] == 0
    found = messages.messages(ACCOUNT, key, query="撤回前的秘密")
    assert found["totalMatches"] == 1
    assert found["items"][0]["text"] == "撤回前的秘密" and found["items"][0]["withdrawn"]
    assert "撤回前的秘密" not in str(messages.context(ACCOUNT, key))


def test_filtered_pagination_queries_all_history_and_keeps_a_stable_cursor(stores):
    _, messages, _ = stores
    key = f"private:{PEER}"
    for index in range(1, 16):
        messages.ingest(
            ACCOUNT, event(message_id=index, message=("命中" if index % 2 else "普通") + str(index))
        )
    ids, before = [], None
    while True:
        page = messages.messages(ACCOUNT, key, before=before, limit=3, query="命中")
        assert page["totalMatches"] == 8 and page["query"] == "命中"
        assert len(page["items"]) <= 3 and [item["id"] for item in page["items"]] == sorted(
            item["id"] for item in page["items"]
        )
        ids.extend(item["mid"] for item in page["items"])
        before = page["nextBefore"]
        if not page["hasMore"]:
            break
        assert before is not None
    assert len(ids) == len(set(ids)) == 8
    assert set(ids) == {str(index) for index in range(1, 16, 2)}
    assert messages.messages(ACCOUNT, key, query="   ")["totalMatches"] == 15


@pytest.mark.parametrize("query", ["x" * 201, None, [], "a\nb", "a\x00b"])
def test_invalid_search_values_do_not_change_stored_data(stores, query):
    _, messages, _ = stores
    key = f"private:{PEER}"
    messages.ingest(ACCOUNT, event())
    with pytest.raises(ValueError):
        messages.messages(ACCOUNT, key, query=query)
    assert messages.messages(ACCOUNT, key)["totalMatches"] == 1


def test_bridge_search_rejects_stale_account_and_invalid_cursor(tmp_path):
    class Selection:
        value = ACCOUNT

        def read(self):
            return self.value

    selected = Selection()

    class Connection:
        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": selected.value}}

    database = Database(tmp_path / "search.sqlite3")
    try:
        messages = MessageStore(database)
        messages.ingest(ACCOUNT, event(message="你好"))
        bridge = DesktopBridge(
            DesktopPaths(tmp_path, tmp_path),
            lambda **changes: None,
            selection=selected,
            connection=Connection(),
            messages=messages,
        )
        response = bridge.get_archive_messages(f"private:{PEER}", "你好", None, ACCOUNT)
        assert response["ok"] and response["totalMatches"] == 1 and response["query"] == "你好"
        selected.value = OTHER
        assert not bridge.get_archive_messages(f"private:{PEER}", "", None, ACCOUNT)["ok"]
        assert not bridge.get_archive_messages(f"private:{PEER}", "", True, OTHER)["ok"]
        assert not bridge.get_archive_messages(f"private:{PEER}", "", None, None)["ok"]
    finally:
        database.close()
