"""The console's session model: live Claude Code sessions from hooks and the session registry.

Nothing here reads a clock or runs a subprocess. `main_checkout`,
`own_pid_domain`, `process_matches` and `read_session_registry` read the file
system or the process table and never raise for a missing, unreadable or
malformed file or directory; everything else is a pure function.

Event kinds (stored in the event log, payloads are JSON objects):

- `session.hook` (`HOOK`): `{"event", "session_id", "cwd", "repo"}` plus at most
  one more string field for its event: `source` (SessionStart), `error`
  (StopFailure), `tool_name` (PermissionRequest), `notification_type`
  (Notification), `reason` (SessionEnd). `repo` is the main checkout of `cwd`,
  or null when `cwd` is in no git repository, and `received_ms` when known:
  the epoch milliseconds at which the service received the hook, taken before
  it answered, which is the time the fold gives the hook (`hook_ms`), the
  log's own time standing in for a payload without one. `hook_entry` builds it
  from a hook's input document and drops every other field.
- `session.seen` (`SEEN`): `{"session_id", "cwd", "repo", "state"}` plus `name`
  and `profile` when known; the registry poll writes it when its reading
  differs from the folded state.
- `session.profile` (`PROFILE`): `{"session_id", "profile"}`, written with no
  project when a known session's registry reading names another account
  profile. The fold replaces the profile of a known session and leaves its
  state, `last_seq`, `last_at` and `hook_ms` as they are; an unknown session or
  a non-string profile is ignored. `session.hook` keeps the known profile, a
  `session.seen` without `profile` keeps it and one with `profile` sets it.
- `session.gone` (`GONE`): `{"session_id"}`; the poll writes it when two
  consecutive polls do not find the session.

Unknown fields, events, kinds and statuses are ignored; so is an event whose
payload lacks a required member.

States: `working`, `waiting_answer`, `waiting_permission`, `idle`, `limit`
(`STATES`), and `ended`, the tombstone of a session that sent SessionEnd, which
is stored but never shown and is not a member of `STATES`.

Hook transitions (`hook_transition`): SessionStart and Stop give idle.
StopFailure gives limit when its `error` is `rate_limit`, else idle.
PermissionRequest gives waiting_answer for the `AskUserQuestion` tool, else
waiting_permission. A Notification of type `permission_prompt` keeps a waiting
state and otherwise gives waiting_permission; `idle_prompt` gives idle; any
other type keeps the state (idle for a session not yet seen) and the time of
that state, so it never makes a newer registry reading look older than the
hook. SessionEnd gives ended.

`state_ms` (#980) is the epoch milliseconds of the session's current state: a hook gives its `hook_ms`
(the time it was received, so a hook ingested late carries its early time) and a `session.seen` row
the time of the row, except that a hook that keeps the state and a row that leaves the state as it
is (a rename, a move) keep the `state_ms` already held. `last_at` moves on every such row; `state_ms`
moves only when the state is asserted afresh. `session.profile` leaves it as it is.

Registry mapping (`registry_state`): `busy` is working, `idle` is idle,
`waiting` is waiting_permission when `waitingFor` is `permission prompt` and
waiting_answer otherwise; any other status (`shell` included) says nothing. An
idle reading never clears a usage-limit stop.

Leaving: a session leaves on SessionEnd (a tombstone, so an older registry
reading cannot bring it back) and, tombstone or not, when two consecutive polls
do not find it in the registry. `poll_changes` returns the absent set to pass
to the next poll.

Profiles: a session's profile is the account it runs under, named by the
registry directory its record was read from (`profile_of`): a directory
`<accounts>/profiles/<name>/sessions` gives `<name>`, any other directory
(`~/.claude/sessions` included) gives `default` (`DEFAULT_PROFILE`). Nothing
beyond the registry files already read is opened to learn it. `poll_changes`
records a changed profile before the hooks-win rule, so a newer hook never hides
it.

A registry record whose `cwd` holds a NUL character is not a session and is
skipped like any other malformed record.

A reading whose `cwd` or `name` differs from the folded state is written as well,
with the repository resolved again when the directory moved.

Hooks win over older readings: when the session's newest hook has a time
(`hook_ms`), a registry reading whose `updatedAt` is missing or not newer
changes nothing.

Main checkout (`main_checkout`): the directory holding the first `.git` found
walking up from the realpath of `cwd`; for a linked worktree, the main
checkout that owns it, found by following `gitdir:` and `commondir` files. A
`cwd` in no git repository gives `None`, and the console lists such a session
nowhere.

Liveness (`process_matches`): a registry file names a live session only while
its pid runs the process it recorded. With procfs, the file's `pidDomain` must
equal this console's own (`linux:<machine-id>:pid:[<pid namespace inode>]`) and
its `procStart` must equal field 22 (`starttime`) of `/proc/<pid>/stat`; a
missing, malformed or unverifiable value of either is a mismatch, so a record
without them is never live. Without procfs only the pid's existence is checked.
"""

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console.event_log import Event

