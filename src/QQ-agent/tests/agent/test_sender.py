import json
import threading

import pytest
from qqbot.agent.sender import DeliveryError, Sender, face_segments
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore

ACCOUNT, PEER = "12345678", "11223344"
KEY = f"private:{PEER}"


@pytest.fixture
def sender(tmp_path):
    database = Database(tmp_path / "sender.sqlite3")
    messages = MessageStore(database)

    class Connection:
        def __init__(self):
            self.calls = []

        def invoke(self, action, params, *, expected_account):
            assert action == "send_private_msg" and expected_account == ACCOUNT
            self.calls.append(params)
            return {"status": "ok", "data": {"message_id": -len(self.calls)}}

    connection = Connection()
    session = {"sent": []}
    yield Sender(connection, messages, lambda *_: True), connection, messages, session
    database.close()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("普通回复", ["普通回复"]),
        (["第一条", "第二条"], ["第一条", "第二条"]),
        ('["单条回复"]', ["单条回复"]),
        ('  ["第一条", "第二条"]  ', ["第一条", "第二条"]),
        (
            json.dumps(['包含"引号"和\n换行', "中文"], ensure_ascii=True),
            ['包含"引号"和\n换行', "中文"],
        ),
        (['["保留 JSON 原文"]'], ['["保留 JSON 原文"]']),
        (["[微笑]"], ["[微笑]"]),
        ("[普通括号内容]", ["[普通括号内容]"]),
        ('{"number":1}', ['{"number":1}']),
        ("[1,2]", ["[1,2]"]),
        (
            ["<b>普通 HTML</b>，1 < 2，tool_call 是一个名称"],
            ["<b>普通 HTML</b>，1 < 2，tool_call 是一个名称"],
        ),
    ],
)
def test_message_payload_receipt_and_archive_share_the_normalized_text(sender, value, expected):
    send, connection, messages, session = sender
    result = send.send(ACCOUNT, KEY, {"messages": value}, 0, session, lambda _: None)
    assert result["sent"] == len(expected)
    assert [call["message"][0]["data"]["text"] for call in connection.calls] == expected
    assert [item["text"] for item in session["sent"]] == expected
    assert [item["text"] for item in messages.messages(ACCOUNT, KEY)["items"]] == expected


@pytest.mark.parametrize(
    "value", ['["普通回复"])', '["普通回复"', '["普通回复",]', '["第一条", "第二条"] extra']
)
def test_malformed_array_wrappers_are_not_sent_as_visible_text(sender, value):
    send, connection, _, session = sender
    with pytest.raises(ValueError, match="数组"):
        send.send(ACCOUNT, KEY, {"messages": value}, 0, session, lambda _: None)
    assert not connection.calls and not session["sent"]


@pytest.mark.parametrize(
    "text",
    [
        "正常话语 <tool_call>finish<arg_key>summary</arg_key><arg_value>内部总结",
        "<TOOL_CALL name='finish'>",
        "正文</arg_value>",
        "<arg_key>summary",
        "正文<tool_call",
        "<tool_calls />",
    ],
)
@pytest.mark.parametrize("encoded", [False, True])
def test_tool_control_markup_rejects_entire_batch_before_any_send(sender, text, encoded):
    send, connection, messages, session = sender
    values = ["前一条也不应先发送", text]
    with pytest.raises(ValueError, match="工具调用标签"):
        send.send(
            ACCOUNT,
            KEY,
            {"messages": json.dumps(values) if encoded else values},
            0,
            session,
            lambda _: None,
        )
    assert not connection.calls and not session["sent"] and not messages.list_chats(ACCOUNT)


def test_image_note_cannot_bypass_tool_control_markup_guard(sender):
    send, connection, messages, session = sender
    with pytest.raises(ValueError, match="工具调用标签"):
        send.send_image(
            ACCOUNT,
            KEY,
            {"note": "附言<arg_value>内部参数"},
            {"part": {"image_url": {"url": "data:image/jpeg;base64,dGVzdA=="}}},
            0,
            session,
            lambda _: None,
            lambda: True,
        )
    assert not connection.calls and not session["sent"] and not messages.list_chats(ACCOUNT)


