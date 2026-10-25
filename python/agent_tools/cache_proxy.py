"""`cache-proxy`: a loopback pass-through from Claude Code to the Anthropic API (#422).

`cache-proxy --port N [--upstream URL]` binds 127.0.0.1 only and serves until killed. It
forwards requests and responses unchanged apart from `Host` and hop-by-hop headers, answers
`GET /_proxy/health` itself, and writes one JSON line per forwarded request to stderr.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import http.server
import json
import select
import socketserver
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

HOST = "127.0.0.1"
DEFAULT_UPSTREAM = "https://api.anthropic.com"
HEALTH_PATH = "/_proxy/health"
HEALTH_BODY = b'{"service":"cache-proxy","status":"ok"}'
UPSTREAM_TIMEOUT = 600.0
IDLE_TIMEOUT = 600.0  # Claude Code's default request timeout
BACKLOG = 64
READ_SIZE = 65536
ERROR_BODY_LIMIT = 4096
HOP_BY_HOP = frozenset({"connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade"})
DEFAULT_PORTS = {"http": 80, "https": 443}
UPSTREAM_FAILURES = (OSError, http.client.HTTPException, ValueError)


@dataclass(frozen=True)
class Upstream:
    url: str
    scheme: str
    host: str
    port: int
    host_header: str


def port_number(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port number (0-65535)")
    return port


def parse_upstream(url: str) -> Upstream:
    """The upstream origin: an http or https URL with a host and nothing after the port."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{url!r} is not a valid URL: {error}") from error
    if (parts.scheme not in DEFAULT_PORTS or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in ("", "/") or parts.query
            or parts.fragment):
        raise argparse.ArgumentTypeError(
            f"{url!r} is not an http or https origin without a path or query")
    default_port = DEFAULT_PORTS[parts.scheme]
    host_text = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    shown = host_text if port in (None, default_port) else f"{host_text}:{port}"
    return Upstream(url.removesuffix("/"), parts.scheme, parts.hostname,
                    default_port if port is None else port, shown)


def dropped_names(message: http.client.HTTPMessage) -> set[str]:
    """Header names a proxy must not forward: hop-by-hop, `proxy-*` and any `Connection` lists."""
    names = set(HOP_BY_HOP)
    for value in message.get_all("Connection", []):
        names.update(token.strip().lower() for token in value.split(",") if token.strip())
    names.update(name.lower() for name in message.keys() if name.lower().startswith("proxy-"))
    return names


def envelope(kind: str, message: str) -> bytes:
    body = {"type": "error", "error": {"type": kind, "message": "cache-proxy: " + message}}
    return json.dumps(body, separators=(",", ":")).encode()


def elapsed_ms(since: float) -> float:
    return round((time.monotonic() - since) * 1000, 1)


class LineLog:
    """One compact JSON object per line, written and flushed whole under a lock."""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def write(self, event: str, **fields) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        line = json.dumps({"event": event, "ts": stamp, **fields}, separators=(",", ":"))
        with self.lock:
            self.stream.write(line + "\n")
            self.stream.flush()


@dataclass
class Relay:
    """How one response body travelled: the outcome, bytes written to the client and any error."""

    outcome: str = "complete"
    error: str | None = None
    written: int = 0
    error_body: bytes = b""


