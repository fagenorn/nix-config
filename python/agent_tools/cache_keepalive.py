"""Keepalive pings for idle subagent conversations behind `cache-proxy --keepalive` (#423).

`--keepalive` keeps a subagent conversation's prompt cache warm while it is idle, by replaying
its last request with `max_tokens=1`. A conversation is a pair of the `X-Claude-Code-Session-Id`
and `x-claude-code-agent-id` headers. `classify` sorts each `POST /v1/messages` the proxy is about
to forward into one outcome of `OUTCOMES`; `ping_body` and `ping_headers` rebuild a candidate
request as its `max_tokens=1` replay; `SseReader` reads a streamed response's `stop_reason` and
usage.

Outcomes. `untracked` (not a messages `POST`, or no session header), `main` (no agent header: the
main conversation) and `unparsed` (the body is not a strict JSON object, or arrives with a
`Content-Encoding`) are not candidates. `no_tail_mark` (the last message carries no
`cache_control`), `ttl_1h` (some mark asks `ttl` `1h`) and `thinking_budget` (`thinking.type` is
`enabled`) are subagent requests that are left alone as well. `tracked` is a subagent request that
can be replayed. A `no_tail_mark` request is a side request (Claude Code's forks and side queries
look like this), and a request with any other outcome but `untracked` is a thread request, its
conversation's own turn. A side request counts as session activity only while it is in flight:
whatever its `stop_reason`, it never clears or sets its conversation's pending tool, ends an idle
period, restarts the ceiling, moves the eviction order or supersedes a ping in flight.

Candidates. A `tracked` request whose response starts 2xx becomes its conversation's candidate (a
newer one replaces an older one; a candidate is held for at most `MAX_CANDIDATES` = 64
conversations, and the 65th evicts the one whose last thread request is oldest). A later 2xx
`unparsed`, `ttl_1h` or `thinking_budget` request clears it; `main` and `no_tail_mark` requests
leave it as it is. Every request with an outcome other than `untracked` is forwarded with
`Accept-Encoding: identity`, and its response chunks are tapped, after they have been written to
the client, by an incremental SSE reader that keeps the final `stop_reason`; the bytes the client
gets are unchanged. The candidate's headers, `authorization` among them, are held in process
memory only, from its 2xx response start until it is cleared, replaced or ended; they are never
logged or written anywhere, and a proxy restart forgets every conversation.

Activity. A session counts as active for a candidate when one of its conversations has a request
in flight (under 60 minutes old, side requests included), is pending a tool (the 2xx response to
its newest thread request completed with `stop_reason` `tool_use`, under 60 minutes ago), or has
sent a thread request since the candidate's last touch; pings never count. A conversation's last
reply is the `stop_reason` the tap read from the 2xx response to its newest thread request once
that response completed; it has none while that response streams, or when the response was not
2xx, was cut short or carried no `stop_reason` the tap could read, and a side request never sets
or clears it.

Ticks. A tick every `TICK_INTERVAL` = 5 s finds each candidate untouched for `DUE_AFTER` = 270 s
(the touch is the upstream send time of its last 2xx `tracked` request or ping). It ends the
conversation with `ceiling` when 60 minutes (`WINDOW`) have passed since its last thread request,
with `session_idle` when the session is not active, with `end_turn_cap` when its last reply was
`end_turn` and its idle period already holds at least `END_TURN_PINGS` = 2 pings (the pings sent
since its last thread request, those sent while that reply streamed included), checked in that
order, and otherwise sends the ping.

Pings. A ping travels on a fresh upstream connection (never a client's) with a `PING_TIMEOUT` =
30 s socket timeout and is never retried; its response is read to the end, its usage logged, and
the bytes discarded. The whole exchange is also bounded by that 30 s from the ping's send time,
checked on the keepalive's clock between reads and enforced by a wall-clock watchdog that shuts
the ping connection's socket, so a read still blocked ends too, the response's headers and chunk
framing included: once it has passed, the read stops, no usage is parsed, the connection is
closed and the `ping` line reads `upstream_error` with `error` `ping exceeded 30.0 s`, so a
response that keeps trickling bytes cannot hold a ping, or its conversation's credentials, in
flight. The ping keeps the candidate's headers, `Accept-Encoding: identity` and a recomputed
`Content-Length` included, and its body is the candidate's with `max_tokens` set to `1` and
nothing else changed. Only a 2xx ping whose body was read whole (outcome `complete`) becomes the
new touch; any other result (a non-2xx status, an upstream error such as a timeout or a
connection failure, a body cut short of its declared length, or the overall bound) ends the
conversation with `ping_failed`, and a ping superseded by a newer thread request of its
conversation while in flight changes nothing.

End reasons (`END_REASONS`). A thread request that arrives after at least one ping ends that idle
period with `resumed`; the others are `ceiling`, `session_idle`, `end_turn_cap`, `ping_failed`
and `evicted`.

Log lines. With the flag, the `listening` line gains `"keepalive":true`, and each `request` line
that reached the keepalive gains `keepalive` (the outcome) and, unless it is `untracked`,
`conversation` (12 hex digits of the `telemetry_digest` of the session and agent, never a header
value) and the `stop_reason` the tap saw. A request rejected while its body was read (`411`,
`400`) and the health path carry none of these. Three events are new: `ping` (`conversation`,
`model`, `idle_s`, `status`, `ttfb_ms`, `duration_ms`, `outcome`, `usage` and, on failure, `error`
and up to 4 KiB of an error body), `keepalive_end` (`conversation`, `reason`, `pings` and
`idle_s`) and `keepalive_error` (`stage` `observe`, `track`, `tick` or `send`, and `error`).

Failure. A keepalive bug never blocks traffic: an exception from `observe`, a track call, `tick`
or `send` is one `keepalive_error` line, the request carries `"keepalive":"untracked"`, and the
scheduler keeps running. When `observe` raises, the request is forwarded exactly as it would be
without the flag; when a later track call raises, the track is dropped and the request continues
untracked, its headers already sent as the track gave them (`Accept-Encoding: identity`); a
dropped track is still told its request is done (unless `done` itself raised), so its flight
never keeps the session active. Without the flag no keepalive object exists, no thread runs, and
every byte sent upstream and every log line is as `agent_tools.cache_proxy` describes.

`Keepalive` holds each subagent conversation's candidate request, `tick` returns the pings now
due, `send` sends one, and `run` is the production loop, which only a command's `main` starts.

"""

