"""The delivery procedure format and its check (#1508).

A procedure directory holds procedure files `<name>.json` (every `*.json` not ending `.reply.json`), prompt files `*.md` and
reply schema files `*.reply.json`. A procedure's name is its file stem and matches `^[a-z][a-z0-9-]*$`. Every file is strict
JSON: a duplicate key or a non-finite literal makes it unreadable.

Header. A procedure is an object with these members: `format` (the integer 1, the only version number), `inputs` (distinct
names matching `^[a-z][a-z0-9_]*$`), `stops` (stop name -> object with exactly `need`, one of `NEEDS`, and `reenter`, a step
id) and `steps` (a non-empty list), all required, and `keep_alive`, optional (a procedure with none runs no keep-alive): an
object with `command`, a command id, optional `subcommand`, and `in`, a list of distinct `run.<input>` paths, the one
keep-alive command and where its arguments come from. A procedure naming a `keep_alive` declares a stop `claim-lost`. A stop
is never named `done`, `exhausted`, `out-of-bounds`, `quota-wait` or like a step. `exhausted` and `out-of-bounds` are reserved:
no stop, declared verdict or reply enum value carries either. `quota-wait` is the engine's own stop, taken when every account
is out of usage (`engine_shell`).

Step. Common members: `id` (never `run` or `done`), `stage` (one of `STAGES`),
`kind` (one of `KINDS`), `holds` (one of `HOLDS`, required: how long the step's
stored result holds when a stopped run continues), `in` (distinct paths,
`<step id>.<member>` or `run.<input>`), `on` (outcome -> target; required on every step except a group
member, forbidden on one), `max_visits` (integer >= 1; its presence makes the
step bounded) and `mutates` (bool). Kind members: `command`: `command`,
optional `subcommand`, its arguments being its `in` paths, and optional `check`
(an object with `command` and optional `subcommand`: the command that reads
whether the step's effect already happened; a command step with `mutates` true
requires one and no other step carries one); `agent`: `role`,
`prompt` (a bare `*.md` name), `reply` (a bare `*.reply.json` name) and
`outcome_from`; `decide`: `grader`; `group`: `members`, a non-empty list of
objects with exactly `step` and `pass` (distinct strings); `call`: `procedure`,
optional `each` (one of the step's `in` paths) and `parallel` (an integer >= 1,
only with `each`). A member a level does not define is `undefined_field`.

Groups. A group member is a step of the same list, listed by exactly one group, not a group, not the first step and never an
`on` target or a stop's `reenter`. The first step is the entry. Command ids and verdicts are declared in
`command_verdicts.json`: an object keyed by command-table id whose value is `null` (not declared yet), `{"verdicts": [...]}`
or `{"subcommands": {<subcommand>: [...]}}`.

Phases. One defect yields one refusal, ordered by procedure name, phase, then step position, and naming the step id, or `None`
for a header, `keep_alive` or stop defect. Phase A (structure, per file): `unreadable_procedure`, `undefined_field`,
`invalid_field`, `unknown_stage`, `duplicate_step`. A file with a phase A refusal gets no other phase.

Phase B (references, only on a file with no phase A refusal; the header, `keep_alive` and stops first, then the steps in
order): `unknown_target` (an `on` target that is no step, stop or `done`, a stop `reenter` or a group member `step` that is
no step), `missing_claim_lost` (a `keep_alive` and no stop `claim-lost`), `unknown_command` and `undeclared_verdicts` (a
`command` step, its `check` or `keep_alive` against `command_verdicts.json`: an id that is no key, or a `subcommand` on a `verdicts`-form
declaration, is the first; a `null` declaration, or a `subcommands`-form declaration that lacks the named subcommand, is the
second), `unknown_role` (not in `ROLES`), `missing_prompt`, `missing_reply` (no such file in the procedure directory, a file
that resolves outside it, or for `missing_prompt` a prompt that is not UTF-8 text), `invalid_reply` (the reply schema is not
a strict-JSON object with a `properties` object, a `required` list of strings that contains `outcome_from`, and an `enum` of
distinct non-empty strings under `properties[outcome_from]` that names neither `exhausted` nor `no-reply`, both reserved), `unsupported_reply` (a reply schema that passes
`invalid_reply` but uses a construct outside the subset `engine_reply` defines, named in the detail), `unknown_grader`
(not in `GRADERS`) and `missing_procedure` (a `call` child file is absent; a child that exists but fails phase A gives the parent no refusal).

`Resolved` records what each step's references resolved to: a `StepResolved` per step id (a member is `None` when its
reference failed or does not apply; `child_stops` is set only when the child loaded with no phase A refusal) and `keep_alive`,
the keep-alive command's outcomes or `None`.

Phase C, graph (only on a file with no phase A refusal and no `unknown_target`; the steps in order, `unreachable_done`
first): `unreachable_step` (a step the walk of `flow_graph` from the first step does not reach, `flow_graph` carrying the
renewal failure as an edge to `claim-lost` into a `mutates` step; a group member is reached when its group is),
`unreachable_done` (no reachable step has an `on` entry to `done` that is an edge of `flow_graph`), `unmapped_outcome` and
`unknown_outcome` (a step's `on` keys against `outcomes_of`; an `agent` step also produces `no-reply`, the shell's outcome when
no valid reply came back, so a non-member agent step whose `on` lacks it is `unmapped_outcome`; an agent step outside a group also
produces `out-of-bounds`, which its `on` must map, and a command step may map it; a command step also produces
`refused`, because the engine calls the lifecycle guard before every command (issue 1515), so its `on` maps it; a step in
`exhaustible` also produces `exhausted`, any step may map it, and a group member's `pass` entries are checked at the
group, where neither `no-reply` nor `refused` passes) and `unbounded_cycle` (a cycle among steps
with no `max_visits`, or a step on a cycle whose `exhausted` target re-enters the loop, or a loop through the `exhausted`
entries of steps on a cycle, alone or mixed with ordinary entries, which never ends once every bound is spent; refused at its
first step). An outcome check whose reference failed phase B is skipped for that step.

Phase C, data flow (after the graph checks; in step order, the header's `keep_alive` first): `unproduced_input` (an `in` path
`run.<n>` whose `n` is not a header input, or `<X>.<m>` where `X` is not produced on every route to the step: `X` is a
non-member step, or a member of a group, among the `dominators` of the step without itself; a group member is dominated
through its group; a step never reads its own result; a step the walk does not reach, and a member of a group it does not
reach, skip this route check and keep the `run.<n>` and member checks; a step's `no-reply` result is `{}`, so the edge
it maps `no-reply` to produces none of its members, and a reader reached through it is refused), `unknown_member` (`X` is an agent step whose reply
schema resolved and `m` is not in its `properties` or its `required` list, since a value the reply may leave out cannot be
consumed; a step ended by a bound (`out-of-bounds`) produces none of its members, so a read of `<X>.<m>` is refused on a
route where `X` ended by the bound, unless the route reenters `X` and passes a normal outcome before the reader (the `exhausted` entry of a step on a cycle follows an earlier visit and keeps that visit's reply, unless the bound route leads back to the step); `X` is a decide step and `m` is not `verdict`, the only member its result publishes; the result of any other kind
declares no schema and is not member-checked), `unknown_placeholder` (a `{{<path>}}` of the step's prompt that is none of
its `in` paths; skipped when the prompt is missing) and `each_not_a_list` (a `call` step's `each` path that resolved with
no refusal above and reads a value that is not a list: a run input, a decide step's `verdict`, an agent reply member
whose property schema has no `"type": "array"`, or a member of a platform command's output that
`PLATFORM_LISTS` does not name; a path that did not resolve keeps its own refusal alone, and a producer of any other
kind, a project command, or an agent whose reply did not resolve, declares no schema and is not list-checked)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery.engine_graders import GRADERS
from agent_tools.delivery.engine_reply import schema_problem

FORMAT = 1
STAGES = ("setup", "planning", "plan review", "building", "final review",
          "verifying", "awaiting look", "landing", "closing out", "done")
KINDS = ("command", "agent", "decide", "group", "call")
NEEDS = ("owner-decision", "owner-look", "retry", "nothing")
ROLES = ("planner", "implementer", "reviewer", "reviewer-lite")
DEFECTS = ("unreadable_procedure", "undefined_field", "invalid_field",
           "unknown_stage", "duplicate_step", "unknown_target", "unknown_command",
           "undeclared_verdicts", "missing_claim_lost", "unknown_role", "missing_prompt", "missing_reply",
           "invalid_reply", "unsupported_reply", "unknown_grader", "missing_procedure",
           "unreachable_step", "unreachable_done", "unmapped_outcome",
           "unknown_outcome", "unbounded_cycle", "unproduced_input",
           "unknown_member", "unknown_placeholder", "each_not_a_list")
EXHAUSTED = "exhausted"
OUT_OF_BOUNDS = "out-of-bounds"
NO_REPLY = "no-reply"
REFUSED = "refused"
CLAIM_LOST = "claim-lost"
QUOTA_WAIT = "quota-wait"
START = "(start)"

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PATH_RE = re.compile(r"^([a-z][a-z0-9-]*)\.([a-z][a-z0-9_]*)$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")

# The members of each platform command's JSON output that are lists; every other member is not one.
PLATFORM_LISTS: Mapping[str, frozenset[str]] = {
    "diff-scope": frozenset({"files"}),
    "forge-claim": frozenset(),
}

HOLDS = ("run", "head", "live")
COMMON_REQUIRED = ("id", "stage", "kind", "holds")
COMMON_OPTIONAL = ("in", "on", "max_visits", "mutates")
KIND_MEMBERS = {
    "command": (("command",), ("subcommand", "check")),
    "agent": (("role", "prompt", "reply", "outcome_from"), ()),
    "decide": (("grader",), ()),
    "group": (("members",), ()),
    "call": (("procedure",), ("each", "parallel")),
}
DEFAULT_VERDICTS = ("ok", "failed")


@dataclass(frozen=True)
class Refusal:
    procedure: str
    step: str | None
    defect: str
    detail: str

    def as_json(self) -> dict:
        return {"defect": self.defect, "detail": self.detail,
                "procedure": self.procedure, "step": self.step}


@dataclass(frozen=True)
class StepResolved:
    """What one step's references resolved to; `None` is unresolved or n/a."""

    outcomes: tuple[str, ...] | None = None
    reply_properties: frozenset[str] | None = None
    reply_required: frozenset[str] | None = None
    reply_lists: frozenset[str] | None = None
    child_stops: tuple[str, ...] | None = None
    prompt: str | None = None


