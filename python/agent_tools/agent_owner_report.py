"""The agent-costs owner report (issue 432).

A transcript is an owner's when one of its Bash calls is a registering command (a
`workflow-state progress`/`mark-progress` or an `sdd-gate` carrying `--run-id` and
`--action-id`). One lineage collects the owner transcripts of a `(run_id, issue)`, and
every other transcript is attributed to its nearest owner through the `parentAgentId`
of its `.meta.json`. scan_owner_transcript reads one transcript through
agent_tools.transcript_calls and prices it through agent_tools.model_pricing; collect
assembles lineages, build_document projects them (with arms and projects, built by
agent_tools.agent_owner_rollup, fresh-owner boots, and the replay of
agent_tools.agent_owner_replay when asked) as the `agent-owner-report` document, and
print_document prints its tables.
With start windows, collect keeps the settled lineages that started in a window and counts
their whole spend. With a ping log, collect adds each counted lineage's keepalive pings to it and
counts the rest as unattributed. agent_costs.main runs the report for `--report owners`. python/README.md
(agent-costs) holds the contract.
"""

import functools
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from agent_tools import agent_owner_rollup
from agent_tools.agent_costs import (
    DISCLAIMER,
    event_in_window,
    find_sessions,
    format_rfc3339_utc,
    human,
    parse_rfc3339_utc,
    percentile,
    print_table,
    project_name,
    repo_root,
    scan_paths,
)
from agent_tools.cache_keepalive import conversation_handle
from agent_tools.context_meter import MEASURED_NOTE
from agent_tools.context_meter_commands import Invocation, invocations, lex
from agent_tools.model_pricing import SOURCE_DATE, SOURCE_URL, cache_write_split, usage_cost
from agent_tools.transcript_calls import TTL_SECONDS, is_death, read_transcript

SCHEMA_VERSION = 1
REPORT_KIND = "agent-owner-report"
LONG_WAIT_SECONDS = 300
MEASURED_PREFIX = MEASURED_NOTE.partition("{tokens}")[0]
DISPATCH_TOOLS = ("Agent", "Task")
BOOT_GROUPS = ("0-5", "6-7")
LIVE_ARM = "live"
BASELINE_ARM = "baseline"
CANDIDATE_ARM = "candidate"
DEFAULT_SETTLE_DAYS = 4
NONE_YET = "(none: pass --policy or --sweep)"
BIAS_NOTE = ("The shift model keeps observed increments after a hand-off and cannot see a fresh "
             "owner's re-reads, so it favours hand-offs (D18); an arm with more hand-offs than "
             "the baseline is kept only if the live arm confirms it.")

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_MENTIONS = re.compile(r"workflow-state|sdd-gate")
_FINISH_COMMAND = re.compile(r"(?<![\w-])workflow-state\s+finish(?![\w-])")
_TASK_FILE = re.compile(r"\.tasks/task-(\d+)\.md$")
_SAVED_TO = re.compile(r"saved to: (\S+)")
_SUMMED = ("launches", "handoffs", "boots", "deaths", "long_child_waits", "owner_dollars",
           "total_dollars", "gate_calls", "measured_gate_calls", "help_calls",
           "absolute_path_calls")


class StartWindow(NamedTuple):
    """A start window of `--started`: the lineages starting in [since, before) form `arm`."""

    arm: str
    since: datetime
    before: datetime


@dataclass(frozen=True)
class Gate:
    phase: int
    turn_count: int | None
    next_needs_context: bool
    artifacts_sufficient: bool
    remainder_self_contained: bool
    handoff_path: bool
    action: str | None


@dataclass(frozen=True)
class OwnerCall:
    start: float
    end: float
    model: str | None
    fresh: int
    read: int
    write_5m: int
    write_1h: int
    output: int
    death: bool
    is_root: bool
    phase: int | None
    bash: bool
    children_out: bool
    gate: Gate | None
    registers: bool
    help: bool
    mark_progress: str | None
    slimmable: int

    @property
    def context(self):
        return self.fresh + self.read + self.write_5m + self.write_1h


@dataclass(frozen=True)
class Launch:
    transcript: str
    launch: int | None
    calls: tuple
    registered_index: int | None
    transfer: str | None
    chain: int = 0  # which lineage of an eval trial's merge the launch came from
    attempt: int | None = None  # the implementation attempt (custody) the launch belongs to
    remainder: int | None = None  # the delivery remainder (custody) the launch belongs to
    boot_whole: bool = True  # every call through the registering call is inside the event window
    # the event window cut every call through the registering call, so the owner is registered
    # from its first kept call while `registered_index` stays None and its boot stays out of the fit
    registered_before: bool = False


@dataclass
class Lineage:
    run_id: str
    issue: int
    direct: bool
    launches: list
    descendant_dollars: float
    delivered: bool
    facts: dict
    relauncher: tuple = field(default_factory=tuple)
    started: float | None = None   # epoch seconds of the earliest call of the owner transcripts
    members: tuple = ()   # (conversation handle, is an owner transcript) of each transcript of the group


def _bound(text):
    """A range bound: a UTC day as its midnight, else an RFC3339 instant."""
    if _DAY.fullmatch(text):
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return parse_rfc3339_utc(text)


def parse_range(text: str) -> tuple[datetime, datetime]:
    """The `(since, before)` of `SINCE..BEFORE` (issue 503 D1); ValueError when it is not a range."""
    since_text, separator, before_text = text.partition("..")
    if not separator:
        raise ValueError("expected SINCE..BEFORE")
    since, before = _bound(since_text), _bound(before_text)
    if since >= before:
        raise ValueError("SINCE must be before BEFORE")
    return since, before


def start_window_label(windows) -> str:
    """The report's window label for start windows."""
    return "; ".join(
        f"{'started' if window.arm == LIVE_ARM else window.arm} "
        f"{format_rfc3339_utc(window.since)} → {format_rfc3339_utc(window.before)}"
        for window in windows)


