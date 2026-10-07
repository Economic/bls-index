"""HTTPS fetcher for BLS flat files.

Every input is downloaded in full on every run: no HEAD requests, conditional requests,
or header checks are used to skip a download. Each program's inputs form one build unit
that is downloaded, then downloaded again and compared by SHA-256 (BLS validators are
not yet established as reliable). A changed or incomplete input retries the program's
entire input set up to a fixed limit.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from bls_index.clock import Clock, isoformat_utc
from bls_index.events import EventLog
from bls_index.scope import input_files, source_path

DEFAULT_BASE_URL = "https://download.bls.gov/pub/time.series/"
USER_AGENT_ENV = "BLS_INDEX_USER_AGENT"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RECORDED_HEADERS = (
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "date",
    "accept-ranges",
    "content-encoding",
)


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


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str
    base_url: str = DEFAULT_BASE_URL
    connect_timeout: float = 30.0
    read_timeout: float = 120.0
    max_request_attempts: int = 4
    backoff_initial: float = 2.0
    backoff_max: float = 60.0
    # Provisional; Phase 1 sets the final limit from measured behavior.
    max_input_set_attempts: int = 3
    max_concurrency: int = 4
    # Minimum seconds between request starts across all workers. BLS blocks robots
    # that "access or download survey information multiple times per second".
    min_request_interval: float = 1.0

    def __post_init__(self) -> None:
        validate_user_agent(self.user_agent)
        if not self.base_url.endswith("/"):
            raise ValueError("base_url must end with '/'")
        for name in ("max_request_attempts", "max_input_set_attempts", "max_concurrency"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.min_request_interval < 0:
            raise ValueError("min_request_interval must not be negative")


@dataclass(frozen=True)
class DownloadRecord:
    url: str
    path: Path | None  # None once the local copy is deleted (identity rechecks)
    status: int
    bytes: int
    sha256: str
    headers: Mapping[str, str]
    started_at: datetime
    finished_at: datetime
    request_attempts: int

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "headers": dict(self.headers),
            "started_at": isoformat_utc(self.started_at),
            "finished_at": isoformat_utc(self.finished_at),
            "request_attempts": self.request_attempts,
        }


class SourceError(Exception):
    """A single download failed. ``reason`` is one of: http_status, timeout, transport,
    incomplete, content_encoding."""

    def __init__(
        self,
        url: str,
        reason: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{url}: {reason}: {message}")
        self.url = url
        self.reason = reason
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class InputSet:
    """One program's inputs, each downloaded twice with identical SHA-256."""

    program: str
    files: tuple[DownloadRecord, ...]
    rechecks: tuple[DownloadRecord, ...]  # metadata only; their files are deleted
    attempts: int


@dataclass(eq=False)
class InputSetError(Exception):
    program: str
    attempts: int
    reason: str  # "source_error" or "changed_during_build"
    detail: str
    source_error: SourceError | None = None

    def __str__(self) -> str:
        return f"{self.program}: {self.reason} after {self.attempts} attempt(s): {self.detail}"


