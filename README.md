# 📦 Trastero Monitor (Raspberry Pi Zero W + BLE)

## 📖 Overview

This project implements a lightweight, fully offline environmental monitoring system using a Raspberry Pi Zero W and Bluetooth Low Energy (BLE) sensors.

The system collects temperature, humidity, and battery data from Xiaomi LYWSD03MMC sensors, stores it locally, and exposes a web interface accessible via a local WiFi network created by the Raspberry Pi.

No internet connection or cloud services are required.

---

## 🎯 Goals

* Monitor **temperature, humidity, and battery level** using BLE sensors
* Store historical data locally using SQLite
* Provide a **web interface** accessible from a mobile device
* Operate **fully offline**
* Keep the system lightweight and suitable for a Raspberry Pi Zero W

---

## 🧠 Architecture

```text
BLE Sensor (Xiaomi LYWSD03MMC)
            ↓
   Raspberry Pi Zero W
            ↓
      BLE Reader (Python)
            ↓
        SQLite Database
            ↓
        Flask Web Server
            ↓
      WiFi Access Point (AP)
            ↓
       Mobile Browser Access
```

---

## 🧰 Tech Stack

* **Hardware**

  * Raspberry Pi Zero W
  * Xiaomi LYWSD03MMC BLE sensors
* **Software**

  * Python 3
  * Flask (web server)
  * Bleak (BLE communication)
  * SQLite (data persistence)
* **OS**

  * Raspberry Pi OS Lite

---

## 🚀 Features

### 📡 Data Acquisition

* Passive BLE scanning
* Reads:

  * Temperature
  * Humidity
  * Battery level

### 💾 Data Storage

* Local SQLite database
* Minimal schema with a single `readings` table
* Each row stores timestamp, sensor MAC, sensor name, temperature, humidity and battery

### 🌐 Web Interface

* Lightweight Flask server
* Accessible via browser (mobile/desktop)
* Displays:

  * Latest readings
  * Historical data

### 📊 Data Visualization

* Time-series charts (Chart.js)
* Date range filtering

### 📶 Offline Connectivity

* Raspberry Pi acts as a **WiFi Access Point**
* Direct connection from mobile device
* No internet required

---

## ▶️ Quick BLE Validation

Run the interactive reader to scan nearby devices and choose the sensor from the console:

```bash
pip3 install -r requirements.txt
python3 ble_reader.py
```

It will try to read temperature, humidity, and battery every few seconds.

## ⚙️ Runtime Configuration

For the deployed writer, copy `config.ini.example` to `config.ini` and set the BLE device MAC or name there.

Use `ble_sqlite_writer.py --mock` to generate synthetic readings and test SQLite plus the web app without the physical sensor.
Add `--mock-count 100` if you want the mock to stop after a finite number of samples.
Use `python3 ble_sqlite_writer.py --mock --mock-count 288` to fill the DB with recent synthetic samples, or `--seed-history --seed-history-count 288 --seed-history-hours 48` to preload a historical baseline in one shot.

The writer stores the latest live reading in `data/latest.json` by default so the dashboard can refresh without waiting for the next SQLite insert.
The SQLite DB is intentionally simple: a single `readings` table stores timestamp, address, name, temperature, humidity and battery.
If you deploy on a device with a different cache location, pass `--cache-path /run/trastero/latest.json` or set it in `config.ini`.
If the BLE sensor is unavailable, the writer keeps running and retries connection every `retry_interval` seconds (default `300`).

## 🚀 Deploy Writer on Raspberry Pi Zero W

### 1. Copy the project to `/opt/trastero`

```bash
sudo mkdir -p /opt/trastero
sudo chown -R admin:admin /opt/trastero
cp -a ~/TempLocalSensor/. /opt/trastero/
```

### 2. Create the virtual environment

```bash
cd /opt/trastero
python3 -m venv venv
/opt/trastero/venv/bin/pip install -r /opt/trastero/requirements.txt
```

### 3. Configure the writer

Edit `/opt/trastero/config.ini` and set at least:

- `ble.address` or `ble.name`
- `writer.db_path`
- `writer.cache_path`
- `writer.poll_interval`
- `writer.retry_interval`
- `writer.save_interval`

Example:

