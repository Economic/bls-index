"""HTTPS fetcher for BLS flat files.

Every input is downloaded in full on every run. No HEAD requests, conditional requests,
or header checks are used to skip a download, and each file is downloaded once.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from bls_index.scope import input_files, source_path

DEFAULT_BASE_URL = "https://download.bls.gov/pub/time.series/"
# BLS blocks robots that request "multiple times per second" (bls.gov/bls/pss.htm).
BLS_MIN_REQUEST_INTERVAL = 1.0
USER_AGENT_ENV = "BLS_INDEX_USER_AGENT"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

log = logging.getLogger(__name__)


def validate_user_agent(user_agent: str) -> str:
    """BLS rejects anonymous clients; require a descriptive agent with contact details."""
    ua = user_agent.strip()
    if not ua:
        raise ValueError("User-Agent must not be empty")
    if "@" not in ua and "http://" not in ua and "https://" not in ua:
        raise ValueError("User-Agent must include contact details (an email address or URL)")
    if "github" in ua.lower():
        # Observed 2026-10-07: download.bls.gov returns 403 for any User-Agent containing
        # "github" (including github.com and github.io URLs).
        raise ValueError("BLS rejects User-Agents containing 'github'; use another contact URL")
    return ua


def user_agent_from_env() -> str:
    value = os.environ.get(USER_AGENT_ENV)
    if not value:
        raise ValueError(f"set {USER_AGENT_ENV} to a descriptive, contactable User-Agent")
    return validate_user_agent(value)


def _is_loopback(url: str) -> bool:
    return urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str
    base_url: str = DEFAULT_BASE_URL
    connect_timeout: float = 30.0
    read_timeout: float = 120.0
    max_attempts: int = 4
    backoff_initial: float = 2.0
    backoff_max: float = 60.0
    # Minimum seconds between request starts. Lower values are allowed only for local
    # test servers.
    min_request_interval: float = BLS_MIN_REQUEST_INTERVAL

    def __post_init__(self) -> None:
        validate_user_agent(self.user_agent)
        if not self.base_url.endswith("/"):
            raise ValueError("base_url must end with '/'")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not math.isfinite(self.min_request_interval) or self.min_request_interval < 0:
            raise ValueError("min_request_interval must be a finite, non-negative number")
        if self.min_request_interval < BLS_MIN_REQUEST_INTERVAL and not _is_loopback(self.base_url):
            raise ValueError(
                f"min_request_interval below {BLS_MIN_REQUEST_INTERVAL}s is allowed only for "
                "local test sources"
            )


@dataclass(frozen=True)
class Download:
    url: str
    path: Path
    bytes: int
    sha256: str


class SourceError(Exception):
    """A download failed. ``reason`` is http_status, timeout, transport, incomplete, or
    content_encoding."""

    def __init__(self, url: str, reason: str, message: str, *, status: int | None = None,
                 retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(f"{url}: {reason}: {message}")
        self.url = url
        self.reason = reason
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


class HttpSource:
    def __init__(
        self,
        config: FetchConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._monotonic = monotonic
        self._next_start: float | None = None
        self._client = httpx.Client(
            headers={
                "User-Agent": validate_user_agent(config.user_agent),
                # Byte-exact bodies: SHA-256 and Content-Length refer to the file itself.
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout),
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch_program(self, program: str, directory: Path) -> dict[str, Download]:
        """Download every input file for ``program`` into ``directory/program``."""
        return {
            name: self.download(source_path(program, name), directory / program / name)
            for name in input_files(program)
        }

    def download(self, rel_path: str, dest: Path) -> Download:
        """GET one file into ``dest``, retrying transient failures with backoff."""
        url = self.config.base_url + rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return self._download_once(url, dest)
            except SourceError as exc:
                delay = self._retry_delay(attempt, exc)
                if not exc.retryable or attempt == self.config.max_attempts or delay is None:
                    raise
                log.info("retrying %s in %.1fs after %s (attempt %d)", url, delay, exc.reason, attempt)
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _retry_delay(self, attempt: int, exc: SourceError) -> float | None:
        """Exponential backoff, never shorter than Retry-After; None if Retry-After is too long."""
        delay = min(self.config.backoff_initial * 2 ** (attempt - 1), self.config.backoff_max)
        if exc.retry_after is not None:
            if exc.retry_after > self.config.backoff_max:
                return None
            delay = max(delay, exc.retry_after)
        return delay

    def _pace(self) -> None:
        now = self._monotonic()
        if self._next_start is not None and now < self._next_start:
            self._sleep(self._next_start - now)

    def _hold_next_start(self) -> None:
        """Start the interval once a request has reached the server (or failed), so a
        slow connection cannot bunch two requests together at the server."""
        self._next_start = self._monotonic() + self.config.min_request_interval

    def _download_once(self, url: str, dest: Path) -> Download:
        digest = hashlib.sha256()
        size = 0
        body_started = False
        headers_received = False
        self._pace()
        try:
            with self._client.stream("GET", url) as resp:
                self._hold_next_start()
                headers_received = True
                if resp.status_code != 200:
                    raise SourceError(
                        url, "http_status", f"HTTP {resp.status_code}", status=resp.status_code,
                        retryable=resp.status_code in RETRYABLE_STATUS,
                        retry_after=_parse_retry_after(resp.headers.get("retry-after")),
                    )  # fmt: skip
                encoding = resp.headers.get("content-encoding", "identity").lower()
                if encoding != "identity":
                    raise SourceError(url, "content_encoding", f"unexpected Content-Encoding {encoding!r}",
                                      retryable=False)
                expected = resp.headers.get("content-length")
                with dest.open("wb") as stream:
                    body_started = True
                    for chunk in resp.iter_raw(1 << 20):
                        digest.update(chunk)
                        stream.write(chunk)
                        size += len(chunk)
        except httpx.TimeoutException as exc:
            raise SourceError(url, "incomplete" if body_started else "timeout", repr(exc),
                              retryable=True) from exc
        except httpx.TransportError as exc:
            raise SourceError(url, "incomplete" if body_started else "transport", repr(exc),
                              retryable=True) from exc
        finally:
            if not headers_received:
                self._hold_next_start()
        if expected is not None and int(expected) != size:
            raise SourceError(url, "incomplete", f"received {size} of {expected} bytes", retryable=True)
        return Download(url, dest, size, digest.hexdigest())


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds to wait from a Retry-After header: delay-seconds or an HTTP-date."""
    if value is None:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:  # RFC 9110 dates are GMT
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())
