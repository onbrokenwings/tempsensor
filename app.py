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

from flask import Flask, jsonify, render_template_string, request

from db import connect, get_history, get_latest_reading, init_db


def parse_range(value: str) -> timedelta:
    value = (value or "24h").strip().lower()
    units = {"h": "hours", "d": "days"}

    if len(value) < 2:
        raise ValueError("Formato de rango inválido")

    amount = int(value[:-1])
    unit = value[-1]
    if unit not in units:
        raise ValueError("Unidad de rango inválida")

    return timedelta(**{units[unit]: amount})


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

        return render_template_string(
            """
            <!doctype html>
            <html lang="es">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>Trastero Monitor</title>
              <style>
                :root { color-scheme: light; }
                body { font-family: system-ui, sans-serif; margin: 0; background: #f5f3ef; color: #1f2937; }
                .wrap { max-width: 960px; margin: 0 auto; padding: 24px; }
                .hero { background: linear-gradient(135deg, #1f2937, #374151); color: white; padding: 24px; border-radius: 18px; }
                .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 16px; }
                .card { background: white; border-radius: 16px; padding: 16px; box-shadow: 0 8px 24px rgba(0,0,0,.06); }
                .value { font-size: 2rem; font-weight: 700; }
                .subvalue { color: #6b7280; font-size: 1rem; margin-top: 4px; }
                table { width: 100%; border-collapse: collapse; margin-top: 16px; background: white; border-radius: 16px; overflow: hidden; }
                th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid #e5e7eb; }
                th { background: #f9fafb; }
                .muted { color: #6b7280; }
              </style>
            </head>
            <body>
                <div class="wrap" data-poll-interval="5000">
                  <div class="hero">
                    <h1>Trastero Monitor</h1>
                    <p>Lectura local offline desde SQLite. Actualizando cada 5 s.</p>
                  </div>

                <div class="grid">
                  <div class="card">
                    <div class="muted">Temperatura actual</div>
                    <div class="value" id="current-temperature">{{ format_number(latest.temperature_c if latest else None, '°C') }}</div>
                  </div>
                  <div class="card">
                    <div class="muted">Humedad actual</div>
                    <div class="value" id="current-humidity">{{ format_number(latest.humidity_pct if latest else None, '%') }}</div>
                  </div>
                  <div class="card">
                    <div class="muted">Batería</div>
                    <div class="value" id="current-battery">{{ format_number(latest.battery_pct if latest else None, '%') }}</div>
                  </div>
                  <div class="card">
                    <div class="muted">Sensor</div>
                    <div class="value" id="current-sensor">{{ latest.name or latest.address if latest else '—' }}</div>
                    <div class="subvalue">MAC / nombre</div>
                  </div>
                  <div class="card">
                    <div class="muted">Fecha</div>
                    <div class="value" id="current-date">{{ latest.date if latest else '—' }}</div>
                    <div class="subvalue">Última lectura</div>
                  </div>
                  <div class="card">
                    <div class="muted">Hora</div>
                    <div class="value" id="current-time">{{ latest.time if latest else '—' }}</div>
                    <div class="subvalue">Hora local</div>
                  </div>
                </div>

                <h2>Últimas 24h</h2>
                <table>
                  <thead>
                    <tr><th>Fecha / hora local</th><th>Temp</th><th>Humedad</th><th>Muestras</th></tr>
                  </thead>
                  <tbody>
                    {% for row in history %}
                    <tr>
                      <td>{{ row.ts_local }}</td>
                      <td>{{ '%.2f'|format(row.temperature_c) if row.temperature_c is not none else '—' }}</td>
                      <td>{{ '%.2f'|format(row.humidity_pct) if row.humidity_pct is not none else '—' }}</td>
                      <td>{{ row.count }}</td>
                    </tr>
                    {% endfor %}
                  </tbody>
                </table>
              </div>
              <script>
                (() => {
                  const root = document.querySelector('.wrap');
                  const pollInterval = Number(root?.dataset.pollInterval || 5000);
                  const temperatureEl = document.getElementById('current-temperature');
                  const humidityEl = document.getElementById('current-humidity');
                  const batteryEl = document.getElementById('current-battery');
                  const sensorEl = document.getElementById('current-sensor');
                  const dateEl = document.getElementById('current-date');
                  const timeEl = document.getElementById('current-time');

                  const fmt = (value, suffix, digits = 2) => value === null || value === undefined ? '—' : `${Number(value).toFixed(digits)} ${suffix}`;

                  async function refreshLatest() {
                    try {
                      const response = await fetch('/api/latest', { cache: 'no-store' });
                      if (!response.ok) return;
                      const data = await response.json();
                      if (!data) {
                        temperatureEl.textContent = '—';
                        humidityEl.textContent = '—';
                        batteryEl.textContent = '—';
                        sensorEl.textContent = '—';
                        dateEl.textContent = '—';
                        timeEl.textContent = '—';
                        return;
                      }

                      temperatureEl.textContent = fmt(data.temperature_c, '°C');
                      humidityEl.textContent = fmt(data.humidity_pct, '%');
                      batteryEl.textContent = fmt(data.battery_pct, '%', 0);
                      sensorEl.textContent = data.name || data.address || '—';
                      dateEl.textContent = data.date || '—';
                      timeEl.textContent = data.time || '—';
                    } catch (error) {
                      console.error('Polling failed:', error);
                    }
                  }

                  refreshLatest();
                  setInterval(refreshLatest, pollInterval);
                })();
              </script>
            </body>
            </html>
            """,
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
                bucket = "raw"

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
