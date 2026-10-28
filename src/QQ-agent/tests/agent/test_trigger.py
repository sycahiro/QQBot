import copy
import json
import time

import pytest
from qqbot.agent.config import DEFAULTS, SettingsStore
from qqbot.agent.trigger import should_trigger
from qqbot.storage.database import Database
from test_agent import ACCOUNT, PEER, packet, result, wait
from test_agent import stack as stack


def segment(kind, **data):
    return {"type": kind, "data": data}


@pytest.mark.parametrize(
    "segments,expected",
    [
        ([segment("text", text="小萨在吗")], True),
        ([segment("text", text="hello BOT")], True),
        ([segment("text", text="今天吃什么")], False),
        ([segment("at", qq=PEER, name="小萨")], False),
        ([segment("at", qq="all")], False),
        ([segment("at", qq=ACCOUNT)], True),
        ([segment("reply", id=77)], True),
        ([segment("reply", id=78, text="小萨")], False),
        ([segment("image", file="小萨.png", url="https://example.test/Bot")], False),
        ([segment("text", text="[引用 小萨: [图片]] 今天吃什么")], False),
        ([segment("text", text="[引用 小萨: [图片]] Bot 在吗")], True),
        ([segment("text", text="@小萨 你先说")], False),
        ([segment("text", text="小"), segment("at", qq=PEER), segment("text", text="萨")], False),
        ("[CQ:at,qq=123,name=小萨] 今天吃什么", False),
        ("[引用 Bot: 晚饭] 小萨在吗", True),
    ],
)
def test_keyword_match_uses_body_without_mentions_quotes_or_media(segments, expected):
    config = copy.deepcopy(DEFAULTS) | {
        "groupTrigger": "keywords",
        "groupKeywords": ["小萨", "bot"],
    }
    item = {"chatKey": "group:99887766", "segments": json.dumps(segments), "self": False}
    assert should_trigger(item, ACCOUNT, config, lambda mid: mid == 77) is expected


def test_existing_modes_and_private_chat_do_not_depend_on_keywords():
    config = copy.deepcopy(DEFAULTS) | {"groupKeywords": ["小萨"]}
    item = {"chatKey": "group:99887766", "segments": [segment("text", text="小萨")]}
    assert not should_trigger(item, ACCOUNT, config, lambda mid: False)
    config["groupTrigger"] = "all"
    assert should_trigger(item, ACCOUNT, config, lambda mid: False)
    config["groupTrigger"] = "keywords"
    config["groupKeywords"] = []
    assert not should_trigger(item, ACCOUNT, config, lambda mid: False)
    item["chatKey"] = f"private:{PEER}"
    assert should_trigger(item, ACCOUNT, config, lambda mid: False)
    item["self"] = True
    assert not should_trigger(item, ACCOUNT, config, lambda mid: False)
    item["self"] = False
    item["withdrawn"] = True
    assert not should_trigger(item, ACCOUNT, config, lambda mid: False)


def test_saving_trigger_keeps_secret_without_touching_stored_keys(tmp_path):
    database = Database(tmp_path / "settings.sqlite3")
    try:
        config = copy.deepcopy(DEFAULTS)
        config["api"]["apiKey"] = "kept-private"
        with database.lock, database.connection as db:
            db.execute("INSERT INTO settings VALUES(?,?)", (ACCOUNT, json.dumps(config)))
        store = SettingsStore(database)
        assert (
            store.read(ACCOUNT)["groupKeywords"] == []
            and store.read(ACCOUNT)["groupTrigger"] == "at"
        )
        saved = store.save(
            ACCOUNT, {"groupTrigger": "keywords", "groupKeywords": [" Bot ", "bot", "小萨"]}
        )
        assert saved["groupKeywords"] == ["Bot", "小萨"] and saved["api"]["apiKeyConfigured"]
        assert store.read(ACCOUNT)["api"]["apiKey"] == "kept-private"
    finally:
        database.close()


@pytest.mark.parametrize("words", [[""], ["word\n"], [4], ["x" * 65], ["x"] * 101, "word"])
def test_invalid_keyword_configuration_is_rejected(stack, words):
    _, _, _, settings, _, _, _ = stack
    with pytest.raises(ValueError):
        settings.save(ACCOUNT, {"groupKeywords": words})
    assert settings.read(ACCOUNT)["groupKeywords"] == []


def test_keyword_triggers_only_new_allowed_messages_and_keeps_nonhits_archived(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    model.responses = [result("finish")]
    settings.save(ACCOUNT, {"groupTrigger": "keywords", "groupKeywords": ["小萨"]})

    def receive(mid, text, **fields):
        return receiver.receive(
            ACCOUNT, packet(mid, kind="group", message=[segment("text", text=text)], **fields)
        )

    receive(1, "小萨在吗")  # Off means archive only; enabling never replays it.
    service.enable(ACCOUNT, True)
    receive(2, "今天吃什么")
    receive(3, "小萨在吗", group_id="11111111")  # Outside allowlist.
    settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    receive(4, "小萨在吗")
    settings.save(ACCOUNT, {"blockedUsers": []})
    time.sleep(0.08)
    assert not model.calls and not sessions.list(ACCOUNT)
    receive(5, "小萨在吗")
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "noreply")
    assert len(model.calls) == len(sessions.list(ACCOUNT)) == 1 and not connection.calls
    assert messages.list_chats(ACCOUNT)[0]["count"] == 3
