"""
=============================================================================
DASHBOARD LAYER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Streamlit Dashboard
Layer      : Presentation / Dashboard
Description:
    Live monitoring dashboard showing:
    - System health (API, Lambda worker, queue)
    - Queue depth over time (chart)
    - KPI metrics (events, alerts, temperature, humidity)
    - Environmental trend charts
    - Recent critical alerts panel
    - Raw event log table

    Auto-refreshes every 5 seconds.

Author     : Cold-Chain Monitor System
Date       : 2026-03-11
Usage      : streamlit run app.py
=============================================================================
"""

import time
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Cold-Chain Monitor",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS for premium look
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Dark background */
    .stApp { background: #0d1117; color: #e6edf3; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px;
    }
    [data-testid="stMetricLabel"] { color: #8b949e; font-size: 0.8rem; }
    [data-testid="stMetricValue"] { color: #58a6ff; font-size: 1.6rem; font-weight: 700; }

    /* Alert boxes */
    .alert-critical {
        background: #3d1a1a; border-left: 4px solid #f85149;
        border-radius: 6px; padding: 10px 14px; margin: 6px 0;
    }
    .alert-warning {
        background: #2d2209; border-left: 4px solid #e3b341;
        border-radius: 6px; padding: 10px 14px; margin: 6px 0;
    }
    .status-dot-green { color: #3fb950; font-size: 1.1rem; }
    .status-dot-red   { color: #f85149; font-size: 1.1rem; }
    .status-dot-yellow { color: #e3b341; font-size: 1.1rem; }

    /* Section headers */
    h2 { color: #58a6ff !important; }
    h3 { color: #79c0ff !important; }

    /* Divider */
    hr { border-color: #30363d; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL      = "http://127.0.0.1:8000"
REFRESH_RATE = 5   # seconds


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=2)
def fetch_health():
    try:
        r = requests.get(f"{API_URL}/health", timeout=2)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=2)
def fetch_queue_status():
    try:
        r = requests.get(f"{API_URL}/queue-status", timeout=2)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=2)
def fetch_summary():
    try:
        r = requests.get(f"{API_URL}/summary", timeout=2)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=2)
def fetch_events(limit=100, only_alerts=False):
    try:
        url = f"{API_URL}/events?limit={limit}"
        if only_alerts:
            url += "&alerts=true"
        r = requests.get(url, timeout=2)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Fetch all data
# ---------------------------------------------------------------------------
health       = fetch_health()
queue_status = fetch_queue_status()
summary      = fetch_summary()
events       = fetch_events(limit=100)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("❄️ Smart Cold-Chain Delivery Monitor")

# ============================================================
# LIVE SYSTEM MONITOR
# ============================================================
st.subheader("Live System Monitor")

total_events = len(events) if events else 0
if events:
    _df_live = pd.DataFrame(events)
    active_devices = _df_live["device_id"].nunique() if "device_id" in _df_live.columns else 0
else:
    active_devices = 0

current_time = datetime.now().strftime("%H:%M:%S")

lm_col1, lm_col2, lm_col3 = st.columns(3)
with lm_col1:
    st.metric("Total Sensor Events", total_events)
with lm_col2:
    st.metric("Active Devices", active_devices)
with lm_col3:
    st.metric("Last Refresh Time", current_time)

# ---------------------------------------------------------------------------
# Connection guard
# ---------------------------------------------------------------------------
if not health:
    st.error("⚠️ Cannot connect to the Cloud Backend API. Is `api.py` running on port 8000?")
    st.stop()

st.divider()

# ============================================================
# COMPONENT STATUS
# ============================================================
st.subheader("Component Status")
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.success("Sensor Simulator Running")
with c2:
    st.success("Fog Node Active")
with c3:
    st.success("API Gateway Online")
with c4:
    st.success("SQS Queue Active")
with c5:
    st.success("Lambda Worker Running")

st.divider()

# ============================================================
# ROW 1: System Health Status
# ============================================================
st.subheader("⚙️ System Health")

h_col1, h_col2, h_col3, h_col4 = st.columns(4)

with h_col1:
    api_online = health.get("status") == "healthy"
    dot = "🟢" if api_online else "🔴"
    st.markdown(f"**{dot} API Gateway**")
    st.caption("Port 8000 — Flask REST API")
    st.metric("DB Records", health.get("db_records", 0))

with h_col2:
    processed = health.get("processed_total", 0)
    enqueued  = health.get("enqueued_total", 0)
    worker_ok = processed > 0 or enqueued == 0
    dot = "🟢" if worker_ok else "🟡"
    st.markdown(f"**{dot} Lambda Worker**")
    st.caption("Polling queue_manager")
    st.metric("Events Processed", processed)

with h_col3:
    q_depth = health.get("queue_depth", 0)
    q_dot   = "🟢" if q_depth < 10 else ("🟡" if q_depth < 50 else "🔴")
    st.markdown(f"**{q_dot} SQS Queue**")
    st.caption("Simulated queue depth")
    st.metric("Queue Depth", q_depth)

with h_col4:
    failed = health.get("failed_total", 0)
    f_dot  = "🟢" if failed == 0 else "🔴"
    st.markdown(f"**{f_dot} Error Rate**")
    st.caption("Lambda failures")
    st.metric("Failed Events", failed)

st.divider()

# ============================================================
# ROW 2: KPI Metrics
# ============================================================
st.subheader("📊 Key Performance Indicators")

# Calculate active devices from live event data
if events:
    _df_kpi = pd.DataFrame(events)
    active_devices = _df_kpi["device_id"].nunique() if "device_id" in _df_kpi.columns else 0
else:
    active_devices = 0

k_col1, k_col2, k_col3, k_col4, k_col5, k_col6 = st.columns(6)

with k_col1:
    st.metric("Total Events", summary.get("total_events", 0) if summary else 0)
with k_col2:
    st.metric("Alert Events", summary.get("alert_events", 0) if summary else 0)
with k_col3:
    avg_t = summary.get("avg_temperature", "—") if summary else "—"
    st.metric("Avg Temp", f"{avg_t} °C")
with k_col4:
    avg_h = summary.get("avg_humidity", "—") if summary else "—"
    st.metric("Avg Humidity", f"{avg_h} %")
with k_col5:
    max_t = summary.get("max_temperature", "—") if summary else "—"
    st.metric("Max Temp", f"{max_t} °C")
with k_col6:
    st.metric("Active Devices", active_devices)

st.divider()

# ============================================================
# ROW 3: Queue Depth Chart | Alert Breakdown
# ============================================================
q_col, alert_col = st.columns([2, 1])

with q_col:
    st.subheader("📉 Queue Depth Over Time")
    if queue_status and queue_status.get("queue_history"):
        qdf = pd.DataFrame(queue_status["queue_history"])
        qdf["timestamp"] = pd.to_datetime(qdf["timestamp"])
        qdf = qdf.sort_values("timestamp").set_index("timestamp")
        st.line_chart(qdf["depth"], color="#f0883e")
        st.caption(f"Current depth: **{queue_status.get('queue_size', 0)}** | "
                   f"Last updated: {queue_status.get('timestamp', '—')}")
    else:
        st.info("Queue history will appear here once events start flowing.")

with alert_col:
    st.subheader("🚨 Alert Breakdown")
    if summary and summary.get("alert_breakdown"):
        breakdown = summary["alert_breakdown"]
        for alert_type, count in breakdown.items():
            colour = {
                "SPOILAGE_RISK": "#f85149",
                "TAMPER_ALERT":  "#e3b341",
                "SHOCK_DAMAGE":  "#ff7b72",
                "HIGH_HUMIDITY": "#58a6ff",
            }.get(alert_type, "#8b949e")
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;'
                f'background:#161b22;border-left:4px solid {colour};'
                f'border-radius:6px;padding:8px 12px;margin:4px 0;">'
                f'<span>{alert_type}</span>'
                f'<strong>{count}</strong></div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("No alert data yet.")

st.divider()

# ============================================================
# ROW 4: Environmental Trends | Critical Alerts Feed
# ============================================================
trend_col, feed_col = st.columns([2, 1])

with trend_col:
    st.subheader("📈 Environmental Trends (Latest 50 Readings)")
    if events:
        df = pd.DataFrame(events)
        if "fog_timestamp" in df.columns:
            df["time"] = pd.to_datetime(df["fog_timestamp"], errors="coerce")

        if "time" in df.columns and "temperature" in df.columns:
            chart_df = df.dropna(subset=["time"]).sort_values("time").set_index("time")

            st.markdown("**Temperature (°C)** — threshold: 8 °C")
            st.line_chart(chart_df["temperature"], color="#f85149")

            if "humidity" in chart_df.columns:
                st.markdown("**Humidity (%)** — threshold: 75 %")
                st.line_chart(chart_df["humidity"], color="#58a6ff")
        else:
            st.info("Waiting for timestamped readings...")
    else:
        st.info("Waiting for sensor data...")

with feed_col:
    st.subheader("🔴 Recent Critical Alerts")
    alerts_only = [e for e in events if e.get("alert_count", 0) > 0]

    if alerts_only:
        for a in alerts_only[:6]:
            device     = a.get("device_id", "?")
            fog_ts     = a.get("fog_timestamp", "")
            time_str   = fog_ts.split("T")[1] if "T" in fog_ts else fog_ts
            alert_list = a.get("alerts", [])
            severity   = a.get("severity", "WARNING")

            sev_colour = "#f85149" if severity == "CRITICAL" else "#e3b341"
            badges = " ".join([
                f'<span style="background:#21262d;border:1px solid {sev_colour};'
                f'border-radius:4px;padding:2px 6px;font-size:0.75rem;">{al}</span>'
                for al in alert_list
            ])
            st.markdown(
                f'<div style="background:#161b22;border-left:4px solid {sev_colour};'
                f'border-radius:6px;padding:10px;margin:6px 0;">'
                f'<div style="font-size:0.8rem;color:#8b949e;">{time_str} | {device}</div>'
                f'<div style="margin-top:6px;">{badges}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.success("✅ No recent alerts. Everything is operating normally.")

st.divider()

# ============================================================
# FOG VS CLOUD EXPLANATION
# ============================================================
st.subheader("Fog vs Cloud Processing")
st.markdown("""
**Fog Layer Responsibilities**
- Real-time anomaly detection
- Immediate alert generation
- Reduce network traffic

**Cloud Layer Responsibilities**
- Store historical sensor data
- Perform analytics
- Provide dashboards and monitoring
""")

st.divider()

# ============================================================
# ROW 6: Raw Event Log
# ============================================================
st.subheader("📋 Raw Sensor Event Log")
if events:
    display_cols = [
        "fog_timestamp", "device_id", "temperature", "humidity",
        "door_open", "vibration", "alert_count", "severity", "alerts"
    ]
    df_raw = pd.DataFrame(events)
    available = [c for c in display_cols if c in df_raw.columns]
    st.dataframe(df_raw[available], use_container_width=True, hide_index=True)
else:
    st.write("No raw event logs available yet.")

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------
st.divider()
if st.checkbox("Auto-refresh every 5 seconds", value=True):
    time.sleep(REFRESH_RATE)
    st.rerun()