import http.client
import json
import socket
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agent_tools.canonical import (
    reject_duplicate_keys,
    reject_nonfinite_literal,
    telemetry_digest,
)
from agent_tools.cache_proxy import ERROR_BODY_LIMIT, READ_SIZE, UPSTREAM_FAILURES

OUTCOMES = ("untracked", "main", "unparsed", "no_tail_mark", "ttl_1h", "thinking_budget",
            "tracked")
MESSAGES_PATH = "/v1/messages"
SESSION_HEADER = "X-Claude-Code-Session-Id"
AGENT_HEADER = "x-claude-code-agent-id"
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                "output_tokens", "cache_creation")

END_REASONS = ("resumed", "ceiling", "session_idle", "ping_failed", "evicted", "end_turn_cap")
DUE_AFTER = 270.0
TICK_INTERVAL = 5.0
WINDOW = 3600.0
# An idle period whose conversation's last reply was `end_turn` ends `end_turn_cap` at the first
# due time at which it holds this many pings. Two keep the cache about 14 minutes past the request
# (2 x 270 s, then the 5-minute lifetime) and gave the best net saving on mbp's proxy log for
# 2026-10-26..11-01 (issue 502 D2).
END_TURN_PINGS = 2
MAX_CANDIDATES = 64
PING_TIMEOUT = 30.0

Headers = list[tuple[str, str]]


