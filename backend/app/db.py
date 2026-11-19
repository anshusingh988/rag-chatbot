"""SQLite storage (stands in for PostgreSQL in the synopsis; schema is portable)."""
import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS refresh_tokens(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  tag TEXT DEFAULT '',
  version INTEGER DEFAULT 1,
  status TEXT DEFAULT 'processing',
  error TEXT DEFAULT '',
  n_chunks INTEGER DEFAULT 0,
  uploaded_by INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  text TEXT NOT NULL,
  heading TEXT DEFAULT '',
  page INTEGER,
  embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  title TEXT DEFAULT 'New chat',
  summary TEXT DEFAULT '',
  summarized_upto INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  citations TEXT DEFAULT '[]',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def one(self, sql, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def run(self, sql, args=()):
        with self.tx() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid


_db = None


def get_db() -> DB:
    global _db
    if _db is None:
        _db = DB(config.DB_PATH)
    return _db


def reset_db(path: str) -> DB:
    """For tests."""
    global _db
    _db = DB(path)
    return _db
