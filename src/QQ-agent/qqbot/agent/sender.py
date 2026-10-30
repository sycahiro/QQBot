"""当前聊天发送、首条引用与本轮成功去重；未知投递绝不重试。"""

import hashlib
import json
import re
import threading
import time

from ..qq.engine import EngineError
from ..faces import FACES, NAMES
from ..storage.messages import chat_key, numeric_id, segments_text


class DeliveryError(RuntimeError):
    pass


def _validate_model_text(text):
    # Reserved tool-control markup is not a real function call. Never dispatch
    # it, strip it into an invented reply, or interpret it as an action.
    if re.search(r"<\s*/?\s*(?:tool_calls?|arg_key|arg_value)(?=[\s/>]|$)", text, re.I):
        raise ValueError(
            "发送正文混入工具调用标签，未发送；请使用真正的函数调用，正文只填写聊天内容"
        )


# QQ built-in emoticon: OneBot CQ form [CQ:face,id=N], numeric [表情:N], and
# named [表情:呲牙] (resolved via the face table). Unknown names stay literal.
FACE_PATTERN = re.compile(
    r"\[(?:CQ:face,id=|表情:)(\d{1,3}|[a-zA-Z0-9+·!\u4e00-\u9fff]{1,10})\]", re.I
)


def face_segments(text):
    """Split plain text into alternating text/face OneBot segments."""
    segments = []
    pos = 0
    for match in FACE_PATTERN.finditer(text):
        token = match.group(1)
        if match.start() > pos:
            segments.append({"type": "text", "data": {"text": text[pos : match.start()]}})
        if token.isdigit():
            # Numeric ids must come from the face table; never trust guesses.
            face_id = int(token) if int(token) in FACES else None
        else:
            face_id = NAMES.get(token)
        if face_id is None:
            # Unknown name: keep the original bracketed form visible as text.
            if segments and segments[-1].get("type") == "text":
                segments[-1]["data"]["text"] += match.group(0)
            else:
                segments.append({"type": "text", "data": {"text": match.group(0)}})
        else:
            segments.append({"type": "face", "data": {"id": str(face_id)}})
        pos = match.end()
    if pos < len(text):
        segments.append({"type": "text", "data": {"text": text[pos:]}})
    merged = []
    for segment in segments:
        if (
            segment["type"] == "text"
            and merged
            and merged[-1]["type"] == "text"
        ):
            merged[-1]["data"]["text"] += segment["data"]["text"]
        else:
            merged.append(segment)
    if not merged:
        raise ValueError("发送内容为空")
    return merged


