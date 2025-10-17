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
  "source": "ups",
  "timestamp": 1752740234,
  "host": "loxberry",
  "alive": 1,
  "ups_status": 1,
  "ups_on_line": 1,
  "status_raw": "ol chrg",
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

### Key Parameters

| Field | Description |
|-------|--------------|
| `alive` | 1 if bridge and NUT communication OK, 0 if connection or script stopped |
| `timestamp` | UNIX timestamp of the reading |
| `ups_status` | **Integer only**. Normalized UPS state: 1 online, 2 on battery, 3 low battery, 4 replace battery, 5 overload, 6 shutdown imminent, 9 unknown |
| `ups_on_line` | 1 if on mains (OL), 0 if on battery (OB). -1 if unknown |
| `status_raw` | Raw NUT `ups.status` string, **lowercase**; tokens space- or comma-separated (e.g. `"ol chrg"`, `"ob lb"`) |
| `battery_percent` | Battery charge percentage |
| `runtime_total_sec` | Total runtime in seconds |
| `runtime_total_min` | Total runtime rounded up to minutes |
| `runtime_min` | Whole minutes portion of runtime |
| `runtime_sec` | Remaining seconds portion of runtime |
| `load_percent` | Current UPS load percentage |
| `input_voltage` | Current mains voltage |
| `battery_charging` | 1 if charging, 0 if discharging, -1 if unknown |

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
