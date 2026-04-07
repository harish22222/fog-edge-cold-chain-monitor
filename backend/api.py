"""
=============================================================================
BACKEND LAYER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Cloud Backend API (Direct DB Write Version)
Layer      : Cloud / Backend
Description:
    Simplified local backend for the Cold-Chain project.

    Flow:
        Sensor -> Fog Node -> Backend API -> SQLite DB -> Dashboard

    This version removes the local queue/lambda dependency so the system
    works reliably in separate terminals/processes.

    Endpoints
    ---------
    POST /events          <- enriched payloads from the Fog Node
    GET  /events          <- stored events for the dashboard
    GET  /summary         <- aggregate KPIs
    GET  /health          <- server + DB health
    GET  /metrics         <- throughput metrics
    GET  /queue-status    <- simulated queue depth history for dashboard

Author : Cold-Chain Monitor System
Date   : 2026-03-11
Usage  : python api.py
=============================================================================
"""

import gzip
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("api")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "coldchain_events.db"

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# In-memory metrics (simple replacement for queue metrics)
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()
_metrics = {
    "received_total": 0,
    "failed_total": 0,
    "queue_history": deque(maxlen=200),   # dashboard expects this
}


def _snapshot_queue_depth() -> None:
    """
    Simulated queue depth history.
    Since this simplified version writes directly to DB,
    queue depth is always 0.
    """
    with _metrics_lock:
        _metrics["queue_history"].append({
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "depth": 0,
        })


def start_history_sampler(interval: float = 5.0) -> None:
    """Background sampler so dashboard always has queue history points."""
    def _sample():
        while True:
            _snapshot_queue_depth()
            time.sleep(interval)

    t = threading.Thread(target=_sample, daemon=True, name="QueueHistorySampler")
    t.start()
    log.info("Queue history sampler started (interval=%.1fs)", interval)


def _inc_received() -> None:
    with _metrics_lock:
        _metrics["received_total"] += 1


def _inc_failed() -> None:
    with _metrics_lock:
        _metrics["failed_total"] += 1


