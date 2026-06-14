from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import sqlite3

from .config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS order_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    price_flag TEXT NOT NULL,
    order_type TEXT NOT NULL,
    trade_kind INTEGER NOT NULL,
    ap_code INTEGER NOT NULL,
    time_in_force TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mit_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    trigger_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    direction TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    triggered_at TEXT,
    order_no TEXT,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS risk_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sim_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_db() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO risk_state(key, value, updated_at) VALUES (?, ?, ?)",
            ("kill_switch", "OFF", datetime.now().isoformat(timespec="seconds")),
        )


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
