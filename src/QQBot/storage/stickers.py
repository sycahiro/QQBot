"""账号本地表情库：沿用原 stickers 的 id、备注、标签和使用次数语义。

保存的是经图片模块清洗的 JPEG 字节，拒绝模型路径/任意文件和远程 URL。
图库与聊天存档独立；只读列表不返回图片，选择单项才返回预览。
"""

import base64
import hashlib
import json
import re
import time
import uuid

from .messages import account_id

MAX_STICKERS = 200


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("无效的表情编号，请从表情库选择")
    return value


def annotation(note, tags=None, usage=""):
    if (
        not isinstance(note, str)
        or len(note) > 120
        or not isinstance(usage, str)
        or len(usage) > 120
    ):
        raise ValueError("表情备注和使用场景分别最多 120 字")
    tags = [] if tags is None else tags
    if (
        not isinstance(tags, list)
        or len(tags) > 8
        or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 20 for t in tags)
    ):
        raise ValueError("最多 8 个标签，每个 1 到 20 字")
    if any(ord(c) < 32 for c in note + usage + "".join(tags)):
        raise ValueError("表情备注不能包含控制字符或换行")
    return note.strip(), list(dict.fromkeys(t.strip() for t in tags)), usage.strip()


class StickerStore:
    def __init__(self, database):
        self._database = database

    def _meta(self, row):
        # sqlite3.Row 的成员判断要显式走 keys()（`in row` 会按值匹配）。
        columns = tuple(row.keys())
        return {
            "id": row["id"],
            "note": row["note"],
            "tags": json.loads(row["tags"]),
            "usage": row["usage"],
            "width": row["width"],
            "height": row["height"],
            "bytes": len(row["image"]) if "image" in columns else row["bytes"],
            "firstFrame": bool(row["first_frame"]),
            "created": row["created"],
            "uses": row["uses"],
        }

    def list(self, account, query="", limit=200):
        account_id(account)
        if (
            not isinstance(query, str)
            or len(query) > 120
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValueError("表情搜索词或条数无效")
        with self._database.lock:
            rows = self._database.connection.execute(
                """SELECT id,note,tags,usage,width,height,length(image) AS bytes,first_frame,created,uses
                FROM stickers WHERE account=? AND (?='' OR instr(lower(note),lower(?))>0 OR instr(lower(tags),lower(?))>0
                OR instr(lower(usage),lower(?))>0) ORDER BY created DESC,id LIMIT ?""",
                (account, query, query, query, query, limit),
            ).fetchall()
        return [self._meta(row) for row in rows]

    def add(self, account, prepared, note="", tags=None, usage="", source=None):
        account_id(account)
        note, tags, usage = annotation(note, tags, usage)
        try:
            url = prepared["part"]["image_url"]["url"]
            prefix = "data:image/jpeg;base64,"
            if not isinstance(url, str) or not url.startswith(prefix):
                raise ValueError()
            data = base64.b64decode(url[len(prefix) :], validate=True)
            info = prepared["info"]
            if (
                not 1 <= len(data) <= 524288
                or not data.startswith(b"\xff\xd8")
                or not 1 <= info["width"] <= 1568
                or not 1 <= info["height"] <= 1568
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("表情必须来自已清洗的聊天图片") from error
        digest = hashlib.sha256(data).hexdigest()
        with self._database.transaction() as db:
            if source is not None:
                row = db.execute(
                    "SELECT 1 FROM messages WHERE account=? AND chat_key=? AND id=? AND mid=? AND withdrawn=0",
                    (account, source["chatKey"], source["id"], source["mid"]),
                ).fetchone()
                if row is None:
                    raise ValueError("原图片消息已删除或撤回，未收藏")
            existing = db.execute(
                "SELECT * FROM stickers WHERE account=? AND digest=?", (account, digest)
            ).fetchone()
            if existing:
                return {"collected": False, "duplicate": True, **self._meta(existing)}
            if (
                db.execute("SELECT count(*) FROM stickers WHERE account=?", (account,)).fetchone()[
                    0
                ]
                >= MAX_STICKERS
            ):
                raise ValueError("表情库已达到 200 张上限，请先删除不需要的表情")
            item = uuid.uuid4().hex
            db.execute(
                "INSERT INTO stickers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item,
                    account,
                    digest,
                    data,
                    note,
                    json.dumps(tags, ensure_ascii=False),
                    usage,
                    info["width"],
                    info["height"],
                    int(info["firstFrame"]),
                    int(time.time() * 1000),
                    0,
                ),
            )
            row = db.execute(
                "SELECT * FROM stickers WHERE account=? AND id=?", (account, item)
            ).fetchone()
            return {"collected": True, "duplicate": False, **self._meta(row)}

    def get(self, account, item):
        account_id(account)
        identifier(item)
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT * FROM stickers WHERE account=? AND id=?", (account, item)
            ).fetchone()
        if row is None:
            raise ValueError("表情不存在或已删除，请刷新表情库")
        data = row["image"]
        if len(data) > 524288 or hashlib.sha256(data).hexdigest() != row["digest"]:
            raise ValueError("表情内容校验失败，请删除后重新收藏")
        return {
            "meta": self._meta(row),
            "digest": row["digest"],
            "part": {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
                },
            },
            "info": {
                "width": row["width"],
                "height": row["height"],
                "bytes": len(data),
                "firstFrame": bool(row["first_frame"]),
            },
        }

    def note(self, account, item, note, tags=None, usage=""):
        account_id(account)
        identifier(item)
        note, tags, usage = annotation(note, tags, usage)
        with self._database.transaction() as db:
            changed = db.execute(
                "UPDATE stickers SET note=?,tags=?,usage=? WHERE account=? AND id=?",
                (note, json.dumps(tags, ensure_ascii=False), usage, account, item),
            ).rowcount
            if not changed:
                raise ValueError("表情不存在或已删除")
        return self.get(account, item)["meta"]

    def delete(self, account, item=None):
        account_id(account)
        if item is not None:
            identifier(item)
        with self._database.transaction() as db:
            return db.execute(
                "DELETE FROM stickers WHERE account=? AND (? IS NULL OR id=?)",
                (account, item, item),
            ).rowcount

    def mark_used(self, account, item):
        account_id(account)
        identifier(item)
        with self._database.transaction() as db:
            db.execute("UPDATE stickers SET uses=uses+1 WHERE account=? AND id=?", (account, item))

    def matches(self, account, item, digest):
        account_id(account)
        identifier(item)
        with self._database.lock:
            return (
                self._database.connection.execute(
                    "SELECT 1 FROM stickers WHERE account=? AND id=? AND digest=?",
                    (account, item, digest),
                ).fetchone()
                is not None
            )
