"""Validate visual-builder segments, reusing Sender's queue and receipt handling."""

import hashlib
import json
import re

from ..agent.config import allowed
from ..agent.sender import Sender
from ..storage.messages import chat_key, numeric_id


def attachments(message):
    result = []
    for segment in message if isinstance(message, list) else []:
        if not isinstance(segment, dict):
            continue
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        if segment.get("type") == "node":
            result.extend(attachments(data.get("content")))
        elif segment.get("type") in ("image", "record", "video", "file"):
            token = data.get("file")
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
                raise ValueError("媒体只接受本窗口已选择的附件，不接受 URL、路径或 base64")
            result.append(token)
    return result


def send(bridge, action, params, account):
    group = "group" in action
    forward = "forward" in action
    kind, field = ("group", "group_id") if group else ("private", "user_id")
    if set(params) != {field, "message"}:
        raise ValueError("消息参数只接受目标号码和 message")
    key = chat_key(f"{kind}:{params[field]}")
    message = params["message"]
    if isinstance(message, str):
        message = [{"type": "text", "data": {"text": message}}]
    if not isinstance(message, list) or not 1 <= len(message) <= 16:
        raise ValueError("消息需要 1 到 16 个片段")
    # Bound before walking nested nodes, so a hand-written JSON tree cannot recurse indefinitely.
    try:
        raw = json.dumps(message, ensure_ascii=False, allow_nan=False)
    except ValueError, TypeError, RecursionError:
        raise ValueError("消息片段格式无效") from None
    if len(raw.encode()) > 64000:
        raise ValueError("消息构建参数超过 64 KB")
    if forward:
        if len(message) > 5 or any(
            not isinstance(s, dict) or s.get("type") != "node" for s in message
        ):
            raise ValueError("合并转发需要 1 到 5 个节点")
        if any(
            not isinstance(s.get("data"), dict) or set(s["data"]) != {"content"} for s in message
        ):
            raise ValueError("转发节点只接受 content，不允许伪造发送者")
        if any(
            not isinstance(s["data"]["content"], list)
            or any(isinstance(n, dict) and n.get("type") == "node" for n in s["data"]["content"])
            for s in message
        ):
            raise ValueError("不支持嵌套转发节点")
    elif any(isinstance(s, dict) and s.get("type") == "node" for s in message):
        raise ValueError("节点消息请使用合并转发接口")
    tokens = attachments(message)
    replies = {}
    mentions = []

    def permit(a, chat, epoch):
        if bridge._active_account() != a:
            return False
        cfg = bridge._settings.read(a)
        return (
            allowed(kind, str(params[field]), "", cfg)
            and all(user not in cfg["blockedUsers"] for user in mentions)
            and all(reply_valid(a, mid, identity) for mid, identity in replies.items())
            and bridge._debug_files.valid(a, tokens)
        )

    def reply_valid(a, mid, identity):
        try:
            return bridge._messages.message_detail(a, key, mid)["id"] == identity
        except ValueError:
            return False

    with bridge._debug_files.use(account, tokens) as files:

        def convert(values, nested=False):
            if not isinstance(values, list) or not 1 <= len(values) <= 16:
                raise ValueError("消息节点片段数无效")
            native = []
            archive = []
            digest = []
            for segment in values:
                if (
                    not isinstance(segment, dict)
                    or set(segment) != {"type", "data"}
                    or not isinstance(segment["data"], dict)
                ):
                    raise ValueError("消息片段结构无效")
                typ, data = segment["type"], segment["data"]
                if typ == "text":
                    if (
                        set(data) != {"text"}
                        or not isinstance(data["text"], str)
                        or not data["text"].strip()
                        or len(data["text"]) > 3000
                    ):
                        raise ValueError("文本片段应为 1 到 3000 字")
                    clean = {"type": "text", "data": {"text": data["text"].replace("\x00", "")}}
                elif typ == "face":
                    if set(data) != {"id"} or not re.fullmatch(r"\d{1,5}", str(data["id"])):
                        raise ValueError("表情编号应为 0 到 99999")
                    clean = {"type": "face", "data": {"id": int(data["id"])}}
                elif typ == "reply":
                    mid = numeric_id(data.get("id"))
                    if (
                        nested
                        or set(data) != {"id"}
                        or not mid
                        or not bridge._messages.has_mid(account, key, mid)
                    ):
                        raise ValueError("引用必须来自当前聊天未撤回的存档")
                    replies[mid] = bridge._messages.message_detail(account, key, mid)["id"]
                    clean = {"type": "reply", "data": {"id": mid}}
                elif typ == "at":
                    user = str(data.get("qq", ""))
                    if (
                        nested
                        or kind != "group"
                        or set(data) != {"qq"}
                        or not re.fullmatch(r"[1-9]\d{0,19}", user)
                    ):
                        raise ValueError("只能在群聊 @ 数字成员号码")
                    mentions.append(user)
                    clean = {"type": "at", "data": {"qq": user}}
                elif typ in ("image", "record", "video", "file"):
                    if (
                        set(data) != {"file"}
                        or data["file"] not in files
                        or files[data["file"]]["kind"] != typ
                    ):
                        raise ValueError("附件与消息片段类型不匹配")
                    if typ != "image" and (nested or len(values) != 1):
                        raise ValueError("语音、视频和文件需各自单独发送")
                    item = files[data["file"]]
                    clean = {
                        "type": typ,
                        "data": {
                            "file": str(item["path"]),
                            **({"name": item["name"]} if typ == "file" else {}),
                        },
                    }
                    native.append(clean)
                    archive.append({"type": typ, "data": {}})
                    digest.append((typ, item["digest"]))
                    continue
                elif typ == "node" and forward and not nested:
                    content, _, inner_digest = convert(data["content"], True)
                    native.append(
                        {
                            "type": "node",
                            "data": {"user_id": account, "nickname": "QQBot", "content": content},
                        }
                    )
                    archive.append({"type": "forward", "data": {}})
                    digest.append(("node", inner_digest))
                    continue
                else:
                    raise ValueError(
                        "不支持该消息片段；可用文字、图片、表情、@、引用、语音、视频、文件及转发节点"
                    )
                native.append(clean)
                archive.append(clean)
                digest.append(clean)
            return native, archive, digest

        native, archive, identity = convert(message)
        if sum(s.get("type") == "reply" for s in native) > 1 or any(
            s.get("type") == "reply" for s in native[1:]
        ):
            raise ValueError("引用片段最多一个，且必须位于第一项")
        sender = Sender(
            bridge._connection,
            bridge._messages,
            permit,
            dispatch_lock=bridge._agent.native_lock
            if bridge._agent
            else bridge._native_fallback_lock,
            rapid_submit_history=bridge._debug_recent,
        )
        session = {"sent": []}
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return sender.send_segments(
            account, key, native, archive, digest, session, action=action if forward else None
        )