def call_cost(call: OwnerCall) -> float:
    """Dollars of one call at its model's price for its prompt size (model_pricing)."""
    usage = {"input_tokens": call.fresh, "output_tokens": call.output,
             "cache_read_input_tokens": call.read,
             "cache_creation_input_tokens": call.write_5m + call.write_1h,
             "cache_creation": {"ephemeral_5m_input_tokens": call.write_5m,
                                "ephemeral_1h_input_tokens": call.write_1h}}
    return usage_cost(call.model, usage)[0]


# ---- reading one transcript ------------------------------------------------------


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reply(result):
    """The first JSON object of a tool result's text; None when the text starts otherwise."""
    if result is None:
        return None
    text = result.text.lstrip()
    if not text.startswith("{"):
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _is_int(value):
    return type(value) is int


@dataclass
class _CallRead:
    """What one call's Bash tool uses show, before the transcript's phases are known."""

    bash: bool = False
    gate: Gate | None = None
    registration: tuple | None = None   # (helper kind, run ID, action ID)
    repo_root: str | None = None        # the first absolute `--repo-root` of a registering invocation
    help: bool = False
    mark_progress: str | None = None
    measured: bool = False
    phase_replied: bool = False         # its progress call got a phase_gate reply
    handed_off: bool = False            # ... whose action was a hand-off for a --handoff-path call
    absolute: int = 0
    review_tasks: list = field(default_factory=list)
    flags: list = field(default_factory=list)       # (issue, attempt) of progress/suspend flags
    replies: list = field(default_factory=list)     # replies that can carry the owner's identity
    finishes: list = field(default_factory=list)    # (run ID, issue) of delivery_complete replies
    directs: list = field(default_factory=list)     # (run ID, issue) of direct-owner replies


def _read_progress(read, inv, reply, note):
    options = inv.options
    if "--help" in options:
        read.help = True
        return
    phase = _int(options.get("--phase"))
    if phase is None or read.gate is not None:
        return
    gated = reply is not None and reply.get("kind") == "phase_gate"
    action = reply.get("action") if gated and isinstance(reply.get("action"), str) else None
    handoff = options.get("--handoff-path") is not None
    read.gate = Gate(
        phase=phase, turn_count=_int(options.get("--turn-count")),
        next_needs_context=options.get("--next-needs-context") == "true",
        artifacts_sufficient=options.get("--artifacts-sufficient") == "true",
        remainder_self_contained=options.get("--remainder-self-contained") == "true",
        handoff_path=handoff, action=action)
    read.phase_replied = gated
    read.handed_off = handoff and action == "handoff"
    read.measured = MEASURED_PREFIX in note


def _read_invocation(read, inv: Invocation, reply, note):
    options = inv.options
    gate = inv.helper == "sdd-gate" or (
        inv.helper == "workflow-state" and inv.subcommand in ("progress", "mark-progress"))
    if inv.helper == "workflow-state" and inv.absolute:
        read.absolute += 1
    if inv.helper == "sdd-gate" and inv.subcommand == "review":
        read.review_tasks.append(_int(options.get("--task")))
    if gate and options.get("--run-id") and options.get("--action-id"):
        if read.registration is None:
            kind = inv.helper if inv.helper == "sdd-gate" else inv.subcommand
            read.registration = (kind, options["--run-id"], options["--action-id"])
        root = options.get("--repo-root")
        if read.repo_root is None and isinstance(root, str) and root.startswith("/"):
            read.repo_root = root
    if inv.helper != "workflow-state":
        return
    if inv.subcommand in ("progress", "suspend"):
        read.flags.append((_int(options.get("--issue")), _int(options.get("--attempt"))))
    if inv.subcommand == "progress":
        _read_progress(read, inv, reply, note)
    elif inv.subcommand == "mark-progress" and reply is not None:
        outcome = reply.get("outcome")
        read.mark_progress = outcome if isinstance(outcome, str) else None


def _read_command(read, tool_id, command, transcript):
    reply = _reply(transcript.results.get(tool_id))
    tokens = lex(command)
    for inv in invocations(tokens) if tokens is not None else ():
        _read_invocation(read, inv, reply, transcript.hook_notes.get(tool_id, ""))
    if reply is None or not _is_int(reply.get("issue")) or not isinstance(reply.get("run_id"), str):
        return
    kind, finish = reply.get("kind"), _FINISH_COMMAND.search(command) is not None
    if kind in ("phase_gate", "owner") or finish:
        read.replies.append(reply)
    if finish and kind == "delivery_complete":
        read.finishes.append((reply["run_id"], reply["issue"]))
    if kind == "owner":
        read.directs.append((reply["run_id"], reply["issue"]))


def _read_call(call, transcript):
    read = _CallRead()
    for tool_id, name in call.tool_names.items():
        if name != "Bash":
            continue
        read.bash = True
        tool_input = call.tool_inputs.get(tool_id)
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if isinstance(command, str) and _MENTIONS.search(command):
            _read_command(read, tool_id, command, transcript)
    return read


def _phases(reads):
    """The phase of each call: a call after a progress call reporting n takes n + 1.

    A call up to and including the first progress call takes that call's `--phase`, or 6
    when the first registering call is an `sdd-gate` or `mark-progress`.
    """
    first = next((read.gate.phase for read in reads if read.gate), None)
    registering = next((read.registration[0] for read in reads if read.registration), None)
    if first is None and registering is None:
        return [None] * len(reads)
    base = 6 if registering in ("sdd-gate", "mark-progress") or first is None else first
    phases, latest = [], None
    for read in reads:
        if latest is None:
            phases.append(base if read.gate is None else read.gate.phase)
        else:
            phases.append(latest + 1)
        if read.gate is not None:
            latest = read.gate.phase
    return phases


def _read_path(call, tool_id):
    if call.tool_names.get(tool_id) != "Read":
        return None
    tool_input = call.tool_inputs.get(tool_id)
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return path if isinstance(path, str) else None


