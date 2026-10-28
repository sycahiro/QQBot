"""复用 OneBot 文档和动作实现；仅开放列明的查询与手动消息构建。"""

import asyncio
import copy
import re
import threading
import time
from collections import deque

from ..agent.config import allowed
from ..agent.queries import MessageQueries, verify_native
from ..storage.messages import chat_key, numeric_id
from .debug_messages import send as send_message

READ_ACTIONS = {
    "get_login_info": set(),
    "get_status": set(),
    "get_version_info": set(),
    "can_send_image": set(),
    "get_friend_list": set(),
    "get_group_list": set(),
    "get_group_info": {"group_id", "no_cache"},
    "get_group_member_list": {"group_id"},
    "get_group_member_info": {"group_id", "user_id", "no_cache"},
    "can_send_record": set(),
    "get_online_clients": {"no_cache"},
    "get_stranger_info": {"user_id", "no_cache"},
    "get_group_honor_info": {"group_id", "type"},
    "get_essence_msg_list": {"group_id"},
    "get_group_file_system_info": {"group_id"},
    "get_group_root_files": {"group_id"},
    "get_group_files_by_folder": {"group_id", "folder_id", "folder"},
    "get_group_msg_history": {"group_id", "message_id", "count", "reverse_order"},
    "get_friend_msg_history": {"user_id", "message_id", "count", "reverse_order"},
    "get_msg": {"chat_key", "message_id"},
    "get_forward_msg": {"chat_key", "message_id"},
}
SEND_ACTIONS = {
    "send_private_msg",
    "send_group_msg",
    "send_private_forward_msg",
    "send_group_forward_msg",
}

# Upstream summaries often contain only a category such as “信息” or “消息”.
# Supply task-oriented names for the explicitly supported desktop operations.
ACTION_HELP = {
    "get_login_info": ("登录账号", "查看当前连接 QQ 的号码和昵称。"),
    "get_status": ("连接状态", "检查 QQ 连接和运行状态。"),
    "get_version_info": ("引擎版本", "查看 QQ 接口引擎的版本信息。"),
    "can_send_image": ("图片发送能力", "检查当前 QQ 接口是否支持发送图片。"),
    "can_send_record": ("语音发送能力", "检查当前 QQ 接口是否支持发送语音。"),
    "get_friend_list": ("好友列表", "读取当前 QQ 的好友号码、昵称和备注。"),
    "get_group_list": ("群聊列表", "读取当前 QQ 加入的群聊。"),
    "get_group_info": ("群聊资料", "查看白名单内指定群聊的名称和成员数量。"),
    "get_group_member_list": ("群成员列表", "读取白名单内指定群聊的成员。"),
    "get_group_member_info": ("群成员资料", "查看白名单群聊中指定成员的昵称、群名片等资料。"),
    "get_online_clients": ("在线设备", "查看当前 QQ 账号的在线客户端。"),
    "get_stranger_info": ("用户资料", "查看白名单内指定好友的公开资料。"),
    "get_group_honor_info": ("群荣誉", "查看白名单内指定群聊的荣誉信息。"),
    "get_essence_msg_list": ("群精华消息", "查看白名单内指定群聊的精华消息。"),
    "get_group_file_system_info": ("群文件空间", "查看白名单内指定群聊的文件数量和空间。"),
    "get_group_root_files": ("群根目录文件", "列出白名单内指定群聊根目录的文件和文件夹。"),
    "get_group_files_by_folder": ("群文件夹内容", "列出白名单群聊中指定文件夹的内容。"),
    "get_group_msg_history": ("群聊天记录", "读取白名单内指定群聊的近期消息。"),
    "get_friend_msg_history": ("好友聊天记录", "读取白名单内指定好友的近期消息。"),
    "get_msg": ("消息详情", "通过当前聊天存档中的消息编号，查询该条消息的原始详情。"),
    "get_forward_msg": ("合并转发内容", "通过当前聊天存档中的消息编号，展开该条合并转发。"),
    "send_private_msg": ("发送私聊消息", "向白名单内的好友发送手动测试消息。"),
    "send_group_msg": ("发送群聊消息", "向白名单内的群聊发送手动测试消息。"),
    "send_private_forward_msg": ("发送私聊合并转发", "向白名单内的好友发送手动构建的合并转发。"),
    "send_group_forward_msg": ("发送群聊合并转发", "向白名单内的群聊发送手动构建的合并转发。"),
}