@dataclass(frozen=True)
class Resolved:
    """The resolved references of one procedure (phase B), by step id."""

    steps: Mapping[str, StepResolved]
    keep_alive: tuple[str, ...] | None = None


@dataclass(frozen=True)
class CheckResult:
    procedures: tuple[str, ...]
    refusals: tuple[Refusal, ...]
    resolved: Mapping[str, Resolved]


class DeclarationError(Exception):
    """`command_verdicts.json` is not a valid declaration file."""


@dataclass(frozen=True)
class CommandDeclaration:
    """The two declared forms: `verdicts` (no subcommands) or `subcommands`."""

    verdicts: tuple[str, ...] | None
    subcommands: Mapping[str, tuple[str, ...]]

    def outcomes(self, subcommand: str | None) -> tuple[str, ...] | None:
        if self.verdicts is not None:
            return (self.verdicts or DEFAULT_VERDICTS) if subcommand is None else None
        if subcommand in self.subcommands:
            return self.subcommands[subcommand] or DEFAULT_VERDICTS
        return None


def _strict_load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the document is nested too deeply") from error


def _verdict_list(value: object, where: str) -> tuple[str, ...]:
    if (not isinstance(value, list) or not all(isinstance(item, str) and item for item in value)
            or len(set(value)) != len(value)):
        raise DeclarationError(f"{where}: verdicts are distinct non-empty strings")
    for reserved in (EXHAUSTED, OUT_OF_BOUNDS):
        if reserved in value:
            raise DeclarationError(f"{where}: {reserved!r} is reserved, not a verdict")
    return tuple(value)


def _declaration(key: str, value: object) -> CommandDeclaration | None:
    if value is None:
        return None
    if isinstance(value, dict) and list(value) == ["verdicts"]:
        return CommandDeclaration(_verdict_list(value["verdicts"], key), {})
    if isinstance(value, dict) and list(value) == ["subcommands"]:
        listed = value["subcommands"]
        if not isinstance(listed, dict) or not listed:
            raise DeclarationError(f"{key}: subcommands is a non-empty object")
        for subcommand in listed:
            if not NAME_RE.fullmatch(subcommand):
                raise DeclarationError(f"{key}: subcommand {subcommand!r} is not a name")
        return CommandDeclaration(None, {
            subcommand: _verdict_list(verdicts, f"{key} {subcommand}")
            for subcommand, verdicts in listed.items()})
    raise DeclarationError(f"{key}: null, {{\"verdicts\": [...]}} or {{\"subcommands\": {{...}}}} only")


