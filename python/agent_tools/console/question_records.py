"""The records document of one project: the file a project question session reads (#1271, ADR-console-089).

Why. A project question ("what did this project spend", "why did the run fail") is answered by a
read-only session (project_question.py). Its own tools reach only the project's files, so the console
hands it the console's own records of that one project as one JSON document. This module builds that
document from rows and states the caller already holds; it reads no clock, file or environment, so
the same arguments give the same document.

Shape. `project_records(project_id, *, root, events, spend, live_runs, sprint_states, inbox,
written_at)` returns the dict below, every key always present, and `encode` writes it as
`json.dumps(records, indent=1, sort_keys=True, ensure_ascii=False)` plus a newline. A `<figure>` is
`figure(tokens)`: `{"tokens", "dollars", "approximate"}`, and every "tokens, dollars, approximate"
below is a figure merged into its entry.

    {"project_id", "written_at",
     "spend": null | {"note": SPEND_NOTE, "first_day", "last_day",
         "days":    [{"day", tokens...}],          # every day of the view, oldest first
         "runs":    [{"run_id", "issues": [int], tokens..., "phases": {<phase>: <figure>},
                      "days": {<day>: <figure>}}],  # tokens above 0, most tokens first, then run id
         "issues":  [{"issue", tokens..., "runs": [id], "shared_runs": [id]}],
         "sprints": [{"sprint_id", "title", tokens..., "phases": {<phase>: <figure>}}]},
     "sprints":     [{"sprint_id", "title", "goal", "stated_at", "ended_at", "stop_reason",
                      "report": null | {"at", "status", "phase", "next_step",
                                        "issues": [{"issue", "status"}]},
                      "closing": null | {"at", "first_line", "issues": [{"issue", "status"}]}}],
     "deliveries":  [{"run_id", "session_id", "first_seen_at", "last_seen_at", "moved_at", "live",
                      "issues": [{"issue", "stage"}]}],     # newest row first
     "activations": [{"commit", "state", "started_at", "finished_at", "reason", "next_step"}],
     "held_checks": [{"key", "issue", "reason", "kind", "question", "detail", "waiting_since",
                      "answered", "answered_at", "wait"}]}

Ownership of a path (ADR-console-089 D3). A checkout path can be registered to another project later,
and the activation rows name a path and the spend view is attributed by today's registry, so neither
says who owned the path when it was observed. The rows' registrations are folded in `seq` order
(`project.registered` carries the root, `project.unregistered` ends it): the newest row at which a
project other than `project_id` stopped owning `root` is its predecessor's end. Activation rows at or
before that `seq` are not counted, and neither are spend days up to and including that row's UTC date
(a day shared with a predecessor is not counted, so a figure is never the predecessor's); `days` still
lists those days, with zero figures. Retention keeps the newest activation rows whatever their age, so it
keeps every registration row (`event_log`, #1271) and the unregistration that ends one: the evidence
of who owned a path lasts as long as the activation rows that name it. A registration row from before that
rule may already be gone from an older log; an activation row at or before the seq of `project_id`'s own
earliest retained registration at `root` is not counted either, since the project cannot have owned the path
before it was registered there. With neither bound nothing is dropped.

Scope (ADR-console-089 D3, D4). Every section holds only rows, keys and ids of `project_id`. A `delivery.seen` row counts
only when its project column is `project_id`. The activation rows have no project column, so one
counts only when its payload's `root` equals `root`. A sprint counts only when its `project_id` is
`project_id`, an inbox record only when `key[0]` is. The spend figures come only from
`day["project"][project_id]` and `day["project_items"][project_id]`, because a run id is unique only
within a project; a run id another project also uses never adds to these figures. An issue's tokens
sum only the runs whose issues are exactly that one issue; the runs that named it with others are its
`shared_runs`. A run's `issues` are the sorted union of the issues the project's delivery rows name
for that run id under any session, `[]` when none is retained. `spend` is None when the view is None,
and the rest is still written.

Deliveries. The rows are walked in `seq` order and parsed by `deliveries.delivery_states`; a row that
gives no state is skipped. A run is one `(session_id, run_id)`; its state is its last row's, and its
`first_seen_at` and `last_seen_at` are the `at` of its first and last row. `live` (ADR-console-089 D3) is
`(session_id, run_id) in live_runs`, the service's own answer from its current fold and its sessions,
never inferred from the rows (a run of an ended session never gets a `delivery.gone` row). Any other
recorded run is listed with `live` false and its last stage.

Activations (ADR-console-089 D3). The rows of the project's root, in `seq` order, folded as `activation_run.fold`
does: a started row opens an entry `running`; a finished row with a bool `ok` settles the newest open
entry of its commit as `activated` or `failed`, or opens a settled one with `started_at` None. They
are the console's record of why a production run failed. Newest first.

Held checks. An inbox item whose `reason` starts with `HELD_PREFIX` or equals `inbox.REVIEW_REASON`;
a tracker `decision` item is not one. `waiting_since` and `answered_at` are the `InboxRecord`'s own
attributes. Ordered by `(waiting_since, key)`.

Sections (ADR-console-090). `SECTIONS` names the five top-level members a session reads alone, in the
order the prompt lists them. `section_lines(text)` gives, for each of them that `encode` wrote as a
top-level member of `text`, `(offset, limit)` for Read: `offset` is the 1-based number of the line that
starts the member (exactly one space, then `"<name>": `) and `limit` the lines up to, not including, the
next top-level member or the closing brace. Lines are counted by `text.split("\n")`, never
`splitlines()`: `encode` keeps U+2028, U+2029 and U+0085 raw inside a string and Read counts only LF.
It reads no JSON, never raises for any `str`, and gives a name that is not present no key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent_tools.console import deliveries, inbox as inbox_module, spend as spend_module, sprints
from agent_tools.console.event_log import (
    ACTIVATION_FINISHED, ACTIVATION_STARTED, PROJECT_REGISTERED as REGISTERED, PROJECT_UNREGISTERED, Event)

if TYPE_CHECKING:
    from agent_tools.console.view import InboxRecord

HELD_PREFIX = "verify-"
SPEND_NOTE = (
    "Tokens sum input, cache writes, cache reads and output; dollars are estimates at API list "
    "prices. A run's spend counts once, under that run; an issue's tokens count only the runs that "
    "delivered that issue alone, and shared_runs lists the runs that delivered it with other issues.")


def _earlier_owner_left(rows: Iterable[Event], project_id: str, root: str) -> Event | None:
    """The newest row at which a project other than `project_id` stopped owning `root`, else None.

    The rows are folded in `seq` order into each project's registered root: a registration of another
    project under a different root, or its unregistration, while it held `root` ends its ownership; an
    unregistration names the root it ended in its payload, else the root the fold holds for the project.
    A registration names only the new root, so when retention pruned the registration that put the
    other project at `root`, its move away is told only by being the newest registration of another
    project under a different root before `project_id`'s own earliest registration at `root`, and only
    when an activation row of `root` precedes that registration: nothing else shows that anyone held
    `root` first, and without it a project registered after another owes that one nothing.
    """
    roots: dict[str, str] = {}
    left = None
    moved = before_own = None
    own_seen = root_used = False
    for event in rows:
        other = event.project
        if event.kind in (ACTIVATION_STARTED, ACTIVATION_FINISHED):
            root_used = root_used or (isinstance(event.payload, dict) and event.payload.get("root") == root)
        if event.kind == REGISTERED and isinstance(other, str):
            now = event.payload.get("root") if isinstance(event.payload, dict) else None
            if other != project_id and roots.get(other) == root and now != root:
                left = event
            if other != project_id and isinstance(now, str) and now != root:
                moved = event
            elif other == project_id and now == root and not own_seen:
                own_seen, before_own = True, moved if root_used else None
            if isinstance(now, str):
                roots[other] = now
        elif event.kind == PROJECT_UNREGISTERED and isinstance(other, str):
            named = event.payload.get("root") if isinstance(event.payload, dict) else None
            if other != project_id and (named if isinstance(named, str) and named else roots.get(other)) == root:
                left = event
            roots.pop(other, None)
    return left or before_own


def _owned_since(rows: Iterable[Event], project_id: str, root: str) -> int:
    """The `seq` of `project_id`'s earliest retained registration at `root`, else 0."""
    for event in rows:
        if (event.kind == REGISTERED and event.project == project_id
                and isinstance(event.payload, dict) and event.payload.get("root") == root):
            return event.seq
    return 0


