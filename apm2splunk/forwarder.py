"""The forwarder: read APM, filter, send to HEC, remember what was sent.

What this adds over the original loop:

* **Group filtering** — the second script had it, the first did not. Now one
  code path does both, and an empty group list means "everything".
* **A state file** — the original re-sent every monitor every interval with no
  record of what it had already delivered. A Splunk scripted input that restarts
  mid-run therefore duplicates whatever it had already sent. The state file
  records the last successful send per monitor so a rerun is idempotent within a
  window.
* **Per-monitor isolation** — one monitor failing to parse must not stop the
  other forty.
* **A dry run** — print what would be sent, send nothing. The only safe way to
  check a new filter or a new index before it lands in production.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .apm import ApmClient, ApmError, parse_monitor_data
from .config import Config
from .hec import HecClient, SendResult

log = logging.getLogger("apm2splunk")


@dataclass
class RunReport:
    monitors_seen: int = 0
    monitors_forwarded: int = 0
    events_built: int = 0
    send: SendResult = field(default_factory=SendResult)
    skipped_unchanged: int = 0
    monitor_errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.monitor_errors and self.send.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitors_seen": self.monitors_seen,
            "monitors_forwarded": self.monitors_forwarded,
            "events_built": self.events_built,
            "sent": self.send.sent,
            "rejected": self.send.rejected,
            "failed_batches": self.send.failed_batches,
            "skipped_unchanged": self.skipped_unchanged,
            "monitor_errors": self.monitor_errors,
            "send_errors": self.send.errors,
            "dry_run": self.dry_run,
            "ok": self.ok,
        }


class StateStore:
    """Last-sent fingerprint per monitor, so a rerun does not duplicate.

    Deliberately a small JSON file, not a database: this runs inside a Splunk
    scripted input, and a scripted input that needs a database is a scripted
    input that will eventually fail to start.
    """

    def __init__(self, path: str | Path | None):
        self.path = Path(path).expanduser() if path else None
        self._data: dict[str, Any] = {}
        if self.path and self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except (OSError, ValueError) as exc:
                # A corrupt state file must not stop the forwarder; it only costs
                # one duplicate window.
                log.warning("state file %s unreadable (%s); starting fresh",
                            self.path, exc)

    def fingerprint(self, monitor_id: str) -> str:
        entry = self._data.get(monitor_id)
        return str(entry.get("fingerprint", "")) if isinstance(entry, dict) else ""

    def remember(self, monitor_id: str, fingerprint: str, events: int) -> None:
        self._data[monitor_id] = {
            "fingerprint": fingerprint,
            "events": events,
            "sent_at": int(time.time()),
        }

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("could not write state file %s: %s", self.path, exc)


def fingerprint(events: list[dict[str, Any]]) -> str:
    """Stable hash of what a monitor reported, ignoring key order."""
    payload = json.dumps(events, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_monitors(monitors: Iterable[dict[str, str]],
                    groups: list[str],
                    client: ApmClient) -> list[dict[str, str]]:
    """Apply the group filter. Empty groups means every monitor."""
    monitors = list(monitors)
    if not groups:
        return monitors

    wanted = {name.strip().lower() for name in groups if name.strip()}
    available = client.list_monitor_groups()
    matched = [g for g in available
               if (g.get("DISPLAYNAME") or "").strip().lower() in wanted]
    if not matched:
        known = sorted({(g.get("DISPLAYNAME") or "").strip() for g in available})
        raise ApmError(
            "none of the requested group(s) %s exist on the APM server. "
            "Groups it reports: %s"
            % (sorted(wanted), known or "none"))

    allowed: set[str] = set()
    for group in matched:
        group_id = group.get("RESOURCEID") or group.get("GROUPID")
        if not group_id:
            continue
        for mon in client.list_group_details(group_id):
            rid = mon.get("RESOURCEID")
            if rid:
                allowed.add(rid)

    return [m for m in monitors
            if (m.get("RESOURCEID") or m.get("resourceid")) in allowed]


def forward(config: Config, *, dry_run: bool = False,
            client: ApmClient | None = None,
            hec: HecClient | None = None,
            state: StateStore | None = None) -> RunReport:
    """One full cycle: list, filter, fetch, build, send."""
    report = RunReport(dry_run=dry_run)
    client = client or ApmClient(config)
    hec = hec or HecClient(config)
    state = state if state is not None else StateStore(config.state_file or None)

    monitors = select_monitors(client.list_monitors(), config.group_names, client)
    report.monitors_seen = len(monitors)
    log.info("APM reports %d monitor(s) after filtering", len(monitors))

    pending: list[dict[str, Any]] = []
    #: resource_id → fingerprint for monitors whose events are in `pending`.
    #: Only committed to the state file once the whole send succeeds.
    staged: dict[str, str] = {}

    for monitor in monitors:
        resource_id = monitor.get("RESOURCEID") or monitor.get("resourceid")
        name = monitor.get("DISPLAYNAME") or resource_id or "?"
        if not resource_id:
            report.monitor_errors.append("%s: no RESOURCEID in the monitor list" % name)
            continue
        try:
            events = parse_monitor_data(client.monitor_data(resource_id))
        except ApmError as exc:
            # One monitor failing is not the run failing.
            report.monitor_errors.append("%s: %s" % (name, exc))
            log.warning("monitor %s could not be read: %s", name, exc)
            continue

        if not events:
            log.debug("monitor %s reported no data", name)
            continue

        digest = fingerprint(events)
        if state.fingerprint(resource_id) == digest:
            report.skipped_unchanged += 1
            log.debug("monitor %s unchanged since last send", name)
            continue

        for event in events:
            event.setdefault("apm_resource_id", resource_id)
            event.setdefault("apm_monitor", name)
        pending.extend(events)
        report.monitors_forwarded += 1
        report.events_built += len(events)
        staged[resource_id] = digest

    if dry_run:
        log.info("dry run: %d event(s) from %d monitor(s) would be sent",
                 report.events_built, report.monitors_forwarded)
        return report

    if not pending:
        log.info("nothing to send")
        return report

    report.send = hec.send_all(pending)

    if report.send.ok:
        for resource_id, digest in staged.items():
            state.remember(resource_id, digest, 0)
        state.save()
    else:
        # Do not advance the state on a partial failure: the next run must retry
        # the monitors whose events did not land.
        log.warning("not updating state: %d event(s) rejected, %d batch(es) failed",
                    report.send.rejected, report.send.failed_batches)

    return report