def _stale_boot_read(path, resumed, phase):
    """Whether a boot's Read of `path` is context the owner can do without (D12, D21)."""
    task = _TASK_FILE.search(path)
    if task is not None:
        return resumed is not None and int(task.group(1)) != resumed
    return path.endswith("ship-handoff.md") and phase < 7


def _slimmable(calls, registered, phase, resumed, transcript):
    """Slimmable tokens per call: boot growth split across tool results by size."""
    slim = [0] * len(calls)
    persisted = set()
    for index in range(registered + 1):
        call = calls[index]
        results = [(tool_id, transcript.results[tool_id]) for tool_id in call.tool_names
                   if tool_id in transcript.results]
        total = sum(result.size for _, result in results)
        following = calls[index + 1].context if index + 1 < len(calls) else call.context
        growth = max(0, following - call.context)
        if not total or not growth:
            continue
        share = 0.0
        for tool_id, result in results:
            path = _read_path(call, tool_id)
            stale = path is not None and _stale_boot_read(path, resumed, phase)
            if stale or path in persisted:
                share += growth * result.size / total
            if stale:
                persisted.update(saved.rstrip(".,;:)") for saved in _SAVED_TO.findall(result.text))
        slim[index] = round(share)
    return slim


def _epoch(value, fallback):
    return value.timestamp() if value is not None else fallback


def _owner_call(call, prev_end, read, phase, death, is_root, slimmable):
    end = _epoch(call.end, prev_end)
    write_1h, write_5m = cache_write_split(call.usage)
    return OwnerCall(
        start=_epoch(call.start, end), end=end, model=call.model,
        fresh=call.usage["input_tokens"], read=call.usage["cache_read_input_tokens"],
        write_5m=write_5m, write_1h=write_1h, output=call.usage["output_tokens"],
        death=death, is_root=is_root, phase=phase, bash=read.bash, children_out=False,
        gate=read.gate, registers=read.registration is not None, help=read.help,
        mark_progress=read.mark_progress, slimmable=slimmable)


def _own_identity(reads, run_id):
    """Issue, attempt, remainder and launch an owner's own replies, then its flags, give (D20)."""
    found = {"issue": None, "attempt": None, "remainder": None, "launch": None}
    replies = [reply for read in reads for reply in read.replies
               if reply["run_id"] == run_id]
    for reply in replies:
        custody = reply.get("custody") if isinstance(reply.get("custody"), dict) else {}
        for name in found:
            value = reply.get("issue") if name == "issue" else custody.get(name)
            if name == "attempt" and value is None:
                value = reply.get("attempt")
            if found[name] is None and _is_int(value):
                found[name] = value
    for read in reads:
        for issue, attempt in read.flags:
            if found["issue"] is None:
                found["issue"] = issue
            if found["attempt"] is None:
                found["attempt"] = attempt
    return found


def _session_and_agent(path, is_root):
    if is_root:
        return path.stem, None
    session = next((parent.parent.name for parent in path.parents if parent.name == "subagents"),
                   path.parent.name)
    return session, path.stem.removeprefix("agent-")