def figure(tokens: spend_module.Tokens) -> dict:
    return {"tokens": tokens.input + tokens.cache_write + tokens.cache_read + tokens.output,
            "dollars": round(tokens.dollars, 2), "approximate": tokens.approximate}


def encode(records: Mapping) -> str:
    return json.dumps(records, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


SECTIONS = ("spend", "sprints", "deliveries", "activations", "held_checks")
_MEMBER = re.compile(r' "([^"]+)": ')


def section_lines(text: str) -> dict[str, tuple[int, int]]:
    lines = text.split("\n")
    found: dict[str, tuple[int, int]] = {}
    opened: tuple[str, int] | None = None
    for number, line in enumerate(lines, 1):
        if opened is not None and (line.startswith(' "') or line == "}"):
            name, start = opened
            if name in SECTIONS:
                found[name] = (start, number - start)
            opened = None
        if opened is None and (match := _MEMBER.match(line)):
            opened = (match.group(1), number)
    return found


def _total(parts: Iterable[spend_module.Tokens]) -> spend_module.Tokens:
    total = spend_module.Tokens()
    for part in parts:
        total += part
    return total


def _ranked(entries: list[dict], name: str) -> list[dict]:
    return sorted(entries, key=lambda entry: (-entry["tokens"], entry[name]))


def _item_phases(day: Mapping, project_id: str, kind: str) -> dict:
    items = day.get("project_items", {}).get(project_id, {}).get(kind, {})
    return {item: {phase: spend_module.Tokens(**wire) for phase, wire in phases.items()}
            for item, phases in items.items()}


def _spend(project_id: str, view: Mapping, run_issues: Mapping[str, list[int]],
           sprint_states: Mapping[str, sprints.SprintState], after_day: str | None = None) -> dict:
    days = view["days"]
    counted = [after_day is None or day["day"] > after_day for day in days]
    run_phases: dict[str, dict[str, list]] = {}
    run_days: dict[str, dict[str, list]] = {}
    sprint_phases: dict[str, dict[str, list]] = {}
    for day, kept in zip(days, counted):
        if not kept:
            continue
        for run, phases in _item_phases(day, project_id, "run").items():
            for phase, tokens in phases.items():
                run_phases.setdefault(run, {}).setdefault(phase, []).append(tokens)
                run_days.setdefault(run, {}).setdefault(day["day"], []).append(tokens)
        for sprint_id, phases in _item_phases(day, project_id, "sprint").items():
            for phase, tokens in phases.items():
                sprint_phases.setdefault(sprint_id, {}).setdefault(phase, []).append(tokens)
    runs = []
    for run, phases in run_phases.items():
        total = _total(t for parts in phases.values() for t in parts)
        if figure(total)["tokens"] <= 0:
            continue
        runs.append({
            "run_id": run, "issues": run_issues.get(run, []), **figure(total),
            "phases": {phase: figure(_total(parts)) for phase, parts in sorted(phases.items())},
            "days": {name: figure(_total(parts)) for name, parts in sorted(run_days[run].items())}})
    runs = _ranked(runs, "run_id")
    by_issue: dict[int, dict[str, list]] = {}
    for entry in runs:
        for issue in entry["issues"]:
            by_issue.setdefault(issue, {"alone": [], "shared": []})[
                "alone" if entry["issues"] == [issue] else "shared"].append(entry)
    issues = [{"issue": issue, **figure(_total(
                  spend_module.Tokens(input=e["tokens"], dollars=e["dollars"],
                                      approximate=e["approximate"]) for e in groups["alone"])),
               "runs": [e["run_id"] for e in groups["alone"]],
               "shared_runs": [e["run_id"] for e in groups["shared"]]}
              for issue, groups in by_issue.items()]
    sprint_entries = []
    for sprint_id, phases in sprint_phases.items():
        total = _total(t for parts in phases.values() for t in parts)
        if figure(total)["tokens"] <= 0:
            continue
        state = sprint_states.get(sprint_id)
        own = state is not None and state.project_id == project_id
        sprint_entries.append({
            "sprint_id": sprint_id, "title": sprints.sprint_title(state) if own else None,
            **figure(total),
            "phases": {phase: figure(_total(parts)) for phase, parts in sorted(phases.items())}})
    names = [day["day"] for day in days]
    return {
        "note": SPEND_NOTE, "first_day": names[0] if names else None,
        "last_day": names[-1] if names else None,
        "days": [{"day": day["day"], **figure(spend_module.Tokens(
                    **(day["project"].get(project_id, spend_module.Tokens().wire()) if kept
                       else spend_module.Tokens().wire())))}
                 for day, kept in zip(days, counted)],
        "runs": runs,
        "issues": sorted(issues, key=lambda entry: (-entry["tokens"], entry["issue"])),
        "sprints": _ranked(sprint_entries, "sprint_id")}


def _pairs(rows: Iterable[tuple[int, str]]) -> list[dict]:
    return [{"issue": issue, "status": status} for issue, status in rows]


def _sprint_entry(state: sprints.SprintState) -> dict:
    report, closing = state.report, state.closing
    return {
        "sprint_id": state.sprint_id, "title": sprints.sprint_title(state), "goal": state.goal,
        "stated_at": state.stated_at, "ended_at": sprints.ended_at(state),
        "stop_reason": state.stop_reason,
        "report": None if report is None else {
            "at": report.at, "status": report.status, "phase": report.phase,
            "next_step": report.next_step, "issues": _pairs(report.issues)},
        "closing": None if closing is None else {
            "at": closing.at, "first_line": closing.first_line, "issues": _pairs(closing.issues)}}


def _moved_at(moved_ms: int) -> str:
    return datetime.fromtimestamp(moved_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def _deliveries(rows: list[Event], live_runs: Collection[tuple[str, str]]) -> list[dict]:
    runs: dict[tuple[str, str], dict] = {}
    for event in rows:
        parsed = deliveries.delivery_states([event])
        if not parsed:
            continue
        (key, state), = parsed.items()
        entry = runs.get(key)
        runs[key] = {
            "run_id": state.run_id, "session_id": state.session_id,
            "first_seen_at": event.at if entry is None else entry["first_seen_at"],
            "last_seen_at": event.at, "moved_at": _moved_at(state.moved_ms), "live": key in live_runs,
            "issues": [{"issue": i.issue, "stage": deliveries.stage_text(i)} for i in state.issues],
            "_seq": event.seq}
    ordered = sorted(runs.values(), key=lambda entry: -entry["_seq"])
    return [{k: v for k, v in entry.items() if k != "_seq"} for entry in ordered]


def _activations(events: Iterable[Event], root: str, after_seq: int = 0) -> list[dict]:
    entries: list[dict] = []
    for event in events:
        if event.kind not in (ACTIVATION_STARTED, ACTIVATION_FINISHED) or event.seq <= after_seq:
            continue
        payload = event.payload
        if not isinstance(payload, dict) or payload.get("root") != root:
            continue
        commit = payload.get("commit")
        if not isinstance(commit, str):
            continue
        if event.kind == ACTIVATION_STARTED:
            entries.append({"commit": commit, "state": "running", "started_at": event.at,
                            "finished_at": None, "reason": None, "next_step": None,
                            "_seq": event.seq})
            continue
        ok = payload.get("ok")
        if not isinstance(ok, bool):
            continue
        text = lambda name: payload[name] if isinstance(payload.get(name), str) else None  # noqa: E731
        settled = {"state": "activated" if ok else "failed", "finished_at": event.at,
                   "reason": text("reason"), "next_step": text("next_step"), "_seq": event.seq}
        open_entry = next((e for e in reversed(entries)
                           if e["commit"] == commit and e["state"] == "running"), None)
        if open_entry is None:
            entries.append({"commit": commit, "started_at": None, **settled})
        else:
            open_entry.update(settled)
    ordered = sorted(entries, key=lambda entry: -entry["_seq"])
    return [{k: v for k, v in entry.items() if k != "_seq"} for entry in ordered]


def _held(record: "InboxRecord") -> dict:
    item = record.item
    wait = item.get("wait")
    return {
        **{name: item.get(name) for name in ("key", "issue", "reason", "kind", "question", "detail")},
        "waiting_since": record.waiting_since, "answered": item.get("answered") is True,
        "answered_at": record.answered_at, "wait": wait if isinstance(wait, Mapping) else None}


def _is_held(item: Mapping) -> bool:
    reason = item.get("reason")
    return isinstance(reason, str) and (
        reason.startswith(HELD_PREFIX) or reason == inbox_module.REVIEW_REASON)


def project_records(
    project_id: str, *, root: str, events: Iterable[Event], spend: Mapping | None,
    live_runs: Collection[tuple[str, str]], sprint_states: Mapping[str, sprints.SprintState],
    inbox: Mapping[tuple[str, str], "InboxRecord"], written_at: str,
) -> dict:
    """The records of `project_id` (see the module docstring); `root` is its checkout root."""
    rows = sorted(events, key=lambda event: event.seq)
    seen_rows = [e for e in rows if e.kind == deliveries.DELIVERY_SEEN and e.project == project_id]
    run_issues: dict[str, set[int]] = {}
    for event in seen_rows:
        for state in deliveries.delivery_states([event]).values():
            run_issues.setdefault(state.run_id, set()).update(i.issue for i in state.issues)
    left = _earlier_owner_left(rows, project_id, root)
    own_sprints = sorted((s for s in sprint_states.values() if s.project_id == project_id),
                         key=lambda state: -state.stated_seq)
    held = sorted((_held(record) for key, record in inbox.items()
                   if key[0] == project_id and _is_held(record.item)),
                  key=lambda entry: (str(entry["waiting_since"]), str(entry["key"])))
    return {
        "project_id": project_id, "written_at": written_at,
        "spend": None if spend is None else _spend(
            project_id, spend, {run: sorted(issues) for run, issues in run_issues.items()},
            sprint_states, None if left is None else left.at[:10]),
        "sprints": [_sprint_entry(state) for state in own_sprints],
        "deliveries": _deliveries(seen_rows, live_runs),
        "activations": _activations(
            rows, root, max(_owned_since(rows, project_id, root), 0 if left is None else left.seq)),
        "held_checks": held}