class RequestPacer:
    """Spaces request starts at least ``interval`` seconds apart across threads.

    Each caller reserves the next free start slot under a lock, then sleeps outside
    the lock until that slot, so concurrent workers queue in order without bursting.
    """

    def __init__(
        self,
        interval: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start: float | None = None

    def wait(self) -> float:
        """Block until this caller may start a request; return the seconds waited."""
        if self.interval <= 0:
            return 0.0
        with self._lock:
            now = self._monotonic()
            start = now if self._next_start is None else max(now, self._next_start)
            self._next_start = start + self.interval
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return delay


class HttpSource:
    def __init__(
        self,
        config: FetchConfig,
        events: EventLog,
        clock: Clock,
        *,
        sleep: Callable[[float], None] = time.sleep,
        pacer: RequestPacer | None = None,
    ) -> None:
        """``sleep`` is used for retry backoff; request pacing uses ``pacer``, which
        defaults to real time with ``config.min_request_interval``."""
        self.config = config
        self._events = events
        self._clock = clock
        self._sleep = sleep
        self._pacer = pacer or RequestPacer(config.min_request_interval)
        self._client = httpx.Client(
            headers={
                "User-Agent": validate_user_agent(config.user_agent),
                # Byte-exact bodies: SHA-256 and Content-Length refer to the file itself.
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout),
            limits=httpx.Limits(max_connections=config.max_concurrency),
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- single files -------------------------------------------------------------

    def download(self, rel_path: str, dest: Path) -> DownloadRecord:
        """GET one file into ``dest`` with request-level retries for transient errors.

        Incomplete bodies are not retried here; they fail the attempt so the caller
        retries the whole program input set.
        """
        url = self.config.base_url + rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        attempt = 1
        while True:
            try:
                return self._download_once(url, dest, attempt)
            except SourceError as exc:
                if (
                    not exc.retryable
                    or exc.reason == "incomplete"
                    or attempt >= self.config.max_request_attempts
                ):
                    raise
                delay = self._retry_delay(attempt, exc)
                if delay is None:
                    raise
                self._events.record(
                    "http.retry", url=url, attempt=attempt, reason=exc.reason,
                    status=exc.status, delay=delay,
                )  # fmt: skip
                self._sleep(delay)
                attempt += 1

    def _retry_delay(self, attempt: int, exc: SourceError | None = None) -> float | None:
        """Exponential backoff, never shorter than the server's Retry-After.

        Returns None when Retry-After exceeds ``backoff_max``: the caller stops retrying
        rather than retrying before the server asked it to.
        """
        delay = min(self.config.backoff_initial * 2 ** (attempt - 1), self.config.backoff_max)
        retry_after = exc.retry_after if exc is not None else None
        if retry_after is not None:
            if retry_after > self.config.backoff_max:
                self._events.record(
                    "http.retry_after_exceeds_limit", url=exc.url, retry_after=retry_after,
                    backoff_max=self.config.backoff_max,
                )  # fmt: skip
                return None
            delay = max(delay, retry_after)
        return delay

    def _download_once(self, url: str, dest: Path, attempt: int) -> DownloadRecord:
        paced = self._pacer.wait()
        self._events.record(
            "http.request", method="GET", url=url, attempt=attempt, paced_seconds=round(paced, 3)
        )
        started = self._clock.now()
        body_started = False
        digest = hashlib.sha256()
        size = 0
        try:
            with self._client.stream("GET", url) as resp:
                status = resp.status_code
                headers = {k: resp.headers[k] for k in RECORDED_HEADERS if k in resp.headers}
                if status != 200:
                    raise SourceError(
                        url, "http_status", f"HTTP {status}", status=status,
                        retryable=status in RETRYABLE_STATUS,
                        retry_after=_parse_retry_after(
                            resp.headers.get("retry-after"), self._clock.now()
                        ),
                    )  # fmt: skip
                encoding = headers.get("content-encoding", "identity").lower()
                if encoding != "identity":
                    raise SourceError(
                        url, "content_encoding", f"unexpected Content-Encoding {encoding!r}",
                        status=status, retryable=False,
                    )  # fmt: skip
                with dest.open("wb") as fh:
                    body_started = True
                    for chunk in resp.iter_raw(1 << 20):
                        digest.update(chunk)
                        fh.write(chunk)
                        size += len(chunk)
        except httpx.TimeoutException as exc:
            reason = "incomplete" if body_started else "timeout"
            raise SourceError(url, reason, repr(exc), retryable=True) from exc
        except httpx.TransportError as exc:
            reason = "incomplete" if body_started else "transport"
            raise SourceError(url, reason, repr(exc), retryable=True) from exc

        expected = headers.get("content-length")
        if expected is not None and int(expected) != size:
            raise SourceError(
                url, "incomplete", f"received {size} of {expected} bytes",
                status=status, retryable=True,
            )  # fmt: skip
        record = DownloadRecord(
            url=url, path=dest, status=status, bytes=size, sha256=digest.hexdigest(),
            headers=headers, started_at=started, finished_at=self._clock.now(),
            request_attempts=attempt,
        )  # fmt: skip
        self._events.record(
            "http.response", url=url, status=status, bytes=size, sha256=record.sha256,
            etag=headers.get("etag"), last_modified=headers.get("last-modified"),
        )  # fmt: skip
        return record

    # -- program input sets --------------------------------------------------------

    def fetch_input_set(
        self, program: str, workdir: Path, files: Sequence[str] | None = None
    ) -> InputSet:
        """Download every input for ``program``, then recheck each by redownloading.

        Raises ``InputSetError`` after a non-retryable failure or once the bounded
        number of input-set attempts is exhausted.
        """
        names = tuple(files) if files is not None else input_files(program)
        detail = ""
        last_error: SourceError | None = None
        for attempt in range(1, self.config.max_input_set_attempts + 1):
            attempt_dir = workdir / program / f"attempt-{attempt}"
            self._events.record("input_set.attempt", program=program, attempt=attempt)
            try:
                first = [
                    self.download(source_path(program, n), attempt_dir / "read-1" / n)
                    for n in names
                ]
                second = [
                    self.download(source_path(program, n), attempt_dir / "read-2" / n)
                    for n in names
                ]
            except SourceError as exc:
                shutil.rmtree(attempt_dir, ignore_errors=True)
                self._events.record(
                    "input_set.failed_attempt", program=program, attempt=attempt,
                    url=exc.url, reason=exc.reason, status=exc.status,
                )  # fmt: skip
                last_error, detail = exc, str(exc)
                delay = self._retry_delay(attempt, exc) if exc.retryable else None
                if delay is None:
                    raise InputSetError(program, attempt, "source_error", detail, exc) from exc
                self._sleep(delay)
                continue

            shutil.rmtree(attempt_dir / "read-2", ignore_errors=True)
            second = [replace(r, path=None) for r in second]
            changed = [a.url for a, b in zip(first, second, strict=True) if a.sha256 != b.sha256]
            if changed:
                shutil.rmtree(attempt_dir, ignore_errors=True)
                self._events.record(
                    "input_set.changed", program=program, attempt=attempt, urls=changed
                )
                last_error, detail = None, f"changed during build: {', '.join(changed)}"
                self._sleep(self._retry_delay(attempt))
                continue

            self._events.record(
                "input_set.verified", program=program, attempt=attempt,
                files={r.url: r.sha256 for r in first},
            )  # fmt: skip
            return InputSet(program, tuple(first), tuple(second), attempt)

        reason = "source_error" if last_error is not None else "changed_during_build"
        self._events.record(
            "input_set.failed", program=program,
            attempts=self.config.max_input_set_attempts, reason=reason,
        )  # fmt: skip
        raise InputSetError(
            program, self.config.max_input_set_attempts, reason, detail, last_error
        )

    def fetch_programs(
        self, programs: Sequence[str], workdir: Path
    ) -> dict[str, InputSet | InputSetError]:
        """Fetch each program's input set with at most ``max_concurrency`` in flight."""

        def one(program: str) -> InputSet | InputSetError:
            try:
                return self.fetch_input_set(program, workdir)
            except InputSetError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
            return dict(zip(programs, pool.map(one, programs), strict=True))


def _parse_retry_after(value: str | None, now: datetime) -> float | None:
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
    return max(0.0, (when - now).total_seconds())