def load_commands(path: Path | None = None) -> dict[str, CommandDeclaration | None]:
    path = path or Path(__file__).with_name("command_verdicts.json")
    try:
        document = _strict_load(path)
    except (OSError, ValueError) as error:
        raise DeclarationError(f"{path.name} is unreadable: {error}") from error
    if not isinstance(document, dict):
        raise DeclarationError(f"{path.name} is not an object")
    commands: dict[str, CommandDeclaration | None] = {}
    for key, value in document.items():
        if not NAME_RE.fullmatch(key):
            raise DeclarationError(f"{key!r} is not a command id")
        commands[key] = _declaration(key, value)
    return commands


class _Findings:
    def __init__(self, procedure: str) -> None:
        self.procedure = procedure
        self.refusals: list[Refusal] = []

    def add(self, defect: str, detail: str, step: str | None = None) -> None:
        self.refusals.append(Refusal(self.procedure, step, defect, detail))


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _members(obj: dict, required: tuple, optional: tuple, found: _Findings,
             step: str | None, where: str) -> None:
    for member in obj:
        if member not in required and member not in optional:
            found.add("undefined_field", f"{where} defines no member {member!r}.", step)
    for member in required:
        if member not in obj:
            found.add("invalid_field", f"{where} requires the member {member!r}.", step)


def _distinct_strings(value: object) -> bool:
    return (isinstance(value, list) and all(isinstance(item, str) for item in value)
            and len(set(value)) == len(value))


def _paths(value: object, only_run: bool, found: _Findings, step: str | None,
           where: str) -> None:
    if not _distinct_strings(value):
        found.add("invalid_field", f"{where} is a list of distinct paths.", step)
        return
    for path in value:
        match = PATH_RE.fullmatch(path)
        if match is None:
            found.add("invalid_field", f"{where} path {path!r} is not <step>.<member> or run.<input>.", step)
        elif only_run and match.group(1) != "run":
            found.add("invalid_field", f"{where} path {path!r} must be a run.<input> path.", step)


def _header(doc: dict, found: _Findings) -> None:
    _members(doc, ("format", "inputs", "stops", "steps"), ("keep_alive",), found, None, "a procedure")
    if "format" in doc and not (_is_int(doc["format"]) and doc["format"] == FORMAT):
        found.add("invalid_field", f"format must be the integer {FORMAT}.")
    if "keep_alive" in doc:
        keep_alive = doc["keep_alive"]
        if not isinstance(keep_alive, dict):
            found.add("invalid_field", "keep_alive must be an object.")
        else:
            _members(keep_alive, ("command", "in"), ("subcommand",), found, None, "keep_alive")
            for member in ("command", "subcommand"):
                if member in keep_alive and not (
                        isinstance(keep_alive[member], str) and NAME_RE.fullmatch(keep_alive[member])):
                    found.add("invalid_field", f"keep_alive {member} must match {NAME_RE.pattern}.")
            if "in" in keep_alive:
                _paths(keep_alive["in"], True, found, None, "keep_alive in")
    if "inputs" in doc:
        inputs = doc["inputs"]
        if not _distinct_strings(inputs) or not all(INPUT_RE.fullmatch(name) for name in inputs):
            found.add("invalid_field", f"inputs is a list of distinct names matching {INPUT_RE.pattern}.")


def _stops(doc: dict, ids: set[str], found: _Findings) -> None:
    stops = doc.get("stops")
    if "stops" not in doc:
        return
    if not isinstance(stops, dict):
        found.add("invalid_field", "stops must be an object.")
        return
    for name, stop in stops.items():
        if not NAME_RE.fullmatch(name):
            found.add("invalid_field", f"stop name {name!r} must match {NAME_RE.pattern}.")
        elif name in ("done", EXHAUSTED, OUT_OF_BOUNDS, QUOTA_WAIT) or name in ids:
            found.add("invalid_field",
                      f"stop name {name!r} is `done`, `{EXHAUSTED}`, `{OUT_OF_BOUNDS}`, `{QUOTA_WAIT}` or a step id.")
        if not isinstance(stop, dict):
            found.add("invalid_field", f"stop {name!r} must be an object.")
            continue
        _members(stop, ("need", "reenter"), (), found, None, f"stop {name!r}")
        if "need" in stop and stop["need"] not in NEEDS:
            found.add("invalid_field", f"stop {name!r} need must be one of {', '.join(NEEDS)}.")
        if "reenter" in stop and not _is_text(stop["reenter"]):
            found.add("invalid_field", f"stop {name!r} reenter must be a step id.")


@dataclass(frozen=True)
class _Layout:
    """What the step checks need to know about the whole list of steps."""

    listing: Mapping[str, int]
    targets: frozenset[str]


def _layout(doc: dict, steps: list) -> _Layout:
    listing: dict[str, int] = {}
    targets: set[str] = set()
    for item in steps:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "group" and isinstance(item.get("members"), list):
            for member in item["members"]:
                if isinstance(member, dict) and isinstance(member.get("step"), str):
                    listing[member["step"]] = listing.get(member["step"], 0) + 1
        if isinstance(item.get("on"), dict):
            targets.update(v for v in item["on"].values() if isinstance(v, str))
    if isinstance(doc.get("stops"), dict):
        for stop in doc["stops"].values():
            if isinstance(stop, dict) and isinstance(stop.get("reenter"), str):
                targets.add(stop["reenter"])
    return _Layout(listing, frozenset(targets))


def _file_name(value: object, suffix: str) -> bool:
    return (isinstance(value, str) and FILE_RE.fullmatch(value) is not None
            and value.endswith(suffix) and value != suffix)