def header_value(headers: Headers, name: str) -> str | None:
    """The first value of `name` (case-insensitive); an empty value counts as absent."""
    wanted = name.lower()
    for header, value in headers:
        if header.lower() == wanted:
            return value or None
    return None


def conversation_handle(session: str, agent: str | None) -> str:
    """Twelve hex digits of the canonical digest of the identity, safe to log (#422 D8)."""
    digest = telemetry_digest({"agent": agent, "session": session})
    return digest.removeprefix("sha256:")[:12]


@dataclass(frozen=True)
class Classification:
    outcome: str
    session: str | None = None
    agent: str | None = None
    model: str | None = None


def _strict_object(body: bytes) -> dict | None:
    try:
        value = json.loads(body, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except ValueError:  # UnicodeDecodeError is a ValueError
        return None
    return value if isinstance(value, dict) else None


def _marks(value: dict) -> Iterator[dict]:
    """Every `cache_control` object at a place the request body can carry one (D16)."""
    def mark_of(item: object) -> Iterator[dict]:
        if isinstance(item, dict) and isinstance(item.get("cache_control"), dict):
            yield item["cache_control"]

    yield from mark_of(value)
    for key in ("tools", "system"):
        items = value.get(key)
        if isinstance(items, list):
            for item in items:
                yield from mark_of(item)
    messages = value.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            yield from mark_of(block)
            inner = block.get("content") if isinstance(block, dict) else None
            if isinstance(inner, list):
                for item in inner:
                    yield from mark_of(item)


def _tail_marks(value: dict) -> list[dict]:
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict):
        return []
    return list(_marks({"messages": [messages[-1]]}))


def classify(method: str, path: str, headers: Headers, body: bytes) -> Classification:
    """Sort a forwarded request into the first matching outcome of `OUTCOMES` (D5)."""
    session = header_value(headers, SESSION_HEADER)
    agent = header_value(headers, AGENT_HEADER)
    if method != "POST" or urlsplit(path).path != MESSAGES_PATH or session is None:
        return Classification("untracked", session, agent)
    if agent is None:
        return Classification("main", session)
    value = None if header_value(headers, "Content-Encoding") is not None \
        else _strict_object(body)
    if value is None:
        return Classification("unparsed", session, agent)
    model = value.get("model")
    model = model if isinstance(model, str) else None

    def result(outcome: str) -> Classification:
        return Classification(outcome, session, agent, model)

    if not _tail_marks(value):
        return result("no_tail_mark")
    if any(mark.get("ttl") == "1h" for mark in _marks(value)):
        return result("ttl_1h")
    thinking = value.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return result("thinking_budget")
    return result("tracked")


def ping_body(body: bytes) -> bytes:
    """The request body with its top-level `max_tokens` set to 1 (D6, D20)."""
    value = _strict_object(body)
    if value is None:
        raise ValueError("ping body is not a strict JSON object")
    value["max_tokens"] = 1
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _set_header(headers: Headers, name: str, value: str) -> Headers:
    """A copy with the first `name` header set to `value`, later ones dropped, or appended."""
    wanted = name.lower()
    result: Headers = []
    seen = False
    for header, current in headers:
        if header.lower() != wanted:
            result.append((header, current))
        elif not seen:
            result.append((header, value))
            seen = True
    if not seen:
        result.append((name, value))
    return result


def identity_headers(headers: Headers) -> Headers:
    return _set_header(headers, "Accept-Encoding", "identity")


def ping_headers(headers: Headers, length: int) -> Headers:
    return _set_header(identity_headers(headers), "Content-Length", str(length))


