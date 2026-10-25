"""Keepalive pings for idle subagent conversations behind `cache-proxy --keepalive` (#423).

`classify` sorts each forwarded request into one outcome of `OUTCOMES`; `ping_body` and
`ping_headers` rebuild a candidate request as its `max_tokens=1` replay; `SseReader` reads a
streamed response's `stop_reason` and usage.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

from agent_tools.canonical import (
    reject_duplicate_keys,
    reject_nonfinite_literal,
    telemetry_digest,
)

OUTCOMES = ("untracked", "main", "unparsed", "no_tail_mark", "ttl_1h", "thinking_budget",
            "tracked")
MESSAGES_PATH = "/v1/messages"
SESSION_HEADER = "X-Claude-Code-Session-Id"
AGENT_HEADER = "x-claude-code-agent-id"
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                "output_tokens", "cache_creation")

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
