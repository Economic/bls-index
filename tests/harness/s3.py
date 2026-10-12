"""Local S3-compatible store (moto server) behind a fault-injecting HTTP proxy.

The production ``S3ObjectStore`` talks to the proxy. The proxy forwards to moto unless a
rule matches, in which case it can return an error status, drop the connection before
or after forwarding (the latter commits a write but loses its response), corrupt or
truncate a response body, or delay. A separate "backdoor" client talks to moto directly
to inspect true stored state and to plant corrupt objects.
"""

from __future__ import annotations

import http.client
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

import boto3
from moto.server import ThreadedMotoServer

DROP_BEFORE = "drop_before"
DROP_AFTER = "drop_after"
CORRUPT_BODY = "corrupt_body"
TRUNCATE_BODY = "truncate_body"
STATUS = "status"
DELAY = "delay"


@dataclass
class FaultRule:
    method: str
    key_contains: str
    action: str
    status: int = 500
    code: str = "InternalError"
    seconds: float = 0.0
    times: int | None = 1  # None = every matching request

    def matches(self, method: str, path: str) -> bool:
        return method == self.method and self.key_contains in path


@dataclass(frozen=True)
class ProxiedRequest:
    method: str
    path: str
    headers: dict[str, str]
    fault: str | None


def start_moto() -> tuple[ThreadedMotoServer, str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    return server, f"http://{host}:{port}"


def backdoor_client(endpoint_url: str) -> Any:
    return boto3.client(
        "s3", endpoint_url=endpoint_url, aws_access_key_id="testing",
        aws_secret_access_key="testing", region_name="us-east-1",
    )  # fmt: skip


class FaultProxy:
    def __init__(self, upstream: str) -> None:
        parts = urlsplit(upstream)
        self._upstream = (parts.hostname, parts.port)
        self._lock = threading.Lock()
        self.rules: list[FaultRule] = []
        self.requests: list[ProxiedRequest] = []
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                proxy._handle(self)

            do_HEAD = do_PUT = do_POST = do_DELETE = do_GET

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def add(self, rule: FaultRule) -> FaultRule:
        with self._lock:
            self.rules.append(rule)
        return rule

    def reset(self) -> None:
        with self._lock:
            self.rules.clear()
            self.requests.clear()

    def requests_matching(self, method: str, key_contains: str) -> list[ProxiedRequest]:
        return [r for r in self.requests if r.method == method and key_contains in r.path]

    def _take_rule(self, method: str, path: str) -> FaultRule | None:
        with self._lock:
            for rule in self.rules:
                if rule.matches(method, path) and (rule.times is None or rule.times > 0):
                    if rule.times is not None:
                        rule.times -= 1
                    return rule
        return None

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        length = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(length) if length else b""
        path = unquote(h.path)
        rule = self._take_rule(h.command, path)
        with self._lock:
            self.requests.append(
                ProxiedRequest(h.command, path, dict(h.headers.items()), rule and rule.action)
            )
        try:
            if rule and rule.action == DELAY:
                time.sleep(rule.seconds)
            if rule and rule.action == DROP_BEFORE:
                _hard_close(h)
                return
            if rule and rule.action == STATUS:
                _send(h, rule.status, _error_xml(rule.code), {"Content-Type": "application/xml"})
                return
            status, headers, resp_body = self._forward(h, body)
            if rule and rule.action == DROP_AFTER:
                _hard_close(h)
                return
            if rule and rule.action == CORRUPT_BODY and resp_body:
                resp_body = bytes([resp_body[0] ^ 0xFF]) + resp_body[1:]
            if rule and rule.action == TRUNCATE_BODY:
                _send(h, status, resp_body, headers, send_only=len(resp_body) // 2)
                _hard_close(h)
                return
            _send(h, status, resp_body, headers)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _forward(
        self, h: BaseHTTPRequestHandler, body: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection(*self._upstream, timeout=30)
        skip = {"host", "expect", "connection", "content-length"}
        headers = {k: v for k, v in h.headers.items() if k.lower() not in skip}
        headers["Content-Length"] = str(len(body))
        conn.request(h.command, h.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        out = {
            k: v for k, v in resp.getheaders()
            if k.lower() not in {"content-length", "transfer-encoding", "connection"}
        }  # fmt: skip
        if h.command == "HEAD":
            out["Content-Length"] = resp.getheader("Content-Length", "0")
        conn.close()
        return resp.status, out, data


def _send(
    h: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    headers: dict[str, str],
    *,
    send_only: int | None = None,
) -> None:
    h.send_response(status)
    for name, value in headers.items():
        h.send_header(name, value)
    if h.command != "HEAD":
        h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    if h.command == "HEAD":
        return
    h.wfile.write(body if send_only is None else body[:send_only])
    h.wfile.flush()


def _hard_close(h: BaseHTTPRequestHandler) -> None:
    h.close_connection = True
    try:
        h.connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _error_xml(code: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Error><Code>{code}</Code><Message>injected {code}</Message></Error>"
    ).encode()
