# ManageEngine APM → Splunk HEC Forwarder

This Python script fetches monitor data from **ManageEngine Application Manager (APM)** and sends it to **Splunk HTTP Event Collector (HEC)**.

It runs in a loop at a user-defined interval and supports filtering monitors by specific attributes.

---

## Features

- ✅ Fetch monitor list from ManageEngine APM via REST API (XML)
- ✅ Filter monitors based on attribute values (e.g., availability)
- ✅ Retrieve detailed monitor and child monitor data
- ✅ Send structured events to Splunk via HEC
- ✅ Interval-based execution (e.g., every `30s` or `5m`)
- ✅ Logging for better observability
- ✅ Configurable via constants in the script or environment variables

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
