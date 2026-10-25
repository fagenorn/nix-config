"""`cache-proxy` forwards requests and streamed responses unchanged (#422).

The forwarding cases run the real server in-process on port 0 against `FakeUpstream`, a
loopback HTTP/1.1 server that records each raw request per upstream connection and runs the
case's scripted responder; `CommandTest` runs `python -m agent_tools.cache_proxy`.
"""

import http.client
import json
import contextlib
import select
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import unittest

from agent_tools import cache_proxy

TIMEOUT = 10
SSE_HEAD = (b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"request-id: req_sse\r\nTransfer-Encoding: chunked\r\n\r\n")
EVENTS = (
    b'event: message_start\ndata: {"type":"message_start"}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)
JSON_REPLY = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
CLOSING_REPLY = b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 2\r\n\r\n{}"


def json_reply(sock, head, body):
    sock.sendall(JSON_REPLY)
    return True


def closed_port():
    """A loopback port nothing listens on: bound, then freed. (On darwin a port that is
    bound but not listening drops connections instead of refusing them.)"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_head(reader):
    """The raw request head through its last header line, or None at end of stream."""
    lines = []
    while True:
        line = reader.readline()
        if not line:
            return None
        if line == b"\r\n":
            return b"".join(lines)
        lines.append(line)


def content_length(head):
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            return int(value.strip())
    return 0


class FakeUpstream:
    """Records (connection number, head, body) per request and runs `responder(sock, head, body)`,
    which writes the raw response and returns True to keep the connection for another request."""

    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        self.connections = 0
        self.lock = threading.Lock()
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with fake.lock:
                    fake.connections += 1
                    number = fake.connections
                reader = self.request.makefile("rb")
                while True:
                    head = read_head(reader)
                    if head is None:
                        return
                    length = content_length(head)
                    body = reader.read(length) if length else b""
                    with fake.lock:
                        fake.requests.append((number, head, body))
                    if not fake.responder(self.request, head, body):
                        return

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RecordingStream:
    """The proxy's log stream: whole lines, which a test waits for under a condition."""

    def __init__(self):
        self.lines = []
        self.partial = ""
        self.condition = threading.Condition()

    def write(self, text):
        with self.condition:
            self.partial += text
            *done, self.partial = self.partial.split("\n")
            self.lines.extend(done)
            self.condition.notify_all()
        return len(text)

    def flush(self):
        pass

    def records(self, count):
        with self.condition:
            if not self.condition.wait_for(lambda: len(self.lines) >= count, TIMEOUT):
                raise AssertionError(f"expected {count} log lines, got {self.lines!r}")
            return [json.loads(line) for line in self.lines[:count]]


class ProxyCase(unittest.TestCase):
    def upstream(self, responder):
        fake = FakeUpstream(responder)
        self.addCleanup(fake.close)
        return fake

    def proxy(self, upstream_url):
        stream = RecordingStream()
        server = cache_proxy.ProxyServer(0, cache_proxy.parse_upstream(upstream_url),
                                         cache_proxy.LineLog(stream))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1], stream

    def client(self, port):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT)
        self.addCleanup(connection.close)
        return connection


