"""
=============================================================================
SENSOR LAYER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Edge / IoT Sensor Simulator
Layer      : Sensor Layer (Edge)
Description:
    Simulates four IoT sensors attached to a cold-chain delivery box:
      1. Temperature sensor  (C)         - normal: 2-8 C
      2. Humidity sensor     (%)         - normal: 40-75 %
      3. Door/Open sensor    (boolean)   - open ~10 % of the time
      4. Vibration/Shock     (0-100)     - spike >70 ~10 % of the time

    Special simulation modes (triggered randomly):
      - Anomaly spike     : 5 % chance -> extreme temperature + door open
      - Burst traffic     : 3 % chance -> sends 10 events rapidly
      - High vibration    : 10 % chance -> shock event
      - Temperature spike : 20 % chance -> SPOILAGE_RISK temperature

    Readings are sent via HTTP POST to the Fog Node every SEND_INTERVAL s.

Author : Cold-Chain Monitor System
Date   : 2026-03-11
Usage  : python sensor_simulator.py
=============================================================================
"""

import logging
import random
import sys
import time
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# Ensure UTF-8 output on Windows (avoids UnicodeEncodeError with symbols)
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("sensor_simulator")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# List of delivery trucks in the cold-chain fleet
devices       = ["truck-01", "truck-02", "truck-03"]
FOG_NODE_URL  = "http://127.0.0.1:5000/sensor-data"
SEND_INTERVAL = 5      # seconds between normal readings
BURST_COUNT   = 10     # number of events in a burst


# ---------------------------------------------------------------------------
# Individual sensor helpers
# ---------------------------------------------------------------------------

def read_temperature(anomaly: bool = False, spike: bool = False) -> float:
    """
    Simulate a temperature sensor.
    Normal   : 2-8 C (cold-chain safe)
    Spike    : 8.1-15 C  -> SPOILAGE_RISK
    Anomaly  : 15-25 C   -> severe SPOILAGE_RISK
    """
    if anomaly:
        return round(random.uniform(15.0, 25.0), 2)
    if spike:
        return round(random.uniform(8.1, 15.0), 2)
    return round(random.uniform(2.0, 8.0), 2)


def read_humidity(anomaly: bool = False) -> float:
    """
    Simulate a humidity sensor (%).
    Normal : 40-75 %    (safe)
    High   : 75.1-95 % -> HIGH_HUMIDITY
    """
    if anomaly:
        return round(random.uniform(85.0, 95.0), 2)
    if random.random() < 0.15:
        return round(random.uniform(75.1, 95.0), 2)
    return round(random.uniform(40.0, 75.0), 2)


def read_door_open(anomaly: bool = False) -> bool:
    """Simulate a magnetic door sensor. Open ~10 % normally, always open during anomaly."""
    return True if anomaly else random.random() < 0.10


def read_vibration(high: bool = False, anomaly: bool = False) -> float:
    """
    Simulate an accelerometer (0-100 scale).
    Normal    : 0-50  (road vibration)
    High vib  : 70.1-100 -> SHOCK_DAMAGE
    Anomaly   : 80-100   -> severe shock
    """
    if anomaly:
        return round(random.uniform(80.0, 100.0), 2)
    if high:
        return round(random.uniform(70.1, 100.0), 2)
    return round(random.uniform(0.0, 50.0), 2)


# ---------------------------------------------------------------------------
# Event modes
# ---------------------------------------------------------------------------

def _decide_mode() -> str:
    """Randomly decide which simulation mode to use for this reading."""
    r = random.random()
    if r < 0.05:
        return "anomaly"         # 5 %  - full anomaly (all alerts)
    elif r < 0.08:
        return "burst"           # 3 %  - burst of 10 events
    elif r < 0.18:
        return "high_vibration"  # 10 % - shock event
    elif r < 0.38:
        return "temp_spike"      # 20 % - temperature spike only
    else:
        return "normal"          # 62 % - normal reading


def build_payload(mode: str = "normal") -> dict:
    """Assemble a sensor payload for the given simulation mode."""
    anomaly    = mode == "anomaly"
    high_vib   = mode in ("high_vibration", "anomaly")
    temp_spike = mode in ("temp_spike", "anomaly")

    device_id = random.choice(devices)

    return {
        "device_id":   device_id,
        "temperature": read_temperature(anomaly=anomaly, spike=temp_spike),
        "humidity":    read_humidity(anomaly=anomaly),
        "door_open":   read_door_open(anomaly=anomaly),
        "vibration":   read_vibration(high=high_vib, anomaly=anomaly),
        "timestamp":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "sim_mode":    mode,
    }


# ---------------------------------------------------------------------------
# Transmission
# ---------------------------------------------------------------------------

def send_to_fog(payload: dict, burst_seq: int = 0) -> None:
    """
    POST the sensor payload to the Fog Node.
    Handles connection errors gracefully so the loop keeps running.
    """
    label = f"[BURST {burst_seq}]" if burst_seq else f"[{payload['sim_mode'].upper()}]"
    try:
        response = requests.post(FOG_NODE_URL, json=payload, timeout=5)
        door_str = "OPEN" if payload["door_open"] else "CLOSED"

        if response.status_code == 200:
            resp_json = response.json()
            alerts    = resp_json.get("alerts", [])
            lat_ms    = resp_json.get("fog_processing_ms", "?")
            log.info(
                "%s component=sensor device=%s T=%.1f H=%.1f Door=%s Vib=%.1f "
                "alerts=%s fog_latency_ms=%s",
                label,
                payload["device_id"],
                payload["temperature"],
                payload["humidity"],
                door_str,
                payload["vibration"],
                alerts if alerts else "None",
                lat_ms,
            )
        else:
            log.warning("%s Fog node HTTP %d: %s", label, response.status_code, response.text)

    except requests.exceptions.ConnectionError:
        log.error("[ERR] Cannot reach Fog Node - is fog_node.py running on port 5000?")
    except requests.exceptions.Timeout:
        log.error("[ERR] Request to Fog Node timed out.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("=" * 62)
    log.info("  SENSOR SIMULATOR  -  Cold-Chain Delivery Monitor")
    log.info("  Fleet   : %s", ", ".join(devices))
    log.info("  Fog URL : %s", FOG_NODE_URL)
    log.info("  Rate    : every %d seconds", SEND_INTERVAL)
    log.info("  Modes   : normal | temp_spike | high_vibration | burst | anomaly")
    log.info("  (Ctrl+C to stop)")
    log.info("=" * 62)

    while True:
        mode = _decide_mode()

        if mode == "burst":
            log.info("[BURST] Simulating burst traffic - sending %d events rapidly!", BURST_COUNT)
            for i in range(1, BURST_COUNT + 1):
                burst_mode = random.choice(["normal", "temp_spike", "high_vibration"])
                p = build_payload(burst_mode)
                send_to_fog(p, burst_seq=i)
                time.sleep(0.2)  # small delay between burst events
        else:
            p = build_payload(mode)
            send_to_fog(p)

        time.sleep(SEND_INTERVAL)