WORKING = "working"
WAITING_ANSWER = "waiting_answer"
WAITING_PERMISSION = "waiting_permission"
IDLE = "idle"
LIMIT = "limit"
STATES = (WORKING, WAITING_ANSWER, WAITING_PERMISSION, IDLE, LIMIT)
ENDED = "ended"

STATE_TEXT = {
    WORKING: "working",
    WAITING_ANSWER: "waiting for an answer in its terminal",
    WAITING_PERMISSION: "waiting for a permission in its terminal",
    IDLE: "idle",
    LIMIT: "stopped on a usage limit",
}

HOOK = "session.hook"
SEEN = "session.seen"
GONE = "session.gone"
PROFILE = "session.profile"
DEFAULT_PROFILE = "default"

HOOK_EVENTS = ("SessionStart", "Stop", "StopFailure", "PermissionRequest",
               "Notification", "SessionEnd")

_KEPT_FIELD = {
    "SessionStart": "source",
    "StopFailure": "error",
    "PermissionRequest": "tool_name",
    "Notification": "notification_type",
    "SessionEnd": "reason",
}

_WAITING = (WAITING_ANSWER, WAITING_PERMISSION)


@dataclass(frozen=True)
class Observation:
    session_id: str
    cwd: str
    pid: int
    status: str | None
    waiting_for: str | None
    name: str | None
    updated_ms: int | None
    profile: str | None = None


@dataclass(frozen=True)
class SessionState:
    session_id: str
    repo: str | None
    cwd: str
    state: str
    name: str | None
    last_seq: int
    last_at: str
    hook_ms: int | None
    profile: str | None = None
    state_ms: int | None = None


def _text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _first_git(cwd: str) -> Path | None:
    directory = Path(os.path.realpath(cwd))
    for candidate in (directory, *directory.parents):
        if os.path.lexists(candidate / ".git"):
            return candidate
    return None


def main_checkout(cwd: str) -> str | None:
    holder = _first_git(cwd)
    if holder is None:
        return None
    dot_git = holder / ".git"
    try:
        if dot_git.is_dir():
            return str(holder)
        lines = dot_git.read_text().splitlines()
        if not lines or not lines[0].startswith("gitdir:"):
            return str(holder)
        gitdir = holder / lines[0][len("gitdir:"):].strip()
        common = Path(os.path.realpath(gitdir / (gitdir / "commondir").read_text().strip()))
    except (OSError, ValueError):
        return str(holder)
    return str(common.parent if common.name == ".git" else common)


def hook_entry(document: object, repo_of: Callable[[str], str | None],
               received_ms: int | None = None) -> tuple[str, dict] | None:
    if not isinstance(document, dict):
        return None
    event = document.get("hook_event_name")
    session_id = document.get("session_id")
    cwd = document.get("cwd")
    if event not in HOOK_EVENTS or not _text(session_id) or not _text(cwd):
        return None
    payload = {"event": event, "session_id": session_id, "cwd": cwd, "repo": repo_of(cwd)}
    if _integer(received_ms):
        payload["received_ms"] = received_ms
    field = _KEPT_FIELD.get(event)
    if field is not None and isinstance(document.get(field), str):
        payload[field] = document[field]
    return HOOK, payload


