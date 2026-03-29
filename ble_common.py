#!/usr/bin/env python3
"""Shared BLE helpers for Xiaomi temperature sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


TEMP_UUIDS = [
    "00002a1f-0000-1000-8000-00805f9b34fb",
    "00002a6e-0000-1000-8000-00805f9b34fb",
]
HUMIDITY_UUID = "00002a6f-0000-1000-8000-00805f9b34fb"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


@dataclass
class Reading:
    name: str
    value: Optional[float]
    raw: bytes
    unit: str


@dataclass
class SensorSnapshot:
    temperature: Reading
    humidity: Reading
    battery: Reading


def normalize(text: str) -> str:
    return text.strip().lower()


def format_raw(data: bytes) -> str:
    return " ".join(f"{byte:02x}" for byte in data)


def format_value(reading: Reading) -> str:
    if reading.value is None:
        return f"N/A (raw: {format_raw(reading.raw)})"
    if reading.name == "battery":
        return f"{reading.value:.0f} {reading.unit} (raw: {format_raw(reading.raw)})"
    return f"{reading.value:.2f} {reading.unit} (raw: {format_raw(reading.raw)})"


def parse_fixed_point(data: bytes, signed: bool, scale: float) -> Optional[float]:
    if len(data) < 2:
        return None
    raw = int.from_bytes(data[:2], byteorder="little", signed=signed)
    return raw / scale


async def discover_devices(timeout: float) -> list:
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError("bleak no está instalado.") from exc

    print(f"Buscando dispositivos BLE durante {timeout:.0f} segundos...\n")
    devices = await BleakScanner.discover(timeout=timeout)
    if not devices:
        print("No se encontraron dispositivos BLE.")
        return []

    for idx, device in enumerate(devices, start=1):
        name = device.name or "<sin nombre>"
        rssi = getattr(device, "rssi", None)
        rssi_text = f" | RSSI {rssi}" if rssi is not None else ""
        print(f"[{idx}] {name} | {device.address}{rssi_text}")

    return devices


def choose_device(devices: list) -> Optional[object]:
    while True:
        answer = input(
            "\nElige un dispositivo por número, pega la MAC/nombre, o escribe 'r' para reescanear: "
        ).strip()

        if not answer:
            continue

        if answer.lower() == "r":
            return None

        if answer.isdigit():
            index = int(answer) - 1
            if 0 <= index < len(devices):
                return devices[index]
            print("Número fuera de rango.")
            continue

        normalized_answer = normalize(answer)
        matches = [
            device
            for device in devices
            if normalize(device.address) == normalized_answer
            or normalize(device.name or "") == normalized_answer
            or normalized_answer in normalize(device.address)
            or (device.name and normalized_answer in normalize(device.name))
        ]

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print("Hay varias coincidencias. Usa el número de la lista o la MAC completa.")
            continue

        print("No encontré coincidencias. Prueba otra vez o reescanea.")


async def read_value(client: object, uuid: str, name: str, unit: str, signed: bool) -> Reading:
    data = await client.read_gatt_char(uuid)
    if name == "temperature":
        value = parse_fixed_point(data, signed=signed, scale=10.0)
    elif name == "humidity":
        value = parse_fixed_point(data, signed=False, scale=100.0)
    elif name == "battery":
        value = float(data[0]) if data else None
    else:
        value = None
    return Reading(name=name, value=value, raw=data, unit=unit)


async def read_first_available(client: object, uuids: list[str], name: str, unit: str, signed: bool) -> Reading:
    last_error: Exception | None = None

    for uuid in uuids:
        try:
            return await read_value(client, uuid, name, unit, signed)
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    assert last_error is not None
    raise last_error


async def read_snapshot(client: object) -> SensorSnapshot:
    temperature = await read_first_available(client, TEMP_UUIDS, "temperature", "°C", signed=True)
    humidity = await read_value(client, HUMIDITY_UUID, "humidity", "%", signed=False)
    battery = await read_value(client, BATTERY_UUID, "battery", "%", signed=False)
    return SensorSnapshot(temperature=temperature, humidity=humidity, battery=battery)


def format_snapshot(snapshot: SensorSnapshot) -> str:
    return (
        f"Temperatura: {format_value(snapshot.temperature)} | "
        f"Humedad: {format_value(snapshot.humidity)} | "
        f"Batería: {format_value(snapshot.battery)}"
    )
