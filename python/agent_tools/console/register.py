"""The console's project registration: plan a repository's adoption and say what was found (#1052).

Decided in ADR-console-028. The owner names a repository on the page; the console runs the adoption
tools as children, off the request path, and tells the owner in plain words what adopting it would
change. The adoption tools stay the one implementation: nothing here edits a repository or writes the
fleet registry.

Request. `parse_register_request(body)` takes a UTF-8 JSON object with exactly the member `path`,
whose value is a string with no character below 0x20 and no 0x7F (the empty string included:
`refusal` judges the rule, so that an empty path is answered as a refusal, not as a malformed
request), and returns it. It raises `ValueError` otherwise. `expand(path, home)` strips the path and
turns a leading `~` (alone, or before a `/`) into `home`. `name_of(root)` is the last path segment.

Refusals. `refusal(path, entries, *, home, toplevel=checkout_root)` returns `(reason, None)` for the
first failing rule, else `(None, root)`, with no adopter in sight: a refusal never runs a plan. The
rules, in order: `EMPTY` (empty after trimming); `RELATIVE` (the expanded path is not absolute);
`not_directory(path)`; `not_toplevel(path)` (`toplevel(path)` is None); `already_registered(path,
project_id)` (a fleet registry entry whose resolved root equals the resolved path). `checkout_root`
runs `git -C <path> rev-parse --show-toplevel` with no shell, `stdin` and `stderr` to `DEVNULL` and
`GIT_TIMEOUT` (10 seconds), and returns the resolved path only when the exit is 0 and the printed
top, resolved, equals it; otherwise (an `OSError` or a timeout included) it returns None and never
raises. `running(name)` is the text of a second registration for the same repository, decided by the
service. `registry_unreadable()` is the text of a registration refused because the fleet registry
exists but cannot be read (an absent registry is an empty fleet), also decided by the service.
`UNAVAILABLE` is `registering a project is not available on this host`.

Runner. `Adopter(command=None, environ=None, timeout=RUN_TIMEOUT)` runs
`[*command, "plan", "--repo-root", root, "--format", "json"]` (`plan`) or
`[*command, "verify", "--repo-root", root, "--register"]` (`register`), the command defaulting to the
`adopt_project` sibling module. Each runs with no shell, in its own process group
(`manager.run_in_own_group`), `stdin` and `stderr` to `DEVNULL`, `stdout` piped, `env=dict(environ)`
when `environ` is given (else the console's own) and `timeout` (`RUN_TIMEOUT`, 300 seconds). Exit 0
or 2 returns the parsed stdout object. A failed run raises `RunFailed(kind)`, `str(error) == kind`,
`kind` one of `RUN_KINDS`: `cancelled` (the `cancel` event is set), `failed` (any other exit),
`unreadable` (stdout is not a JSON object), `timed_out` (`subprocess.TimeoutExpired`), `not_installed`
(`FileNotFoundError`, or `PermissionError` on the executable) and `unavailable` (any other
`OSError`). `adopter_for(platform)` is `Adopter()` where `manager.supported(platform)`, else None.

Plain lines. `plan_lines(document)` is the D4 list of ADR-console-028, each line only when its count
is above zero, in this order: `moves N agent file(s)` (followed by ` under .agents/` when every move
target starts with `.agents/`), `writes the project contract`, `generates N file(s) from the
contract`, `writes <paths>` (the non-contract files other than the adoption's own records), `records
the adoption` (when the plan writes any record), `deletes <paths>`, `rewrites N link(s)` and `rewrites
N path reference(s)` (the references answered `rewrite` or `extend`). `<paths>` names up to three
paths, as `a`, `a and b`, `a, b and c`, and from four on `a, b, c and N more` (#1057). The adoption's
own records, the two files the plan's `handoff` names as `migration_map` and `evidence_record` (any
other file, even beside them, stays named), are never named: a plan that writes any ends its `writes`
line with `, and records the adoption`, or is the line `records the adoption` when it writes nothing
else, and `NAMED` counts only the named files (#1060). It is a
pure function of the document. `summary(root, plan, report=None)` is the row payload (`by`, `root`,
`project_id`, `result`, `outcome`, `headline`, `lines`, `note`) with the D4 to D6 texts; message
text is whitespace-collapsed. A failed plan's headline is `The adoption plan for <name> failed:
<message>`, or `... could not be made.` when the error has no message; a refused registration's is
`<name> was not registered: <message>`, or `... was not registered.`; neither shows the error code
(#1057). `failed(root, kind)` is the same shape for a run that raised, its headline ending in the
words of `RUN_WORDS[kind]` (an unknown kind reads `it stopped unexpectedly`), never the kind word.

Row. `ended(payload)` is `("registration.ended", None, payload)` and raises `ValueError` unless the
members are exactly the eight above, `by` is `owner`, `result` is one of `RESULTS` and `lines` is a
list of strings. `ENDED` is `event_log.REGISTRATION_ENDED`, not in `KEPT_KINDS`. `latest(events,
state=None)` is the last valid `ENDED` payload with `at` added, else `state`: the view's
`registration` member, folded by the service. `view_entry(running, latest)` is that member: the
`running` entry (headline `Planning the adoption of <name>…`) while a run is under way, else the
latest with status `done`, else None.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from agent_tools.console import event_log, manager
from agent_tools.system import siblings

ENDED = event_log.REGISTRATION_ENDED
RUN_TIMEOUT = 300
GIT_TIMEOUT = 10
RESULTS = ("planned", "registered", "not_registered", "needs_migration", "needs_repair", "failed")
RUN_KINDS = ("not_installed", "timed_out", "unavailable", "failed", "unreadable", "cancelled")
UNAVAILABLE = "registering a project is not available on this host"
EMPTY = "type the path of a repository"
RELATIVE = "type the full path of the repository, starting with / or ~"
OUTCOME_TEXT = {
    "bootstrap": "it has no agent files or project contract yet",
    "reconcile": "it has agent files or a contract to bring up to date",
}
MEMBERS = {"by", "root", "project_id", "result", "outcome", "headline", "lines", "note"}
CONTRACT = ".agents/project.json"
NAMED = 3
RUN_WORDS = {
    "timed_out": "it took too long and was stopped",
    "not_installed": "the adoption tool could not be started",
    "unavailable": "the adoption tool could not be started",
    "cancelled": "it was cancelled",
    "failed": "the adoption tool stopped with an error",
    "unreadable": "the adoption tool gave an answer that could not be read",
}
UNEXPECTED = "it stopped unexpectedly"


def not_directory(path: str) -> str:
    return f"{path} is not a directory on this host"


def not_toplevel(path: str) -> str:
    return f"{path} is not the top of a git checkout"


def already_registered(path: str, project_id: str) -> str:
    return f"{path} is already registered as {project_id}"


def registry_unreadable() -> str:
    return "the project registry exists but cannot be read, so no registration was started"


def running(name: str) -> str:
    return f"a registration is already running for {name}"


def parse_register_request(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"path"} or not isinstance(value["path"], str):
        raise ValueError("wrong members")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value["path"]):
        raise ValueError("control character")
    return value["path"]


def expand(path: str, home: str) -> str:
    path = path.strip()
    if path == "~":
        return home
    if path.startswith("~/"):
        return home + path[1:]
    return path


def name_of(root: str) -> str:
    return Path(root).name


def checkout_root(path: str) -> Path | None:
    try:
        done = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        if done.returncode != 0:
            return None
        top = Path(done.stdout.decode("utf-8").rstrip("\n")).resolve()
        root = Path(path).resolve()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return root if top == root else None


def refusal(path: str, entries: Iterable[Mapping], *, home: str,
            toplevel=checkout_root) -> tuple[str | None, Path | None]:
    if not path.strip():
        return (EMPTY, None)
    expanded = expand(path, home)
    if not expanded.startswith("/"):
        return (RELATIVE, None)
    if not os.path.isdir(expanded):
        return (not_directory(expanded), None)
    root = toplevel(expanded)
    if root is None:
        return (not_toplevel(expanded), None)
    for entry in entries:
        if Path(entry["root"]).resolve() == root:
            return (already_registered(expanded, entry["project_id"]), None)
    return (None, root)


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _named(paths: Sequence[str]) -> str:
    if len(paths) > NAMED:
        return f"{', '.join(paths[:NAMED])} and {len(paths) - NAMED} more"
    if len(paths) > 1:
        return f"{', '.join(paths[:-1])} and {paths[-1]}"
    return paths[0]


def plan_lines(document: Mapping) -> list[str]:
    changes = document["changes"]
    moves = [op for op in changes if op["op"] == "git-mv"]
    writes = [op for op in changes if op["op"] == "write-file"]
    contract = any(CONTRACT in op["targets"] for op in writes)
    moved = sum(len(op["sources"]) for op in moves)
    generated = sum(len(op["targets"]) for op in changes if op["op"] == "regenerate-projection")
    written = [path for op in writes if CONTRACT not in op["targets"] for path in op["targets"]]
    handoff = document.get("handoff") or {}
    records = {handoff.get("migration_map"), handoff.get("evidence_record")} - {None}
    other = [path for path in written if path not in records]
    recorded = len(other) != len(written)
    deleted = [path for op in changes if op["op"] == "delete-file" for path in op["sources"]]
    rewrites = document["link_rewrites"]
    links = rewrites["inbound"]["links"] + rewrites["outbound"]["links"]
    references = sum(1 for row in document["path_references"]
                     if row.get("answer") in ("rewrite", "extend"))
    lines = []
    if moved:
        under = all(target.startswith(".agents/") for op in moves for target in op["targets"])
        lines.append(f"moves {_count(moved, 'agent file')}" + (" under .agents/" if under else ""))
    if contract:
        lines.append("writes the project contract")
    if generated:
        lines.append(f"generates {_count(generated, 'file')} from the contract")
    if other:
        lines.append(f"writes {_named(other)}" + (", and records the adoption" if recorded else ""))
    elif recorded:
        lines.append("records the adoption")
    if deleted:
        lines.append(f"deletes {_named(deleted)}")
    if links:
        lines.append(f"rewrites {_count(links, 'link')}")
    if references:
        lines.append(f"rewrites {_count(references, 'path reference')}")
    return lines


def _collapse(text: object) -> str:
    return " ".join(str(text).split())


def _error_message(error: Mapping) -> str:
    violations = error.get("violations") or []
    if violations and isinstance(violations[0], Mapping):
        return _collapse(violations[0].get("message") or "")
    return ""


def _row(root: str, project_id: str | None, result: str, outcome: str | None, headline: str,
         lines: list[str], note: str | None) -> dict:
    return {"by": "owner", "root": root, "project_id": project_id, "result": result,
            "outcome": outcome, "headline": headline, "lines": lines, "note": note}


def _note(plan: Mapping, document: Mapping) -> str:
    if plan.get("state") == "ready":
        return "The plan is ready to apply."
    questions = len(document.get("decisions", {}).get("open", []))
    if questions:
        return f"The plan has {_count(questions, 'open question')}."
    blockers = plan.get("blockers") or []
    if blockers:
        return f"The plan is a draft: {_collapse(blockers[0]['message'])}"
    return "The plan is a draft."


def _after(command: object, verb: str) -> str:
    return str(command or "").partition(f"{verb} ")[2].strip()


def summary(root: str, plan: Mapping, report: Mapping | None = None) -> dict:
    name = name_of(root)
    if "error" in plan:
        message = _error_message(plan["error"])
        text = (f"The adoption plan for {name} failed: {message}" if message
                else f"The adoption plan for {name} could not be made.")
        return _row(root, None, "failed", None, text, [], None)
    header = plan["plan"]
    outcome = header["outcome"]
    project_id = report.get("project_id") if report is not None else header.get("project_id")
    if outcome in OUTCOME_TEXT:
        return _row(root, project_id, "planned", outcome,
                    f"What adopting {name} would change: {OUTCOME_TEXT[outcome]}",
                    plan_lines(plan), _note(header, plan))
    if outcome == "no_change":
        if report is not None and "error" in report:
            message = _error_message(report["error"])
            text = (f"{name} was not registered: {message}" if message
                    else f"{name} was not registered.")
            return _row(root, project_id, "not_registered", outcome, text, [], None)
        if report is not None and report.get("registered") is True:
            return _row(root, project_id, "registered", outcome,
                        f"{name} is registered as {report.get('project_id')}.", [], None)
        result = _collapse(report.get("result")) if report is not None else "no report"
        return _row(root, project_id, "not_registered", outcome,
                    f"{name} was not registered: {result}", [], None)
    command = plan.get("handoff", {}).get("next_command")
    if outcome == "migration_required":
        migration = _after(command, "migrate")
        return _row(root, project_id, "needs_migration", outcome,
                    f"{name} needs migration {migration} first: run adopt-project migrate "
                    f"--migration {migration} --repo-root {root}", [], None)
    if outcome == "repair_required":
        repair = _after(command, "repair")
        return _row(root, project_id, "needs_repair", outcome,
                    f"{name} needs repair {repair} first: run resolve-project resolve "
                    f"--repo-root {root}", [], None)
    return failed(root, "unreadable")


def failed(root: str, kind: str) -> dict:
    return _row(root, None, "failed", None,
                f"The adoption plan for {name_of(root)} failed: {RUN_WORDS.get(kind, UNEXPECTED)}",
                [], None)


def ended(payload: Mapping) -> tuple[str, None, dict]:
    if (not isinstance(payload, Mapping) or set(payload) != MEMBERS or payload["by"] != "owner"
            or payload["result"] not in RESULTS or not isinstance(payload["lines"], list)
            or not all(isinstance(line, str) for line in payload["lines"])):
        raise ValueError("not a registration row")
    return (ENDED, None, dict(payload))


def latest(events: Iterable[event_log.Event], state: dict | None = None) -> dict | None:
    found = state
    for event in events:
        if event.kind != ENDED:
            continue
        try:
            _, _, payload = ended(event.payload)
        except ValueError:
            continue
        found = {**payload, "at": event.at}
    return found


def view_entry(running: str | None, latest: Mapping | None) -> dict | None:
    if running is not None:
        name = name_of(running)
        return {"root": running, "name": name, "project_id": None, "status": "running",
                "result": None, "outcome": None,
                "headline": f"Planning the adoption of {name}…", "lines": [], "note": None,
                "at": None}
    if latest is None:
        return None
    return {"root": latest["root"], "name": name_of(latest["root"]),
            "project_id": latest["project_id"], "status": "done", "result": latest["result"],
            "outcome": latest["outcome"], "headline": latest["headline"],
            "lines": latest["lines"], "note": latest["note"], "at": latest["at"]}


class RunFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class Adopter:
    def __init__(self, *, command: Sequence[str] | None = None,
                 environ: Mapping[str, str] | None = None, timeout: float = RUN_TIMEOUT):
        self._command = (tuple(command) if command is not None
                         else tuple(siblings.sibling_argv("project_contract.adopt_project")))
        self._environ = environ
        self._timeout = timeout

    def plan(self, root: str, cancel=None) -> dict:
        return self._run(["plan", "--repo-root", root, "--format", "json"], cancel)

    def register(self, root: str, cancel=None) -> dict:
        return self._run(["verify", "--repo-root", root, "--register"], cancel)

    def _run(self, arguments: list[str], cancel) -> dict:
        env = dict(self._environ) if self._environ is not None else None
        try:
            done = manager.run_in_own_group(
                [*self._command, *arguments], timeout=self._timeout, cancel=cancel,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=env, start_new_session=True)
        except subprocess.TimeoutExpired as error:
            raise RunFailed("timed_out") from error
        except (FileNotFoundError, PermissionError) as error:
            raise RunFailed("not_installed") from error
        except OSError as error:
            raise RunFailed("unavailable") from error
        if cancel is not None and cancel.is_set():
            raise RunFailed("cancelled")
        if done.returncode not in (0, 2):
            raise RunFailed("failed")
        try:
            value = json.loads(done.stdout)
        except ValueError as error:
            raise RunFailed("unreadable") from error
        if not isinstance(value, dict):
            raise RunFailed("unreadable")
        return value


def adopter_for(platform: str) -> Adopter | None:
    return Adopter() if manager.supported(platform) else None
