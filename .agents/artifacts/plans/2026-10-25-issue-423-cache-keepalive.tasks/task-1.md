# Task 1: Classification, ping building and the SSE reader

Spec § Conversation identity and eligibility, § The ping, § Response tap and § Log contract (the handle), per D4, D5, D6, D9, D11, D16, D20 and D23. This task creates the library module `agent_tools.cache_keepalive` with its constants and pure functions. Task 2 adds the stateful `Keepalive` class to the same module, and Task 3 wires it into the proxy. Nothing here touches the network, a thread or the clock.

**Files:**
- Create: `python/agent_tools/cache_keepalive.py`
- Create: `tests/test_cache_keepalive.py`
- Modify: `justfile` (the `agent-workflow-tests` list: add the line `    tests/test_cache_keepalive.py \` directly after `    tests/test_cache_proxy.py \`)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest`, `reject_duplicate_keys` and `reject_nonfinite_literal`.
- Produces, in `agent_tools.cache_keepalive`:
  - `OUTCOMES = ("untracked", "main", "unparsed", "no_tail_mark", "ttl_1h", "thinking_budget", "tracked")`, in check order.
  - `MESSAGES_PATH = "/v1/messages"`, `SESSION_HEADER = "X-Claude-Code-Session-Id"`, `AGENT_HEADER = "x-claude-code-agent-id"`.
  - `USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens", "cache_creation")`.
  - `header_value(headers: list[tuple[str, str]], name: str) -> str | None`.
  - `conversation_handle(session: str, agent: str | None) -> str`.
  - `@dataclass(frozen=True) class Classification` with `outcome: str`, `session: str | None = None`, `agent: str | None = None` and `model: str | None = None`.
  - `classify(method: str, path: str, headers: list[tuple[str, str]], body: bytes) -> Classification`.
  - `ping_body(body: bytes) -> bytes`, `identity_headers(headers) -> list[tuple[str, str]]` and `ping_headers(headers, length: int) -> list[tuple[str, str]]`.
  - `class SseReader` with `feed(chunk: bytes) -> None` and the attributes `stop_reason: str | None` and `usage: dict`.
- Produces, in `tests/test_cache_keepalive.py`, module-level helpers that Tasks 2 and 3 reuse: `MESSAGES`, `SESSION`, `AGENT_P`, `AGENT_Q`, `START_USAGE`, `mark`, `document`, `encode`, `forwarded`, `sse` and `pieces`.

**Invariants:**
- `classify` checks the outcomes in `OUTCOMES` order and stops at the first match (D5):
  1. `untracked`: the method is not `POST`, `urlsplit(path).path` is not `MESSAGES_PATH`, or there is no session header.
  2. `main`: there is no agent header. The body is never parsed, so a main body that is not JSON is still `main`.
  3. `unparsed`: the request has any `Content-Encoding` header, or the body is not a JSON object under `json.loads(body, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)` (a `ValueError`, `UnicodeDecodeError` included, or a non-`dict` result).
  4. `no_tail_mark`: no mark lies in the last message (below).
  5. `ttl_1h`: some mark has `"ttl": "1h"`. A mark with no `ttl` or any other value is a five-minute mark.
  6. `thinking_budget`: `thinking` is an object whose `type` is `"enabled"`.
  7. `tracked`: everything else.
- Header names compare case-insensitively, and `header_value` returns the first value. An absent header and an empty value both count as absent, for the session and the agent header alike.
- A **mark** is a JSON object under the key `cache_control` at one of these places: the top level; `tools[i]`; `system[j]` when `system` is a list; `messages[i].content[j]` when `content` is a list; or `messages[i].content[j].content[k]` when that inner `content` is a list. Non-object items are skipped. This is the set #429 counts (D16). The **tail marks** are the marks inside `messages[-1]`, and only when `messages` is a non-empty list whose last item is an object.
- `Classification.session` and `.agent` are set from `untracked`'s check onward whenever the header is present. `.model` is the body's `model` when the body was parsed and that value is a string, and `None` otherwise.
- `conversation_handle` returns the 12 hex digits after `sha256:` of `telemetry_digest({"agent": agent, "session": session})` (D11). It never contains either header value.
- `ping_body` parses strictly, sets the top-level `max_tokens` to `1` in its key position (appended last if absent), and returns `json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")` (D6, D20). A nested `max_tokens`, such as a tool input's, is untouched. A body that does not parse to an object raises `ValueError`.
- `identity_headers` replaces the value of the first `Accept-Encoding` header with `identity`, keeping its name and position, drops any later `Accept-Encoding`, and appends `("Accept-Encoding", "identity")` when there is none. `ping_headers` also sets the first `Content-Length` to `str(length)` in the same way. Every other header keeps its name, value, order and duplicates. `Host` is not touched, because the headers passed in are the ones the proxy forwarded, whose `Host` is already the upstream's.
- `SseReader` splits lines on `\n` across `feed` calls and drops a trailing `\r`. A line `event: X` sets the event name. A `data:` line (one leading space removed) is kept only while the event name starts with `message_`. A blank line dispatches the event. Lines starting with `:` are ignored. At dispatch, the joined data is decoded with plain `json.loads`. A `ValueError` or a non-object result records nothing. `message_start` merges `message.usage`, and `message_delta` merges `usage` and takes `delta.stop_reason` when it is a string. Merging copies only the `USAGE_FIELDS` keys present, and later values win.
- Nothing runs at import time. The module imports only the standard library and `agent_tools.canonical`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cache_keepalive.py`:

```python
"""`agent_tools.cache_keepalive`: keepalive pings for idle subagent conversations (#423).

The classification, ping-building and SSE-reader cases call the module's functions directly.
Later classes drive `Keepalive` on a fake clock against #422's `FakeUpstream`, put a
`ProxyServer` in front of it, and run `python -m agent_tools.cache_proxy --keepalive`.
"""

import json
import unittest

from agent_tools import cache_keepalive
from agent_tools.canonical import telemetry_digest

MESSAGES = "/v1/messages?beta=true"
SESSION = "5e2b6c1a-0d3f-4c55-9a51-6f0c2d1e7a90"
AGENT_P = "a38fa800e252fb137"
AGENT_Q = "a39c48ae0258a6edb"
START_USAGE = {"input_tokens": 3, "cache_creation_input_tokens": 120,
               "cache_read_input_tokens": 40000,
               "cache_creation": {"ephemeral_5m_input_tokens": 120, "ephemeral_1h_input_tokens": 0},
               "output_tokens": 1}


def mark(ttl=None):
    return {"type": "ephemeral"} if ttl is None else {"type": "ephemeral", "ttl": ttl}


def document(*, tail_mark=True, ttl=None, thinking=None, note="ok"):
    """A body shaped like Claude Code 2.1.302's subagent requests: adaptive thinking, marks
    without a ttl, and the last mark on a trailing system-role message."""
    tail = {"type": "text", "text": "<system-reminder>" + note + "</system-reminder>"}
    if tail_mark:
        tail["cache_control"] = mark(ttl)
    return {
        "model": "claude-opus-5-5",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Read the file."}]},
            {"role": "assistant", "content": [{
                "type": "tool_use", "id": "toolu_01", "name": "Read",
                "input": {"file_path": "/tmp/f", "max_tokens": 50}}]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "toolu_01",
                "content": [{"type": "text", "text": "line one"}]}]},
            {"role": "system", "content": [tail]},
        ],
        "system": [{"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.302"},
                   {"type": "text", "text": "You are a subagent.", "cache_control": mark(ttl)}],
        "tools": [{"name": "Read", "description": "Read a file.",
                   "input_schema": {"type": "object"}}],
        "metadata": {"user_id": "user_0123"},
        "max_tokens": 32000,
        "thinking": {"type": "adaptive"} if thinking is None else thinking,
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        "output_config": {"effort": "high"},
        "stream": True,
    }


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def forwarded(agent=AGENT_P, *, length=0, session=SESSION, extra=()):
    """Request headers as the proxy forwards them (Host already the upstream's), in Claude
    Code's order; `agent=None` is a main-session request."""
    headers = [("Host", "api.anthropic.com"), ("Accept", "application/json"),
               ("X-Stainless-Retry-Count", "0"), ("X-Stainless-Timeout", "600"),
               ("anthropic-beta", "claude-code-20250219"), ("anthropic-beta", "oauth-2025-04-20"),
               ("anthropic-version", "2023-06-01"), ("authorization", "Bearer test-token-1"),
               ("content-type", "application/json"),
               ("user-agent", "claude-cli/2.1.302 (external, cli)"), ("x-app", "cli")]
    if session is not None:
        headers.append(("X-Claude-Code-Session-Id", session))
    if agent is not None:
        headers.append(("x-claude-code-agent-id", agent))
    return headers + list(extra) + [("Accept-Encoding", "gzip, deflate, br, zstd"),
                                    ("Content-Length", str(length))]


