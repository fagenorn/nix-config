# Task 3: `cache-proxy --keepalive`: the seam, the service flag and the docs

Spec § Interface and seam (per-request seam, failure posture, switch), § Response tap, § Log contract and § Docs, per D2, D3, D9, D11, D18, D19 and D24. `cache-proxy` gains `--keepalive`. With the flag, `ProxyServer` holds a `Keepalive` (Task 2): the handler calls `observe` on the headers and body it is about to forward, sends the headers the track gives, and then calls the track's `started`, `chunk` and `done`. Both hosts' services pass the flag, and the two READMEs describe it. Without the flag, behaviour and log lines are #422's, byte for byte.

**Files:**
- Modify: `python/agent_tools/cache_proxy.py`
- Modify: `tests/test_cache_keepalive.py` (new imports, the classes `KeepaliveProxyTest` and `KeepaliveCommandTest`)
- Modify: `home/common/claude-code/default.nix` (`cacheProxyArgs`, the comment above it, the systemd `Unit.Description`)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy), `python/README.md` (§ `cache-proxy`)

**Interfaces:**
- Consumes (Task 2): `cache_keepalive.Keepalive(log, connect, clock)` and its `observe`, `tick`, `send` and `run`, plus the `Track` methods `started(status, content_type, content_encoding)`, `chunk(data)`, `done(outcome)` and `log_fields()`, and the attribute `headers`. Also the test helpers `MESSAGES`, `SESSION`, `AGENT_P`, `AGENT_Q`, `document`, `encode`, `forwarded`, `sse`, `SSE_HEAD`, `chunked`, `sse_reply` and `FakeClock`, and from `tests.test_cache_proxy` the names `TIMEOUT`, `FakeUpstream`, `RecordingStream` and `json_reply`.
- Produces: `cache_proxy.upstream_tls(upstream: Upstream) -> ssl.SSLContext | None`, `cache_proxy.open_upstream(upstream: Upstream, tls, timeout: float) -> http.client.HTTPConnection` (unconnected), and `ProxyServer(port, upstream, log, keepalive=None)`. The command is `cache-proxy --port N [--upstream URL] [--keepalive]`. The built launchd agents' `ProgramArguments` end `"--port", "27183", "--keepalive"`, and the systemd `ExecStart` ends `--port 27183 --keepalive`; Tasks 4 and 5 read both.