@pytest.mark.parametrize(
    "values", [[], [""], ["good", ""], ["good", "\x00  \x00"], ["x"] * 5, ["x" * 3001]]
)
def test_misencoded_message_lists_still_validate_whole_batch_before_dispatch(sender, values):
    send, connection, messages, session = sender
    with pytest.raises(ValueError):
        send.send(ACCOUNT, KEY, {"messages": json.dumps(values)}, 0, session, lambda _: None)
    assert not connection.calls and not session["sent"] and not messages.list_chats(ACCOUNT)


def test_misencoded_and_normal_message_lists_share_success_deduplication(sender):
    send, connection, _, session = sender
    assert (
        send.send(ACCOUNT, KEY, {"messages": '["相同内容"]'}, 0, session, lambda _: None)["sent"]
        == 1
    )
    result = send.send(ACCOUNT, KEY, {"messages": ["相同内容"]}, 0, session, lambda _: None)
    assert result["sent"] == 0 and result["deduped"] == 1 and len(connection.calls) == 1


def test_null_removal_precedes_trim_dedupe_and_archiving(sender):
    send, connection, messages, session = sender
    send.send(ACCOUNT, KEY, {"messages": ["\x00 hello \x00"]}, 0, session, lambda _: None)
    assert (
        send.send(ACCOUNT, KEY, {"messages": ["hello"]}, 0, session, lambda _: None)["deduped"] == 1
    )
    assert len(connection.calls) == 1 and session["sent"][0]["text"] == "hello"
    assert messages.messages(ACCOUNT, KEY)["items"][0]["text"] == "hello"


@pytest.mark.parametrize("kind", ["text", "image"])
def test_content_deduplication_is_per_run_and_survives_receipt_round_trip(sender, kind):
    send, connection, messages, first = sender

    def dispatch(session):
        if kind == "text":
            return send.send(ACCOUNT, KEY, {"messages": ["再次回应"]}, 0, session, lambda _: None)
        return send.send_image(
            ACCOUNT,
            KEY,
            {},
            {"part": {"image_url": {"url": "data:image/jpeg;base64,dGVzdA=="}}},
            0,
            session,
            lambda _: None,
            lambda: True,
        )

    assert dispatch(first)["sent"] == 1
    repeated = dispatch(json.loads(json.dumps(first)))
    assert repeated["sent"] == 0 and repeated["deduped"] == 1
    assert "本次处理已确认发送" in repeated["message"] and not repeated["messageIds"]
    second = {"sent": []}
    assert dispatch(second)["sent"] == 1
    assert len(connection.calls) == 2
    assert first["sent"][0]["messageId"] != second["sent"][0]["messageId"]
    assert len(messages.messages(ACCOUNT, KEY)["items"]) == 2
    assert not send._recent  # No global ordinary-content cooldown remains.


