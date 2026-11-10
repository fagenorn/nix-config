"""Reorder a subagent's first user message so sibling subagents share a cached prefix (#429).

`SubagentPrefix().transform(method, path, headers, body)` returns the body and header list to
forward and an outcome from `OUTCOMES`. For a Claude Code subagent's `POST /v1/messages` it moves
the delegation prompt in `messages[0]` after the `<system-reminder>` attachments that follow it,
keeps any `<total_tokens>` budget line that followed the prompt after it, and, while the body
holds fewer than four cache breakpoints, marks the block just before the prompt as one. A
subagent's later turns are reordered only once its first request was, so a forked subagent keeps
its parent's prefix. Every other request, and every body of another shape, comes back as the
bytes and headers it arrived with.

Which requests. A `POST` to `/v1/messages` (any query) with a non-empty `x-claude-code-agent-id`
is parsed as strict JSON (a duplicate key or `NaN` is `unparsed`); every other request is
`not_subagent` and is never parsed, and so is a body whose `system[0]` is not a text block
starting `x-anthropic-billing-header:` with `cc_is_subagent=true` among its `;`-separated fields.
A request with no assistant message is a first request, and its agent id is registered when it is
reordered (in memory, at most 4,096 ids, oldest out first, forgotten on restart); a later request
is reordered only when its id is registered, so a forked subagent, which carries its parent's
first message, passes as `unregistered`.

Shape. The reorder needs `messages[0]` to be a user message of text blocks: attachments (text
starting `<system-reminder>`), budget lines (whole text `<total_tokens>N tokens left</total_tokens>`,
`N` digits or `Infinite`) and exactly one other block, the prompt, which is not first. Only its
last block may carry a `cache_control`, and the body's marks (on `tools`, `system`, each message
block after its inner content, then a top-level one) number at most four, are objects with a
`ttl` of `5m` (the default) or `1h`, and never grow longer in prefix order; anything else is
`shape`.

Output. The output keeps every block before the prompt and every attachment after it in order,
then the prompt, then the budget lines that followed it, and a mark on the original last block
moves to the new last block. With fewer than four marks, the block just before the prompt gains
`{"type":"ephemeral"}` with the `ttl` of the nearest mark after it, else of the nearest before
it, else none (`applied`); with four, nothing is added (`applied_at_cap`). No existing mark is
retimed or removed, and the billing header is never changed. A reordered body is re-encoded as
compact UTF-8 JSON in its key order, with every `Content-Length` value replaced; every other
outcome forwards the client's bytes and headers.

Where it runs. The transform runs after the upstream headers are assembled and before the
keepalive's observation, so a keepalive candidate and its pings carry the reordered body.

Log lines. With `--reorder`, the `listening` line gains `"reorder":true` and each `request` line
that reached the transform gains `reorder`: `applied`, `applied_at_cap`, `not_subagent`,
`unregistered`, `unparsed`, `shape` or `error`. A request rejected while its body was read
(`411`, `400`) and the health path carry none. An exception from the transform, or an outcome
outside that set, forwards the original bytes and headers and is logged at once as a
`reorder_error` line with `method`, `path` and `error`. Without the flag no transform object
exists, and every byte sent upstream and every log line is as `agent_tools.hosts.cache_proxy`
describes.

"""

from __future__ import annotations

from collections import OrderedDict
import json
import re
import threading
from urllib.parse import urlsplit

from agent_tools.hosts.cache_keepalive import AGENT_HEADER, Headers, header_value
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

MESSAGES_PATH = "/v1/messages"
BILLING_PREFIX = "x-anthropic-billing-header:"
SUBAGENT_FIELD = "cc_is_subagent=true"
ATTACHMENT_PREFIX = "<system-reminder>"
BUDGET_LINE = re.compile(r"<total_tokens>(?:[0-9]+|Infinite) tokens left</total_tokens>")
MAX_MARKS = 4  # the API's breakpoint limit; a top-level cache_control takes one slot
TTL_RANK = {"5m": 0, "1h": 1}
DEFAULT_TTL = "5m"
REGISTRY_CAPACITY = 4096
REWRITTEN = frozenset({"applied", "applied_at_cap"})
OUTCOMES = REWRITTEN | {"not_subagent", "unregistered", "unparsed", "shape"}


def _encode(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _decode(body: bytes):
    """The body as a JSON object that re-encodes, or None (`unparsed`)."""
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
        if isinstance(value, dict):
            _encode(value)
            return value
    except (ValueError, RecursionError):  # UnicodeError is a ValueError
        pass
    return None


def _is_subagent(value) -> bool:
    system = value.get("system")
    block = system[0] if isinstance(system, list) and system else None
    text = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None
    if not isinstance(text, str) or not text.startswith(BILLING_PREFIX):
        return False
    return SUBAGENT_FIELD in {field.strip() for field in text[len(BILLING_PREFIX):].split(";")}


def _has_assistant(value) -> bool:
    messages = value.get("messages")
    return isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "assistant" for message in messages)


