"""The cache report's per-transcript scanner (issue 421).

scan_transcript reads one Claude Code transcript and returns its calls in the
window, its cache deaths with their cause and premium, its cache-read cost above
a context threshold, its peak context and, for a subagent, its start-up overhead.
"""

import json
from dataclasses import dataclass, field

from agent_tools.agent_costs import (
    PRICING,
    cache_write_split,
    event_in_window,
    model_family,
    parse_rfc3339_utc,
)

DEFAULT_CONTEXT_THRESHOLD = 120_000
STARTUP_ATTACHMENTS = (
    "skill_listing",
    "instructions",
    "mcp_instructions_delta",
    "deferred_tools_delta",
    "agent_listing_delta",
    "environment",
)
# Prompt-cache lifetime by transcript kind: a root transcript (True) writes 1-hour
# entries, a subagent transcript (False) 5-minute ones.
TTL_SECONDS = {True: 3_600, False: 300}
TTL_SLACK_SECONDS = 10
MIN_DEATH_CONTEXT = 5_000

_RECORD_MARKERS = ('"type":"assistant"', '"type":"user"', '"type":"attachment"')
_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
_TTL_FIELDS = ("ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens")


def _new_usage():
    usage = dict.fromkeys(_USAGE_FIELDS, 0)
    usage["cache_creation"] = dict.fromkeys(_TTL_FIELDS, 0)
    return usage


@dataclass
class _Call:
    first_line: int
    last_line: int
    start: object = None
    start_raw: str | None = None
    end: object = None
    model: str | None = None
    usage: dict = field(default_factory=_new_usage)
    tool_names: dict = field(default_factory=dict)

    @property
    def context(self):
        return (self.usage["input_tokens"] + self.usage["cache_read_input_tokens"]
                + self.usage["cache_creation_input_tokens"])


