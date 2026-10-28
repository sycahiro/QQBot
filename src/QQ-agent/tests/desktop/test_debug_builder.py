import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from qqbot.desktop.debug import READ_ACTIONS, SEND_ACTIONS, catalog, safe_detail
from qqbot.qq.engine import EngineError
from test_debug import ACCOUNT, OTHER, PEER
from test_debug import debug as debug


@pytest.fixture
def builder(debug):
    yield debug
    debug[0]._debug_files.close()


def stage(bridge, kind="image", name="test.png", data=None):
    if data is None:
        stream = io.BytesIO()
        Image.new("RGB", (20, 10), "red").save(stream, "PNG")
        data = stream.getvalue()
    result = bridge.stage_debug_file(kind, name, base64.b64encode(data).decode(), ACCOUNT)
    assert result["ok"], result
    return result["attachment"]


def segment(kind, data):
    return {"type": kind, "data": data}


def send(bridge, message, action="send_private_msg", peer=PEER):
    return bridge.run_debug_action(
        action, {"group_id" if "group" in action else "user_id": peer, "message": message}, ACCOUNT
    )


def test_rich_image_message_uses_staged_clean_bytes_and_does_not_archive_paths(builder):
    bridge, conn, _, messages = builder
    item = stage(bridge)
    result = send(
        bridge,
        [
            segment("text", {"text": "图片测试"}),
            segment("image", {"file": item["token"]}),
            segment("face", {"id": "14"}),
        ],
    )
    assert result["ok"] and result["result"]["sent"] == 1
    sent = conn.calls[0][1]["message"]
    file = Path(sent[1]["data"]["file"])
    assert file.exists()
    with Image.open(file) as image:
        assert image.format == "JPEG"
    archived = messages.context(ACCOUNT, f"private:{PEER}")[0]
    assert archived["text"] == "图片测试[图片][表情]"
    assert str(file) not in json.dumps(archived) and "base64" not in json.dumps(archived)
    assert (
        send(
            bridge,
            [
                segment("text", {"text": "图片测试"}),
                segment("image", {"file": item["token"]}),
                segment("face", {"id": "14"}),
            ],
        )["result"]["deduped"]
        == 1
    )
    assert len(conn.calls) == 1


@pytest.mark.parametrize(
    "source",
    ["https://example.com/photo", "C:\\private.png", "base64://AAAA", "../private", "0" * 32],
)
def test_arbitrary_media_paths_urls_and_unknown_handles_cannot_send(builder, source):
    bridge, conn, _, _ = builder
    assert not send(bridge, [segment("image", {"file": source})])["ok"] and not conn.calls


def test_staged_files_are_account_bound_expire_and_detect_changes(builder):
    bridge, conn, selection, _ = builder
    item = stage(bridge)
    selection.value = OTHER
    assert not bridge.stage_debug_file("file", "x.txt", "eA==", ACCOUNT)["ok"]
    assert not send(bridge, [segment("image", {"file": item["token"]})])["ok"]
    selection.value = ACCOUNT
    stored = bridge._debug_files._items[item["token"]]
    stored["path"].write_bytes(b"changed")
    assert not send(bridge, [segment("image", {"file": item["token"]})])["ok"] and not conn.calls
    item2 = stage(bridge)
    bridge._debug_files._items[item2["token"]]["created"] -= 901
    assert not send(bridge, [segment("image", {"file": item2["token"]})])["ok"]


