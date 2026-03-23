#!/bin/bash

echo "Starting Cold Chain Monitoring System..."

source venv/bin/activate

echo "Starting Backend API..."
python backend/api.py &

sleep 2

echo "Starting Fog Node..."
python fog/fog_node.py &

sleep 2

echo "Starting Sensor Simulator..."
python sensors/sensor_simulator.py &

sleep 2

echo "Starting Dashboard..."
streamlit run dashboard/app.py --server.port 8080 --server.address 0.0.0.0