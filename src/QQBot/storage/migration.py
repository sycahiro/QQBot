"""只读 QQ Agent JSON 复制件，导入隔离数据库；保留导入凭据，清理后的记录不被重复导入复活。"""

import copy
import hashlib
import json
import re
import time
import uuid

from ..agent.config import DEFAULTS, SettingsStore
from .memory import MemoryStore
from .messages import MessageStore, account_id, chat_key, numeric_id
from .sessions import encode


def integer(value, default=0, ceiling=10**15):
    return int(value) if type(value) in (int, float) and 0 <= value <= ceiling else default


def snapshot(source):
    source = source.resolve(strict=True)
    files = (
        [source / "config.json"]
        + sorted((source / "messages").glob("*.json"))
        + sorted((source / "sessions").glob("*.json"))
        + sorted((source / "memory").rglob("*.json"))
    )
    out, size = [], 0
    for file in files:
        if not file.is_file():
            continue
        if file.is_symlink() or not file.resolve().is_relative_to(source):
            raise ValueError("迁移源包含目录外链接，请先制作独立复制件")
        before = file.stat()
        if before.st_size > 10 * 1024 * 1024:
            raise ValueError("单个旧数据文件超过 10 MB，请单独检查：" + file.name)
        raw = file.read_bytes()
        after = file.stat()
        size += len(raw)
        if size > 256 * 1024 * 1024:
            raise ValueError("源数据超过 256 MB，请分批迁移")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("旧数据仍在变化，请停止旧版后重试")
        relative = file.relative_to(source).as_posix()
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("旧 JSON 无法读取：" + relative) from error
        if not isinstance(payload, dict):
            raise ValueError("旧数据结构无效：" + relative)
        out.append((relative, hashlib.sha256(raw).hexdigest(), payload))
    if not any(name == "config.json" for name, _, _ in out):
        raise ValueError("未发现旧版 config.json")
    return out


def migrated_config(raw):
    config = copy.deepcopy(DEFAULTS)
    api = raw.get("api") or {}
    for field in config["api"]:
        if field in api:
            config["api"][field] = api[field]
    selected = str(api.get("provider") or "")
    if selected:
        provider = next(
            (
                p
                for p in raw.get("providers", [])
                if isinstance(p, dict) and p.get("id") == selected
            ),
            {},
        )
        key = (raw.get("dshProviderKeys") or {}).get(selected) or provider.get("apiKey")
        if key and key != "******":
            config["api"]["apiKey"] = key
    if config["api"]["apiKey"] == "******":
        config["api"]["apiKey"] = ""
    config["api"]["maxRounds"] = min(20, max(1, integer(config["api"]["maxRounds"], 12)))
    config["api"]["timeoutMs"] = min(300000, max(1000, integer(config["api"]["timeoutMs"], 90000)))
    for field in ("roleText", "customRules"):
        if isinstance((raw.get("persona") or {}).get(field), str):
            config["persona"][field] = raw["persona"][field]
    for field in ("allow", "deny"):
        for kind in ("groups", "private"):
            config[field][kind] = [str(v) for v in (raw.get(field) or {}).get(kind, [])]
    config["blockedUsers"] = [
        str(v) for v in raw.get("globalBlocklist", []) if isinstance(v, (str, int))
    ]
    config["contextLimit"] = min(
        200, max(1, integer((raw.get("store") or {}).get("contextLimit"), 40))
    )
    # Probability/active mode is deliberately not replayed during migration.
    config["groupTrigger"] = "at"
    return config


