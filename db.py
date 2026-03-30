#!/usr/bin/env python3
"""SQLite helpers for storing sensor readings."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    address TEXT NOT NULL,
    name TEXT,
    temperature_c REAL,
    humidity_pct REAL,
    battery_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_readings_address_ts
ON readings(address, ts_utc);

CREATE INDEX IF NOT EXISTS idx_readings_ts
ON readings(ts_utc);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")

        if not table_exists(conn, "readings"):
            conn.executescript(SCHEMA)
            return

        if not has_column(conn, "readings", "address"):
            if table_exists(conn, "sensors"):
                conn.execute("ALTER TABLE readings RENAME TO readings_old")
                conn.executescript(SCHEMA)
                conn.execute(
                    """
                    INSERT INTO readings (id, ts_utc, address, name, temperature_c, humidity_pct, battery_pct)
                    SELECT r.id, r.ts_utc, s.address, s.name, r.temperature_c, r.humidity_pct, r.battery_pct
                    FROM readings_old r
                    JOIN sensors s ON s.id = r.sensor_id
                    """
                )
                conn.execute("DROP TABLE readings_old")
                conn.execute("DROP TABLE IF EXISTS sensors")
            else:
                conn.executescript(SCHEMA)
            return

        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_address_ts ON readings(address, ts_utc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts_utc)")


def insert_reading(
    conn: sqlite3.Connection,
    *,
    address: str,
    name: str | None,
    ts_utc: str,
    temperature_c: Optional[float],
    humidity_pct: Optional[float],
    battery_pct: Optional[float],
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO readings (ts_utc, address, name, temperature_c, humidity_pct, battery_pct)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ts_utc, address, name, temperature_c, humidity_pct, battery_pct),
    )
    return int(cursor.lastrowid)


def get_latest_reading(conn: sqlite3.Connection, address: str | None = None) -> sqlite3.Row | None:
    if address is None:
        return conn.execute(
            """
            SELECT *
            FROM readings
            ORDER BY ts_utc DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    return conn.execute(
        """
        SELECT *
        FROM readings
        WHERE address = ?
        ORDER BY ts_utc DESC, id DESC
        LIMIT 1
        """,
        (address,),
    ).fetchone()


def get_history(
    conn: sqlite3.Connection,
    *,
    address: str | None = None,
    since_utc: str | None = None,
) -> list[sqlite3.Row]:
    query = [
        "SELECT *",
        "FROM readings",
        "WHERE 1=1",
    ]
    params: list[object] = []

    if address is not None:
        query.append("AND address = ?")
        params.append(address)

    if since_utc is not None:
        query.append("AND ts_utc >= ?")
        params.append(since_utc)

    query.append("ORDER BY ts_utc ASC, id ASC")
    return conn.execute("\n".join(query), params).fetchall()
