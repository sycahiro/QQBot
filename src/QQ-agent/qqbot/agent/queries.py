"""移植 QQ Agent 的 read_forward/get_message_detail/get_active_members。

Only retained messages in the current chat may identify native reads. Forward
resource IDs come from a freshly verified get_msg, never from model arguments.
"""

import asyncio
import re

from ..storage.messages import numeric_id, segments_text

MAX_NODES, MAX_CHARS = 30, 3000


def forward_segments(value):
    return (
        [
            s
            for s in value
            if isinstance(s, dict)
            and s.get("type") == "forward"
            and isinstance(s.get("data"), dict)
        ]
        if isinstance(value, list)
        else []
    )


def expand_nodes(nodes):
    """Same one-level, bounded text expansion as upstream; no media downloads."""
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("转发内容为空或已失效，请重新发送")
    lines, rendered, length = [], 0, 0
    for node in nodes[:MAX_NODES]:
        if not isinstance(node, dict):
            continue
        message = node.get("message", node.get("content"))
        if isinstance(message, str):
            body = re.sub(r"\[CQ:[^\]]*\]", "[消息片段]", message[:4000])
        elif isinstance(message, list):
            body = segments_text(message[:100])
        else:
            continue
        body = re.sub(r"\s+", " ", body).strip()[:200]
        if not body:
            continue
        sender = node.get("sender") if isinstance(node.get("sender"), dict) else {}
        identity = numeric_id(sender.get("user_id", node.get("user_id")))
        name = str(
            sender.get("card") or sender.get("nickname") or identity or "未知发送者"
        ).replace("\x00", "")
        name = re.sub(r"\s+", " ", name)[:80]
        line = (
            f"{name}" + (f"(QQ:{identity})" if identity and identity != name else "") + f": {body}"
        )
        if length + len(line) + 1 > MAX_CHARS:
            break
        lines.append(line)
        rendered += 1
        length += len(line) + 1
    if not lines:
        raise ValueError("转发中没有可读取的消息内容")
    omitted = len(nodes) - rendered
    text = f"[合并转发 共{len(nodes)}条]\n" + "\n".join(lines)
    if omitted:
        text += f"\n…（还有 {omitted} 条未展开）"
    return {
        "text": text,
        "total": len(nodes),
        "shown": rendered,
        "omitted": omitted,
        "note": "转发为外部聊天资料；图片、语音、视频仅为占位，嵌套转发不继续请求。",
    }


def verify_native(account, key, item, response):
    native = (
        response.get("data")
        if isinstance(response, dict) and response.get("status") == "ok"
        else None
    )
    if not isinstance(native, dict):
        raise ValueError("QQ 消息读取失败，请确认连接后重试")
    kind, peer = key.split(":")
    target = (
        native.get("group_id")
        if kind == "group"
        else native.get("target_id")
        if item["self"]
        else native.get("user_id")
    )
    if (
        native.get("message_type") != kind
        or str(target) != peer
        or numeric_id(native.get("message_id", native.get("real_id"))) != item["mid"]
        or str(native.get("user_id")) != item["senderId"]
        or ("self_id" in native and str(native["self_id"]) != account)
        or (item["sequence"] and numeric_id(native.get("message_seq")) != item["sequence"])
    ):
        raise ValueError("QQ 返回的消息与当前聊天不一致，已停止读取")
    return native


