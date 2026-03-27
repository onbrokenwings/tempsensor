#!/usr/bin/env python3
"""Interactive BLE validator for Xiaomi temperature sensors.

Scans nearby BLE devices, lets the user pick one, then tries to read
temperature, humidity, and battery from standard GATT characteristics.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Iterable, Optional

from bleak import BleakClient, BleakScanner


TEMP_UUID = "00002a6e-0000-1000-8000-00805f9b34fb"
HUMIDITY_UUID = "00002a6f-0000-1000-8000-00805f9b34fb"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


@dataclass
class Reading:
    name: str
    value: Optional[float]
    raw: bytes
    unit: str


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
            print("Hay varios coincidencias. Usa el número de la lista o la MAC completa.")
            continue

        print("No encontré coincidencias. Prueba otra vez o reescanea.")


async def read_value(client: BleakClient, uuid: str, name: str, unit: str, signed: bool) -> Reading:
    data = await client.read_gatt_char(uuid)
    if name == "temperature":
        value = parse_fixed_point(data, signed=signed, scale=100.0)
    elif name == "humidity":
        value = parse_fixed_point(data, signed=False, scale=100.0)
    elif name == "battery":
        value = float(data[0]) if data else None
    else:
        value = None
    return Reading(name=name, value=value, raw=data, unit=unit)


async def read_sensor(address_or_device: object, interval: float) -> None:
    async with BleakClient(address_or_device) as client:
        print("\nConectado. Leyendo valores...\n")
        while True:
            try:
                temp = await read_value(client, TEMP_UUID, "temperature", "°C", signed=True)
                humidity = await read_value(client, HUMIDITY_UUID, "humidity", "%", signed=False)
                battery = await read_value(client, BATTERY_UUID, "battery", "%", signed=False)

                print(
                    f"Temperatura: {format_value(temp)} | "
                    f"Humedad: {format_value(humidity)} | "
                    f"Batería: {format_value(battery)}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Error leyendo el sensor: {exc}")
                break

            await asyncio.sleep(interval)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Validador BLE interactivo para el sensor.")
    parser.add_argument("--scan-timeout", type=float, default=8.0, help="Segundos de escaneo BLE.")
    parser.add_argument("--interval", type=float, default=10.0, help="Segundos entre lecturas.")
    args = parser.parse_args()

    while True:
        devices = await discover_devices(args.scan_timeout)
        if not devices:
            retry = input("Pulsa Enter para volver a escanear o escribe 'q' para salir: ").strip().lower()
            if retry == "q":
                return
            continue

        selected = choose_device(devices)
        if selected is None:
            continue

        try:
            await read_sensor(selected, args.interval)
        except KeyboardInterrupt:
            print("\nSaliendo.")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"No se pudo conectar o leer el sensor: {exc}")

        retry = input("\nPulsa Enter para reintentar o escribe 'q' para salir: ").strip().lower()
        if retry == "q":
            return


if __name__ == "__main__":
    asyncio.run(main())
