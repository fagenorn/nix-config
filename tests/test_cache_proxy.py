"""`cache-proxy` forwards requests and streamed responses (#422); `--reorder` reshapes subagent first messages (#429).

The forwarding cases run the real server in-process on port 0 against `FakeUpstream`, a
loopback HTTP/1.1 server that records each raw request per upstream connection and runs the
case's scripted responder; `CommandTest` runs `python -m agent_tools.cache_proxy`.
`SubagentPrefixTest` calls `agent_tools.subagent_prefix` directly on the sanitised re-test captures in `tests/fixtures/cache_proxy/`.
"""

import copy
import http.client
import json
import contextlib
import re
import select
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from agent_tools import cache_proxy
from agent_tools import subagent_prefix

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
FIXTURES = Path(__file__).parent / "fixtures" / "cache_proxy"
MESSAGES = "/v1/messages?beta=true"
RANK = {"5m": 0, "1h": 1}
BUDGET = "<total_tokens>48213 tokens left</total_tokens>"
BUDGET_LINE = re.compile(r"<total_tokens>(?:[0-9]+|Infinite) tokens left</total_tokens>")


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def fixture(name):
    return json.loads(fixture_bytes(name))


def agent(agent_id=None, length=0):
    """Upstream headers as the proxy assembles them, with `agent_id` as the subagent header."""
    headers = [("Host", "api.anthropic.com"), ("content-type", "application/json")]
    if agent_id is not None:
        headers.append(("x-claude-code-agent-id", agent_id))
    return headers + [("Content-Length", str(length))]


