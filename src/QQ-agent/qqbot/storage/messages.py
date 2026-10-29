"""沿用 QQ Agent 的 chatKey、发送者/消息 ID/媒体片段语义，使用账号隔离的 SQLite 存档。"""

import json
import math
import re
import time

ACCOUNT_RE = re.compile(r"[1-9][0-9]{4,11}\Z")
PEER_RE = re.compile(r"[1-9][0-9]{0,19}\Z")
NUMERIC_RE = re.compile(r"-?[0-9]{1,24}\Z")


def stored_segments(raw):
    """Damaged attachment metadata must not hide an otherwise readable archive."""
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, (list, str)) else []


def account_id(value):
    if not isinstance(value, str) or not ACCOUNT_RE.fullmatch(value):
        raise ValueError("无效的机器人账号")
    return value


def chat_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"(group|private):[1-9][0-9]{0,19}", value):
        raise ValueError("无效的会话")
    return value


def numeric_id(value):
    text = str(value) if value is not None and not isinstance(value, bool) else ""
    return text if NUMERIC_RE.fullmatch(text) and text != "0" else None


def segments_text(segments):
    if isinstance(segments, str):
        return segments.replace("\x00", "")
    parts = []
    for item in segments if isinstance(segments, list) else []:
        if not isinstance(item, dict):
            continue
        kind, data = item.get("type"), item.get("data") or {}
        if not isinstance(data, dict):
            continue
        if kind == "text":
            parts.append(str(data.get("text", "")))
        elif kind == "at":
            parts.append(
                "@全体成员" if str(data.get("qq")) == "all" else "@" + str(data.get("qq", ""))
            )
        elif kind == "reply":
            parts.append("[引用 " + str(data.get("id", "")) + "] ")
        else:
            parts.append(
                {
                    "image": "[图片]",
                    "record": "[语音]",
                    "video": "[视频]",
                    "face": "[表情]",
                    "forward": "[合并转发聊天记录]",
                    "file": "[文件]",
                    "json": "[卡片消息]",
                }.get(kind, "[消息片段]")
            )
    return "".join(parts).replace("\x00", "")


def normalize_message(account, event):
    account_id(account)
    if str(event.get("self_id")) != account:
        raise ValueError("事件账号与存档账号不一致")
    if event.get("post_type") == "notice":
        return normalize_poke(account, event)
    if event.get("post_type") not in ("message", "message_sent"):
        return None
    kind = event.get("message_type")
    if kind not in ("group", "private"):
        return None
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = numeric_id(event.get("user_id") or sender.get("user_id"))
    if not sender_id or not PEER_RE.fullmatch(sender_id):
        return None
    is_self = event.get("post_type") == "message_sent" or sender_id == account
    peer = (
        event.get("group_id")
        if kind == "group"
        else event.get("target_id")
        if is_self
        else event.get("user_id")
    )
    peer = numeric_id(peer)
    if not peer or not PEER_RE.fullmatch(peer):
        return None
    key = chat_key(f"{kind}:{peer}")
    timestamp = event.get("time")
    if (
        type(timestamp) not in (int, float)
        or not math.isfinite(timestamp)
        or not 0 < timestamp < 32503680000
    ):
        timestamp = time.time()
    segments = event.get("message")
    if not isinstance(segments, (list, str)):
        segments = str(event.get("raw_message") or "")
    serialized = json.dumps(segments, ensure_ascii=False, allow_nan=False)
    if len(serialized.encode()) > 1024 * 1024:
        raise ValueError("单条消息超出存档大小上限")
    display_name = str(sender.get("card") or sender.get("nickname") or "")[:256]
    name = display_name or sender_id
    chat_name = (
        str(event.get("group_name") or "")[:256]
        if kind == "group"
        else (display_name if not is_self else "")
    )
    return {
        "chatKey": key,
        "name": chat_name,
        "mid": numeric_id(event.get("message_id")),
        "sequence": numeric_id(event.get("message_seq")) or "",
        "ts": int(timestamp * 1000),
        "senderId": account if is_self else sender_id,
        "senderName": name,
        "text": segments_text(segments),
        "segments": serialized,
        "self": is_self,
    }