def safe_detail(value, depth=0, budget=None):
    if budget is None:
        budget = [60000]
    if depth > 5 or budget[0] <= 0:
        return "[其余内容已省略]"
    if isinstance(value, dict):
        result = {}
        for k, v in list(value.items())[:80]:
            if budget[0] <= 0:
                result["…"] = "[其余内容已省略]"
                break
            key = str(k)[:120]
            budget[0] -= len(key.encode())
            sensitive = re.sub(r"[^a-z0-9]", "", key.lower())
            result[key] = (
                "[已隐藏]"
                if any(
                    word in sensitive
                    for word in (
                        "cookie",
                        "token",
                        "rkey",
                        "secret",
                        "authorization",
                        "password",
                        "apikey",
                        "accesskey",
                        "privatekey",
                        "credential",
                        "url",
                    )
                )
                or key == "file"
                else safe_detail(v, depth + 1, budget)
            )
        return result
    if isinstance(value, list):
        result = []
        for item in value[:50]:
            if budget[0] <= 0:
                break
            result.append(safe_detail(item, depth + 1, budget))
        if len(result) < len(value):
            result.append("[其余条目已省略]")
        return result
    if isinstance(value, str):
        if "base64" in value or re.search(r"(?:[A-Za-z]:[\\/]|file://)", value):
            return "[已隐藏文件内容或路径]"
        clean = (
            re.sub(r"https?://\S+", "[地址已隐藏]", value[:3000])
            .encode()[: max(0, budget[0])]
            .decode(errors="ignore")
        )
        budget[0] -= len(clean.encode())
        return clean
    budget[0] -= 24
    return (
        value if value is None or type(value) in (bool, int, float) else str(type(value).__name__)
    )


class Activity:
    def __init__(self):
        self._items, self._sequence, self._lock = deque(maxlen=200), 0, threading.Lock()

    def add(self, account, kind, summary, detail=None):
        if not account:
            return
        with self._lock:
            self._sequence += 1
            self._items.append(
                {
                    "id": self._sequence,
                    "account": account,
                    "kind": kind,
                    "time": int(time.time() * 1000),
                    "summary": str(summary)[:1000],
                    **({"detail": safe_detail(detail)} if detail is not None else {}),
                }
            )

    def read(self, account, after=0):
        if type(after) is not int or after < 0:
            raise ValueError("无效的活动位置")
        with self._lock:
            return {
                "items": [
                    copy.deepcopy(i)
                    for i in self._items
                    if i["account"] == account and i["id"] > after
                ],
                "cursor": self._sequence,
            }


def catalog(connection):
    docs = connection.action_docs()
    if isinstance(docs, dict) and isinstance(docs.get("actions"), str):
        # SnowLuma only exposes OneBot 11 standard actions through a whitelist
        # and reports them as a summary string; browse the local table instead.
        docs = [{"name": name} for name in (*READ_ACTIONS, *SEND_ACTIONS)]
    if not isinstance(docs, list):
        raise ValueError("QQ 接口文档返回格式错误")
    result = []
    for doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("name"), str):
            continue
        name = doc["name"]
        callable = name in READ_ACTIONS or name in SEND_ACTIONS
        item = {**doc, "callable": callable}
        if callable:
            title, description = ACTION_HELP[name]
            item.update(summary=title, description=description, readOnly=name in READ_ACTIONS)
            fields = READ_ACTIONS.get(
                name, {"group_id" if "group" in name else "user_id", "message"}
            )
            schema = doc.get("inputSchema") if isinstance(doc.get("inputSchema"), dict) else {}
            properties = {k: v for k, v in schema.get("properties", {}).items() if k in fields}
            required = [k for k in schema.get("required", []) if k in fields]
            for field in fields:
                properties.setdefault(
                    field,
                    {
                        "type": "boolean"
                        if field in ("no_cache", "reverse_order")
                        else "integer"
                        if field == "count"
                        else "string"
                    },
                )
            for field in ("group_id", "user_id", "message", "chat_key", "message_id"):
                if (
                    field in fields
                    and (
                        field in ("group_id", "user_id", "message", "chat_key")
                        or name in ("get_msg", "get_forward_msg")
                    )
                    and field not in required
                ):
                    required.append(field)
            if "chat_key" in fields:
                properties["chat_key"] = {
                    "type": "string",
                    "description": "当前账号已存档的 group:群号 或 private:QQ号",
                }
            item.update(
                inputSchema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                params=[p for p in doc.get("params", []) if p.get("name") in fields],
            )
        result.append(item)
    return result