def encode(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def holders(value):
    """The test's own oracle: every object whose cache_control is a breakpoint, in prefix order."""
    found = [tool for tool in value.get("tools", []) if isinstance(tool, dict)]
    if isinstance(value.get("system"), list):
        found += [block for block in value["system"] if isinstance(block, dict)]
    for message in value.get("messages", []):
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            inner = block.get("content")
            found += [item for item in inner if isinstance(item, dict)] if isinstance(inner, list) else []
            found.append(block)
    found.append(value)
    return found


def marks(value):
    return [holder["cache_control"] for holder in holders(value) if "cache_control" in holder]


def unmarked(value):
    value = copy.deepcopy(value)
    for holder in holders(value):
        holder.pop("cache_control", None)
    return value


def kind(block):
    text = block["text"]
    if text.startswith("<system-reminder>"):
        return "attachment"
    return "budget" if BUDGET_LINE.fullmatch(text) else "prompt"


def prompt_index(content):
    [index] = [i for i, block in enumerate(content) if kind(block) == "prompt"]
    return index


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


class SubagentPrefixTest(unittest.TestCase):
    """The transform on the re-test's sanitised captures (D19) and variants derived from them."""

    PAIRS = (("sibling1-first", "agent-1"), ("sibling2-first", "agent-2"),
             ("sibling1-second", "agent-1"))
    HOUR = {"type": "ephemeral", "ttl": "1h"}

    def run_transform(self, transform, source, agent_id="agent-1", path=MESSAGES, method="POST"):
        """(body, headers, result): what was passed and the transform's (body, headers, outcome)."""
        body = fixture_bytes(source) if isinstance(source, str) else encode(source)
        headers = agent(agent_id, len(body))
        return body, headers, transform.transform(method, path, headers, body)

    def assert_unchanged(self, body, headers, result, outcome):
        self.assertEqual(result[2], outcome)
        self.assertIs(result[0], body)
        self.assertIs(result[1], headers)

    def first(self):
        """Sibling 1's first request with every mark removed: the base of the variants."""
        return unmarked(fixture("sibling1-first.received.json"))

    def variant(self, places=(), top=None):
        """`first()` with marks at "tool0", "tool1", "system-1" (the last system block) or
        "tail" (the last block of messages[0]), and `top` as a top-level cache_control."""
        value = self.first()
        for where, mark in places:
            if where.startswith("tool"):
                value["tools"][int(where[4:])]["cache_control"] = mark
            elif where == "system-1":
                value["system"][-1]["cache_control"] = mark
            else:
                value["messages"][0]["content"][-1]["cache_control"] = mark
        if top is not None:
            value["cache_control"] = top
        return value

    def with_budget(self, offset):
        """`first()` with a budget line inserted at the prompt's index plus `offset`."""
        value = self.first()
        content = value["messages"][0]["content"]
        content.insert(prompt_index(content) + offset, {"type": "text", "text": BUDGET})
        return value

    def applied(self, value, expected="applied"):
        """A fresh transform's parsed output, and the mark on the block before its prompt."""
        _, _, (forwarded, _, outcome) = self.run_transform(subagent_prefix.SubagentPrefix(), value)
        self.assertEqual(outcome, expected)
        output = json.loads(forwarded)
        content = output["messages"][0]["content"]
        return output, content[prompt_index(content) - 1].get("cache_control")

    def test_fixture_pairs_transform_received_into_forwarded(self):
        transform = subagent_prefix.SubagentPrefix()
        for name, agent_id in self.PAIRS:
            with self.subTest(name=name):
                _, headers, (forwarded, sent, outcome) = self.run_transform(
                    transform, f"{name}.received.json", agent_id)
                self.assertIn(outcome, subagent_prefix.REWRITTEN)
                self.assertEqual(json.loads(forwarded), fixture(f"{name}.forwarded.json"))
                self.assertEqual(forwarded, encode(json.loads(forwarded)))
                self.assertEqual(sent, [(header, str(len(forwarded)) if header == "Content-Length"
                                         else value) for header, value in headers])

    def test_applied_outputs_add_one_mark_and_keep_ttls_non_increasing(self):
        transform = subagent_prefix.SubagentPrefix()
        for name, agent_id in self.PAIRS:
            with self.subTest(name=name):
                body, _, (forwarded, _, outcome) = self.run_transform(
                    transform, f"{name}.received.json", agent_id)
                before, after = marks(json.loads(body)), marks(json.loads(forwarded))
                self.assertEqual(len(after), len(before) + (outcome == "applied"))
                self.assertLessEqual(len(after), 4)
                ranks = [RANK[mark.get("ttl", "5m")] for mark in after]
                self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_sibling_outputs_agree_through_the_block_before_the_prompt(self):
        transform = subagent_prefix.SubagentPrefix()
        one, two = (json.loads(self.run_transform(transform, f"sibling{k}-first.received.json",
                                                  f"agent-{k}")[2][0]) for k in (1, 2))
        self.assertEqual(one["tools"], two["tools"])
        self.assertEqual(one["system"][1:], two["system"][1:])
        first, second = one["messages"][0]["content"], two["messages"][0]["content"]
        index = prompt_index(first)
        self.assertEqual(prompt_index(second), index)
        self.assertEqual(first[:index], second[:index])
        self.assertNotEqual(first[index], second[index])

    def test_a_later_turn_keeps_the_first_requests_reordered_first_message(self):
        transform = subagent_prefix.SubagentPrefix()
        first = json.loads(self.run_transform(transform, "sibling1-first.received.json")[2][0])
        _, _, (forwarded, _, outcome) = self.run_transform(transform,
                                                           "sibling1-second.received.json")
        self.assertIn(outcome, subagent_prefix.REWRITTEN)
        self.assertEqual(unmarked({"messages": [json.loads(forwarded)["messages"][0]]}),
                         unmarked({"messages": [first["messages"][0]]}))

    def test_a_later_turn_on_a_fresh_transform_is_unregistered_and_unchanged(self):
        self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(),
                                                  "sibling1-second.received.json"), "unregistered")

    def test_a_fork_shaped_request_is_unregistered_and_unchanged(self):
        transform = subagent_prefix.SubagentPrefix()
        self.run_transform(transform, "sibling1-first.received.json")
        self.assert_unchanged(*self.run_transform(transform, "sibling1-second.received.json",
                                                  "agent-fork"), "unregistered")

    def test_the_registry_evicts_its_oldest_id_past_capacity(self):
        transform = subagent_prefix.SubagentPrefix(capacity=2)
        for agent_id in ("agent-a", "agent-b", "agent-c"):
            self.assertIn(self.run_transform(transform, "sibling1-first.received.json",
                                             agent_id)[2][2], subagent_prefix.REWRITTEN)
        self.assertEqual(self.run_transform(transform, "sibling1-second.received.json",
                                            "agent-a")[2][2], "unregistered")
        for agent_id in ("agent-b", "agent-c"):
            self.assertIn(self.run_transform(transform, "sibling1-second.received.json",
                                             agent_id)[2][2], subagent_prefix.REWRITTEN)

    def test_blocks_before_the_prompt_and_attachments_after_it_keep_their_order(self):
        value = self.variant()
        content = value["messages"][0]["content"]
        index = prompt_index(content)
        later = content[index + 1:]
        expected = (content[:index] + [b for b in later if kind(b) == "attachment"]
                    + [content[index]] + [b for b in later if kind(b) == "budget"])
        output, _ = self.applied(value)
        self.assertEqual([b["text"] for b in output["messages"][0]["content"]],
                         [b["text"] for b in expected])
        self.assertEqual({k: v for k, v in output.items() if k != "messages"},
                         {k: v for k, v in value.items() if k != "messages"})
        self.assertEqual(output["messages"][1:], value["messages"][1:])

    def test_the_tail_mark_stays_on_the_last_block(self):
        tail = {"type": "ephemeral", "ttl": "5m"}
        output, mark = self.applied(self.variant([("tail", tail)]))
        content = output["messages"][0]["content"]
        self.assertEqual(content[-1]["cache_control"], tail)
        self.assertEqual([i for i, b in enumerate(content) if "cache_control" in b],
                         [prompt_index(content) - 1, len(content) - 1])
        self.assertEqual(mark, tail)

    def test_a_1h_system_mark_and_a_5m_tail_give_a_5m_mark(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR),
                                             ("tail", {"type": "ephemeral", "ttl": "5m"})]))
        self.assertEqual(mark, {"type": "ephemeral", "ttl": "5m"})

    def test_all_1h_marks_give_a_1h_mark(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR), ("tail", self.HOUR)]))
        self.assertEqual(mark, self.HOUR)

    def test_with_no_mark_after_it_the_new_mark_takes_the_preceding_ttl(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR)]))
        self.assertEqual(mark, self.HOUR)

    def test_with_no_marks_the_new_mark_has_no_ttl(self):
        output, mark = self.applied(self.variant())
        self.assertEqual(mark, {"type": "ephemeral"})
        self.assertEqual(marks(output), [{"type": "ephemeral"}])

    def test_four_marks_reorder_at_the_cap_with_marks_unchanged(self):
        value = self.variant([("tool0", self.HOUR), ("tool1", self.HOUR),
                              ("system-1", self.HOUR), ("tail", {"type": "ephemeral"})])
        output, mark = self.applied(value, "applied_at_cap")
        self.assertIsNone(mark)
        self.assertEqual(marks(output), marks(value))
        self.assertNotEqual(kind(output["messages"][0]["content"][-1]), "attachment")

    def test_a_top_level_cache_control_takes_a_slot_and_comes_last(self):
        self.applied(self.variant([("tool0", self.HOUR), ("system-1", self.HOUR),
                                   ("tail", {"type": "ephemeral"})], top={"type": "ephemeral"}),
                     "applied_at_cap")
        _, mark = self.applied(self.variant([("system-1", self.HOUR)], top={"type": "ephemeral"}))
        self.assertEqual(mark, {"type": "ephemeral"})

    def with_inner(self, value, mark):
        """`value` plus a later user message whose tool_result holds `mark` in its inner content."""
        value["messages"].append({"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "toolu_inner",
            "content": [{"type": "text", "text": "inner", "cache_control": mark}]}]})
        return value

    def test_an_inner_content_mark_takes_a_slot(self):
        places = [("tool0", self.HOUR), ("tool1", self.HOUR), ("system-1", self.HOUR)]
        self.applied(self.variant(places))
        value = self.with_inner(self.variant(places), {"type": "ephemeral"})
        output, mark = self.applied(value, "applied_at_cap")
        self.assertIsNone(mark)
        self.assertEqual(marks(output), marks(value))

    def test_an_inner_content_mark_sets_the_ttl_and_its_order(self):
        _, mark = self.applied(self.with_inner(self.variant([("system-1", self.HOUR)]),
                                               {"type": "ephemeral", "ttl": "5m"}))
        self.assertEqual(mark, {"type": "ephemeral", "ttl": "5m"})
        value = self.with_inner(self.variant([("system-1", {"type": "ephemeral", "ttl": "5m"})]),
                                dict(self.HOUR))
        self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(), value),
                              "shape")

    def test_a_budget_line_after_the_prompt_stays_after_it(self):
        output, mark = self.applied(self.with_budget(1))
        content = output["messages"][0]["content"]
        self.assertEqual(content[-1], {"type": "text", "text": BUDGET})
        self.assertEqual(prompt_index(content), len(content) - 2)
        self.assertEqual(mark, {"type": "ephemeral"})

    def test_a_budget_line_before_the_prompt_keeps_its_place(self):
        value = self.with_budget(0)
        index = prompt_index(value["messages"][0]["content"])
        output, _ = self.applied(value)
        self.assertEqual(output["messages"][0]["content"][index - 1]["text"], BUDGET)

    def test_unexpected_shapes_pass_through_as_shape(self):
        def prompt_first(value):
            content = value["messages"][0]["content"]
            content.insert(0, content.pop(prompt_index(content)))

        def two_prompts(value):
            value["messages"][0]["content"].append({"type": "text", "text": "a second prompt"})

        def budget_with_text(value):
            value["messages"][0]["content"].append({"type": "text", "text": BUDGET + "\nand a note"})

        def non_text_block(value):
            value["messages"][0]["content"][0] = {
                "type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ""}}

        def middle_mark(value):
            value["messages"][0]["content"][0]["cache_control"] = {"type": "ephemeral"}

        def five_marks(value):
            for tool in value["tools"][:4]:
                tool["cache_control"] = dict(self.HOUR)
            value["messages"][0]["content"][-1]["cache_control"] = {"type": "ephemeral"}

        def unknown_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "2h"}

        def unhashable_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": ["1h"]}

        def rising_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "5m"}
            value["messages"][0]["content"][-1]["cache_control"] = dict(self.HOUR)

        def mark_not_an_object(value):
            value["system"][-1]["cache_control"] = "ephemeral"

        self.assertGreaterEqual(len(self.first()["tools"]), 4)
        for change in (prompt_first, two_prompts, budget_with_text, non_text_block, middle_mark,
                       five_marks, unknown_ttl, unhashable_ttl, rising_ttl, mark_not_an_object):
            with self.subTest(change=change.__name__):
                value = self.first()
                change(value)
                self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(), value),
                                      "shape")

    def test_unparseable_bodies_pass_through_as_unparsed(self):
        for body in (b'{"a":1,"a":2}', b'{"system":NaN}', b"[]", b'{"system":"\\ud800"}',
                     b"\xff", b"", b"[" * 100000 + b"]" * 100000):
            with self.subTest(body=body[:20]):
                headers = agent("agent-1", len(body))
                self.assert_unchanged(body, headers, subagent_prefix.SubagentPrefix().transform(
                    "POST", MESSAGES, headers, body), "unparsed")

    def test_requests_other_than_subagent_messages_are_never_rewritten(self):
        sibling = fixture_bytes("sibling1-first.received.json")
        parent = fixture_bytes("parent-first.json")
        main = fixture("sibling1-first.received.json")
        prefix = "x-anthropic-billing-header:"
        fields = main["system"][0]["text"][len(prefix):].split(";")
        self.assertIn("cc_is_subagent=true", [field.strip() for field in fields])
        main["system"][0]["text"] = prefix + ";".join(
            field for field in fields if field.strip() != "cc_is_subagent=true")
        cases = (("POST", MESSAGES, None, sibling), ("POST", MESSAGES, "", sibling),
                 ("GET", MESSAGES, "agent-1", sibling),
                 ("POST", "/v1/messages/count_tokens?beta=true", "agent-1", sibling),
                 ("POST", MESSAGES, "agent-1", encode(main)),
                 ("POST", MESSAGES, "agent-1", parent), ("POST", MESSAGES, None, parent))
        for method, path, agent_id, body in cases:
            with self.subTest(method=method, path=path, agent_id=agent_id):
                headers = agent(agent_id, len(body))
                self.assert_unchanged(body, headers, subagent_prefix.SubagentPrefix().transform(
                    method, path, headers, body), "not_subagent")


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
