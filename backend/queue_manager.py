import logging
import queue
import threading
import time
from collections import deque
from datetime import datetime

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------
log = logging.getLogger("queue_manager")

# ---------------------------------------------------------------------------
# Shared SQS-simulation state
# ---------------------------------------------------------------------------
_q: queue.Queue = queue.Queue()

_lock               = threading.Lock()
_enqueued_total: int  = 0
_processed_total: int = 0
_failed_total: int    = 0

# Stores (timestamp, depth) tuples for the queue-depth chart
_queue_history: deque = deque(maxlen=200)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue(event: dict) -> None:
    """Push one event onto the simulated SQS queue."""
    global _enqueued_total
    _q.put(event)
    with _lock:
        _enqueued_total += 1
    _snapshot_depth()
    log.info(
        "ENQUEUE component=queue_manager event_id=%s depth=%d",
        event.get("event_id", "?"),
        _q.qsize(),
    )


def dequeue(timeout: float = 1.0) -> dict:
    """
    Block until an event is available (or timeout).
    Raises queue.Empty if nothing arrives within `timeout`.
    """
    return _q.get(timeout=timeout)


def task_done() -> None:
    """Signal the queue that one item has been processed."""
    _q.task_done()


def mark_processed() -> None:
    """Increment the processed counter."""
    global _processed_total
    with _lock:
        _processed_total += 1
    _snapshot_depth()


def mark_failed() -> None:
    """Increment the failed counter."""
    global _failed_total
    with _lock:
        _failed_total += 1


def get_metrics() -> dict:
    """Return a snapshot of current queue metrics."""
    with _lock:
        return {
            "queue_size":       _q.qsize(),
            "enqueued_total":   _enqueued_total,
            "processed_total":  _processed_total,
            "failed_total":     _failed_total,
            "queue_history":    list(_queue_history),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _snapshot_depth() -> None:
    """Append a (timestamp, depth) data-point to the history deque."""
    _queue_history.append({
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "depth":     _q.qsize(),
    })


def start_history_sampler(interval: float = 5.0) -> None:
    """
    Background thread that records queue depth every `interval` seconds.
    Call once at startup so the chart always has fresh data even when
    no events are flowing.
    """
    def _sample():
        while True:
            _snapshot_depth()
            time.sleep(interval)

    t = threading.Thread(target=_sample, daemon=True, name="QueueHistorySampler")
    t.start()
    log.info("Queue history sampler started (interval=%.1fs)", interval)