@pytest.mark.parametrize(
    "kind,name,data",
    [
        ("record", "test.wav", b"RIFF1234WAVE" + b"\x00" * 30),
        ("video", "test.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20),
        ("file", "test.txt", b"hello"),
    ],
)
def test_standalone_voice_video_and_file_use_native_message_pipeline(builder, kind, name, data):
    bridge, conn, _, messages = builder
    item = stage(bridge, kind, name, data)
    value = send(bridge, [segment(kind, {"file": item["token"]})])
    assert value["ok"] and value["result"]["messageIds"] == ["-1"]
    assert Path(conn.calls[0][1]["message"][0]["data"]["file"]).read_bytes() == data
    assert "file" not in messages.context(ACCOUNT, f"private:{PEER}")[0]["segments"][0]["data"]
    assert not send(
        bridge, [segment(kind, {"file": item["token"]}), segment("text", {"text": "不能混用"})]
    )["ok"]
    assert len(conn.calls) == 1


def test_forward_nodes_route_to_native_forward_action_and_fixed_current_identity(builder):
    bridge, conn, _, messages = builder
    message = [
        segment("node", {"content": [segment("text", {"text": "节点一"})]}),
        segment("node", {"content": [segment("face", {"id": 1})]}),
    ]
    result = send(bridge, message, "send_private_forward_msg")
    assert result["ok"]
    action, params = conn.calls[0]
    assert (
        action == "send_private_forward_msg" and params["messages"][0]["data"]["user_id"] == ACCOUNT
    )
    assert "节点一" not in messages.context(ACCOUNT, f"private:{PEER}")[0]["text"]
    assert messages.context(ACCOUNT, f"private:{PEER}")[0]["text"].startswith("[合并转发")
    assert not send(
        bridge,
        [segment("node", {"user_id": OTHER, "content": [segment("text", {"text": "伪造"})]})],
        "send_private_forward_msg",
    )["ok"]
    assert not send(bridge, [segment("node", {"content": message})], "send_private_forward_msg")[
        "ok"
    ]
    assert len(conn.calls) == 1


def test_reply_must_belong_to_current_chat_and_mentions_must_not_be_blocked(builder):
    bridge, conn, _, messages = builder
    messages.ingest(
        ACCOUNT,
        {
            "post_type": "message",
            "self_id": ACCOUNT,
            "message_type": "group",
            "group_id": "99887766",
            "user_id": PEER,
            "message_id": -12,
            "sender": {"user_id": PEER},
            "message": [segment("text", {"text": "source"})],
        },
    )
    assert send(
        bridge,
        [segment("reply", {"id": -12}), segment("text", {"text": "引用"})],
        "send_group_msg",
        "99887766",
    )["ok"]
    messages.recall(ACCOUNT, "group:99887766", -12)
    assert not send(
        bridge,
        [segment("reply", {"id": -12}), segment("text", {"text": "撤回"})],
        "send_group_msg",
        "99887766",
    )["ok"]
    bridge._settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    assert not send(bridge, [segment("at", {"qq": PEER})], "send_group_msg", "99887766")["ok"]
    assert len(conn.calls) == 1


def test_clear_during_inflight_send_keeps_attachment_until_ack_and_cleans_afterward(builder):
    bridge, conn, selection, messages = builder
    item = stage(bridge)
    path = bridge._debug_files._items[item["token"]]["path"]

    def native(action, params, expected_account=None):
        assert path.exists()
        bridge._debug_files.clear()
        assert path.exists()
        selection.value = OTHER
        return {"status": "ok", "data": {"message_id": -99}}

    conn.invoke = native
    assert not send(bridge, [segment("image", {"file": item["token"]})])["ok"]
    assert not path.exists()
    assert messages.context(ACCOUNT, f"private:{PEER}")[0]["mid"] == "-99"


def test_unknown_delivery_is_logged_once_without_resend(builder):
    bridge, conn, _, _ = builder
    conn.error = EngineError("REQUEST_TIMEOUT", "unknown")
    result = send(bridge, [segment("face", {"id": 1})])
    assert not result["ok"] and len(conn.calls) == 1 and "未确认" in result["error"]["message"]
    item = bridge.get_debug_activity(ACCOUNT)["items"][0]
    assert item["kind"] == "error" and "durationMs" in item["detail"]


def test_stage_limits_types_and_close_cleanup(builder):
    bridge, _, _, _ = builder
    assert not bridge.stage_debug_file(
        "record", "evil.exe", base64.b64encode(b"MZabc").decode(), ACCOUNT
    )["ok"]
    assert not bridge.stage_debug_file("image", "../x.png", "eA==", ACCOUNT)["ok"]
    assert not bridge.stage_debug_file("image", "x.png", "invalid", ACCOUNT)["ok"]
    entries = [stage(bridge, "file", f"{i}.txt", b"x") for i in range(8)]
    assert not bridge.stage_debug_file("file", "ninth.txt", "eA==", ACCOUNT)["ok"]
    paths = [bridge._debug_files._items[e["token"]]["path"] for e in entries]
    bridge._debug_files.close()
    assert not any(p.exists() for p in paths)


def test_new_read_queries_are_scoped_and_schema_uses_only_allowed_fields(builder):
    bridge, conn, _, _ = builder
    assert len(READ_ACTIONS) == 21 and len(SEND_ACTIONS) == 4
    assert bridge.run_debug_action("get_group_root_files", {"group_id": "99887766"}, ACCOUNT)["ok"]
    assert not bridge.run_debug_action("get_group_root_files", {"group_id": "88776655"}, ACCOUNT)[
        "ok"
    ]
    assert not bridge.run_debug_action("get_stranger_info", {"user_id": OTHER}, ACCOUNT)["ok"]
    assert not bridge.run_debug_action(
        "get_group_msg_history", {"group_id": "99887766", "count": 1000}, ACCOUNT
    )["ok"]
    assert not bridge.run_debug_action(
        "get_msg", {"chat_key": f"private:{PEER}", "message_id": 99}, ACCOUNT
    )["ok"]
    assert not bridge.run_debug_action("get_cookies", {}, ACCOUNT)["ok"]
    assert len(conn.calls) == 1
    conn.action_docs = lambda: [
        {
            "name": "get_msg",
            "inputSchema": {
                "properties": {"message_id": {"type": "integer"}, "forbidden": {"type": "string"}},
                "required": ["message_id"],
            },
        }
    ]
    doc = catalog(conn)[0]
    assert (
        set(doc["inputSchema"]["properties"]) == {"message_id", "chat_key"}
        and doc["inputSchema"]["additionalProperties"] is False
    )


def test_debug_activity_details_redact_credentials_paths_bytes_and_urls():
    result = safe_detail(
        {
            "cookie": "private",
            "result": {"url": "https://private.test?ticket=secret", "file": "C:\\private.jpg"},
            "body": "data:image/jpeg;base64,private",
            "text": "http://private.test?x=secret",
        }
    )
    text = json.dumps(result)
    assert "private" not in text and "secret" not in text and "base64" not in text