**Invariants:**
- With `keepalive=None`, every byte sent upstream and every log line is as before this task. The existing `tests/test_cache_proxy.py` cases pass unchanged, and that file is not edited (D25).
- The health path is answered, and a request rejected while its body is read (`411`, `400`) is logged, before `observe` runs. Their lines carry no `keepalive` field.
- With a keepalive, every request that reaches `observe` gets a `request` line carrying `track.log_fields()`. When `observe`, a track call or `log_fields` raised, the line carries `"keepalive":"untracked"` alone. Each such exception is written first as one `keepalive_error` line with `stage` (`observe` or `track`) and `error` = `"<class>: <message>"`. A track that raised is dropped, so no further call reaches it, and the request continues as an untracked one would (D18, D24).
- A request that has a track calls `done` exactly once on each path: `done("upstream_error")` when the upstream fails before a response, and otherwise `done(relay.outcome)` after the relay (`client_closed` included).
- `chunk` is called with each response chunk after that chunk has been written to the client, so the bytes the client gets are unchanged (D9).
- Only `main` starts `Keepalive.run`, on a daemon thread, after the `listening` line; a `stop` event is set when serving ends. The port `27183` still appears exactly once in `default.nix`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cache_keepalive.py`, add `import functools`, `import select`, `import socket`, `import subprocess` and `import sys` to the imports, and add `json_reply` to the `tests.test_cache_proxy` import. Then add at the end, before the `__main__` guard:

```python
class KeepaliveProxyTest(unittest.TestCase):
    """`ProxyServer` with a keepalive in front of `FakeUpstream` (D2, D9, D18, D24)."""

    def setUp(self):
        self.clock = FakeClock()
        self.stream = RecordingStream()
        self.log = cache_proxy.LineLog(self.stream)

    def start(self, responder, keepalive=None):
        fake = FakeUpstream(responder)
        self.addCleanup(fake.close)
        upstream = cache_proxy.parse_upstream(fake.url)
        if keepalive is None:
            keepalive = cache_keepalive.Keepalive(
                self.log, functools.partial(cache_proxy.open_upstream, upstream, None), self.clock)
        server = cache_proxy.ProxyServer(0, upstream, self.log, keepalive=keepalive)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return fake, server.server_address[1], keepalive

    def send(self, port, agent, raw):
        """One raw POST on a new client connection; returns (socket, status, body)."""
        headers = [(name, "127.0.0.1:%d" % port if name == "Host" else value)
                   for name, value in forwarded(agent, length=len(raw))]
        sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        self.addCleanup(sock.close)
        sock.sendall(b"POST %s HTTP/1.1\r\n" % MESSAGES.encode()
                     + b"".join(("%s: %s\r\n" % pair).encode() for pair in headers) + b"\r\n" + raw)
        reply = http.client.HTTPResponse(sock)
        reply.begin()
        return sock, reply.status, reply.read()

    def test_a_ping_reaches_upstream_on_its_own_connection_and_no_byte_reaches_the_client(self):
        fake, port, keepalive = self.start(sse_reply("tool_use"))
        value = document()
        raw = encode(value)
        sock, status, body = self.send(port, AGENT_P, raw)
        self.assertEqual((status, body), (200, sse("tool_use")))
        [(number, head, received)] = fake.requests
        self.assertEqual(received, raw)
        host = "127.0.0.1:%d" % fake.server.server_address[1]
        expected = [(name, host if name == "Host" else "identity" if name == "Accept-Encoding"
                     else header) for name, header in forwarded(AGENT_P, length=len(raw))]
        self.assertEqual(head.split(b"\r\n"), [b"POST %s HTTP/1.1" % MESSAGES.encode()]
                         + [("%s: %s" % pair).encode() for pair in expected] + [b""])
        [record] = self.stream.records(1)
        self.assertEqual(
            {key: record[key] for key in ("keepalive", "conversation", "stop_reason", "outcome")},
            {"keepalive": "tracked", "conversation": cache_keepalive.conversation_handle(SESSION, AGENT_P),
             "stop_reason": "tool_use", "outcome": "complete"})
        self.clock.advance(270)
        [ping] = keepalive.tick()
        keepalive.send(ping)
        self.assertEqual([entry[0] for entry in fake.requests], [number, number + 1])
        self.assertEqual(json.loads(fake.requests[1][2]), dict(value, max_tokens=1))
        self.assertEqual(select.select([sock], [], [], 0.3)[0], [])

    def test_a_keepalive_whose_observe_raises_forwards_unchanged_and_logs_one_error(self):
        class Raising:
            def observe(self, method, path, headers, body):
                raise KeyError("boom")

        fake, port, _ = self.start(json_reply, Raising())
        raw = encode(document())
        _, status, body = self.send(port, AGENT_P, raw)
        self.assertEqual((status, body), (200, b"{}"))
        [(_, head, received)] = fake.requests
        self.assertIn(b"Accept-Encoding: gzip, deflate, br, zstd", head.split(b"\r\n"))
        self.assertEqual(received, raw)
        error, request = self.stream.records(2)
        self.assertEqual((error["event"], error["stage"], error["error"]),
                         ("keepalive_error", "observe", "KeyError: 'boom'"))
        self.assertEqual((request["event"], request["keepalive"]), ("request", "untracked"))
        self.assertNotIn("conversation", request)

    def test_a_track_that_raises_is_dropped_and_the_response_still_arrives_whole(self):
        log = self.log

        class Track:
            outcome, conversation, stop_reason = "tracked", "0123456789ab", None

            def __init__(self, headers):
                self.headers = headers

            def started(self, status, content_type, content_encoding):
                pass

            def chunk(self, data):
                raise ValueError("tap")

            def done(self, outcome):
                log.write("unexpected_done")

            def log_fields(self):
                return {"keepalive": "tracked"}

        class Tapping:
            def observe(self, method, path, headers, body):
                return Track(headers)

        _, port, _ = self.start(sse_reply(), Tapping())
        _, status, body = self.send(port, AGENT_P, encode(document()))
        self.assertEqual((status, body), (200, sse("end_turn")))
        error, request = self.stream.records(2)
        self.assertEqual((error["event"], error["stage"], error["error"]),
                         ("keepalive_error", "track", "ValueError: tap"))
        self.assertEqual((request["event"], request["keepalive"]), ("request", "untracked"))
        self.assertEqual(len(self.stream.lines), 2)

    def test_a_request_rejected_before_its_body_is_read_has_no_keepalive_field(self):
        _, port, _ = self.start(json_reply)
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            reply.read()
        self.assertEqual(reply.status, 411)
        [record] = self.stream.records(1)
        self.assertEqual(record["outcome"], "rejected")
        self.assertNotIn("keepalive", record)

    def test_an_upstream_failure_ends_the_request_flight(self):
        def responder(sock, head, body):
            if b"x-claude-code-agent-id: " + AGENT_Q.encode() in head:
                return False  # closed without a response: the proxy answers 502
            sock.sendall(SSE_HEAD + chunked(sse("end_turn")))
            return True

        _, port, keepalive = self.start(responder)
        self.assertEqual(self.send(port, AGENT_Q, encode(document(note="q")))[1], 502)
        self.assertEqual(self.send(port, AGENT_P, encode(document()))[1], 200)
        self.stream.records(2)
        self.clock.advance(270)
        self.assertEqual(keepalive.tick(), [])
        ends = [json.loads(line) for line in self.stream.lines if '"keepalive_end"' in line]
        self.assertEqual([(end["conversation"], end["reason"]) for end in ends],
                         [(cache_keepalive.conversation_handle(SESSION, AGENT_P), "session_idle")])