def _kind_members(item: dict, kind: str, label: str | None, found: _Findings) -> None:
    def invalid(detail: str) -> None:
        found.add("invalid_field", detail, label)

    if kind == "command":
        if "command" in item and not (isinstance(item["command"], str) and NAME_RE.fullmatch(item["command"])):
            invalid("command must be a command id.")
        if "subcommand" in item and not (isinstance(item["subcommand"], str) and NAME_RE.fullmatch(item["subcommand"])):
            invalid(f"subcommand must match {NAME_RE.pattern}.")
        _check_member(item, label, found)
    elif kind == "agent":
        if "role" in item and not _is_text(item["role"]):
            invalid("role must be a non-empty string.")
        if "prompt" in item and not _file_name(item["prompt"], ".md"):
            invalid("prompt must be a bare *.md file name.")
        if "reply" in item and not _file_name(item["reply"], ".reply.json"):
            invalid("reply must be a bare *.reply.json file name.")
        if "outcome_from" in item and not _is_text(item["outcome_from"]):
            invalid("outcome_from must be a non-empty string.")
    elif kind == "decide":
        if "grader" in item and not _is_text(item["grader"]):
            invalid("grader must be a non-empty string.")
    elif kind == "group":
        _group_members(item, label, found)
    elif kind == "call":
        if "procedure" in item and not (isinstance(item["procedure"], str) and NAME_RE.fullmatch(item["procedure"])):
            invalid("procedure must be a procedure name.")
        if "each" in item and not (isinstance(item["each"], str) and item["each"] in _listed(item)):
            invalid("each must be one of the step's in paths.")
        if "parallel" in item and not (_is_int(item["parallel"]) and item["parallel"] >= 1 and "each" in item):
            invalid("parallel must be an integer >= 1 and needs each.")


def _check_member(item: dict, label: str | None, found: _Findings) -> None:
    """A command step's `check` pairs with `mutates`: a mutating step has one, no other does."""
    mutating = item.get("mutates") is True
    if "check" not in item:
        if mutating:
            found.add("invalid_field", "a command step that mutates needs a check.", label)
        return
    check = item["check"]
    if not mutating:
        found.add("invalid_field", "check belongs only to a command step whose mutates is true.", label)
    if not isinstance(check, dict):
        found.add("invalid_field", "check must be an object.", label)
        return
    _members(check, ("command",), ("subcommand",), found, label, "check")
    for member in ("command", "subcommand"):
        if member in check and not (isinstance(check[member], str) and NAME_RE.fullmatch(check[member])):
            found.add("invalid_field", f"check {member} must match {NAME_RE.pattern}.", label)


def _listed(item: dict) -> list:
    return item["in"] if isinstance(item.get("in"), list) else []


def _group_members(item: dict, label: str | None, found: _Findings) -> None:
    members = item.get("members")
    if "members" not in item:
        return
    if not isinstance(members, list) or not members:
        found.add("invalid_field", "members must be a non-empty list.", label)
        return
    for member in members:
        if not isinstance(member, dict):
            found.add("invalid_field", "a group member must be an object.", label)
            continue
        _members(member, ("step", "pass"), (), found, label, "a group member")
        if "step" in member and not (isinstance(member["step"], str) and NAME_RE.fullmatch(member["step"])):
            found.add("invalid_field", "a group member step must be a step id.", label)
        passing = member.get("pass")
        if "pass" in member and not (_distinct_strings(passing) and passing):
            found.add("invalid_field", "a group member pass is a non-empty list of distinct strings.", label)


def _step(item: dict, index: int, layout: _Layout, found: _Findings) -> None:
    label = item["id"] if isinstance(item.get("id"), str) else None
    kind = item.get("kind")
    every_kind = tuple(m for req, opt in KIND_MEMBERS.values() for m in req + opt)
    if isinstance(kind, str) and kind in KIND_MEMBERS:
        required, optional = KIND_MEMBERS[kind]
        _members(item, COMMON_REQUIRED + required, COMMON_OPTIONAL + optional,
                 found, label, "a step")
    else:
        _members(item, COMMON_REQUIRED, COMMON_REQUIRED + COMMON_OPTIONAL + every_kind,
                 found, label, "a step")
        if "kind" in item:
            found.add("invalid_field", f"kind must be one of {', '.join(KINDS)}.", label)
    if "id" in item and not (isinstance(item["id"], str) and NAME_RE.fullmatch(item["id"])
                             and item["id"] not in ("run", "done")):
        found.add("invalid_field", f"id must match {NAME_RE.pattern} and not be run or done.", label)
    if "stage" in item:
        if not isinstance(item["stage"], str):
            found.add("invalid_field", "stage must be a string.", label)
        elif item["stage"] not in STAGES:
            found.add("unknown_stage", f"stage {item['stage']!r} is not one of the ten stages.", label)
    if "in" in item:
        _paths(item["in"], False, found, label, "in")
    if "max_visits" in item and not (_is_int(item["max_visits"]) and item["max_visits"] >= 1):
        found.add("invalid_field", "max_visits must be an integer >= 1.", label)
    if "holds" in item and item["holds"] not in HOLDS:
        found.add("invalid_field", f"holds must be one of {', '.join(HOLDS)}.", label)
    if "mutates" in item and not isinstance(item["mutates"], bool):
        found.add("invalid_field", "mutates must be a boolean.", label)
    if "on" in item:
        on = item["on"]
        if not (isinstance(on, dict) and all(_is_text(k) and _is_text(v) for k, v in on.items())):
            found.add("invalid_field", "on maps outcome names to target names.", label)
    if isinstance(kind, str):
        _kind_members(item, kind, label, found)
    _group_member_rules(item, index, layout, found, label)


def _group_member_rules(item: dict, index: int, layout: _Layout, found: _Findings,
                        label: str | None) -> None:
    if label is not None and label in layout.listing:
        if layout.listing[label] > 1:
            found.add("invalid_field", "a group member is listed by exactly one group.", label)
        if item.get("kind") == "group":
            found.add("invalid_field", "a group member is not itself a group.", label)
        if index == 0:
            found.add("invalid_field", "a group member is not the first step.", label)
        if label in layout.targets:
            found.add("invalid_field", "a group member is never an on target or a stop reenter.", label)
        if "on" in item:
            found.add("invalid_field", "a group member has no on.", label)
    elif "on" not in item:
        found.add("invalid_field", "a step that is no group member requires on.", label)


