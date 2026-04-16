import gzip
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime

import requests
from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("fog_node")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BACKEND_URL   = "http://127.0.0.1:8000/events"   # Cloud Backend API
MAX_CACHE     = 100                                # ring-buffer size
BATCH_SIZE    = 5                                  # events to batch before forwarding
BATCH_TIMEOUT = 10.0                               # seconds before flushing partial batch

# Alert thresholds
THRESHOLDS = {
    "temperature_max": 8.0,
    "humidity_max":    75.0,
    "vibration_max":   70.0,
}

# ---------------------------------------------------------------------------
# App + in-memory store
# ---------------------------------------------------------------------------
app = Flask(__name__)
recent_readings: list = []           # ring-buffer (local edge DB)
_batch_buffer: list   = []           # events waiting to be forwarded
_batch_lock           = threading.Lock()

# ---------------------------------------------------------------------------
# Fog-layer metrics
# ---------------------------------------------------------------------------
_metrics = {
    "events_received":  0,
    "events_forwarded": 0,
    "alerts_generated": 0,
    "forward_errors":   0,
    "batches_sent":     0,
    "processing_times": deque(maxlen=100),  # ms per event
}
_metrics_lock = threading.Lock()


def _inc(key: str, val: int = 1) -> None:
    with _metrics_lock:
        _metrics[key] += val


# ---------------------------------------------------------------------------
# Core fog-intelligence: alert detection
# ---------------------------------------------------------------------------

def detect_alerts(data: dict) -> list:
    """
    Evaluate a sensor reading against the threshold rules.
    Returns a list of alert-code strings.
    Runs entirely on the fog node — latency is <1 ms.
    """
    alerts = []
    if data.get("temperature", 0) > 8:
        alerts.append("SPOILAGE_RISK")
    if data.get("humidity", 0) > 75:
        alerts.append("HIGH_HUMIDITY")
    if data.get("vibration", 0) > 70:
        alerts.append("SHOCK_DAMAGE")
    if data.get("door_open", False) == True:
        alerts.append("TAMPER_ALERT")
    return alerts