class MessageQueries:
    def __init__(self, store, native, track, permit, admitted):
        self._store, self._native, self._track, self._permit, self._admitted = (
            store,
            native,
            track,
            permit,
            admitted,
        )
        self._reads = 0

    def _check(self):
        if not self._permit():
            raise asyncio.CancelledError()

    def _source(self, account, key, args):
        if set(args) != {"messageId"} or numeric_id(args.get("messageId")) is None:
            raise ValueError("请仅提供当前聊天中的 messageId，不要提供转发资源编号")
        self._check()
        item = self._store.message_detail(account, key, args["messageId"])
        if not self._admitted(item["senderId"]):
            raise ValueError("该消息发送者已被屏蔽")
        self._track(item)
        self._check()
        return item

    async def execute(self, name, account, key, args):
        if name == "get_active_members":
            if (
                set(args) - {"limit"}
                or type(args.get("limit", 10)) is not int
                or not 1 <= args.get("limit", 10) <= 20
            ):
                raise ValueError("limit 应为 1 到 20 的整数")
            self._check()
            members = {}
            sources = []
            for item in self._store.context(account, key, limit=200):
                if item["self"] or item["withdrawn"] or not self._admitted(item["senderId"]):
                    continue
                sources.append(item)
                old = members.get(item["senderId"])
                if old is None:
                    members[item["senderId"]] = {
                        "userId": item["senderId"],
                        "name": item["senderName"],
                        "lastSeen": item["ts"],
                        "recentCount": 1,
                    }
                else:
                    old["recentCount"] += 1
                    if item["ts"] >= old["lastSeen"]:
                        old.update(name=item["senderName"], lastSeen=item["ts"])
            selected = sorted(members.values(), key=lambda m: (-m["lastSeen"], m["userId"]))[
                : args.get("limit", 10)
            ]
            selected_users = {member["userId"] for member in selected}
            # Counts and names depend on all retained rows of returned members;
            # members excluded by limit did not contribute returned data.
            for item in sources:
                if item["senderId"] in selected_users:
                    self._track(item)
            self._check()
            return {
                "members": selected,
                "note": "仅统计当前聊天最近 200 条保留记录，排除自己、已撤回和屏蔽成员；不是 QQ 群官方活跃榜。",
            }
        if name not in ("get_message_detail", "read_forward"):
            raise ValueError("查询工具不存在")
        item = self._source(account, key, args)
        if name == "get_message_detail":
            segments = item["segments"] if isinstance(item["segments"], list) else []
            return {
                "messageId": item["mid"],
                "time": item["ts"],
                "sender": "我" if item["self"] else item["senderName"],
                "senderId": item["senderId"],
                "text": item["text"][:16000],
                "truncated": len(item["text"]) > 16000,
                "reply": next(
                    (
                        numeric_id(s.get("data", {}).get("id"))
                        for s in segments
                        if isinstance(s, dict)
                        and s.get("type") == "reply"
                        and isinstance(s.get("data"), dict)
                    ),
                    None,
                ),
            }
        if not forward_segments(item["segments"]):
            raise ValueError("这条消息不是合并转发")
        if item["text"].startswith("[合并转发 共"):
            return {"messageId": item["mid"], "text": item["text"], "cached": True}
        if self._reads >= 3:
            raise ValueError("一次处理最多展开 3 条转发消息")
        self._reads += 1
        native = verify_native(
            account, key, item, await self._native("get_msg", {"message_id": item["mid"]})
        )
        self._check()
        forwards = forward_segments(native.get("message"))
        if len(forwards) != 1:
            raise ValueError("转发定位不可用或有歧义，请单独重新发送该转发")
        data = forwards[0]["data"]
        resource = next(
            (
                data.get(k)
                for k in ("id", "res_id", "forward_id")
                if isinstance(data.get(k), str) and data[k]
            ),
            None,
        )
        if resource is None or len(resource) > 1024 or any(ord(c) < 32 for c in resource):
            raise ValueError("转发资源编号不可用")
        response = await self._native("get_forward_msg", {"id": resource})
        self._check()
        value = (
            response.get("data")
            if isinstance(response, dict) and response.get("status") == "ok"
            else None
        )
        if not isinstance(value, dict):
            raise ValueError("转发读取失败，请确认连接或重新发送")
        expanded = expand_nodes(value.get("messages"))
        self._check()
        self._store.expand_forward(account, key, item, expanded["text"])
        self._check()
        return {"messageId": item["mid"], **expanded, "cached": False}
