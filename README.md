# ManageEngine APM → Splunk HEC Forwarder

Pulls monitor data from **ManageEngine Application Manager (APM)** and ships it to
**Splunk HTTP Event Collector (HEC)**, so APM metrics sit next to everything else
in your indexers instead of in a dashboard nobody opens.

Runs as a Splunk scripted input, as a cron job, or by hand. Python 3.11+, one
runtime dependency.

---

## What changed in 2.0

The 1.x script worked, and it had four problems that only show up in production:

| 1.x | 2.0 |
|---|---|
| APM key and HEC token hard-coded in the file | flags, environment, or config file — no secret in the repo |
| `verify=False` on every request | TLS verification on by default; `--ca-bundle` for self-signed |
| one HTTP request per event | batched, 100 events per request |
| checked `status_code == 200` | reads the HEC body — HEC returns **200 while dropping events** |
| no timeout | per-request timeout, bounded retries |
| re-sent everything every interval | state file; a rerun does not duplicate a window |
| one bad monitor killed the run | per-monitor isolation, errors reported per monitor |
| two scripts, two behaviours | one CLI: `forward`, `check`, `status` |

The last row of that table is the one that mattered most. HEC answers `200 OK`
with `{"code": 5, "text": "No index"}` when it rejects your events. The 1.x script
printed "Sent to Splunk" for every one of them.

---

## Install

```bash
git clone https://github.com/TuanCui22/ManageEngine-APM-to-Splunk-HEC-Forwarder.git
cd ManageEngine-APM-to-Splunk-HEC-Forwarder
python -m pip install -e .
```

Or without installing: `python -m apm2splunk.cli <command>`.

## Configure

Three sources, highest wins: **flags → environment → config file → defaults**.

```bash
cp config.example.toml config.local.toml
# edit config.local.toml, or keep secrets out of it entirely:
export APM2SPLUNK_APM_API_KEY="..."
export APM2SPLUNK_HEC_TOKEN="..."
```

The minimum you must set: `apm_server`, `apm_api_key`, `hec_url`, `hec_token`,
`index`. A missing one is an error at startup, not a silent failure at 3am.

## Verify before you deploy

```bash
apm2splunk check --config config.local.toml
```

It prints the effective config with secrets redacted, lists the monitors APM
reports, and sends **one** harmless probe event to prove the token and the index.
It touches no APM monitor data.

Then look at what would be sent, without sending it:

```bash
apm2splunk forward --config config.local.toml --dry-run
```

## Run

```bash
apm2splunk forward --config config.local.toml
```

Exit codes, because a scripted input's only signal is its exit code:

| code | meaning |
|---|---|
| 0 | clean run |
| 1 | a monitor could not be read, or HEC rejected events |
| 2 | configuration missing or malformed |
| 3 | APM or HEC unreachable |

### As a Splunk scripted input

The old entry point still works — `apm_to_splunk.py` and `scriptFilterGroups.py`
are now thin shims over the new CLI, so an existing input keeps running.

```bash
# $SPLUNK_HOME/etc/apps/<app>/bin/
cp -r apm2splunk /path/to/splunk/etc/apps/<app>/bin/
cp apm_to_splunk.py /path/to/splunk/etc/apps/<app>/bin/
```

Then **Settings → Data Inputs → Scripts**, interval `60`, and set the environment
variables in the input's configuration (or in `bin/.env` read by your wrapper).
Give the state file a writable path — `$SPLUNK_HOME/var/run/apm2splunk-state.json`
is a reasonable choice.

### Filter to specific groups

```bash
apm2splunk forward --group "Linux Group" --group "Windows Group"
```

An empty filter means every monitor. A group name that does not exist is an
error that lists the names APM actually reports, rather than silently forwarding
nothing.

## Status page

```bash
apm2splunk forward --json > report.json
apm2splunk status --report report.json --out status.html
```

One self-contained HTML file: inline CSS, no script tags fetching anything, no
network requests. Open it locally or drop it behind whatever already serves
static pages. It reports what it can read from the state file and the last run
report — and a value it cannot read renders as a named gap, never as a zero.

## How it decides what to send

1. `ListMonitor` → every monitor, or the members of the groups you named.
2. `GetMonitorData` per monitor → one event for the monitor, one per child.
3. Fingerprint the events. If the fingerprint matches the last one sent for that
   monitor, skip it. That is what makes a rerun idempotent.
4. Send in batches of `batch_size`. Read the HEC body for the per-event verdict.
5. Only on a fully clean send, write the fingerprints to the state file. A
   partial failure leaves the state alone so the next run retries.

## Tests

```bash
python -m pytest -q          # 28 tests, no network
```

Every HTTP call in the suite is faked. The tests cover the failure modes that
matter: HEC returning 200 with a rejection code, a non-JSON 200 from a proxy, a
4xx that must not be retried, a corrupt state file, an unknown group name, and
units being folded into attribute names.

## Layout

```
apm2splunk/
  config.py      flags / env / file resolution, validation, redaction
  apm.py         APM XML client and parsers
  hec.py         batching HEC client with per-event verdict handling
  forwarder.py   the cycle: list, filter, fetch, fingerprint, send
  status.py      the self-contained HTML status page
  cli.py         forward / check / status
tests/
  test_apm2splunk.py
apm_to_splunk.py        1.x-compatible shim
scriptFilterGroups.py   1.x-compatible shim
```

## Licence

Private research artefact. Not open source, not for redistribution. See
[`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
