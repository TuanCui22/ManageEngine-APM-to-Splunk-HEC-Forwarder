Here’s a **professional README.md** you can drop into your GitHub repo so it looks clean and complete:

---

````markdown
# ManageEngine APM → Splunk HEC Forwarder

This Python script fetches monitor data from **ManageEngine Application Manager (APM)** and sends it to **Splunk HTTP Event Collector (HEC)**.

It runs in a loop at a user-defined interval and supports filtering monitors by specific attributes.

---

## Features

- ✅ Fetch monitor list from ManageEngine APM via REST API (XML).
- ✅ Filter monitors based on attribute values (e.g., availability).
- ✅ Retrieve detailed monitor and child monitor data.
- ✅ Send structured events to Splunk via HEC.
- ✅ Interval-based execution (e.g., every `30s` or `5m`).
- ✅ Logging for better observability.
- ✅ Configurable via constants in the script or environment variables.

---

## Requirements

- Python **3.7+**
- Splunk HEC enabled with a valid token.
- ManageEngine APM server with API access.

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
````

Example prompt:

```
Enter the interval (e.g., 30s or 5m): 1m
```

This will run every **1 minute** until you press `Ctrl+C`.

---

## Example Output

```
2025-08-13 10:00:00 [INFO] Fetching list of monitors...
2025-08-13 10:00:01 [INFO] Found 5 monitors after filtering.
2025-08-13 10:00:02 [INFO] Fetching monitor data for RESOURCEID: 123456
2025-08-13 10:00:03 [INFO] Sent event to Splunk successfully.
```

---

## Environment Variables (Optional)

Instead of editing the script, you can set environment variables:

```bash
export APM_SERVER="http://apm-server:9090"
export API_KEY="your-apm-api-key"
export SPLUNK_HEC_URL="https://splunk-server:8088/services/collector"
export SPLUNK_HEC_TOKEN="your-token"
export SPLUNK_INDEX="me-apm"
```

---

## Project Structure

```
me-apm-to-splunk/
│
├── apm_to_splunk.py    # Main script
├── requirements.txt    # Python dependencies
├── README.md           # Documentation
└── .gitignore          # Git ignore file
```

---

## Dependencies

* `requests` – for HTTP requests.
* `urllib3` – to handle HTTPS warnings.
* `logging` – for structured logging.
* `xml.etree.ElementTree` – to parse XML from APM.

Install them with:

```bash
pip install requests urllib3
```

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Author

👤 **Thanh Tuan**
💼 GitHub: [@TuanCui22](https://github.com/TuanCui22)

---

## Disclaimer

This script is provided **as-is** without warranty. Use at your own risk and test in a non-production environment before deployment.

```

---

If you want, I can also give you a matching **`.gitignore`** and **`requirements.txt`** so your GitHub repo is instantly clean and ready for cloning.  
Do you want me to prepare those too?
```
