import copy
import json
import time

import pytest
from test_agent import ACCOUNT, OTHER, PEER, packet, result, wait

from QQBot.agent.config import DEFAULTS, SettingsStore
from QQBot.agent.trigger import should_trigger
from QQBot.storage.database import Database


def segment(kind, **data):
    return {"type": kind, "data": data}


@pytest.mark.parametrize(
    "percent,roll,expected",
    [
        (0, 0, False),
        (100, 0.999999, True),
        (10, 0.099999, True),
        (10, 0.1, False),
        (10, 0.9, False),
        (1, 0.009999, True),
        (1, 0.01, False),
        (99, 0.989999, True),
        (99, 0.99, False),
    ],
)
def test_random_threshold_matches_upstream_strict_percent(monkeypatch, percent, roll, expected):
    monkeypatch.setattr("QQBot.agent.trigger.random", lambda: roll)
    config = copy.deepcopy(DEFAULTS) | {"groupTrigger": "random", "groupRandomPercent": percent}
    item = {"chatKey": "group:99887766", "segments": [segment("text", text="普通消息")]}
    assert should_trigger(item, ACCOUNT, config, lambda mid: False) is expected


@pytest.mark.parametrize(
    "segments",
    [
        [segment("at", qq=ACCOUNT)],
        [segment("reply", id=77)],
        [segment("text", text="Hello BOT")],
    ],
)
def test_mentions_replies_and_keywords_bypass_random_percent(monkeypatch, segments):
    def unexpected():
        pytest.fail("direct calls and keywords must not roll")

    monkeypatch.setattr("QQBot.agent.trigger.random", unexpected)
    config = copy.deepcopy(DEFAULTS) | {
        "groupTrigger": "random",
        "groupRandomPercent": 0,
        "groupKeywords": ["bot"],
    }
    item = {"chatKey": "group:99887766", "segments": json.dumps(segments)}
    assert should_trigger(item, ACCOUNT, config, lambda mid: mid == 77)


@pytest.mark.parametrize(
    "segments",
    [
        [segment("at", qq=PEER, name="bot")],
        [segment("at", qq="all")],
        [segment("reply", id=78, text="bot")],
        [segment("image", file="bot.png", url="https://example.test/bot")],
        [segment("text", text="[引用 bot: [图片]] 普通消息")],
    ],
)
def test_random_mode_does_not_turn_other_mentions_or_metadata_into_direct_calls(segments):
    config = copy.deepcopy(DEFAULTS) | {
        "groupTrigger": "random",
        "groupRandomPercent": 0,
        "groupKeywords": ["bot"],
    }
    item = {"chatKey": "group:99887766", "segments": segments}
    assert not should_trigger(item, ACCOUNT, config, lambda mid: mid == 77)


def test_random_is_not_used_for_other_modes_private_self_or_withdrawn(monkeypatch):
    def unexpected():
        pytest.fail("not an eligible random group message")

    monkeypatch.setattr("QQBot.agent.trigger.random", unexpected)
    config = copy.deepcopy(DEFAULTS) | {"groupRandomPercent": 100}
    item = {"chatKey": "group:99887766", "segments": [segment("text", text="普通消息")]}
    for mode, expected in [("at", False), ("keywords", False), ("all", True)]:
        config["groupTrigger"] = mode
        assert should_trigger(item, ACCOUNT, config, lambda mid: False) is expected
    config["groupTrigger"] = "random"
    assert should_trigger(item | {"chatKey": f"private:{PEER}"}, ACCOUNT, config, lambda mid: False)
    assert not should_trigger(item | {"self": True}, ACCOUNT, config, lambda mid: False)
    assert not should_trigger(item | {"withdrawn": True}, ACCOUNT, config, lambda mid: False)