```ini
[ble]
address = A4:C1:38:5E:2D:4D

[writer]
db_path = data/trastero.sqlite3
cache_path = data/latest.json
poll_interval = 10
retry_interval = 300
save_interval = 300
```

### 4. Test it manually

```bash
cd /opt/trastero
/opt/trastero/venv/bin/python ble_sqlite_writer.py --config /opt/trastero/config.ini
```

Expected behavior:

- connects to the BLE sensor
- prints temperature, humidity, and battery readings
- writes `data/latest.json`
- writes rows to `data/trastero.sqlite3`

### 5. Create the systemd service

Create `/etc/systemd/system/trastero-writer.service`:

```ini
[Unit]
Description=Trastero BLE Writer
After=bluetooth.service network.target
Wants=bluetooth.service

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/opt/trastero
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/trastero/venv/bin/python /opt/trastero/ble_sqlite_writer.py --config /opt/trastero/config.ini
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
```

### 6. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable trastero-writer
sudo systemctl start trastero-writer
```

### 7. Check status and logs

```bash
systemctl status trastero-writer
journalctl -u trastero-writer -f
```

### 8. Stop the service safely

```bash
sudo systemctl stop trastero-writer
```

### 9. Verify BLE recovery

- Turn the sensor off or remove the battery.
- Confirm the writer logs BLE errors and retries every `retry_interval` seconds.
- Put the battery back or power the sensor again.
- Confirm the writer reconnects automatically and resumes writing.

### 10. Quick checks

```bash
ls -l /opt/trastero/data
python3 -c "import sqlite3; conn=sqlite3.connect('/opt/trastero/data/trastero.sqlite3'); print(conn.execute('select count(*) from readings').fetchone()[0])"
cat /opt/trastero/data/latest.json
```

## 🌐 Deploy Front on Raspberry Pi Zero W

The web front reuses the same `venv` and reads the same SQLite DB and `latest.json` as the writer.

### 1. Create the systemd service

```bash
sudo nano /etc/systemd/system/trastero-web.service
```

Paste this content:

```ini
[Unit]
Description=Trastero Web Flask
After=network.target trastero-writer.service
Wants=trastero-writer.service

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/opt/trastero
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/trastero/venv/bin/python /opt/trastero/app.py --db-path /opt/trastero/data/trastero.sqlite3 --cache-path /opt/trastero/data/latest.json --host 0.0.0.0 --port 5000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Reload systemd and enable the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable trastero-web
sudo systemctl start trastero-web
```

### 3. Check status and logs

```bash
systemctl status trastero-web
journalctl -u trastero-web -f
```

### 4. Access the front

Open this URL from a browser:

```text
http://IP_DE_LA_PI:5000
```

### 5. Stop the service safely

```bash
sudo systemctl stop trastero-web
```

## ⚙️ Setup

### 1. Install OS

* Flash Raspberry Pi OS Lite
* Enable SSH
* Connect to the device

### 2. Install dependencies

```bash
sudo apt update
sudo apt install python3-pip bluetooth bluez
pip3 install -r requirements.txt
```

---

### 3. Verify BLE

```bash
bluetoothctl
scan on
```

Ensure your sensor is detected (e.g., `ATC_xxxxxx`).

---

### 4. Run BLE reader

```bash
python3 ble_reader.py
```

---

### 5. Run web server

```bash
python3 app.py
```

Access:

```
http://<raspberry-ip>:5000
```

The dashboard auto-refreshes the latest reading every 5 seconds.

---

## 📡 WiFi Access Point (Offline Mode)

The Raspberry Pi can be configured as a WiFi Access Point:

* SSID: `TrasteroMonitor`
* Default IP: `192.168.4.1`

Then access:

```
http://192.168.4.1:5000
```

---

## 🔄 Data Flow

```text
BLE broadcast → BLE reader → SQLite → Flask API → Browser UI
```

---

## 🧪 Development Strategy

Recommended approach:

1. Implement BLE reading (console output)
2. Store data in SQLite
3. Build Flask API
4. Add web interface
5. Configure WiFi AP
6. Add charts and filtering

---

## 🔧 Configuration Notes

* Recommended BLE advertising interval: **5–10 seconds**
* Ensure stable power supply for Raspberry Pi
* Use firmware (ATC/pvvx) on sensor for easier BLE parsing