def hook_transition(event: str, payload: Mapping, previous: str | None) -> str:
    if event == "StopFailure":
        return LIMIT if payload.get("error") == "rate_limit" else IDLE
    if event == "PermissionRequest":
        if payload.get("tool_name") == "AskUserQuestion":
            return WAITING_ANSWER
        return WAITING_PERMISSION
    if event == "Notification":
        kind = payload.get("notification_type")
        if kind == "permission_prompt":
            return previous if previous in _WAITING else WAITING_PERMISSION
        if kind == "idle_prompt":
            return IDLE
        return previous if previous in STATES else IDLE
    if event == "SessionEnd":
        return ENDED
    return IDLE


def own_pid_domain(proc: Path = Path("/proc"),
                   machine_id: Path = Path("/etc/machine-id")) -> str | None:
    try:
        ident = machine_id.read_text().strip()
        namespace = os.readlink(proc / "self" / "ns" / "pid")
    except (OSError, ValueError):
        return None
    return f"linux:{ident}:{namespace}" if ident else None


def process_matches(pid: int, proc_start: str | None, pid_domain: str | None, *,
                    proc: Path = Path("/proc"),
                    machine_id: Path = Path("/etc/machine-id")) -> bool:
    if pid <= 0:
        return False
    if not (proc / "self" / "stat").exists():
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except (OSError, OverflowError):
            return False
        return True
    own = own_pid_domain(proc, machine_id)
    if own is None or not isinstance(pid_domain, str) or pid_domain != own:
        return False
    try:
        line = (proc / str(pid) / "stat").read_text()
    except (OSError, ValueError):
        return False
    fields = line.rsplit(")", 1)[1].split() if ")" in line else []
    if len(fields) < 20:
        return False
    return isinstance(proc_start, str) and proc_start == fields[19]


def profile_name(config_dir: Path) -> str:
    if config_dir.parent.name == "profiles":
        return config_dir.name
    return DEFAULT_PROFILE


def profile_of(directory: Path) -> str:
    return profile_name(directory.parent)


def _observation(document: object,
                 alive: Callable[[int, str | None, str | None], bool],
                 profile: str | None = None) -> Observation | None:
    if not isinstance(document, dict):
        return None
    session_id, cwd, pid = document.get("sessionId"), document.get("cwd"), document.get("pid")
    if not _text(session_id) or not _text(cwd) or "\0" in cwd \
            or not _integer(pid) or pid <= 0:
        return None
    start = document.get("procStart")
    if _integer(start):
        start = str(start)
    elif not isinstance(start, str):
        start = None
    domain = document.get("pidDomain")
    if not alive(pid, start, domain if isinstance(domain, str) else None):
        return None
    updated = document.get("updatedAt")

    def optional(key: str) -> str | None:
        value = document.get(key)
        return value if isinstance(value, str) else None

    return Observation(session_id, cwd, pid, optional("status"), optional("waitingFor"),
                       optional("name"), updated if _integer(updated) else None, profile)


def read_session_registry(
    directories: Iterable[Path],
    alive: Callable[[int, str | None, str | None], bool] = process_matches,
) -> dict[str, Observation]:
    result: dict[str, Observation] = {}
    for directory in directories:
        profile = profile_of(Path(directory))
        try:
            names = sorted(Path(directory).glob("*.json"))
        except OSError:
            continue
        for path in names:
            try:
                document = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            found = _observation(document, alive, profile)
            if found is not None and found.session_id not in result:
                result[found.session_id] = found
    return result


def registry_state(observation: Observation) -> str | None:
    if observation.status == "busy":
        return WORKING
    if observation.status == "idle":
        return IDLE
    if observation.status == "waiting":
        if observation.waiting_for == "permission prompt":
            return WAITING_PERMISSION
        return WAITING_ANSWER
    return None