def build_processed_payload(raw: dict, alerts: list) -> dict:
    """Enrich the raw sensor dict with fog-generated fields."""
    return {
        "device_id":        raw.get("device_id", "unknown"),
        "temperature":      raw.get("temperature"),
        "humidity":         raw.get("humidity"),
        "door_open":        raw.get("door_open"),
        "vibration":        raw.get("vibration"),
        "alerts":           alerts,
        "alert_count":      len(alerts),
        "processed_by":     "fog-node-01",
        "source_timestamp": raw.get("timestamp"),
        "fog_timestamp":    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Batch forwarding to Cloud Backend
# ---------------------------------------------------------------------------

def _forward_batch(batch: list) -> None:
    """
    Forward a batch of events to the cloud backend.
    Each event is sent as an individual POST (the cloud API handles one event
    at a time, which maps cleanly to one SQS message per event on AWS).
    Payload is gzip-compressed for network efficiency.
    """
    if not batch:
        return

    success = 0
    for event in batch:
        try:
            compressed = gzip.compress(json.dumps(event).encode("utf-8"))
            resp = requests.post(
                BACKEND_URL,
                data=compressed,
                headers={
                    "Content-Type":     "application/json",
                    "Content-Encoding": "gzip",
                },
                timeout=5,
            )
            if resp.status_code == 200:
                success += 1
            else:
                log.warning("Backend returned HTTP %d for event %s", resp.status_code, event.get("device_id"))
                _inc("forward_errors")
        except requests.exceptions.RequestException as exc:
            log.error("Forward failed: %s", exc)
            _inc("forward_errors")

    _inc("events_forwarded", success)
    _inc("batches_sent")
    log.info(
        "BATCH_SENT component=fog size=%d forwarded=%d errors=%d",
        len(batch), success, len(batch) - success,
    )


def _batch_flusher() -> None:
    """
    Background thread that flushes the batch buffer every BATCH_TIMEOUT seconds
    even if BATCH_SIZE hasn't been reached (timeout-based flush).
    """
    while True:
        time.sleep(BATCH_TIMEOUT)
        batch = []
        with _batch_lock:
            if _batch_buffer:
                batch = list(_batch_buffer)
                _batch_buffer.clear()
        if batch:
            log.info("Timeout flush: forwarding %d buffered events", len(batch))
            _forward_batch(batch)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/sensor-data", methods=["POST"])
def receive_sensor_data():
    """
    POST /sensor-data
    Accepts raw sensor payload (plain JSON or gzip-compressed JSON).
    Returns detected alerts.
    """
    t_start = time.perf_counter()

    # Support both plain JSON and gzip-compressed payloads
    content_encoding = request.headers.get("Content-Encoding", "")
    if "gzip" in content_encoding:
        raw_bytes = gzip.decompress(request.data)
        raw = json.loads(raw_bytes)
    else:
        raw = request.get_json(force=True)

    if not raw:
        return jsonify({"error": "Empty or invalid JSON"}), 400

    alerts    = detect_alerts(raw)
    processed = build_processed_payload(raw, alerts)

    # Ring-buffer cache
    recent_readings.append(processed)
    if len(recent_readings) > MAX_CACHE:
        recent_readings.pop(0)

    # Update metrics
    _inc("events_received")
    _inc("alerts_generated", len(alerts))

    # Add to batch buffer; flush if batch is full
    batch_to_forward = []
    with _batch_lock:
        _batch_buffer.append(processed)
        if len(_batch_buffer) >= BATCH_SIZE:
            batch_to_forward = list(_batch_buffer)
            _batch_buffer.clear()

    if batch_to_forward:
        threading.Thread(
            target=_forward_batch,
            args=(batch_to_forward,),
            daemon=True,
        ).start()

    # Record processing latency
    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 3)
    with _metrics_lock:
        _metrics["processing_times"].append(elapsed_ms)

    icon = "[ALERT]" if alerts else "[OK]"
    log.info(
        "%s component=fog device=%s T=%.1f H=%.1f alerts=%s latency_ms=%.2f",
        icon,
        processed["device_id"],
        processed["temperature"],
        processed["humidity"],
        alerts or "None",
        elapsed_ms,
    )

    return jsonify({
        "status":            "processed",
        "alerts":            alerts,
        "fog_timestamp":     processed["fog_timestamp"],
        "fog_processing_ms": elapsed_ms,
    }), 200


@app.route("/status", methods=["GET"])
def health_check():
    """GET /status — fog node health and cache info."""
    last_ts = recent_readings[-1]["fog_timestamp"] if recent_readings else None
    return jsonify({
        "status":          "online",
        "node_id":         "fog-node-01",
        "cached_readings": len(recent_readings),
        "last_reading_at": last_ts,
    }), 200


@app.route("/data", methods=["GET"])
def get_cached_data():
    """GET /data — return up to last 50 enriched readings from the cache."""
    limit = min(int(request.args.get("limit", 50)), MAX_CACHE)
    return jsonify(list(reversed(recent_readings[-limit:]))), 200


@app.route("/metrics", methods=["GET"])
def get_metrics():
    """GET /metrics — fog-layer processing metrics."""
    with _metrics_lock:
        times = list(_metrics["processing_times"])
        avg_latency = round(sum(times) / len(times), 3) if times else 0.0
        max_latency = round(max(times), 3) if times else 0.0
        return jsonify({
            "component":         "fog-node-01",
            "events_received":   _metrics["events_received"],
            "events_forwarded":  _metrics["events_forwarded"],
            "alerts_generated":  _metrics["alerts_generated"],
            "forward_errors":    _metrics["forward_errors"],
            "batches_sent":      _metrics["batches_sent"],
            "avg_latency_ms":    avg_latency,
            "max_latency_ms":    max_latency,
            "batch_buffer_size": len(_batch_buffer),
            "timestamp":         datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        }), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start background batch-flusher
    flusher = threading.Thread(target=_batch_flusher, daemon=True, name="BatchFlusher")
    flusher.start()

    print("=" * 62)
    print("  FOG NODE  -  Cold-Chain Delivery Monitor")
    print("  Listening : http://0.0.0.0:5000")
    print(f"  Backend   : {BACKEND_URL}")
    print(f"  Batch size: {BATCH_SIZE} events | Timeout: {BATCH_TIMEOUT}s")
    print("  (Ctrl+C to stop)")
    print("=" * 62)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
