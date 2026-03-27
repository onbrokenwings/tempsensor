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
* Timestamped records

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

## 📂 Project Structure

```text
trastero-monitor/
├── ble_reader.py        # BLE sensor reading logic
├── database.py          # SQLite helper functions
├── app.py               # Flask web server
├── data.db              # SQLite database (generated)
├── templates/
│   └── index.html       # Web UI
├── static/              # JS / CSS (optional)
├── requirements.txt
└── README.md
```

---

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

---

## 🔮 Future Improvements

* Multiple sensor support
* Alerts (e.g., high humidity)
* MQTT integration
* Home Assistant integration
* Alexa support (via HA)
* Data export (CSV/API)
* Advanced dashboards

---

## ⚠️ Limitations

* Designed for low-resource hardware (Pi Zero W)
* No cloud sync (by design)
* BLE range limitations

---

## 📜 License

MIT License (or define your own)

---

## 👨‍💻 Author

Personal project for learning and practical IoT deployment using low-power hardware.

