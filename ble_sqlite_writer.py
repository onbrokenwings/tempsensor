#!/usr/bin/env python3
"""BLE reader that persists readings into SQLite."""

from __future__ import annotations

import argparse
import asyncio
import configparser
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ble_common import Reading, SensorSnapshot, format_snapshot, normalize, read_snapshot
from db import connect, init_db, insert_reading


@dataclass
class PersistState:
    ts_utc: datetime | None = None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    battery_pct: float | None = None


@dataclass
class WriterConfig:
    db_path: str
    cache_path: str
    poll_interval: float
    save_interval: float
    temp_delta: float
    humidity_delta: float
    battery_delta: float
    address: str | None
    name: str | None
    mock_enabled: bool
    mock_seed: int
    mock_start_temp: float
    mock_start_humidity: float
    mock_start_battery: float
    mock_temp_jitter: float
    mock_humidity_jitter: float
    mock_battery_drain: float


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_bleak_runtime() -> tuple[Any, Any]:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "bleak no está instalado. Instala requirements.txt o usa --mock en un entorno con bleak disponible."
        ) from exc

    return BleakClient, BleakScanner


def load_writer_config(path: str) -> WriterConfig:
    parser = configparser.ConfigParser()
    parser.read(path)

    ble = parser["ble"] if parser.has_section("ble") else {}
    writer = parser["writer"] if parser.has_section("writer") else {}
    mock = parser["mock"] if parser.has_section("mock") else {}

    def get(section: Any, key: str, fallback: Any) -> Any:
        return section.get(key, fallback)

    return WriterConfig(
        db_path=get(writer, "db_path", "data/trastero.sqlite3"),
        cache_path=get(writer, "cache_path", "data/latest.json"),
        poll_interval=float(get(writer, "poll_interval", 10.0)),
        save_interval=float(get(writer, "save_interval", 300.0)),
        temp_delta=float(get(writer, "temp_delta", 0.3)),
        humidity_delta=float(get(writer, "humidity_delta", 2.0)),
        battery_delta=float(get(writer, "battery_delta", 1.0)),
        address=(get(ble, "address", "") or "").strip() or None,
        name=(get(ble, "name", "") or "").strip() or None,
        mock_enabled=str(get(mock, "enabled", "false")).strip().lower() in {"1", "true", "yes", "on"},
        mock_seed=int(get(mock, "seed", 1234)),
        mock_start_temp=float(get(mock, "start_temp", 21.5)),
        mock_start_humidity=float(get(mock, "start_humidity", 48.0)),
        mock_start_battery=float(get(mock, "start_battery", 100.0)),
        mock_temp_jitter=float(get(mock, "temp_jitter", 0.08)),
        mock_humidity_jitter=float(get(mock, "humidity_jitter", 0.35)),
        mock_battery_drain=float(get(mock, "battery_drain", 0.01)),
    )


def to_temp_raw(value: float) -> bytes:
    return int(round(value * 10)).to_bytes(2, byteorder="little", signed=True)


def to_humidity_raw(value: float) -> bytes:
    return int(round(value * 100)).to_bytes(2, byteorder="little", signed=False)


def to_battery_raw(value: float) -> bytes:
    return bytes([max(0, min(100, int(round(value))))])


def snapshot_payload(
    *,
    ts_utc: datetime,
    address: str,
    name: str | None,
    snapshot: SensorSnapshot,
) -> dict[str, Any]:
    local = ts_utc.astimezone()
    return {
        "ts_utc": ts_utc.isoformat(timespec="seconds"),
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M:%S"),
        "address": address,
        "name": name,
        "temperature_c": snapshot.temperature.value,
        "humidity_pct": snapshot.humidity.value,
        "battery_pct": snapshot.battery.value,
    }


