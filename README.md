![HEADRACE](docs/banner.svg)

# HEADRACE

**ManageEngine APM into Splunk HEC, without losing a window.**

Streams monitor and child-monitor metrics from **ManageEngine Application Manager
(APM)** into **Splunk HTTP Event Collector (HEC)**, so APM telemetry sits in the
same index as the rest of your operational data.

Runs as a Splunk scripted input, under cron, or interactively. Python 3.11+, one
runtime dependency.

---

## Capabilities

| | |
|---|---|
| **Scoped collection** | Forward every monitor, or restrict to named monitor groups. An unknown group name is reported with the groups APM actually exposes, rather than silently forwarding nothing. |
| **Batched delivery** | Events are sent as HEC arrays, configurable batch size, instead of one request per event. |
| **Per-event verdict handling** | HEC answers `200 OK` even when it rejects events. The client reads the response body and reports the per-event `code`, so a rejected batch is never counted as delivered. |
| **Bounded retries** | Transient failures (5xx, 429, connection errors) are retried with backoff. A 4xx is treated as permanent and reported immediately. |
| **Idempotent reruns** | A state file records a content fingerprint per monitor, so a restart or an overlapping schedule does not duplicate a window. State advances only after a fully clean send. |
| **Per-monitor isolation** | A monitor that cannot be read is recorded and skipped; the rest of the run continues. |
| **Credential hygiene** | No secret has a default. Configuration resolves from flags, environment, or a file, in that order, and secrets are redacted in every log line and status view. |
| **TLS verification on by default** | Self-signed endpoints are supported through a CA bundle rather than by disabling verification. |
| **Machine-readable output** | `--json` on every command; exit codes distinguish configuration errors from delivery failures. |

---

## Install

```bash
git clone https://github.com/TuanCui22/ManageEngine-APM-to-Splunk-HEC-Forwarder.git
cd ManageEngine-APM-to-Splunk-HEC-Forwarder
python -m pip install -e .
```

Without installing: `python -m apm2splunk.cli <command>`.

## Configure

Three sources, highest precedence first: **flags → environment → config file → defaults**.

```bash
cp config.example.toml config.local.toml
# edit config.local.toml, or keep secrets in the environment:
export APM2SPLUNK_APM_API_KEY="..."
export APM2SPLUNK_HEC_TOKEN="..."
```

Required: `apm_server`, `apm_api_key`, `hec_url`, `hec_token`, `index`. A missing
value is reported at startup with the exact flag and variable name to set.

| Setting | Flag | Environment |
|---|---|---|
| APM base URL | `--apm-server` | `APM2SPLUNK_APM_SERVER` |
| APM API key | `--apm-api-key` | `APM2SPLUNK_APM_API_KEY` |
| HEC endpoint | `--hec-url` | `APM2SPLUNK_HEC_URL` |
| HEC token | `--hec-token` | `APM2SPLUNK_HEC_TOKEN` |
| Target index | `--index` | `APM2SPLUNK_INDEX` |
| Sourcetype | `--sourcetype` | `APM2SPLUNK_SOURCETYPE` |
| Group filter | `--group` (repeatable) | `APM2SPLUNK_GROUP_NAMES` |
| Batch size | `--batch-size` | `APM2SPLUNK_BATCH_SIZE` |
| State file | `--state-file` | `APM2SPLUNK_STATE_FILE` |
| CA bundle | `--ca-bundle` | `APM2SPLUNK_CA_BUNDLE` |

## Verify before deploying

```bash
apm2splunk check --config config.local.toml
```

Prints the effective configuration with secrets redacted, lists the monitors APM
reports, and sends a single harmless probe event to confirm the token and index.
It does not read any monitor data.

Then preview a run without sending:

```bash
apm2splunk forward --config config.local.toml --dry-run
```

## Run

```bash
apm2splunk forward --config config.local.toml
```

| Exit code | Meaning |
|---|---|
| 0 | clean run |
| 1 | a monitor could not be read, or HEC rejected events |
| 2 | configuration missing or malformed |
| 3 | APM or HEC unreachable |

### As a Splunk scripted input

`apm_to_splunk.py` and `scriptFilterGroups.py` are thin entry points over the
same CLI, so a scripted input can point at either name.

```bash
# $SPLUNK_HOME/etc/apps/<app>/bin/
cp -r apm2splunk /path/to/splunk/etc/apps/<app>/bin/
cp apm_to_splunk.py /path/to/splunk/etc/apps/<app>/bin/
```

Then **Settings → Data Inputs → Scripts**, set the interval, and provide the
environment variables through the input's configuration. Point `--state-file` at
a writable, persistent path such as
`$SPLUNK_HOME/var/run/apm2splunk-state.json`.

### Filtering to specific groups

```bash
apm2splunk forward --group "Linux Group" --group "Windows Group"
```

No `--group` means every monitor.

## Status page

```bash
apm2splunk forward --json > report.json
apm2splunk status --report report.json --out status.html
```

A single self-contained HTML file: inline CSS, no external requests, no listening
port. Open it locally or serve it from whatever already hosts static pages. It
renders only what it can read from the state file and the last run report — an
absent measurement is shown as absent, never as zero.

## Delivery model

1. `ListMonitor` → every monitor, or the members of the named groups.
2. `GetMonitorData` per monitor → one event for the monitor, one per child.
3. Fingerprint the events. An unchanged fingerprint skips the monitor.
4. Send in batches. Read the HEC body for the per-event verdict.
5. On a fully clean send, persist the fingerprints. A partial failure leaves the
   state untouched so the next run retries.

## Tests

```bash
python -m pytest -q          # 28 tests, no network
```

Every HTTP call is faked. Coverage includes HEC returning 200 with a rejection
code, a non-JSON 200 from an intermediary proxy, a 4xx that must not be retried,
a corrupt state file, an unknown group name, and unit folding in attribute names.

## Layout

```
apm2splunk/
  config.py      flag / environment / file resolution, validation, redaction
  apm.py         APM XML client and parsers
  hec.py         batching HEC client with per-event verdict handling
  forwarder.py   the cycle: list, filter, fetch, fingerprint, send
  status.py      the self-contained HTML status page
  cli.py         forward / check / status
tests/
  test_apm2splunk.py
apm_to_splunk.py        entry point
scriptFilterGroups.py   entry point
```

## Licence

Private research artefact. Not open source, not for redistribution. See
[`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
