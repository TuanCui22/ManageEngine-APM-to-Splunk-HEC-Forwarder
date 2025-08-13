#!/usr/bin/env python3
"""
ManageEngine APM to Splunk HEC Forwarder
----------------------------------------
This script:
  1. Fetches a list of monitors from ManageEngine APM.
  2. Filters them based on given criteria.
  3. Retrieves monitor data for each.
  4. Sends the results to Splunk via HTTP Event Collector (HEC).

Author: Thanh Tuan
License: MIT
"""

import requests
import xml.etree.ElementTree as ET
import json
import urllib3
import time
import logging
from typing import List, Dict, Any

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------
# Configuration
# ---------------------------
APM_SERVER = "http://<apm-server>:9090"
API_KEY = "<your-apm-api-key>"

SPLUNK_HEC_URL = "https://<splunk-server>:8088/services/collector"
SPLUNK_HEC_TOKEN = "<your-splunk-hec-token>"
SPLUNK_INDEX = "<splunk-index>"

FILTERS = {
    "AVAILABILITYATTRIBUTEID": ["700"]
}

# ---------------------------
# Logging setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ---------------------------
# Functions
# ---------------------------
def apm_api_list_monitors() -> str:
    """Fetch the list of monitors from ManageEngine APM."""
    url = f"{APM_SERVER}/AppManager/xml/ListMonitor"
    params = {'apikey': API_KEY, 'type': 'all'}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.text


def parse_list_monitor_xml(xml_text: str) -> List[Dict[str, str]]:
    """Parse the XML and extract monitor attributes."""
    root = ET.fromstring(xml_text)
    monitors = []
    response_node = root.find("./result/response")
    if not response_node:
        logging.warning("No <response> node found in ListMonitor XML.")
        return monitors

    for monitor in response_node.findall('Monitor'):
        monitors.append(monitor.attrib)
    return monitors


def filter_monitors(monitors: List[Dict[str, str]], filters: Dict[str, Any]) -> List[Dict[str, str]]:
    """Filter monitors based on the given filters."""
    filtered = []
    for mon in monitors:
        match = True
        for k, v in filters.items():
            val = mon.get(k.upper()) or mon.get(k.lower()) or mon.get(k)
            if val is None:
                match = False
                break
            if isinstance(v, list):
                if val not in v:
                    match = False
                    break
            else:
                if str(val).strip().lower() != str(v).strip().lower():
                    match = False
                    break
        if match:
            filtered.append(mon)
    return filtered


def get_monitor_data(resourceid: str) -> str:
    """Fetch monitor data for a specific resource ID."""
    url = f"{APM_SERVER}/AppManager/xml/GetMonitorData"
    params = {'apikey': API_KEY, 'resourceid': resourceid}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.text


def parse_monitor_data(xml_text: str) -> List[Dict[str, Any]]:
    """Parse monitor data XML into structured logs."""
    root = ET.fromstring(xml_text)
    monitorinfo = root.find("./result/response/Monitorinfo")
    if not monitorinfo:
        logging.warning("No Monitorinfo found in GetMonitorData XML.")
        return []

    logs = []

    # Main monitor info
    main_info = dict(monitorinfo.attrib)
    main_attributes = {}

    for attr in monitorinfo.findall("Attribute"):
        key = attr.attrib.get("DISPLAYNAME") or attr.attrib.get("AttributeID")
        unit = attr.attrib.get("Units")
        value = attr.attrib.get("Value")
        if unit and unit.strip():
            key = f"{key} ({unit.strip()})"
        main_attributes[key] = value

    main_info['Attributes'] = main_attributes
    main_info['host'] = main_info.get('RESOURCENAME', 'unknown')
    main_info['source'] = "main"
    logs.append(main_info)

    # Child monitors
    for childmonitors in monitorinfo.findall("CHILDMONITORS"):
        for childmonitorinfo in childmonitors.findall("CHILDMONITORINFO"):
            child_log = dict(childmonitorinfo.attrib)
            child_attributes = {}
            for childattr in childmonitorinfo.findall("CHILDATTRIBUTES"):
                key = childattr.attrib.get("DISPLAYNAME") or childattr.attrib.get("AttributeID")
                unit = childattr.attrib.get("Units")
                value = childattr.attrib.get("Value")
                if unit and unit.strip():
                    key = f"{key} ({unit.strip()})"
                child_attributes[key] = value
            child_log['Attributes'] = child_attributes
            child_log['host'] = main_info.get('RESOURCENAME', 'unknown')
            child_log['source'] = childmonitorinfo.attrib.get("DISPLAYNAME", "child")
            logs.append(child_log)

    return logs


def send_event_to_splunk(data: Dict[str, Any]) -> None:
    """Send a single event to Splunk HEC."""
    headers = {
        "Authorization": f"Splunk {SPLUNK_HEC_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "index": SPLUNK_INDEX,
        "event": data
    }
    try:
        resp = requests.post(SPLUNK_HEC_URL, headers=headers, data=json.dumps(payload), verify=False, timeout=10)
        if resp.status_code == 200:
            logging.info("Sent event to Splunk successfully.")
        else:
            logging.error(f"Failed to send event. Status: {resp.status_code}, Response: {resp.text}")
    except requests.RequestException as e:
        logging.error(f"Error sending to Splunk: {e}")


def main() -> None:
    """Main execution logic."""
    logging.info("Fetching list of monitors...")
    try:
        xml_list = apm_api_list_monitors()
    except requests.RequestException as e:
        logging.error(f"Error fetching monitor list: {e}")
        return

    monitors = parse_list_monitor_xml(xml_list)
    filtered_monitors = filter_monitors(monitors, FILTERS)
    logging.info(f"Found {len(filtered_monitors)} monitors after filtering.")

    for mon in filtered_monitors:
        resourceid = mon.get("RESOURCEID") or mon.get("resourceid") or mon.get("ResourceID")
        logging.info(f"Fetching monitor data for RESOURCEID: {resourceid}")
        try:
            xml_data = get_monitor_data(resourceid)
            logs = parse_monitor_data(xml_data)
            for log in logs:
                send_event_to_splunk(log)
        except requests.RequestException as e:
            logging.error(f"Error fetching monitor data for {resourceid}: {e}")
        logging.info("----------------------------------------------------")


if __name__ == "__main__":
    try:
        interval_input = input("Enter the interval (e.g., 30s or 5m): ").strip().lower()
        if interval_input.endswith('s'):
            interval = int(interval_input[:-1])
        elif interval_input.endswith('m'):
            interval = int(interval_input[:-1]) * 60
        else:
            interval = int(interval_input)  # default to seconds

        logging.info(f"Running every {interval} seconds. Press Ctrl+C to stop.")

        while True:
            main()
            logging.info(f"Sleeping for {interval} seconds...\n")
            time.sleep(interval)

    except KeyboardInterrupt:
        logging.info("Stopped by user. Goodbye!")

