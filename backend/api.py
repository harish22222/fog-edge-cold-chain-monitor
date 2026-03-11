"""
=============================================================================
BACKEND LAYER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Cloud Backend API (API Gateway simulation)
Layer      : Cloud / Backend
Description:
    Simulates an AWS API Gateway + SQS ingest path locally.
    All heavy processing (DB writes) is delegated to the Lambda worker
    (lambda_function.py) via the shared queue_manager module.

    Local component          AWS equivalent
    -----------------------  --------------------------
    Flask API (port 8000)    API Gateway (REST)
    queue_manager.py         SQS
    lambda_function.py       Lambda (SQS trigger)
    SQLite file              DynamoDB table

    Endpoints
    ---------
    POST /events          <- enriched payloads from the Fog Node
    GET  /events          <- stored events for the dashboard
    GET  /summary         <- aggregate KPIs
    GET  /health          <- server + queue health
    GET  /metrics         <- detailed queue + throughput metrics
    GET  /queue-status    <- queue depth + recent history

Author : Cold-Chain Monitor System
Date   : 2026-03-11
Usage  : python api.py
=============================================================================
"""

import gzip
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

import queue_manager

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
CORS(app)   # allow cross-origin requests from Streamlit


# ---------------------------------------------------------------------------
# Database helpers (SQLite ~ DynamoDB)
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
            severity         TEXT    DEFAULT 'NORMAL',
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


# ---------------------------------------------------------------------------
# Flask routes — API Gateway simulation
# ---------------------------------------------------------------------------

@app.route("/events", methods=["POST"])
def receive_event():
    """
    POST /events
    Fog Node -> API Gateway -> SQS.SendMessage (simulated).
    Assigns a unique event_id and enqueues for async Lambda processing.
    """
    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    # Assign a unique ID (mimics SQS MessageId)
    payload["event_id"]    = payload.get("event_id", str(uuid.uuid4()))
    payload["received_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    queue_manager.enqueue(payload)

    log.info(
        "ENQUEUED component=api event_id=%s device=%s depth=%d",
        payload["event_id"],
        payload.get("device_id"),
        queue_manager.get_metrics()["queue_size"],
    )

    return jsonify({
        "message":     "Event queued for Lambda processing",
        "event_id":    payload["event_id"],
        "queue_depth": queue_manager.get_metrics()["queue_size"],
    }), 200


@app.route("/events", methods=["GET"])
def list_events():
    """
    GET /events?limit=100&device=truck-01&alerts=true
    Returns stored events from SQLite, newest first.
    """
    limit       = int(request.args.get("limit", 100))
    device      = request.args.get("device")
    only_alerts = request.args.get("alerts", "false").lower() == "true"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query  = "SELECT * FROM events WHERE 1=1"
    params = []
    if device:
        query  += " AND device_id = ?";  params.append(device)
    if only_alerts:
        query  += " AND alert_count > 0"
    query += " ORDER BY id DESC LIMIT ?"; params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    events = []
    for row in rows:
        d = dict(row)
        d["alerts"]    = json.loads(d["alerts"] or "[]")
        d["door_open"] = bool(d["door_open"])
        events.append(d)

    return jsonify(events), 200


@app.route("/summary", methods=["GET"])
def summary():
    """GET /summary — aggregated KPIs for the dashboard."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    total        = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    alert_events = cur.execute("SELECT COUNT(*) FROM events WHERE alert_count > 0").fetchone()[0]
    avg_temp     = cur.execute("SELECT ROUND(AVG(temperature),2) FROM events").fetchone()[0]
    avg_humidity = cur.execute("SELECT ROUND(AVG(humidity),2) FROM events").fetchone()[0]
    max_temp     = cur.execute("SELECT ROUND(MAX(temperature),2) FROM events").fetchone()[0]
    spoilage     = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%SPOILAGE_RISK%'").fetchone()[0]
    tamper       = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%TAMPER_ALERT%'").fetchone()[0]
    shock        = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%SHOCK_DAMAGE%'").fetchone()[0]
    high_hum     = cur.execute("SELECT COUNT(*) FROM events WHERE alerts LIKE '%HIGH_HUMIDITY%'").fetchone()[0]
    conn.close()

    metrics = queue_manager.get_metrics()

    return jsonify({
        "total_events":    total,
        "alert_events":    alert_events,
        "avg_temperature": avg_temp,
        "avg_humidity":    avg_humidity,
        "max_temperature": max_temp,
        "alert_breakdown": {
            "SPOILAGE_RISK":  spoilage,
            "TAMPER_ALERT":   tamper,
            "SHOCK_DAMAGE":   shock,
            "HIGH_HUMIDITY":  high_hum,
        },
        "queue_metrics":   metrics,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """GET /health — server, queue, and DB health check."""
    conn  = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    metrics = queue_manager.get_metrics()

    return jsonify({
        "status":            "healthy",
        "component":         "api-gateway",
        "db_records":        count,
        "queue_depth":       metrics["queue_size"],
        "enqueued_total":    metrics["enqueued_total"],
        "processed_total":   metrics["processed_total"],
        "failed_total":      metrics["failed_total"],
        "timestamp":         datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    """GET /metrics — detailed throughput + queue metrics."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    m = queue_manager.get_metrics()
    return jsonify({
        "component":        "api-gateway",
        "db_records":       count,
        "queue_size":       m["queue_size"],
        "enqueued_total":   m["enqueued_total"],
        "processed_total":  m["processed_total"],
        "failed_total":     m["failed_total"],
        "timestamp":        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


@app.route("/queue-status", methods=["GET"])
def queue_status():
    """GET /queue-status — queue depth and recent depth history."""
    m = queue_manager.get_metrics()
    return jsonify({
        "queue_size":     m["queue_size"],
        "queue_history":  m["queue_history"][-50:],  # last 50 data-points
        "timestamp":      datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    queue_manager.start_history_sampler(interval=5.0)

    log.info("=" * 62)
    log.info("  BACKEND API  -  Cold-Chain Delivery Monitor")
    log.info("  Listening : http://0.0.0.0:8000")
    log.info("  POST /events       <- fog payloads")
    log.info("  GET  /events       <- dashboard reads")
    log.info("  GET  /summary      <- KPI aggregates")
    log.info("  GET  /health       <- health check")
    log.info("  GET  /metrics      <- queue + throughput metrics")
    log.info("  GET  /queue-status <- queue depth history")
    log.info("  (Ctrl+C to stop)")
    log.info("=" * 62)
    log.info("NOTE: Start lambda_function.py in a separate terminal to process the queue.")

    app.run(host="0.0.0.0", port=8000, debug=False)