def _holders(value) -> list:
    """Every object whose `cache_control` is a breakpoint, in prefix order (D14, D16)."""
    holders = []
    for key in ("tools", "system"):
        items = value.get(key)
        if isinstance(items, list):
            holders.extend(item for item in items if isinstance(item, dict))
    messages = value.get("messages")
    for message in messages if isinstance(messages, list) else ():
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict):
                inner = block.get("content")
                if isinstance(inner, list):  # a block's inner content precedes its own mark
                    holders.extend(item for item in inner if isinstance(item, dict))
                holders.append(block)
    holders.append(value)  # a top-level cache_control (automatic caching) sits last
    return holders


def _marks(holders) -> list:
    return [holder["cache_control"] for holder in holders if "cache_control" in holder]


def _marks_valid(marks) -> bool:
    """At most four marks, each an object with a known TTL, none longer than one before it."""
    if len(marks) > MAX_MARKS:
        return False
    ranks = []
    for mark in marks:
        ttl = mark.get("ttl", DEFAULT_TTL) if isinstance(mark, dict) else None
        if not isinstance(ttl, str) or ttl not in TTL_RANK:
            return False
        ranks.append(TTL_RANK[ttl])
    return all(earlier >= later for earlier, later in zip(ranks, ranks[1:]))


def _kind(text: str) -> str:
    if text.startswith(ATTACHMENT_PREFIX):
        return "attachment"
    return "budget" if BUDGET_LINE.fullmatch(text) else "prompt"


def _reorder(value) -> str | None:
    """Reorder `value` in place and return the outcome, or None (`shape`) before any change."""
    messages = value.get("messages")
    first = messages[0] if isinstance(messages, list) and messages else None
    if not isinstance(first, dict) or first.get("role") != "user":
        return None
    content = first.get("content")
    if not isinstance(content, list) or not all(
            isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) for block in content):
        return None
    kinds = [_kind(block["text"]) for block in content]
    if kinds.count("prompt") != 1 or kinds[0] == "prompt":
        return None
    if any("cache_control" in block for block in content[:-1]):
        return None
    marks = _marks(_holders(value))
    if not _marks_valid(marks):
        return None
    index = kinds.index("prompt")
    later = list(zip(content[index + 1:], kinds[index + 1:]))
    attachments = [block for block, kind in later if kind == "attachment"]
    reordered = (content[:index] + attachments + [content[index]]
                 + [block for block, kind in later if kind == "budget"])
    if reordered[-1] is not content[-1] and "cache_control" in content[-1]:
        reordered[-1]["cache_control"] = content[-1].pop("cache_control")
    first["content"] = reordered
    if len(marks) == MAX_MARKS:
        return "applied_at_cap"
    target = reordered[index + len(attachments) - 1]  # the block just before the prompt
    holders = _holders(value)
    position = next(i for i, holder in enumerate(holders) if holder is target)
    following, preceding = _marks(holders[position + 1:]), _marks(holders[:position])
    source = following[0] if following else preceding[-1] if preceding else None
    mark = {"type": "ephemeral"}
    if source is not None and "ttl" in source:
        mark["ttl"] = source["ttl"]
    target["cache_control"] = mark
    return "applied"


def _with_length(headers: Headers, length: int) -> Headers:
    return [(name, str(length)) if name.lower() == "content-length" else (name, value)
            for name, value in headers]


class SubagentPrefix:
    """The reorder, plus the registry of agent ids whose first request it reordered (D13)."""

    def __init__(self, capacity: int = REGISTRY_CAPACITY):
        self.capacity = capacity
        self._registry: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def transform(self, method: str, path: str, headers: Headers,
                  body: bytes) -> tuple[bytes, Headers, str]:
        """`(body, headers, outcome)` to forward. Outside `REWRITTEN` the body and headers are
        the very objects passed in; a rewrite returns new bytes and a new header list whose every
        `Content-Length` value is the new length, each header keeping its name and place."""
        agent_id = header_value(headers, AGENT_HEADER)
        if method != "POST" or urlsplit(path).path != MESSAGES_PATH or agent_id is None:
            return body, headers, "not_subagent"
        value = _decode(body)
        if value is None:
            return body, headers, "unparsed"
        if not _is_subagent(value):
            return body, headers, "not_subagent"
        first_request = not _has_assistant(value)
        if not first_request and not self._registered(agent_id):
            return body, headers, "unregistered"
        outcome = _reorder(value)
        if outcome is None:
            return body, headers, "shape"
        if first_request:
            self._register(agent_id)
        forwarded = _encode(value)
        return forwarded, _with_length(headers, len(forwarded)), outcome

    def _registered(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._registry

    def _register(self, agent_id: str) -> None:
        with self._lock:
            self._registry[agent_id] = None
            self._registry.move_to_end(agent_id)
            while len(self._registry) > self.capacity:
                self._registry.popitem(last=False)
