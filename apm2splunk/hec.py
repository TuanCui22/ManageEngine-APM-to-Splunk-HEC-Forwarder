"""Splunk HEC sender.

The original sent one HTTP request per event and checked ``status_code == 200``.
Both are wrong in ways that only show up at scale or under failure:

* HEC accepts an array of events in one request. One request per event means a
  monitor with 40 children costs 41 round trips every interval.
* HEC returns **200 even when individual events are rejected**. The per-event
  verdict is in the response body's ``code`` field. Checking only the status code
  reports success for a batch where every event was dropped for a wrong index.

This module batches, retries only what is worth retrying, and reports per-event
rejections as errors rather than as success.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import requests

from .config import Config

#: HEC codes that mean "this batch will never succeed as sent".
#: 4 = invalid event, 5 = no index, 6 = invalid token, 7 = invalid data format,
#: 9 = channel missing, 12 = event too large, 13 = too many events.
PERMANENT_CODES = frozenset({4, 5, 6, 7, 9, 12, 13})

#: Codes worth retrying: 1 = token disabled, 2 = token required, 3 = invalid
#: authorization, 8 = internal error, 9 = busy (also permanent above), 10 = data
#: channel missing, 11 = server busy.
RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})


class HecError(Exception):
    """A batch could not be delivered."""


@dataclass
class SendResult:
    sent: int = 0
    rejected: int = 0
    failed_batches: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.rejected == 0 and self.failed_batches == 0

    def merge(self, other: "SendResult") -> None:
        self.sent += other.sent
        self.rejected += other.rejected
        self.failed_batches += other.failed_batches
        self.errors.extend(other.errors)


class HecClient:
    """Batching, retrying HEC client."""

    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self._verify: bool | str = config.verify_tls
        if config.ca_bundle:
            self._verify = config.ca_bundle

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Splunk %s" % self.config.hec_token,
            "Content-Type": "application/json",
        }

    def _event(self, body: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {
            "index": self.config.index,
            "sourcetype": self.config.sourcetype,
            "event": body,
        }
        host = body.get("host")
        if host and host != "unknown":
            event["host"] = str(host)
        return event

    def send_batch(self, bodies: Sequence[dict[str, Any]]) -> SendResult:
        """Send one batch. Retries transient failures, reports permanent ones."""
        result = SendResult()
        if not bodies:
            return result

        payload = json.dumps([self._event(b) for b in bodies])
        last_error = ""

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self.config.hec_url, headers=self._headers(), data=payload,
                    verify=self._verify, timeout=self.config.timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if response.status_code in RETRYABLE_HTTP:
                    last_error = "HTTP %d" % response.status_code
                elif response.status_code != 200:
                    result.failed_batches += 1
                    result.errors.append(
                        "HEC rejected the batch with HTTP %d: %s"
                        % (response.status_code, _short(response.text)))
                    return result
                else:
                    return self._read_verdict(response, bodies, result)

            if attempt < self.config.max_retries:
                time.sleep(min(2 ** attempt, 8))

        result.failed_batches += 1
        result.errors.append(
            "HEC unreachable after %d attempt(s): %s"
            % (self.config.max_retries + 1, last_error))
        return result

    def _read_verdict(self, response: requests.Response, bodies: Sequence[dict[str, Any]],
                      result: SendResult) -> SendResult:
        """HEC answers 200 even when events were dropped. Read the body."""
        try:
            body = response.json()
        except ValueError:
            # A 200 with a non-JSON body is not a success we can verify.
            result.failed_batches += 1
            result.errors.append(
                "HEC returned 200 with a non-JSON body: %s" % _short(response.text))
            return result

        code = body.get("code")
        if code == 0:
            result.sent += len(bodies)
            return result

        text = str(body.get("text") or "").strip()
        if code in PERMANENT_CODES:
            result.rejected += len(bodies)
            result.errors.append(
                "HEC code %s (%s): the whole batch of %d event(s) was dropped"
                % (code, text or "no detail", len(bodies)))
        else:
            result.rejected += len(bodies)
            result.errors.append(
                "HEC code %s (%s): batch of %d event(s) not acknowledged"
                % (code, text or "no detail", len(bodies)))
        return result

    def send_all(self, bodies: Iterable[dict[str, Any]]) -> SendResult:
        """Send everything, in batches of ``config.batch_size``."""
        total = SendResult()
        batch: list[dict[str, Any]] = []
        for body in bodies:
            batch.append(body)
            if len(batch) >= self.config.batch_size:
                total.merge(self.send_batch(batch))
                batch = []
        if batch:
            total.merge(self.send_batch(batch))
        return total


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"