def invoke(bridge, action, params, account):
    if not isinstance(action, str):
        raise ValueError("无效的接口名称")
    if action not in READ_ACTIONS and action not in SEND_ACTIONS:
        raise ValueError("该接口尚未向桌面测试台开放，可在 API 浏览器查看文档")
    if not isinstance(params, dict):
        raise ValueError("参数必须为 JSON 对象")
    if bridge._settings is None or bridge._messages is None:
        raise ValueError("账号数据尚未就绪")
    if action in READ_ACTIONS:
        if set(params) - READ_ACTIONS[action]:
            raise ValueError("接口含未知参数")
        config = bridge._settings.read(account)
        if "group_id" in READ_ACTIONS[action]:
            if not allowed("group", str(params.get("group_id", "")), "", config):
                raise ValueError("仅能查询当前机器人白名单中的群聊")
        if action in ("get_stranger_info", "get_friend_msg_history"):
            user = str(params.get("user_id", ""))
            if not allowed("private", user, user, config):
                raise ValueError("只能查询白名单内未屏蔽的好友")
        for field in ("group_id", "user_id"):
            if field in params and not re.fullmatch(r"[1-9]\d{0,19}", str(params[field])):
                raise ValueError("目标号码无效")
        if "user_id" in params and str(params["user_id"]) in config["blockedUsers"]:
            raise ValueError("该成员已屏蔽")
        for field in ("no_cache", "reverse_order"):
            if field in params and type(params[field]) is not bool:
                raise ValueError("开关参数必须为布尔值")
        if "count" in params and (
            type(params["count"]) is not int or not 1 <= params["count"] <= 100
        ):
            raise ValueError("查询数量应为 1 到 100")
        for field in ("folder", "folder_id", "type"):
            if field in params and (
                not isinstance(params[field], str)
                or len(params[field]) > 256
                or any(ord(c) < 32 for c in params[field])
            ):
                raise ValueError("查询文本参数无效")
        if (
            "message_id" in params
            and params["message_id"] != 0
            and numeric_id(params["message_id"]) is None
        ):
            raise ValueError("消息编号无效")
        if (
            action in ("get_group_msg_history", "get_friend_msg_history")
            and params.get("message_id", 0) != 0
        ):
            key = f"{'group' if action == 'get_group_msg_history' else 'private'}:{params.get('group_id') if action == 'get_group_msg_history' else params.get('user_id')}"
            bridge._messages.message_detail(account, key, params["message_id"])
        if action in ("get_msg", "get_forward_msg"):
            key = chat_key(params.get("chat_key"))
            source = bridge._messages.message_detail(account, key, params.get("message_id"))

            def permit():
                if bridge._active_account() != account:
                    return False
                try:
                    current = bridge._messages.message_detail(account, key, source["mid"])
                except ValueError:
                    return False
                kind, peer = key.split(":")
                return current["id"] == source["id"] and allowed(
                    kind, peer, current["senderId"], bridge._settings.read(account)
                )

            if not permit():
                raise ValueError("消息不在当前白名单范围内")

            async def native(name, values):
                with bridge._agent.native_lock if bridge._agent else bridge._native_fallback_lock:
                    if not permit():
                        raise ValueError("消息或账号已变化，查询已停止")
                    return bridge._connection.invoke(name, values, expected_account=account)

            if action == "get_forward_msg":
                queries = MessageQueries(
                    bridge._messages, native, lambda _: None, permit, lambda _: True
                )
                try:
                    result = asyncio.run(
                        queries.execute("read_forward", account, key, {"messageId": source["mid"]})
                    )
                except asyncio.CancelledError:
                    raise ValueError("消息或账号已变化，转发查询已停止") from None
            else:
                result = asyncio.run(native("get_msg", {"message_id": source["mid"]}))
                verify_native(account, key, source, result)
                if not permit():
                    raise ValueError("消息或账号已变化，查询结果已丢弃")
        else:
            with bridge._agent.native_lock if bridge._agent else bridge._native_fallback_lock:
                if bridge._active_account() != account:
                    raise ValueError("账号已变化，未提交查询")
                result = bridge._connection.invoke(action, params, expected_account=account)
            if bridge._active_account() != account:
                raise ValueError("账号已变化，查询结果已丢弃")
    else:
        result = send_message(bridge, action, params, account)
    return result
