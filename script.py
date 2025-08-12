import requests
import xml.etree.ElementTree as ET
import json
import urllib3

# Bỏ cảnh báo SSL (nếu dùng https không verify cert)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cấu hình APM và Splunk HEC
APM_SERVER = "http://192.168.35.17:9090"
API_KEY = "715641f8cdb12cfed5e155953ad6d536"

SPLUNK_HEC_URL = "https://192.168.35.5:8088/services/collector"
SPLUNK_HEC_TOKEN = "cef782f2-bfe7-4d32-9cea-20c3dfe6ee2e"
SPLUNK_INDEX = "me-apm"

def apm_api_list_monitors():
    url = f"{APM_SERVER}/AppManager/xml/ListMonitor"
    params = {'apikey': API_KEY, 'type': 'all'}
    resp = requests.get(url, params=params)
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

def filter_monitors(monitors, filters):
    filtered = []
    for mon in monitors:
        match = True
        for k, v in filters.items():
            val = mon.get(k.upper()) or mon.get(k.lower()) or mon.get(k)
            if val is None:
                match = False
                break
            
            # Check if filter value is list -> check if val in that list
            if isinstance(v, list):
                if val not in v:
                    match = False
                    break
            else:
                # Exact match
                if str(val).strip().lower() != str(v).strip().lower():
                    match = False
                    break
        if match:
            filtered.append(mon)
    return filtered

def get_monitor_data(resourceid):
    url = f"{APM_SERVER}/AppManager/xml/GetMonitorData"
    params = {'apikey': API_KEY, 'resourceid': resourceid}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.text

def parse_monitor_data(xml_text):
    root = ET.fromstring(xml_text)
    monitorinfo = root.find("./result/response/Monitorinfo")
    if monitorinfo is None:
        print("No Monitorinfo found")
        return []
    
    logs = []

    # Thuộc tính chính (Monitorinfo)
    main_info = {k: v for k, v in monitorinfo.attrib.items()}

    # Thuộc tính con của monitor chính, thêm đơn vị vào key nếu có và không phải là space
    main_attributes = {}
    for attr in monitorinfo.findall("Attribute"):
        key = attr.attrib.get("DISPLAYNAME") or attr.attrib.get("AttributeID")
        unit = attr.attrib.get("Units")
        value = attr.attrib.get("Value")

        if unit and unit.strip() != "":
            key = f"{key} ({unit.strip()})"
        main_attributes[key] = value

    main_info['Attributes'] = main_attributes
    main_info['host'] = main_info.get('RESOURCENAME', 'unknown')
    main_info['source'] = "main"
    logs.append(main_info)

    # Các child monitors, thêm đơn vị vào key nếu có và không phải là space
    for childmonitors in monitorinfo.findall("CHILDMONITORS"):
        for childmonitorinfo in childmonitors.findall("CHILDMONITORINFO"):
            child_log = {}
            child_log.update(childmonitorinfo.attrib)

            child_attributes = {}
            for childattr in childmonitorinfo.findall("CHILDATTRIBUTES"):
                key = childattr.attrib.get("DISPLAYNAME") or childattr.attrib.get("AttributeID")
                unit = childattr.attrib.get("Units")
                value = childattr.attrib.get("Value")

                if unit and unit.strip() != "":
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
        print(f"Successfully sent event to Splunk HEC!")
    else:
        print(f"Failed to send event. Status code: {resp.status_code}, Response: {resp.text}")

    # In command curl tương ứng để test thủ công
    curl_cmd = (
        f"curl -k {SPLUNK_HEC_URL} "
        f"-H 'Authorization: Splunk {SPLUNK_HEC_TOKEN}' "
        f"-H 'Content-Type: application/json' "
        f"-d '{json.dumps(payload)}'"
    )
    print("\nRun this command in terminal to test manually:")
    print(curl_cmd)
    print("----------------------------------------------------")

if __name__ == "__main__":
    print("Fetching list of monitors...")
    xml_list = apm_api_list_monitors()
    monitors = parse_list_monitor_xml(xml_list)
    
    filters = {
    "AVAILABILITYATTRIBUTEID": ["3100", "40902"]
}
    
    filtered_monitors = filter_monitors(monitors, filters)

    print(f"After filtering, found {len(filtered_monitors)} monitors:\n")
    for mon in filtered_monitors:
        resourceid = mon.get("RESOURCEID") or mon.get("resourceid") or mon.get("ResourceID")
        displayname = mon.get("DISPLAYNAME") or mon.get("displayname")
        hostip = mon.get("HOSTIP") or mon.get("hostip")
        availabilityattributeid = mon.get("AVAILABILITYATTRIBUTEID") or mon.get("availabilityattributeid")
        print(f"RESOURCEID: {resourceid}, DISPLAYNAME: {displayname}, HOSTIP: {hostip}, AVAILABILITYATTRIBUTEID: {availabilityattributeid}")
    
    
    print("\nFetching monitor data for filtered monitors...\n")
    for mon in filtered_monitors:
        resourceid = mon.get("RESOURCEID") or mon.get("resourceid") or mon.get("ResourceID")
        print(f"Monitor Data for RESOURCEID: {resourceid}")
        xml_data = get_monitor_data(resourceid)
        logs = parse_monitor_data(xml_data)
        for log in logs:
            # Gửi từng log lên Splunk
            send_event_to_splunk(log)
        print("----------------------------------------------------")

    print("Done.")
