#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

APM_SERVER = "http://192.168.33.41:9090"
API_KEY = "ce65b0070758f90a59e770bb8d84161b"

SPLUNK_HEC_URL = "https://localhost:8088/services/collector"
SPLUNK_HEC_TOKEN = "4c338c04-9ac4-405b-a1dd-f1e8083b495a"
SPLUNK_INDEX = "my-apm"

def apm_api_list_monitors():
    url = f"{APM_SERVER}/AppManager/xml/ListMonitor"
    params = {'apikey': API_KEY, 'type': 'all'}
    resp = requests.get(url, params=params, verify=False)
    resp.raise_for_status()
    return resp.text

def parse_list_monitor_xml(xml_text):
    root = ET.fromstring(xml_text)
    monitors = []
    response_node = root.find("./result/response")
    if response_node is None:
        print("Cannot find <response> node in XML.")
        return monitors
    for monitor in response_node.findall('Monitor'):
        monitors.append(monitor.attrib)
    return monitors

def get_monitor_data(resourceid):
    url = f"{APM_SERVER}/AppManager/xml/GetMonitorData"
    params = {'apikey': API_KEY, 'resourceid': resourceid}
    resp = requests.get(url, params=params, verify=False)
    resp.raise_for_status()
    return resp.text

def parse_monitor_data(xml_text):
    root = ET.fromstring(xml_text)
    monitorinfo = root.find("./result/response/Monitorinfo")
    if monitorinfo is None:
        print("No Monitorinfo found")
        return []
    
    logs = []

    # Main monitor info
    main_info = {k: v for k, v in monitorinfo.attrib.items()}

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
            child_log = {}
            child_log.update(childmonitorinfo.attrib)

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

def send_event_to_splunk(data):
    headers = {
        "Authorization": f"Splunk {SPLUNK_HEC_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "index": SPLUNK_INDEX,
        "event": data
    }

    resp = requests.post(SPLUNK_HEC_URL, headers=headers, data=json.dumps(payload), verify=False)
    if resp.status_code == 200:
        print("Sent to Splunk:", data.get('host', 'unknown'))
    else:
        print(f"Failed to send event. Status: {resp.status_code}, Response: {resp.text}")

def main():
    print("Fetching list of monitors...")
    xml_list = apm_api_list_monitors()
    monitors = parse_list_monitor_xml(xml_list)

    print(f"Found {len(monitors)} monitors:")
    for mon in monitors:
        resourceid = mon.get("RESOURCEID") or mon.get("resourceid")
        displayname = mon.get("DISPLAYNAME")
        hostip = mon.get("HOSTIP")
        print(f"- {displayname} ({hostip})")

    print("\nFetching monitor data and sending to Splunk...\n")
    for mon in monitors:
        resourceid = mon.get("RESOURCEID") or mon.get("resourceid")
        xml_data = get_monitor_data(resourceid)
        logs = parse_monitor_data(xml_data)
        for log in logs:
            send_event_to_splunk(log)

    print("Run completed.")

if __name__ == "__main__":
    main()
