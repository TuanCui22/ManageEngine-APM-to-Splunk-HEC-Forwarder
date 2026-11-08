"""Command-line entry point.

Two modes, because they are used by different people at different times:

* ``forward`` — the Splunk scripted-input path. Quiet by default, exit code is
  the only signal Splunk reads, so the exit code has to mean something.
* ``check`` — the "is my config right" path, run by a human before deploying.
  It touches both endpoints and prints what it found without sending an event.

Exit codes:
  0  success
  1  a monitor could not be read, or HEC rejected events
  2  configuration is missing or malformed
  3  APM or HEC was unreachable
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Sequence

from . import __version__
from .apm import ApmClient, ApmError
from .config import Config, ConfigError, build_config
from .forwarder import StateStore, forward
from .hec import HecClient
from .status import write as write_status

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_UNREACHABLE = 3


def _add_connection_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("connection")
    group.add_argument("--apm-server", metavar="URL",
                       help="ManageEngine APM base URL, e.g. https://apm.example:9090")
    group.add_argument("--apm-api-key", metavar="KEY",
                       help="APM API key (prefer %sAPM_API_KEY)" % "APM2SPLUNK_")
    group.add_argument("--hec-url", metavar="URL",
                       help="Splunk HEC endpoint, e.g. https://splunk:8088/services/collector")
    group.add_argument("--hec-token", metavar="TOKEN",
                       help="Splunk HEC token (prefer APM2SPLUNK_HEC_TOKEN)")
    group.add_argument("--index", metavar="NAME", help="target Splunk index")
    group.add_argument("--sourcetype", metavar="NAME",
                       help="sourcetype for the events (default manageengine:apm)")


def _add_behaviour_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("behaviour")
    group.add_argument("--group", action="append", dest="group_names", metavar="NAME",
                       help="only forward monitors in this group; repeatable")
    group.add_argument("--batch-size", type=int, metavar="N",
                       help="events per HEC request (default 100)")
    group.add_argument("--timeout", type=float, metavar="SECONDS",
                       help="per-request timeout (default 30)")
    group.add_argument("--max-retries", type=int, metavar="N",
                       help="retries for transient failures (default 3)")
    group.add_argument("--state-file", metavar="PATH",
                       help="JSON file remembering what was already sent")
    group.add_argument("--no-verify-tls", action="store_true",
                       help="disable TLS verification (see --ca-bundle first)")
    group.add_argument("--ca-bundle", metavar="PATH",
                       help="CA bundle for a self-signed APM or Splunk certificate")
    group.add_argument("--log-level", metavar="LEVEL",
                       help="DEBUG, INFO, WARNING, ERROR (default INFO)")
    group.add_argument("--json", dest="json_out", action="store_true",
                       help="print the run report as JSON on stdout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apm2splunk",
        description="Forward ManageEngine APM monitor data to Splunk HEC.",
        epilog="Configuration precedence: flags > environment > config file > defaults. "
               "Environment variables are prefixed APM2SPLUNK_.",
    )
    parser.add_argument("--version", action="version",
                        version="apm2splunk %s" % __version__)
    parser.add_argument("--config", metavar="PATH",
                        help="JSON or TOML config file")

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("forward", help="read APM and send to HEC (the scripted-input mode)")
    _add_connection_flags(run)
    _add_behaviour_flags(run)
    run.add_argument("--dry-run", action="store_true",
                     help="build events and report counts, send nothing")

    check = sub.add_parser("check", help="verify config and reachability, send nothing")
    _add_connection_flags(check)
    _add_behaviour_flags(check)

    status = sub.add_parser(
        "status", help="write a self-contained HTML status page from the state file")
    _add_connection_flags(status)
    _add_behaviour_flags(status)
    status.add_argument("--out", metavar="PATH", default="apm2splunk-status.html",
                        help="where to write the page (default apm2splunk-status.html)")
    status.add_argument("--report", metavar="PATH",
                        help="a run report written with `forward --json > report.json`")

    return parser


def _configure_logging(level: str, *, quiet: bool) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr if quiet else sys.stdout,
    )


def _config_from_args(args: argparse.Namespace) -> Config:
    flags: dict[str, Any] = {
        "apm_server": args.apm_server,
        "apm_api_key": args.apm_api_key,
        "hec_url": args.hec_url,
        "hec_token": args.hec_token,
        "index": args.index,
        "sourcetype": args.sourcetype,
        "batch_size": args.batch_size,
        "timeout": args.timeout,
        "max_retries": args.max_retries,
        "state_file": args.state_file,
        "ca_bundle": args.ca_bundle,
        "log_level": args.log_level,
        "group_names": args.group_names,
    }
    if getattr(args, "no_verify_tls", False):
        flags["verify_tls"] = False
    return build_config(flags, config_file=args.config)


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args)
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        return EXIT_CONFIG

    _configure_logging(config.log_level, quiet=False)
    print("configuration looks complete:")
    for key, value in config.redacted().items():
        print("  %-16s %s" % (key, value))

    client = ApmClient(config)
    try:
        monitors = client.list_monitors()
    except ApmError as exc:
        print("\nAPM is not reachable: %s" % exc, file=sys.stderr)
        return EXIT_UNREACHABLE
    print("\nAPM reachable: %d monitor(s)" % len(monitors))
    for monitor in monitors[:10]:
        print("  %s  %s" % (monitor.get("RESOURCEID", "?"),
                            monitor.get("DISPLAYNAME", "?")))
    if len(monitors) > 10:
        print("  … and %d more" % (len(monitors) - 10))

    hec = HecClient(config)
    # A single harmless event proves the token and the index without touching
    # the APM data path.
    probe = hec.send_batch([{
        "host": "apm2splunk-check",
        "source": "apm2splunk",
        "message": "connectivity check from apm2splunk %s" % __version__,
    }])
    if not probe.ok:
        print("\nHEC rejected the probe event:", file=sys.stderr)
        for error in probe.errors:
            print("  " + error, file=sys.stderr)
        return EXIT_UNREACHABLE
    print("\nHEC accepted a probe event into index %r" % config.index)
    print("\nBoth endpoints work. Run `apm2splunk forward --dry-run` next.")
    return EXIT_OK


def _cmd_forward(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args)
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        return EXIT_CONFIG

    _configure_logging(config.log_level, quiet=args.json_out)

    try:
        report = forward(config, dry_run=args.dry_run,
                         state=StateStore(config.state_file or None))
    except ApmError as exc:
        print("APM error: %s" % exc, file=sys.stderr)
        return EXIT_UNREACHABLE

    if args.json_out:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print("monitors seen       %d" % report.monitors_seen)
        print("monitors forwarded  %d" % report.monitors_forwarded)
        print("events built        %d" % report.events_built)
        print("events sent         %d" % report.send.sent)
        print("events rejected     %d" % report.send.rejected)
        print("skipped unchanged   %d" % report.skipped_unchanged)
        for error in report.monitor_errors:
            print("monitor error: %s" % error, file=sys.stderr)
        for error in report.send.errors:
            print("send error: %s" % error, file=sys.stderr)

    return EXIT_OK if report.ok else EXIT_PARTIAL


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args)
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        return EXIT_CONFIG
    out = write_status(config, args.out, report_path=args.report)
    print("wrote %s" % out)
    print("open it in a browser; it makes no network requests.")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "check":
        return _cmd_check(args)
    if args.command == "status":
        return _cmd_status(args)
    return _cmd_forward(args)


if __name__ == "__main__":
    raise SystemExit(main())