class SseReader:
    """Reads `stop_reason` and usage from a streamed Messages response, chunk by chunk.

    Holds only the unterminated line, the event name and one `message_*` event's data lines.
    """

    def __init__(self) -> None:
        self.stop_reason: str | None = None
        self.usage: dict = {}
        self._line = b""
        self._event = ""
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> None:
        *lines, self._line = (self._line + chunk).split(b"\n")
        for line in lines:
            self._read_line(line.removesuffix(b"\r").decode("utf-8", "replace"))

    def _read_line(self, line: str) -> None:
        if not line:
            self._dispatch()
        elif line.startswith(":"):
            return
        elif line.startswith("event:"):
            self._event = line[len("event:"):].removeprefix(" ")
        elif line.startswith("data:") and self._event.startswith("message_"):
            self._data.append(line[len("data:"):].removeprefix(" "))

    def _dispatch(self) -> None:
        event, data, self._event, self._data = self._event, self._data, "", []
        if not data:
            return
        try:
            value = json.loads("\n".join(data))
        except ValueError:
            return
        if not isinstance(value, dict):
            return
        if event == "message_start":
            message = value.get("message")
            self._merge(message.get("usage") if isinstance(message, dict) else None)
        elif event == "message_delta":
            self._merge(value.get("usage"))
            delta = value.get("delta")
            reason = delta.get("stop_reason") if isinstance(delta, dict) else None
            if isinstance(reason, str):
                self.stop_reason = reason

    def _merge(self, usage: object) -> None:
        if isinstance(usage, dict):
            self.usage.update({key: usage[key] for key in USAGE_FIELDS if key in usage})


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _media_type(content_type: str | None) -> str:
    return (content_type or "").partition(";")[0].strip().lower()


def _is_stream(status: int, content_type: str | None, content_encoding: str | None) -> bool:
    """Whether a response is a plain-bytes event stream a `SseReader` can read."""
    return (200 <= status < 300 and _media_type(content_type) == "text/event-stream"
            and (content_encoding or "identity").strip().lower() == "identity")


@dataclass(eq=False)
class _Candidate:
    method: str
    path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    model: str | None
    touch: float


@dataclass(eq=False)
class _Conversation:
    session: str
    agent: str | None
    handle: str
    in_flight: dict["Track", float] = field(default_factory=dict)
    last_request: float | None = None
    pending_since: float | None = None
    last_reply: str | None = None
    epoch: int = 0
    applied: int = 0
    pings: int = 0
    candidate: _Candidate | None = None
    ping: "Ping | None" = None


@dataclass(frozen=True, eq=False)
class Ping:
    """One keepalive request, due now. Headers and body hold credentials and are never shown."""

    conversation: str
    method: str
    path: str
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    body: bytes = field(repr=False)
    model: str | None
    idle_s: float
    _record: _Conversation = field(repr=False)
    _candidate: _Candidate = field(repr=False)
    _epoch: int


class Track:
    """What the proxy tells `Keepalive` about one client request, from its first byte to its end.

    A track of an untracked request has no owner and ignores every call. A side request's track
    (`no_tail_mark`) has no sequence: it holds no place in its conversation's request order, so it
    never marks a tool pending, never sets its conversation's last reply and never supersedes a
    ping.
    """

    def __init__(self, headers: Headers, owner: "Keepalive | None" = None, outcome: str = "untracked",
                 record: _Conversation | None = None, sequence: int | None = None, sent: float = 0.0,
                 candidate: _Candidate | None = None) -> None:
        self.outcome = outcome
        self.conversation = record.handle if record else None
        self.headers = headers
        self.stop_reason: str | None = None
        self._owner = owner
        self._record = record
        self._sequence = sequence
        self._sent = sent
        self._candidate = candidate
        self._status: int | None = None
        self._reader: SseReader | None = None
        self._finished = False

    def started(self, status: int, content_type: str | None, content_encoding: str | None) -> None:
        if self._owner is not None:
            self._owner._started(self, status, _is_stream(status, content_type, content_encoding))

    def chunk(self, data: bytes) -> None:
        if self._reader is not None:
            self._reader.feed(data)

    def done(self, outcome: str) -> None:
        if self._owner is not None:
            self._owner._done(self, outcome)

    def log_fields(self) -> dict:
        if self._owner is None:
            return {"keepalive": "untracked"}
        fields = {"keepalive": self.outcome, "conversation": self.conversation}
        if self.stop_reason is not None:
            fields["stop_reason"] = self.stop_reason
        return fields


