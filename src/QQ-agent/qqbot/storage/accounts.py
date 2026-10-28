"""每个机器人 QQ 号拥有独立目录、数据库和连接；保留现有存储接口。"""

import sqlite3
import threading
from contextlib import closing, contextmanager

from ..agent.config import SettingsStore
from . import maintenance
from .database import Database
from .files import file_size, managed
from .memory import MemoryStore
from .messages import MessageStore, account_id
from .sessions import SessionStore
from .stickers import StickerStore

METHODS = {
    "settings": {"read", "save", "profile", "check_api", "check_search"},
    "messages": {
        "ingest",
        "set_names",
        "recall",
        "list_chats",
        "messages",
        "delete",
        "context",
        "source_rows",
        "name",
        "has_mid",
        "image_message",
        "active_senders",
        "message_detail",
        "expand_forward",
        "archive_state",
        "mark_read",
        "claim",
    },
    "memory": {
        "chats",
        "members",
        "replace",
        "append",
        "delete",
        "format",
        "snapshot",
        "apply_review",
    },
    "sessions": {"start", "save", "list", "get", "delete", "usage"},
    "stickers": {"list", "add", "get", "note", "delete", "mark_used", "matches"},
}


def account_directory(root, account):
    account_id(account)
    root = root.resolve()
    directory = root / account
    if directory.resolve() != directory:
        raise ValueError("账号目录不能指向其他位置")
    return directory


class _AccountStore:
    def __init__(self, owner, kind):
        self._owner, self._kind = owner, kind

    def __getattr__(self, method):
        if method not in METHODS[self._kind]:
            raise AttributeError(method)

        def call(first, *args, **kwargs):
            account = (
                first.get("account")
                if self._kind == "sessions" and method == "save" and isinstance(first, dict)
                else first
            )
            store = self._owner._open(account)[self._kind]
            return getattr(store, method)(first, *args, **kwargs)

        return call


class AccountStorage:
    def __init__(self, root, *, global_settings=None):
        self._global_settings = global_settings
        self._root, self._lock, self._stores, self._closed = root, threading.RLock(), {}, False
        self._opening = {}
        self.messages = _AccountStore(self, "messages")
        self.settings = _AccountStore(self, "settings")
        self.memory = _AccountStore(self, "memory")
        self.sessions = _AccountStore(self, "sessions")
        self.stickers = _AccountStore(self, "stickers")

    def _open(self, account):
        directory = account_directory(self._root, account)
        with self._lock:
            if self._closed:
                raise ValueError("账号存储已关闭")
            if account in self._stores:
                return self._stores[account]
            ready = self._opening.get(account)
            creator = ready is None
            if creator:
                ready = self._opening[account] = threading.Event()
        if not creator:
            ready.wait()
            return self._open(account)
        database = None
        try:
            # Only this account waits for its schema/IO. Other accounts retain
            # access to their existing stores while a cold database is opened.
            database = Database(directory / "agent.sqlite3")
            stores = {
                "database": database,
                "settings": SettingsStore(database, global_settings=self._global_settings),
                "messages": MessageStore(database),
                "memory": MemoryStore(database),
                "sessions": SessionStore(database),
                "stickers": StickerStore(database),
            }
            with self._lock:
                if self._closed:
                    raise ValueError("账号存储已关闭")
                self._stores[account] = stores
            return stores
        except BaseException:
            if database is not None:
                database.close()
            raise
        finally:
            with self._lock:
                self._opening.pop(account, None)
                ready.set()

    def close(self):
        with self._lock:
            self._closed = True
            stores = list(self._stores.values())
            opening = list(self._opening.values())
            self._stores.clear()
        for store in stores:
            store["database"].close()
        for ready in opening:
            ready.wait()

    def _storage_file(self, account):
        directory = account_directory(self._root, account)
        file = managed(directory / "agent.sqlite3", self._root)
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = file.with_name(file.name + suffix)
            file_size(target, self._root)
            if target.exists() and target.stat().st_nlink > 1:
                raise ValueError("账号数据库不能使用硬链接")
        return file

    @contextmanager
    def _storage_connection(self, account, *, write=False):
        # Reuse a live connection under its transaction lock. Offline reads must
        # not instantiate SessionStore (which marks interrupted runs aborted).
        with self._lock:
            if self._closed:
                raise ValueError("账号存储已关闭")
            file = self._storage_file(account)
            if not file.exists():
                yield None
            elif account in self._stores:
                database = self._stores[account]["database"]
                with database.lock:
                    yield database.connection
            else:
                mode = "rw" if write else "ro"
                with closing(
                    sqlite3.connect(file.as_uri() + "?mode=" + mode, uri=True, timeout=3)
                ) as connection:
                    yield connection

    def storage_snapshot(self, account):
        with self._storage_connection(account) as connection:
            values = (
                maintenance.counts(connection, account)
                if connection
                else dict.fromkeys(maintenance.CATEGORIES, 0)
            )
            file = self._storage_file(account)
            size = sum(
                file_size(file.with_name(file.name + suffix), self._root)
                for suffix in ("", "-wal", "-shm", "-journal")
            )
            return {"databaseBytes": size, "counts": values}

    def storage_clear(self, account, category):
        if category not in maintenance.CATEGORIES:
            raise ValueError("数据分类无效")
        with self._storage_connection(account, write=True) as connection:
            if connection is None:
                return {"deletedRows": 0, "freedBytes": 0, "failures": []}
            before = self.storage_snapshot(account)["databaseBytes"]
            deleted = maintenance.clear(connection, account, category)
            failures = []
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                # DELETE was already committed; report that truth separately
                # from optional file compaction instead of claiming rollback.
                failures.append("记录已清理，但数据库压缩未完成，请稍后重试")
            after = self.storage_snapshot(account)["databaseBytes"]
            return {
                "deletedRows": deleted,
                "freedBytes": max(0, before - after),
                "failures": failures,
            }
