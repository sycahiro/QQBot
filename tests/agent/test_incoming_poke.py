import copy
import json

import pytest
from test_agent import ACCOUNT, OTHER, PEER, packet, wait

from QQBot.agent.config import DEFAULTS
from QQBot.agent.prompt import prompt


def poke(**changes):
    return {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "self_id": ACCOUNT,
        "user_id": PEER,
        "target_id": ACCOUNT,
        "group_id": "99887766",
        "time": 1800000000,
        **changes,
    }


def test_group_poke_reaches_model_without_at_or_outgoing_poke_permission(stack):
    service, receiver, sessions, settings, _messages, connection, model = stack
    assert settings.read(ACCOUNT)["sticker"]["allowPoke"] is False
    service.enable(ACCOUNT, True)
    incoming = receiver.receive(ACCOUNT, poke())
    assert incoming and incoming["mid"] is None and incoming["chatKey"] == "group:99887766"
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    assert "[拍一拍] 拍了拍我" in model.calls[0][1]["content"]
    assert len(connection.calls) == 1


def test_poke_with_auto_reply_off_is_archived_without_model_or_enable_replay(stack):
    service, receiver, _, _, messages, _, model = stack
    assert receiver.receive(ACCOUNT, poke())
    assert not model.calls
    service.enable(ACCOUNT, True)
    assert not model.calls
    assert messages.list_chats(ACCOUNT)[0]["lastText"].startswith("[拍一拍]")


@pytest.mark.parametrize(
    "changes", [{"user_id": ACCOUNT}, {"target_id": None}, {"user_id": None}, {"group_id": "bad"}]
)
def test_self_echo_or_invalid_poke_does_not_enter_archive(stack, changes):
    _, receiver, _, _, messages, _, model = stack
    assert receiver.receive(ACCOUNT, poke(**changes)) is None
    assert not messages.list_chats(ACCOUNT) and not model.calls


def test_blocked_or_unlisted_pokes_are_ignored_and_private_poke_is_scoped(stack):
    _, receiver, _, settings, messages, _, _ = stack
    assert receiver.receive(ACCOUNT, poke(group_id="11111111")) is None
    assert receiver.receive(ACCOUNT, poke(group_id=None, user_id=OTHER)) is None
    item = receiver.receive(ACCOUNT, poke(group_id=None))
    assert item and item["chatKey"] == f"private:{PEER}"
    settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    assert receiver.receive(ACCOUNT, poke()) is None
    assert len(messages.list_chats(ACCOUNT)) == 1


def test_poke_keeps_previous_sender_name_and_marks_no_native_message_id(stack):
    _, receiver, _, _, _messages, _, _ = stack
    receiver.receive(
        ACCOUNT, packet(kind="group", sender={"nickname": "真实昵称", "user_id": PEER})
    )
    item = receiver.receive(ACCOUNT, poke())
    assert item["senderName"] == "真实昵称" and item["mid"] is None
    assert json.loads(item["segments"])[-1]["type"] == "poke"


def test_execution_rules_precede_persona_and_include_action_endings():
    config = copy.deepcopy(DEFAULTS)
    config["persona"]["roleText"] = "PERSONA_MARKER"
    system = prompt(config, ACCOUNT, f"private:{PEER}", [], set())[0]["content"]
    assert system.index("send_message") < system.index("PERSONA_MARKER")
    assert "【最后检查】" in system and "finish" in system
