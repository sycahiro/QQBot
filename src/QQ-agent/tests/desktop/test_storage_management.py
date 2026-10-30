import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.desktop.storage import DEFAULT_POLICY, StorageManagement
from qqbot.qq.connection import QqConnection
from qqbot.qq.engine import EngineError
from qqbot.storage.accounts import AccountStorage
from qqbot.storage.database import Database

ROOT = Path(__file__).resolve().parents[4]
A, B = "12345678", "87654321"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    paths = DesktopPaths(ROOT, tmp_path)
    # snowluma_data 锚定真实根目录（生产数据库位置）；测试必须隔离到 tmp，避免污染运行数据。
    monkeypatch.setattr(DesktopPaths, "snowluma_home", property(lambda self: tmp_path / "snowluma-home"))
    monkeypatch.setattr(
        DesktopPaths, "snowluma_data", property(lambda self: self.snowluma_home / "data")
    )
    accounts = AccountStorage(tmp_path / "accounts")
    connection = QqConnection(paths, None, None, engine_factory=lambda _: None)
    manager = StorageManagement(paths, accounts, connection)
    try:
        yield paths, accounts, connection, manager
    finally:
        accounts.close()
        connection.close()


def seed(accounts, account):
    database = accounts._open(account)["database"]
    with database.lock, database.connection as db:
        db.execute("INSERT INTO conversations VALUES(?, 'private:11111111', '联系人')", (account,))
        db.execute("INSERT INTO settings VALUES(?,?)", (account, '{"persona":"保留的人设"}'))
        db.execute("INSERT INTO imports VALUES('old',?,'messages','1','digest')", (account,))
        db.execute(
            "INSERT INTO messages(account,chat_key,mid,ts,sender_id,sender_name,body,segments,is_self) VALUES(?,'private:11111111','1',1,'11111111','成员','正文','[]',0)",
            (account,),
        )
        db.execute("INSERT INTO recalls VALUES(?,'private:11111111','2')", (account,))
        db.execute(
            "INSERT INTO sessions VALUES(?,?,'private:11111111','联系人',1,2,'done','model','正文','{}','[]','[]','')",
            (account, account),
        )
        db.execute(
            "INSERT INTO memories(account,chat_key,user_id,target,content,ts) VALUES(?,'private:11111111','11111111','成员','印象',1)",
            (account,),
        )
        db.execute(
            "INSERT INTO stickers VALUES(?,?,'digest',?,'备注','[]','场景',1,1,0,1,0)",
            (account, account, b"fake-jpeg"),
        )
    return database


def log(paths, session, size=10):
    directory = paths.runtime / "logs" / session
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / "desktop.log"
    file.write_bytes(b"x" * size)
    return file


def test_overview_and_bridge_do_not_expose_configuration_or_create_databases(stores):
    paths, accounts, connection, manager = stores
    seed(accounts, A)
    index = paths.snowluma_data / B / "messages.db"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"index")
    data = manager.overview()
    assert data["settings"] == DEFAULT_POLICY
    assert data["accounts"][0]["counts"] == dict.fromkeys(
        ("archives", "sessions", "memories", "stickers"), 1
    )
    assert data["accounts"][1]["indexBytes"] == 5
    assert data["accounts"][1]["counts"]["sessions"] == 0
    assert not (paths.runtime / "accounts" / B).exists()
    assert "保留的人设" not in json.dumps(data, ensure_ascii=False)
    bridge = DesktopBridge(paths, lambda **_: None, accounts=accounts, connection=connection)
    assert bridge.get_storage()["ok"]
    assert (
        bridge.cleanup_storage({"scope": "account", "category": "settings", "account": A})["ok"]
        is False
    )


@pytest.mark.parametrize("category", ["archives", "sessions", "memories", "stickers"])
def test_category_cleanup_preserves_other_data_settings_imports_and_names(stores, category):
    _, accounts, _, manager = stores
    database = seed(accounts, A)
    seed(accounts, B)
    result = manager.cleanup({"scope": "account", "category": category, "account": A})
    assert result["success"] and result["cleanup"]["deletedRows"] == 1
    assert accounts.storage_snapshot(A)["counts"] == {
        key: int(key != category) for key in ("archives", "sessions", "memories", "stickers")
    }
    assert accounts.storage_snapshot(B)["counts"] == dict.fromkeys(
        ("archives", "sessions", "memories", "stickers"), 1
    )
    assert (
        database.connection.execute("SELECT value FROM settings").fetchone()[0]
        == '{"persona":"保留的人设"}'
    )
    assert database.connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 1
    assert database.connection.execute("SELECT name FROM conversations").fetchone()[0] == "联系人"
    assert database.connection.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == int(
        category != "archives"
    )


def test_overview_does_not_mark_unopened_interrupted_sessions_aborted(stores):
    paths, accounts, _, manager = stores
    database = Database(paths.runtime / "accounts" / A / "agent.sqlite3")
    with database.connection as db:
        db.execute(
            "INSERT INTO sessions VALUES('run',?,'private:11111111','联系人',1,NULL,'running','model','','{}','[]','[]','')",
            (A,),
        )
    database.close()
    assert manager.overview()["accounts"][0]["counts"]["sessions"] == 1
    with sqlite3.connect(paths.runtime / "accounts" / A / "agent.sqlite3") as db:
        assert db.execute("SELECT status FROM sessions").fetchone()[0] == "running"
    assert accounts._stores == {}