class ForwardingTest(ProxyCase):
    def test_sse_events_arrive_byte_identical_and_one_at_a_time(self):
        released = [threading.Event() for _ in EVENTS[1:]]

        def responder(sock, head, body):
            sock.sendall(SSE_HEAD)
            for index, event in enumerate(EVENTS):
                if index and not released[index - 1].wait(TIMEOUT):
                    return False
                sock.sendall(b"%x\r\n%s\r\n" % (len(event), event))
            sock.sendall(b"0\r\n\r\n")
            return True

        port, log = self.proxy(self.upstream(responder).url)
        client = self.client(port)
        client.request("POST", "/v1/messages", body=b'{"stream":true}',
                       headers={"Content-Type": "application/json"})
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual([name.lower() for name, _ in response.getheaders()],
                         ["content-type", "request-id", "transfer-encoding"])
        received = b""
        for index in range(len(EVENTS)):
            # Upstream holds the next event until this one has arrived whole, so a
            # buffering proxy times this read out instead of passing.
            expected = b"".join(EVENTS[:index + 1])
            while len(received) < len(expected):
                chunk = response.read1(65536)
                self.assertTrue(chunk, "the stream ended early")
                received += chunk
            self.assertEqual(received, expected)
            if index < len(released):
                released[index].set()
        self.assertEqual(response.read(), b"")
        [record] = log.records(1)
        self.assertEqual((record["event"], record["status"], record["outcome"], record["bytes"]),
                         ("request", 200, "complete", len(b"".join(EVENTS))))

    def test_request_headers_reach_upstream_verbatim_with_only_host_rewritten(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        body = b'{"model":"x"}'
        request = (b"POST /v1/messages?beta=true HTTP/1.1\r\n"
                   b"Host: 127.0.0.1:%d\r\n"
                   b"authorization: Bearer test-token-1\r\n"
                   b"anthropic-beta: first\r\n"
                   b"x-api-key: test-key-1\r\n"
                   b"anthropic-beta: second\r\n"
                   b"Accept-Encoding: gzip, br\r\n"
                   b"Connection: keep-alive, X-Hop\r\n"
                   b"X-Hop: drop-me\r\n"
                   b"Keep-Alive: timeout=5\r\n"
                   b"Proxy-Authorization: Basic drop-me\r\n"
                   b"Content-Type: application/json\r\n"
                   b"Content-Length: %d\r\n\r\n" % (port, len(body))) + body
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(request)
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            self.assertEqual((reply.status, reply.read()), (200, b"{}"))
        [(_, head, received)] = fake.requests
        self.assertEqual(head.split(b"\r\n"), [
            b"POST /v1/messages?beta=true HTTP/1.1",
            b"Host: 127.0.0.1:%d" % fake.server.server_address[1],
            b"authorization: Bearer test-token-1",
            b"anthropic-beta: first",
            b"x-api-key: test-key-1",
            b"anthropic-beta: second",
            b"Accept-Encoding: gzip, br",
            b"Content-Type: application/json",
            b"Content-Length: %d" % len(body),
            b"",
        ])
        self.assertEqual(received, body)
        [record] = log.records(1)
        self.assertNotIn("test-token-1", json.dumps(record))
        self.assertNotIn("test-key-1", json.dumps(record))

    def test_the_health_path_answers_without_reaching_upstream(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        client = self.client(port)
        client.request("GET", "/_proxy/health")
        response = client.getresponse()
        self.assertEqual((response.status, response.getheader("Content-Type"), response.read()),
                         (200, "application/json", b'{"service":"cache-proxy","status":"ok"}'))
        client.request("POST", "/_proxy/health", body=b"{}")
        response = client.getresponse()
        self.assertEqual((response.status, response.getheader("Allow"), response.read()),
                         (405, "GET", b""))
        client.request("GET", "/v1/models")
        response = client.getresponse()
        self.assertEqual((response.status, response.read()), (200, b"{}"))
        self.assertEqual([head.split(b"\r\n")[0] for _, head, _ in fake.requests],
                         [b"GET /v1/models HTTP/1.1"])
        self.assertEqual([record["path"] for record in log.records(1)], ["/v1/models"])

    def test_an_unreachable_upstream_gets_a_502_error_envelope(self):
        port, log = self.proxy("http://127.0.0.1:%d" % closed_port())
        client = self.client(port)
        client.request("POST", "/v1/messages", body=b"{}")
        response = client.getresponse()
        self.assertEqual((response.status, response.getheader("Content-Type")),
                         (502, "application/json"))
        envelope = json.loads(response.read())
        self.assertEqual((envelope["type"], envelope["error"]["type"]), ("error", "api_error"))
        self.assertTrue(envelope["error"]["message"].startswith("cache-proxy: "), envelope)
        [record] = log.records(1)
        self.assertEqual((record["status"], record["outcome"]), (502, "upstream_error"))
        self.assertIn("ConnectionRefusedError", record["error"])
        self.assertEqual(record["bytes"], int(response.getheader("Content-Length")))

    def test_a_failed_head_ends_at_its_headers_and_the_connection_stays_usable(self):
        port, log = self.proxy("http://127.0.0.1:%d" % closed_port())
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            # Raw bytes, so no client buffer can hide body bytes after the HEAD reply.
            sock.sendall(b"HEAD /v1/models HTTP/1.1\r\nHost: x\r\n\r\n"
                         b"GET /_proxy/health HTTP/1.1\r\nHost: x\r\n\r\n")
            received = b""
            while not received.endswith(cache_proxy.HEALTH_BODY):
                chunk = sock.recv(65536)
                self.assertTrue(chunk, f"the connection closed after {received!r}")
                received += chunk
        head, _, rest = received.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 502 "), head)
        self.assertIn(b"Content-Length: ", head)
        self.assertTrue(rest.startswith(b"HTTP/1.1 200 "), rest)
        [record] = log.records(1)
        self.assertEqual((record["method"], record["status"], record["bytes"]), ("HEAD", 502, 0))

    def test_an_upstream_reset_mid_stream_leaves_the_body_unterminated(self):
        def responder(sock, head, body):
            sock.sendall(SSE_HEAD + b"%x\r\n%s\r\n" % (len(EVENTS[0]), EVENTS[0]) + b"40\r\npartial")
            sock.shutdown(socket.SHUT_RDWR)
            return False

        port, log = self.proxy(self.upstream(responder).url)
        client = self.client(port)
        client.request("POST", "/v1/messages", body=b"{}")
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        with self.assertRaises(http.client.IncompleteRead):
            response.read()
        [record] = log.records(1)
        self.assertEqual(record["outcome"], "upstream_error")

    def test_a_client_that_disconnects_mid_stream_is_logged_client_closed(self):
        finished = threading.Event()

        def responder(sock, head, body):
            try:
                sock.sendall(SSE_HEAD + b"%x\r\n%s\r\n" % (len(EVENTS[0]), EVENTS[0]))
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    sock.sendall(b"%x\r\n%s\r\n" % (len(EVENTS[1]), EVENTS[1]))
            except OSError:
                pass  # the proxy closed its upstream connection: the hang-up arrived
            finally:
                finished.set()
            return False

        port, log = self.proxy(self.upstream(responder).url)
        client = self.client(port)
        client.request("POST", "/v1/messages", body=b"{}")
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        received = b""
        while len(received) < len(EVENTS[0]):
            chunk = response.read1(65536)
            self.assertTrue(chunk, "the stream ended early")
            received += chunk
        self.assertTrue(received.startswith(EVENTS[0]))
        client.close()
        self.assertTrue(finished.wait(TIMEOUT), "the upstream connection was never closed")
        [record] = log.records(1)
        self.assertEqual(record["outcome"], "client_closed")
        self.assertEqual(len(log.lines), 1)

    def test_a_second_request_on_one_client_connection_reuses_the_upstream_connection(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        client = self.client(port)
        for _ in range(2):
            client.request("POST", "/v1/messages", body=b"{}")
            response = client.getresponse()
            self.assertEqual((response.status, response.read()), (200, b"{}"))
        self.assertEqual([number for number, _, _ in fake.requests], [1, 1])
        self.assertEqual([record["upstream_conn"] for record in log.records(2)], ["new", "reused"])

    def test_an_upstream_connection_the_upstream_closed_is_not_reused(self):
        def responder(sock, head, body):
            sock.sendall(CLOSING_REPLY)
            return False

        fake = self.upstream(responder)
        port, log = self.proxy(fake.url)
        client = self.client(port)
        for _ in range(2):
            client.request("POST", "/v1/messages", body=b"{}")
            response = client.getresponse()
            self.assertEqual((response.status, response.getheader("Connection"), response.read()),
                             (200, None, b"{}"))
        self.assertEqual([number for number, _, _ in fake.requests], [1, 2])
        self.assertEqual([record["upstream_conn"] for record in log.records(2)], ["new", "new"])

    def test_a_chunked_request_body_is_rejected_with_411(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            # The head alone: a body the proxy never reads would turn its close into a reset.
            sock.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            envelope = json.loads(reply.read())
        self.assertEqual((reply.status, envelope["error"]["type"]), (411, "invalid_request_error"))
        self.assertEqual(fake.requests, [])
        [record] = log.records(1)
        self.assertEqual((record["outcome"], record["upstream_conn"]), ("rejected", None))


    def test_a_client_reset_leaves_only_json_lines_and_the_server_keeps_serving(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        traceback_text = RecordingStream()
        with contextlib.redirect_stderr(traceback_text):
            self.reset_after(port, b"POST /v1/messages HTTP/1.1\r\nHost: x\r\n"
                                   b"Content-Length: 100\r\n\r\n0123456789")
            with traceback_text.condition:
                traceback_text.condition.wait_for(lambda: traceback_text.lines, 0.5)
        self.assertEqual((traceback_text.lines, traceback_text.partial), ([], ""))
        client = self.client(port)
        client.request("GET", "/_proxy/health")
        self.assertEqual(client.getresponse().status, 200)
        self.assertEqual(fake.requests, [])
        self.assertEqual([json.loads(line)["event"] for line in log.lines], [])

    def test_a_client_reset_on_an_idle_connection_is_one_handler_error_line(self):
        port, log = self.proxy(self.upstream(json_reply).url)
        self.reset_after(port, b"")
        [record] = log.records(1)
        self.assertEqual(record["event"], "handler_error")
        self.assertTrue(record["error"].startswith("ConnectionResetError: "), record)

    @staticmethod
    def reset_after(port, data):
        """Send `data`, then close with a RST instead of a FIN."""
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            if data:
                sock.sendall(data)
                time.sleep(0.1)  # let the proxy block in the body read before the reset


class CommandTest(unittest.TestCase):
    def run_command(self, *args):
        return subprocess.run([sys.executable, "-m", "agent_tools.cache_proxy", *args],
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)

    def start(self, *args):
        process = subprocess.Popen([sys.executable, "-m", "agent_tools.cache_proxy", *args],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(process.stderr.close)
        self.addCleanup(process.wait, TIMEOUT)
        self.addCleanup(process.terminate)
        return process

    @staticmethod
    def read_record(stream):
        ready, _, _ = select.select([stream], [], [], TIMEOUT)
        if not ready:
            raise AssertionError("no log line within the timeout")
        return json.loads(stream.readline())

    def test_help_prints_usage_and_a_missing_port_exits_2(self):
        completed = self.run_command("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: cache-proxy "), completed.stdout)
        completed = self.run_command()
        self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        self.assertIn("--port", completed.stderr)

    def test_the_command_serves_one_round_trip(self):
        fake = FakeUpstream(json_reply)
        self.addCleanup(fake.close)
        process = self.start("--port", "0", "--upstream", fake.url)
        listening = self.read_record(process.stderr)
        self.assertEqual({key: listening[key] for key in ("event", "host", "upstream")},
                         {"event": "listening", "host": "127.0.0.1", "upstream": fake.url})
        connection = http.client.HTTPConnection("127.0.0.1", listening["port"], timeout=TIMEOUT)
        self.addCleanup(connection.close)
        connection.request("POST", "/v1/messages", body=b"{}")
        response = connection.getresponse()
        self.assertEqual((response.status, response.read()), (200, b"{}"))
        record = self.read_record(process.stderr)
        self.assertEqual((record["event"], record["method"], record["path"], record["outcome"]),
                         ("request", "POST", "/v1/messages", "complete"))

    def test_a_port_in_use_exits_1_with_a_bind_failed_line(self):
        with socket.socket() as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen()
            process = self.start("--port", str(holder.getsockname()[1]))
            self.assertEqual(process.wait(TIMEOUT), 1)
            record = self.read_record(process.stderr)
        self.assertEqual(record["event"], "bind_failed")
        self.assertIn("error", record)


if __name__ == "__main__":
    unittest.main()
