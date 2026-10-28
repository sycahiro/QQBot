"""QQ Agent memberImpression 记忆：按机器人/聊天/成员隔离，不自动发起整理请求。"""

import hashlib
import json
import time

from .messages import PEER_RE, account_id, chat_key


def member_id(key, user):
    chat_key(key)
    if not isinstance(user, str) or not PEER_RE.fullmatch(user):
        raise ValueError("记忆成员号码无效")
    if key.startswith("private:") and key.split(":")[1] != user:
        raise ValueError("私聊记忆只能属于当前聊天对象")
    return user


def contents(values):
    if (
        not isinstance(values, list)
        or len(values) > 50
        or any(not isinstance(v, str) or len(v.strip()) > 120 for v in values)
    ):
        raise ValueError("每位成员最多 50 条记忆，每条不超过 120 字")
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class MemoryStore:
    def __init__(self, database):
        self._database = database

    def chats(self, account):
        account_id(account)
        with self._database.lock:
            rows = self._database.connection.execute(
                """WITH chats AS (
                SELECT chat_key FROM messages WHERE account=? UNION SELECT chat_key FROM memories WHERE account=?)
                SELECT k.chat_key,COALESCE(c.name,'') AS name,COUNT(m.id) AS count,COUNT(DISTINCT m.user_id) AS members
                FROM chats k LEFT JOIN conversations c ON c.account=? AND c.chat_key=k.chat_key
                LEFT JOIN memories m ON m.account=? AND m.chat_key=k.chat_key GROUP BY k.chat_key ORDER BY MAX(m.ts) DESC,k.chat_key LIMIT 500""",
                (account, account, account, account),
            ).fetchall()
        return [
            {
                "chatKey": r["chat_key"],
                "name": r["name"],
                "count": r["count"],
                "members": r["members"],
            }
            for r in rows
        ]

    def members(self, account, key):
        account_id(account)
        chat_key(key)
        with self._database.lock:
            rows = self._database.connection.execute(
                "SELECT * FROM memories WHERE account=? AND chat_key=? ORDER BY user_id,id LIMIT 25001",
                (account, key),
            ).fetchall()
        if len(rows) > 25000:
            raise ValueError("该聊天记忆超过当前列表上限，请先按成员整理；未截断或删除原数据")
        result = {}
        for r in rows:
            item = result.setdefault(
                r["user_id"], {"userId": r["user_id"], "target": r["target"], "entries": []}
            )
            item["entries"].append({"id": r["id"], "content": r["content"], "ts": r["ts"]})
        return list(result.values())

    def replace(self, account, key, user, target, values):
        account_id(account)
        member_id(key, user)
        values = contents(values)
        if not isinstance(target, str) or len(target) > 256:
            raise ValueError("成员名称过长或格式错误")
        with self._database.transaction() as db:
            db.execute(
                "DELETE FROM memories WHERE account=? AND chat_key=? AND user_id=?",
                (account, key, user),
            )
            db.executemany(
                "INSERT INTO memories(account,chat_key,user_id,target,content,ts) VALUES(?,?,?,?,?,?)",
                [(account, key, user, target, text, int(time.time() * 1000)) for text in values],
            )
        return len(values)

    def snapshot(self, account, key, user):
        account_id(account)
        member_id(key, user)
        with self._database.lock:
            rows = self._database.connection.execute(
                "SELECT id,target,content,ts FROM memories WHERE account=? AND chat_key=? AND user_id=? ORDER BY id",
                (account, key, user),
            ).fetchall()
        entries = [dict(row) for row in rows]
        revision = hashlib.sha256(
            json.dumps(entries, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return {
            "revision": revision,
            "target": entries[0]["target"] if entries else "",
            "values": [r["content"] for r in entries],
        }

    def apply_review(self, account, key, user, revision, values, permit):
        values = contents(values)
        with self._database.transaction():
            if not permit():
                raise ValueError("账号或整理来源已变化，请重新生成预览")
            current = self.snapshot(account, key, user)
            if current["revision"] != revision:
                raise ValueError("记忆已被修改或删除，请重新生成预览")
            return self.replace(account, key, user, current["target"], values)

    def append(self, account, key, user, target, content):
        account_id(account)
        member_id(key, user)
        if not isinstance(content, str) or not contents([content]):
            raise ValueError("记忆内容不能为空")
        if not isinstance(target, str) or len(target) > 256:
            raise ValueError("成员名称格式错误")
        with self._database.transaction() as db:
            existing = db.execute(
                "SELECT content FROM memories WHERE account=? AND chat_key=? AND user_id=?",
                (account, key, user),
            ).fetchall()
            if content.strip() in {r["content"] for r in existing}:
                return {"saved": False, "duplicate": True}
            if len(existing) >= 50:
                raise ValueError("该成员已有 50 条记忆，请先删除过时的内容")
            db.execute(
                "INSERT INTO memories(account,chat_key,user_id,target,content,ts) VALUES(?,?,?,?,?,?)",
                (account, key, user, target, content.strip(), int(time.time() * 1000)),
            )
        return {"saved": True}

    def delete(self, account, key=None, user=None, content=None):
        account_id(account)
        if key is not None:
            chat_key(key)
        if user is not None:
            if key is None:
                raise ValueError("删除成员记忆时必须指定聊天")
            member_id(key, user)
        if content is not None and not isinstance(content, str):
            raise ValueError("记忆内容格式无效")
        with self._database.transaction() as db:
            return db.execute(
                """DELETE FROM memories WHERE account=? AND (? IS NULL OR chat_key=?)
                AND (? IS NULL OR user_id=?) AND (? IS NULL OR content=?)""",
                (account, key, key, user, user, content, content),
            ).rowcount

    def format(self, account, key, user_ids):
        lines = []
        account_id(account)
        chat_key(key)
        if not user_ids:
            return ""
        users = sorted(set(user_ids))
        if key.startswith("private:"):
            users = [user for user in users if user == key.split(":")[1]]
        if not users:
            return ""
        if len(users) > 200:
            raise ValueError("记忆引用成员数量超过上限")
        for user in users:
            member_id(key, user)
        placeholders = ",".join("?" for _ in users)
        with self._database.lock:
            rows = self._database.connection.execute(
                f"SELECT user_id,target,content FROM memories WHERE account=? AND chat_key=? AND user_id IN ({placeholders}) ORDER BY user_id,id LIMIT 81",
                (account, key, *users),
            ).fetchall()
        for row in rows[:80]:
            lines.append(f"{row['target'] or '成员'}({row['user_id']}): {row['content']}")
        if len(rows) > 80:
            lines.append("（记忆较多，仅展示前 80 条）")
        return "\n".join(lines)