def check_structure(name: str, doc: object) -> list[Refusal]:
    """Phase A: the shape of one decoded procedure, F2-F5."""
    found = _Findings(name)
    if not isinstance(doc, dict):
        found.add("unreadable_procedure", "the procedure is not a JSON object.")
        return found.refusals
    steps = doc.get("steps")
    listed = steps if isinstance(steps, list) else []
    ids = {item["id"] for item in listed if isinstance(item, dict) and isinstance(item.get("id"), str)}
    _header(doc, found)
    _stops(doc, ids, found)
    if "steps" in doc and (not isinstance(steps, list) or not steps):
        found.add("invalid_field", "steps must be a non-empty list.")
    layout = _layout(doc, listed)
    seen: set[str] = set()
    repeated: set[str] = set()
    for index, item in enumerate(listed):
        if not isinstance(item, dict):
            found.add("invalid_field", "a step must be an object.")
            continue
        label = item.get("id")
        if isinstance(label, str):
            if label in seen and label not in repeated:
                repeated.add(label)
                found.add("duplicate_step", f"the step id {label!r} is used more than once.", label)
            seen.add(label)
        _step(item, index, layout, found)
    return found.refusals


@dataclass(frozen=True)
class _Reply:
    properties: frozenset[str]
    required: frozenset[str]
    outcomes: tuple[str, ...]
    lists: frozenset[str]


def _reply_schema(path: Path, outcome_from: str, name: str) -> _Reply | tuple[str, str]:
    """The reply schema's facts, or the defect and its detail."""
    try:
        schema = _strict_load(path)
    except (OSError, ValueError) as error:
        return "invalid_reply", " ".join(f"the reply schema cannot be read as strict JSON: {error}".split())
    if not isinstance(schema, dict):
        return "invalid_reply", "the reply schema is not a JSON object."
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return "invalid_reply", "the reply schema has no properties object."
    required = schema.get("required")
    if not isinstance(required, list) or not all(isinstance(n, str) for n in required):
        return "invalid_reply", "the reply schema has no required list of strings."
    if outcome_from not in required:
        return "invalid_reply", f"the reply schema does not require {outcome_from!r}."
    outcome = properties.get(outcome_from)
    enum = outcome.get("enum") if isinstance(outcome, dict) else None
    if (not isinstance(enum, list) or not enum or not all(_is_text(v) for v in enum)
            or len(set(enum)) != len(enum)):
        return "invalid_reply", f"properties.{outcome_from} has no enum of distinct non-empty strings."
    for reserved in (EXHAUSTED, OUT_OF_BOUNDS, NO_REPLY):
        if reserved in enum:
            return "invalid_reply", f"properties.{outcome_from} enum names {reserved!r}, which is reserved."
    problem = schema_problem(schema)
    if problem:
        return "unsupported_reply", f"{name} uses {problem}, outside the reply schema subset."
    lists = frozenset(name for name, schema in properties.items()
                      if isinstance(schema, dict) and schema.get("type") == "array")
    return _Reply(frozenset(properties), frozenset(required), tuple(enum), lists)


def _command_outcomes(reference: dict, commands: Mapping[str, CommandDeclaration | None],
                      found: _Findings, step: str | None) -> tuple[str, ...] | None:
    command, subcommand = reference["command"], reference.get("subcommand")
    if command not in commands:
        found.add("unknown_command", f"{command!r} is not a command-table id.", step)
        return None
    declaration = commands[command]
    if declaration is None:
        found.add("undeclared_verdicts", f"{command!r} declares no verdicts yet.", step)
        return None
    if declaration.verdicts is not None and subcommand is not None:
        found.add("unknown_command", f"{command!r} has no subcommands.", step)
        return None
    outcomes = declaration.outcomes(subcommand)
    if outcomes is None:
        found.add("undeclared_verdicts",
                  f"{command!r} declares no verdicts for subcommand {subcommand!r}.", step)
    return outcomes


def _inside(directory: Path, name: str) -> Path | None:
    """The named file when it is a file that resolves inside `directory`."""
    path = directory / name
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return None
    return path


def _agent_references(item: dict, directory: Path, replies: dict[str, _Reply | tuple[str, str]],
                      found: _Findings, label: str) -> StepResolved:
    if item["role"] not in ROLES:
        found.add("unknown_role", f"{item['role']!r} is not one of {', '.join(ROLES)}.", label)
    prompt = None
    prompt_path = _inside(directory, item["prompt"])
    if prompt_path is None:
        found.add("missing_prompt", f"{item['prompt']!r} is not a file in the procedure directory.", label)
    else:
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            found.add("missing_prompt",
                      " ".join(f"{item['prompt']!r} cannot be read as UTF-8 text: {error}".split()), label)
    reply_path = _inside(directory, item["reply"])
    if reply_path is None:
        found.add("missing_reply", f"{item['reply']!r} is not a file in the procedure directory.", label)
        return StepResolved(prompt=prompt)
    key = f"{item['reply']}\0{item['outcome_from']}"
    if key not in replies:
        replies[key] = _reply_schema(reply_path, item["outcome_from"], item["reply"])
    reply = replies[key]
    if isinstance(reply, tuple):
        found.add(reply[0], reply[1], label)
        return StepResolved(prompt=prompt)
    return StepResolved(reply.outcomes, reply.properties, reply.required,
                        reply.lists, prompt=prompt)


def check_references(name: str, doc: dict, directory: Path,
                     commands: Mapping[str, CommandDeclaration | None],
                     child_stops: Mapping[str, tuple[str, ...]]) -> tuple[list[Refusal], Resolved]:
    """Phase B: what a structurally valid procedure refers to must exist, F9-F11."""
    found = _Findings(name)
    ids = {item["id"] for item in doc["steps"]}
    stops = set(doc["stops"])
    keep_alive = None
    if "keep_alive" in doc:
        keep_alive = _command_outcomes(doc["keep_alive"], commands, found, None)
        if CLAIM_LOST not in stops:
            found.add("missing_claim_lost",
                      f"keep_alive {doc['keep_alive']['command']!r} needs a stop {CLAIM_LOST!r}.")
    for stop_name, stop in doc["stops"].items():
        if stop["reenter"] not in ids:
            found.add("unknown_target", f"stop {stop_name!r} re-enters {stop['reenter']!r}, which is no step.")
    resolved: dict[str, StepResolved] = {}
    replies: dict[str, _Reply | tuple[str, str]] = {}
    for item in doc["steps"]:
        label, kind = item["id"], item["kind"]
        for outcome, target in item.get("on", {}).items():
            if target not in ids and target not in stops and target != "done":
                found.add("unknown_target",
                          f"on {outcome!r} goes to {target!r}, which is no step, stop or done.", label)
        step = StepResolved()
        if kind == "command":
            step = StepResolved(_command_outcomes(item, commands, found, label))
            if "check" in item:
                _command_outcomes(item["check"], commands, found, label)
        elif kind == "agent":
            step = _agent_references(item, directory, replies, found, label)
        elif kind == "decide":
            if item["grader"] in GRADERS:
                step = StepResolved(GRADERS[item["grader"]].outcomes)
            else:
                found.add("unknown_grader", f"{item['grader']!r} is not a grader.", label)
        elif kind == "group":
            for member in item["members"]:
                if member["step"] not in ids:
                    found.add("unknown_target", f"group member {member['step']!r} is no step.", label)
        elif kind == "call":
            if not (directory / f"{item['procedure']}.json").is_file():
                found.add("missing_procedure", f"{item['procedure']!r} is not in the procedure directory.", label)
            else:
                step = StepResolved(child_stops=child_stops.get(item["procedure"]))
        resolved[label] = step
    return found.refusals, Resolved(resolved, keep_alive)


