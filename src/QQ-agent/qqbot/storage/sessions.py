"""一次触发对应一次独立运行，沿用 QQ Agent 的会话、工具记录和 usage 口径。"""

import json
import time
import uuid
from datetime import datetime, timedelta

from .messages import account_id


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


USAGE_FIELDS = ("promptTokens", "completionTokens", "totalTokens", "calls")


def stored_json(raw, expected):
    try:
        value = json.loads(raw)
    except ValueError, TypeError:
        return expected()
    return value if isinstance(value, expected) else expected()


def stored_usage(raw):
    value = stored_json(raw, dict)
    return {
        field: value.get(field, 0)
        if type(value.get(field)) is int and 0 <= value[field] <= 10**12
        else 0
        for field in USAGE_FIELDS
    }


class SessionStore:
    def __init__(self, database):
        self._database = database
        with database.transaction() as db:
            ended = int(time.time() * 1000)
            for row in db.execute(
                "SELECT id,records FROM sessions WHERE status='running'"
            ).fetchall():
                encoded = row["records"]
                try:
                    records = json.loads(encoded)
                except ValueError:
                    records = None  # Preserve a damaged record; do not break application startup.
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict) and record.get("status") == "running":
                            record.update(status="aborted", ended=ended)
                            if record.get("kind") == "tool":
                                record["result"] = {"error": "应用退出时处理尚未结束"}
                    encoded = encode(records)
                db.execute(
                    "UPDATE sessions SET status='aborted',ended=?,records=?,reason='应用上次退出时处理尚未结束，未自动重试' WHERE id=?",
                    (ended, encoded, row["id"]),
                )

    def start(self, account, key, name, model, trigger):
        item = {
            "id": uuid.uuid4().hex,
            "account": account,
            "chatKey": key,
            "name": name,
            "started": int(time.time() * 1000),
            "ended": None,
            "status": "running",
            "model": model,
            "triggerText": trigger[:2000],
            "usage": {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "calls": 0},
            "records": [],
            "sent": [],
            "reason": "",
        }
        account_id(account)
        with self._database.transaction() as db:
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"],
                    account,
                    key,
                    name,
                    item["started"],
                    None,
                    "running",
                    model,
                    item["triggerText"],
                    encode(item["usage"]),
                    "[]",
                    "[]",
                    "",
                ),
            )
        return item

    def save(self, item):
        with self._database.transaction() as db:
            db.execute(
                """UPDATE sessions SET ended=?,status=?,model=?,usage=?,records=?,sent=?,reason=? WHERE id=? AND account=?""",
                (
                    item["ended"],
                    item["status"],
                    item["model"],
                    encode(item["usage"]),
                    encode(item["records"]),
                    encode(item["sent"]),
                    item["reason"][:1000],
                    item["id"],
                    item["account"],
                ),
            )

    def _item(self, row, *, detail=False):
        item = {
            "id": row["id"],
            "account": row["account"],
            "chatKey": row["chat_key"],
            "name": row["name"],
            "started": row["started"],
            "ended": row["ended"],
            "status": row["status"],
            "model": row["model"],
            "triggerText": row["trigger_text"],
            "usage": stored_usage(row["usage"]),
            "sent": [item for item in stored_json(row["sent"], list) if isinstance(item, dict)],
            "reason": row["reason"],
        }
        if detail:
            item["records"] = [
                item for item in stored_json(row["records"], list) if isinstance(item, dict)
            ]
        return item

    def list(self, account, limit=200):
        account_id(account)
        if type(limit) is not int or not 1 <= limit <= 2000:
            raise ValueError("会话列表条数无效")
        with self._database.lock:
            # Summary polling must not fetch all prompt/tool blobs every 2s.
            rows = self._database.connection.execute(
                """SELECT id,account,chat_key,name,started,ended,status,model,trigger_text,usage,sent,reason
                FROM sessions WHERE account=? ORDER BY started DESC,rowid DESC LIMIT ?""",
                (account, limit),
            ).fetchall()
        return [self._item(r) for r in rows]

    def get(self, account, identifier):
        account_id(account)
        if not isinstance(identifier, str) or len(identifier) > 64:
            raise ValueError("无效的会话日志编号")
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT * FROM sessions WHERE account=? AND id=?", (account, identifier)
            ).fetchone()
        return self._item(row, detail=True) if row else None

    def delete(self, account, identifier=None):
        account_id(account)
        with self._database.transaction() as db:
            if identifier is not None:
                row = db.execute(
                    "SELECT status FROM sessions WHERE account=? AND id=?", (account, identifier)
                ).fetchone()
                if row and row["status"] == "running":
                    raise ValueError("当前会话正在处理，请先关闭自动回复再删除")
            return db.execute(
                "DELETE FROM sessions WHERE account=? AND (? IS NULL OR id=?) AND status<>'running'",
                (account, identifier, identifier),
            ).rowcount

    def usage(self, account):
        account_id(account)
        today = datetime.now().astimezone().date()
        start = int(datetime.combine(today, datetime.min.time()).timestamp() * 1000)
        end = int(
            datetime.combine(today + timedelta(days=1), datetime.min.time()).timestamp() * 1000
        )
        # Guard invalid JSON before extraction; count only sane integer counters.
        expressions = []
        for field in USAGE_FIELDS:
            path = "$." + field
            expressions.append(
                f"CASE WHEN json_valid(usage) THEN CASE WHEN json_type(usage,'{path}')='integer' AND json_extract(usage,'{path}') BETWEEN 0 AND 1000000000000 THEN json_extract(usage,'{path}') ELSE 0 END ELSE 0 END AS {field}"
            )
        with self._database.lock:
            row = self._database.connection.execute(
                "WITH values_checked AS (SELECT started,"
                + ",".join(expressions)
                + " FROM sessions WHERE account=?) SELECT "
                + ",".join(f"COALESCE(SUM({field}),0) AS {field}" for field in USAGE_FIELDS)
                + ",COALESCE(SUM(CASE WHEN started>=? AND started<? THEN totalTokens ELSE 0 END),0) AS todayTokens,COUNT(*) AS sessions FROM values_checked",
                (account, start, end),
            ).fetchone()
        return dict(row)
