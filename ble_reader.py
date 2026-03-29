#!/usr/bin/env python3
"""Interactive BLE validator for Xiaomi temperature sensors.

Scans nearby BLE devices, lets the user pick one, then tries to read
temperature, humidity, and battery from standard GATT characteristics.
"""

from __future__ import annotations

import argparse
import asyncio

from bleak import BleakClient

from ble_common import choose_device, discover_devices, format_snapshot, read_snapshot


async def read_sensor(address_or_device: object, interval: float) -> None:
    async with BleakClient(address_or_device) as client:
        print("\nConectado. Leyendo valores...\n")
        while True:
            try:
                snapshot = await read_snapshot(client)
                print(format_snapshot(snapshot))
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
