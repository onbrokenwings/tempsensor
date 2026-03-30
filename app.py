#!/usr/bin/env python3
"""Local Flask app for current and historical sensor readings."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from db import connect, get_history, get_latest_reading, init_db


def parse_range(value: str) -> timedelta:
    value = (value or "24h").strip().lower()
    if len(value) < 2:
        raise ValueError("Formato de rango inválido")

    amount = int(value[:-1])
    unit = value[-1]
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "m":
        return timedelta(days=30 * amount)

    raise ValueError("Unidad de rango inválida")


def to_iso(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("Z", "+00:00")


def row_to_dict(row) -> dict:
    ts_utc = row["ts_utc"]
    dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
    local = dt.astimezone()
    return {
        "id": row["id"],
        "address": row["address"],
        "name": row["name"],
        "ts_utc": ts_utc,
        "ts_local": local.strftime("%Y-%m-%d %H:%M"),
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M:%S"),
        "temperature_c": row["temperature_c"],
        "humidity_pct": row["humidity_pct"],
        "battery_pct": row["battery_pct"],
    }


def format_number(value, suffix: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f} {suffix}"
    return f"{value} {suffix}"


def load_latest_cache(cache_path: str) -> dict | None:
    path = Path(cache_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_payload_from_row(row) -> dict | None:
    return row_to_dict(row) if row is not None else None


def bucket_start(ts: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        week_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return week_start - timedelta(days=week_start.weekday())
    return ts


def aggregate_rows(rows: list, bucket: str) -> list[dict]:
    grouped: dict[tuple[str, str], list] = defaultdict(list)

    for row in rows:
        ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
        bucket_ts = bucket_start(ts, bucket)
        grouped[(row["address"], bucket_ts.isoformat())].append(row)

    output: list[dict] = []
    for (address, bucket_ts_iso), bucket_rows in sorted(grouped.items(), key=lambda item: item[0][1]):
        temperatures = [r["temperature_c"] for r in bucket_rows if r["temperature_c"] is not None]
        humidities = [r["humidity_pct"] for r in bucket_rows if r["humidity_pct"] is not None]
        last = bucket_rows[-1]
        bucket_ts = datetime.fromisoformat(bucket_ts_iso).astimezone()
        output.append(
            {
                "address": address,
                "name": last["name"],
                "ts_local": bucket_ts.strftime("%Y-%m-%d %H:%M"),
                "count": len(bucket_rows),
                "temperature_c": mean(temperatures) if temperatures else None,
                "humidity_pct": mean(humidities) if humidities else None,
                "battery_pct": last["battery_pct"],
            }
        )

    return output


def create_app(db_path: str, cache_path: str) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        latest = None
        history = []
        with connect(db_path) as conn:
            latest_row = get_latest_reading(conn)
            latest = load_latest_cache(cache_path) or latest_payload_from_row(latest_row)
            rows = get_history(conn, since_utc=(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat())
            history = aggregate_rows(rows, "hour")

        return render_template(
            "index.html",
            latest=latest,
            history=history,
            format_number=format_number,
        )

    @app.get("/api/latest")
    def api_latest():
        address = request.args.get("address")
        cache = load_latest_cache(cache_path)
        if cache is not None and (address is None or cache.get("address") == address):
            return jsonify(cache)

        with connect(db_path) as conn:
            row = get_latest_reading(conn, address=address)
        return jsonify(row_to_dict(row) if row is not None else None)

    @app.get("/api/history")
    def api_history():
        address = request.args.get("address")
        range_value = request.args.get("range", "24h")
        bucket = request.args.get("bucket")

        try:
            delta = parse_range(range_value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        since_utc = (datetime.now(timezone.utc) - delta).isoformat()
        with connect(db_path) as conn:
            rows = get_history(conn, address=address, since_utc=since_utc)

        if bucket is None:
            if delta >= timedelta(days=14):
                bucket = "day"
            elif delta >= timedelta(days=2):
                bucket = "hour"
            else:
                bucket = "hour"

        if bucket == "raw":
            payload = [row_to_dict(row) for row in rows]
        else:
            payload = aggregate_rows(rows, bucket)

        return jsonify(payload)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Flask API local para el monitor del trastero.")
    parser.add_argument("--db-path", default=os.getenv("TRASTERO_DB", "data/trastero.sqlite3"))
    parser.add_argument("--cache-path", default=os.getenv("TRASTERO_LATEST", "data/latest.json"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app(args.db_path, args.cache_path)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
