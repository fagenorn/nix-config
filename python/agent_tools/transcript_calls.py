"""The shared Claude Code transcript reader (issues 421 and 432).

read_transcript makes one pass over a transcript and returns its calls (usage merged
per message ID, in first-line order, context above 0), its user entries, the first
attachment of each type, its tool results and the notes a PreToolUse:Bash hook
attached to a tool use. The cache report (agent_cache_report) and the owner report
read through it, and is_death is their one cache-death rule. python/README.md
(agent-costs) holds the contract.
"""

import json
from dataclasses import dataclass, field
from typing import NamedTuple

from agent_tools.agent_costs import parse_rfc3339_utc

# Prompt-cache lifetime by transcript kind: a root transcript (True) writes 1-hour
# entries, a subagent transcript (False) 5-minute ones.
TTL_SECONDS = {True: 3_600, False: 300}
TTL_SLACK_SECONDS = 10
MIN_DEATH_CONTEXT = 5_000
RESULT_TEXT_LIMIT = 65_536
BASH_HOOK_NAME = "PreToolUse:Bash"

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
class Call:
    first_line: int
    last_line: int
    start: object = None
    start_raw: str | None = None
    end: object = None
    model: str | None = None
    usage: dict = field(default_factory=_new_usage)
    tool_names: dict = field(default_factory=dict)
    tool_inputs: dict = field(default_factory=dict)

    @property
    def context(self):
        return (self.usage["input_tokens"] + self.usage["cache_read_input_tokens"]
                + self.usage["cache_creation_input_tokens"])


class ToolResult(NamedTuple):
    line: int
    text: str
    size: int
    ends_turn: bool


@dataclass
class Transcript:
    calls: list
    user_entries: list
    attachments: dict
    results: dict
    hook_notes: dict


def _count(value):
    """A usage field as a token count; anything but an int (a bool, float or null) reads as 0."""
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
        call = calls[key] = Call(first_line=line_no, last_line=line_no)
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
                if isinstance(block.get("input"), dict):
                    call.tool_inputs[block.get("id")] = block["input"]


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


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block["text"] for block in content
                         if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def _add_results(results, value, line_no):
    message = value.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    ends_turn = value.get("toolEndsTurn") is True
    for block in content:
        if (isinstance(block, dict) and block.get("type") == "tool_result"
                and isinstance(block.get("tool_use_id"), str)):
            text = _result_text(block.get("content"))
            results.setdefault(block["tool_use_id"], ToolResult(
                line_no, text[:RESULT_TEXT_LIMIT], len(text), ends_turn))


def _add_hook_note(hook_notes, body):
    if body.get("hookName") != BASH_HOOK_NAME or not isinstance(body.get("toolUseID"), str):
        return
    content = body.get("content")
    if not isinstance(content, list):
        return
    note = " ".join(item for item in content if isinstance(item, str))
    earlier = hook_notes.get(body["toolUseID"])
    hook_notes[body["toolUseID"]] = note if earlier is None else f"{earlier} {note}"


def _rendered_size(value):
    rendered = value.get("rendered")
    if not isinstance(rendered, list):
        return None
    return sum(len(item["content"]) for item in rendered
               if isinstance(item, dict) and isinstance(item.get("content"), str))


def read_transcript(handle):
    """One pass over the transcript: its calls, user entries, attachments, results, hook notes.

    `attachments` maps each attachment type to `(line, rendered size)` of its first record.
    """
    calls, user_entries, attachments, results, hook_notes = {}, [], {}, {}, {}
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
            _add_results(results, value, line_no)
        elif kind == "attachment":
            body = value.get("attachment")
            name = body.get("type") if isinstance(body, dict) else None
            if isinstance(name, str) and name not in attachments:
                attachments[name] = (line_no, _rendered_size(value))
            if name == "hook_additional_context":
                _add_hook_note(hook_notes, body)
    ordered = sorted(calls.values(), key=lambda call: call.first_line)
    return Transcript([call for call in ordered if call.context > 0], user_entries,
                      attachments, results, hook_notes)


def is_death(prev, call, ttl):
    if prev.context <= MIN_DEATH_CONTEXT or prev.end is None or call.start is None:
        return False
    gap = (call.start - prev.end).total_seconds()
    return (gap > ttl - TTL_SLACK_SECONDS
            and 2 * call.usage["cache_creation_input_tokens"] > prev.context)
