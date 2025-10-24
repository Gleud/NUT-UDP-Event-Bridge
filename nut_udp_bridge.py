#!/usr/bin/env python3
"""
UPS -> UDP bridge (NUT client)
- Polls NUT via `upsc <nut_target>` (Ubuntu) OR reads a sample file on macOS (Darwin).
- Sends a single-line JSON UDP packet each cycle (flat schema, English keys).
- alive == 1 while the script runs AND NUT/UPS is reachable (even on battery).
- On error (no NUT data) send alive=0 and back off 10s.
- On SIGINT/SIGTERM send one last packet with alive=0, then exit.
- Logging: rotating file (5 MB, keep 3 backups) + console.

Config file: config.json (see DEFAULT_CONFIG for keys).
"""

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
import signal
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional
import math
import atexit

DEFAULT_CONFIG = {
    "udp_receiver_ip": "127.0.0.1",
    "udp_receiver_port": 9999,
    "nut_target": "qnapups@192.168.1.20",
    "intervall_ol": 10,
    "dev_sample_file": "sample_upsc.txt",
    "hostname_override": "",
    "log_level": "INFO",
    "log_file": "ups_udp_bridge.log",
    "upsc_timeout_sec": 3,
    "rb_debounce_polls": 12,
    "rb_ignore_during_selftest": True
}

BACKOFF_ERROR_SEC = 10  # fixed 10s backoff on communication errors

def now_ts() -> int:
    return int(time.time())

def map_status(raw: str):
    # TODO: consider "Degraded" state? State combos (eg. ups.status: OL CHRG LB)

    """
    Map NUT ups.status string to a single numeric code with severity priority:
    6 Forced shutdown > 5 Overload > 4 Replace battery > 3 Low battery > 2 On battery > 1 Online > 9 Unknown
    Returns: (code:int, text:str)
    """

    s = (raw or "").strip().upper()

    if not s:
        return 9, "unknown"

    # Highest severity first
    if "FSD" in s:
        return 6, "shutdown_imminent"
    if "OVER" in s:
        return 5, "overload"
    if "RB" in s or "REPLACE" in s:
        return 4, "replace_battery"
    if "LB" in s or "LOW" in s:
        return 3, "low_battery"
    if "OB" in s or "ONBATT" in s or "ON BATTERY" in s:
        return 2, "on_battery"
    if "OL" in s or "ONLINE" in s:
        return 1, "online"

    return 9, "unknown"


def parse_ups_on_line(raw: str) -> int:
    """
    Returns 1 if UPS is on mains (OL), 0 if on battery (OB/ONBATT), -1 if unknown.
    """
    s = (raw or "").upper()
    if "OB" in s or "ONBATT" in s or "ON BATTERY" in s:
        return 0
    if "OL" in s or "ONLINE" in s:
        return 1
    return -1

def parse_charging_flag(raw: str) -> int:
    """
    Returns 1 if charging (CHRG), 0 if discharging (DISCHRG), else -1 (unknown/not provided).
    """
    s = (raw or "").upper()
    if "CHRG" in s:
        return 1
    if "DISCHRG" in s:
        return 0
    return -1

def to_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    txt = v.strip()
    if not txt:
        return None
    try:
        return float(txt)
    except Exception:
        try:
            txt = txt.replace(",", ".").split()[0]
            return float(txt)
        except Exception:
            return None

def to_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    txt = v.strip()
    if not txt:
        return None
    try:
        return int(float(txt))
    except Exception:
        try:
            return int(txt.split()[0])
        except Exception:
            return None

def _filter_rb_tokens(status_str: str) -> str:
    """
    Entfernt RB/REPLACE-Tokens aus einem ups.status-String.
    """
    tokens = (status_str or "").split()
    drop = {"RB", "REPLACE", "REPLACEBATTERY", "BATTREPLACE"}
    return " ".join(t for t in tokens if t.upper() not in drop)

def build_logger(log_file: str, log_level: str) -> logging.Logger:
    logger = logging.getLogger("ups_udp_bridge")
    logger.setLevel(logging.DEBUG)  # capture all; handlers filter

    # Formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    # Rotating file handler: 5 MB, 3 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.addHandler(file_handler)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.addHandler(console)

    # Avoid duplicate handlers if build_logger called multiple times
    logger.propagate = False
    return logger