@dataclass
class _PingResult:
    status: int | None = None
    ttfb_ms: float | None = None
    outcome: str = "complete"
    error: str | None = None
    error_body: bytes = b""
    usage: dict = field(default_factory=dict)


class Keepalive:
    """Candidate requests per subagent conversation, and the pings that keep them cached (D2).

    One lock guards all state; no method holds it across network I/O.
    """

    def __init__(self, log, connect: Callable[[float], http.client.HTTPConnection],
                 clock: Callable[[], float]) -> None:
        self._log = log
        self._connect = connect
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str | None, _Conversation]] = {}

    def observe(self, method: str, path: str, headers: Headers, body: bytes) -> Track:
        """Classify one request and, unless it is `untracked`, register its flight.

        A thread request (any other outcome but `no_tail_mark`) is its conversation's next turn:
        it ends a pinged idle period `resumed`, stamps the last request, advances the sequence and
        clears a pending tool and the last reply. A side request (`no_tail_mark`) does none of
        these, so it counts as session activity only while it is in flight (issue 501)."""
        verdict = classify(method, path, headers, body)
        if verdict.outcome == "untracked":
            return Track(headers)
        sent_headers = identity_headers(headers)
        with self._lock:
            now = self._clock()
            record = self._conversation(verdict.session, verdict.agent)
            sequence = None
            if verdict.outcome != "no_tail_mark":
                if record.pings > 0:
                    self._log_end(record, "resumed", now)
                record.last_request = now
                record.epoch += 1
                record.pending_since = None
                record.last_reply = None
                sequence = record.epoch
            candidate = None
            if verdict.outcome == "tracked":
                candidate = _Candidate(method, path, tuple(sent_headers), body, verdict.model, now)
            track = Track(sent_headers, self, verdict.outcome, record, sequence, now, candidate)
            record.in_flight[track] = now
            return track

    def tick(self) -> list[Ping]:
        """The pings now due. At its due time a candidate's conversation ends `ceiling` or
        `session_idle` when their rules apply, else `end_turn_cap` when its last reply was
        `end_turn` and its idle period already holds `END_TURN_PINGS` pings or more; otherwise it
        is pinged."""
        now = self._clock()
        pings = []
        with self._lock:
            self._prune(now)
            for record in self._records():
                candidate = record.candidate
                if candidate is None or record.ping is not None or now - candidate.touch < DUE_AFTER:
                    continue
                if now - record.last_request >= WINDOW:
                    self._end(record, "ceiling", now)
                elif not self._active(record, now):
                    self._end(record, "session_idle", now)
                elif record.last_reply == "end_turn" and record.pings >= END_TURN_PINGS:
                    self._end(record, "end_turn_cap", now)
                else:
                    pings.append(self._build_ping(record, candidate, now))
        return pings

    def send(self, ping: Ping) -> None:
        sent = self._clock()
        result = _PingResult()
        try:
            self._exchange(ping, sent, result)
        except UPSTREAM_FAILURES as error:
            result.outcome, result.error = "upstream_error", _describe(error)
        except Exception:
            self._settle(ping, sent, False)
            raise
        self._log_ping(ping, sent, result)
        self._settle(ping, sent, 200 <= (result.status or 0) < 300 and result.outcome == "complete")

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(TICK_INTERVAL):
            try:
                pings = self.tick()
            except Exception as error:
                self._log.write("keepalive_error", stage="tick", error=_describe(error))
                continue
            for ping in pings:
                threading.Thread(target=self._send_logged, args=(ping,), daemon=True).start()

    def _send_logged(self, ping: Ping) -> None:
        try:
            self.send(ping)
        except Exception as error:
            self._log.write("keepalive_error", stage="send", error=_describe(error))

    def _conversation(self, session: str, agent: str | None) -> _Conversation:
        agents = self._sessions.setdefault(session, {})
        if agent not in agents:
            agents[agent] = _Conversation(session, agent, conversation_handle(session, agent))
        return agents[agent]

    def _records(self) -> list[_Conversation]:
        return [record for agents in self._sessions.values() for record in agents.values()]

    def _prune(self, now: float) -> None:
        def old(stamp: float | None) -> bool:
            return stamp is None or now - stamp >= WINDOW

        for session, agents in list(self._sessions.items()):
            for agent, record in list(agents.items()):
                record.in_flight = {track: sent for track, sent in record.in_flight.items()
                                    if now - sent < WINDOW}
                if (record.candidate is None and record.ping is None and not record.in_flight
                        and old(record.last_request) and old(record.pending_since)):
                    del agents[agent]
            if not agents:
                del self._sessions[session]

    def _active(self, record: _Conversation, now: float) -> bool:
        """Some conversation of the session has a request in flight, a pending tool or a thread
        request newer than this candidate's last touch (D8)."""
        for other in self._sessions[record.session].values():
            if (any(now - sent < WINDOW for sent in other.in_flight.values())
                    or (other.pending_since is not None and now - other.pending_since < WINDOW)
                    or (other.last_request is not None
                        and other.last_request > record.candidate.touch)):
                return True
        return False

    def _build_ping(self, record: _Conversation, candidate: _Candidate, now: float) -> Ping:
        body = ping_body(candidate.body)
        headers = tuple(ping_headers(list(candidate.headers), len(body)))
        ping = Ping(record.handle, candidate.method, candidate.path, headers, body,
                    candidate.model, round(now - record.last_request, 1),
                    record, candidate, record.epoch)
        record.ping = ping
        record.pings += 1
        return ping

    def _log_end(self, record: _Conversation, reason: str, now: float) -> None:
        if reason not in END_REASONS:
            raise ValueError(f"unknown keepalive end reason {reason!r}")
        self._log.write("keepalive_end", conversation=record.handle, reason=reason,
                        pings=record.pings, idle_s=round(now - record.last_request, 1))
        record.pings = 0

    def _end(self, record: _Conversation, reason: str, now: float) -> None:
        self._log_end(record, reason, now)
        record.candidate = None

    def _started(self, track: Track, status: int, streamed: bool) -> None:
        with self._lock:
            track._status = status
            if 200 <= status < 300:
                self._apply(track, self._clock())
        if streamed:
            track._reader = SseReader()

    def _apply(self, track: Track, now: float) -> None:
        """The effect of a 2xx response on its conversation's candidate (D5, D19, D23, D27)."""
        record = track._record
        match track.outcome:
            case "main" | "no_tail_mark":
                return
            case "tracked" | "unparsed" | "ttl_1h" | "thinking_budget":
                if track._sequence < record.applied:
                    return
                record.applied = track._sequence
                if track.outcome != "tracked":
                    record.candidate = None
                    return
                if record.candidate is None:
                    held = [other for other in self._records() if other.candidate is not None]
                    if len(held) >= MAX_CANDIDATES:
                        self._end(min(held, key=lambda other: other.last_request), "evicted", now)
                record.candidate = track._candidate
            case other:
                raise ValueError(f"unhandled keepalive outcome {other!r}")

    def _done(self, track: Track, outcome: str) -> None:
        """End a request's flight. A completed 2xx response to its conversation's newest thread
        request sets the last reply to its `stop_reason` (`None` when the tap read none), and a
        `tool_use` one also marks a tool pending."""
        with self._lock:
            if track._finished:
                return
            track._finished = True
            record = track._record
            record.in_flight.pop(track, None)
            if outcome == "complete" and track._reader is not None:
                track.stop_reason = track._reader.stop_reason
            if (track._status is not None and 200 <= track._status < 300 and outcome == "complete"
                    and track._sequence == record.epoch):
                record.last_reply = track.stop_reason
                if track.stop_reason == "tool_use":
                    record.pending_since = self._clock()

    def _exchange(self, ping: Ping, sent: float, result: _PingResult) -> None:
        """Send the ping and read its response, for at most `PING_TIMEOUT` overall (D31, D32).

        A wall-clock watchdog shuts the connection's socket once `PING_TIMEOUT` has passed, which
        ends any read still blocked, the response's headers and chunk framing included."""
        connection = self._connect(PING_TIMEOUT)
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            if connection.sock is not None:
                try:
                    socket.socket.shutdown(connection.sock, socket.SHUT_RDWR)
                except OSError:
                    pass

        watchdog = threading.Timer(PING_TIMEOUT, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            connection.connect()
            if expired.is_set():
                raise TimeoutError("connected after the ping's bound")
            connection.putrequest(ping.method, ping.path, skip_host=True, skip_accept_encoding=True)
            for name, value in ping.headers:
                connection.putheader(name, value)
            connection.endheaders(ping.body)
            response = connection.getresponse()
            result.status = response.status
            result.ttfb_ms = round((self._clock() - sent) * 1000, 1)
            self._read(response, sent, result)
        except UPSTREAM_FAILURES:
            if not expired.is_set():
                raise
        finally:
            watchdog.cancel()
            connection.close()
        if expired.is_set():
            result.outcome, result.error = "upstream_error", f"ping exceeded {PING_TIMEOUT} s"
            result.usage = {}

    def _read(self, response: http.client.HTTPResponse, sent: float, result: _PingResult) -> None:
        """Read the ping's response to its end, for at most `PING_TIMEOUT` from `sent` on the
        keepalive's clock, checked between reads: the socket timeout bounds each read, not a body
        that keeps trickling bytes (D31); `_exchange`'s watchdog bounds a read still blocked."""
        content_type = response.getheader("Content-Type")
        reader = SseReader() if _is_stream(response.status, content_type,
                                           response.getheader("Content-Encoding")) else None
        whole = bytearray() if (200 <= response.status < 300
                                and _media_type(content_type) == "application/json") else None
        declared = None if response.chunked else response.length
        received = 0
        while True:
            if self._clock() - sent > PING_TIMEOUT:
                result.outcome = "upstream_error"
                result.error = f"ping exceeded {PING_TIMEOUT} s"
                return
            if not (chunk := response.read1(READ_SIZE)):
                break
            received += len(chunk)
            if reader is not None:
                reader.feed(chunk)
            if whole is not None:
                whole += chunk
            if response.status >= 400 and len(result.error_body) < ERROR_BODY_LIMIT:
                result.error_body += chunk[:ERROR_BODY_LIMIT - len(result.error_body)]
        if declared is not None and received != declared:
            result.outcome = "upstream_error"
            result.error = f"body ended after {received} of {declared} bytes"
            return
        if reader is not None:
            result.usage = reader.usage
        elif whole is not None:
            value = _strict_object(bytes(whole))
            usage = value.get("usage") if value is not None else None
            if isinstance(usage, dict):
                result.usage = {key: usage[key] for key in USAGE_FIELDS if key in usage}

    def _log_ping(self, ping: Ping, sent: float, result: _PingResult) -> None:
        fields = {"conversation": ping.conversation, "model": ping.model, "idle_s": ping.idle_s,
                  "status": result.status, "ttfb_ms": result.ttfb_ms,
                  "duration_ms": round((self._clock() - sent) * 1000, 1),
                  "outcome": result.outcome}
        if result.usage:
            fields["usage"] = result.usage
        if result.error is not None:
            fields["error"] = result.error
        if (result.status or 0) >= 400 and result.error_body:
            fields["error_body"] = result.error_body.decode("utf-8", "replace")
        self._log.write("ping", **fields)

    def _settle(self, ping: Ping, sent: float, succeeded: bool) -> None:
        with self._lock:
            record = ping._record
            if record.ping is not ping:
                return
            record.ping = None
            if record.candidate is not ping._candidate or record.epoch != ping._epoch:
                return
            if succeeded:
                record.candidate.touch = sent
            else:
                self._end(record, "ping_failed", self._clock())
