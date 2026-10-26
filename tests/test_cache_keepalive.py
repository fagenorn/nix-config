"""`agent_tools.cache_keepalive`: keepalive pings for idle subagent conversations (#423).

The classification, ping-building and SSE-reader cases call the module's functions directly.
Later classes drive `Keepalive` on a fake clock against #422's `FakeUpstream`, put a
`ProxyServer` in front of it, and run `python -m agent_tools.cache_proxy --keepalive`.
"""

import functools
import http.client
import json
import select
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from agent_tools import cache_keepalive, cache_proxy, subagent_prefix
from agent_tools.canonical import telemetry_digest
from tests.test_cache_proxy import (TIMEOUT, FakeUpstream, RecordingStream, closed_port, fixture,
                                    holders, json_reply)

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

    def test_a_delayed_older_response_never_undoes_a_newer_requests_clear(self):
        self.busy_main()
        raw = encode(document(note="older"))
        older = self.keepalive.observe("POST", MESSAGES, forwarded(AGENT_P, length=len(raw)), raw)
        self.clock.advance(1)
        self.exchange(AGENT_P, document(ttl="1h"))
        older.started(200, "text/event-stream", None)
        for piece in pieces(sse("end_turn")):
            older.chunk(piece)
        older.done("complete")
        self.assertEqual(older.outcome, "tracked")
        self.assertEqual((self.due(270), self.ends()), ([], []))
        self.assertEqual(self.upstream.requests, [])

    def test_an_older_tool_use_finishing_after_a_newer_request_is_not_pending(self):
        raw = encode(document(note="older"))
        older = self.keepalive.observe("POST", MESSAGES, forwarded(AGENT_P, length=len(raw)), raw)
        older.started(200, "text/event-stream", None)
        self.clock.advance(1)
        self.exchange(AGENT_P, document(note="newer"))
        for piece in pieces(sse("tool_use")):
            older.chunk(piece)
        older.done("complete")
        self.assertEqual(older.stop_reason, "tool_use")
        self.assertEqual(self.due(270), [])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "session_idle", 0)])

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

    def test_a_ping_body_cut_short_of_its_content_length_ends_ping_failed(self):
        partial = b'{"type":"message","usage":{"input_tokens":3'

        def short(sock, head, body):
            sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Content-Length: 100\r\n\r\n" + partial)
            return False

        upstream = FakeUpstream(short)
        self.addCleanup(upstream.close)
        port = upstream.server.server_address[1]
        self.keepalive = self.make(
            lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        self.keepalive.send(ping)
        [line] = self.events("ping")
        self.assertEqual((line["status"], line["outcome"], line["error"]),
                         (200, "upstream_error", "body ended after %d of 100 bytes" % len(partial)))
        self.assertNotIn("usage", line)
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "ping_failed", 1)])
        self.assertEqual(self.due(270), [])
        self.assertEqual(len(upstream.requests), 1)

    def test_a_ping_still_streaming_past_the_ping_timeout_ends_ping_failed(self):
        def frame(data):
            return b"%x\r\n%s\r\n" % (len(data), data)

        start, rest = sse("end_turn").split(b"\n\n", 1)
        beat = frame(b'event: ping\ndata: {"type": "ping"}\n\n')

        def trickle(sock, head, body):
            """message_start, then heartbeats sent once the fake clock is past the bound; the
            stream ends whole only if the reader never stops."""
            sock.sendall(SSE_HEAD + frame(start + b"\n\n"))
            self.clock.advance(cache_keepalive.PING_TIMEOUT + 1)
            try:
                for _ in range(500):
                    sock.sendall(beat)
                sock.sendall(chunked(rest))
            except OSError:
                pass
            return False

        upstream = FakeUpstream(trickle)
        self.addCleanup(upstream.close)
        port = upstream.server.server_address[1]
        self.keepalive = self.make(
            lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        self.keepalive.send(ping)
        [line] = self.events("ping")
        self.assertEqual((line["status"], line["outcome"], line["error"]),
                         (200, "upstream_error", "ping exceeded 30.0 s"))
        self.assertNotIn("usage", line)
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "ping_failed", 1)])
        self.assertEqual(self.due(270), [])
        self.assertEqual(len(upstream.requests), 1)


    def test_a_ping_whose_headers_trickle_past_the_ping_timeout_is_cut_off_by_the_watchdog(self):
        def slow_headers(sock, head, body):
            """A status line, then one header every 50 ms for 2 s: each read returns well inside
            the socket timeout, and the fake clock never moves, so only the watchdog stops it."""
            try:
                sock.sendall(b"HTTP/1.1 200 OK\r\n")
                for number in range(40):
                    time.sleep(0.05)
                    sock.sendall(b"X-Slow-%d: 1\r\n" % number)
                sock.sendall(b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
            except OSError:
                pass
            return False

        upstream = FakeUpstream(slow_headers)
        self.addCleanup(upstream.close)
        port = upstream.server.server_address[1]
        self.keepalive = self.make(
            lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
        self.busy_main()
        self.exchange(AGENT_P)
        [ping] = self.due(270)
        with mock.patch.object(cache_keepalive, "PING_TIMEOUT", 0.3):
            began = time.monotonic()
            self.keepalive.send(ping)
            self.assertLess(time.monotonic() - began, 1.5)
        [line] = self.events("ping")
        self.assertEqual((line["status"], line["outcome"], line["error"]),
                         (200, "upstream_error", "ping exceeded 0.3 s"))
        self.assertNotIn("usage", line)
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "ping_failed", 1)])
        self.assertEqual(self.due(270), [])


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


