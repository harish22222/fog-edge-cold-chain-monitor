Smart Cold-Chain Delivery Monitoring System

Project Overview
This project simulates a real-time cold-chain monitoring system using Fog and Cloud computing. It includes sensor simulation, fog processing, a cloud backend, and a dashboard for visualization. The system is designed to monitor environmental conditions such as temperature, humidity, door status, and vibration, and to generate alerts when abnormal conditions are detected.

Requirements
Make sure the following are installed on your system:
Python 3.x
pip (Python package manager)

Install the required libraries using the following command:
pip install flask requests streamlit pandas

Execution Steps
All components should be run in separate terminals.

Step 1: Run Sensor Simulator
Navigate to the sensors folder:
cd sensors

Run the simulator:
python sensor_simulator.py

This will continuously generate sensor data such as temperature, humidity, door status, and vibration.

Step 2: Run Fog Node
Open a new terminal and navigate to the fog folder:
cd fog

Run the fog application:
python fog_app.py

The fog node receives sensor data, checks for abnormal values, generates alerts, and sends processed data to AWS SQS.

Step 3: Run Backend API
Open a new terminal and navigate to the backend folder:
cd backend

Run the backend application:
python app.py

The backend consumes messages from AWS SQS, processes the data, and stores it in a SQLite database. It also provides API endpoints for accessing system data.

Step 4: Run Dashboard
Open a new terminal and navigate to the dashboard folder:
cd dashboard

Run the dashboard:
streamlit run app.py

The dashboard will open in a browser and display system health, alerts, graphs, and logs in real time.

AWS Setup
Make sure an AWS SQS queue is created and AWS credentials are configured on your system.

You can configure AWS using:
aws configure

Enter your access key, secret key, and region when prompted.

System Flow
Sensor data is generated and sent to the fog node. The fog node processes the data and sends it to AWS SQS. The backend retrieves the data from SQS, stores it in the database, and the dashboard displays the information.

Notes
All components must be running at the same time for the system to work correctly.
If the dashboard does not update, restart the fog node and backend services.
Ensure that the correct SQS queue URL is configured in the application.

Project Structure
sensors folder contains the sensor simulator
fog folder contains the fog node implementation
backend folder contains the backend API
dashboard folder contains the Streamlit dashboard

End of README
