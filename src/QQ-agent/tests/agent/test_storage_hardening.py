import copy
import json
import sqlite3
import threading

import pytest
from qqbot.agent.config import DEFAULTS, SettingsStore, validate_api
from qqbot.agent.global_settings import GlobalSettings
from qqbot.agent.profiles import public_config
from qqbot.storage import accounts as account_module
from qqbot.storage.accounts import AccountStorage
from qqbot.storage.database import Database
from qqbot.storage.files import ACCOUNT as MANAGED_ACCOUNT
from qqbot.storage.memory import MemoryStore
from qqbot.storage.messages import MessageStore, normalize_message
from qqbot.storage.migration import import_snapshot, snapshot
from qqbot.storage.sessions import SessionStore
from test_agent import ACCOUNT, OTHER, PEER, packet
from test_migration import source

KEY = f"private:{PEER}"


def test_public_settings_are_pure_idempotent_and_keep_private_keys():
    private = copy.deepcopy(DEFAULTS)
    private["api"]["apiKey"] = "fixture-secret"
    private["profiles"] = [
        {"id": "fixture", "name": "fixture", "api": copy.deepcopy(private["api"])}
    ]
    before = copy.deepcopy(private)
    public = public_config(private)
    assert private == before and public_config(public) == public
    assert public["api"]["apiKeyConfigured"] and "apiKey" not in public["api"]
    assert "fixture-secret" not in json.dumps(public)


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
def test_explicit_chat_token_field_and_legacy_profiles_keep_keys(tmp_path, field):
    shared = GlobalSettings(tmp_path)
    shared.profile(
        "global", "save", {"name": "fixture", "api": {"model": "fixture", "apiKey": "fixture-key"}}
    )
    file = tmp_path / "settings" / "global.json"
    raw = json.loads(file.read_text())
    for api in [raw["api"], raw["profiles"][0]["api"]]:
        api.pop("chatTokenLimitField")
    file.write_text(json.dumps(raw), encoding="utf-8")
    before = file.read_bytes()
    loaded = shared.read()
    assert loaded["api"]["chatTokenLimitField"] == "max_tokens"
    assert loaded["profiles"][0]["api"]["chatTokenLimitField"] == "max_tokens"
    assert loaded["api"]["apiKey"] == "fixture-key" and file.read_bytes() == before
    assert (
        shared.save("global", {"api": {"chatTokenLimitField": field}})["api"]["chatTokenLimitField"]
        == field
    )
    with pytest.raises(ValueError):
        validate_api({**copy.deepcopy(DEFAULTS["api"]), "chatTokenLimitField": "both"})


@pytest.mark.parametrize("payload", [b'{"api":', b"\xff\xfeinvalid"])
def test_damaged_global_config_preserves_bytes_and_reports_consistently(tmp_path, payload):
    file = tmp_path / "settings" / "global.json"
    file.parent.mkdir(parents=True)
    file.write_bytes(payload)
    shared = GlobalSettings(tmp_path)
    assert file.exists()
    for operation in (shared.read,):
        with pytest.raises(ValueError, match="全局设置无法读取，原文件已保留"):
            operation()
    assert file.read_bytes() == payload


def test_missing_original_account_fields_are_not_silently_defaulted(tmp_path):
    database = Database(tmp_path / "account.sqlite3")
    try:
        raw = copy.deepcopy(DEFAULTS)
        del raw["allow"]
        encoded = json.dumps(raw)
        with database.connection as db:
            db.execute("INSERT INTO settings VALUES(?,?)", (ACCOUNT, encoded))
        with pytest.raises(ValueError, match="原数据已保留"):
            SettingsStore(database).read(ACCOUNT)
        assert database.connection.execute("SELECT value FROM settings").fetchone()[0] == encoded
    finally:
        database.close()


@pytest.mark.parametrize("raw", ["[not-json", '{"bad":1}', "null", b"[bad"])
def test_damaged_segments_do_not_hide_archive_or_break_model_metadata(tmp_path, raw):
    database = Database(tmp_path / "messages.sqlite3")
    try:
        store = MessageStore(database)
        store.ingest(ACCOUNT, packet(1))
        with database.connection as db:
            db.execute("UPDATE messages SET segments=?", (raw,))
        item = store.messages(ACCOUNT, KEY)["items"][0]
        assert item["text"] == "你好" and not item["hasImage"] and not item["hasForward"]
        assert store.context(ACCOUNT, KEY)[0]["segments"] == []
        assert store.message_detail(ACCOUNT, KEY, 1)["segments"] == []
        assert database.connection.execute("SELECT segments FROM messages").fetchone()[0] == raw
    finally:
        database.close()