def get_metrics() -> dict:
    with _metrics_lock:
        return {
            "queue_size": 0,
            "enqueued_total": _metrics["received_total"],
            "processed_total": _metrics["received_total"],
            "failed_total": _metrics["failed_total"],
            "queue_history": list(_metrics["queue_history"]),
        }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the events table if it does not already exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id         TEXT UNIQUE,
            device_id        TEXT,
            temperature      REAL,
            humidity         REAL,
            door_open        INTEGER,
            vibration        REAL,
            alerts           TEXT,
            alert_count      INTEGER DEFAULT 0,
            severity         TEXT DEFAULT 'NORMAL',
            processed_by     TEXT,
            source_timestamp TEXT,
            fog_timestamp    TEXT,
            lambda_timestamp TEXT,
            received_at      TEXT
        )
    """)
    conn.commit()
    conn.close()
    log.info("DB ready: %s", DB_PATH)


def _calculate_severity(alert_count: int) -> str:
    if alert_count >= 2:
        return "CRITICAL"
    elif alert_count == 1:
        return "WARNING"
    return "NORMAL"


def save_event(payload: dict) -> None:
    """Write one event directly into SQLite."""
    alerts = payload.get("alerts", [])
    if isinstance(alerts, str):
        try:
            alerts = json.loads(alerts)
        except Exception:
            alerts = []

    alert_count = payload.get("alert_count", len(alerts))
    severity = payload.get("severity", _calculate_severity(alert_count))

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO events
                (event_id, device_id, temperature, humidity, door_open,
                 vibration, alerts, alert_count, severity, processed_by,
                 source_timestamp, fog_timestamp, lambda_timestamp, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("event_id"),
            payload.get("device_id"),
            payload.get("temperature"),
            payload.get("humidity"),
            int(bool(payload.get("door_open", False))),
            payload.get("vibration"),
            json.dumps(alerts),
            alert_count,
            severity,
            payload.get("processed_by", "fog-node-01"),
            payload.get("source_timestamp"),
            payload.get("fog_timestamp"),
            None,  # no lambda in simplified mode
            payload.get("received_at"),
        ))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
@app.route("/events", methods=["POST"])
def receive_event():
    """
    POST /events
    Accepts plain JSON or gzip-compressed JSON from the Fog Node.
    Stores directly into SQLite.
    """
    try:
        content_encoding = request.headers.get("Content-Encoding", "")

        if "gzip" in content_encoding.lower():
            raw_bytes = gzip.decompress(request.data)
            payload = json.loads(raw_bytes.decode("utf-8"))
        else:
            payload = request.get_json(force=True)

        if not payload:
            return jsonify({"error": "Empty payload"}), 400

        payload["event_id"] = payload.get("event_id", str(uuid.uuid4()))
        payload["received_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        save_event(payload)
        _inc_received()
        _snapshot_queue_depth()

        log.info(
            "STORED component=api event_id=%s device=%s temp=%s humidity=%s alerts=%s",
            payload["event_id"],
            payload.get("device_id"),
            payload.get("temperature"),
            payload.get("humidity"),
            payload.get("alerts", []),
        )

        return jsonify({
            "message": "Event stored successfully",
            "event_id": payload["event_id"],
            "queue_depth": 0,
        }), 200

    except Exception as exc:
        _inc_failed()
        log.error("Failed to receive/store event: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/events", methods=["GET"])
def list_events():
    """
    GET /events?limit=100&device=truck-01&alerts=true
    Returns stored events from SQLite, newest first.
    """
    limit = int(request.args.get("limit", 100))
    device = request.args.get("device")
    only_alerts = request.args.get("alerts", "false").lower() == "true"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM events WHERE 1=1"
    params = []

    if device:
        query += " AND device_id = ?"
        params.append(device)

    if only_alerts:
        query += " AND alert_count > 0"

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    events = []
    for row in rows:
        d = dict(row)
        d["alerts"] = json.loads(d["alerts"] or "[]")
        d["door_open"] = bool(d["door_open"])
        events.append(d)

    return jsonify(events), 200


@app.route("/summary", methods=["GET"])
def summary():
    """GET /summary — aggregated KPIs for the dashboard."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    alert_events = cur.execute("SELECT COUNT(*) FROM events WHERE alert_count > 0").fetchone()[0]
    avg_temp = cur.execute("SELECT ROUND(AVG(temperature),2) FROM events").fetchone()[0]
    avg_humidity = cur.execute("SELECT ROUND(AVG(humidity),2) FROM events").fetchone()[0]
    max_temp = cur.execute("SELECT ROUND(MAX(temperature),2) FROM events").fetchone()[0]
    spoilage = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%SPOILAGE_RISK%'").fetchone()[0]
    tamper = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%TAMPER_ALERT%'").fetchone()[0]
    shock = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%SHOCK_DAMAGE%'").fetchone()[0]
    high_hum = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%HIGH_HUMIDITY%'").fetchone()[0]

    conn.close()

    metrics = get_metrics()

    return jsonify({
        "total_events": total,
        "alert_events": alert_events,
        "avg_temperature": avg_temp,
        "avg_humidity": avg_humidity,
        "max_temperature": max_temp,
        "alert_breakdown": {
            "SPOILAGE_RISK": spoilage,
            "TAMPER_ALERT": tamper,
            "SHOCK_DAMAGE": shock,
            "HIGH_HUMIDITY": high_hum,
        },
        "queue_metrics": metrics,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """GET /health — server and DB health check."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    metrics = get_metrics()

    return jsonify({
        "status": "healthy",
        "component": "api-gateway",
        "db_records": count,
        "queue_depth": 0,
        "enqueued_total": metrics["enqueued_total"],
        "processed_total": metrics["processed_total"],
        "failed_total": metrics["failed_total"],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    """GET /metrics — detailed throughput metrics."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    m = get_metrics()

    return jsonify({
        "component": "api-gateway",
        "db_records": count,
        "queue_size": 0,
        "enqueued_total": m["enqueued_total"],
        "processed_total": m["processed_total"],
        "failed_total": m["failed_total"],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


@app.route("/queue-status", methods=["GET"])
def queue_status():
    """GET /queue-status — simulated queue depth history for dashboard."""
    m = get_metrics()
    return jsonify({
        "queue_size": 0,
        "queue_history": m["queue_history"][-50:],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    start_history_sampler(interval=5.0)

    log.info("=" * 62)
    log.info("  BACKEND API  -  Cold-Chain Delivery Monitor")
    log.info("  Listening : http://0.0.0.0:8000")
    log.info("  POST /events       <- fog payloads")
    log.info("  GET  /events       <- dashboard reads")
    log.info("  GET  /summary      <- KPI aggregates")
    log.info("  GET  /health       <- health check")
    log.info("  GET  /metrics      <- throughput metrics")
    log.info("  GET  /queue-status <- simulated queue history")
    log.info("  (Ctrl+C to stop)")
    log.info("=" * 62)
    log.info("NOTE: Direct DB mode enabled. Lambda worker not required.")

    app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)