def _count(value):
    """A usage field as a token count; a missing, null or non-numeric value reads as 0."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _merge_usage(merged, usage):
    for name in _USAGE_FIELDS:
        merged[name] = max(merged[name], _count(usage.get(name)))
    split = usage.get("cache_creation")
    if isinstance(split, dict):
        for name in _TTL_FIELDS:
            merged["cache_creation"][name] = max(merged["cache_creation"][name],
                                                 _count(split.get(name)))


def _add_assistant(calls, value, line_no):
    message = value.get("message")
    if not isinstance(message, dict):
        return
    key = message.get("id") or value.get("requestId") or value.get("uuid")
    if not key:
        return
    call = calls.get(key)
    if call is None:
        call = calls[key] = _Call(first_line=line_no, last_line=line_no)
    call.last_line = line_no
    try:
        stamp = parse_rfc3339_utc(value.get("timestamp"))
    except ValueError:
        stamp = None
    if stamp is not None:
        if call.start is None or stamp < call.start:
            call.start, call.start_raw = stamp, value["timestamp"]
        if call.end is None or stamp > call.end:
            call.end = stamp
    if call.model is None and isinstance(message.get("model"), str) and message["model"]:
        call.model = message["model"]
    usage = message.get("usage")
    if isinstance(usage, dict):
        _merge_usage(call.usage, usage)
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                call.tool_names[block.get("id")] = block.get("name")


def _waker_kind(origin):
    if isinstance(origin, dict):
        if origin.get("kind") == "peer" and origin.get("handback") is True:
            return "hand-back after end of turn"
        if origin.get("kind") == "task-notification":
            return "task notification after end of turn"
    return "message after end of turn"


def _user_entry(value, line_no):
    """A user record as ("result", line, tool_use_ids, ends_turn) or ("wake", line, kind)."""
    message = value.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        ids = [block.get("tool_use_id") for block in content
               if isinstance(block, dict) and block.get("type") == "tool_result"]
        if ids:
            return ("result", line_no, ids, value.get("toolEndsTurn") is True)
    return ("wake", line_no, _waker_kind(value.get("origin")))


def _rendered_size(value):
    rendered = value.get("rendered")
    if not isinstance(rendered, list):
        return None
    return sum(len(item["content"]) for item in rendered
               if isinstance(item, dict) and isinstance(item.get("content"), str))


def _read_records(handle):
    """One pass over the transcript: its calls, user entries and start-up attachments."""
    calls, user_entries, attachments = {}, [], {}
    for line_no, line in enumerate(handle):
        if not any(marker in line for marker in _RECORD_MARKERS):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        kind = value.get("type")
        if kind == "assistant":
            _add_assistant(calls, value, line_no)
        elif kind == "user":
            user_entries.append(_user_entry(value, line_no))
        elif kind == "attachment":
            body = value.get("attachment")
            name = body.get("type") if isinstance(body, dict) else None
            if name in STARTUP_ATTACHMENTS and name not in attachments:
                attachments[name] = (line_no, _rendered_size(value))
    ordered = sorted(calls.values(), key=lambda call: call.first_line)
    return [call for call in ordered if call.context > 0], user_entries, attachments


def _agent_type(path, is_root):
    if is_root:
        return "main"
    try:
        with open(path.with_name(path.stem + ".meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return "unknown"
    name = meta.get("agentType") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and name else "unknown"


def _counts(calls, since, before):
    """Per call, whether it is in the window; with no window every call counts."""
    if since is None and before is None:
        return [True] * len(calls)
    return [call.start_raw is not None
            and event_in_window(call.start_raw, since, before) is True for call in calls]


def _cause(prev, call, user_entries):
    """Death kind of `call`, from the user records between it and `prev` (D5, D12)."""
    between = [entry for entry in user_entries if prev.first_line < entry[1] < call.first_line]
    tool = None
    for entry in between:
        if entry[0] == "result" and not entry[3]:          # ("result", line, ids, ends_turn)
            for tool_id in entry[2]:
                if tool_id in prev.tool_names:
                    tool = prev.tool_names[tool_id]
    if tool is not None:
        if tool in ("Agent", "Task"):
            return "child dispatch"
        if tool == "Bash":
            return "long foreground command"
        return "other tool"
    for entry in between:
        if entry[0] == "wake":                              # ("wake", line, kind)
            return entry[2]
    return "unclassified"


def _premium(prev, call):
    """Rewrite cost beyond a warm read of the prefix that was cached (D6), in dollars."""
    _, _, p_1h, p_5m, p_read = PRICING[model_family(call.model)]
    cw_1h, cw_5m = cache_write_split(call.usage)
    write = (cw_1h * p_1h + cw_5m * p_5m) / (cw_1h + cw_5m)
    return min(call.usage["cache_creation_input_tokens"], prev.context) * (write - p_read) / 1e6


def _is_death(prev, call, ttl):
    if prev.context <= MIN_DEATH_CONTEXT or prev.end is None or call.start is None:
        return False
    gap = (call.start - prev.end).total_seconds()
    return (gap > ttl - TTL_SLACK_SECONDS
            and 2 * call.usage["cache_creation_input_tokens"] > prev.context)


def _deaths(calls, counts, user_entries, is_root):
    ttl = TTL_SECONDS[is_root]
    deaths = []
    for index in range(1, len(calls)):
        prev, call = calls[index - 1], calls[index]
        if counts[index] and _is_death(prev, call, ttl):
            deaths.append({
                "kind": _cause(prev, call, user_entries),
                "gap_s": (call.start - prev.end).total_seconds(),
                "premium": _premium(prev, call),
            })
    return deaths


def _reread_above(calls, counts, threshold):
    total = 0.0
    for call, counted in zip(calls, counts):
        if counted:
            p_read = PRICING[model_family(call.model)][4]
            total += max(0, call.usage["cache_read_input_tokens"] - threshold) * p_read / 1e6
    return total


def _startup(calls, counts, attachments, is_root):
    if is_root or not calls or not counts[0]:
        return None
    first = calls[0]
    cutoff = calls[1].first_line if len(calls) > 1 else None
    sizes = {name: size for name, (line_no, size) in attachments.items()
             if size is not None and (cutoff is None or line_no < cutoff)}
    return {
        "write": first.usage["cache_creation_input_tokens"],
        "read": first.usage["cache_read_input_tokens"],
        "attachments": {name: sizes[name] for name in STARTUP_ATTACHMENTS if name in sizes},
    }


def scan_transcript(job, *, since, before, threshold):
    """Scan one transcript `(path, is_root)`; None when it cannot be opened."""
    path, is_root = job
    try:
        with open(path, "r", errors="replace") as handle:
            calls, user_entries, attachments = _read_records(handle)
    except OSError:
        return None
    agent_type = _agent_type(path, is_root)
    counts = _counts(calls, since, before)
    counted = [call for call, flag in zip(calls, counts) if flag]
    return {
        "agent_type": agent_type,
        "is_root": is_root,
        "calls": len(counted),
        "deaths": _deaths(calls, counts, user_entries, is_root),
        "reread_above": _reread_above(calls, counts, threshold),
        "peak_ctx": max((call.context for call in counted), default=None),
        "startup": _startup(calls, counts, attachments, is_root),
    }