def at_ms(at: str) -> int | None:
    try:
        moment = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return None
    return (moment - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def _repo_member(payload: Mapping) -> bool:
    return "repo" in payload and (payload["repo"] is None or isinstance(payload["repo"], str))


def _keeps_state(event: str, payload: Mapping) -> bool:
    return event == "Notification" and \
        payload.get("notification_type") not in ("permission_prompt", "idle_prompt")


def session_states(
    events: Iterable[Event],
    states: Mapping[str, SessionState] | None = None,
) -> dict[str, SessionState]:
    result = dict(states or {})
    for event in events:
        payload = event.payload
        if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str):
            continue
        session_id = payload["session_id"]
        known = result.get(session_id)
        if event.kind == GONE:
            result.pop(session_id, None)
        elif event.kind == HOOK:
            kind, cwd = payload.get("event"), payload.get("cwd")
            if kind not in HOOK_EVENTS or not isinstance(cwd, str) or not _repo_member(payload):
                continue
            previous = known.state if known and known.state != ENDED else None
            received = payload.get("received_ms")
            hook_ms = received if _integer(received) else at_ms(event.at)
            if previous in STATES and _keeps_state(kind, payload):
                hook_ms = known.hook_ms
            state_ms = known.state_ms if previous in STATES and _keeps_state(kind, payload) \
                else hook_ms
            result[session_id] = SessionState(
                session_id, payload["repo"], cwd, hook_transition(kind, payload, previous),
                known.name if known else None, event.seq, event.at, hook_ms,
                known.profile if known else None, state_ms)
        elif event.kind == SEEN:
            cwd, state = payload.get("cwd"), payload.get("state")
            if not isinstance(cwd, str) or not _repo_member(payload) or state not in STATES:
                continue
            name = payload.get("name")
            if not isinstance(name, str):
                name = known.name if known else None
            profile = payload.get("profile")
            if not isinstance(profile, str):
                profile = known.profile if known else None
            state_ms = known.state_ms if known and known.state == state else at_ms(event.at)
            result[session_id] = SessionState(
                session_id, payload["repo"], cwd, state, name, event.seq, event.at,
                known.hook_ms if known else None, profile, state_ms)
        elif event.kind == PROFILE:
            profile = payload.get("profile")
            if known is not None and isinstance(profile, str):
                result[session_id] = replace(known, profile=profile)
    return result


def poll_changes(
    states: Mapping[str, SessionState],
    observations: Mapping[str, Observation],
    absent: frozenset[str],
    repo_of: Callable[[str], str | None],
    project_of: Callable[[str | None], str | None],
) -> tuple[list[tuple[str, str | None, dict]], frozenset[str]]:
    changes: list[tuple[str, str | None, dict]] = []

    def seen(obs: Observation, state: str, repo: str | None,
             known: SessionState | None) -> None:
        payload = {"session_id": obs.session_id, "cwd": obs.cwd, "repo": repo, "state": state}
        name = obs.name if isinstance(obs.name, str) else known.name if known else None
        if isinstance(name, str):
            payload["name"] = name
        if isinstance(obs.profile, str):
            payload["profile"] = obs.profile
        changes.append((SEEN, project_of(repo), payload))

    for session_id in sorted(observations):
        obs = observations[session_id]
        known = states.get(session_id)
        reading = registry_state(obs)
        if known is not None and isinstance(obs.profile, str) and obs.profile != known.profile:
            changes.append((PROFILE, None, {"session_id": session_id, "profile": obs.profile}))
        if known is None:
            seen(obs, reading or IDLE, repo_of(obs.cwd), None)
        elif known.hook_ms is not None and (obs.updated_ms is None
                                            or obs.updated_ms <= known.hook_ms):
            continue
        elif known.state == ENDED:
            seen(obs, reading or IDLE, repo_of(obs.cwd), known)
        else:
            state = known.state
            if reading is not None and reading != state \
                    and not (reading == IDLE and state == LIMIT):
                state = reading
            moved = obs.cwd != known.cwd
            renamed = isinstance(obs.name, str) and obs.name != known.name
            if state != known.state or moved or renamed:
                seen(obs, state, repo_of(obs.cwd) if moved else known.repo, known)
    missing = {sid for sid in states if sid not in observations}
    for session_id in sorted(missing & absent):
        changes.append((GONE, project_of(states[session_id].repo), {"session_id": session_id}))
    return changes, frozenset(missing - absent)
