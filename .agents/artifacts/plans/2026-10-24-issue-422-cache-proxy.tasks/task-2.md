# Task 2: Spike gate ruling and the `cache-proxy` command

Step 0 appends the owner's gate ruling to the spike report (spec § Spike, per D21, D22 and D23). Steps 1–6 then add, per spec § The `cache-proxy` command, § Forwarding contract and § Test seams and D5, D6, D7, D8, D15 and D16, a new standard-library module `agent_tools.cache_proxy`, one command-table row, its tests in `just agent-workflow-tests`, and its `python/README.md` section.

**Files:**
- Modify: `docs/spikes/cache-proxy-spike.md` (Step 0 only: one appended section)
- Create: `python/agent_tools/cache_proxy.py`
- Create: `tests/test_cache_proxy.py`
- Modify: `lib/agent-tools.nix` (add `"cache-proxy"` to `commands`, between `"agent-model-matrix"` and `"conformance"`)
- Modify: `justfile` (`agent-workflow-tests`: add the line `    tests/test_cache_proxy.py \` directly above `    tests/test_branch_protection.py`)
- Modify: `python/README.md` (new section after `## \`orchestrate-control\``)

**Interfaces:**
- Consumes (Task 1, committed at `d6b19390`): the spike report's recorded lines `Fact 1: holds` and `Fact 2: holds`. Steps 1–6 consume nothing from earlier tasks.
- Produces (Step 0; read by Task 5, acceptance row `AC1` and the controller): the report's last section `## Gate ruling — 2026-10-25` holding the line `Gate ruling: go` alone on its line.
- Produces (Task 3 imports the first four; Task 4 runs the launcher):
  - `HEALTH_PATH = "/_proxy/health"`, `HEALTH_BODY = b'{"service":"cache-proxy","status":"ok"}'`
  - `parse_upstream(url: str) -> Upstream` — `Upstream(url, scheme, host, port, host_header)`, frozen dataclass; `url` is the argument without a trailing `/`; `host_header` omits the scheme's default port; anything but an `http`/`https` origin without path or query raises `argparse.ArgumentTypeError`.
  - `LineLog(stream)` with `write(event: str, **fields) -> None`: one line `{"event": …, "ts": <UTC ISO-8601, milliseconds>, **fields}` (compact JSON), written and flushed under a lock.
  - `ProxyServer(port: int, upstream: Upstream, log: LineLog)` — a `socketserver.ThreadingTCPServer` bound to `("127.0.0.1", port)`; `serve_forever()`, `shutdown()`, `server_close()`, `server_address`.
  - `build_parser()`, `main(argv: list[str] | None = None) -> int`; the launcher `~/.agents/bin/cache-proxy` and store path `<hash>-agent-tools-cache-proxy`.

**Invariants:**
- Step 0 only appends: the report as committed at `d6b19390` stays a byte-identical prefix of the file, so its `Fact 4: fails` and `Verdict: no-go` lines stay as recorded (D22).
- Bind host is `127.0.0.1` and no argument changes it; `--port` is required (exit 2 without it); nothing runs at import time.
- Upstream request = client method, path with query and body bytes verbatim; headers in client order with duplicates, `Host` rewritten in place (prepended if absent), hop-by-hop (`connection`, `keep-alive`, `te`, `trailer`, `transfer-encoding`, `upgrade`, every `proxy-*`, every name a `Connection` header lists) dropped, nothing added (`putrequest(..., skip_host=True, skip_accept_encoding=True)`).
- Client response = upstream status and reason, end-to-end headers in upstream order with duplicates, no `Server`/`Date` (use `send_response_only`, never `send_response`/`send_error`); a sized body keeps its `Content-Length`; an unsized body drops any `Content-Length`, gets `Transfer-Encoding: chunked` after the forwarded headers, and is written one chunk per upstream `read1(65536)`, flushed each time.
- Pre-response upstream failure → `502` with `{"type":"error","error":{"type":"api_error","message":"cache-proxy: …"}}`; never a retry. Mid-body upstream failure (an exception, or a sized body ending short) → client connection closed without the terminating chunk. Client hang-up → upstream connection closed.
- One upstream connection per client connection, reused only when the last response was read to the end, its socket is still open and `select` finds it not readable.
- `GET /_proxy/health` → `200`, `Content-Type: application/json`, `HEALTH_BODY`; any other method → `405`, `Allow: GET`, empty body; neither is forwarded or logged (D16).
- One `request` log line per forwarded or rejected request with `method`, `path`, `status`, `upstream_conn` (`new`, `reused`, or `null` when rejected), `ttfb_ms`, `duration_ms`, `bytes` (body bytes written to the client, de-chunked), `outcome` (`complete`, `client_closed`, `upstream_error`, `rejected`), plus `error` on `upstream_error` and `error_body` (first 4096 bytes, UTF-8 with replacement) when the upstream status is ≥ 400. No header value and no other body bytes are logged.

- [ ] **Step 0: Record the owner's gate ruling in the spike report (D21, D22, D23)**

The report `docs/spikes/cache-proxy-spike.md` records `Verdict: no-go` under the original gate, which needed facts 1, 2 and 4. The owner ruled fact 4 inconclusive and the gate go on facts 1 and 2. This step appends that ruling as the report's last section and changes nothing above it.

Confirm the starting state (timeout 30 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-spike.md
grep -qx 'Fact 1: holds' "$f"
grep -qx 'Fact 2: holds' "$f"
if grep -q '^Gate ruling:' "$f"; then exit 1; fi
echo ruling-absent
```

Expected: `ruling-absent`. If either fact line is missing, report BLOCKED with `spike gate: facts 1 and 2 do not both hold`; the amended gate (D21) is then not met, and nothing else in this plan runs.

Append the following to the end of the file. The file already ends in a newline, so first add one blank line, then this text, and end with a newline:

```markdown
## Gate ruling — 2026-10-25

Gate ruling: go

This section was appended after the run. Everything above it is the 2026-10-24 run as recorded, and it is not edited. The recorded `Verdict: no-go` applied the original gate, under which facts 1, 2 and 4 all had to hold. On 2026-10-25 the issue owner ruled fact 4 inconclusive, not failed (https://github.com/fagenorn/nix-config/issues/422#issuecomment-6394974531). It failed only the structural rule, because the two siblings' `system` blocks differ in the billing header's `cc_version` suffix. Its token threshold was met, the breakpoint was never moved, and the attachment set was 862 tokens. The amended gate is facts 1 and 2, and both hold above, so the gate is go and the pass-through service proceeds (D21, D22). The shared sibling start-up prefix, including a proper re-test of fact 4, moves to https://github.com/fagenorn/nix-config/issues/429. Fact 3 does not gate: it is measured on the shipped proxy, as § Fact 3 says. A routed session loses Remote Control (§ Fact 1), a consequence the owner accepted.
```

Verify (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-spike.md
n=$(git show d6b19390:"$f" | wc -l)
head -n "$n" "$f" | cmp -s - <(git show d6b19390:"$f")
test "$(grep -c '^Gate ruling: ' "$f")" -eq 1
grep -qx 'Gate ruling: go' "$f"
test "$(grep '^## ' "$f" | tail -1)" = '## Gate ruling — 2026-10-25'
for key in 'Fact 1: holds' 'Fact 2: holds' 'Fact 4: fails' 'Verdict: no-go'; do grep -qx "$key" "$f"; done
grep -qF 'issues/422#issuecomment-6394974531' "$f"
grep -qF 'issues/429' "$f"
test -z "$(tail -c 1 "$f" | tr -d '\n')"
if grep -nE 'sk-ant-|Bearer |oat01' "$f"; then exit 1; fi
echo ruling-recorded
```

Expected: `ruling-recorded`. At the starting commit it fails at the `Gate ruling:` count (0). Then commit:

```bash
git add docs/spikes/cache-proxy-spike.md
git commit -m "docs(spike): record the owner's go ruling on the spike gate (#422)"
```

- [ ] **Step 1: Write the failing tests** — `tests/test_cache_proxy.py`:

```python
"""`cache-proxy` forwards requests and streamed responses unchanged (#422).

The forwarding cases run the real server in-process on port 0 against `FakeUpstream`, a
loopback HTTP/1.1 server that records each raw request per upstream connection and runs the
case's scripted responder; `CommandTest` runs `python -m agent_tools.cache_proxy`.
"""

import http.client
import json
import select
import socket
import socketserver
import subprocess
import sys
import threading
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
        # Added at Phase-5 review (S3); the implementer writes the body: the responder
        # sends SSE_HEAD and EVENTS[0] as one chunk, then keeps sending one chunk every
        # 50 ms for at most 3 s while sendall succeeds; the client reads the status and
        # the first event, then closes its socket. Exactly one log record follows, with
        # outcome "client_closed" (never overwritten by "upstream_error").
        ...

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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py`
Expected: FAIL — `ImportError: cannot import name 'cache_proxy' from 'agent_tools'`.

- [ ] **Step 3: Write `python/agent_tools/cache_proxy.py`**

Module docstring (verbatim): `"""\`cache-proxy\`: a loopback pass-through from Claude Code to the Anthropic API (#422).` followed by a paragraph stating that `cache-proxy --port N [--upstream URL]` binds 127.0.0.1 only and serves until killed, forwards requests and responses unchanged apart from `Host` and hop-by-hop headers, answers `GET /_proxy/health` itself, and writes one JSON line per forwarded request to stderr.

Constants: `HOST = "127.0.0.1"`, `DEFAULT_UPSTREAM = "https://api.anthropic.com"`, `HEALTH_PATH`, `HEALTH_BODY`, `UPSTREAM_TIMEOUT = 600.0`, `IDLE_TIMEOUT = 600.0` (Claude Code's default request timeout), `BACKLOG = 64`, `READ_SIZE = 65536`, `ERROR_BODY_LIMIT = 4096`, `HOP_BY_HOP = frozenset({"connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade"})`.

- `port_number(text) -> int` (0–65535, else `ArgumentTypeError`); `parse_upstream` per Interfaces (wrap `urlsplit(...).port`'s `ValueError`).
- `dropped_names(message) -> set[str]`: `HOP_BY_HOP` plus every comma-separated token of every `Connection` value, lowercased; a name is also dropped when it starts with `proxy-`. Used for the client request (`self.headers`) and the upstream response (`response.msg`), both `http.client.HTTPMessage`.
- `envelope(kind, message) -> bytes`: compact JSON `{"type":"error","error":{"type":kind,"message":"cache-proxy: " + message}}`.
- `ProxyServer(socketserver.ThreadingTCPServer)`: `daemon_threads = True`, `allow_reuse_address = True`, `request_queue_size = BACKLOG`; `__init__(port, upstream, log)` stores both, sets `self.tls = ssl.create_default_context()` for an `https` upstream (once per server, not per connection) else `None`, then `super().__init__((HOST, port), ProxyHandler)`. Not `http.server.HTTPServer`, whose `server_bind` does a reverse lookup.
- `ProxyHandler(http.server.BaseHTTPRequestHandler)`: `protocol_version = "HTTP/1.1"`, `timeout = IDLE_TIMEOUT` (the idle client connection close); `log_message` silenced (the JSON lines are the log); `setup` adds `_upstream_conn = None`, `_reusable = False`; `finish` closes the upstream connection first; `do_GET`, `do_POST`, `do_PUT`, `do_PATCH`, `do_DELETE`, `do_HEAD`, `do_OPTIONS` all call `_handle`.

`_handle` algorithm, in order:
1. `started = time.monotonic()`.
2. Body: any `Transfer-Encoding` header → reject `411` "chunked request bodies are not supported". The set of stripped `Content-Length` values: empty → body `b""`; more than one distinct value, or one that is not `isascii() and isdigit()` → reject `400` "invalid Content-Length"; else `rfile.read(n)`, and a short read sets `close_connection` and returns. A reject sends the `invalid_request_error` envelope with `Content-Type: application/json` and `Content-Length`, sets `close_connection`, and logs `rejected` with `upstream_conn: null`.
3. `urlsplit(self.path).path == HEALTH_PATH` → answer per Invariants (body read already, so the connection stays in sync) and return without logging.
4. Upstream headers: client headers in order; the first `host` header keeps its name and position with the value `upstream.host_header`, any later one is dropped; dropped names removed; `Host` prepended if none came.
5. Connection: `label = "reused"` when `_upstream_conn` is not `None`, `_reusable`, `_upstream_conn.sock is not None` and `select.select([sock], [], [], 0)[0]` is empty; otherwise close any old one, `label = "new"`, build `HTTPSConnection(host, port, timeout=UPSTREAM_TIMEOUT, context=server.tls)` or `HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT)` and `connect()`. Set `_reusable = False`.
6. `putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)`, one `putheader` per header, `endheaders(body or None)`, `getresponse()`. Any `OSError`, `http.client.HTTPException` or `ValueError` from step 5 or 6 → close the upstream connection, send `502` with `envelope("api_error", f"upstream request failed: {type(e).__name__}: {e}")`, log `upstream_error` with `error = f"{type(e).__name__}: {e}"`, return. `ttfb_ms` = milliseconds from `started` to `getresponse()` returning.
7. Response: `bodiless = command == "HEAD" or 100 <= status < 200 or status in (204, 304)`; `sized = bodiless or (not response.chunked and response.length is not None)`; `declared = response.length` when sized and not bodiless. Forwarded headers = `response.getheaders()` minus dropped names, minus `content-length` when not sized. Write `send_response_only(status, response.reason)`, each header via `send_header`, then `Transfer-Encoding: chunked` when not sized, `end_headers()`.
8. Body: bodiless → `response.read()` (closes it; nothing written). Otherwise loop `chunk = response.read1(READ_SIZE)`: an exception → outcome `upstream_error` (with `error`); `b""` → end; capture up to `ERROR_BODY_LIMIT` bytes when `status >= 400`; write `chunk` (sized) or `b"%x\r\n%s\r\n" % (len(chunk), chunk)` and flush — an `OSError` → outcome `client_closed`; count bytes. After the loop a sized body with `bytes != declared` is `upstream_error` (`error` names both counts). On `complete` and not sized write `b"0\r\n\r\n"`. Every write to the client — step 7's status line and headers, each body chunk and the terminating chunk — is under the same `OSError` handling, which sets outcome `client_closed` and still reaches step 9's cleanup and log line; the sized short-body check runs only while the outcome is still `complete`, so it never overwrites `client_closed` (Phase-5 review S3).
9. `complete` → `_reusable = True`; any other outcome → close the upstream connection and set `close_connection`. Log the line.

A planning dry run of this algorithm (before the S3 refinement) passed the original 11 tests on darwin.

- `main`: `build_parser()` is `argparse.ArgumentParser(prog="cache-proxy", description=<docstring's first line>)` with `--port` (`type=port_number`, required) and `--upstream` (`type=parse_upstream`, default `DEFAULT_UPSTREAM`). `log = LineLog(sys.stderr)`. A bind `OSError` → `log.write("bind_failed", host=HOST, port=args.port, error="<Class>: <message>")`, return 1. Otherwise `with server:` write `listening` (`host`, `port` from `server_address`, `upstream=args.upstream.url`) and `serve_forever()`, treating `KeyboardInterrupt` as a clean stop; return 0. `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 4: Wire the command and its docs**

Add `"cache-proxy"` to `commands` in `lib/agent-tools.nix` and the test file to the `agent-workflow-tests` recipe (see Files). Add to `python/README.md`, after the `orchestrate-control` section:

```markdown
## `cache-proxy`

`cache-proxy --port N [--upstream URL]` (#422) is a loopback pass-through from Claude Code to the Anthropic API: it binds `127.0.0.1` only, forwards each request's method, path, query and body bytes and each response's status, headers and body unchanged (only `Host` is rewritten and hop-by-hop headers are dropped; nothing is added, decoded or retried), re-chunks an unsized (streamed) response one upstream read at a time, and holds one keep-alive upstream connection per client connection. `GET /_proxy/health` answers `{"service":"cache-proxy","status":"ok"}` without being forwarded or logged. An upstream that fails before responding gets the client a `502` Anthropic error envelope; one that fails mid-body gets the client connection closed without the terminating chunk. stderr carries one JSON line per request (`method`, `path`, `status`, `upstream_conn`, `ttfb_ms`, `duration_ms`, `bytes`, `outcome`, plus `error` and up to 4 KiB of an upstream error body), never a header value. The service that runs it and the `claude` wrapper that routes through it are in `home/common/claude-code/README.md`.
```

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py`
Expected: PASS, 12 tests.

First stage the new files — a Git-backed flake build omits untracked files, and `lib/agent-tools.nix` asserts every command row has a discoverable module (Phase-5 review B2): `git add python/agent_tools/cache_proxy.py tests/test_cache_proxy.py lib/agent-tools.nix justfile python/README.md`. Then run (timeout 3600 s): `just build`, then (timeout 60 s):

```bash
set -euo pipefail
set -- $(nix-store --query --requisites ./result | grep -- '-agent-tools-cache-proxy$' || true)
test "$#" -eq 1
"$1" --help | head -1 | grep -q '^usage: cache-proxy '
grep -q 'tests/test_cache_proxy.py \\' justfile
echo launcher-ok
```

Expected: `launcher-ok`. Then the installed-layout check over every launcher, this one included (timeout 600 s): `set -- $(nix-store --query --requisites ./result | grep -- '-home-manager-files$'); test "$#" -eq 1 && AGENT_SKILLS_INSTALLED_HOME="$1" python3 -m unittest -v tests/test_agent_tools_launchers.py -k test_a_hostile_agent_tools_on_every_channel_is_ignored` — expected `OK`. At the starting commit the unittest run fails on the import and the store query finds no launcher.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/cache_proxy.py tests/test_cache_proxy.py lib/agent-tools.nix justfile python/README.md
git commit -m "feat(cache-proxy): loopback pass-through command (#422)"
```