def sse(stop_reason, *, newline=b"\n"):
    """A streamed Messages response: message_start with START_USAGE, a text block whose text
    looks like an event line, a ping, then message_delta with `stop_reason` and 12 output tokens."""
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [], "stop_reason": None, "usage": START_USAGE}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("ping", {"type": "ping"}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "event: message_delta"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 12}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(b"event: " + name.encode() + newline + b"data: " + encode(data) + newline
                    + newline for name, data in events)


def pieces(data, size=7):
    return [data[index:index + size] for index in range(0, len(data), size)]


class ClassifyTest(unittest.TestCase):
    """`classify` checks the D5 outcomes in order and stops at the first match."""

    def classify(self, value=None, *, raw=None, method="POST", path=MESSAGES, **headers):
        body = encode(document() if value is None else value) if raw is None else raw
        return cache_keepalive.classify(method, path, forwarded(length=len(body), **headers), body)

    def test_the_outcome_set_is_closed_and_in_check_order(self):
        self.assertEqual(cache_keepalive.OUTCOMES, ("untracked", "main", "unparsed", "no_tail_mark",
                                                    "ttl_1h", "thinking_budget", "tracked"))

    def test_requests_the_keepalive_ignores_are_untracked(self):
        for result in (self.classify(method="GET"),
                       self.classify(path="/v1/messages/count_tokens?beta=true"),
                       self.classify(session=None), self.classify(session="")):
            self.assertEqual(result.outcome, "untracked")

    def test_a_request_without_an_agent_header_is_main_and_its_body_is_never_parsed(self):
        for agent in (None, ""):
            result = self.classify(raw=b"not json", agent=agent)
            self.assertEqual((result.outcome, result.session, result.agent),
                             ("main", SESSION, None))

    def test_an_encoded_body_or_one_that_is_no_strict_object_is_unparsed(self):
        self.assertEqual(self.classify(extra=[("Content-Encoding", "gzip")]).outcome, "unparsed")
        for raw in (b"[1]", b"{", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"):
            self.assertEqual(self.classify(raw=raw).outcome, "unparsed", raw)

    def test_a_last_message_without_a_mark_is_no_tail_mark_even_with_a_one_hour_mark(self):
        value = document(tail_mark=False)
        self.assertEqual(self.classify(value).outcome, "no_tail_mark")
        value["messages"][-1]["content"] = "plain text"
        self.assertEqual(self.classify(value).outcome, "no_tail_mark")
        self.assertEqual(self.classify(dict(value, messages=[])).outcome, "no_tail_mark")
        self.assertEqual(self.classify(document(tail_mark=False, ttl="1h")).outcome, "no_tail_mark")

    def test_a_mark_inside_a_tool_result_of_the_last_message_is_a_tail_mark(self):
        value = document(tail_mark=False)
        value["messages"][-1] = {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "toolu_01",
            "content": [{"type": "text", "text": "x", "cache_control": mark()}]}]}
        self.assertEqual(self.classify(value).outcome, "tracked")

    def test_any_one_hour_mark_is_ttl_1h_and_is_checked_before_thinking(self):
        in_tools = document()
        in_tools["tools"][0]["cache_control"] = mark("1h")
        inner = document()
        inner["messages"][2]["content"][0]["content"][0]["cache_control"] = mark("1h")
        top = dict(document(), cache_control=mark("1h"))
        enabled = {"type": "enabled", "budget_tokens": 2048}
        for value in (document(ttl="1h"), in_tools, inner, top,
                      document(ttl="1h", thinking=enabled)):
            self.assertEqual(self.classify(value).outcome, "ttl_1h")

    def test_enabled_thinking_is_thinking_budget(self):
        value = document(thinking={"type": "enabled", "budget_tokens": 2048})
        self.assertEqual(self.classify(value).outcome, "thinking_budget")

    def test_a_five_minute_subagent_request_is_tracked_with_its_identity_and_model(self):
        for value in (document(), document(ttl="5m")):
            result = self.classify(value)
            self.assertEqual((result.outcome, result.session, result.agent, result.model),
                             ("tracked", SESSION, AGENT_P, "claude-opus-5-5"))