def test_parallel_repeated_calls_share_current_runs_confirmed_receipt(sender):
    send, connection, _, session = sender
    start = threading.Barrier(3)
    results = []

    def dispatch():
        start.wait(2)
        results.append(
            send.send(ACCOUNT, KEY, {"messages": ["同一轮"]}, 0, session, lambda _: None)
        )

    workers = [threading.Thread(target=dispatch) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(2)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert sorted(result["sent"] for result in results) == [0, 1]
    assert len(connection.calls) == len(session["sent"]) == 1


def test_unconfirmed_delivery_is_not_a_successful_deduplication_receipt(sender):
    send, connection, _, session = sender
    connection.invoke = lambda *args, **kwargs: {"status": "ok", "data": {}}
    with pytest.raises(DeliveryError, match="未确认消息编号"):
        send.send(ACCOUNT, KEY, {"messages": ["不能假报成功"]}, 0, session, lambda _: None)
    assert not session["sent"] and not send._recent


@pytest.mark.parametrize("change", ["recall", "delete", "collision"])
def test_reference_invalidated_while_waiting_in_send_queue_is_not_dispatched(sender, change):
    send, connection, messages, session = sender
    event = {
        "post_type": "message",
        "self_id": ACCOUNT,
        "message_type": "private",
        "user_id": PEER,
        "message_id": 9,
        "message_seq": 1,
        "message": "source",
    }
    messages.ingest(ACCOUNT, event)
    checked = threading.Event()
    original = messages.has_mid

    def has_mid(*args, **kwargs):
        result = original(*args, **kwargs)
        checked.set()
        return result

    messages.has_mid = has_mid
    errors = []

    def run():
        try:
            send.send(
                ACCOUNT,
                KEY,
                {"messages": ["reply"], "replyToMessageId": 9},
                0,
                session,
                lambda _: None,
            )
        except ValueError as error:
            errors.append(error)

    with send._dispatch_lock:
        worker = threading.Thread(target=run)
        worker.start()
        assert checked.wait(2)
        if change == "recall":
            messages.recall(ACCOUNT, KEY, 9)
        elif change == "delete":
            messages.delete(ACCOUNT, KEY)
        else:
            messages.ingest(ACCOUNT, {**event, "message_seq": 2})
    worker.join(2)
    assert not worker.is_alive() and errors
    assert not connection.calls and not session["sent"]


def test_face_codes_are_split_into_onebot_face_segments():
    assert face_segments("早 [CQ:face,id=13]") == [
        {"type": "text", "data": {"text": "早 "}},
        {"type": "face", "data": {"id": "13"}},
    ]
    assert face_segments("[表情:384]你说说") == [
        {"type": "face", "data": {"id": "384"}},
        {"type": "text", "data": {"text": "你说说"}},
    ]
    assert face_segments("[表情:呲牙]早 [表情:doge]") == [
        {"type": "face", "data": {"id": "13"}},
        {"type": "text", "data": {"text": "早 "}},
        {"type": "face", "data": {"id": "179"}},
    ]
    # 官方新表条目：名字、纯数字编号、特殊字符名（+1）都按表解析。
    assert face_segments("[表情:晚安] [表情:干饭] [表情:+1]") == [
        {"type": "face", "data": {"id": "384"}},
        {"type": "text", "data": {"text": " "}},
        {"type": "face", "data": {"id": "475"}},
        {"type": "text", "data": {"text": " "}},
        {"type": "face", "data": {"id": "449"}},
    ]
    assert face_segments("[CQ:face,id=13]") == [{"type": "face", "data": {"id": "13"}}]
    # 未知名字、表外编号和非数字写法不是有效表情码，按普通文本原样发送。
    assert face_segments("[表情:狗头] [CQ:face, id=13] [CQ:face,id=999] [表情:999]") == [
        {"type": "text", "data": {"text": "[表情:狗头] [CQ:face, id=13] [CQ:face,id=999] [表情:999]"}}
    ]


def test_face_messages_keep_receipt_dedupe_and_archive_text(sender):
    send, connection, messages, session = sender
    send.send(ACCOUNT, KEY, {"messages": ["早 [表情:13]"]}, 0, session, lambda _: None)
    assert [item["text"] for item in session["sent"]] == ["早 [表情:13]"]
    # 存档正文把已知表情渲染成名字，模型之后能照抄。
    assert messages.messages(ACCOUNT, KEY)["items"][0]["text"] == "早 [表情:呲牙]"
    # 相同正文在本次处理内去重，回执为空。
    result = send.send(ACCOUNT, KEY, {"messages": ["早 [表情:13]"]}, 0, session, lambda _: None)
    assert result["deduped"] == 1 and result["sent"] == 0