class KeepaliveCommandTest(unittest.TestCase):
    def start(self, *args):
        fake = FakeUpstream(json_reply)
        self.addCleanup(fake.close)
        process = subprocess.Popen([sys.executable, "-m", "agent_tools.cache_proxy", "--port", "0",
                                    "--upstream", fake.url, *args],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(process.stderr.close)
        self.addCleanup(process.wait, TIMEOUT)
        self.addCleanup(process.terminate)
        return process

    @staticmethod
    def record(process):
        ready, _, _ = select.select([process.stderr], [], [], TIMEOUT)
        if not ready:
            raise AssertionError("no log line within the timeout")
        return json.loads(process.stderr.readline())

    def round_trip(self, process):
        listening = self.record(process)
        connection = http.client.HTTPConnection("127.0.0.1", listening["port"], timeout=TIMEOUT)
        self.addCleanup(connection.close)
        connection.request("POST", "/v1/messages", body=b"{}")
        self.assertEqual(connection.getresponse().read(), b"{}")
        return listening, self.record(process)

    def test_help_lists_the_keepalive_flag(self):
        completed = subprocess.run([sys.executable, "-m", "agent_tools.cache_proxy", "--help"],
                                   capture_output=True, text=True, timeout=TIMEOUT, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--keepalive", completed.stdout)

    def test_the_flag_marks_the_listening_line_and_each_request_line(self):
        listening, request = self.round_trip(self.start("--keepalive"))
        self.assertEqual((listening["event"], listening["keepalive"]), ("listening", True))
        self.assertEqual((request["event"], request["keepalive"]), ("request", "untracked"))

    def test_without_the_flag_no_line_carries_keepalive(self):
        listening, request = self.round_trip(self.start())
        self.assertEqual((listening["event"], request["event"]), ("listening", "request"))
        self.assertNotIn("keepalive", listening)
        self.assertNotIn("keepalive", request)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py`
Expected: the 35 earlier tests pass. The `KeepaliveProxyTest` cases error (`AttributeError` for `open_upstream`, or a `TypeError` for the `keepalive` keyword), and the `--keepalive` command cases fail.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/cache_proxy.py`:
- Docstring: the synopsis becomes `cache-proxy --port N [--upstream URL] [--keepalive]`. Add one sentence: with `--keepalive` it also replays idle subagent conversations' last requests with `max_tokens=1` (`agent_tools.cache_keepalive`, #423), and its forwarding changes only as described there.
- New module functions: `upstream_tls(upstream)` returns `ssl.create_default_context()` for `https` and `None` otherwise. `open_upstream(upstream, tls, timeout)` returns an unconnected `HTTPSConnection(host, port, timeout=timeout, context=tls)` or `HTTPConnection(host, port, timeout=timeout)`. `ProxyServer.__init__(self, port, upstream, log, keepalive=None)` stores `self.keepalive` and sets `self.tls = upstream_tls(upstream)`. `ProxyHandler._connect_upstream` opens through `open_upstream(self.server.upstream, self.server.tls, UPSTREAM_TIMEOUT)`, then calls `connect()` as before.
- `ProxyHandler.setup` also sets `self._track = None` and `self._observed = False`, and `_handle` resets both at its start. After the health check, `_handle` computes `headers = self._upstream_headers()`, then `self._observe(headers, body)`, and sends `self._track.headers` when a track is held, else `headers`. `_send_request(self, headers, body)` takes the header list instead of building it.
- `_observe` does nothing without `self.server.keepalive`. Otherwise it sets `self._observed = True` and calls `observe(self.command, self.path, headers, body)`, writing an exception as `keepalive_error` with `stage` `observe`.
- `_track_call(self, name, *args)` calls the held track's method and, on an exception, writes `keepalive_error` with `stage` `track` and drops the track. `_handle` calls `started(response.status, response.getheader("Content-Type"), response.getheader("Content-Encoding"))` after `getresponse`, and `done` on each path (Invariants). `_copy_body` calls `chunk(chunk)` after a successful client write.
- `_log_request` adds, when `self._observed`, the held track's `log_fields()` (guarded like a track call), or `{"keepalive": "untracked"}`.
- `build_parser` adds `--keepalive` (`action="store_true"`), with help text naming the `max_tokens=1` replays of idle subagent conversations (#423).
- `main`: with `--keepalive`, `from agent_tools import cache_keepalive` (inside `main`, with a one-line comment that `cache_keepalive` imports this module's transport constants, D24). It then builds `cache_keepalive.Keepalive(log, functools.partial(open_upstream, args.upstream, upstream_tls(args.upstream)), time.monotonic)` and passes it as `keepalive=`. The `listening` line gains `keepalive=True` only then. After that line, a daemon thread runs `keepalive.run(stop)`, and `stop.set()` runs in a `finally` around `serve_forever`.

`home/common/claude-code/default.nix`: `cacheProxyArgs` becomes the launcher, `"--port"`, `(toString cacheProxyPort)`, `"--keepalive"`. The comment above it gains one line saying that `--keepalive` (#423) turns on the keepalive pings, and that dropping it and rebuilding turns them off. The systemd `Unit.Description` becomes `"Claude Code cache proxy (Anthropic API, with keepalive pings)"`.

Docs, written from the code as implemented (D3, spec § Docs):
- `python/README.md` § `cache-proxy`: the synopsis gains `[--keepalive]`, and the pass-through sentence is qualified as the behaviour without it. One new paragraph covers what `--keepalive` does and when: the session and agent headers, the seven outcomes and their candidate effects, `Accept-Encoding: identity` and the SSE tap, the activity rule, 270 s due, the 5 s tick, the 60-min ceiling, the end reasons, 64 candidates and memory-only state. It also covers the ping's shape (a fresh connection, a 30 s timeout, no retry, a response read and discarded), the held credentials (D7), the new log fields and events, and the failure posture.
- `home/common/claude-code/README.md` § Cache proxy: replace the whole sentence that begins `It forwards requests unchanged today;` and ends with the spike's path with sentences saying that the service runs with `--keepalive`, which `python/README.md` § `cache-proxy` describes, and that the replay is the one fact 2 of `docs/spikes/cache-proxy-spike.md` measured. Say how to switch it off (drop the flag from `cacheProxyArgs`, rebuild) and how an A/B pair runs: the built launcher by hand in the foreground on `--port 0`, with and without the flag, and one session pointed at it by a caller-set `ANTHROPIC_BASE_URL` with `ENABLE_TOOL_SEARCH=true`. Also give the accepted cost: a subagent that has finished for good is pinged while the rest of its session stays active, up to 60 minutes, and `keepalive_end` lines measure it (D17). The service description's `--port 27183` becomes `--port 27183 --keepalive`.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py tests/test_cache_proxy.py`
Expected: PASS, 43 tests in `test_cache_keepalive` and every `test_cache_proxy` case.

Run (timeout 30 s): `git diff --quiet HEAD -- tests/test_cache_proxy.py && test "$(grep -c '27183' home/common/claude-code/default.nix)" -eq 1 && if grep -q 'forwards requests unchanged today' home/common/claude-code/README.md; then exit 1; fi && grep -q -- '--keepalive' python/README.md && echo docs-ok`
Expected: `docs-ok`.

Run (timeout 3600 s): `just build`. Then (timeout 600 s):

```bash
set -euo pipefail
a='.config.home-manager.users.anis.launchd.agents.claude-cache-proxy.config.ProgramArguments'
for host in mbp eleven-m5; do
  nix eval --json ".#darwinConfigurations.$host$a" | jq -e '.[1:] == ["--port","27183","--keepalive"]'
done
nix eval --json '.#nixosConfigurations.anis-desktop.config.home-manager.users.anis.systemd.user.services.claude-cache-proxy.Service.ExecStart' \
  | jq -e 'length == 1 and (.[0] | endswith(" --port 27183 --keepalive"))'
echo nix-ok
```

Expected: three `true` lines, then `nix-ok`. At the starting commit the first `jq -e` prints `false` and the script stops.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/cache_proxy.py tests/test_cache_keepalive.py home/common/claude-code/default.nix home/common/claude-code/README.md python/README.md
launch-commit … -- -m "feat(cache-proxy): --keepalive pings idle subagent conversations; the service runs with it (issue 423)" -m "<session trailers>"
```
