# ManageEngine APM → Splunk HEC Forwarder

A Python script that pulls monitor data from **ManageEngine Application Manager (APM)** and sends it to **Splunk HTTP Event Collector (HEC)**.  

It can run continuously at a set interval, with optional filtering to only send data from monitors that match specific attributes.

## Workflow

![Workflow Diagram](WF.png)

## Features

- Fetch monitor list from ManageEngine APM via REST API (XML)
- Filter monitors by attribute values (e.g., availability)
- Retrieve detailed data for monitors and their child monitors
- Send structured events to Splunk via HEC
- Run at a fixed interval (e.g., `30s`, `1m`, `5m`)
- Logging for visibility and troubleshooting
- Configuration via script constants or environment variables

## Requirements

- Python **3.7+**
- Splunk HEC enabled with a valid token
- ManageEngine APM server with API access enabled

## Installation

1. **Clone the repository**
    ```bash
    git clone https://github.com/TuanCui22/ManageEngine-APM-to-Splunk-HEC-Forwarder.git
    cd ManageEngine-APM-to-Splunk-HEC-Forwarder
    ```

2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **Configure settings**
    ```python
    APM_SERVER = "http://<apm-server>:9090"
    API_KEY = "<your-apm-api-key>"
    SPLUNK_HEC_URL = "https://<splunk-server>:8088/services/collector"
    SPLUNK_HEC_TOKEN = "<your-splunk-hec-token>"
    SPLUNK_INDEX = "<splunk-index>"
    ```

## Usage

### Run with script prompts
```bash
python apm_to_splunk.py
```

### Run with environment variables (optional)
```bash
export APM_SERVER="http://apm-server:9090"
export API_KEY="your-apm-api-key"
export SPLUNK_HEC_URL="https://splunk-server:8088/services/collector"
export SPLUNK_HEC_TOKEN="your-token"
export SPLUNK_INDEX="me-apm"
python apm_to_splunk.py
```

### Example run
```
Enter the interval to run the script repeatedly (e.g., 30s or 5m): 1m
[INFO] Fetching list of monitors...
[INFO] After filtering, found 3 monitors:
[INFO] RESOURCEID: 101, DISPLAYNAME: WebServer-1, HOSTIP: 192.168.1.10
[INFO] Fetching monitor data for RESOURCEID: 101
[INFO] Successfully sent event to Splunk HEC!
----------------------------------------------------
[INFO] Sleeping for 60 seconds...
```

### Example Splunk event
```json
{
  "AVAILABILITYSEVERITY": "-",
  "Attributes": {
    "CPU Utilization (%)": 0,
    "I/O Wait Time (%)": 0,
    "Idle Time (%)": 100,
    "Steal Time (%)": 0,
    "System Time (%)": 0,
    "User Time (%)": 0
  },
  "DISPLAYNAME": "CPU Core-CPU_0",
  "HEALTHSEVERITY": "-",
  "RESOURCEID": 10000283,
  "host": "192.168.33.46",
  "source": "CPU Core-CPU_0"
}
```

## Disclaimer
This script is provided as is, without warranty.  
Always test in a non-production environment before deploying to production.

## License
MIT License

## Author
Thanh Tuan  
GitHub: https://github.com/TuanCui22