def test_bulk_sources_use_one_scoped_query_without_segments_and_redact_recalled_body(tmp_path):
    storage = AccountStorage(tmp_path / "accounts")
    try:
        first = storage.messages.ingest(ACCOUNT, packet(1))
        foreign = storage.messages.ingest(OTHER, packet(2, self_id=OTHER))
        other_chat = storage.messages.ingest(ACCOUNT, packet(3, user_id=OTHER))
        storage.messages.recall(ACCOUNT, KEY, 1)
        database = storage._open(ACCOUNT)["database"]
        queries = []
        database.connection.set_trace_callback(queries.append)
        result = storage.messages.source_rows(
            ACCOUNT, KEY, [first["id"], foreign["id"], other_chat["id"]]
        )
        assert len(result) == 1 and result[0]["withdrawn"] and result[0]["text"] == "[消息已撤回]"
        assert len([q for q in queries if q.startswith("SELECT")]) == 1
        assert "segments" not in queries[-1]
        assert storage.messages.source_rows(ACCOUNT, KEY, []) == []
        with pytest.raises(ValueError):
            storage.messages.source_rows(ACCOUNT, KEY, [True])
    finally:
        storage.close()


def test_bulk_source_checks_keep_all_old_rows_across_sql_parameter_chunks(tmp_path):
    database = Database(tmp_path / "many-sources.sqlite3")
    try:
        store = MessageStore(database)
        store.ingest(ACCOUNT, packet(1))
        with database.transaction() as db:
            db.executemany(
                "INSERT INTO messages(account,chat_key,mid,ts,sender_id,sender_name,body,segments,is_self) VALUES(?,?,?,?,?,?,?,?,0)",
                [
                    (ACCOUNT, KEY, str(mid), 1, PEER, "fixture", str(mid), "[]")
                    for mid in range(2, 602)
                ],
            )
        queries = []
        database.connection.set_trace_callback(queries.append)
        rows = store.source_rows(ACCOUNT, KEY, list(range(1, 602)))
        assert len(rows) == 601 and rows[0]["id"] == 1 and rows[-1]["id"] == 601
        assert len([query for query in queries if query.startswith("SELECT")]) == 2
        store.recall(ACCOUNT, KEY, 1)
        assert store.source_rows(ACCOUNT, KEY, list(range(1, 602)))[0]["withdrawn"]
        with pytest.raises(ValueError):
            store.source_rows(ACCOUNT, KEY, list(range(1, 4098)))
    finally:
        database.close()


def test_session_bad_rows_do_not_break_lists_details_or_usage(tmp_path):
    database = Database(tmp_path / "sessions.sqlite3")
    try:
        store = SessionStore(database)
        first = store.start(ACCOUNT, KEY, "fixture", "fixture", "fixture")
        with database.connection as db:
            db.execute(
                "UPDATE sessions SET status='done',started=?,usage=?,sent=?,records=? WHERE id=?",
                (
                    10**15,
                    '{"totalTokens":5,"calls":"bad","promptTokens":true,"completionTokens":-2}',
                    "[bad",
                    "null",
                    first["id"],
                ),
            )
        second = store.start(ACCOUNT, KEY, "fixture", "fixture", "fixture")
        with database.connection as db:
            db.execute("UPDATE sessions SET usage=? WHERE id=?", ("[bad", second["id"]))
        assert len(store.list(ACCOUNT)) == 2
        detail = store.get(ACCOUNT, first["id"])
        assert detail["sent"] == detail["records"] == []
        assert detail["usage"] == {
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 5,
            "calls": 0,
        }
        assert store.usage(ACCOUNT) == {
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 5,
            "calls": 0,
            "todayTokens": 0,
            "sessions": 2,
        }
        assert (
            database.connection.execute(
                "SELECT records FROM sessions WHERE id=?", (first["id"],)
            ).fetchone()[0]
            == "null"
        )
    finally:
        database.close()


