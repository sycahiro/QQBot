"""单账号 SQLite 连接及事务锁；不读取或修改 QQ 原生数据库。"""

import sqlite3
import threading
from contextlib import contextmanager


class Database:
    def __init__(self, file):
        file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._savepoint = 0
        self.connection = sqlite3.connect(file, check_same_thread=False, timeout=3)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 6:
            self.connection.close()
            raise RuntimeError("业务数据库版本高于当前程序支持的版本")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS conversations(
                account TEXT NOT NULL, chat_key TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(account,chat_key));
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, chat_key TEXT NOT NULL,
                mid TEXT, sequence TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL,
                sender_id TEXT NOT NULL, sender_name TEXT NOT NULL, body TEXT NOT NULL,
                segments TEXT NOT NULL, is_self INTEGER NOT NULL, withdrawn INTEGER NOT NULL DEFAULT 0,
                is_read INTEGER NOT NULL DEFAULT 1 CHECK(is_read IN (0,1)),
                UNIQUE(account,chat_key,mid,sequence,is_self),
                FOREIGN KEY(account,chat_key) REFERENCES conversations(account,chat_key) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS messages_chat ON messages(account,chat_key,id);
            CREATE TABLE IF NOT EXISTS recalls(
                account TEXT NOT NULL, chat_key TEXT NOT NULL, mid TEXT NOT NULL,
                PRIMARY KEY(account,chat_key,mid));
            CREATE TABLE IF NOT EXISTS settings(account TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, chat_key TEXT NOT NULL, name TEXT NOT NULL,
                started INTEGER NOT NULL, ended INTEGER, status TEXT NOT NULL, model TEXT NOT NULL,
                trigger_text TEXT NOT NULL, usage TEXT NOT NULL, records TEXT NOT NULL, sent TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account,started DESC);
            CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, chat_key TEXT NOT NULL,
                user_id TEXT NOT NULL, target TEXT NOT NULL, content TEXT NOT NULL, ts INTEGER NOT NULL,
                UNIQUE(account,chat_key,user_id,content));
            CREATE INDEX IF NOT EXISTS memories_chat ON memories(account,chat_key,user_id);
            CREATE TABLE IF NOT EXISTS imports(
                source TEXT NOT NULL, account TEXT NOT NULL, kind TEXT NOT NULL, identity TEXT NOT NULL,
                fingerprint TEXT NOT NULL, PRIMARY KEY(source,account,kind,identity));
            CREATE TABLE IF NOT EXISTS stickers(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, digest TEXT NOT NULL,
                image BLOB NOT NULL CHECK(length(image)<=524288), note TEXT NOT NULL,
                tags TEXT NOT NULL, usage TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                first_frame INTEGER NOT NULL, created INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
                UNIQUE(account,digest));
            CREATE INDEX IF NOT EXISTS stickers_account ON stickers(account,created DESC);
        """)
        with self.connection as db:
            # Earlier versions did not record unread state. Existing archives
            # start read; only newly admitted incoming messages become unread.
            if "is_read" not in {row[1] for row in db.execute("PRAGMA table_info(messages)")}:
                db.execute(
                    "ALTER TABLE messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 1 CHECK(is_read IN (0,1))"
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS messages_unread ON messages(account,chat_key,id) WHERE is_read=0 AND is_self=0 AND withdrawn=0"
            )
            db.execute("PRAGMA user_version=6")

    def close(self):
        with self.lock:
            self.connection.close()

    @contextmanager
    def transaction(self):
        """Nest writes without committing a caller's transaction prematurely."""
        with self.lock:
            self._savepoint += 1
            name = f"store_{self._savepoint}"
            self.connection.execute(f"SAVEPOINT {name}")
            try:
                yield self.connection
            except BaseException:
                self.connection.execute(f"ROLLBACK TO {name}")
                self.connection.execute(f"RELEASE {name}")
                raise
            else:
                self.connection.execute(f"RELEASE {name}")
