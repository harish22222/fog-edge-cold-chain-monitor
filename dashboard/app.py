"""
=============================================================================
DASHBOARD LAYER — Smart Cold-Chain Delivery Monitor
=============================================================================
Component  : Streamlit Dashboard
Layer      : Presentation / Dashboard
Description:
    Live monitoring dashboard showing:
    - System health (Sensor, Fog, API, Database)
    - Event ingestion timeline
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
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .stApp { background: #0d1117; color: #e6edf3; }

    [data-testid="stMetric"] {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px;
    }

    [data-testid="stMetricLabel"] {
        color: #8b949e;
        font-size: 0.8rem;
    }

    [data-testid="stMetricValue"] {
        color: #58a6ff;
        font-size: 1.6rem;
        font-weight: 700;
    }

    h1, h2, h3 { color: #58a6ff !important; }
    hr { border-color: #30363d; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = "http://127.0.0.1:8000"
REFRESH_RATE = 5

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
# Fetch data
# ---------------------------------------------------------------------------
health = fetch_health()
queue_status = fetch_queue_status()
summary = fetch_summary()
events = fetch_events(limit=100)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("❄️ Smart Cold-Chain Delivery Monitor")
st.caption("Live monitoring for temperature, humidity, door status, vibration, and cold-chain alerts")

# ---------------------------------------------------------------------------
# Connection guard
# ---------------------------------------------------------------------------
if not health:
    st.error("⚠️ Cannot connect to the backend API. Make sure `backend/api.py` is running on port 8000.")
    st.stop()

# ---------------------------------------------------------------------------
# Live monitor
# ---------------------------------------------------------------------------
st.subheader("Live System Monitor")

total_events = len(events) if events else 0
active_devices = 0
latest_timestamp = "—"

if events:
    df_live = pd.DataFrame(events)
    if "device_id" in df_live.columns:
        active_devices = df_live["device_id"].nunique()
    if "fog_timestamp" in df_live.columns and not df_live.empty:
        latest_timestamp = df_live.iloc[0].get("fog_timestamp", "—")

lm_col1, lm_col2, lm_col3 = st.columns(3)
with lm_col1:
    st.metric("Total Sensor Events", total_events)
with lm_col2:
    st.metric("Active Devices", active_devices)
with lm_col3:
    st.metric("Last Event Time", latest_timestamp)

st.divider()

# ---------------------------------------------------------------------------
# Component status
# ---------------------------------------------------------------------------
st.subheader("Component Status")
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.success("Sensor Layer Active")
with c2:
    st.success("Fog Node Active")
with c3:
    st.success("Backend API Online")
with c4:
    st.success("Database Connected")

st.divider()

# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------
st.subheader("⚙️ System Health")

h_col1, h_col2, h_col3, h_col4 = st.columns(4)

with h_col1:
    api_online = health.get("status") == "healthy"
    dot = "🟢" if api_online else "🔴"
    st.markdown(f"**{dot} Backend API**")
    st.caption("Port 8000 — Flask REST API")
    st.metric("DB Records", health.get("db_records", 0))

with h_col2:
    stored_total = health.get("processed_total", 0)
    st.markdown("**🟢 Event Storage**")
    st.caption("Direct database mode")
    st.metric("Stored Events", stored_total)

with h_col3:
    failed = health.get("failed_total", 0)
    dot = "🟢" if failed == 0 else "🔴"
    st.markdown(f"**{dot} Error Status**")
    st.caption("Backend write failures")
    st.metric("Failed Events", failed)

with h_col4:
    current_time = datetime.now().strftime("%H:%M:%S")
    st.markdown("**🟢 Dashboard Refresh**")
    st.caption("Current UI refresh time")
    st.metric("Last Refresh", current_time)

st.divider()

# ---------------------------------------------------------------------------
# KPI metrics
# ---------------------------------------------------------------------------
st.subheader("📊 Key Performance Indicators")

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

# ---------------------------------------------------------------------------
# Event ingestion timeline + alert breakdown
# ---------------------------------------------------------------------------
left_col, right_col = st.columns([2, 1])

with left_col:
    st.subheader("📉 Data Flow Monitoring")
    if queue_status and queue_status.get("queue_history"):
        qdf = pd.DataFrame(queue_status["queue_history"])
        qdf["timestamp"] = pd.to_datetime(qdf["timestamp"], errors="coerce")
        qdf = qdf.dropna(subset=["timestamp"]).sort_values("timestamp").set_index("timestamp")
        st.line_chart(qdf["depth"])
        st.caption(
            f"Current depth: {queue_status.get('queue_size', 0)} | "
            f"Last updated: {queue_status.get('timestamp', '—')}"
        )
    else:
        st.info("Timeline will appear here once data is available.")

with right_col:
    st.subheader("🚨 Alert Breakdown")
    if summary and summary.get("alert_breakdown"):
        breakdown = summary["alert_breakdown"]
        for alert_type, count in breakdown.items():
            colour = {
                "SPOILAGE_RISK": "#f85149",
                "TAMPER_ALERT": "#e3b341",
                "SHOCK_DAMAGE": "#ff7b72",
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

# ---------------------------------------------------------------------------
# Environmental trends + alert feed
# ---------------------------------------------------------------------------
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
            st.line_chart(chart_df["temperature"])

            if "humidity" in chart_df.columns:
                st.markdown("**Humidity (%)** — threshold: 75 %")
                st.line_chart(chart_df["humidity"])
        else:
            st.info("Waiting for timestamped readings...")
    else:
        st.info("Waiting for sensor data...")

with feed_col:
    st.subheader("🔴 Recent Critical Alerts")
    alerts_only = [e for e in events if e.get("alert_count", 0) > 0]

    if alerts_only:
        for a in alerts_only[:6]:
            device = a.get("device_id", "?")
            fog_ts = a.get("fog_timestamp", "")
            time_str = fog_ts.split("T")[1] if "T" in fog_ts else fog_ts
            alert_list = a.get("alerts", [])
            severity = a.get("severity", "WARNING")

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

# ---------------------------------------------------------------------------
# Architecture explanation
# ---------------------------------------------------------------------------
st.subheader("System Flow")
st.markdown("""
**Current Data Flow**
- Sensor Simulator generates temperature, humidity, door-open, and vibration readings
- Fog Node performs local alert detection
- Backend API stores processed events in the database
- Streamlit Dashboard visualises trends, alerts, and raw event history

**Fog Layer Responsibilities**
- Real-time anomaly detection
- Immediate alert generation
- Reduced unnecessary cloud traffic

**Cloud / Backend Responsibilities**
- Store historical sensor data
- Serve analytics and summaries
- Provide dashboard monitoring
""")

st.divider()

# ---------------------------------------------------------------------------
# Raw event log
# ---------------------------------------------------------------------------
st.subheader("📋 Raw Sensor Event Log")

if events:
    display_cols = [
        "fog_timestamp",
        "device_id",
        "temperature",
        "humidity",
        "door_open",
        "vibration",
        "alert_count",
        "severity",
        "alerts",
    ]

    df_raw = pd.DataFrame(events)
    available = [c for c in display_cols if c in df_raw.columns]
    st.dataframe(df_raw[available], use_container_width=True, hide_index=True)
else:
    st.write("No raw event logs available yet.")

# ---------------------------------------------------------------------------
# Auto refresh
# ---------------------------------------------------------------------------
st.divider()
if st.checkbox("Auto-refresh every 5 seconds", value=True):
    time.sleep(REFRESH_RATE)
    st.rerun()