def import_snapshot(database, data, account, source_id):
    account_id(account)
    messages, memory, settings = (
        MessageStore(database),
        MemoryStore(database),
        SettingsStore(database),
    )
    report = {
        "account": account,
        "files": len(data),
        "messages": 0,
        "sessions": 0,
        "memories": 0,
        "configuration": 0,
        "alreadyImported": 0,
        "skipped": [],
        "warnings": [
            "群触发映射为被 @ 时处理；未迁移概率/活跃模式、主动发言、命令、定时器及插件配置。",
            "旧媒体定位信息保留为元数据；Linux 本地文件路径没有自动复制或下载。",
            "旧版发送记录保留为历史记录，未在 Windows QQ 中重新核验；没有自动恢复旧任务。",
        ],
    }

    def done(kind, identity, fingerprint, operation):
        with database.transaction() as db:
            row = database.connection.execute(
                "SELECT fingerprint FROM imports WHERE source=? AND account=? AND kind=? AND identity=?",
                (source_id, account, kind, identity),
            ).fetchone()
            if row:
                report["alreadyImported"] += 1
                if row["fingerprint"] != fingerprint:
                    report["warnings"].append(f"源记录变化但未覆盖已有导入：{kind}/{identity}")
                return
            operation()
            db.execute(
                "INSERT INTO imports VALUES(?,?,?,?,?)",
                (source_id, account, kind, identity, fingerprint),
            )
        report[kind] += 1

    for path, fingerprint, raw in data:
        try:
            if path == "config.json":
                with database.lock:
                    exists = database.connection.execute(
                        "SELECT 1 FROM settings WHERE account=?", (account,)
                    ).fetchone()
                if exists:
                    report["warnings"].append(
                        "当前账号已有桌面版配置，保留现有配置，未覆盖密钥和人设。"
                    )
                else:
                    done(
                        "configuration",
                        path,
                        fingerprint,
                        lambda: settings.save(account, migrated_config(raw)),
                    )
            elif path.startswith("messages/"):
                key = chat_key(raw.get("chatKey"))
                for index, entry in enumerate(raw.get("messages", [])):
                    try:
                        if not isinstance(entry, dict):
                            raise ValueError("条目格式错误")
                        digest = hashlib.sha256(encode(entry).encode()).hexdigest()
                        identity = f"{key}/{entry.get('id', index)}"

                        def put(entry=entry, key=key):
                            is_self = entry.get("self") is True
                            sender = account if is_self else str(entry.get("senderId") or "")
                            if not re.fullmatch(r"[1-9]\d{0,19}", sender):
                                raise ValueError("发送者号码无效")
                            ts = integer(entry.get("ts"))
                            if not 0 < ts < 32503680000000:
                                raise ValueError("时间无效")
                            text = str(entry.get("text") or "")
                            segments = [{"type": "text", "data": {"text": text}}]
                            for media in entry.get("media") or []:
                                if isinstance(media, dict):
                                    segments.append(
                                        {
                                            "type": media.get("kind", "file"),
                                            "data": media | {"legacyPlatform": "linux"},
                                        }
                                    )
                            name = str(entry.get("senderName") or sender)[:256]
                            with database.transaction() as db:
                                db.execute(
                                    "INSERT OR IGNORE INTO conversations VALUES(?,?,?)",
                                    (
                                        account,
                                        key,
                                        name if key.startswith("private:") and not is_self else "",
                                    ),
                                )
                                db.execute(
                                    """INSERT OR IGNORE INTO messages(account,chat_key,mid,sequence,ts,sender_id,sender_name,body,segments,is_self,withdrawn)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                    (
                                        account,
                                        key,
                                        numeric_id(entry.get("mid")),
                                        "legacy:" + str(entry.get("id", index)),
                                        ts,
                                        sender,
                                        name,
                                        text,
                                        encode(segments),
                                        int(is_self),
                                        0,
                                    ),
                                )

                        done("messages", identity, digest, put)
                    except (ValueError, TypeError, KeyError):
                        report["skipped"].append(
                            {
                                "file": path,
                                "entry": index,
                                "reason": "消息条目校验失败，原数据未改动",
                            }
                        )
            elif path.startswith("sessions/"):
                key = chat_key(raw.get("chatKey"))
                original = str(raw.get("id") or "")
                if not original or len(original) > 128:
                    raise ValueError("日志编号无效")

                def put_session():
                    identifier = uuid.uuid5(
                        uuid.NAMESPACE_URL, source_id + "/" + account + "/" + original
                    ).hex
                    records = []
                    prompts = [
                        {"role": role, "content": raw[field]}
                        for field, role in [("systemPrompt", "system"), ("userPrompt", "user")]
                        if isinstance(raw.get(field), str)
                    ]
                    if prompts:
                        records.append({"kind": "prompt", "messages": prompts})
                    for item in raw.get("messages") or []:
                        if not isinstance(item, dict):
                            continue
                        if (
                            item.get("role") == "assistant"
                            and isinstance(item.get("content"), str)
                            and item["content"].strip()
                        ):
                            records.append({"kind": "assistant", "text": item["content"]})
                        call = item.get("toolCall")
                        if isinstance(call, dict):
                            result = call.get("result")
                            if isinstance(result, str):
                                try:
                                    result = json.loads(result)
                                except ValueError:
                                    result = {"text": result}
                            records.append(
                                {
                                    "kind": "tool",
                                    "name": str(call.get("name") or ""),
                                    "args": call.get("args") or {},
                                    "result": result,
                                    "isError": call.get("isError") is True,
                                }
                            )
                    started = integer(
                        raw.get("startedAt"), int(time.time() * 1000), ceiling=32503679999999
                    )
                    sent = [
                        {
                            "text": str(s.get("text") or "[旧版非文本消息]"),
                            "messageId": numeric_id(s.get("messageId")),
                            "ts": started,
                            "verified": False,
                        }
                        for s in raw.get("sent") or []
                        if isinstance(s, dict)
                    ]
                    state = str(raw.get("status") or "aborted")
                    if state in ("running", "waiting"):
                        state = "aborted"
                    if state not in ("done", "noreply", "error", "aborted"):
                        state = "aborted"
                    if state == "done" and not sent:
                        state = "noreply"
                    usage = {
                        field: integer((raw.get("usage") or {}).get(field), ceiling=10**12)
                        for field in (
                            "promptTokens",
                            "completionTokens",
                            "totalTokens",
                            "calls",
                            "cachedTokens",
                        )
                    }
                    name = str(raw.get("chatName") or "")[:256]
                    if name == key:
                        name = ""
                    messages.set_names(account, {key: name})
                    with database.transaction() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                identifier,
                                account,
                                key,
                                name,
                                started,
                                integer(raw.get("endedAt"), started, ceiling=32503679999999),
                                state,
                                str(raw.get("model") or "")[:256],
                                str(raw.get("triggerSummary") or raw.get("triggerText") or "")[
                                    :2000
                                ],
                                encode(usage),
                                encode(records),
                                encode(sent),
                                str(
                                    raw.get("finishReason")
                                    or raw.get("error")
                                    or "旧版历史会话，未重新执行"
                                )[:1000],
                            ),
                        )

                done("sessions", original, fingerprint, put_session)
            elif path.startswith("memory/") and re.fullmatch(
                r"memory/(group|private)_\d+/\d+\.json", path
            ):
                folder = path.split("/")[1]
                kind, peer = folder.split("_", 1)
                key = chat_key(kind + ":" + peer)
                user = str(raw.get("userId") or path.rsplit("/", 1)[1][:-5])
                for index, entry in enumerate(raw.get("impressions") or []):
                    try:
                        text = str(entry.get("content") or "")
                        digest = hashlib.sha256(text.encode()).hexdigest()
                        done(
                            "memories",
                            key + "/" + user + "/" + digest,
                            digest,
                            lambda text=text: memory.append(
                                account, key, user, str(raw.get("name") or "")[:256], text
                            ),
                        )
                    except (ValueError, TypeError, AttributeError):
                        report["skipped"].append(
                            {
                                "file": path,
                                "entry": index,
                                "reason": "记忆条目校验失败，原数据未改动",
                            }
                        )
            elif path.startswith("memory/"):
                report["skipped"].append(
                    {"file": path, "reason": "不是当前成员记忆格式，未自动转换"}
                )
        except (ValueError, TypeError, KeyError):
            report["skipped"].append(
                {"file": path, "reason": "文件结构或字段校验失败，原数据未改动"}
            )
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    return report
