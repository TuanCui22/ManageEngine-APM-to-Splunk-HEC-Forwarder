"""Tests for apm2splunk. No network: every request is faked."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from apm2splunk.apm import ApmError, parse_list_monitor, parse_monitor_data
from apm2splunk.config import Config, ConfigError, build_config
from apm2splunk.forwarder import StateStore, fingerprint, select_monitors
from apm2splunk.hec import HecClient

LIST_MONITOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result><response>
  <Monitor RESOURCEID="101" DISPLAYNAME="web-01" HOSTIP="10.0.0.5"/>
  <Monitor RESOURCEID="102" DISPLAYNAME="db-01" HOSTIP="10.0.0.6"/>
</response></result>"""

MONITOR_DATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result><response>
  <Monitorinfo RESOURCEID="101" RESOURCENAME="web-01">
    <Attribute DISPLAYNAME="CPU Usage" Units="%" Value="42"/>
    <Attribute DISPLAYNAME="Availability" Units="" Value="up"/>
    <CHILDMONITORS>
      <CHILDMONITORINFO RESOURCEID="101-1" DISPLAYNAME="disk /">
        <CHILDATTRIBUTES DISPLAYNAME="Used" Units="%" Value="81"/>
      </CHILDMONITORINFO>
    </CHILDMONITORS>
  </Monitorinfo>
</response></result>"""

EMPTY_MONITOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result><response></response></result>"""


def make_config(**overrides: Any) -> Config:
    base = dict(
        apm_server="https://apm.example:9090",
        apm_api_key="key",
        hec_url="https://splunk.example:8088/services/collector",
        hec_token="token",
        index="me-apm",
    )
    base.update(overrides)
    return Config(**base)


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: Any = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records requests and replays a scripted list of responses."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.responses.pop(0)


class TestConfig(unittest.TestCase):
    def test_missing_secrets_are_refused_before_any_request(self):
        with self.assertRaises(ConfigError) as ctx:
            Config(apm_server="https://a", hec_url="https://b").validate()
        message = str(ctx.exception)
        self.assertIn("apm_api_key", message)
        self.assertIn("hec_token", message)

    def test_bad_scheme_is_refused(self):
        with self.assertRaises(ConfigError):
            make_config(apm_server="apm.example:9090").validate()

    def test_tls_verification_defaults_to_on(self):
        # The original passed verify=False everywhere. That must not be the default.
        self.assertTrue(make_config().verify_tls)

    def test_redacted_hides_secrets_but_keeps_shape(self):
        shown = make_config(apm_api_key="abcdef1234567890").redacted()
        self.assertNotIn("abcdef1234567890", json.dumps(shown))
        self.assertIn("…", shown["apm_api_key"])

    def test_precedence_flags_beat_env_beat_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({
                "apm_server": "https://from-file",
                "apm_api_key": "file-key",
                "hec_url": "https://hec",
                "hec_token": "file-token",
                "index": "file-index",
            }), encoding="utf-8")
            config = build_config(
                {"index": "from-flag"},
                config_file=path,
                env={"APM2SPLUNK_INDEX": "from-env",
                     "APM2SPLUNK_APM_SERVER": "https://from-env"},
            )
        self.assertEqual(config.index, "from-flag")
        self.assertEqual(config.apm_server, "https://from-env")
        self.assertEqual(config.apm_api_key, "file-key")

    def test_unknown_config_key_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"apm_sever": "typo"}), encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                build_config(None, config_file=path, env={})
        self.assertIn("unknown key", str(ctx.exception))

    def test_group_names_parse_from_a_comma_string(self):
        config = build_config(
            {"group_names": "Linux Group, Windows Group"},
            env={"APM2SPLUNK_APM_SERVER": "https://a",
                 "APM2SPLUNK_APM_API_KEY": "k",
                 "APM2SPLUNK_HEC_URL": "https://b",
                 "APM2SPLUNK_HEC_TOKEN": "t",
                 "APM2SPLUNK_INDEX": "i"},
        )
        self.assertEqual(config.group_names, ["Linux Group", "Windows Group"])


class TestApmParsing(unittest.TestCase):
    def test_monitor_list_keeps_the_api_attributes(self):
        monitors = parse_list_monitor(LIST_MONITOR_XML)
        self.assertEqual(len(monitors), 2)
        self.assertEqual(monitors[0]["RESOURCEID"], "101")
        self.assertEqual(monitors[1]["DISPLAYNAME"], "db-01")

    def test_missing_response_node_is_an_error_not_an_empty_list(self):
        # An empty list would look like "nothing to do" and hide a broken API.
        with self.assertRaises(ApmError):
            parse_list_monitor("<result></result>")

    def test_non_xml_is_an_error_naming_the_cause(self):
        with self.assertRaises(ApmError) as ctx:
            parse_list_monitor("<html>502 Bad Gateway</html")
        self.assertIn("not valid XML", str(ctx.exception))

    def test_units_are_folded_into_the_attribute_name(self):
        events = parse_monitor_data(MONITOR_DATA_XML)
        main = events[0]
        self.assertIn("CPU Usage (%)", main["Attributes"])
        self.assertIn("Availability", main["Attributes"])
        self.assertEqual(main["Attributes"]["CPU Usage (%)"], "42")

    def test_child_monitors_become_their_own_events(self):
        events = parse_monitor_data(MONITOR_DATA_XML)
        self.assertEqual(len(events), 2)
        child = events[1]
        self.assertEqual(child["source"], "disk /")
        self.assertEqual(child["host"], "web-01")
        self.assertIn("Used (%)", child["Attributes"])

    def test_a_monitor_with_no_data_returns_empty_not_an_error(self):
        self.assertEqual(parse_monitor_data(EMPTY_MONITOR_XML), [])


