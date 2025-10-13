# NUT-UDP-Event-Bridge

A lightweight **Python wrapper for Network UPS Tools (NUT)** that forwards UPS status data via UDP in flat JSON format.

This project serves as a simple way to integrate UPS information into systems like **Loxone**, **Node-RED**, or any other UDP-capable receiver.

---

## 🧩 Overview

```
[NUT Server / NAS]  →  [NUT-UDP-Event-Bridge]  →  UDP →  [Receiver (e.g. Loxone)]
```

The script queries a remote NUT UPS instance (`upsc`) or reads from a local sample file (for development on macOS) and transmits JSON data at regular intervals.

A matching Loxone UDP template (`VIU_NUT-UDP-Event-Bridge.xml`) is included for easy integration.

---

## ⚙️ Configuration

All settings are defined in `config.json`:

```json
{
  "udp_receiver_ip": "<YOUR UDP RECEIVER / MINISERVER IP>",
  "udp_receiver_port": 9999,
  "nut_target": "qnapups@<YOUR UPS NUT MASTER IP>",
  "intervall_ol": 10,
  "dev_sample_file": "examples/sample_upsc.txt",
  "hostname_override": "",
  "log_level": "DEBUG",
  "upsc_timeout_sec": 10
}
```

### Key Parameters

| Field | Description |
|-------|--------------|
| `udp_receiver_ip` | Target IP address of the UDP receiver (e.g. Loxone Miniserver) |
| `udp_receiver_port` | UDP port number for transmission |
| `nut_target` | Address of your NUT UPS (e.g. `qnapups@192.168.1.10`) |
| `intervall_ol` | Query interval in seconds while UPS is online |
| `dev_sample_file` | Sample file for macOS testing (no real UPS access) |
| `hostname_override` | Optional fixed hostname in JSON output |
| `log_level` | Logging verbosity (`DEBUG`, `INFO`, etc.) |
| `upsc_timeout_sec` | Timeout in seconds for each NUT query |

---

## 🖥️ Usage

### Install Dependencies
```bash
sudo apt install nut-client
pip3 install aiohttp
```

### Start the Bridge
```bash
python3 nut_udp_bridge.py -c config.json
```

The script will send periodic UDP JSON packets to the defined receiver.

---

## 🧪 Example JSON Output

```json
{
  "source": "ups",
  "timestamp": 1752740234,
  "host": "loxberry",
  "alive": 1,
  "ups_status": 1,
  "status_raw": "Online",
  "battery_percent": 100,
  "runtime_total_sec": 1430,
  "runtime_total_min": 24,
  "runtime_min": 23,
  "runtime_sec": 50,
  "load_percent": 18,
  "input_voltage": 226.0,
  "battery_charging": 1
}
```

---

## 🧠 Data Fields

| Field | Description |
|-------|--------------|
| `alive` | 1 if bridge and NUT communication OK, 0 if connection or script stopped |
| `timestamp` | UNIX timestamp of the reading |
| `ups_status` | 1 Online, 2 On battery, 3 Low battery, 4 Replace battery, 5 Overload, 6 Forced shutdown, 9 Unknown |
| `status_raw` | Full UPS status text |
| `battery_percent` | Battery charge percentage |
| `runtime_total_sec` | Total runtime in seconds |
| `runtime_total_min` | Total runtime rounded up to minutes |
| `runtime_min` | Whole minutes portion of runtime |
| `runtime_sec` | Remaining seconds portion of runtime |
| `load_percent` | Current UPS load percentage |
| `input_voltage` | Current mains voltage |
| `battery_charging` | 1 if charging, 0 if discharging |

---

## 📡 Loxone Integration

Import `VIU_NUT-UDP-Event-Bridge.xml` into **Loxone Config** as a UDP Virtual Input template.

1. Open **Loxone Config** → *Periphery* → *Virtual Inputs*  
2. Create a new **Virtual UDP Input**  
   - **Sender IP:** IP address of the system running the bridge  
   - **Port:** UDP port configured for your camera in `config.json`
3. Add a new **Virtual Input Command**  
   Example command:  
   ```text
   \i"alive":\i\v
   
[📄 Example File (Loxone Config Import UDP Device)](./examples/VIU_NUT-UDP-Event-Bridge.xml)


---

## 📜 License & Credits

- This bridge is provided “as is” for personal/non‑commercial use. No warranty or affiliation with NUT is implied.
