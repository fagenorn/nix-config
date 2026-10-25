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