class HandleTest(unittest.TestCase):
    def test_the_handle_is_twelve_hex_digits_of_the_canonical_digest(self):
        handle = cache_keepalive.conversation_handle(SESSION, AGENT_P)
        digest = telemetry_digest({"agent": AGENT_P, "session": SESSION})
        self.assertEqual(handle, digest.removeprefix("sha256:")[:12])
        self.assertRegex(handle, r"\A[0-9a-f]{12}\Z")
        main = cache_keepalive.conversation_handle(SESSION, None)
        self.assertEqual(main, telemetry_digest({"agent": None, "session": SESSION})[7:19])
        self.assertNotEqual(main, handle)


class PingRequestTest(unittest.TestCase):
    def test_the_ping_body_changes_only_the_top_level_max_tokens(self):
        value = document()
        ping = cache_keepalive.ping_body(encode(value))
        expected = dict(value, max_tokens=1)
        self.assertEqual(ping, json.dumps(expected, separators=(",", ":"), ensure_ascii=True).encode())
        self.assertEqual(list(json.loads(ping)), list(value))
        self.assertEqual(json.loads(ping)["messages"][1]["content"][0]["input"]["max_tokens"], 50)

    def test_a_lone_surrogate_escape_stays_an_escape(self):
        raw = encode(document()).replace(b"line one", b"line \\ud800 one")
        ping = cache_keepalive.ping_body(raw)
        self.assertTrue(ping.isascii())
        self.assertIn(b"line \\ud800 one", ping)
        self.assertEqual(json.loads(ping), dict(json.loads(raw), max_tokens=1))

    def test_ping_headers_keep_names_order_and_duplicates_and_change_two_values(self):
        headers = forwarded(length=999)
        self.assertEqual(cache_keepalive.ping_headers(headers, 1234), [
            (name, "identity" if name == "Accept-Encoding" else
             "1234" if name == "Content-Length" else value) for name, value in headers])

    def test_identity_headers_replace_accept_encoding_in_place_or_append_it(self):
        headers = forwarded(length=10)
        expected = [(name, "identity" if name == "Accept-Encoding" else value)
                    for name, value in headers]
        self.assertEqual(cache_keepalive.identity_headers(headers), expected)
        self.assertEqual(cache_keepalive.identity_headers(headers + [("accept-encoding", "br")]),
                         expected)
        bare = [header for header in headers if header[0] != "Accept-Encoding"]
        self.assertEqual(cache_keepalive.identity_headers(bare),
                         bare + [("Accept-Encoding", "identity")])


