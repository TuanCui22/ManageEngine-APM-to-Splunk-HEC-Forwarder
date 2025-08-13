# ManageEngine APM → Splunk HEC Forwarder

This Python script fetches monitor data from **ManageEngine Application Manager (APM)** and sends it to **Splunk HTTP Event Collector (HEC)**.

It runs in a loop at a user-defined interval and supports filtering monitors by specific attributes.

---

## Features

- Fetch monitor list from ManageEngine APM via REST API (XML)
- Filter monitors based on attribute values (e.g., availability)
- Retrieve detailed monitor and child monitor data
- Send structured events to Splunk via HEC
- Interval-based execution (e.g., every `30s` or `5m`)
- Logging for better observability
- Configurable via constants in the script or environment variables

---

## Requirements

- Python **3.7+**
- Splunk HEC enabled with a valid token
- ManageEngine APM server with API access

---

## Installation

1. **Clone this repository**
    ```bash
    git clone https://github.com/<your-username>/me-apm-to-splunk.git
    cd me-apm-to-splunk
    ```

2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **Edit configuration**  
   Open `apm_to_splunk.py` and update:
    ```python
    APM_SERVER = "http://<apm-server>:9090"
    API_KEY = "<your-apm-api-key>"

    SPLUNK_HEC_URL = "https://<splunk-server>:8088/services/collector"
    SPLUNK_HEC_TOKEN = "<your-splunk-hec-token>"
    SPLUNK_INDEX = "<splunk-index>"
    ```

---

## Usage

Run the script and enter an interval when prompted:
```bash
python apm_to_splunk.py


Environment Variables (Optional)

export APM_SERVER="http://apm-server:9090"
export API_KEY="your-apm-api-key"
export SPLUNK_HEC_URL="https://splunk-server:8088/services/collector"
export SPLUNK_HEC_TOKEN="your-token"
export SPLUNK_INDEX="me-apm"


Example Run

Enter the interval to run the script repeatedly (e.g., 30s or 5m): 1m
Running every 60 seconds. Press Ctrl+C to stop.
Example Output
csharp
Copy
Edit
[INFO] Fetching list of monitors...
[INFO] After filtering, found 3 monitors:
[INFO] RESOURCEID: 101, DISPLAYNAME: WebServer-1, HOSTIP: 192.168.1.10
[INFO] Fetching monitor data for RESOURCEID: 101
[INFO] Successfully sent event to Splunk HEC!
----------------------------------------------------
[INFO] Sleeping for 60 seconds...


Example Splunk Event

{ [-]
   AVAILABILITYSEVERITY: -
   Attributes: { [-]
     CPU Utilization (%): 0
     I/O Wait Time (%): 0
     Idle Time (%): 100
     Steal Time (%): 0
     System Time (%): 0
     User Time (%): 0
   }
   DISPLAYNAME: CPU Core-CPU_0
   HEALTHSEVERITY: -
   RESOURCEID: 10000283
   host: 192.168.33.46
   source: CPU Core-CPU_0
}



Disclaimer
This script is provided as-is without warranty.
Test in a non-production environment before deploying in production.


License
This project is licensed under the MIT License.

Author
👤 Thanh Tuan
💼 GitHub: @TuanCui22