class Sender:
    def __init__(self, connection, messages, permit, *, dispatch_lock=None, rapid_submit_history=None):
        self._connection, self._messages, self._permit = connection, messages, permit
        self._lock = threading.Lock()
        self._dispatch_lock = dispatch_lock if dispatch_lock is not None else threading.Lock()
        self._recent = rapid_submit_history if rapid_submit_history is not None else {}

    def _prune_recent(self, now):
        # Preserve the manual builder's shared dictionary identity.
        for key, stamp in list(self._recent.items()):
            if now - stamp >= 300:
                self._recent.pop(key, None)

    def send(self, account, key, args, epoch, session, persist):
        chat_key(key)
        if set(args) - {"messages", "replyToMessageId", "atUserId"}:
            raise ValueError("发送工具不接受跨会话或未知参数")
        values = args.get("messages")
        if isinstance(values, str):
            # Some models encode the message-list parameter a second time.
            # Decode only this top-level list of strings, never each text body:
            # messages=['["literal JSON"]'] must still send its literal content.
            text = values.strip()
            if len(text) <= 80000 and text.startswith("[") and text.endswith("]"):
                try:
                    decoded = json.loads(text)
                except ValueError:
                    decoded = None
                    if re.match(r'^\[\s*"', text):
                        raise ValueError(
                            "messages 像是格式损坏的数组；请使用真正的字符串数组，不要把数组或外层括号作为正文"
                        ) from None
                if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
                    values = decoded
            if isinstance(values, str):
                if re.match(r'^\[\s*"', text) and not text.endswith("]"):
                    raise ValueError("messages 包含错误的数组包装；请使用真正的字符串数组")
                values = [values]
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    stripped = value.strip()
                    if (
                        0 < len(stripped) <= 80000
                        and stripped.startswith("[")
                        and stripped.endswith("]")
                    ):
                        try:
                            decoded = json.loads(stripped)
                        except ValueError:
                            decoded = None
                        if not isinstance(decoded, list) and re.match(r'^\[\s*"', stripped):
                            # 合法 JSON 原文是允许的正文（用户要求时）；解析失败又长
                            # 得像损坏的字符串数组，才是模型把参数误写进正文。
                            raise ValueError(
                                "messages 元素像是被再次编码的数组；请直接使用字符串数组，"
                                "每个元素写纯文本正文，不要把数组或引号塞进正文"
                            )
            values = [
                value.replace("\x00", "").strip() if isinstance(value, str) else value
                for value in values
            ]
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 4
            or any(not isinstance(v, str) or not v or len(v) > 3000 for v in values)
        ):
            raise ValueError("发送内容必须是 1 到 4 条非空文本，每条不超过 3000 字")
        for text in values:
            _validate_model_text(text)
        bodies = [face_segments(text) for text in values]
        prefix = self._prefix(account, key, args)
        sent, deduped = [], 0
        for index, segments in enumerate(bodies):
            receipt = self._deliver(
                account,
                key,
                (prefix if index == 0 else []) + segments,
                ("text", values[index]),
                values[index],
                epoch,
                session,
                persist,
            )
            if receipt is None:
                deduped += 1
            else:
                sent.append(receipt)
        return self._result(sent, deduped)

    def send_image(self, account, key, args, prepared, epoch, session, persist, permit):
        chat_key(key)
        prefix = self._prefix(account, key, args)
        # Only internal, decoded/validated preview bytes reach this method.
        encoded = prepared["part"]["image_url"]["url"].removeprefix("data:image/jpeg;base64,")
        if not encoded or len(encoded) > 700000:
            raise ValueError("待发送图片超出通信大小上限")
        note = args.get("note", "").strip().replace("\x00", "")
        _validate_model_text(note)
        note_parts = face_segments(note) if note else []
        segments = prefix + [{"type": "image", "data": {"file": "base64://" + encoded}}]
        segments.extend(note_parts)
        # Archive a placeholder, never the base64 payload or a local path.
        archive = prefix + [{"type": "image", "data": {"summary": "[图片]"}}]
        if note:
            archive.append({"type": "text", "data": {"text": note}})
        receipt = self._deliver(
            account,
            key,
            segments,
            ("image", hashlib.sha256(encoded.encode("ascii")).hexdigest()),
            "[图片]" + (" " + note if note else ""),
            epoch,
            session,
            persist,
            archive=archive,
            image_permit=permit,
        )
        return self._result([receipt] if receipt else [], int(receipt is None))

    @staticmethod
    def _result(sent, deduped):
        result = {
            "sent": len(sent),
            "messageIds": [item["messageId"] for item in sent],
            "deduped": deduped,
        }
        if deduped:
            result["message"] = (
                "本次处理已确认发送过相同内容，已跳过重复项；"
                "sent 和 messageIds 仅统计此次调用新增的 QQ 回执，请勿为跳过项补发或换路重发"
            )
        return result

    def send_segments(self, account, key, segments, archive, digest, session, *, action=None):
        """Internal debug builder only; the caller validates segments and staged files."""
        receipt = self._deliver(
            account,
            key,
            segments,
            ("debug", digest),
            segments_text(archive),
            0,
            session,
            lambda _: None,
            archive=archive,
            action=action,
        )
        return {
            "sent": int(receipt is not None),
            "messageIds": [receipt["messageId"]] if receipt else [],
            "deduped": int(receipt is None),
        }

    def _prefix(self, account, key, args):
        kind, _ = key.split(":")
        reply, mention = args.get("replyToMessageId"), args.get("atUserId")
        if reply is not None:
            reply = numeric_id(reply)
            if not reply or not self._messages.has_mid(account, key, reply):
                raise ValueError("引用的消息不属于当前可用聊天记录")
        if mention is not None:
            mention = str(mention)
            if kind != "group" or not re.fullmatch(r"[1-9]\d{0,19}", mention):
                raise ValueError("只能在群聊中 @ 有效成员号码")
            known = {item["senderId"] for item in self._messages.context(account, key, limit=200)}
            if mention not in known:
                raise ValueError("无法确认当前聊天中的被 @ 成员")
        if reply:
            return [{"type": "reply", "data": {"id": reply}}]
        if mention:
            return [
                {"type": "at", "data": {"qq": mention}},
                {"type": "text", "data": {"text": " "}},
            ]
        return []

    def poke(self, account, key, args, epoch, session, persist, permit):
        chat_key(key)
        if set(args) - {"targetUserId"}:
            raise ValueError("拍一拍不接受其他聊天或未知参数")
        kind, peer = key.split(":")
        target = str(args.get("targetUserId", peer if kind == "private" else ""))
        if not re.fullmatch(r"[1-9]\d{0,19}", target) or (kind == "private" and target != peer):
            raise ValueError("只能拍当前聊天对象或指定有效群成员 QQ 号")
        with self._dispatch_lock:
            if not self._permit(account, key, epoch) or not permit(target):
                raise DeliveryError("拍一拍已停止或目标不在当前允许范围")
            if kind == "group" and target not in {
                i["senderId"]
                for i in self._messages.context(account, key, limit=200)
                if not i["withdrawn"]
            }:
                raise ValueError("只能拍当前聊天记录中已确认的群成员")
            token = (account, key, ("poke", target))
            now = time.monotonic()
            with self._lock:
                if now - self._recent.get(token, -1000) < 300:
                    return {"poked": False, "deduped": True}
            try:
                result = self._connection.invoke(
                    "send_poke",
                    {"user_id": target, **({"group_id": peer} if kind == "group" else {})},
                    expected_account=account,
                )
            except EngineError as error:
                raise DeliveryError("拍一拍结果未确认，已停止本轮且不会自动重发") from error
            if result.get("status") != "ok":
                raise DeliveryError("QQ 未确认拍一拍成功，不会自动重发")
            receipt = {
                "text": f"[拍一拍] {target}",
                "messageId": None,
                "type": "poke",
                "ts": int(time.time() * 1000),
            }
            session["sent"].append(receipt)
            persist(session)
            with self._lock:
                self._prune_recent(now)
                if len(self._recent) >= 2048:
                    self._recent.pop(next(iter(self._recent)))
                self._recent[token] = time.monotonic()
            target_field = "group_id" if kind == "group" else "target_id"
            self._messages.ingest(
                account,
                {
                    "post_type": "message_sent",
                    "self_id": account,
                    "user_id": account,
                    "message_type": kind,
                    target_field: peer,
                    "time": receipt["ts"] / 1000,
                    "sender": {"nickname": "我"},
                    "message": [{"type": "text", "data": {"text": receipt["text"]}}],
                },
            )
            return {"poked": True, "deduped": False, "targetUserId": target}

    def recall(self, account, key, args, epoch, session, persist):
        """撤回本轮处理中自己发出的一条消息；只作纠错用，不提供翻旧账能力。"""
        chat_key(key)
        if set(args) - {"messageId"}:
            raise ValueError("撤回工具不接受其他参数")
        mid = numeric_id(args.get("messageId"))
        if not mid:
            raise ValueError("请提供要撤回的消息编号")
        receipt = next(
            (item for item in session["sent"] if item.get("messageId") == mid), None
        )
        if receipt is None:
            raise ValueError("只能撤回本次处理中自己发出的消息")
        if receipt.get("recalled"):
            return {"recalled": True, "messageId": mid, "deduped": True}
        with self._dispatch_lock:
            if not self._permit(account, key, epoch):
                raise DeliveryError("处理已停止，未执行撤回")
            try:
                result = self._connection.invoke(
                    "delete_msg", {"message_id": mid}, expected_account=account
                )
            except EngineError as error:
                raise DeliveryError("撤回结果未确认，消息可能仍在") from error
            if result.get("status") != "ok":
                raise DeliveryError("QQ 未确认撤回成功，消息可能仍在")
            receipt["recalled"] = True
            persist(session)
            self._messages.recall(account, key, mid)
        return {"recalled": True, "messageId": mid}

    def _deliver(
        self,
        account,
        key,
        segments,
        token,
        text,
        epoch,
        session,
        persist,
        *,
        archive=None,
        image_permit=None,
        action=None,
    ):
        kind, peer = key.split(":")
        # Shared queue for text, images and native reads. Recheck after waiting.
        with self._dispatch_lock:
            if not self._permit(account, key, epoch) or (
                image_permit is not None and not image_permit()
            ):
                raise DeliveryError("处理已停止，未提交排队中的消息")
            # A reference can disappear while this send waits behind a native
            # action. Validate it again at dispatch, across all sending routes.
            for segment in segments:
                if segment.get("type") == "reply":
                    self._messages.message_detail(account, key, segment["data"]["id"])
            # Agent sends dedupe only against confirmed receipts in this run.
            # A new trigger/manual rerun may intentionally repeat the same reply
            # or sticker. Never let an earlier run consume that new request.
            # The manual debug builder retains its separate rapid-submit guard.
            debug = token[0] == "debug"
            token = (account, key, token)
            delivery_key = hashlib.sha256(json.dumps(token, ensure_ascii=True).encode()).hexdigest()
            if debug:
                with self._lock:
                    now = time.monotonic()
                    self._prune_recent(now)
                    if now - self._recent.get(token, -1000) < 300:
                        return None
            elif any(item.get("deliveryKey") == delivery_key for item in session["sent"]):
                return None
            try:
                target_field = "user_id" if kind == "private" else "group_id"
                body_field = "messages" if action else "message"
                result = self._connection.invoke(
                    action or ("send_private_msg" if kind == "private" else "send_group_msg"),
                    {target_field: peer, body_field: segments},
                    expected_account=account,
                )
            except EngineError as error:
                # BUSY/NOT_CONNECTED are known pre-dispatch failures; all other
                # errors still stop the run, with no automatic resend.
                uncertain = error.code not in (
                    "BUSY",
                    "NOT_CONNECTED",
                    "IDENTITY_MISMATCH",
                    "CLOSED",
                )
                raise DeliveryError(
                    "发送结果未确认，已停止本轮且不会自动重发" if uncertain else str(error)
                ) from error
            mid = numeric_id((result.get("data") or {}).get("message_id"))
            if result.get("status") != "ok" or not mid:
                raise DeliveryError("QQ 未确认消息编号，已停止本轮且不会自动重发")
            receipt = {"text": text, "messageId": mid, "ts": int(time.time() * 1000)}
            if not debug:
                receipt["deliveryKey"] = delivery_key
            if image_permit is not None:
                receipt["type"] = "image"
            # Record the acknowledgement even if the user paused during the
            # already-dispatched action. Such a message cannot be unsent here.
            session["sent"].append(receipt)
            persist(session)
            if debug:
                with self._lock:
                    if len(self._recent) >= 2048:
                        self._recent.pop(next(iter(self._recent)))
                    self._recent[token] = time.monotonic()
            self._messages.ingest(
                account,
                {
                    "post_type": "message_sent",
                    "self_id": account,
                    "user_id": account,
                    "message_type": kind,
                    "group_id" if kind == "group" else "target_id": peer,
                    "message_id": mid,
                    "time": receipt["ts"] / 1000,
                    "sender": {"user_id": account, "nickname": "我"},
                    "message": archive if archive is not None else segments,
                },
            )
            return receipt
