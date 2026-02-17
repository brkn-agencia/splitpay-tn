import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

DB_PATH = os.environ.get("DB_PATH", "app.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tn_store_id TEXT UNIQUE NOT NULL,
  tn_access_token TEXT NOT NULL,
  mp_access_token TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('product','category','global')),
  reference_id TEXT,
  max_installments INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(store_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS splits (
  id TEXT PRIMARY KEY,
  store_id INTEGER NOT NULL,
  buyer_email TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  shipping_method TEXT,
  shipping_cost INTEGER NOT NULL DEFAULT 0,
  shipping_paid_in_group TEXT,
  cart_json TEXT NOT NULL,
  groups_json TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(store_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS split_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  split_id TEXT NOT NULL,
  group_key TEXT NOT NULL,
  mp_preference_id TEXT,
  mp_init_point TEXT,
  mp_payment_id TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(split_id) REFERENCES splits(id) ON DELETE CASCADE
);
"""

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
