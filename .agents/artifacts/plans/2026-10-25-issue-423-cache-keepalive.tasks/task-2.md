# Task 2: The `Keepalive` state and scheduler

Spec § Interface and seam, § Conversation identity and eligibility, § The ping, § Session activity, § Timing and stop rules and § Log contract, per D2, D5–D11, D17–D19, D23 and D24. This task adds `Keepalive`, `Track` and `Ping` to `agent_tools.cache_keepalive`. They are driven directly on a fake clock, and pings go to #422's `FakeUpstream`. The proxy does not call them yet; that is Task 3.

**Files:**
- Modify: `python/agent_tools/cache_keepalive.py`
- Modify: `tests/test_cache_keepalive.py` (new imports and helpers, plus the classes `KeepaliveTest`, `FailingPingTest` and `RunLoopTest`)

**Interfaces:**
- Consumes (Task 1): `classify`, `Classification`, `conversation_handle`, `ping_body`, `ping_headers`, `identity_headers`, `SseReader`, `USAGE_FIELDS`, and the test helpers `MESSAGES`, `SESSION`, `AGENT_P`, `AGENT_Q`, `START_USAGE`, `document`, `encode`, `forwarded`, `sse` and `pieces`.
- Consumes (#422): `agent_tools.cache_proxy.ERROR_BODY_LIMIT`, `READ_SIZE`, `UPSTREAM_FAILURES` and `LineLog`, and from `tests.test_cache_proxy` the names `TIMEOUT`, `FakeUpstream`, `RecordingStream` and `closed_port` (D25).
- Produces, in `agent_tools.cache_keepalive`:
  - `END_REASONS = ("resumed", "ceiling", "session_idle", "ping_failed", "evicted")`, `DUE_AFTER = 270.0`, `TICK_INTERVAL = 5.0`, `WINDOW = 3600.0`, `MAX_CANDIDATES = 64` and `PING_TIMEOUT = 30.0`.
  - `Keepalive(log, connect, clock)`. `log` has `write(event, **fields)`. `connect(timeout: float)` returns an unconnected `http.client.HTTPConnection`, and `clock()` returns monotonic seconds. Its methods are `observe(method, path, headers, body) -> Track`, `tick() -> list[Ping]`, `send(ping: Ping) -> None` and `run(stop: threading.Event) -> None`.
  - `Track`, with the attributes `outcome: str`, `conversation: str | None` (the handle, or `None` when untracked), `headers: list[tuple[str, str]]` (the headers to send) and `stop_reason: str | None`, and the methods `started(status: int, content_type: str | None, content_encoding: str | None)`, `chunk(data: bytes)`, `done(outcome: str)` and `log_fields() -> dict`.
  - `@dataclass(frozen=True, eq=False) class Ping`, with the public fields `conversation`, `method`, `path`, `headers` (a tuple of pairs), `body`, `model` and `idle_s`, plus whatever private fields tie it to its conversation.
- Produces, in `tests/test_cache_keepalive.py`: `OTHER_SESSION`, `SSE_HEAD`, `chunked`, `sse_reply`, `FakeClock` and `KeepaliveCase`, which Task 3 reuses.

**Invariants:**
- One `threading.Lock` guards all state. Every method takes it for the whole of its state change and never across network I/O. Log lines written under it go to `LineLog`, which has its own lock and never calls back.
- `observe` never parses a `main` or `untracked` body (Task 1). An `untracked` track touches no state: its `headers` is the list passed in, its `started`, `chunk` and `done` do nothing, and `log_fields()` is `{"keepalive": "untracked"}`. Every other track's `headers` is `identity_headers(headers)` (D9).
- Only a candidate's body and headers are kept past its track (D7). They are never logged.
- `ping` lines are written for every ping sent, superseded ones included, because AC3 prices every one (D15).
- `TICK_INTERVAL` is read from the module globals on every loop turn, so a test can patch it (D25).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cache_keepalive.py`, add these imports below the existing ones:

```python
import http.client
import threading
from unittest import mock

from agent_tools import cache_proxy
from tests.test_cache_proxy import TIMEOUT, FakeUpstream, RecordingStream, closed_port
```

Then add, after `class SseReaderTest`:

```python
OTHER_SESSION = "0c4f9a7e-2b1d-4e8a-9f3c-5d6e7f8a9b0c"
SSE_HEAD = (b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n")


def chunked(payload):
    return b"%x\r\n%s\r\n0\r\n\r\n" % (len(payload), payload)


def sse_reply(stop_reason="end_turn"):
    """A FakeUpstream responder answering every request with one streamed response."""
    def responder(sock, head, body):
        sock.sendall(SSE_HEAD + chunked(sse(stop_reason)))
        return True
    return responder


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class KeepaliveCase(unittest.TestCase):
    """A `Keepalive` on a fake clock whose pings go to a `FakeUpstream` (D12)."""

    def setUp(self):
        self.clock = FakeClock()
        self.stream = RecordingStream()
        self.upstream = FakeUpstream(self.responder())
        self.addCleanup(self.upstream.close)
        port = self.upstream.server.server_address[1]
        self.keepalive = self.make(
            lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))

    def make(self, connect):
        return cache_keepalive.Keepalive(cache_proxy.LineLog(self.stream), connect, self.clock)

    def responder(self):
        return sse_reply()

    def exchange(self, agent, value=None, *, session=SESSION, status=200,
                 stop_reason="end_turn", finish=True):
        """One client request through its track: observed, started, streamed and done."""
        raw = encode(document() if value is None else value)
        track = self.keepalive.observe("POST", MESSAGES,
                                       forwarded(agent, length=len(raw), session=session), raw)
        track.started(status, "text/event-stream; charset=utf-8", None)
        if finish:
            for piece in pieces(sse(stop_reason)):
                track.chunk(piece)
            track.done("complete")
        return track

    def busy_main(self):
        """The main conversation, pending on a tool such as an Agent call: the session is active."""
        return self.exchange(None, document(ttl="1h"), stop_reason="tool_use")

    def due(self, seconds):
        self.clock.advance(seconds)
        return self.keepalive.tick()

    def events(self, event):
        return [record for record in map(json.loads, self.stream.lines)
                if record["event"] == event]

    def ends(self):
        return [(record["conversation"], record["reason"], record["pings"])
                for record in self.events("keepalive_end")]

    @staticmethod
    def handle(agent, session=SESSION):
        return cache_keepalive.conversation_handle(session, agent)


class KeepaliveTest(KeepaliveCase):
    def test_a_conversation_with_a_sibling_in_flight_gets_one_ping_at_270_s(self):
        sibling = encode(document(note="sibling"))
        self.keepalive.observe("POST", MESSAGES, forwarded(AGENT_Q, length=len(sibling)), sibling)
        self.clock.advance(1)
        value = document()
        self.exchange(AGENT_P, value)
        self.assertEqual(self.due(269.5), [])
        [ping] = self.due(0.5)
        self.assertEqual((ping.conversation, ping.method, ping.path),
                         (self.handle(AGENT_P), "POST", MESSAGES))
        self.keepalive.send(ping)
        [(_, head, body)] = self.upstream.requests
        self.assertEqual(json.loads(body), dict(value, max_tokens=1))
        expected = [(name, "identity" if name == "Accept-Encoding" else
                     str(len(body)) if name == "Content-Length" else header)
                    for name, header in forwarded(AGENT_P)]
        self.assertEqual(head.split(b"\r\n"), [b"POST %s HTTP/1.1" % MESSAGES.encode()]
                         + [("%s: %s" % pair).encode() for pair in expected] + [b""])
        [line] = self.events("ping")
        self.assertEqual(
            {key: line[key] for key in ("conversation", "model", "idle_s", "status", "outcome", "usage")},
            {"conversation": self.handle(AGENT_P), "model": "claude-opus-5-5", "idle_s": 270.0,
             "status": 200, "outcome": "complete", "usage": dict(START_USAGE, output_tokens=12)})
        self.assertNotIn("test-token-1", "\n".join(self.stream.lines))
        self.assertEqual(self.keepalive.tick(), [])

    def test_an_idle_session_ends_the_conversation_and_later_activity_does_not_revive_it(self):
        self.exchange(AGENT_P)
        self.assertEqual(self.due(270), [])
        [end] = self.events("keepalive_end")
        self.assertEqual({key: end[key] for key in ("conversation", "reason", "pings", "idle_s")},
                         {"conversation": self.handle(AGENT_P), "reason": "session_idle",
                          "pings": 0, "idle_s": 270.0})
        self.busy_main()
        self.assertEqual(self.due(600), [])
        self.assertEqual(self.upstream.requests, [])

    def test_pings_repeat_while_the_session_is_active_and_stop_at_the_ceiling(self):
        self.busy_main()
        self.exchange(AGENT_P)
        while pings := self.due(270):
            [ping] = pings
            self.keepalive.send(ping)
        self.assertEqual(len(self.upstream.requests), 13)
        [end] = self.events("keepalive_end")
        self.assertEqual((end["reason"], end["pings"], end["idle_s"]), ("ceiling", 13, 3780.0))

    def test_its_own_pending_tool_keeps_it_pinged_while_end_turn_does_not(self):
        self.exchange(AGENT_P, stop_reason="tool_use")
        self.exchange(AGENT_Q, session=OTHER_SESSION)
        [ping] = self.due(270)
        self.assertEqual(ping.conversation, self.handle(AGENT_P))
        self.assertEqual(self.ends(), [(self.handle(AGENT_Q, OTHER_SESSION), "session_idle", 0)])

    def test_two_idle_conversations_do_not_keep_each_other_alive(self):
        self.exchange(AGENT_P)
        self.clock.advance(100)
        self.exchange(AGENT_Q, document(note="q"))
        [ping] = self.due(170)
        self.assertEqual(ping.conversation, self.handle(AGENT_P))
        self.keepalive.send(ping)
        self.assertEqual(self.due(100), [])
        self.assertEqual(self.due(170), [])
        self.assertEqual(self.ends(), [(self.handle(AGENT_Q), "session_idle", 0),
                                       (self.handle(AGENT_P), "session_idle", 1)])

    def test_one_hour_main_and_thinking_budget_conversations_are_never_pinged(self):
        self.busy_main()
        value = document()
        enabled = {"type": "enabled", "budget_tokens": 2048}
        tracks = [self.exchange(AGENT_P, value),
                  self.exchange(AGENT_P, document(tail_mark=False, note="summary")),
                  self.exchange(AGENT_Q, document(ttl="1h")),
                  self.exchange("a-thinking", document(note="t")),
                  self.exchange("a-thinking", document(thinking=enabled))]
        self.assertEqual([track.outcome for track in tracks],
                         ["tracked", "no_tail_mark", "ttl_1h", "tracked", "thinking_budget"])
        [ping] = self.due(270)
        self.assertEqual((ping.conversation, json.loads(ping.body)),
                         (self.handle(AGENT_P), dict(value, max_tokens=1)))
        self.keepalive.send(ping)
        self.assertEqual([later.conversation for later in self.due(270)], [self.handle(AGENT_P)])

    def test_a_non_2xx_client_response_changes_no_candidate(self):
        self.busy_main()
        value = document()
        self.exchange(AGENT_P, value)
        self.exchange(AGENT_P, document(note="overloaded"), status=529)
        self.exchange(AGENT_Q, document(note="q"), status=400)
        [ping] = self.due(270)
        self.assertEqual((ping.conversation, json.loads(ping.body)),
                         (self.handle(AGENT_P), dict(value, max_tokens=1)))

    def test_a_client_request_after_pings_ends_the_period_resumed_with_its_count(self):
        self.busy_main()
        self.exchange(AGENT_P)
        for _ in range(2):
            [ping] = self.due(270)
            self.keepalive.send(ping)
        self.clock.advance(60)
        self.exchange(AGENT_P, document(note="next turn"))
        self.exchange(AGENT_P, document(note="turn after"))
        [end] = self.events("keepalive_end")
        self.assertEqual((end["conversation"], end["reason"], end["pings"], end["idle_s"]),
                         (self.handle(AGENT_P), "resumed", 2, 600.0))

    def test_a_client_request_while_a_ping_is_in_flight_supersedes_it(self):
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        self.clock.advance(5)
        newer = document(note="newer")
        self.exchange(AGENT_P, newer)
        self.clock.advance(5)
        self.keepalive.send(ping)
        self.assertEqual(len(self.events("ping")), 1)
        self.assertEqual(self.due(264), [])
        [later] = self.due(1)
        self.assertEqual(json.loads(later.body), dict(newer, max_tokens=1))

    def test_a_candidate_still_streaming_is_pinged_at_its_due_time(self):
        self.exchange(AGENT_P, finish=False)
        [ping] = self.due(270)
        self.assertEqual(ping.conversation, self.handle(AGENT_P))

    def test_a_lone_surrogate_body_is_pinged_with_the_same_json_value(self):
        self.busy_main()
        raw = encode(document()).replace(b"line one", b"line \\ud800 one")
        track = self.keepalive.observe("POST", MESSAGES, forwarded(AGENT_P, length=len(raw)), raw)
        track.started(200, "text/event-stream", None)
        track.done("complete")
        [ping] = self.due(270)
        self.keepalive.send(ping)
        [(_, _, body)] = self.upstream.requests
        self.assertEqual(json.loads(body), dict(json.loads(raw), max_tokens=1))

    def test_the_65th_candidate_evicts_the_one_whose_last_client_request_is_oldest(self):
        self.busy_main()
        agents = ["a%02d" % index for index in range(65)]
        for agent in agents:
            self.exchange(agent, document(note=agent))
            self.clock.advance(1)
        self.assertEqual(self.ends(), [(self.handle("a00"), "evicted", 0)])
        self.assertEqual({ping.conversation for ping in self.due(270)},
                         {self.handle(agent) for agent in agents[1:]})

    def test_a_track_carries_its_outcome_headers_and_log_fields(self):
        raw = encode(document())
        headers = forwarded(AGENT_P, length=len(raw))
        track = self.keepalive.observe("POST", MESSAGES, headers, raw)
        self.assertEqual((track.outcome, track.conversation, track.headers),
                         ("tracked", self.handle(AGENT_P), cache_keepalive.identity_headers(headers)))
        track.started(200, "text/event-stream", None)
        for piece in pieces(sse("tool_use")):
            track.chunk(piece)
        track.done("complete")
        self.assertEqual(track.log_fields(), {"keepalive": "tracked",
                                              "conversation": self.handle(AGENT_P),
                                              "stop_reason": "tool_use"})
        cut = self.exchange(AGENT_Q, finish=False)
        cut.chunk(sse("tool_use"))
        cut.done("client_closed")
        packed = self.keepalive.observe("POST", MESSAGES, headers, raw)
        packed.started(200, "text/event-stream", "gzip")
        packed.chunk(sse("tool_use"))
        packed.done("complete")
        self.assertEqual([cut.log_fields(), packed.log_fields()],
                         [{"keepalive": "tracked", "conversation": self.handle(AGENT_Q)},
                          {"keepalive": "tracked", "conversation": self.handle(AGENT_P)}])
        ignored = self.keepalive.observe("GET", "/v1/models", headers, b"")
        ignored.started(200, "text/event-stream", None)
        ignored.chunk(sse("tool_use"))
        ignored.done("complete")
        self.assertEqual((ignored.headers, ignored.log_fields()), (headers, {"keepalive": "untracked"}))


class FailingPingTest(KeepaliveCase):
    ERROR = b'{"type":"error","error":{"type":"authentication_error","message":"expired"}}'

    def responder(self):
        def reply(sock, head, body):
            sock.sendall(b"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\n"
                         b"Content-Length: %d\r\n\r\n%s" % (len(self.ERROR), self.ERROR))
            return True
        return reply

    def test_a_401_ping_ends_ping_failed_with_its_error_body_and_is_never_retried(self):
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        self.keepalive.send(ping)
        [line] = self.events("ping")
        self.assertEqual((line["status"], line["outcome"], line["error_body"]),
                         (401, "complete", self.ERROR.decode()))
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "ping_failed", 1)])
        self.assertEqual(self.due(270), [])
        self.assertEqual(len(self.upstream.requests), 1)

    def test_an_unreachable_upstream_ends_ping_failed(self):
        port = closed_port()
        self.keepalive = self.make(
            lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        self.keepalive.send(ping)
        [line] = self.events("ping")
        self.assertEqual((line["status"], line["outcome"]), (None, "upstream_error"))
        self.assertTrue(line["error"].startswith("ConnectionRefusedError"), line)
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "ping_failed", 1)])

    def test_an_unexpected_error_in_send_ends_the_conversation_and_propagates(self):
        def broken(timeout):
            raise RuntimeError("bug")

        self.keepalive = self.make(broken)
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        with self.assertRaises(RuntimeError):
            self.keepalive.send(ping)
        self.assertEqual((self.events("ping"), self.ends()),
                         ([], [(self.handle(AGENT_P), "ping_failed", 1)]))


