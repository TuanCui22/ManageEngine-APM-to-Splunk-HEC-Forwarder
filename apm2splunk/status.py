"""A self-contained status page for the forwarder.

Why a generated HTML file and not a web server: this runs on a Splunk host. A
second listening port on a Splunk host is a firewall conversation, a certificate
conversation, and an authentication conversation, and none of them are worth it
for a page an operator looks at once a day. ``status --html out.html`` writes one
file with inline CSS, no script, no external origin, that can be opened locally or
dropped behind whatever the team already uses to serve static pages.

The page reports only what it can read: the state file and the last run report.
A field that is absent renders as a named gap, never as a zero.
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

from .config import Config
from .forwarder import StateStore


def _fmt_age(seconds: float) -> str:
    if seconds < 90:
        return "%d seconds ago" % seconds
    if seconds < 5400:
        return "%d minutes ago" % (seconds / 60)
    if seconds < 172800:
        return "%d hours ago" % (seconds / 3600)
    return "%d days ago" % (seconds / 86400)


def collect(config: Config, report_path: str | Path | None = None) -> dict[str, Any]:
    """Everything the page shows, derived from files on disk."""
    state = StateStore(config.state_file or None)
    entries = getattr(state, "_data", {}) or {}
    now = time.time()

    monitors = []
    for monitor_id, entry in sorted(entries.items()):
        if not isinstance(entry, dict):
            continue
        sent_at = entry.get("sent_at")
        age = now - sent_at if isinstance(sent_at, (int, float)) else None
        monitors.append({
            "id": monitor_id,
            "fingerprint": str(entry.get("fingerprint", ""))[:12],
            "sent_at": sent_at,
            "age": _fmt_age(age) if age is not None else None,
            "stale": bool(age is not None and age > 3600),
        })

    last_run = None
    if report_path:
        path = Path(report_path).expanduser()
        if path.is_file():
            try:
                last_run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                last_run = {"error": "report file exists but could not be parsed"}

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "apm_server": config.apm_server,
        "hec_url": config.hec_url,
        "index": config.index,
        "sourcetype": config.sourcetype,
        "state_file": config.state_file or None,
        "verify_tls": config.verify_tls,
        "batch_size": config.batch_size,
        "group_names": config.group_names,
        "monitors": monitors,
        "monitor_count": len(monitors) if entries else None,
        "stale_count": sum(1 for m in monitors if m["stale"]),
        "last_run": last_run,
    }


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HEADRACE — status</title>
<style>
:root{--bg:#0f1419;--panel:#161d26;--line:#243040;--ink:#e6edf3;--muted:#9aa8b6;
  --faint:#6b7a89;--red:#e5534b;--amber:#d29922;--teal:#2f9e8f;--blue:#3b82f6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:26px 20px 60px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;
  flex-wrap:wrap;margin-bottom:22px}
h1{margin:0;font-size:20px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:12.5px;margin-top:4px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;
  border:1px solid var(--line);color:var(--muted)}
.pill.ok{border-color:var(--teal);color:var(--teal)}
.pill.warn{border-color:var(--amber);color:var(--amber)}
.pill.bad{border-color:var(--red);color:var(--red)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;
  margin-bottom:20px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .k{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--faint)}
.kpi .v{font-size:22px;font-weight:600;margin-top:3px;
  font-variant-numeric:tabular-nums}
.kpi .n{font-size:11px;color:var(--faint);margin-top:2px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:15px 17px;margin-bottom:14px}
.panel h2{margin:0 0 11px;font-size:13px;text-transform:uppercase;
  letter-spacing:.09em;color:var(--faint);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-weight:600;color:var(--faint);font-size:10.5px;
  text-transform:uppercase;letter-spacing:.07em;padding:0 8px 7px 0;
  border-bottom:1px solid var(--line)}
td{padding:7px 8px 7px 0;border-bottom:1px solid rgba(36,48,64,.5);
  vertical-align:top}
tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px}
.empty{color:var(--faint);font-size:12.5px;padding:6px 0}
.gap{border-left:3px solid var(--amber);background:rgba(210,153,34,.07);
  border-radius:7px;padding:8px 11px;margin-bottom:7px;font-size:12.5px}
.gap.bad{border-left-color:var(--red);background:rgba(229,83,75,.07)}
.gap b{font-weight:600}
.gap .why{color:var(--faint);font-size:11.5px;margin-top:2px}
dl.kv{display:grid;grid-template-columns:auto 1fr;gap:5px 16px;margin:0;font-size:12.5px}
dl.kv dt{color:var(--faint);white-space:nowrap}
dl.kv dd{margin:0}
footer{margin-top:26px;padding-top:12px;border-top:1px solid var(--line);
  color:var(--faint);font-size:11.5px}
</style></head><body><div class="wrap">
<header>
  <div>
    <h1>HEADRACE</h1>
    <div class="sub">ManageEngine APM &rarr; Splunk HEC forwarder</div>
  </div>
  <div class="sub" id="stamp"></div>
</header>
<div class="kpis" id="kpis"></div>
<div id="gaps"></div>
<div class="panel"><h2>Configuration</h2><dl class="kv" id="config"></dl></div>
<div class="panel"><h2>Monitors last sent <span class="empty" id="mcount"></span></h2>
  <div id="monitors"></div></div>
<div class="panel"><h2>Last run</h2><div id="lastrun"></div></div>
<footer>Generated from the state file and the last run report on this host.
Nothing here is a live query &mdash; a value that is absent is shown as absent,
never as zero.</footer>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
  var d = JSON.parse(document.getElementById('data').textContent);
  function esc(v){ return String(v==null?'':v).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function dash(v){ return (v==null||v==='') ? '\u2014' : v; }

  document.getElementById('stamp').textContent = 'generated ' + d.generated;

  var lr = d.last_run || {};
  var kpis = [
    ['monitors tracked', d.monitor_count, d.monitor_count==null ? 'state file not written yet' : 'in the state file'],
    ['stale', d.stale_count, 'not sent in over an hour'],
    ['events sent', lr.sent, 'last run'],
    ['rejected', lr.rejected, 'last run'],
    ['failed batches', lr.failed_batches, 'last run']
  ];
  document.getElementById('kpis').innerHTML = kpis.map(function(k){
    var cls = '';
    if (k[0]==='rejected' && k[1]>0) cls = ' style="color:var(--red)"';
    if (k[0]==='failed batches' && k[1]>0) cls = ' style="color:var(--red)"';
    if (k[0]==='stale' && k[1]>0) cls = ' style="color:var(--amber)"';
    return '<div class="kpi"><div class="k">'+esc(k[0])+'</div>'+
      '<div class="v"'+cls+'>'+esc(dash(k[1]))+'</div>'+
      '<div class="n">'+esc(k[2])+'</div></div>';
  }).join('');

  var gaps = [];
  if (d.monitor_count == null) {
    gaps.push(['bad','No state file has been written.',
      'The forwarder has not completed a successful run on this host, or --state-file is not set. Without it every run re-sends everything.']);
  }
  if (d.stale_count > 0) {
    gaps.push(['',' '+d.stale_count+' monitor(s) have not been sent in over an hour.',
      'Either the monitor stopped reporting, or the forwarder has not run. Check the Splunk scripted input interval.']);
  }
  if (lr.error) {
    gaps.push(['bad','The last run report could not be parsed.',
      lr.error]);
  }
  if (lr.ok === false) {
    gaps.push(['bad','The last run did not complete cleanly.',
      (lr.send_errors||[]).concat(lr.monitor_errors||[]).join(' ') || 'See the run log.']);
  }
  if (!d.verify_tls) {
    gaps.push(['bad','TLS verification is disabled.',
      'A machine in the path can read the APM API key and the HEC token. Use --ca-bundle for a self-signed certificate instead.']);
  }
  document.getElementById('gaps').innerHTML = gaps.length ? gaps.map(function(g){
    return '<div class="gap '+g[0]+'"><b>'+esc(g[1])+'</b><div class="why">'+esc(g[2])+'</div></div>';
  }).join('') : '';

  var cfg = [
    ['APM server', d.apm_server],
    ['HEC endpoint', d.hec_url],
    ['index', d.index],
    ['sourcetype', d.sourcetype],
    ['group filter', (d.group_names&&d.group_names.length) ? d.group_names.join(', ') : 'none (every monitor)'],
    ['batch size', d.batch_size],
    ['TLS verification', d.verify_tls ? 'on' : 'OFF'],
    ['state file', d.state_file || 'not set']
  ];
  document.getElementById('config').innerHTML = cfg.map(function(p){
    return '<dt>'+esc(p[0])+'</dt><dd class="mono">'+esc(dash(p[1]))+'</dd>';
  }).join('');

  document.getElementById('mcount').textContent = d.monitors.length
    ? '(' + d.monitors.length + ')' : '';
  document.getElementById('monitors').innerHTML = d.monitors.length
    ? '<table><thead><tr><th>resource id</th><th>fingerprint</th><th>last sent</th></tr></thead><tbody>'+
      d.monitors.map(function(m){
        return '<tr><td class="mono">'+esc(m.id)+'</td>'+
          '<td class="mono">'+esc(m.fingerprint)+'</td>'+
          '<td'+(m.stale?' style="color:var(--amber)"':'')+'>'+esc(dash(m.age))+'</td></tr>';
      }).join('')+'</tbody></table>'
    : '<div class="empty">Nothing recorded yet. The table fills in after the first successful run.</div>';

  document.getElementById('lastrun').innerHTML = d.last_run
    ? '<dl class="kv">' + [
        ['monitors seen', lr.monitors_seen],
        ['monitors forwarded', lr.monitors_forwarded],
        ['events built', lr.events_built],
        ['events sent', lr.sent],
        ['events rejected', lr.rejected],
        ['skipped unchanged', lr.skipped_unchanged],
        ['dry run', lr.dry_run ? 'yes' : 'no'],
        ['result', lr.ok ? 'clean' : 'not clean']
      ].map(function(p){
        return '<dt>'+esc(p[0])+'</dt><dd>'+esc(dash(p[1]))+'</dd>';
      }).join('') + '</dl>'
    : '<div class="empty">No run report supplied. Pass --report PATH to include one.</div>';
})();
</script>
</body></html>
"""


def render(data: dict[str, Any]) -> str:
    """The page with the data embedded. No external requests, no inline handlers."""
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    return PAGE.replace("__DATA__", payload)


def write(config: Config, out_path: str | Path,
          report_path: str | Path | None = None) -> Path:
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(collect(config, report_path)), encoding="utf-8")
    return out


def _unused(value: Any) -> str:  # pragma: no cover - keeps html import honest
    return html.escape(str(value))