def write_latest_cache(cache_path: str, payload: dict[str, Any]) -> None:
    path = Path(cache_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        print(f"Aviso: no se pudo escribir la caché en RAM ({cache_path}): {exc}")


def save_snapshot(
    conn,
    *,
    address: str,
    name: str | None,
    ts_utc: datetime,
    snapshot: SensorSnapshot,
) -> None:
    insert_reading(
        conn,
        address=address,
        name=name,
        ts_utc=ts_utc.isoformat(timespec="seconds"),
        temperature_c=snapshot.temperature.value,
        humidity_pct=snapshot.humidity.value,
        battery_pct=snapshot.battery.value,
    )


class MockSensor:
    def __init__(self, seed: int, temp: float, humidity: float, battery: float, temp_jitter: float, humidity_jitter: float, battery_drain: float) -> None:
        self._rng = random.Random(seed)
        self.temperature = temp
        self.humidity = humidity
        self.battery = battery
        self.temp_jitter = temp_jitter
        self.humidity_jitter = humidity_jitter
        self.battery_drain = battery_drain

    def snapshot(self) -> SensorSnapshot:
        self.temperature = max(-10.0, min(50.0, self.temperature + self._rng.uniform(-self.temp_jitter, self.temp_jitter)))
        self.humidity = max(0.0, min(100.0, self.humidity + self._rng.uniform(-self.humidity_jitter, self.humidity_jitter)))
        self.battery = max(0.0, self.battery - self._rng.uniform(0.0, self.battery_drain))

        temperature = Reading(name="temperature", value=round(self.temperature, 2), raw=to_temp_raw(self.temperature), unit="°C")
        humidity = Reading(name="humidity", value=round(self.humidity, 2), raw=to_humidity_raw(self.humidity), unit="%")
        battery = Reading(name="battery", value=round(self.battery, 0), raw=to_battery_raw(self.battery), unit="%")
        return SensorSnapshot(temperature=temperature, humidity=humidity, battery=battery)


def should_persist(
    current: PersistState,
    previous: PersistState | None,
    *,
    save_interval_s: float,
    temp_delta: float,
    humidity_delta: float,
    battery_delta: float,
) -> bool:
    if previous is None or previous.ts_utc is None:
        return True

    elapsed = (current.ts_utc - previous.ts_utc).total_seconds()
    if elapsed >= save_interval_s:
        return True

    if current.temperature_c is not None and previous.temperature_c is not None:
        if abs(current.temperature_c - previous.temperature_c) >= temp_delta:
            return True

    if current.humidity_pct is not None and previous.humidity_pct is not None:
        if abs(current.humidity_pct - previous.humidity_pct) >= humidity_delta:
            return True

    if current.battery_pct is not None and previous.battery_pct is not None:
        if abs(current.battery_pct - previous.battery_pct) >= battery_delta:
            return True

    return False


async def persist_sensor(address_or_device: object, config: WriterConfig) -> None:
    db_path = config.db_path
    init_db(db_path)
    BleakClient, _BleakScanner = load_bleak_runtime()

    last_saved: PersistState | None = None

    async with BleakClient(address_or_device) as client:
        print("\nConectado. Leyendo y guardando valores...\n")
        while True:
            try:
                snapshot = await read_snapshot(client)
                now = utc_now()
                current = PersistState(
                    ts_utc=now,
                    temperature_c=snapshot.temperature.value,
                    humidity_pct=snapshot.humidity.value,
                    battery_pct=snapshot.battery.value,
                )

                print(format_snapshot(snapshot))
                write_latest_cache(
                    config.cache_path,
                    snapshot_payload(
                        ts_utc=now,
                        address=getattr(address_or_device, "address", str(address_or_device)),
                        name=getattr(address_or_device, "name", None),
                        snapshot=snapshot,
                    ),
                )

                if should_persist(
                    current,
                    last_saved,
                    save_interval_s=config.save_interval,
                    temp_delta=config.temp_delta,
                    humidity_delta=config.humidity_delta,
                    battery_delta=config.battery_delta,
                ):
                    with connect(db_path) as conn:
                        insert_reading(
                            conn,
                            address=getattr(address_or_device, "address", str(address_or_device)),
                            name=getattr(address_or_device, "name", None),
                            ts_utc=now.isoformat(timespec="seconds"),
                            temperature_c=current.temperature_c,
                            humidity_pct=current.humidity_pct,
                            battery_pct=current.battery_pct,
                        )
                        conn.commit()
                    last_saved = current
                    print("Guardado en SQLite.")

            except Exception as exc:  # noqa: BLE001
                print(f"Error leyendo o guardando el sensor: {exc}")
                break

            await asyncio.sleep(config.poll_interval)


async def persist_mock_sensor(config: WriterConfig, mock_count: int | None = None) -> None:
    db_path = config.db_path
    init_db(db_path)
    mock = MockSensor(
        seed=config.mock_seed,
        temp=config.mock_start_temp,
        humidity=config.mock_start_humidity,
        battery=config.mock_start_battery,
        temp_jitter=config.mock_temp_jitter,
        humidity_jitter=config.mock_humidity_jitter,
        battery_drain=config.mock_battery_drain,
    )
    last_saved: PersistState | None = None
    address = config.address or "MOCK:00:00:00:00"
    name = config.name or "mock-sensor"

    print("\nModo mock activo. Generando lecturas sintéticas...\n")
    produced = 0
    while True:
        snapshot = mock.snapshot()
        now = utc_now()
        current = PersistState(
            ts_utc=now,
            temperature_c=snapshot.temperature.value,
            humidity_pct=snapshot.humidity.value,
            battery_pct=snapshot.battery.value,
        )

        print(format_snapshot(snapshot))
        write_latest_cache(
            config.cache_path,
            snapshot_payload(ts_utc=now, address=address, name=name, snapshot=snapshot),
        )

        if should_persist(
            current,
            last_saved,
            save_interval_s=config.save_interval,
            temp_delta=config.temp_delta,
            humidity_delta=config.humidity_delta,
            battery_delta=config.battery_delta,
        ):
            with connect(db_path) as conn:
                insert_reading(
                    conn,
                    address=address,
                    name=name,
                    ts_utc=now.isoformat(timespec="seconds"),
                    temperature_c=current.temperature_c,
                    humidity_pct=current.humidity_pct,
                    battery_pct=current.battery_pct,
                )
                conn.commit()
            last_saved = current
            print("Guardado en SQLite.")

        produced += 1
        if mock_count is not None and produced >= mock_count:
            print(f"Mock finalizado tras {produced} muestras.")
            return

        await asyncio.sleep(config.poll_interval)


async def seed_mock_history(
    config: WriterConfig,
    *,
    sample_count: int,
    duration_hours: float,
) -> None:
    if sample_count < 2:
        raise ValueError("sample_count debe ser mayor o igual que 2")
    if duration_hours <= 0:
        raise ValueError("duration_hours debe ser mayor que 0")

    db_path = config.db_path
    init_db(db_path)
    mock = MockSensor(
        seed=config.mock_seed,
        temp=config.mock_start_temp,
        humidity=config.mock_start_humidity,
        battery=config.mock_start_battery,
        temp_jitter=config.mock_temp_jitter,
        humidity_jitter=config.mock_humidity_jitter,
        battery_drain=config.mock_battery_drain,
    )
    address = config.address or "MOCK:00:00:00:00"
    name = config.name or "mock-sensor"

    start_ts = utc_now() - timedelta(hours=duration_hours)
    step = timedelta(seconds=(duration_hours * 3600.0) / (sample_count - 1))

    print(f"\nSembrando histórico sintético: {sample_count} muestras en {duration_hours:g}h...\n")
    last_payload: dict[str, Any] | None = None

    with connect(db_path) as conn:
        for index in range(sample_count):
            snapshot = mock.snapshot()
            ts_utc = start_ts + (step * index)
            save_snapshot(
                conn,
                address=address,
                name=name,
                ts_utc=ts_utc,
                snapshot=snapshot,
            )
            last_payload = snapshot_payload(ts_utc=ts_utc, address=address, name=name, snapshot=snapshot)

        conn.commit()

    if last_payload is not None:
        write_latest_cache(config.cache_path, last_payload)

    print("Seed histórico completado.")


async def resolve_ble_target(config: WriterConfig, scan_timeout: float) -> object:
    _, BleakScanner = load_bleak_runtime()

    if config.address:
        return config.address

    if not config.name:
        raise RuntimeError("Falta [ble] address o name en config.ini.")

    devices = await BleakScanner.discover(timeout=scan_timeout)
    normalized_target = normalize(config.name)
    matches = [device for device in devices if normalize(device.name or "") == normalized_target]

    if not matches:
        raise RuntimeError(f"No se encontró un dispositivo BLE con nombre '{config.name}'.")
    if len(matches) > 1:
        raise RuntimeError(f"Hay varios dispositivos BLE con nombre '{config.name}'. Usa la MAC en config.ini.")
    return matches[0]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Writer BLE para guardar lecturas en SQLite.")
    parser.add_argument("--config", default="config.ini", help="Ruta del fichero de configuración.")
    parser.add_argument("--db-path", default=None, help="Sobrescribe la ruta de la base de datos SQLite.")
    parser.add_argument("--cache-path", default=None, help="Sobrescribe la ruta de la caché live JSON.")
    parser.add_argument("--scan-timeout", type=float, default=8.0, help="Segundos de escaneo BLE.")
    parser.add_argument("--poll-interval", type=float, default=None, help="Sobrescribe los segundos entre lecturas BLE.")
    parser.add_argument("--save-interval", type=float, default=None, help="Sobrescribe los segundos máximos entre guardados.")
    parser.add_argument("--temp-delta", type=float, default=None, help="Sobrescribe el delta mínimo de temperatura para guardar.")
    parser.add_argument("--humidity-delta", type=float, default=None, help="Sobrescribe el delta mínimo de humedad para guardar.")
    parser.add_argument("--battery-delta", type=float, default=None, help="Sobrescribe el delta mínimo de batería para guardar.")
    parser.add_argument("--mock", action="store_true", help="Ejecuta el writer con datos sintéticos.")
    parser.add_argument("--mock-count", type=int, default=None, help="Número de muestras mock a generar y detenerse.")
    parser.add_argument("--seed-history", action="store_true", help="Carga un histórico sintético en SQLite y sale.")
    parser.add_argument("--seed-history-count", type=int, default=288, help="Número de muestras a insertar al sembrar histórico.")
    parser.add_argument("--seed-history-hours", type=float, default=48.0, help="Ventana temporal total del histórico a sembrar.")
    args = parser.parse_args()

    config = load_writer_config(args.config)
    if args.db_path is not None:
        config.db_path = args.db_path
    if args.cache_path is not None:
        config.cache_path = args.cache_path
    if args.poll_interval is not None:
        config.poll_interval = args.poll_interval
    if args.save_interval is not None:
        config.save_interval = args.save_interval
    if args.temp_delta is not None:
        config.temp_delta = args.temp_delta
    if args.humidity_delta is not None:
        config.humidity_delta = args.humidity_delta
    if args.battery_delta is not None:
        config.battery_delta = args.battery_delta
    config.mock_enabled = config.mock_enabled or args.mock

    try:
        if args.seed_history:
            await seed_mock_history(
                config,
                sample_count=args.seed_history_count,
                duration_hours=args.seed_history_hours,
            )
            return

        if config.mock_enabled:
            await persist_mock_sensor(config, args.mock_count)
            return

        target = await resolve_ble_target(config, args.scan_timeout)
        await persist_sensor(target, config)
    except KeyboardInterrupt:
        print("\nSaliendo.")
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo conectar, leer o persistir el sensor: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