class RunLoopTest(unittest.TestCase):
    def test_run_logs_tick_and_send_errors_and_keeps_running(self):
        stream = RecordingStream()
        sent = threading.Event()

        class Flaky(cache_keepalive.Keepalive):
            ticks = 0

            def tick(self):
                Flaky.ticks += 1
                if Flaky.ticks == 1:
                    raise RuntimeError("tick boom")
                return ["ping"] if Flaky.ticks == 2 else []

            def send(self, ping):
                sent.set()
                raise RuntimeError("send boom")

        keepalive = Flaky(cache_proxy.LineLog(stream), None, FakeClock())
        stop = threading.Event()
        with mock.patch.object(cache_keepalive, "TICK_INTERVAL", 0.01):
            thread = threading.Thread(target=keepalive.run, args=(stop,), daemon=True)
            thread.start()
            self.assertTrue(sent.wait(TIMEOUT))
            records = stream.records(2)
            stop.set()
            thread.join(TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual([(record["event"], record["stage"], record["error"]) for record in records],
                         [("keepalive_error", "tick", "RuntimeError: tick boom"),
                          ("keepalive_error", "send", "RuntimeError: send boom")])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py`
Expected: Task 1's 18 tests pass. The 17 new ones error with `AttributeError: module 'agent_tools.cache_keepalive' has no attribute 'Keepalive'`.

- [ ] **Step 3: Write the minimal implementation**

Add `import http.client`, `import threading`, `from dataclasses import dataclass, field` and `from agent_tools.cache_proxy import ERROR_BODY_LIMIT, READ_SIZE, UPSTREAM_FAILURES` to `cache_keepalive.py`. `cache_proxy` must not import this module at its top level (D24; Task 3 imports it inside `main`). Extend the module docstring with one paragraph: `Keepalive` holds each subagent conversation's candidate request, `tick` returns the pings now due, `send` sends one, and `run` is the production loop, which only a command's `main` starts.

**State.** `_sessions: dict[str, dict[str | None, _Conversation]]` maps session to agent (`None` for main) to a record. A `_Conversation` has `session`, `agent`, `handle`; `in_flight: dict[Track, float]` (a track and its send time); `last_request: float | None`; `pending_since: float | None`; `epoch: int`; `pings: int` (the pings issued in the current idle period); `candidate: _Candidate | None`; and `ping: Ping | None` (the ping in flight). A `_Candidate` has `method`, `path`, `headers` (a tuple of the track's sent headers), `body`, `model` and `touch` (seconds).

**Rules** (`now` is `clock()` read under the lock):
1. **`observe`**. Classify the request (Task 1). For `untracked`, return an inert track. Otherwise get or create the conversation. If its `pings > 0`, write `keepalive_end` with `reason` `resumed`, `pings` and `idle_s = round(now - last_request, 1)`, then set `pings = 0` and keep the candidate (D24). Then set `last_request = now`, increment `epoch`, clear `pending_since`, and record the track in `in_flight` at `now`. The track keeps the request's `method`, `path`, sent headers and, for `tracked` only, its body and model.
2. **`started(status, content_type, content_encoding)`**. Record the status. When the status is 2xx, apply the candidate effect (D5, D19, D23). `tracked` replaces the candidate with one whose `touch` is the track's send time, unless the current candidate's `touch` is later. Creating a candidate when `MAX_CANDIDATES` are already held first ends, with `evicted`, the other conversation that holds a candidate and has the oldest `last_request`. `unparsed`, `ttl_1h` and `thinking_budget` clear the candidate silently. `no_tail_mark` and `main` leave it. The effect is one dispatch over the outcome, whose default branch raises `ValueError` naming the value (D5; the seam records it, D18). A tap (`SseReader`) starts only for a 2xx status, a `content_type` whose media type is `text/event-stream`, and a `content_encoding` that is `None` or `identity`.
3. **`chunk(data)`** feeds the tap, if there is one, outside the lock.
4. **`done(outcome)`**. Only the first call counts. It removes the track from `in_flight`. The track's `stop_reason` becomes the tap's when `outcome == "complete"`, and `None` otherwise. When the status was 2xx, the outcome `complete` and the stop reason `tool_use`, set `pending_since = now`. `log_fields()` returns `keepalive` (the outcome) and `conversation`, plus `stop_reason` when it is not `None`.
5. **Activity** of candidate X at `now` (D8). Some conversation of X's session, X and main included, has an `in_flight` send time under `WINDOW` old, or a `pending_since` under `WINDOW` old, or a `last_request` later than X's candidate `touch`. Pings never change any of these.
6. **`tick`**. First prune: drop `in_flight` entries `WINDOW` or more old, then drop each conversation that has no candidate, no ping in flight and no `in_flight` entry, and whose `last_request` and `pending_since` are both absent or `WINDOW` or more old. Then, for each conversation with a candidate, no ping in flight and `now - touch >= DUE_AFTER`, in this order: if `now - last_request >= WINDOW`, end it with `ceiling`; if the session is not active, end it with `session_idle`; otherwise build a `Ping` under the lock, with `body = ping_body(candidate.body)`, `headers = tuple(ping_headers(list(candidate.headers), len(body)))` and `idle_s = round(now - last_request, 1)`. Set `ping` on the conversation, increment `pings`, and return it with the others.
7. **End** (every reason but `resumed`) writes `keepalive_end` with `conversation`, `reason`, `pings` and `idle_s`, then clears the candidate and sets `pings = 0`.
8. **`send(ping)`**. Read `sent = clock()`. Inside the guarded region, call `connect(PING_TIMEOUT)`, then `putrequest(method, path, skip_host=True, skip_accept_encoding=True)`, a `putheader` per pair and `endheaders(body)`, then `getresponse()`. Read the body to its end with `read1(READ_SIZE)`. Feed an SSE 2xx response (by the rule-2 type and encoding test) to an `SseReader`. Parse a 2xx `application/json` body read whole with `json.loads`, taking its `usage`'s `USAGE_FIELDS`. Keep up to `ERROR_BODY_LIMIT` bytes of a body whose status is 400 or more, and always close the connection. A `UPSTREAM_FAILURES` exception gives `outcome` `upstream_error` and `error` = `"<class>: <message>"`; any other exception settles the ping as failed and propagates, with no `ping` line written (D24). Write one `ping` line with `conversation`, `model`, `idle_s`, `status` (`None` without a response), `ttfb_ms`, `duration_ms` (both `round((clock() - sent) * 1000, 1)`, `ttfb_ms` `None` without a response), `outcome` (`complete` once the body was read to its end, else `upstream_error`), and also `usage` when any usage field was seen, `error` when set, and `error_body` (decoded `utf-8` with `replace`) when the status is 400 or more and the body is not empty. Then settle under the lock. If the conversation's `ping` is not this ping, do nothing. Otherwise clear it. If the candidate or the `epoch` changed since the ping was built, stop there (superseded). Otherwise a 2xx with outcome `complete` sets the candidate's `touch` to `sent`, and anything else ends the conversation with `ping_failed`.
9. **`run(stop)`**: `while not stop.wait(TICK_INTERVAL):` call `tick()`. An exception writes `keepalive_error` with `stage` `tick` and `error` = `"<class>: <message>"`, and the loop continues. Each returned ping gets a daemon thread that calls `send` and writes any exception as `keepalive_error` with `stage` `send` (D18).

- [ ] **Step 4: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py tests/test_cache_proxy.py`
Expected: PASS, 35 tests in `test_cache_keepalive` and every `test_cache_proxy` case, with nothing printed outside the unittest report.

Run (timeout 30 s): `if grep -nE '^(import|from) .*cache_keepalive' python/agent_tools/cache_proxy.py; then exit 1; fi; echo no-cycle`
Expected: `no-cycle`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/cache_keepalive.py tests/test_cache_keepalive.py
launch-commit … -- -m "feat(cache-proxy): keepalive state, scheduler and ping sender (issue 423)" -m "<session trailers>"
```