def test_cleanup_refuses_active_engine_and_holds_attach_gate(stores):
    _, accounts, connection, manager = stores
    seed(accounts, A)
    connection._client = SimpleNamespace(close=lambda: None)
    with pytest.raises(EngineError, match="断开"):
        manager.cleanup({"scope": "account", "category": "archives", "account": A})
    connection._client = None
    ready, release = threading.Event(), threading.Event()

    def maintain():
        with connection.storage_maintenance():
            ready.set()
            release.wait(3)

    thread = threading.Thread(target=maintain)
    thread.start()
    try:
        assert ready.wait(2)
        with pytest.raises(EngineError, match="操作"):
            with connection._operation():
                pytest.fail("concurrent attach acquired maintenance gate")
    finally:
        release.set()
        thread.join(3)
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1


def test_all_accounts_requires_exact_reviewed_scope_before_first_delete(stores):
    _, accounts, _, manager = stores
    seed(accounts, A)
    seed(accounts, B)
    with pytest.raises(ValueError, match="变化"):
        manager.cleanup({"scope": "allAccounts", "category": "archives", "accounts": [A]})
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1
    result = manager.cleanup({"scope": "allAccounts", "category": "archives", "accounts": [A, B]})
    assert result["cleanup"]["deletedRows"] == 2


def test_logs_prune_oldest_by_quota_and_never_touch_current_or_unknown_files(stores):
    paths, _, _, manager = stores
    first = log(paths, "2020-01-01_00-00-00.000001-1", 700000)
    second = log(paths, "2021-01-01_00-00-00.000001-2", 700000)
    current = log(paths, paths.log_session, 100)
    unknown = first.parent / "keep.json"
    unknown.write_text("keep")
    result = manager.save({"logMaxTotalMb": 1, "logRetainDays": 0, "engineRetainDays": 0})
    assert result["cleanup"]["deletedFiles"] == 1
    assert not first.exists() and second.exists() and current.exists() and unknown.exists()
    manager.cleanup({"scope": "logs"})
    assert not second.exists() and current.exists() and unknown.exists()
    assert manager.overview()["logs"]["activeBytes"] == 100


def test_retention_applies_on_sweep_without_rewriting_settings(stores):
    paths, _, _, manager = stores
    old = log(paths, "2020-01-01_00-00-00.000001-1")
    current = log(paths, paths.log_session)
    manager.sweep()
    assert not old.exists() and current.exists()
    assert not (paths.runtime / "settings" / "storage.json").exists()


def test_current_launch_survives_over_quota(stores):
    paths, _, _, manager = stores
    current = log(paths, paths.log_session, 1100000)
    result = manager.save({"logMaxTotalMb": 1, "logRetainDays": 1, "engineRetainDays": 1})
    assert current.exists() and result["overview"]["logs"]["activeBytes"] > 1024**2


def test_engine_logs_are_counted_and_pruned_without_touching_today(stores):
    paths, _, _, manager = stores
    folder = paths.snowluma_home / "logs"
    folder.mkdir(parents=True)
    old = folder / "snowluma-2020-01-01.log"
    old.write_bytes(b"y" * 64)
    today = folder / f"snowluma-{datetime.now():%Y-%m-%d}.log"
    today.write_bytes(b"z" * 32)
    unknown = folder / "keep.txt"
    unknown.write_text("keep")

    logs = manager.overview()["logs"]
    assert logs["engineFiles"] == 2 and logs["engineBytes"] == 96
    assert logs["engineClosedFiles"] == 1 and logs["engineActiveBytes"] == 32
    assert logs["bytes"] == logs["activeBytes"] + logs["engineBytes"]

    result = manager.save({"logMaxTotalMb": 256, "logRetainDays": 30, "engineRetainDays": 30})
    assert result["cleanup"]["deletedFiles"] == 1 and not old.exists()
    assert today.exists() and unknown.exists()
    manager.cleanup({"scope": "logs"})
    assert today.exists() and unknown.exists()


def test_temporary_and_indexes_only_remove_fixed_managed_data(stores):
    paths, accounts, _, manager = stores
    seed(accounts, A)
    folder = paths.runtime / "accounts" / A / "media-tmp" / "read-old"
    folder.mkdir(parents=True)
    (folder / "input.media").write_bytes(b"input")
    index = paths.snowluma_data / A
    index.mkdir(parents=True)
    (index / "messages.db").write_bytes(b"index")
    (index / "identity.json").write_text("keep")
    assert manager.cleanup({"scope": "temporary"})["cleanup"]["freedBytes"] == 5
    assert not (folder / "input.media").exists()
    assert (
        manager.cleanup({"scope": "account", "category": "indexes", "account": A})["cleanup"][
            "deletedFiles"
        ]
        == 1
    )
    assert (index / "identity.json").read_text() == "keep"
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"logMaxTotalMb": True, "logRetainDays": 1, "engineRetainDays": 1},
        {"logMaxTotalMb": 0, "logRetainDays": 1, "engineRetainDays": 1},
        {"logMaxTotalMb": 1, "logRetainDays": -1, "engineRetainDays": 1},
        {"logMaxTotalMb": 1, "logRetainDays": 1.5, "engineRetainDays": 1},
    ],
)
def test_invalid_policy_never_deletes_or_saves(stores, value):
    paths, _, _, manager = stores
    old = log(paths, "2020-01-01_00-00-00.000001-1")
    with pytest.raises(ValueError):
        manager.save(value)
    assert old.exists() and not (paths.runtime / "settings" / "storage.json").exists()