@pytest.mark.parametrize("value", [-1, 101, 1.5, True, None, "10", float("nan"), float("inf")])
def test_invalid_percent_is_rejected_without_overwriting_config(stack, value):
    _, _, _, settings, _, _, _ = stack
    before = settings.read(ACCOUNT)
    with pytest.raises(ValueError):
        settings.save(ACCOUNT, {"groupTrigger": "random", "groupRandomPercent": value})
    assert settings.read(ACCOUNT) == before


def test_read_never_rewrites_the_stored_account_config(tmp_path):
    database = Database(tmp_path / "settings.sqlite3")
    try:
        config = copy.deepcopy(DEFAULTS)
        config["groupTrigger"] = "keywords"
        config["api"]["apiKey"] = "kept-private"
        config["groupKeywords"] = ["bot"]
        original = json.dumps(config)
        with database.lock, database.connection as db:
            db.execute("INSERT INTO settings VALUES(?,?)", (ACCOUNT, original))
        settings = SettingsStore(database)
        read = settings.read(ACCOUNT)
        assert read["groupRandomPercent"] == 10 and read["groupTrigger"] == "keywords"
        assert read["groupKeywords"] == ["bot"] and read["api"]["apiKey"] == "kept-private"
        assert (
            database.connection.execute(
                "SELECT value FROM settings WHERE account=?", (ACCOUNT,)
            ).fetchone()[0]
            == original
        )
        saved = settings.save(ACCOUNT, {"groupTrigger": "random", "groupRandomPercent": 25})
        assert saved["groupRandomPercent"] == 25 and saved["api"]["apiKeyConfigured"]
        assert "apiKey" not in saved["api"]
        assert settings.read(ACCOUNT)["api"]["apiKey"] == "kept-private"
        assert (
            settings.read(OTHER)["groupRandomPercent"] == 10
            and settings.read(OTHER)["groupTrigger"] == "at"
        )
    finally:
        database.close()


def test_one_roll_only_for_new_allowed_messages_no_replay_and_misses_remain_archived(
    stack, monkeypatch
):
    service, receiver, sessions, settings, messages, connection, model = stack
    model.responses = [result("finish")]
    settings.save(ACCOUNT, {"groupTrigger": "random", "groupRandomPercent": 10})
    rolls = []

    def draw():
        value = [0.9, 0.05][len(rolls)]
        rolls.append(value)
        return value

    monkeypatch.setattr("QQBot.agent.trigger.random", draw)
    receiver.receive(ACCOUNT, packet(1, kind="group"))  # OFF: archive, never roll.
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(2, kind="group", group_id="11111111"))
    settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    receiver.receive(ACCOUNT, packet(3, kind="group"))
    settings.save(ACCOUNT, {"blockedUsers": []})
    receiver.receive(ACCOUNT, packet(4, kind="group"))  # Miss: retain for context.
    time.sleep(0.08)
    assert rolls == [0.9] and not model.calls and not sessions.list(ACCOUNT)
    receiver.receive(ACCOUNT, packet(5, kind="group"))
    receiver.receive(ACCOUNT, packet(5, kind="group"))  # Duplicate never rolls.
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "noreply")
    assert rolls == [0.9, 0.05] and len(model.calls) == 1 and not connection.calls
    assert messages.list_chats(ACCOUNT)[0]["count"] == 3
    service.enable(ACCOUNT, False)
    wait(lambda: service.status()["active"] == 0)
    service.enable(ACCOUNT, True)
    time.sleep(0.08)
    assert len(model.calls) == 1 and rolls == [0.9, 0.05]


def test_pausing_discards_random_hits_waiting_in_debounce(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    service._debounce = 0.15
    settings.save(ACCOUNT, {"groupTrigger": "random", "groupRandomPercent": 10})
    monkeypatch.setattr("QQBot.agent.trigger.random", lambda: 0)
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(kind="group"))
    service.enable(ACCOUNT, False)
    wait(lambda: service.status()["active"] == 0)
    service.enable(ACCOUNT, True)
    time.sleep(0.2)
    assert not model.calls and not sessions.list(ACCOUNT) and not connection.calls
