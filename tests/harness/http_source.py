"""Controlled HTTP source serving scripted BLS-like responses.

Each path has a script: a list of ``Reply`` objects consumed one per request, with the
last one repeating. Replies can set status, body, delays (for timeouts), truncation, or
an immediate connection close. Every request is recorded with its method and headers.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass(frozen=True)
class Reply:
    status: int = 200
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    delay: float = 0.0  # seconds before sending headers
    truncate_at: int | None = None  # send Content-Length of full body, then close early
    close_without_response: bool = False
    chunked: bool = False  # Transfer-Encoding: chunked, no Content-Length (as BLS serves .series)


@dataclass(frozen=True)
class SeenRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    arrived: float  # time.monotonic() when the server received the request


class ControlledHttpSource:
    def __init__(self) -> None:
        self._scripts: dict[str, list[Reply]] = {}
        self._lock = threading.Lock()
        self.requests: list[SeenRequest] = []
        self.in_flight = 0
        self.max_in_flight = 0
        harness = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                harness._handle(self)

            def do_HEAD(self) -> None:
                harness._handle(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/pub/time.series/"

    def start(self) -> ControlledHttpSource:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- scripting -----------------------------------------------------------------

    def script(self, rel_path: str, *replies: Reply) -> None:
        with self._lock:
            self._scripts["/pub/time.series/" + rel_path] = list(replies)

    def serve_tree(self, root: Path) -> dict[str, bytes]:
        """Serve every file under ``root`` (``<program>/<file>``) with a 200 reply."""
        served = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            served[rel] = path.read_bytes()
            self.script(rel, Reply(body=served[rel]))
        return served

    def requests_for(self, rel_path: str) -> list[SeenRequest]:
        target = "/pub/time.series/" + rel_path
        return [r for r in self.requests if r.path == target]

    # -- serving -------------------------------------------------------------------

    def _next_reply(self, path: str) -> Reply | None:
        with self._lock:
            script = self._scripts.get(path)
            if not script:
                return None
            return script.pop(0) if len(script) > 1 else script[0]

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            self.requests.append(
                SeenRequest(
                    handler.command, handler.path, dict(handler.headers.items()), time.monotonic()
                )
            )
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            reply = self._next_reply(handler.path) or Reply(status=404, body=b"Not Found")
            if reply.delay:
                time.sleep(reply.delay)
            if reply.close_without_response:
                _hard_close(handler)
                return
            handler.send_response(reply.status)
            for name, value in reply.headers.items():
                handler.send_header(name, value)
            if reply.chunked:
                handler.send_header("Transfer-Encoding", "chunked")
            else:
                handler.send_header("Content-Length", str(len(reply.body)))
            handler.end_headers()
            if handler.command == "HEAD":
                return
            if reply.chunked:
                _write_chunked(handler, reply.body, reply.truncate_at)
                return
            if reply.truncate_at is not None:
                handler.wfile.write(reply.body[: reply.truncate_at])
                handler.wfile.flush()
                _hard_close(handler)
                return
            handler.wfile.write(reply.body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up (e.g. on a timeout)
        finally:
            with self._lock:
                self.in_flight -= 1


def _write_chunked(
    handler: BaseHTTPRequestHandler, body: bytes, truncate_at: int | None, size: int = 64
) -> None:
    """Send ``body`` in chunks; when truncating, stop mid-stream without the final
    zero-length chunk and close the connection."""
    end = len(body) if truncate_at is None else truncate_at
    for start in range(0, end, size):
        piece = body[start : min(start + size, end)]
        handler.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
    if truncate_at is None:
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()
    else:
        _hard_close(handler)


def _hard_close(handler: BaseHTTPRequestHandler) -> None:
    handler.close_connection = True
    try:
        handler.wfile.flush()
        handler.connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
