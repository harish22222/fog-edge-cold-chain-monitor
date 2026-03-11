# Smart Cold-Chain Delivery Monitor

A complete, scalable IoT system that simulates a **full AWS serverless architecture** locally using Python. Designed for a Master's-level Fog and Edge Computing assignment, it demonstrates a multi-tier pipeline from edge sensors through fog processing to a cloud backend and live dashboard.

---

## 🏗️ Architecture

```
┌─────────────────┐     HTTP POST      ┌─────────────────┐
│  Sensor Layer   │ ─────────────────► │   Fog Node      │
│  (Edge / IoT)   │                    │  (Fog Layer)    │
│sensor_simulator │                    │  fog_node.py    │
└─────────────────┘                    └────────┬────────┘
                                                │
                                  Batch + GZIP POST
                                                │
                                                ▼
                                       ┌────────────────┐
                                       │  API Gateway   │
                                       │  (api.py)      │
                                       │  Port 8000     │
                                       └───────┬────────┘
                                               │
                                        Enqueue event
                                               │
                                               ▼
                                       ┌────────────────┐
                                       │  SQS Queue     │
                                       │ queue_manager  │
                                       │  (in-memory)   │
                                       └───────┬────────┘
                                               │
                                        Poll + process
                                               │
                                               ▼
                                       ┌────────────────┐
                                       │ Lambda Worker  │
                                       │lambda_function │
                                       │  .py           │
                                       └───────┬────────┘
                                               │
                                          Persist
                                               │
                                               ▼
                                       ┌────────────────┐
                                       │   SQLite DB    │  ≈ DynamoDB
                                       │ coldchain_     │
                                       │ events.db      │
                                       └───────┬────────┘
                                               │
                                          REST reads
                                               │
                                               ▼
                                       ┌────────────────┐
                                       │   Dashboard    │
                                       │   (Streamlit)  │
                                       │   Port 8501    │
                                       └────────────────┘
```

---

## 📂 Project Structure

```
coldchain-monitor/
├── backend/
│   ├── api.py               # API Gateway simulation (Flask, port 8000)
│   ├── queue_manager.py     # SQS simulation (in-memory queue + metrics)
│   ├── lambda_function.py   # Lambda worker (local polling + AWS handler)
│   └── coldchain_events.db  # SQLite database (auto-created)
├── fog/
│   └── fog_node.py          # Fog Layer (Flask, port 5000)
├── sensors/
│   └── sensor_simulator.py  # Edge IoT sensor simulation
├── dashboard/
│   └── app.py               # Streamlit monitoring dashboard (port 8501)
├── requirements.txt
└── README.md
```

---

## 🧩 Component Responsibilities

| Component | Layer | AWS Equivalent | Description |
|---|---|---|---|
| `sensor_simulator.py` | Edge | IoT Core / Greengrass | Generates sensor readings every 5s with 5 simulation modes |
| `fog_node.py` | Fog | Greengrass Edge Runtime | Local alert detection, batching, gzip compression, latency metrics |
| `api.py` | Cloud | API Gateway | REST ingest endpoint; pushes events to the SQS queue |
| `queue_manager.py` | Cloud | SQS | Thread-safe queue with depth tracking and history |
| `lambda_function.py` | Cloud | Lambda | Polls queue, enriches events, persists to DB, tracks throughput |
| `dashboard/app.py` | Presentation | CloudWatch / QuickSight | Live Streamlit dashboard with system health and charts |

---

## 📡 Data Flow

1. **Sensor → Fog** — Every 5s the sensor simulator POSTs a JSON payload to the Fog Node at port 5000.
2. **Fog processing** — The fog node runs alert detection locally (<1 ms latency), buffers events into batches of 5, then gzip-compresses and forwards each batch to the backend.
3. **API → Queue** — The API gateway receives events via `POST /events`, assigns a unique `event_id`, and pushes them onto the in-memory SQS queue.
4. **Lambda polling** — The Lambda worker continuously polls the queue, enriches events (re-validates alerts, adds severity), and persists records to SQLite.
5. **Dashboard reads** — The Streamlit dashboard polls the API every 5s for live data, queue metrics, and system health status.

---

## 🚀 How to Run Locally

### 0. Install prerequisites

```bash
cd coldchain-monitor
pip install -r requirements.txt
```

### 1. Start the API Gateway

```bash
# Terminal 1
cd backend
python api.py
```

### 2. Start the Lambda Worker

```bash
# Terminal 2
cd backend
python lambda_function.py
```

### 3. Start the Fog Node

```bash
# Terminal 3
cd fog
python fog_node.py
```

### 4. Start the Sensor Simulator

```bash
# Terminal 4
cd sensors
python sensor_simulator.py
```

### 5. Start the Dashboard

```bash
# Terminal 5
cd dashboard
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

---

## 📊 API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/events` | Receive enriched event from Fog Node → enqueue |
| `GET` | `/events` | Retrieve stored events (supports `limit`, `device`, `alerts` filters) |
| `GET` | `/summary` | Aggregated KPIs (total events, avg temp, alert breakdown) |
| `GET` | `/health` | Server, queue, and database health check |
| `GET` | `/metrics` | Detailed queue + Lambda throughput metrics |
| `GET` | `/queue-status` | Queue depth + recent depth history (for chart) |

---

## 🛰️ Sensor Simulation Modes

| Mode | Probability | Description |
|---|---|---|
| `normal` | 62 % | Safe readings within cold-chain thresholds |
| `temp_spike` | 20 % | Temperature > 8 °C → SPOILAGE_RISK |
| `high_vibration` | 10 % | Vibration > 70 → SHOCK_DAMAGE |
| `burst` | 3 % | 10 events sent rapidly to stress-test the queue |
| `anomaly` | 5 % | All sensors breached → CRITICAL severity |

---

## ☁️ Future Deployment on AWS

The architecture is designed to map directly to AWS services with minimal changes:

| Local Component | AWS Service |
|---|---|
| `sensor_simulator.py` | Physical IoT devices with AWS IoT Core SDK |
| `fog_node.py` | AWS Greengrass Core (edge runtime) |
| `api.py` (Flask) | AWS API Gateway (REST API) |
| `queue_manager.py` | AWS SQS Standard Queue |
| `lambda_function.py` → `lambda_handler()` | AWS Lambda (SQS event source mapping) |
| `coldchain_events.db` | AWS DynamoDB table |
| `dashboard/app.py` | AWS QuickSight / Hosted Streamlit on EC2 |

**Lambda deployment steps:**
```bash
zip lambda.zip backend/lambda_function.py
aws lambda create-function \
    --function-name cold-chain-processor \
    --runtime python3.11 \
    --role arn:aws:iam::<account>:role/lambda-sqs-dynamo \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://lambda.zip
# Then add SQS trigger in the Lambda console
```