def _read_meta(path):
    try:
        with open(path.with_name(path.stem + ".meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return None, None
    if not isinstance(meta, dict):
        return None, None
    parent, tool_use = meta.get("parentAgentId"), meta.get("toolUseId")
    return (parent if isinstance(parent, str) else None,
            tool_use if isinstance(tool_use, str) else None)


def _counted(calls, since, before):
    if since is None and before is None:
        return [True] * len(calls)
    return [call.start_raw is not None and event_in_window(call.start_raw, since, before) is True
            for call in calls]


def _in_windows(calls, windows):
    """Per call, whether its start lies in any `(since, before)` pair of `windows`."""
    flags = [False] * len(calls)
    for since, before in windows:
        flags = [seen or inside for seen, inside in zip(flags, _counted(calls, since, before))]
    return flags


def _owner_scan(path, is_root, transcript, reads, counted):
    calls = transcript.calls
    registered = next(index for index, read in enumerate(reads) if read.registration)
    _, run_id, action_id = reads[registered].registration
    phases = _phases(reads)
    ttl = TTL_SECONDS[is_root]
    deaths = [False] + [is_death(calls[index - 1], calls[index], ttl) for index in range(1, len(calls))]
    resumed = next((task for read in reads for task in read.review_tasks), None)
    slim = [0] * len(calls)
    if not is_root and phases[registered] is not None:
        slim = _slimmable(calls, registered, phases[registered], resumed, transcript)
    owner_calls, prev_end = [], 0.0
    for index, call in enumerate(calls):
        owner_calls.append(_owner_call(call, prev_end, reads[index], phases[index], deaths[index],
                                       is_root, slim[index]))
        prev_end = owner_calls[-1].end
    live = [read for read, flag in zip(reads, counted) if flag]
    replied = [read.gate.action for read in live if read.gate and read.gate.action is not None]
    handoffs = sum(read.handed_off for read in live)
    return {
        **_own_identity(reads, run_id), "run_id": run_id, "action_id": action_id,
        "repo_root": next((read.repo_root for read in reads if read.repo_root is not None), None),
        "cwds": transcript.cwds,
        "calls": owner_calls, "counted": counted, "registered_index": registered,
        "transfer": "handoff" if handoffs else (replied[-1] if replied else None),
        "handoffs": handoffs, "measured": sum(read.measured for read in live),
        "absolute": sum(read.absolute for read in live),
        "phase7": any(read.gate and read.gate.phase == 6 and read.phase_replied for read in live),
    }


def scan_owner_transcript(job, *, since, before, windows=()):
    """Scan one transcript `(path, is_root)`; None when it cannot be opened.

    `windows` holds `(since, before)` pairs; the scan's `window_calls` and `window_dollars` are
    the count and dollars of the calls starting in any of them.
    """
    path, is_root = job
    try:
        with open(path, "r", errors="replace") as handle:
            transcript = read_transcript(handle)
    except OSError:
        return None
    calls = transcript.calls
    counted = _counted(calls, since, before)
    reads = [_read_call(call, transcript) for call in calls]
    priced = [usage_cost(call.model, call.usage) for call, flag in zip(calls, counted) if flag]
    windowed = [usage_cost(call.model, call.usage)
                for call, flag in zip(calls, _in_windows(calls, windows)) if flag]
    session, agent_id = _session_and_agent(path, is_root)
    parent, tool_use = (None, None) if is_root else _read_meta(path)
    ends = [call.end for call in calls if call.end is not None]
    starts = [call.start for call in calls if call.start is not None]
    scan = {
        "path": str(path), "is_root": is_root, "session": session, "agent_id": agent_id,
        "handle": conversation_handle(session, agent_id),
        "parent": parent, "tool_use_id": tool_use, "counted_calls": len(priced),
        "dollars": sum(dollars for dollars, _ in priced),
        "approximate_calls": sum(approximate for _, approximate in priced),
        "window_calls": len(windowed), "window_dollars": sum(dollars for dollars, _ in windowed),
        "last_end": max(ends).timestamp() if ends else None,
        "first_start": min(starts).timestamp() if starts else None,
        "dispatched": {tool_id: index for index, call in enumerate(calls)
                       for tool_id, name in call.tool_names.items() if name in DISPATCH_TOOLS},
        "finishes": [pair for read, flag in zip(reads, counted) if flag for pair in read.finishes],
        "directs": [pair for read in reads for pair in read.directs],
        "owner": None,
    }
    if any(read.registration for read in reads):
        scan["owner"] = _owner_scan(path, is_root, transcript, reads, counted)
    return scan


# ---- assembling lineages ---------------------------------------------------------


def _resolve_owners(scans):
    """Fill an owner's missing issue, attempt, remainder and launch from a peer with its action ID."""
    peers = defaultdict(list)
    for scan in scans:
        if scan["owner"] is not None:
            peers[(scan["owner"]["run_id"], scan["owner"]["action_id"])].append(scan["owner"])
    for owners in peers.values():
        for name in ("issue", "attempt", "remainder", "launch"):
            known = next((owner[name] for owner in owners if owner[name] is not None), None)
            for owner in owners:
                if owner[name] is None:
                    owner[name] = known


def _parent_of(scan, by_agent, roots):
    """The transcript that dispatched `scan`: its `parentAgentId`, else its session's root."""
    if scan["is_root"]:
        return None
    if scan["parent"] is not None:
        return by_agent.get((scan["session"], scan["parent"]))
    return roots.get(scan["session"])


def _nearest_owner(scan, by_agent, roots):
    """The owner scan `scan` belongs to (itself, else an ancestor), else None."""
    seen = set()
    while scan is not None and scan["path"] not in seen:
        if scan["owner"] is not None:
            return scan
        seen.add(scan["path"])
        scan = _parent_of(scan, by_agent, roots)
    return None


def _children(scan, child_ends):
    """The `(dispatching call index, last end)` of each child this transcript dispatched."""
    return [(index, child_ends[(scan["session"], tool_id)])
            for tool_id, index in scan["dispatched"].items() if (scan["session"], tool_id) in child_ends]


def _out_flags(calls, children):
    return [any(index < position and last_end > call.start for index, last_end in children)
            for position, call in enumerate(calls)]


def _long_waits(calls, counted, children):
    """Gaps over LONG_WAIT_SECONDS with a dispatched child out across them, once per gap."""
    return sum(
        1 for position in range(1, len(calls))
        if counted[position] and calls[position].start - calls[position - 1].end > LONG_WAIT_SECONDS
        and any(index <= position - 1 and last_end > calls[position - 1].end
                for index, last_end in children))


def _launch(scan, children):
    owner = scan["owner"]
    calls, counted = owner["calls"], owner["counted"]
    out = _out_flags(calls, children)
    kept = tuple(replace(call, children_out=out[index])
                 for index, call in enumerate(calls) if counted[index])
    registered = owner["registered_index"]
    kept_index = sum(counted[:registered]) if counted[registered] else None
    return Launch(scan["path"], owner["launch"], kept, kept_index, owner["transfer"],
                  boot_whole=all(counted[:registered + 1]),
                  registered_before=not any(counted[:registered + 1]), attempt=owner["attempt"],
                  remainder=owner["remainder"])


def _phase_reached(calls):
    reached = [call.gate.phase + 1 if call.gate and call.gate.action is not None else call.phase
               for call in calls if call.phase is not None]
    return max(reached, default=None)


def _lineage_row(run_id, issue, launches, extras, *, direct, delivered, descendant_dollars,
                 project, started):
    """The per-lineage JSON fields; `extras` are the owner scans' counts per launch."""
    calls = [call for launch in launches for call in launch.calls]
    owner_dollars = sum(call_cost(call) for call in calls)
    return {
        "key": f"{run_id}:{issue}", "run_id": run_id, "issue": issue, "arm": LIVE_ARM,
        "trial": None, "verdict": None, "direct": direct, "launches": len(launches),
        "handoffs": sum(extra["handoffs"] for extra in extras),
        "boots": sum(1 for launch in launches if not launch.calls[0].is_root),
        "deaths": sum(call.death for call in calls),
        "long_child_waits": sum(extra["waits"] for extra in extras),
        "peak_context": max(call.context for call in calls),
        "owner_dollars": owner_dollars, "total_dollars": owner_dollars + descendant_dollars,
        "delivered": delivered, "phase_reached": _phase_reached(calls),
        "phase7_entered": any(extra["phase7"] for extra in extras),
        "gate_calls": sum(call.gate is not None for call in calls),
        "measured_gate_calls": sum(extra["measured"] for extra in extras),
        "help_calls": sum(call.help for call in calls),
        "absolute_path_calls": sum(extra["absolute"] for extra in extras),
        "project": project, "started": _instant(started),
        "owner_ping_dollars": 0.0, "ping_dollars": 0.0,   # collect adds a ping log's share
    }


def _instant(epoch):
    """An epoch-seconds instant as an RFC3339 UTC string; None for None."""
    if epoch is None:
        return None
    return format_rfc3339_utc(datetime.fromtimestamp(epoch, timezone.utc))


def _project(owner_scans, homes):
    """The repository holding the lineage's ledger (issue 503 D4): the first absolute registering
    `--repo-root` in launch order, else `project_name` over the owners' record cwds."""
    for scan in owner_scans:
        if scan["owner"]["repo_root"] is not None:
            return os.path.basename(repo_root(scan["owner"]["repo_root"]))
    cwds = sum((scan["owner"]["cwds"] for scan in owner_scans), Counter())
    return project_name(homes[owner_scans[0]["path"]], cwds)


def _relauncher(launches):
    for launch in launches:
        if launch.calls and launch.calls[0].is_root:
            return tuple((call.end, call.context) for call in launch.calls)
    return ()


def _launch_order(launch):
    """A launch's place in its lineage: by attempt, then remainder, then launch ordinal (each
    unknown last, an attempt's own launches before its remainders'), then first call time.

    A launch ordinal counts within one attempt or remainder, so a retry's launch 1 follows the
    first attempt's last launch, never its launch 1.
    """
    return (launch.attempt is None, launch.attempt or 0, launch.remainder is not None,
            launch.remainder or 0, launch.launch is None, launch.launch or 0, launch.calls[0].start)


def _lineage(run_id, issue, group, child_ends, homes):
    """The lineage of one `(run_id, issue)`, from its `(scan, nearest owner scan)` members."""
    owners = [scan for scan, owner_scan in group if scan is owner_scan and scan["counted_calls"]]
    launches, extras = [], []
    for scan in owners:
        children = _children(scan, child_ends)
        launches.append(_launch(scan, children))
        owner = scan["owner"]
        extras.append({"handoffs": owner["handoffs"], "measured": owner["measured"],
                       "absolute": owner["absolute"], "phase7": owner["phase7"],
                       "waits": _long_waits(owner["calls"], owner["counted"], children)})
    ordered = sorted(zip(launches, extras, owners), key=lambda triple: _launch_order(triple[0]))
    launches = [launch for launch, _, _ in ordered]
    extras = [extra for _, extra, _ in ordered]
    project = _project([scan for _, _, scan in ordered], homes)
    starts = [scan["first_start"] for scan, owner_scan in group
              if scan is owner_scan and scan["first_start"] is not None]
    started = min(starts, default=None)
    descendants = sum(scan["dollars"] for scan, owner_scan in group if scan is not owner_scan)
    key = (run_id, issue)
    delivered = any(key in scan["finishes"] for scan, _ in group)
    direct = any(key in scan["directs"] for scan, _ in group)
    facts = _lineage_row(run_id, issue, launches, extras, direct=direct, delivered=delivered,
                         descendant_dollars=descendants, project=project, started=started)
    members = tuple((scan["handle"], scan is owner_scan) for scan, owner_scan in group)
    return Lineage(run_id, issue, direct, launches, descendants, delivered, facts,
                   _relauncher(launches), started, members)


def _lineages(scans, homes, *, start_mode=False):
    """The lineages of `scans` and the unattributed transcripts, dollars and unresolved owners.

    With `start_mode` a transcript is lost by its calls inside the start windows, not by its counted ones.
    """
    _resolve_owners(scans)
    by_agent = {(scan["session"], scan["agent_id"]): scan for scan in scans if not scan["is_root"]}
    roots = {scan["session"]: scan for scan in scans if scan["is_root"]}
    child_ends = {(scan["session"], scan["tool_use_id"]): scan["last_end"] for scan in scans
                  if scan["tool_use_id"] and scan["last_end"] is not None}
    members = defaultdict(list)
    unattributed = {"transcripts": 0, "dollars": 0.0, "unresolved_owners": 0}

    calls_name, dollars_name = ("window_calls", "window_dollars") if start_mode else (
        "counted_calls", "dollars")

    def lose(scan):
        if scan[calls_name]:
            unattributed["transcripts"] += 1
            unattributed["dollars"] += scan[dollars_name]

    for scan in scans:
        owner_scan = _nearest_owner(scan, by_agent, roots)
        if owner_scan is not None and owner_scan["owner"]["issue"] is not None:
            members[(owner_scan["owner"]["run_id"], owner_scan["owner"]["issue"])].append(
                (scan, owner_scan))
        else:
            unattributed["unresolved_owners"] += owner_scan is scan and (
                not start_mode or bool(scan["window_calls"]))
            lose(scan)
    lineages = []
    for (run_id, issue), group in sorted(members.items()):
        if any(scan is owner_scan and scan["counted_calls"] for scan, owner_scan in group):
            lineages.append(_lineage(run_id, issue, group, child_ends, homes))
        else:
            for scan, _ in group:   # every owner transcript is outside the window
                lose(scan)
    return lineages, unattributed


def _merge_trial(row, lineages):
    """One lineage row for a whole eval trial: sums, the highest peak, any Phase 7 entry."""
    first = lineages[0]
    facts = dict(first.facts)
    for name in _SUMMED:
        facts[name] = sum(lineage.facts[name] for lineage in lineages)
    facts["peak_context"] = max(lineage.facts["peak_context"] for lineage in lineages)
    facts["phase_reached"] = max((lineage.facts["phase_reached"] for lineage in lineages
                                  if lineage.facts["phase_reached"] is not None), default=None)
    facts["phase7_entered"] = any(lineage.facts["phase7_entered"] for lineage in lineages)
    direct = any(lineage.direct for lineage in lineages)
    delivered = row.get("verdict") == "PASS"
    arm = f"{str(row.get('tree_rev'))[:12]}/{row.get('policy') or 'default'}"
    facts.update(key=f"{arm}/T{row.get('trial')}", arm=arm, trial=row.get("trial"),
                 verdict=row.get("verdict"), direct=direct, delivered=delivered)
    return Lineage(
        first.run_id, first.issue, direct,
        [replace(launch, chain=position) for position, lineage in enumerate(lineages)
         for launch in lineage.launches],
        sum(lineage.descendant_dollars for lineage in lineages), delivered, facts, first.relauncher)


def _mangled(workdir):
    return re.sub(r"[^A-Za-z0-9]", "-", workdir)


def _in_workdir(home, workdir):
    prefix = _mangled(workdir)
    return home == prefix or home.startswith(prefix + "-")


def _clean_exit(row):
    return type(row.get("claude_exit")) is int and row["claude_exit"] == 0


def _interrupted(row):
    return {"trial": row.get("trial"), "tree_rev": row.get("tree_rev"),
            "claude_exit": row.get("claude_exit")}


def _select_started(lineages, windows, settle_days, report_end):
    """The kept lineages, the left-out ones and the `start_grouping` of start windows (issue 503 D2, D3).

    A lineage that started in a window is kept for that window's arm once it has settled: it
    started at least `settle_days` days before `report_end`. A younger one is counted in the
    window's `unsettled`.
    """
    unsettled = [{"lineages": 0, "dollars": 0.0} for _ in windows]
    kept, left = [], []
    for lineage in lineages:
        position = next((index for index, window in enumerate(windows)
                         if lineage.started is not None
                         and window.since.timestamp() <= lineage.started < window.before.timestamp()),
                        None)
        if position is None:
            left.append(lineage)
        elif lineage.started > report_end - settle_days * 86_400:
            unsettled[position]["lineages"] += 1
            unsettled[position]["dollars"] += lineage.facts["total_dollars"]
            left.append(lineage)
        else:
            lineage.facts["arm"] = windows[position].arm
            kept.append(lineage)
    grouping = {
        "settle_days": settle_days, "report_end": _instant(report_end),
        "windows": [{"arm": window.arm, "since": format_rfc3339_utc(window.since),
                     "before": format_rfc3339_utc(window.before), "unsettled": counts}
                    for window, counts in zip(windows, unsettled)]}
    return kept, left, grouping


def _attribute_pings(log, counted, left_out, *, attributed_scope, unattributed_scope):
    """The `pings` footer of `log` and the count of approximately priced pings it counts.

    A ping whose conversation is a member of a counted lineage adds to that lineage (its owner
    share too, for an owner transcript) when `attributed_scope` holds; one of a left-out
    lineage is dropped; any other counts as unattributed when `unattributed_scope` holds."""
    members = {handle: (lineage, owner) for lineage in counted for handle, owner in lineage.members}
    dropped = {handle for lineage in left_out for handle, _ in lineage.members}
    attributed = {"pings": 0, "dollars": 0.0, "owner_dollars": 0.0}
    unattributed = {"pings": 0, "dollars": 0.0}
    unpriced = approximate = 0
    for ping in log.pings:
        hit = members.get(ping.conversation)
        if hit is not None:
            if not attributed_scope(ping.ts):
                continue
            lineage, owner = hit
            lineage.facts["ping_dollars"] += ping.dollars
            attributed["pings"] += 1
            attributed["dollars"] += ping.dollars
            if owner:
                lineage.facts["owner_ping_dollars"] += ping.dollars
                attributed["owner_dollars"] += ping.dollars
        elif ping.conversation in dropped or not unattributed_scope(ping.ts):
            continue
        else:
            unattributed["pings"] += 1
            unattributed["dollars"] += ping.dollars
        unpriced += not ping.priced
        approximate += ping.approximate
    return ({"log": log.log, "lines": len(log.pings), "skipped_lines": log.skipped,
             "unpriced": unpriced, "attributed": attributed, "unattributed": unattributed},
            approximate)


def _scan_all(jobs, since, before, executor_factory, windows=()):
    scanner = functools.partial(scan_owner_transcript, since=since, before=before, windows=windows)
    return [scan for scan in scan_paths(jobs, executor_factory, scanner=scanner) if scan]


def _in_event_window(ts, since, before):
    return (since is None or ts >= since) and (before is None or ts < before)


def _ping_scopes(windows, since, before, cutoff):
    """The `(attributed, unattributed)` predicates over a ping's instant (issue 503 D6).

    A ping of a counted lineage counts in the event window if there is one, else always. An
    unmatched ping counts in a start window if there are windows, else in the event window if
    there is one, else after the mtime `cutoff`."""
    def attributed(ts):
        return _in_event_window(ts, since, before)

    if windows:
        def unattributed(ts):
            return any(window.since <= ts < window.before for window in windows)
    elif since is not None or before is not None:
        unattributed = attributed
    else:
        def unattributed(ts):
            return cutoff is None or ts.timestamp() >= cutoff
    return attributed, unattributed


def collect(root: Path, *, cutoff, since, before, eval_rows, executor_factory, windows=(),
            settle_days=0, pings=None):
    """The lineages of the transcripts under `root` and the footer facts.

    With `windows` (StartWindow, never combined with `eval_rows`) the mtime `cutoff` and the
    event window do not apply: every transcript is read and every call counted, and the
    settled lineages that started in a window are kept (issue 503 D1, D3). The footer's
    `start_grouping` is None without `windows`.

    With `pings` (a keepalive_pings.PingLog, never combined with `eval_rows`) each ping adds to
    its counted lineage, counts as unattributed, or is left out (issue 503 D5, D6, D12); the
    footer's `pings` is None without it.

    With `eval_rows` the mtime `cutoff` does not apply: each row with `claude_exit` 0
    is one lineage row built from the sessions of its workdir's project directories, and
    every other row is listed as interrupted. A clean-exit row that yields no lineage (no
    matching session, or no resolved owner) is listed as unmatched, never dropped.
    """
    start_mode = bool(windows)
    sessions = list(find_sessions(root, None if eval_rows is not None or start_mode else cutoff))
    interrupted, unmatched, samples = [], [], []
    if eval_rows is not None:
        samples = [row for row in eval_rows if _clean_exit(row)]
        interrupted = [_interrupted(row) for row in eval_rows if not _clean_exit(row)]
        sessions = [session for session in sessions
                    if any(_in_workdir(session[0], str(row.get("workdir"))) for row in samples)]
    homes, jobs = {}, []
    for home, root_files, sub_files in sessions:
        for is_root, paths in ((True, root_files), (False, sub_files)):
            for path in paths:
                homes[str(path)] = home
                jobs.append((path, is_root))
    pairs = tuple((window.since, window.before) for window in windows)
    scans = _scan_all(jobs, None if start_mode else since, None if start_mode else before,
                      executor_factory, pairs)
    start_grouping, left_out = None, []
    if eval_rows is None:
        lineages, unattributed = _lineages(scans, homes, start_mode=start_mode)
        if start_mode:
            report_end = max((scan["last_end"] for scan in scans if scan["last_end"] is not None),
                             default=None)
            lineages, left_out, start_grouping = _select_started(lineages, windows, settle_days, report_end)
    else:
        lineages, unattributed = [], {"transcripts": 0, "dollars": 0.0, "unresolved_owners": 0}
        for row in samples:
            scoped = [scan for scan in scans if _in_workdir(homes[scan["path"]], str(row.get("workdir")))]
            found, missing = _lineages(scoped, homes)
            for name, value in missing.items():
                unattributed[name] += value
            if found:
                lineages.append(_merge_trial(row, found))
            else:
                unmatched.append(_interrupted(row))
    approximate = sum(scan["approximate_calls"] for scan in scans)
    ping_footer = None
    if pings is not None:
        attributed_scope, unattributed_scope = _ping_scopes(windows, since, before, cutoff)
        ping_footer, approximate_pings = _attribute_pings(
            pings, lineages, left_out, attributed_scope=attributed_scope,
            unattributed_scope=unattributed_scope)
        approximate += approximate_pings
    footer = {
        "pricing": {"source": SOURCE_URL, "date": SOURCE_DATE, "approximate_calls": approximate},
        "unattributed": unattributed, "interrupted": interrupted,
        "unmatched": unmatched, "start_grouping": start_grouping, "pings": ping_footer,
    }
    return lineages, footer


def load_eval_rows(path, skill, case):
    """The results rows of `path` whose `skill` and `id` match; ValueError on a bad line."""
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: not JSON") from error
            if isinstance(row, dict) and row.get("skill") == skill and str(row.get("id")) == case:
                rows.append(row)
    return rows


# ---- the document ----------------------------------------------------------------


def phase_group(phase):
    """The boot group (BOOT_GROUPS) of a working phase; an unknown phase is in "0-5"."""
    return "6-7" if phase is not None and phase >= 6 else "0-5"


def boot_slice(launch):
    """The calls of a fresh owner's boot: through its registering call, and no further than the
    last call before the first with a child out, because a dispatched child is the owner's
    first unit of work and the replay's observed increments already carry it."""
    boot = launch.calls[:launch.registered_index + 1]
    out = next((index for index, call in enumerate(boot) if call.children_out), len(boot))
    return boot[:out]


def boot_facts(launch):
    """B, start context, call count and slimmable tokens of a fresh owner's boot.

    None for a root launch, for a boot the event window cuts (its counted calls would start
    later than the boot, or at a call with a child out and so hold no boot call at all), and
    for any boot slice with no call.
    """
    if (not launch.calls or launch.calls[0].is_root or launch.registered_index is None
            or not launch.boot_whole):
        return None
    boot = boot_slice(launch)
    if not boot:
        return None
    group = phase_group(launch.calls[launch.registered_index].phase)
    return group, {"b": boot[-1].context, "start": boot[0].context, "calls": len(boot),
                   "slimmable": sum(call.slimmable for call in boot)}


def _boot_rows(lineages):
    groups = {name: [] for name in BOOT_GROUPS}
    for lineage in lineages:
        for launch in lineage.launches:
            boot = boot_facts(launch)
            if boot is not None:
                groups[boot[0]].append(boot[1])
    return [{"phase_group": name, "count": len(boots),
             "b_p50": percentile([boot["b"] for boot in boots], 50),
             "b_p90": percentile([boot["b"] for boot in boots], 90),
             "start_p50": percentile([boot["start"] for boot in boots], 50),
             "calls_p50": percentile([boot["calls"] for boot in boots], 50),
             "slimmable_p50": percentile([boot["slimmable"] for boot in boots], 50)}
            for name, boots in groups.items() if boots]


def build_document(lineages, footer, *, window: str, arms=None, sweep=False) -> dict:
    """The `agent-owner-report` document; `arms` (replay Arms) and `sweep` fill the replay. Two
    start windows make a comparison of the baseline and candidate arms (issue 503 D4)."""
    rows = [lineage.facts for lineage in lineages]
    simulated, calibration = [], None
    if arms or sweep:
        from agent_tools import agent_owner_replay  # imports this module, so only here
        model = agent_owner_replay.fit(lineages)
        simulated = agent_owner_replay.compare(lineages, model, arms or [])
        if sweep:
            simulated += agent_owner_replay.sweep(lineages, model)
        calibration = agent_owner_replay.calibration(lineages, model)
    grouping = footer["start_grouping"]
    compared = grouping is not None and len(grouping["windows"]) == 2
    arm_rows = agent_owner_rollup.arm_rows(
        rows, required=[BASELINE_ARM, CANDIDATE_ARM] if compared else ())
    project_rows = agent_owner_rollup.project_rows(rows, [arm["arm"] for arm in arm_rows])
    return {
        "kind": REPORT_KIND, "schema_version": SCHEMA_VERSION, "window": window,
        "start_grouping": grouping, "pricing": footer["pricing"],
        "lineages": rows, "arms": arm_rows, "projects": project_rows,
        "boots": _boot_rows(lineages), "simulated": simulated, "calibration": calibration,
        "pings": footer["pings"], "comparison": (agent_owner_rollup.comparison(arm_rows, project_rows, BASELINE_ARM,
                                                     CANDIDATE_ARM) if compared else None),
        "unattributed": footer["unattributed"], "interrupted": footer["interrupted"],
        "unmatched": footer["unmatched"],
    }


def _money(value):
    return "-" if value is None else f"${value:,.2f}"


def _print_capped(rows, top, headers, aligns):
    print_table(rows[:top], headers, aligns)
    if len(rows) > top:
        print(f"\n... {len(rows) - top} more rows not shown (--top {len(rows)} for all)")


def _print_simulated(rows):
    print("\nSimulated arms (savings are per lineage against the baseline replay; a sweep step's "
          "rows are against the step's simpler arm; hand-offs and deaths per issue):\n")
    if not rows:
        print(NONE_YET)
        return
    print_table(   # every row: a sweep's final and combined verdicts come last
        [[row["arm"], row["step"], row["spec"], _money(row["dollars_per_delivered"]),
          _money(row["mean_saving"]), _money(row["lower_bound"]), f"{row['share_saving']:.0%}",
          f"{row['handoffs_per_issue']:.2f}", f"{row['deaths_per_issue']:.2f}",
          human(row["peak_p90"]), row["verdict"],
          "yes" if row["live_confirmation_required"] else "no"] for row in rows],
        ["arm", "step", "spec", "$ / delivered", "mean saving", "lower bound", "saves",
         "hand-offs", "deaths", "peak p90", "verdict", "live check"],
        ["l", "l", "l"] + ["r"] * 7 + ["l", "l"])
    threshold_rows = [row for row in rows if row["step"] == "threshold"]
    cheapest = min(threshold_rows, key=lambda row: row["dollars_per_delivered"] or 0, default=None)
    if cheapest is not None and cheapest["verdict"] == "info":
        print("\nthreshold=never is the cheapest threshold arm; it is a reference, never chosen.")


def _print_calibration(calibration, top):
    print("\nCalibration:\n")
    if calibration is None:
        print(NONE_YET)
        return
    print(f"Identity replay matches the priced lineages: "
          f"{'yes' if calibration['identity_matches'] else 'NO'} "
          f"(max error ${calibration['identity_max_error']:.9f})")
    model = calibration["model"]
    print(f"Boot model: start {human(model['start'])}; boot calls {model['boot_calls']}; "
          f"B {model['boot_end']}; slimmable {model['slimmable']}; hand-off overhead calls "
          f"{model['overhead_calls']}; boot output {model['boot_output']}; defaults: "
          f"{', '.join(model['defaults']) or 'none'}\n")
    groups = {boot["phase_group"] for boot in calibration["boots"]}
    _print_capped(
        [[group, f"{len(members):,}",
          _money(percentile([boot["observed_dollars"] for boot in members], 50)),
          _money(percentile([boot["modelled_dollars"] for boot in members], 50))]
         for group in BOOT_GROUPS if group in groups
         for members in [[boot for boot in calibration["boots"] if boot["phase_group"] == group]]],
        top, ["phase", "boots", "observed p50", "modelled p50"], ["l", "r", "r", "r"])


def print_document(doc: dict, *, top: int) -> None:
    """Print the six tables of the owner report for `doc` (build_document's result)."""
    rows = sorted(doc["lineages"], key=lambda row: (-row["total_dollars"], row["key"]))
    print(f"Owner report ({doc['window']}, {len(rows):,} lineages)\n")
    print("Lineages (one per run and issue; one per trial in an eval; dollars are list-price "
          "estimates):\n")
    _print_capped(
        [[row["key"], row["arm"], f"{row['launches']:,}", f"{row['handoffs']:,}",
          f"{row['boots']:,}", f"{row['deaths']:,}", f"{row['long_child_waits']:,}",
          human(row["peak_context"]), _money(row["owner_dollars"]), _money(row["total_dollars"]),
          "yes" if row["delivered"] else "no"] for row in rows],
        top, ["lineage", "arm", "launches", "hand-offs", "boots", "deaths", "child waits",
              "peak", "owner $", "total $", "delivered"],
        ["l", "l"] + ["r"] * 8 + ["l"])
    print("\nArms (dollars per delivered issue = all spend of the arm / delivered; sd is the "
          "sample standard deviation over delivered rows):\n")
    _print_capped(
        [[arm["arm"], f"{arm['n']:,}", f"{arm['delivered']:,}", _money(arm["dollars_per_delivered"]),
          _money(arm["sd"]), _money(arm["undelivered_dollars"]), human(arm["peak_p50"]),
          human(arm["peak_p90"])] for arm in doc["arms"]],
        top, ["arm", "n", "delivered", "$ / delivered", "sd", "undelivered $", "peak p50", "peak p90"],
        ["l"] + ["r"] * 7)
    print("\nFresh-owner boots by phase (B = context at the end of the boot, the registering call or the last call before the first child; slimmable = boot "
          "tokens a smaller resume would skip):\n")
    _print_capped(
        [[boot["phase_group"], f"{boot['count']:,}", human(boot["b_p50"]), human(boot["b_p90"]),
          human(boot["start_p50"]), f"{boot['calls_p50']:,}", human(boot["slimmable_p50"])]
         for boot in doc["boots"]],
        top, ["phase", "boots", "B p50", "B p90", "start p50", "boot calls p50", "slimmable p50"],
        ["l"] + ["r"] * 6)
    _print_simulated(doc["simulated"])
    _print_calibration(doc["calibration"], top)
    pricing, lost = doc["pricing"], doc["unattributed"]
    print(f"\nPricing: {pricing['source']} ({pricing['date']}); "
          f"{pricing['approximate_calls']:,} calls priced approximately")
    print(f"Unattributed: {lost['transcripts']:,} transcripts, {_money(lost['dollars'])}; "
          f"{lost['unresolved_owners']:,} owners without an issue")
    if doc["interrupted"]:
        print(f"Interrupted trials left out (evidence gaps): {len(doc['interrupted']):,}")
    if doc["unmatched"]:
        print(f"Clean-exit trials with no owner lineage (evidence gaps): {len(doc['unmatched']):,}")
    if doc["simulated"]:
        print(BIAS_NOTE)
    print(f"NOTE: {DISCLAIMER}")
