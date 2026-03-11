"""
=============================================================================
LAMBDA WORKER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Serverless Lambda Worker (local simulation + AWS handler)
Layer      : Cloud / Serverless Compute
Description:
    Dual-mode file:

    MODE 1 — LOCAL WORKER (run directly: python lambda_function.py)
        Polls queue_manager for events, enriches them, persists to SQLite,
        and logs structured throughput metrics.  Simulates the behaviour of
        an AWS Lambda function triggered by SQS.

    MODE 2 — AWS LAMBDA HANDLER (deployed to AWS)
        The lambda_handler() function is the production entry-point.
        It receives a batch of SQS Records and writes to DynamoDB.

    Local component          AWS equivalent
    -----------------------  --------------------------
    queue_manager.dequeue()  SQS event source mapping
    SQLite                   DynamoDB
    print / logging          CloudWatch Logs

    Deployment steps
    ----------------
    1.  zip lambda.zip lambda_function.py
    2.  aws lambda create-function \
            --function-name cold-chain-processor \
            --runtime python3.11 \
            --role arn:aws:iam::<acct>:role/lambda-sqs-dynamo \
            --handler lambda_function.lambda_handler \
            --zip-file fileb://lambda.zip
    3.  Add SQS trigger in the Lambda console (event source mapping).

Author : Cold-Chain Monitor System
Date   : 2026-03-11
Usage  : python lambda_function.py          (local worker mode)
=============================================================================
"""

import json
import logging
import os
import queue
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("lambda_worker")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "coldchain_events.db"

# ---------------------------------------------------------------------------
# Alert thresholds — mirrors fog_node for defence-in-depth
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "temperature_max": 8.0,
    "humidity_max":    75.0,
    "vibration_max":   70.0,
}


# ---------------------------------------------------------------------------
# Database helpers (SQLite ~ DynamoDB)
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Ensure the DB and table exist before the worker starts polling."""
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


def _persist(event: dict) -> None:
    """Write one enriched event to SQLite (DynamoDB PutItem simulation)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO events
                (event_id, device_id, temperature, humidity, door_open,
                 vibration, alerts, alert_count, severity, processed_by,
                 source_timestamp, fog_timestamp, lambda_timestamp, received_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            event.get("event_id", str(uuid.uuid4())),
            event.get("device_id"),
            event.get("temperature"),
            event.get("humidity"),
            int(event.get("door_open", False)),
            event.get("vibration"),
            json.dumps(event.get("alerts", [])),
            event.get("alert_count", 0),
            event.get("severity", "NORMAL"),
            event.get("processed_by", "lambda-worker-local"),
            event.get("source_timestamp"),
            event.get("fog_timestamp"),
            datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            event.get("received_at"),
        ))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Enrichment — mirrors AWS Lambda re-validation
# ---------------------------------------------------------------------------

def enrich(data: dict) -> dict:
    """
    Add server-side fields, re-verify alert codes as a second line of defence
    in case the fog node had outdated thresholds.
    """
    t0 = time.perf_counter()
    data = dict(data)   # avoid mutating the original

    data["lambda_received_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    alerts = list(data.get("alerts", []))
    if data.get("temperature", 0) > THRESHOLDS["temperature_max"] and "SPOILAGE_RISK" not in alerts:
        alerts.append("SPOILAGE_RISK")
    if data.get("humidity", 0) > THRESHOLDS["humidity_max"] and "HIGH_HUMIDITY" not in alerts:
        alerts.append("HIGH_HUMIDITY")
    if data.get("door_open", False) and "TAMPER_ALERT" not in alerts:
        alerts.append("TAMPER_ALERT")
    if data.get("vibration", 0) > THRESHOLDS["vibration_max"] and "SHOCK_DAMAGE" not in alerts:
        alerts.append("SHOCK_DAMAGE")

    data["alerts"]      = alerts
    data["alert_count"] = len(alerts)
    data["severity"]    = (
        "CRITICAL" if len(alerts) >= 2 else
        "WARNING"  if len(alerts) == 1 else
        "NORMAL"
    )

    data["processing_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return data


# ---------------------------------------------------------------------------
# Local worker loop — simulates Lambda + SQS trigger
# ---------------------------------------------------------------------------

def _run_local_worker() -> None:
    """
    Continuously polls queue_manager for events and processes them.
    This is the local equivalent of Lambda's SQS event-source mapping.
    """
    import queue_manager  # imported here so it works when run standalone

    processed = 0
    failed    = 0

    log.info("=" * 62)
    log.info("  LAMBDA WORKER  -  Cold-Chain Delivery Monitor")
    log.info("  Polling queue_manager for events...")
    log.info("  DB: %s", DB_PATH)
    log.info("  (Ctrl+C to stop)")
    log.info("=" * 62)

    while True:
        try:
            event = queue_manager.dequeue(timeout=1.0)
        except queue.Empty:
            continue

        t_start = time.perf_counter()
        event_id = event.get("event_id", "unknown")
        try:
            enriched = enrich(event)
            _persist(enriched)
            queue_manager.task_done()
            queue_manager.mark_processed()
            processed += 1

            elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
            log.info(
                "PROCESSED component=lambda event_id=%s device=%s severity=%s "
                "alerts=%s processing_time_ms=%.1f total_processed=%d",
                event_id,
                enriched.get("device_id"),
                enriched.get("severity"),
                enriched.get("alerts"),
                elapsed_ms,
                processed,
            )
        except Exception as exc:
            queue_manager.mark_failed()
            failed += 1
            log.error(
                "FAILED component=lambda event_id=%s error=%s total_failed=%d",
                event_id, exc, failed,
            )


# ---------------------------------------------------------------------------
# AWS Lambda handler — production entry-point (MODE 2)
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda entry-point.
    event['Records'] contains a batch of SQS messages.
    Returns batchItemFailures so SQS can retry failed messages individually.
    """
    # Lazy import boto3 only when running on AWS
    import boto3
    from decimal import Decimal

    DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "coldchain-events")
    AWS_REGION     = os.environ.get("AWS_REGION", "us-east-1")
    dynamodb       = boto3.resource("dynamodb", region_name=AWS_REGION)
    table          = dynamodb.Table(DYNAMODB_TABLE)

    def to_decimal(v):
        return Decimal(str(v)) if isinstance(v, float) else v

    records = event.get("Records", [])
    log.info("Lambda triggered with %d SQS record(s)", len(records))

    batch_failures = []
    for record in records:
        msg_id = record.get("messageId", "unknown")
        try:
            body     = json.loads(record["body"])
            enriched = enrich(body)
            item = {
                k: (to_decimal(v) if isinstance(v, float) else v)
                for k, v in enriched.items()
            }
            table.put_item(Item=item)
            log.info("Stored messageId=%s device=%s", msg_id, enriched.get("device_id"))
        except Exception as exc:
            log.error("Failed messageId=%s error=%s", msg_id, exc)
            batch_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_failures}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    _run_local_worker()
