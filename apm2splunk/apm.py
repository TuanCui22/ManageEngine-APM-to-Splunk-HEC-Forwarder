"""ManageEngine APM REST client.

The APM XML API is the only source of truth here, so the client's job is narrow:
make a request, surface a useful error, and hand back parsed data. It does not
decide what to forward.

Two things the original got wrong that this fixes:

* ``verify=False`` on every call. A management network is not a trusted network;
  a self-signed certificate is handled with ``ca_bundle``, not by disabling
  verification for every request.
* No timeout. A hung APM server blocked the Splunk scripted input forever, and
  Splunk's own scheduler then piled up runs behind it.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

from .config import Config


class ApmError(Exception):
    """The APM API could not be read. Carries what was tried."""

    def __init__(self, message: str, *, url: str = "", status: int | None = None):
        self.url = url
        self.status = status
        super().__init__(message)


class ApmClient:
    """Thin, retrying client over the APM XML endpoints."""

    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/xml, text/xml, */*"})
        self._verify: bool | str = config.verify_tls
        if config.ca_bundle:
            self._verify = config.ca_bundle

    def _get(self, path: str, params: dict[str, Any]) -> str:
        url = self.config.apm_server.rstrip("/") + path
        query = {"apikey": self.config.apm_api_key}
        query.update(params)

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url, params=query, verify=self._verify,
                    timeout=self.config.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    return response.text
                # 4xx is a configuration problem: retrying will not fix a bad key.
                if 400 <= response.status_code < 500:
                    raise ApmError(
                        "APM returned %d for %s: %s"
                        % (response.status_code, path, _short(response.text)),
                        url=url, status=response.status_code)
                last_error = ApmError(
                    "APM returned %d for %s" % (response.status_code, path),
                    url=url, status=response.status_code)
            if attempt < self.config.max_retries:
                time.sleep(min(2 ** attempt, 8))

        raise ApmError(
            "APM request to %s failed after %d attempt(s): %s"
            % (path, self.config.max_retries + 1, last_error),
            url=url)

    # -- endpoints -----------------------------------------------------
    def list_monitors(self) -> list[dict[str, str]]:
        return parse_list_monitor(self._get("/AppManager/xml/ListMonitor",
                                            {"type": "all"}))

    def list_monitor_groups(self) -> list[dict[str, str]]:
        return parse_monitor_groups(self._get("/AppManager/xml/ListMonitorGroups", {}))

    def list_group_details(self, group_id: str) -> list[dict[str, str]]:
        return parse_group_details(
            self._get("/AppManager/xml/ListMGDetails", {"groupId": group_id}))

    def monitor_data(self, resource_id: str) -> str:
        return self._get("/AppManager/xml/GetMonitorData",
                         {"resourceid": resource_id})


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def _parse(xml_text: str, what: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        # A truncated or HTML error page is the usual cause. Say so, rather than
        # letting a bare ParseError reach the operator.
        raise ApmError(
            "%s: response is not valid XML (%s). First bytes: %s"
            % (what, exc, _short(xml_text, 120))) from exc


def _find_response(root: ET.Element, what: str) -> ET.Element:
    """Locate the <response> node whether or not it is wrapped in <result>.

    The endpoint returns <result><response>…</response></result> in the fixtures,
    but the original code's path assumed a wrapper above <result>. Accepting both
    shapes costs nothing and avoids a "no response node" error on a valid document.
    """
    if root.tag == "response":
        return root
    node = root.find(".//response")
    if node is None:
        raise ApmError("%s: no <response> node in the response" % what)
    return node


def parse_list_monitor(xml_text: str) -> list[dict[str, str]]:
    """Monitor list. Returns the attribute dicts as the API sent them."""
    root = _parse(xml_text, "ListMonitor")
    response = _find_response(root, "ListMonitor")
    return [dict(monitor.attrib) for monitor in response.findall("Monitor")]


def parse_monitor_groups(xml_text: str) -> list[dict[str, str]]:
    root = _parse(xml_text, "ListMonitorGroups")
    return [dict(group.attrib) for group in root.findall(".//MonitorGroup")]


def parse_group_details(xml_text: str) -> list[dict[str, str]]:
    root = _parse(xml_text, "ListMGDetails")
    return [dict(mon.attrib) for mon in root.findall(".//Monitors")]


def _attributes(node: ET.Element, tag: str) -> dict[str, str]:
    """Attribute children as name → value, with the unit folded into the name.

    Folding the unit into the key is what the original did and it is the right
    call: two attributes with the same display name and different units are
    different measurements, and collapsing them silently loses one.
    """
    out: dict[str, str] = {}
    for attr in node.findall(tag):
        key = attr.attrib.get("DISPLAYNAME") or attr.attrib.get("AttributeID") or "unknown"
        unit = (attr.attrib.get("Units") or "").strip()
        if unit:
            key = "%s (%s)" % (key, unit)
        out[key] = attr.attrib.get("Value", "")
    return out


def parse_monitor_data(xml_text: str) -> list[dict[str, Any]]:
    """One event for the monitor itself, one per child monitor.

    Returns [] rather than raising when the response carries no Monitorinfo: a
    monitor that has never reported is a normal state, not an error.
    """
    root = _parse(xml_text, "GetMonitorData")
    monitorinfo = root.find(".//Monitorinfo")
    if monitorinfo is None:
        return []

    host = monitorinfo.attrib.get("RESOURCENAME", "unknown")
    events: list[dict[str, Any]] = []

    main = dict(monitorinfo.attrib)
    main["Attributes"] = _attributes(monitorinfo, "Attribute")
    main["host"] = host
    main["source"] = "main"
    events.append(main)

    for group in monitorinfo.findall("CHILDMONITORS"):
        for child in group.findall("CHILDMONITORINFO"):
            event = dict(child.attrib)
            event["Attributes"] = _attributes(child, "CHILDATTRIBUTES")
            event["host"] = host
            event["source"] = child.attrib.get("DISPLAYNAME", "child")
            events.append(event)

    return events