def _load_procedure(path: Path) -> tuple[object | None, list[Refusal]]:
    """Read one file and run phase A on it."""
    name = path.stem
    if not NAME_RE.fullmatch(name):
        return None, [Refusal(name, None, "invalid_field",
                              f"the procedure name must match {NAME_RE.pattern}.")]
    if _inside(path.parent, path.name) is None:
        return None, [Refusal(name, None, "unreadable_procedure",
                              "the file does not resolve inside the procedure directory.")]
    try:
        doc = _strict_load(path)
    except (OSError, ValueError) as error:
        return None, [Refusal(name, None, "unreadable_procedure",
                              " ".join(f"the file cannot be read as strict JSON: {error}".split()))]
    return doc, check_structure(name, doc)


def check_directory(directory: Path,
                    commands: Mapping[str, CommandDeclaration | None]) -> CheckResult:
    files = sorted((p for p in directory.glob("*.json")
                    if p.is_file() and not p.name.endswith(".reply.json")),
                   key=lambda p: p.stem)
    if not files:
        raise ValueError(f"{directory} holds no procedure file")
    loaded = {path.stem: _load_procedure(path) for path in files}
    child_stops = {name: tuple(doc["stops"]) for name, (doc, found) in loaded.items()
                   if not found}
    refusals: list[Refusal] = []
    resolved: dict[str, Resolved] = {}
    for name, (doc, found) in loaded.items():
        if found:
            refusals.extend(found)
            continue
        found, resolved[name] = check_references(name, doc, directory, commands, child_stops)
        refusals.extend(found)
        if not any(r.defect == "unknown_target" for r in found):
            refusals.extend(check_graph(name, doc, resolved[name]))
    return CheckResult(tuple(p.stem for p in files), tuple(refusals), resolved)


def outcomes_of(step: dict, resolved: Resolved) -> tuple[str, ...] | None:
    """The outcomes a step can produce but `exhausted`; `None` when unresolved. An agent step also produces `no-reply`."""
    kind = step["kind"]
    if kind == "group":
        return ("pass", "blocked")
    known = resolved.steps[step["id"]]
    if kind == "call":
        return None if known.child_stops is None else ("done",) + tuple(known.child_stops)
    if kind == "agent" and known.outcomes is not None:
        return known.outcomes + (NO_REPLY,)
    if kind == "command" and known.outcomes is not None:
        return known.outcomes + (REFUSED,)
    return known.outcomes


def _members_of(procedure: dict) -> set[str]:
    return {member["step"] for item in procedure["steps"] if item["kind"] == "group"
            for member in item["members"]}


def step_graph(procedure: dict) -> dict[str, tuple[str, ...]]:
    """Non-member step -> the step targets of its `on` entries but `exhausted`."""
    members = _members_of(procedure)
    ids = {item["id"] for item in procedure["steps"]} - members
    return {item["id"]: tuple(target for outcome, target in item["on"].items()
                              if outcome != EXHAUSTED and target in ids)
            for item in procedure["steps"] if item["id"] not in members}


def _reach(graph: Mapping[str, tuple[str, ...]], start: str) -> set[str]:
    """The nodes reachable from `start` by one or more edges."""
    seen: set[str] = set()
    pending = list(graph.get(start, ()))
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(graph.get(node, ()))
    return seen


