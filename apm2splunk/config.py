"""Configuration for the APM → Splunk HEC forwarder.

A credential in a file that gets committed is a credential that has to be
rotated, and an address in a file cannot be changed without editing code. So
neither lives in the source: everything resolves at runtime.

Resolution order, highest first:
  1. command-line flags
  2. environment variables
  3. a config file (JSON or TOML)
  4. defaults

Nothing here has a default secret. A missing token is an error at startup, not a
request that silently fails at 3am.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_PREFIX = "APM2SPLUNK_"

#: Environment variable name for each setting. Kept explicit rather than derived
#: so a rename in one place cannot silently break deployment scripts.
ENV_MAP = {
    "apm_server": "APM_SERVER",
    "apm_api_key": "APM_API_KEY",
    "hec_url": "HEC_URL",
    "hec_token": "HEC_TOKEN",
    "index": "INDEX",
    "sourcetype": "SOURCETYPE",
    "verify_tls": "VERIFY_TLS",
    "ca_bundle": "CA_BUNDLE",
    "timeout": "TIMEOUT",
    "max_retries": "MAX_RETRIES",
    "batch_size": "BATCH_SIZE",
    "state_file": "STATE_FILE",
    "log_level": "LOG_LEVEL",
    "group_names": "GROUP_NAMES",
}


class ConfigError(Exception):
    """Configuration is missing or malformed. Raised before any network call."""


@dataclass
class Config:
    apm_server: str = ""
    apm_api_key: str = ""
    hec_url: str = ""
    hec_token: str = ""
    index: str = ""
    sourcetype: str = "manageengine:apm"
    #: TLS verification. Default True: the original passed verify=False on every
    #: call, which turns a MITM on the management network into a credential leak.
    verify_tls: bool = True
    ca_bundle: str = ""
    timeout: float = 30.0
    max_retries: int = 3
    #: Events per HEC request. HEC accepts an array; one request per event is the
    #: single biggest throughput cost in the original.
    batch_size: int = 100
    state_file: str = ""
    log_level: str = "INFO"
    #: Only forward monitors in these groups. Empty means every monitor.
    group_names: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Fail loudly, before a socket is opened."""
        missing = [
            name for name in ("apm_server", "apm_api_key", "hec_url", "hec_token", "index")
            if not getattr(self, name)
        ]
        if missing:
            raise ConfigError(
                "missing required setting(s): %s. Set them with --%s, the %s* "
                "environment variables, or a config file."
                % (", ".join(missing),
                   ", --".join(m.replace("_", "-") for m in missing),
                   ENV_PREFIX))
        if not self.apm_server.startswith(("http://", "https://")):
            raise ConfigError("apm_server must start with http:// or https://")
        if not self.hec_url.startswith(("http://", "https://")):
            raise ConfigError("hec_url must start with http:// or https://")
        if self.batch_size < 1:
            raise ConfigError("batch_size must be at least 1")
        if self.max_retries < 0:
            raise ConfigError("max_retries cannot be negative")
        if self.timeout <= 0:
            raise ConfigError("timeout must be positive")

    def redacted(self) -> dict[str, Any]:
        """The config as a dict, with secrets replaced. Safe to log."""
        out = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name in ("apm_api_key", "hec_token") and value:
                out[name] = value[:4] + "…" + value[-2:] if len(value) > 8 else "***"
            else:
                out[name] = value
        return out


def _coerce(name: str, raw: Any) -> Any:
    """Turn a string from env or file into the field's type."""
    if name == "verify_tls":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in ("0", "false", "no", "off", "")
    if name in ("timeout",):
        return float(raw)
    if name in ("max_retries", "batch_size"):
        return int(raw)
    if name == "group_names":
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return [part.strip() for part in str(raw).split(",") if part.strip()]
    return str(raw)


def load_config_file(path: str | Path) -> dict[str, Any]:
    """Read a JSON or TOML config file. Unknown keys are refused."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise ConfigError("config file not found: %s" % file)
    raw = file.read_bytes()
    try:
        if file.suffix.lower() == ".toml":
            data = tomllib.loads(raw.decode("utf-8"))
        else:
            data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ConfigError("cannot parse config %s: %s" % (file, exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError("config %s must be an object at the top level" % file)

    known = set(Config.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ConfigError(
            "config %s has unknown key(s): %s. Known keys: %s"
            % (file, ", ".join(sorted(unknown)), ", ".join(sorted(known))))
    return data


def build_config(flags: dict[str, Any] | None = None,
                 config_file: str | Path | None = None,
                 env: dict[str, str] | None = None) -> Config:
    """Merge file, environment and flags into a validated Config.

    Precedence: flags > environment > file > defaults. A flag whose value is
    None is treated as absent, so argparse defaults do not mask the environment.
    """
    env = os.environ if env is None else env
    values: dict[str, Any] = {}

    if config_file:
        for key, raw in load_config_file(config_file).items():
            values[key] = _coerce(key, raw)

    for name, suffix in ENV_MAP.items():
        key = ENV_PREFIX + suffix
        if key in env and env[key] != "":
            values[name] = _coerce(name, env[key])

    for name, raw in (flags or {}).items():
        if raw is not None and raw != "":
            values[name] = _coerce(name, raw)

    config = Config(**{k: v for k, v in values.items()
                       if k in Config.__dataclass_fields__})
    config.validate()
    return config