def test_memory_review_does_not_commit_an_outer_transaction(tmp_path):
    database = Database(tmp_path / "memory.sqlite3")
    try:
        memory = MemoryStore(database)
        memory.replace(ACCOUNT, KEY, PEER, "fixture", ["old"])
        revision = memory.snapshot(ACCOUNT, KEY, PEER)["revision"]
        with pytest.raises(RuntimeError):
            with database.transaction() as db:
                db.execute("INSERT INTO conversations VALUES(?,?,?)", (ACCOUNT, KEY, "uncommitted"))
                memory.apply_review(ACCOUNT, KEY, PEER, revision, ["new"], lambda: True)
                raise RuntimeError("fixture rollback")
        assert memory.snapshot(ACCOUNT, KEY, PEER)["values"] == ["old"]
        assert database.connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    finally:
        database.close()


@pytest.mark.parametrize(
    "kind,table",
    [
        ("config", "settings"),
        ("messages", "messages"),
        ("sessions", "sessions"),
        ("memory", "memories"),
    ],
)
def test_migration_business_row_and_receipt_roll_back_together(tmp_path, kind, table):
    data = [item for item in snapshot(source(tmp_path)) if item[0].startswith(kind)]
    database = Database(tmp_path / "migration.sqlite3")
    try:
        database.connection.execute(
            "CREATE TRIGGER fixture_fail BEFORE INSERT ON imports BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            import_snapshot(database, data, ACCOUNT, "fixture")
        assert database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert database.connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0
        database.connection.execute("DROP TRIGGER fixture_fail")
        result = import_snapshot(database, data, ACCOUNT, "fixture")
        assert not result["skipped"]
    finally:
        database.close()


def test_memory_prompt_limit_is_explicit_and_ignores_unrelated_member_rows(tmp_path):
    database = Database(tmp_path / "many-memory.sqlite3")
    try:
        memory = MemoryStore(database)
        key = "group:99887766"
        for user in [PEER, OTHER]:
            memory.replace(ACCOUNT, key, user, "fixture", [f"memory {i}" for i in range(50)])
        assert memory.format(ACCOUNT, key, {PEER}).count("fixture") == 50
        assert "仅展示前 80 条" in memory.format(ACCOUNT, key, {PEER, OTHER})
    finally:
        database.close()


def test_oversized_memory_list_is_reported_instead_of_silently_losing_the_tail(tmp_path):
    database = Database(tmp_path / "memory-cap.sqlite3")
    try:
        with database.transaction() as db:
            db.executemany(
                "INSERT INTO memories(account,chat_key,user_id,target,content,ts) VALUES(?,?,?,?,?,?)",
                [
                    (ACCOUNT, "group:99887766", str(22000000 + i // 50), "fixture", str(i % 50), 1)
                    for i in range(25001)
                ],
            )
        with pytest.raises(ValueError, match="列表上限"):
            MemoryStore(database).members(ACCOUNT, "group:99887766")
        assert database.connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 25001
    finally:
        database.close()


@pytest.mark.parametrize("sender", ["-12345", "1\u0662", "123456789012345678901"])
def test_sender_ids_are_positive_ascii_peers_but_message_ids_may_be_negative(sender):
    assert normalize_message(ACCOUNT, packet(-9, kind="group", user_id=sender)) is None
    assert normalize_message(ACCOUNT, packet(-9))["mid"] == "-9"
    assert not MANAGED_ACCOUNT.fullmatch("1234567890123")


def test_cold_account_initialization_does_not_block_another_account_and_is_single_owner(
    tmp_path, monkeypatch
):
    storage = AccountStorage(tmp_path / "accounts")
    storage.settings.read(ACCOUNT)
    entered, release, read_ready = threading.Event(), threading.Event(), threading.Event()
    created = []
    errors = []
    original = account_module.Database

    def slow_database(file):
        if file.parent.name == OTHER:
            created.append(file)
            entered.set()
            assert release.wait(3)
        return original(file)

    monkeypatch.setattr(account_module, "Database", slow_database)

    def cold_read():
        try:
            storage.settings.read(OTHER)
        except Exception as error:
            errors.append(error)

    first, second = threading.Thread(target=cold_read), threading.Thread(target=cold_read)
    first.start()
    try:
        assert entered.wait(2)
        second.start()
        warm = threading.Thread(target=lambda: (storage.settings.read(ACCOUNT), read_ready.set()))
        warm.start()
        assert read_ready.wait(2)
        warm.join(2)
    finally:
        release.set()
        first.join(3)
        second.join(3)
        storage.close()
    assert len(created) == 1 and not errors and not first.is_alive() and not second.is_alive()
