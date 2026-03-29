#!/usr/bin/env python3
"""SQLite helpers for storing sensor readings."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL UNIQUE,
    name TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    ts_utc TEXT NOT NULL,
    temperature_c REAL,
    humidity_pct REAL,
    battery_pct REAL,
    FOREIGN KEY(sensor_id) REFERENCES sensors(id)
);

CREATE INDEX IF NOT EXISTS idx_readings_sensor_ts
ON readings(sensor_id, ts_utc);

CREATE INDEX IF NOT EXISTS idx_readings_ts
ON readings(ts_utc);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_sensor(conn: sqlite3.Connection, address: str, name: str | None, ts_utc: str) -> int:
    row = conn.execute("SELECT id FROM sensors WHERE address = ?", (address,)).fetchone()
    if row is None:
        cursor = conn.execute(
            """
            INSERT INTO sensors (address, name, first_seen, last_seen, enabled)
            VALUES (?, ?, ?, ?, 1)
            """,
            (address, name, ts_utc, ts_utc),
        )
        return int(cursor.lastrowid)

    conn.execute(
        "UPDATE sensors SET name = COALESCE(?, name), last_seen = ? WHERE id = ?",
        (name, ts_utc, int(row["id"])),
    )
    return int(row["id"])


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
    sensor_id = upsert_sensor(conn, address, name, ts_utc)
    cursor = conn.execute(
        """
        INSERT INTO readings (sensor_id, ts_utc, temperature_c, humidity_pct, battery_pct)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sensor_id, ts_utc, temperature_c, humidity_pct, battery_pct),
    )
    return int(cursor.lastrowid)


def get_latest_reading(conn: sqlite3.Connection, address: str | None = None) -> sqlite3.Row | None:
    if address is None:
        return conn.execute(
            """
            SELECT r.*, s.address, s.name
            FROM readings r
            JOIN sensors s ON s.id = r.sensor_id
            ORDER BY r.ts_utc DESC, r.id DESC
            LIMIT 1
            """
        ).fetchone()

    return conn.execute(
        """
        SELECT r.*, s.address, s.name
        FROM readings r
        JOIN sensors s ON s.id = r.sensor_id
        WHERE s.address = ?
        ORDER BY r.ts_utc DESC, r.id DESC
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
        "SELECT r.*, s.address, s.name",
        "FROM readings r",
        "JOIN sensors s ON s.id = r.sensor_id",
        "WHERE 1=1",
    ]
    params: list[object] = []

    if address is not None:
        query.append("AND s.address = ?")
        params.append(address)

    if since_utc is not None:
        query.append("AND r.ts_utc >= ?")
        params.append(since_utc)

    query.append("ORDER BY r.ts_utc ASC, r.id ASC")
    return conn.execute("\n".join(query), params).fetchall()