class KeepaliveProxyTest(unittest.TestCase):
    """`ProxyServer` with a keepalive in front of `FakeUpstream` (D2, D9, D18, D24)."""

    def setUp(self):
        self.clock = FakeClock()
        self.stream = RecordingStream()
        self.log = cache_proxy.LineLog(self.stream)

    def start(self, responder, keepalive=None, reorder=None):
        fake = FakeUpstream(responder)
        self.addCleanup(fake.close)
        upstream = cache_proxy.parse_upstream(fake.url)
        if keepalive is None:
            keepalive = cache_keepalive.Keepalive(
                self.log, functools.partial(cache_proxy.open_upstream, upstream, None), self.clock)
        server = cache_proxy.ProxyServer(0, upstream, self.log, keepalive=keepalive, reorder=reorder)
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

    def test_with_the_reorder_the_ping_replays_the_reordered_body(self):
        value = fixture("sibling1-first.received.json")
        for holder in holders(value):
            if isinstance(holder.get("cache_control"), dict):
                holder["cache_control"].pop("ttl", None)
        value.pop("thinking", None)
        raw = encode(value)
        expected, _, outcome = subagent_prefix.SubagentPrefix().transform(
            "POST", MESSAGES, forwarded(AGENT_P, length=len(raw)), raw)
        self.assertEqual(outcome, "applied")
        self.assertEqual(cache_keepalive.classify(
            "POST", MESSAGES, forwarded(AGENT_P, length=len(expected)), expected).outcome, "tracked")
        fake, port, keepalive = self.start(sse_reply("tool_use"),
                                           reorder=subagent_prefix.SubagentPrefix())
        _, status, _ = self.send(port, AGENT_P, raw)
        self.assertEqual(status, 200)
        [(_, head, received)] = fake.requests
        self.assertEqual(received, expected)
        self.assertIn(b"Content-Length: %d" % len(expected), head.split(b"\r\n"))
        [record] = self.stream.records(1)
        self.assertEqual((record["reorder"], record["keepalive"]), ("applied", "tracked"))
        self.clock.advance(270)
        [ping] = keepalive.tick()
        self.assertEqual(json.loads(ping.body), dict(json.loads(expected), max_tokens=1))
        self.assertEqual([length for name, length in ping.headers if name == "Content-Length"],
                         [str(len(ping.body))])

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
        done = []

        class Track:
            outcome, conversation, stop_reason = "tracked", "0123456789ab", None

            def __init__(self, headers):
                self.headers = headers

            def started(self, status, content_type, content_encoding):
                pass

            def chunk(self, data):
                raise ValueError("tap")

            def done(self, outcome):
                done.append(outcome)

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
        self.assertEqual(done, ["track_error"])

    def test_a_dropped_track_ends_its_flight_so_the_session_can_go_idle(self):
        _, port, keepalive = self.start(sse_reply("end_turn"))
        with mock.patch.object(cache_keepalive.SseReader, "feed",
                               side_effect=RecursionError("deep")):
            _, status, body = self.send(port, AGENT_P, encode(document()))
        self.assertEqual((status, body), (200, sse("end_turn")))
        error, request = self.stream.records(2)
        self.assertEqual((error["event"], error["stage"], error["error"]),
                         ("keepalive_error", "track", "RecursionError: deep"))
        self.assertEqual(request["keepalive"], "untracked")
        self.clock.advance(270)
        self.assertEqual(keepalive.tick(), [])
        ends = [json.loads(line) for line in self.stream.lines if '"keepalive_end"' in line]
        self.assertEqual([(end["conversation"], end["reason"]) for end in ends],
                         [(cache_keepalive.conversation_handle(SESSION, AGENT_P), "session_idle")])

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


if __name__ == "__main__":
    unittest.main()
