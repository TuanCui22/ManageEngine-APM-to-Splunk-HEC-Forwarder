import requests
import xml.etree.ElementTree as ET
import json
import urllib3
import time
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== CONFIG ====================
APM_SERVER = "http://192.168.100.28:9090"
API_KEY = "b73827fc9f629a83806b916830f15689"

SPLUNK_HEC_URL = "https://localhost:8088/services/collector"
SPLUNK_HEC_TOKEN = "a617aee7-7167-4ade-b0da-99c3cf5f68bd"
SPLUNK_INDEX = "my-apm"

GROUP_NAMES = ["Linux Group"]  # Target groups
# =================================================


# ==== API CALLS ====
def call_apm_api(path, params):
    """Call APM API with apikey đứng trước"""
    url = f"{APM_SERVER}{path}"
    full_params = {"apikey": API_KEY}
    full_params.update(params)
    resp = requests.get(url, params=full_params, verify=False)
    resp.raise_for_status()
    return resp.text


def list_monitor_groups():
    return call_apm_api("/AppManager/xml/ListMonitorGroups", {})


def list_mg_details(group_id):
    return call_apm_api("/AppManager/xml/ListMGDetails", {"groupId": group_id})


def get_monitor_data(resourceid):
    return call_apm_api("/AppManager/xml/GetMonitorData", {"resourceid": resourceid})


# ==== XML PARSING ====
def parse_group_xml(xml_text, target_names):
    root = ET.fromstring(xml_text)
    groups = []
    for mg in root.findall(".//MonitorGroup"):
        name = mg.attrib.get("DISPLAYNAME", "").strip()
        gid = mg.attrib.get("RESOURCEID")
        if name in target_names:
            groups.append({"DISPLAYNAME": name, "GROUPID": gid})
    return groups


def parse_mg_details(xml_text):
    root = ET.fromstring(xml_text)
    monitors = []
    for mon in root.findall(".//Monitors"):
        monitors.append({
            "RESOURCEID": mon.attrib.get("RESOURCEID"),
            "DISPLAYNAME": mon.attrib.get("DISPLAYNAME")
        })
    return monitors


def parse_monitor_data(xml_text):
    root = ET.fromstring(xml_text)
    monitorinfo = root.find("./result/response/Monitorinfo")
    if monitorinfo is None:
        return []

    logs = []
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


# ==== SPLUNK SEND ====
def send_event_to_splunk(data):
    headers = {
        "Authorization": f"Splunk {SPLUNK_HEC_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "index": SPLUNK_INDEX,
        "event": data
    }
    try:
        resp = requests.post(SPLUNK_HEC_URL, headers=headers, data=json.dumps(payload), verify=False)
        return resp.status_code == 200
    except Exception:
        return False


# ==== MAIN ====
def main():
    try:
        xml_groups = list_monitor_groups()
        groups = parse_group_xml(xml_groups, GROUP_NAMES)
        if not groups:
            return

        for group in groups:
            try:
                xml_mg = list_mg_details(group["GROUPID"])
                monitors = parse_mg_details(xml_mg)
            except Exception:
                continue

            if not monitors:
                continue

            for mon in monitors:
                try:
                    xml_data = get_monitor_data(mon["RESOURCEID"])
                    logs = parse_monitor_data(xml_data)
                    for log in logs:
                        send_event_to_splunk(log)
                except Exception:
                    continue
    except Exception:
        pass


if __name__ == "__main__":
    main()