class TestHecVerdict(unittest.TestCase):
    def test_a_200_with_code_zero_counts_as_sent(self):
        session = FakeSession([FakeResponse(200, payload={"code": 0, "text": "Success"})])
        result = HecClient(make_config(), session).send_batch([{"host": "h"}])
        self.assertTrue(result.ok)
        self.assertEqual(result.sent, 1)

    def test_a_200_with_a_nonzero_code_is_a_rejection_not_a_success(self):
        # This is the bug the original had: HEC answers 200 and drops the events.
        session = FakeSession([FakeResponse(200, payload={"code": 5, "text": "No index"})])
        result = HecClient(make_config(), session).send_batch([{"host": "h"}])
        self.assertFalse(result.ok)
        self.assertEqual(result.rejected, 1)
        self.assertIn("No index", result.errors[0])

    def test_a_200_with_a_non_json_body_is_not_trusted(self):
        session = FakeSession([FakeResponse(200, text="<html>proxy</html>")])
        result = HecClient(make_config(), session).send_batch([{"host": "h"}])
        self.assertFalse(result.ok)
        self.assertEqual(result.failed_batches, 1)

    def test_batching_sends_one_request_per_batch(self):
        responses = [FakeResponse(200, payload={"code": 0}) for _ in range(3)]
        session = FakeSession(responses)
        client = HecClient(make_config(batch_size=2), session)
        result = client.send_all([{"host": "h%d" % i} for i in range(5)])
        self.assertEqual(result.sent, 5)
        self.assertEqual(len(session.calls), 3)

    def test_the_batch_is_sent_as_an_array(self):
        session = FakeSession([FakeResponse(200, payload={"code": 0})])
        HecClient(make_config(), session).send_batch([{"host": "a"}, {"host": "b"}])
        payload = json.loads(session.calls[0]["data"])
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["index"], "me-apm")
        self.assertEqual(payload[0]["sourcetype"], "manageengine:apm")

    def test_a_4xx_is_permanent_and_not_retried(self):
        session = FakeSession([FakeResponse(403, text="bad token")])
        result = HecClient(make_config(max_retries=3), session).send_batch([{"host": "h"}])
        self.assertFalse(result.ok)
        self.assertEqual(len(session.calls), 1)

    def test_an_empty_batch_sends_nothing(self):
        session = FakeSession([])
        result = HecClient(make_config(), session).send_batch([])
        self.assertEqual(result.sent, 0)
        self.assertEqual(session.calls, [])


class TestStateStore(unittest.TestCase):
    def test_a_fingerprint_is_stable_across_key_order(self):
        a = [{"x": 1, "y": 2}]
        b = [{"y": 2, "x": 1}]
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_a_changed_value_changes_the_fingerprint(self):
        self.assertNotEqual(fingerprint([{"x": 1}]), fingerprint([{"x": 2}]))

    def test_round_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            store.remember("101", "abc", 3)
            store.save()
            again = StateStore(path)
        self.assertEqual(again.fingerprint("101"), "abc")

    def test_a_corrupt_state_file_does_not_stop_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            store = StateStore(path)
        self.assertEqual(store.fingerprint("101"), "")

    def test_no_path_means_no_persistence_and_no_crash(self):
        store = StateStore(None)
        store.remember("101", "abc", 1)
        store.save()
        self.assertEqual(store.fingerprint("101"), "abc")


class FakeApm:
    def __init__(self, monitors, groups=None, details=None):
        self._monitors = monitors
        self._groups = groups or []
        self._details = details or {}

    def list_monitors(self):
        return self._monitors

    def list_monitor_groups(self):
        return self._groups

    def list_group_details(self, group_id):
        return self._details.get(group_id, [])


class TestGroupFilter(unittest.TestCase):
    def test_no_groups_means_every_monitor(self):
        monitors = [{"RESOURCEID": "1"}, {"RESOURCEID": "2"}]
        self.assertEqual(len(select_monitors(monitors, [], FakeApm(monitors))), 2)

    def test_a_group_keeps_only_its_members(self):
        monitors = [{"RESOURCEID": "1"}, {"RESOURCEID": "2"}]
        client = FakeApm(monitors,
                         groups=[{"RESOURCEID": "g1", "DISPLAYNAME": "Linux Group"}],
                         details={"g1": [{"RESOURCEID": "2"}]})
        kept = select_monitors(monitors, ["Linux Group"], client)
        self.assertEqual([m["RESOURCEID"] for m in kept], ["2"])

    def test_an_unknown_group_is_an_error_naming_the_known_ones(self):
        client = FakeApm([], groups=[{"RESOURCEID": "g1", "DISPLAYNAME": "Linux Group"}])
        with self.assertRaises(ApmError) as ctx:
            select_monitors([], ["Nonexistent"], client)
        self.assertIn("Linux Group", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