def normalize_poke(account, event):
    if event.get("notice_type") != "notify" or event.get("sub_type") != "poke":
        return None
    operator = numeric_id(event.get("user_id"))
    target = numeric_id(event.get("target_id"))
    if not operator or not target or operator == account:
        return None
    if not all(re.fullmatch(r"[1-9]\d{0,19}", value) for value in (operator, target)):
        return None
    group = event.get("group_id")
    if group is None and target != account:
        return None
    item = normalize_message(
        account,
        {
            "post_type": "message",
            "self_id": account,
            "message_type": "group" if group is not None else "private",
            "user_id": operator,
            "group_id": group,
            "time": event.get("time"),
            "sender": event.get("sender"),
            "message": [
                {
                    "type": "text",
                    "data": {
                        "text": "[拍一拍] 拍了拍" + ("我" if target == account else f" QQ {target}")
                    },
                },
                {"type": "poke", "data": {"target_id": target}},
            ],
        },
    )
    if item:
        item["isPoke"] = True
        # The internal marker is not a visible message fragment.
        item["text"] = "[拍一拍] 拍了拍" + ("我" if target == account else f" QQ {target}")
    return item


class MessageStore:
    def __init__(self, database):
        self._database = database

    def ingest(self, account, event):
        account_id(account)
        if str(event.get("self_id")) != account:
            raise ValueError("事件账号不一致")
        if event.get("post_type") == "notice" and event.get("notice_type") in (
            "group_recall",
            "friend_recall",
        ):
            kind = "group" if event["notice_type"] == "group_recall" else "private"
            peer = numeric_id(event.get("group_id") if kind == "group" else event.get("user_id"))
            mid = numeric_id(event.get("message_id"))
            if peer and mid:
                self.recall(account, chat_key(f"{kind}:{peer}"), mid)
            return None
        item = normalize_message(account, event)
        if item is None:
            return None
        with self._database.transaction() as db:
            if item.get("isPoke") and item["senderName"] == item["senderId"]:
                prior = db.execute(
                    "SELECT sender_name FROM messages WHERE account=? AND chat_key=? AND sender_id=? AND sender_name<>sender_id ORDER BY id DESC LIMIT 1",
                    (account, item["chatKey"], item["senderId"]),
                ).fetchone()
                if prior:
                    item["senderName"] = prior[0]
            db.execute(
                "INSERT INTO conversations(account,chat_key,name) VALUES(?,?,?) ON CONFLICT(account,chat_key) DO UPDATE SET name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE name END",
                (account, item["chatKey"], item["name"]),
            )
            recalled = (
                item["mid"]
                and db.execute(
                    "SELECT 1 FROM recalls WHERE account=? AND chat_key=? AND mid=?",
                    (account, item["chatKey"], item["mid"]),
                ).fetchone()
            )
            # Sending acknowledgements may reach us before the native self echo;
            # replace the unknown sequence instead of making two archive entries.
            if item["self"] and item["mid"]:
                previous = db.execute(
                    "SELECT id,sequence FROM messages WHERE account=? AND chat_key=? AND mid=? AND is_self=1",
                    (account, item["chatKey"], item["mid"]),
                ).fetchall()
                if previous and (
                    not item["sequence"] or any(not row["sequence"] for row in previous)
                ):
                    if item["sequence"]:
                        # A colliding known sequence may precede the receipt row.
                        # Fill the unknown receipt, not an arbitrary first row;
                        # an already-retained echo must not create a UNIQUE clash.
                        if not any(row["sequence"] == item["sequence"] for row in previous):
                            db.execute(
                                "UPDATE messages SET sequence=? WHERE account=? AND chat_key=? AND mid=? AND is_self=1 AND sequence=''",
                                (item["sequence"], account, item["chatKey"], item["mid"]),
                            )
                    return None
            cursor = db.execute(
                """INSERT OR IGNORE INTO messages(account,chat_key,mid,sequence,ts,sender_id,sender_name,body,segments,is_self,withdrawn,is_read)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    account,
                    item["chatKey"],
                    item["mid"],
                    item["sequence"],
                    item["ts"],
                    item["senderId"],
                    item["senderName"],
                    item["text"],
                    item["segments"],
                    int(item["self"]),
                    int(bool(recalled)),
                    int(item["self"] or bool(recalled)),
                ),
            )
            if cursor.rowcount != 1:
                return None
            item["id"] = cursor.lastrowid
            if recalled:
                item["withdrawn"] = True
            return item

    def set_names(self, account, names):
        account_id(account)
        with self._database.transaction() as db:
            for key, name in names.items():
                chat_key(key)
                if name:
                    db.execute(
                        "INSERT INTO conversations(account,chat_key,name) VALUES(?,?,?) ON CONFLICT(account,chat_key) DO UPDATE SET name=excluded.name",
                        (account, key, str(name)[:256]),
                    )

    def recall(self, account, key, mid):
        account_id(account)
        chat_key(key)
        with self._database.transaction() as db:
            db.execute("INSERT OR IGNORE INTO recalls VALUES(?,?,?)", (account, key, str(mid)))
            db.execute(
                "UPDATE messages SET withdrawn=1,is_read=1 WHERE account=? AND chat_key=? AND mid=?",
                (account, key, str(mid)),
            )

    def list_chats(self, account, limit=200, *, unread_only=False):
        account_id(account)
        if type(unread_only) is not bool:
            raise ValueError("未读筛选必须为布尔值")
        with self._database.lock:
            rows = self._database.connection.execute(
                """WITH latest AS (
                SELECT chat_key,MAX(id) AS last_id,COUNT(*) AS count,
                SUM(CASE WHEN is_read=0 AND is_self=0 AND withdrawn=0 THEN 1 ELSE 0 END) AS unread
                FROM messages WHERE account=? GROUP BY chat_key)
                SELECT c.chat_key,c.name,l.count,l.unread,l.last_id,m.body,m.ts,m.withdrawn,m.sender_name,m.sender_id,m.is_self FROM latest l JOIN messages m ON m.id=l.last_id
                JOIN conversations c ON c.account=m.account AND c.chat_key=m.chat_key WHERE (?=0 OR l.unread>0)
                ORDER BY m.id DESC LIMIT ?""",
                (account, int(unread_only), min(500, max(1, int(limit)))),
            ).fetchall()
        return [
            {
                "chatKey": row["chat_key"],
                "name": row["name"],
                "count": row["count"],
                "unread": row["unread"],
                "lastId": row["last_id"],
                "lastText": ("[已撤回] " if row["withdrawn"] else "") + row["body"],
                "lastSenderName": "我"
                if row["is_self"]
                else row["sender_name"] or row["sender_id"],
                "lastTs": row["ts"],
            }
            for row in rows
        ]

    def archive_state(self, account, *, unread_only=False):
        account_id(account)
        with self._database.lock:
            items = self.list_chats(account, limit=500, unread_only=unread_only)
            row = self._database.connection.execute(
                """SELECT COUNT(*) AS unread,COUNT(DISTINCT chat_key) AS chats
                FROM messages WHERE account=? AND is_read=0 AND is_self=0 AND withdrawn=0""",
                (account,),
            ).fetchone()
            through = self._database.connection.execute(
                "SELECT COALESCE(MAX(id),0) FROM messages WHERE account=?", (account,)
            ).fetchone()[0]
            return {
                "items": items,
                "unread": row["unread"],
                "unreadChats": row["chats"],
                "readThrough": through,
            }

    def mark_read(self, account, key, through):
        account_id(account)
        if key is not None:
            chat_key(key)
        if type(through) is not int or not 0 <= through <= 9223372036854775807:
            raise ValueError("请刷新存档后确认已读位置")
        with self._database.transaction() as db:
            return db.execute(
                """UPDATE messages SET is_read=1 WHERE account=? AND (? IS NULL OR chat_key=?)
                AND id<=? AND is_read=0 AND is_self=0 AND withdrawn=0""",
                (account, key, key, through),
            ).rowcount

    def claim(self, account, key, identities, *, only_unread=True):
        """Snapshot and mark exactly this admitted batch; new arrivals stay unread.

        Automatic batches skip rows manually marked before this point. Explicit
        manual runs may deliberately reprocess a read row without unread replay.
        """
        account_id(account)
        chat_key(key)
        if (
            not isinstance(identities, (list, set))
            or not 1 <= len(identities) <= 512
            or any(type(i) is not int or not 0 < i <= 9223372036854775807 for i in identities)
        ):
            raise ValueError("处理批消息位置无效")
        placeholders = ",".join("?" for _ in identities)
        with self._database.transaction() as db:
            rows = db.execute(
                f"""SELECT id FROM messages WHERE account=? AND chat_key=? AND is_self=0 AND withdrawn=0
                AND (?=0 OR is_read=0) AND id IN ({placeholders})""",
                (account, key, int(only_unread), *identities),
            ).fetchall()
            result = {row["id"] for row in rows}
            db.executemany("UPDATE messages SET is_read=1 WHERE id=?", [(i,) for i in result])
            return result

    def messages(self, account, key, before=None, limit=100, *, query=""):
        account_id(account)
        chat_key(key)
        limit = min(200, max(1, int(limit)))
        if before is not None and (type(before) is not int or before <= 0):
            raise ValueError("无效的分页位置")
        if not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query):
            raise ValueError("搜索内容应为不超过 200 字的单行文本")
        query = query.strip()
        # Literal substring search, not SQL wildcard syntax. Only the current
        # chat's visible body/sender fields participate; never media metadata.
        condition = """account=? AND chat_key=? AND (?='' OR instr(lower(body),lower(?))>0
            OR instr(lower(sender_name),lower(?))>0 OR instr(sender_id,?)>0)"""
        arguments = (account, key, query, query, query, query)
        with self._database.lock:
            total = self._database.connection.execute(
                "SELECT COUNT(*) FROM messages WHERE " + condition, arguments
            ).fetchone()[0]
            rows = self._database.connection.execute(
                "SELECT * FROM messages WHERE "
                + condition
                + " AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?",
                (*arguments, before, before, limit + 1),
            ).fetchall()
        items = [
            {
                "id": row["id"],
                "mid": row["mid"],
                "ts": row["ts"],
                "senderId": row["sender_id"],
                "senderName": row["sender_name"],
                "text": row["body"],
                "self": bool(row["is_self"]),
                "withdrawn": bool(row["withdrawn"]),
                "read": bool(row["is_read"]),
                "hasForward": not row["withdrawn"]
                and any(
                    isinstance(s, dict) and s.get("type") == "forward"
                    for s in stored_segments(row["segments"])
                )
                if isinstance(row["segments"], str) and row["segments"].startswith("[")
                else False,
                "hasImage": not row["withdrawn"]
                and any(
                    isinstance(s, dict) and s.get("type") == "image"
                    for s in stored_segments(row["segments"])
                    if isinstance(s, dict)
                )
                if isinstance(row["segments"], str) and row["segments"].startswith("[")
                else False,
            }
            for row in reversed(rows[:limit])
        ]
        return {
            "items": items,
            "hasMore": len(rows) > limit,
            "nextBefore": items[0]["id"] if len(rows) > limit else None,
            "query": query,
            "totalMatches": total,
        }

    def delete(self, account, key=None):
        account_id(account)
        if key is not None:
            chat_key(key)
        with self._database.transaction() as db:
            condition, args = (
                ("account=?", (account,))
                if key is None
                else ("account=? AND chat_key=?", (account, key))
            )
            count = db.execute("SELECT COUNT(*) FROM messages WHERE " + condition, args).fetchone()[
                0
            ]
            # Contact names also label memory and session pages. Clearing an
            # archive removes messages, not the shared contact metadata.
            db.execute("DELETE FROM messages WHERE " + condition, args)
            db.execute("DELETE FROM recalls WHERE " + condition, args)
            return count

    def context(self, account, key, through=None, limit=40, *, include=None):
        """Recent context plus explicitly identified trigger rows, in chronological order."""
        account_id(account)
        chat_key(key)
        identities = list(include or [])
        if len(identities) > 512 or any(type(i) is not int or i <= 0 for i in identities):
            raise ValueError("处理批消息位置无效")
        with self._database.lock:
            rows = self._database.connection.execute(
                """SELECT * FROM messages WHERE account=? AND chat_key=?
                AND (? IS NULL OR id<=?) ORDER BY id DESC LIMIT ?""",
                (account, key, through, through, min(200, max(1, int(limit)))),
            ).fetchall()
            by_id = {row["id"]: row for row in rows}
            if identities:
                placeholders = ",".join("?" for _ in identities)
                included = self._database.connection.execute(
                    f"""SELECT * FROM messages WHERE account=? AND chat_key=?
                    AND (? IS NULL OR id<=?) AND id IN ({placeholders})""",
                    (account, key, through, through, *identities),
                ).fetchall()
                by_id.update((row["id"], row) for row in included)
        return [
            {
                "id": r["id"],
                "mid": r["mid"],
                "ts": r["ts"],
                "senderId": r["sender_id"],
                "senderName": r["sender_name"],
                "text": "[消息已撤回]" if r["withdrawn"] else r["body"],
                "self": bool(r["is_self"]),
                "withdrawn": bool(r["withdrawn"]),
                "segments": [] if r["withdrawn"] else stored_segments(r["segments"]),
            }
            for r in sorted(by_id.values(), key=lambda row: row["id"])
        ]

    def source_rows(self, account, key, identifiers):
        """Fresh model-facing identities; no segments or withdrawn original text."""
        account_id(account)
        chat_key(key)
        if not isinstance(identifiers, (list, tuple, set, frozenset)) or len(identifiers) > 4096:
            raise ValueError("来源消息位置无效")
        if any(
            type(identity) is not int or not 0 < identity <= 9223372036854775807
            for identity in identifiers
        ):
            raise ValueError("来源消息位置无效")
        if not identifiers:
            return []
        identities = list(set(identifiers))
        rows = []
        with self._database.lock:
            for start in range(0, len(identities), 512):
                chunk = identities[start : start + 512]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    self._database.connection.execute(
                        f"SELECT id,sender_id,withdrawn,is_self,body FROM messages WHERE account=? AND chat_key=? AND id IN ({placeholders}) ORDER BY id",
                        (account, key, *chunk),
                    ).fetchall()
                )
        return [
            {
                "id": row["id"],
                "senderId": row["sender_id"],
                "withdrawn": bool(row["withdrawn"]),
                "self": bool(row["is_self"]),
                "text": "[消息已撤回]" if row["withdrawn"] else row["body"],
            }
            for row in sorted(rows, key=lambda row: row["id"])
        ]

    def name(self, account, key):
        account_id(account)
        chat_key(key)
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT name FROM conversations WHERE account=? AND chat_key=?", (account, key)
            ).fetchone()
        return row["name"] if row else ""

    def has_mid(self, account, key, mid, *, self_only=False):
        account_id(account)
        chat_key(key)
        with self._database.lock:
            return (
                self._database.connection.execute(
                    """SELECT 1 FROM messages WHERE account=? AND chat_key=? AND mid=?
                AND withdrawn=0 AND (?=0 OR is_self=1) LIMIT 1""",
                    (account, key, str(mid), int(self_only)),
                ).fetchone()
                is not None
            )

    def image_message(self, account, key, mid):
        """Resolve an unambiguous message only inside this account and chat."""
        account_id(account)
        chat_key(key)
        mid = numeric_id(mid)
        if mid is None:
            raise ValueError("请提供当前聊天中的有效消息编号")
        with self._database.lock:
            rows = self._database.connection.execute(
                """SELECT id,mid,sender_id,is_self,segments,sequence FROM messages
                WHERE account=? AND chat_key=? AND mid=? AND withdrawn=0 LIMIT 2""",
                (account, key, mid),
            ).fetchall()
        if len(rows) != 1:
            raise ValueError("图片消息不存在、已撤回，或消息编号有歧义")
        row = rows[0]
        return {
            "id": row["id"],
            "mid": row["mid"],
            "senderId": row["sender_id"],
            "self": bool(row["is_self"]),
            "sequence": row["sequence"],
            "segments": stored_segments(row["segments"]),
        }

    def message_detail(self, account, key, mid):
        account_id(account)
        chat_key(key)
        mid = numeric_id(mid)
        if mid is None:
            raise ValueError("请提供当前聊天中的有效消息编号")
        with self._database.lock:
            rows = self._database.connection.execute(
                """SELECT * FROM messages
                WHERE account=? AND chat_key=? AND mid=? AND withdrawn=0 LIMIT 2""",
                (account, key, mid),
            ).fetchall()
        if len(rows) != 1:
            raise ValueError("消息不存在、已撤回，或消息编号有歧义")
        row = rows[0]
        return {
            "id": row["id"],
            "mid": row["mid"],
            "sequence": row["sequence"],
            "ts": row["ts"],
            "senderId": row["sender_id"],
            "senderName": row["sender_name"],
            "self": bool(row["is_self"]),
            "text": row["body"],
            "segments": stored_segments(row["segments"]),
        }

    def expand_forward(self, account, key, original, text):
        """Update the retained source only; recall/deletion must never resurrect it."""
        account_id(account)
        chat_key(key)
        with self._database.transaction() as db:
            cursor = db.execute(
                """UPDATE messages SET body=? WHERE account=? AND chat_key=?
                AND id=? AND mid=? AND body=? AND withdrawn=0""",
                (text, account, key, original["id"], original["mid"], original["text"]),
            )
            if cursor.rowcount != 1:
                current = self.message_detail(account, key, original["mid"])
                if current["id"] != original["id"] or current["text"] != text:
                    raise ValueError("原消息已变化，未保存转发内容")

    def active_senders(self, account, key, identities):
        account_id(account)
        chat_key(key)
        if not identities:
            return set()
        placeholders = ",".join("?" for _ in identities)
        with self._database.lock:
            rows = self._database.connection.execute(
                f"""SELECT DISTINCT sender_id FROM messages
                WHERE account=? AND chat_key=? AND withdrawn=0 AND id IN ({placeholders})""",
                (account, key, *identities),
            ).fetchall()
        return {row["sender_id"] for row in rows}