class UPSUDPBridge:
    def __init__(self, cfg: Dict, logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self.dev_mode = platform.system() == "Darwin"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = (cfg["udp_receiver_ip"], int(cfg["udp_receiver_port"]))
        self.hostname = cfg.get("hostname_override") or socket.gethostname()
        self.running = True
        self.last_known_status_num = 9
        self.last_known_status_text = "unknown"
        self._dead_sent = False
        self.rb_count = 0
        self.rb_threshold = int(self.cfg.get("rb_debounce_polls", 12))
        self.rb_ignore_during_selftest = bool(self.cfg.get("rb_ignore_during_selftest", True))

        signal.signal(signal.SIGINT, self._sig_handler)
        signal.signal(signal.SIGTERM, self._sig_handler)
        # zusätzlich:
        try:
            signal.signal(signal.SIGHUP, self._sig_handler)
        except Exception:
            pass
        try:
            signal.signal(signal.SIGQUIT, self._sig_handler)
        except Exception:
            pass
        # Fallback, falls kein Signal mehr zugestellt wird:
        atexit.register(self._send_dead_packet)

        self.logger.info(
            "Starting UPS UDP bridge | target=%s:%s | dev_mode=%s | nut_target=%s",
            self.target[0], self.target[1], self.dev_mode, self.cfg.get("nut_target")
        )

    def _selftest_active(self, data: Dict[str, str]) -> bool:
        """
        Erkenne laufenden Selbsttest anhand typischer Texte in ups.test.result.
        Beeinflusst nur die interne Bewertung, nicht das Payload-Schema.
        """
        txt = (data.get("ups.test.result") or "").strip().lower()
        return any(k in txt for k in [
            "in progress", "progress", "testing", "self-test in progress", "selftest in progress"
        ])

    def _sig_handler(self, *_):
        self.logger.info("Signal received -> shutting down")
        self.running = False
        # Dead-Packet
        self._send_dead_packet()

    def _send_dead_packet(self):
        if getattr(self, "_dead_sent", False):
            return
        try:
            pkt = {
                "source": "ups",
                "timestamp": now_ts(),
                "host": self.hostname,
                "alive": 0,
                "ups_status": self.last_known_status_num,
                "ups_on_line": parse_ups_on_line(self.last_known_status_text),
                "status_raw": (self.last_known_status_text or "").lower().strip()
            }
            self._send_packet(pkt)
            # kurze Pause, damit UDP rausgeht (falls Netz noch lebt)
            time.sleep(0.05)
        except Exception as e:
            self.logger.debug("dead-packet send failed: %s", e)
        finally:
            self._dead_sent = True
            try:
                self.sock.close()
            except Exception:
                pass

    def _send_packet(self, payload: Dict):
        try:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.sock.sendto(data, self.target)
            self.logger.debug("Sent UDP: %s", payload)
        except Exception as e:
            self.logger.error("UDP send error: %s", e)

    def _query_upsc(self) -> Dict[str, str]:
        """
        Return dict of key -> value (strings) from either:
        - macOS dev file (sample_upsc.txt), or
        - `upsc <nut_target>` stdout.
        """
        if platform.system() == "Darwin":
            path = Path(self.cfg.get("dev_sample_file", "sample_upsc.txt"))
            if not path.exists():
                raise RuntimeError(f"Dev sample file not found: {path}")
            content = path.read_text(encoding="utf-8")
            self.logger.debug("Read dev sample file: %s (%d bytes)", path, len(content))
        else:
            cmd = ["upsc", self.cfg["nut_target"]]
            self.logger.debug("Running: %s", " ".join(cmd))
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=int(self.cfg.get("upsc_timeout_sec", 3))
                )
            except FileNotFoundError:
                raise RuntimeError("upsc binary not found")
            except subprocess.TimeoutExpired:
                raise RuntimeError("upsc command timed out")
            if proc.returncode != 0:
                err = proc.stderr.strip() or proc.stdout.strip()
                raise RuntimeError(f"upsc error rc={proc.returncode}: {err}")
            content = proc.stdout
            if not content:
                raise RuntimeError("upsc returned empty output")

        parsed: Dict[str, str] = {}
        for line in content.splitlines():
            # Ignore lines without colon (e.g., "Init SSL without certificate database")
            if ":" not in line:
                self.logger.debug("Ignoring non KV line: %s", line)
                continue
            k, v = line.split(":", 1)
            parsed[k.strip()] = v.strip()
        self.logger.debug("Parsed %d keys from NUT/dev sample", len(parsed))
        return parsed

    def run(self):
        while self.running:
            try:
                data = self._query_upsc()
            except Exception as e:
                self.logger.warning("NUT communication error: %s", e)
                # comms error: send alive=0 + unknown state, then back off 10s
                self._send_packet({
                    "source": "ups",
                    "timestamp": now_ts(),
                    "host": self.hostname,
                    "alive": 0,
                    "ups_status": 9,
                    "ups_on_line": -1,
                    "status_raw": "unknown",
                    "error": str(e)
                })
                time.sleep(BACKOFF_ERROR_SEC)
                continue

            # --- parse/normalize fields ---
            status_str_raw = data.get("ups.status", "")  # Original vom Treiber
            up_upper = (status_str_raw or "").upper()

            # RB- und Selbsttest-Erkennung
            raw_rb = ("RB" in up_upper) or ("REPLACE" in up_upper)
            st_active = self._selftest_active(data)

            # Debounce-Zähler pflegen (RB nur zählen, wenn nicht im Selbsttest – falls konfiguriert)
            if raw_rb and not (self.rb_ignore_during_selftest and st_active):
                self.rb_count += 1
            else:
                if self.rb_count != 0:
                    self.logger.debug("RB debounce reset (raw_rb=%s, selftest_active=%s)", raw_rb, st_active)
                self.rb_count = 0

            # Darf RB wirksam sein?
            rb_allowed = raw_rb and (self.rb_count >= self.rb_threshold) and not (
                    self.rb_ignore_during_selftest and st_active
            )

            # Effektiver Statusstring für Mapping/Output:
            # -> solange RB NICHT erlaubt ist: RB-Tokens entfernen, damit Mapping NICHT sofort greift.
            eff_status_str = status_str_raw if rb_allowed else _filter_rb_tokens(status_str_raw)

            # Ab hier nur noch mit dem gefilterten String arbeiten:
            status_num, status_text = map_status(eff_status_str)
            chg = parse_charging_flag(eff_status_str)

            self.last_known_status_num = status_num
            self.last_known_status_text = status_text

            payload = {
                "source": "ups",
                "timestamp": now_ts(),
                "host": self.hostname,
                "alive": 1,  # we reached NUT successfully
                "ups_status": status_num,
                "ups_on_line": parse_ups_on_line(eff_status_str),
                "status_raw": (eff_status_str or "").lower().strip()
            }

            if chg != -1:
                payload["battery_charging"] = chg

            # core numeric fields
            bp = to_float(data.get("battery.charge"))
            if bp is not None:
                payload["battery_percent"] = bp
            rt = to_int(data.get("battery.runtime"))
            if rt is not None:
                payload["runtime_total_sec"] = rt
                payload["runtime_total_min"] = math.ceil(rt / 60)
                payload["runtime_min"] = rt // 60
                payload["runtime_sec"] = rt % 60
            loadp = to_float(data.get("ups.load"))
            if loadp is not None:
                payload["load_percent"] = loadp
            inv = to_float(data.get("input.voltage"))
            if inv is not None:
                payload["input_voltage"] = inv

            # optional enrichments (only if present/parsable)
            bv = to_float(data.get("battery.voltage"))
            if bv is not None:
                payload["battery_voltage"] = bv

            ltr = data.get("input.transfer.reason")
            if ltr:
                payload["last_transfer_reason"] = ltr

            utr = data.get("ups.test.result")
            if utr:
                payload["ups_test_result"] = utr

            dm = data.get("device.model")
            if dm:
                payload["device_model"] = dm

            ds = data.get("device.serial")
            if ds:
                payload["device_serial"] = ds

            ivn = to_float(data.get("input.voltage.nominal"))
            if ivn is not None:
                payload["input_voltage_nominal"] = ivn

            bvn = to_float(data.get("battery.voltage.nominal"))
            if bvn is not None:
                payload["battery_voltage_nominal"] = bvn

            rpn = to_float(data.get("ups.realpower.nominal"))
            if rpn is not None:
                payload["realpower_nominal"] = rpn

            drv = data.get("driver.version")
            if drv:
                payload["driver_version"] = drv

            self._send_packet(payload)

            # Sleep-Strategie (wie zuvor)
            if status_num == 1:
                sleep_s = max(1, int(self.cfg.get("intervall_ol", 10)))
            else:
                sleep_s = 5
            self.logger.debug("Sleeping %ss (status=%s)", sleep_s, status_text)
            time.sleep(sleep_s)

        # wenn die Schleife endet, sende Dead-Packet (falls nicht schon gesendet)
        self._send_dead_packet()
        self.logger.info("Stopped")

def load_config(path: Path) -> Dict:
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return DEFAULT_CONFIG.copy()
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    return merged

def main():
    ap = argparse.ArgumentParser(description="UPS -> UDP bridge (flat JSON, English keys)")
    ap.add_argument("-c", "--config", default="config.json", help="Path to config.json")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    logger = build_logger(cfg.get("log_file", "ups_udp_bridge.log"), cfg.get("log_level", "INFO"))

    logger.info("Config loaded from %s", args.config)
    logger.debug("Effective config: %s", cfg)

    bridge = UPSUDPBridge(cfg, logger)
    try:
        bridge.run()
    except Exception as e:
        # last resort: try to send one dead packet and exit non-zero
        logger.exception("Fatal error: %s", e)
        try:
            bridge._send_dead_packet()
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()