class ProxyServer(socketserver.ThreadingTCPServer):
    # Not http.server.HTTPServer, whose server_bind does a reverse lookup.
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = BACKLOG

    def __init__(self, port: int, upstream: Upstream, log: LineLog):
        self.upstream = upstream
        self.log = log
        self.tls = ssl.create_default_context() if upstream.scheme == "https" else None
        super().__init__((HOST, port), ProxyHandler)

    def handle_error(self, request, client_address):
        """An exception no handler step expected (for one, a client reset on an idle
        connection): one structured line, never the traceback socketserver prints."""
        error = sys.exc_info()[1]
        self.log.write("handler_error", error=f"{type(error).__name__}: {error}")


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = IDLE_TIMEOUT

    def log_message(self, format, *args):
        """Silenced: the JSON lines are the log."""

    def setup(self):
        super().setup()
        self._upstream_conn = None
        self._reusable = False

    def finish(self):
        self._close_upstream()
        super().finish()

    def _close_upstream(self):
        if self._upstream_conn is not None:
            self._upstream_conn.close()
            self._upstream_conn = None

    def _can_reuse(self):
        conn = self._upstream_conn
        if conn is None or not self._reusable or conn.sock is None:
            return False
        return not select.select([conn.sock], [], [], 0)[0]

    def _connect_upstream(self):
        self._close_upstream()
        upstream = self.server.upstream
        if upstream.scheme == "https":
            conn = http.client.HTTPSConnection(upstream.host, upstream.port,
                                               timeout=UPSTREAM_TIMEOUT, context=self.server.tls)
        else:
            conn = http.client.HTTPConnection(upstream.host, upstream.port, timeout=UPSTREAM_TIMEOUT)
        self._upstream_conn = conn
        conn.connect()

    def _answer(self, status, body, headers=()):
        """Write a response this proxy makes itself; a vanished client only closes the connection."""
        try:
            self.send_response_only(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _log_request(self, started, status, label, ttfb_ms, relay):
        fields = {"method": self.command, "path": self.path, "status": status,
                  "upstream_conn": label, "ttfb_ms": ttfb_ms, "duration_ms": elapsed_ms(started),
                  "bytes": relay.written, "outcome": relay.outcome}
        if relay.error is not None:
            fields["error"] = relay.error
        if relay.error_body:
            fields["error_body"] = relay.error_body.decode("utf-8", "replace")
        self.server.log.write("request", **fields)

    def _reject(self, started, status, kind, message):
        body = envelope(kind, message)
        self._answer(status, body, [("Content-Type", "application/json")])
        self.close_connection = True
        self._log_request(started, status, None, None, Relay("rejected", written=len(body)))

    def _read_body(self, started):
        """The request body, or None when the request was rejected or the client left."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._reject(started, 411, "invalid_request_error",
                         "chunked request bodies are not supported")
            return None
        lengths = {value.strip() for value in self.headers.get_all("Content-Length", [])}
        if not lengths:
            return b""
        text = next(iter(lengths))
        if len(lengths) > 1 or not (text.isascii() and text.isdigit()):
            self._reject(started, 400, "invalid_request_error", "invalid Content-Length")
            return None
        try:
            body = self.rfile.read(int(text))
        except OSError:
            body = b""
        if len(body) < int(text):
            self.close_connection = True
            return None
        return body

    def _upstream_headers(self):
        dropped = dropped_names(self.headers)
        headers, host_seen = [], False
        for name, value in self.headers.items():
            if name.lower() == "host":
                if not host_seen:
                    headers.append((name, self.server.upstream.host_header))
                host_seen = True
            elif name.lower() not in dropped:
                headers.append((name, value))
        if not host_seen:
            headers.insert(0, ("Host", self.server.upstream.host_header))
        return headers

    def _send_request(self, body):
        conn = self._upstream_conn
        conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
        for name, value in self._upstream_headers():
            conn.putheader(name, value)
        conn.endheaders(body or None)
        return conn.getresponse()

    def _handle(self):
        started = time.monotonic()
        body = self._read_body(started)
        if body is None:
            return
        if urlsplit(self.path).path == HEALTH_PATH:
            if self.command == "GET":
                self._answer(200, HEALTH_BODY, [("Content-Type", "application/json")])
            else:
                self._answer(405, b"", [("Allow", "GET")])
            return
        label = "reused" if self._can_reuse() else "new"
        self._reusable = False
        try:
            if label == "new":
                self._connect_upstream()
            response = self._send_request(body)
        except UPSTREAM_FAILURES as error:
            self._close_upstream()
            detail = f"{type(error).__name__}: {error}"
            self._answer(502, envelope("api_error", f"upstream request failed: {detail}"),
                         [("Content-Type", "application/json")])
            self._log_request(started, 502, label, None, Relay("upstream_error", detail))
            return
        ttfb_ms = elapsed_ms(started)
        relay = self._relay(response)
        if relay.outcome == "complete":
            self._reusable = True
        else:
            self._close_upstream()
            self.close_connection = True
        self._log_request(started, response.status, label, ttfb_ms, relay)

    def _relay(self, response):
        """Copy the upstream response to the client, one upstream read per client chunk."""
        bodiless = (self.command == "HEAD" or 100 <= response.status < 200
                    or response.status in (204, 304))
        sized = bodiless or (not response.chunked and response.length is not None)
        declared = None if bodiless or not sized else response.length
        dropped = dropped_names(response.msg)
        relay = Relay()
        try:
            self.send_response_only(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in dropped and (sized or name.lower() != "content-length"):
                    self.send_header(name, value)
            if not sized:
                self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.flush()
        except OSError:
            relay.outcome = "client_closed"
            return relay
        if bodiless:
            self._drain_bodiless(response, relay)
            return relay
        self._copy_body(response, sized, relay)
        if relay.outcome == "complete" and declared is not None and relay.written != declared:
            relay.outcome = "upstream_error"
            relay.error = f"body ended after {relay.written} of {declared} bytes"
        if relay.outcome == "complete" and not sized:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                relay.outcome = "client_closed"
        return relay

    @staticmethod
    def _drain_bodiless(response, relay):
        try:
            response.read()
        except UPSTREAM_FAILURES as error:
            relay.outcome, relay.error = "upstream_error", f"{type(error).__name__}: {error}"

    def _copy_body(self, response, sized, relay):
        while True:
            try:
                chunk = response.read1(READ_SIZE)
            except UPSTREAM_FAILURES as error:
                relay.outcome, relay.error = "upstream_error", f"{type(error).__name__}: {error}"
                return
            if not chunk:
                return
            if response.status >= 400 and len(relay.error_body) < ERROR_BODY_LIMIT:
                relay.error_body += chunk[:ERROR_BODY_LIMIT - len(relay.error_body)]
            try:
                self.wfile.write(chunk if sized else b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            except OSError:
                relay.outcome = "client_closed"
                return
            relay.written += len(chunk)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cache-proxy", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=port_number, required=True,
                        help="loopback port to listen on (0 picks a free one)")
    parser.add_argument("--upstream", type=parse_upstream, default=DEFAULT_UPSTREAM,
                        help="origin to forward to (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = LineLog(sys.stderr)
    try:
        server = ProxyServer(args.port, args.upstream, log)
    except OSError as error:
        log.write("bind_failed", host=HOST, port=args.port, error=f"{type(error).__name__}: {error}")
        return 1
    with server:
        log.write("listening", host=HOST, port=server.server_address[1], upstream=args.upstream.url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