def test_database_hardlink_and_account_junction_rejected_without_touching_target(stores, tmp_path):
    paths, accounts, _, manager = stores
    source = tmp_path / "outside.sqlite3"
    database = Database(source)
    database.close()
    directory = paths.runtime / "accounts" / A
    directory.mkdir(parents=True)
    os.link(source, directory / "agent.sqlite3")
    with pytest.raises(ValueError, match="硬链接"):
        manager.overview()
    (directory / "agent.sqlite3").unlink()
    directory.rmdir()
    import _winapi

    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    _winapi.CreateJunction(str(target), str(directory))
    try:
        with pytest.raises(ValueError, match="链接"):
            manager.cleanup({"scope": "temporary"})
        assert (target / "keep.txt").read_text() == "keep"
    finally:
        os.rmdir(directory)


def test_pending_agent_jobs_prevent_cleanup(stores):
    _, accounts, _, manager = stores
    seed(accounts, A)
    manager._agent = SimpleNamespace(status=lambda: {"active": 1, "queued": 0})
    with pytest.raises(ValueError, match="任务"):
        manager.cleanup({"scope": "account", "category": "archives", "account": A})
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1


def test_future_database_is_rejected_before_any_bulk_deletion(stores):
    _, accounts, _, manager = stores
    seed(accounts, A)
    database = seed(accounts, B)
    database.connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="版本"):
        manager.cleanup({"scope": "allAccounts", "category": "archives", "accounts": [A, B]})
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1


def test_bulk_cleanup_reports_partial_failure_and_retains_actual_counts(stores, monkeypatch):
    _, accounts, _, manager = stores
    seed(accounts, A)
    seed(accounts, B)
    original = accounts.storage_clear

    def clear(account, category):
        if account == B:
            raise sqlite3.OperationalError("database is locked")
        return original(account, category)

    monkeypatch.setattr(accounts, "storage_clear", clear)
    result = manager.cleanup({"scope": "allAccounts", "category": "archives", "accounts": [A, B]})
    assert result["success"] is False and result["cleanup"]["deletedRows"] == 1
    assert len(result["cleanup"]["failures"]) == 1 and B in result["cleanup"]["failures"][0]
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 0
    assert accounts.storage_snapshot(B)["counts"]["archives"] == 1


@pytest.mark.parametrize(
    "cleanup_request",
    [
        {"scope": "allAccounts", "category": "archives", "accounts": []},
        {"scope": "allAccounts", "category": "archives", "accounts": [A, A]},
        {"scope": "allAccounts", "category": "archives", "accounts": ["../outside"]},
        {"scope": "account", "category": "archives", "account": "../outside"},
        {"scope": "account", "category": "settings", "account": A},
        {"scope": "account", "category": {}, "account": A},
        {"scope": {}},
        {"scope": "logs", "path": "../outside"},
    ],
)
def test_forged_cleanup_requests_do_not_change_data(stores, cleanup_request):
    _, accounts, _, manager = stores
    seed(accounts, A)
    with pytest.raises(ValueError):
        manager.cleanup(cleanup_request)
    assert accounts.storage_snapshot(A)["counts"]["archives"] == 1


def test_engine_retention_is_independent_of_application_retention(stores):
    paths, _, _, manager = stores
    old_app = log(paths, "2020-01-01_00-00-00.000000-111")
    engine_dir = paths.snowluma_home / "logs"
    engine_dir.mkdir(parents=True)
    old_engine = engine_dir / "snowluma-2020-01-01.log"
    old_engine.write_bytes(b"engine")
    manager.save({"logMaxTotalMb": 256, "logRetainDays": 1, "engineRetainDays": 0})
    assert not old_app.exists() and old_engine.exists()
    manager.save({"logMaxTotalMb": 256, "logRetainDays": 0, "engineRetainDays": 1})
    assert not old_engine.exists()


def test_snowluma_home_counted_without_double_counting_index(stores):
    paths, _, _, manager = stores
    index = paths.snowluma_data / A / "messages.db"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"index")
    credentials = paths.snowluma_home / "credentials.json"
    credentials.write_bytes(b"secret-value")
    totals = manager.overview()["totals"]
    assert totals["accountBytes"] == 5
    assert totals["serviceBytes"] == len(b"secret-value")
    assert totals["managedBytes"] == 5 + len(b"secret-value")