def on_cycle(graph: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    """The steps in a strongly connected set of two or more, or with a self-edge."""
    return frozenset(node for node in graph if node in _reach(graph, node))


def stop_closed_graph(procedure: dict) -> dict[str, tuple[str, ...]]:
    """`step_graph` plus, for each step with an `on` entry to a stop, an edge to the stop's
    re-entry step when that step does not dominate it. Such a step may never have been
    reached, so continuing enters it fresh and keeps every visit already spent; that step
    then leads to it (an over-approximation: the re-entry step itself may never run past
    its bound)."""
    graph = step_graph(procedure)
    members = _members_of(procedure)
    group_of = {member["step"]: item["id"] for item in procedure["steps"]
                if item["kind"] == "group" for member in item["members"]}
    stops = procedure["stops"]
    routes = {item["id"]: tuple(t for t in item["on"].values() if t != "done")
              for item in procedure["steps"] if item["id"] not in members}
    routes.update({name: (stop["reenter"],) for name, stop in stops.items()})
    dom = dominators(routes, procedure["steps"][0]["id"])
    closed = {node: set(targets) for node, targets in graph.items()}
    for item in procedure["steps"]:
        for outcome, stop in item.get("on", {}).items():
            if item["id"] not in dom or outcome == EXHAUSTED or stop not in stops:
                continue
            reenter = stops[stop]["reenter"]
            fresh = group_of.get(reenter, reenter)
            if fresh in graph and reenter not in dom[item["id"]]:
                closed[item["id"]].add(fresh)
    return {node: tuple(targets) for node, targets in closed.items()}


def exhaustible(procedure: dict) -> frozenset[str]:
    """The steps that can be entered past their bound: on a cycle of `stop_closed_graph`."""
    return on_cycle(stop_closed_graph(procedure))


def _changing_steps(procedure: dict) -> set[str]:
    """The ids of the `mutates` steps and of the groups with a `mutates` member."""
    changing = {item["id"] for item in procedure["steps"] if item.get("mutates")}
    changing |= {item["id"] for item in procedure["steps"]
                 if changing.intersection(m["step"] for m in item.get("members", ()))}
    return changing


def flow_graph(procedure: dict) -> dict[str, tuple[str, ...]]:
    """Steps and stops -> where control can go (`START` to the first step), `done` and dead `exhausted` left out.

    A node entering a `mutates` step of a procedure with a `keep_alive` and a `claim-lost` stop also goes to that stop.
    """
    members = _members_of(procedure)
    cyclic = exhaustible(procedure)
    renews = "keep_alive" in procedure and CLAIM_LOST in procedure["stops"]
    changing = _changing_steps(procedure)
    graph: dict[str, tuple[str, ...]] = {START: (procedure["steps"][0]["id"],)}
    for item in procedure["steps"]:
        if item["id"] in members:
            continue
        graph[item["id"]] = tuple(
            target for outcome, target in item["on"].items()
            if target != "done" and (outcome != EXHAUSTED or item["id"] in cyclic))
    for name, stop in procedure["stops"].items():
        graph[name] = (stop["reenter"],)
    for node, targets in graph.items():
        if renews and changing.intersection(targets):
            graph[node] = targets + (CLAIM_LOST,)
    return graph


def result_flow_graph(procedure: dict) -> dict[str, tuple[str, ...]]:
    """`flow_graph` with a `(result)` node after each step whose `on` maps `out-of-bounds` or, for an agent step, `no-reply`.

    The step's node keeps its `out-of-bounds` and `no-reply` edges (unless their target is `done`) and goes to
    `<id>(result)`, which stands for the step having ended by a normal outcome and carries the step's other outcome
    edges. A route through the step's own node alone is one on which the step ended by a bound or with no reply and
    stored no member of this visit (a bound stores `{"bound": ...}`, no reply stores `{}`).

    The `exhausted` edge of a step on a cycle is taken on an entry after a visit ended, and a visit's result is
    kept until the next one replaces it, so it hangs on `<id>(result)`: the previous visit ended by a normal outcome.
    It hangs on the step's own node too only when its `out-of-bounds` or `no-reply` target leads back to the step
    through steps, the one way the previous visit can have ended with no member stored.
    """
    members = _members_of(procedure)
    cyclic = exhaustible(procedure)
    renews = "keep_alive" in procedure and CLAIM_LOST in procedure["stops"]
    changing = _changing_steps(procedure)
    graph = flow_graph(procedure)
    steps_only = step_graph(procedure)

    def renewing(targets: tuple[str, ...]) -> tuple[str, ...]:
        return targets + (CLAIM_LOST,) if renews and changing.intersection(targets) else targets

    for item in procedure["steps"]:
        if item["id"] in members or item["kind"] not in ("agent", "command"):
            continue
        bare = {OUT_OF_BOUNDS} | ({NO_REPLY} if item["kind"] == "agent" else set())
        if not bare.intersection(item["on"]):
            continue
        name = item["id"]
        result_node = f"{name}(result)"
        bare_targets = tuple(dict.fromkeys(
            target for outcome, target in item["on"].items() if outcome in bare and target != "done"))
        bare_returns = any(target == name or name in _reach(steps_only, target) for target in bare_targets)
        exhausted = tuple(target for outcome, target in item["on"].items()
                          if outcome == EXHAUSTED and target != "done" and name in cyclic)
        graph[name] = renewing(bare_targets + (exhausted if bare_returns else ()) + (result_node,))
        graph[result_node] = renewing(tuple(
            target for outcome, target in item["on"].items()
            if outcome not in bare | {EXHAUSTED} and target != "done") + exhausted)
    return graph


def dominators(graph: Mapping[str, tuple[str, ...]], entry: str) -> dict[str, frozenset[str]]:
    """Node -> the nodes on every route from `entry` to it, itself included."""
    nodes = {entry} | _reach(graph, entry)
    predecessors: dict[str, list[str]] = {node: [] for node in nodes}
    for node in nodes:
        for target in graph.get(node, ()):
            predecessors[target].append(node)
    dom = {node: frozenset(nodes) for node in nodes}
    dom[entry] = frozenset({entry})
    changed = True
    while changed:
        changed = False
        for node in nodes - {entry}:
            common = frozenset.intersection(*(dom[p] for p in predecessors[node]))
            updated = common | {node}
            if updated != dom[node]:
                dom[node] = updated
                changed = True
    return dom


def _check_data_flow(procedure: dict, resolved: Resolved, found: _Findings) -> None:
    graph = result_flow_graph(procedure)
    by_id = {item["id"]: item for item in procedure["steps"]}
    group_of = {member["step"]: item["id"] for item in procedure["steps"]
                if item["kind"] == "group" for member in item["members"]}
    dom = dominators(graph, START)
    inputs = set(procedure["inputs"])

    def check_path(path: str, step: dict | None) -> bool:
        """Report a path that does not resolve; true when it resolved."""
        refused = len(found.refusals)
        label = None if step is None else step["id"]
        producer, member = path.split(".", 1)
        if producer == "run":
            if member not in inputs:
                found.add("unproduced_input", f"{path!r} is not an input of the procedure.", label)
            return len(found.refusals) == refused
        if step is not None:
            owner = group_of.get(label, label)
            if owner in dom:
                before = dom[owner] - {owner}
                node = group_of.get(producer, producer)
                if f"{node}(result)" in graph:
                    node = f"{node}(result)"
                if producer not in by_id or node not in before:
                    found.add("unproduced_input",
                              f"{path!r} is not produced on every route to the step.", label)
        known = resolved.steps.get(producer)
        if (producer in by_id and by_id[producer]["kind"] == "agent"
                and known is not None and known.reply_properties is not None
                and known.reply_required is not None
                and (member not in known.reply_properties or member not in known.reply_required)):
            found.add("unknown_member",
                      f"{path!r} is not a member the reply of {producer!r} always carries.", label)
        elif producer in by_id and by_id[producer]["kind"] == "decide" and member != "verdict":
            found.add("unknown_member",
                      f"{path!r} is not a member the result of {producer!r} carries; a decide step publishes only 'verdict'.",
                      label)
        return len(found.refusals) == refused

    def is_list(path: str) -> bool:
        """Whether a resolved path reads a list; a producer with no schema is taken as one."""
        producer, member = path.split(".", 1)
        if producer == "run":
            return False
        kind = by_id[producer]["kind"] if producer in by_id else None
        if kind == "decide":
            return False
        if kind == "command" and by_id[producer]["command"] in PLATFORM_LISTS:
            return member in PLATFORM_LISTS[by_id[producer]["command"]]
        known = resolved.steps.get(producer)
        if kind == "agent" and known is not None and known.reply_lists is not None:
            return member in known.reply_lists
        return True

    for path in procedure.get("keep_alive", {}).get("in", ()):
        check_path(path, None)
    for item in procedure["steps"]:
        reads = item.get("in", [])
        resolved_reads = {path: check_path(path, item) for path in reads}
        each = item.get("each") if item["kind"] == "call" else None
        if resolved_reads.get(each) and not is_list(each):
            found.add("each_not_a_list", f"{each!r} is not a list the producer publishes.", item["id"])
        prompt = resolved.steps[item["id"]].prompt
        if item["kind"] == "agent" and prompt is not None:
            for name in dict.fromkeys(PLACEHOLDER_RE.findall(prompt)):
                if name not in reads:
                    found.add("unknown_placeholder",
                              f"the prompt names {{{{{name}}}}}, which is not an in path.", item["id"])


def _check_reachability(procedure: dict, found: _Findings) -> None:
    members = _members_of(procedure)
    graph = flow_graph(procedure)
    cyclic = exhaustible(procedure)
    reached = {START} | _reach(graph, START)
    group_of = {member["step"]: item["id"] for item in procedure["steps"]
                if item["kind"] == "group" for member in item["members"]}
    reaches_done = any(
        item["id"] in reached and item["id"] not in members
        and any(target == "done" and (outcome != EXHAUSTED or item["id"] in cyclic)
                for outcome, target in item["on"].items())
        for item in procedure["steps"])
    if not reaches_done:
        found.add("unreachable_done", "no reachable step has an on entry to done.")
    for item in procedure["steps"]:
        owner = group_of.get(item["id"], item["id"])
        if owner not in reached:
            found.add("unreachable_step",
                      f"no path from the first step reaches {item['id']!r}.", item["id"])


def _check_outcomes(procedure: dict, resolved: Resolved, found: _Findings) -> None:
    cyclic = exhaustible(procedure)
    by_id = {item["id"]: item for item in procedure["steps"]}
    members = _members_of(procedure)
    for item in procedure["steps"]:
        label = item["id"]
        produced = outcomes_of(item, resolved)
        if produced is None:
            continue
        if item["kind"] == "group":
            for member in item["members"]:
                member_outcomes = outcomes_of(by_id[member["step"]], resolved)
                if member_outcomes is None:
                    continue
                if REFUSED in member["pass"]:
                    found.add("unknown_outcome",
                              f"member {member['step']!r} passes on 'refused', which never passes a group.",
                              label)
                stray = [o for o in member["pass"]
                         if o == NO_REPLY or (o not in member_outcomes and o != REFUSED)]
                if stray:
                    found.add("unknown_outcome",
                              f"member {member['step']!r} cannot produce {', '.join(map(repr, stray))}.",
                              label)
        if label in members:
            continue
        producible = (set(produced) | ({EXHAUSTED} if label in cyclic else set())
                      | ({OUT_OF_BOUNDS} if item["kind"] == "agent" else set()))
        unmapped = [o for o in sorted(producible, key=(*produced, OUT_OF_BOUNDS, EXHAUSTED).index)
                    if o not in item["on"]]
        if unmapped:
            found.add("unmapped_outcome",
                      f"on does not map {', '.join(map(repr, unmapped))}.", label)
        unknown = [o for o in item["on"] if o not in producible and o != EXHAUSTED
                   and not (o == OUT_OF_BOUNDS and item["kind"] in ("agent", "command"))]
        if unknown:
            found.add("unknown_outcome",
                      f"on maps {', '.join(map(repr, unknown))}, which the step cannot produce.", label)


def _loop_heads(graph: Mapping[str, tuple[str, ...]], order: list[str]) -> list[str]:
    """The first step, in `order`, of each loop of `graph`."""
    looping = on_cycle(graph)
    heads = []
    for node in order:
        loop = {other for other in looping if other == node
                or (other in _reach(graph, node) and node in _reach(graph, other))}
        if node in looping and node == next(other for other in order if other in loop):
            heads.append(node)
    return heads


def _check_cycles(procedure: dict, found: _Findings) -> None:
    graph = stop_closed_graph(procedure)
    bounded = {item["id"] for item in procedure["steps"] if "max_visits" in item}
    unbounded = {node: tuple(t for t in targets if t not in bounded)
                 for node, targets in step_graph(procedure).items() if node not in bounded}
    refused: dict[str, str] = {}
    order = [item["id"] for item in procedure["steps"]]
    by_id = {item["id"]: item for item in procedure["steps"]}
    for node in _loop_heads(unbounded, order):
        refused[node] = "it is on a cycle in which no step declares max_visits."
    for item in procedure["steps"]:
        label = item["id"]
        target = item["on"].get(EXHAUSTED) if "on" in item else None
        if (label in on_cycle(graph) and label not in refused and target in graph
                and (target == label or label in _reach(graph, target))):
            refused[label] = f"its exhausted target {target!r} re-enters the loop it ends."
    live = on_cycle(graph)
    spent = {node: targets + ((by_id[node]["on"][EXHAUSTED],)
                              if node in live and by_id[node]["on"].get(EXHAUSTED) in graph else ())
             for node, targets in graph.items()}
    for node in order:
        target = by_id[node]["on"].get(EXHAUSTED) if node in live else None
        if target not in graph or node not in _reach(spent, target) | {target}:
            continue
        loop = {other for other in spent if other == node
                or (other in _reach(spent, node) and node in _reach(spent, other))}
        if not loop & refused.keys():
            refused[node] = "its exhausted outcomes hand control around a loop that never ends."
    for item in procedure["steps"]:
        if item["id"] in refused:
            found.add("unbounded_cycle", refused[item["id"]], item["id"])


def check_graph(name: str, doc: dict, resolved: Resolved) -> list[Refusal]:
    """Phase C, graph part: reachability, outcomes and cycles, F7 and F11."""
    found = _Findings(name)
    _check_reachability(doc, found)
    _check_outcomes(doc, resolved, found)
    _check_cycles(doc, found)
    _check_data_flow(doc, resolved, found)
    position = {item["id"]: index for index, item in enumerate(doc["steps"])}
    return sorted(found.refusals,
                  key=lambda r: (-1 if r.step is None else position[r.step]))