class SseReaderTest(unittest.TestCase):
    @staticmethod
    def read(data, size):
        reader = cache_keepalive.SseReader()
        for piece in pieces(data, size):
            reader.feed(piece)
        return reader

    def test_stop_reason_and_merged_usage_survive_any_chunking(self):
        for size in (1, 7, 65536):
            reader = self.read(sse("tool_use"), size)
            self.assertEqual(reader.stop_reason, "tool_use")
            self.assertEqual(reader.usage, dict(START_USAGE, output_tokens=12))

    def test_crlf_line_endings_are_read(self):
        self.assertEqual(self.read(sse("end_turn", newline=b"\r\n"), 5).stop_reason, "end_turn")

    def test_only_message_events_are_decoded(self):
        data = b"event: content_block_delta\ndata: {not json\n\n" + sse("end_turn")
        self.assertEqual(self.read(data, 3).stop_reason, "end_turn")

    def test_a_malformed_message_event_records_nothing(self):
        reader = self.read(b'event: message_delta\ndata: {"delta":\n\n', 4)
        self.assertEqual((reader.stop_reason, reader.usage), (None, {}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py`
Expected: an `ImportError` for `cache_keepalive`, since the module does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/cache_keepalive.py` with this docstring, which Task 2 extends when it adds `Keepalive`:

```python
"""Keepalive pings for idle subagent conversations behind `cache-proxy --keepalive` (#423).

`classify` sorts each forwarded request into one outcome of `OUTCOMES`; `ping_body` and
`ping_headers` rebuild a candidate request as its `max_tokens=1` replay; `SseReader` reads a
streamed response's `stop_reason` and usage.
"""
```

Implement the Interfaces' names to the Invariants. Decisions the code must keep:
- `classify` resolves `session = header_value(headers, SESSION_HEADER)` and `agent = header_value(headers, AGENT_HEADER)` first, then returns at the first matching rule, so a `main` or `untracked` body is never decoded.
- One private helper owns the mark walk (`_marks(value) -> Iterator[dict]`), and `ttl_1h` and the tail rule both use it: the tail rule runs it over `{"messages": [value["messages"][-1]]}`. With this, D16's merge step has exactly one function to point at #429's.
- One private helper owns the header rewrite (`_set_header(headers, name, value)`), which `identity_headers` and `ping_headers` share. It returns a new list and leaves its input unchanged.
- `SseReader` holds only the unterminated line, the current event name and the data lines of a `message_*` event, so its memory does not grow with the stream.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_keepalive.py`
Expected: PASS, 18 tests.

Run (timeout 30 s): `test "$(grep -A1 -n '^    tests/test_cache_proxy.py \\$' justfile | tail -1 | sed 's/^[0-9]*-//')" = '    tests/test_cache_keepalive.py \' && test "$(grep -c 'tests/test_cache_keepalive.py' justfile)" -eq 1 && echo listed`
Expected: `listed`. At the starting commit this fails, because the justfile does not list the file.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/cache_keepalive.py tests/test_cache_keepalive.py justfile
launch-commit … -- -m "feat(cache-proxy): keepalive request classification and ping builders (issue 423)" -m "<session trailers>"
```
