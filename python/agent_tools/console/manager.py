"""A sprint's manager: which profile it runs under and how it is launched (#888).

Reads no clock: capacity arrives as the `capacity.capacity_view` dict the caller built.

Launch profile (#1011). `choose_profile(capacity, last_use)` returns a profile name or a `Wait`.
With `capacity["all_out"]` set (every profile that is neither signed out nor excluded reads out) it is
`Wait(resumes_at)`; otherwise it is `session_profile(capacity, last_use)`, and `Wait(None)` when
that names nothing. The per-project account binding is not an input.

Session profile (#1011). `session_profile(capacity, last_use)` names the profile a new session
runs under, or None when nothing can be chosen; it never returns a `Wait` and ignores `all_out`.
An entry marked `excluded` (#1028, the owner's exclusion; it reaches this rule through
`capacity_view`, not as a parameter) is dropped first, before the room rule and the fallback.
Room is a profile whose state is `ok` or `reset`, whose sign-in is not `signed_out` (an entry
without a sign-in reading counts as `unknown`, P1) and which is not excluded: `has_room(entry)`.
An entry marked `pinned` (#1029, ADR-console-023; it reaches the rule through `capacity_view`, not
as a parameter) that has room answers first, whatever the others have left; a pinned entry without
room changes nothing, and the rule below applies. Otherwise the most `week_left`, then the most
`five_hour_left` (unknown below 0) wins, then the smallest name. With no room, the signed-in
profile used most recently (as an instant; a never-used one ranks below every used one, ties to
the smallest name) answers; with none signed in, None (P2). The entries are the accounts only (the
service lists the named profiles, #1016), so the unprofiled client directory is never chosen. A
name in `last_use` that is not an entry is ignored.
Last use is folded from the log's session rows by `profile_use(events, use)` (a new `ProfileUse`
of `last`, profile to the `at` of its latest `session.seen`, `session.hook` or `session.profile`
row, and `owner`, live session id to profile) and outlives the session: a `session.gone` row only
drops the owner (P3). `write_choice(path, profile)` writes `<name>\n` atomically to the file
`CHOICE_FILE` names (`chosen-profile`) and removes the file for None; `read_choice(path)` reads it
back, None for a missing, empty or unreadable file.

Command (Linux only; `launch_command` is None elsewhere and `launcher_for` gives None). The
manager runs in its own transient systemd scope and in the background, so it outlives the console
unit and a restart of it does not end it:

    systemd-run --user --scope --quiet --collect --description=agent manager <name> --
        claude-account run --bg --name <name> --settings <file> "<prompt>"

The name is `<project> sprint <sprint id>`. The prompt is one argv element, `PROMPT_LEAD` (`You
are the manager of one sprint, started by the console. Run "sprint contract" first and follow
what it prints. The goal: `) followed by the goal verbatim; `sprint contract` prints the manager's
contract, a document of this package. The secret is on no argv element. A takeover launch (a
sprint whose manager is gone and has work, `Launch.takeover`) carries `TAKEOVER_LEAD` instead (`You
take over one sprint whose manager is gone, started by the console. Run "sprint contract" first,
then "sprint recap", and follow what they print. The goal: `) followed by the goal verbatim.

Settings file. `claude --bg` hands the session to one supervisor per configuration directory,
and a supervisor that is already running may start the session with its own environment, not the
launching client's. So `run_launch` writes the sprint's id and secret as `{"env": {...}}` to a
per-sprint settings file (mode 0600, replaced on a retry) and passes `--settings <file>`; Claude
Code applies a settings file's `env` to that session. Only the path is on argv. The file holds
two more members (ADR-console-021, #973): `"worktree": {"bgIsolation": "none"}`, because a manager
writes no code and every delivery makes its own worktree, and one `PermissionRequest` command hook
that prints the client's deny decision with `REFUSAL`, one fixed sentence, because nobody watches
a manager's session (a plain `printf`, no interpreter start). `settings_document(env)` is that
content and `write_settings(path, env)` writes it (mode 0600, atomically); the console writes it
again before every wake of a stopped or removed session (`service._refresh_settings`).

Runner. `run_launch` starts the command with no terminal (`stdin` and `stdout` to the null
device, stderr to a temporary file, never a pipe, so a detached child that keeps the descriptors
open cannot hold the launch), in its own session, in the project root, within `LAUNCH_TIMEOUT`
seconds. The client's environment (`client_environment(profile, environ)`, shared with the nudge
commands) is the console's without `CLAUDE_CONFIG_DIR`, `CONSOLE_SPRINT_ID`
and `CONSOLE_SPRINT_SECRET`, plus `CLAUDE_ACCOUNT=<profile>` and `$HOME/.agents/bin` first on
`PATH` (where `sprint` and `resolve-project` are installed). `LAUNCH_TOOLS` names every program the
launch runs by name on `PATH`.

Failures are `LaunchFailed` with a one-line reason, the secret shown as `<secret>`: the host is
not Linux (`UNAVAILABLE_TEXT`), `the project root <root> is not a directory`, `cannot write the
manager's settings: <reason>`, `<program> is not installed`, `the launch did not return within
<n> s`, the last non-empty stderr line of a launch that failed, or `the launch exited <n>`.

Stopping. A withdrawal appends `goal.withdrawn` and the console then stops the manager's background
session (ADR-console-018), so a check that states a real goal still stops its test manager first and
the withdrawal's own stop finds nothing listed (ADR-console-016).
`stop_session(session_id, profile)` runs `claude-account run stop <short id>` under the session's own
profile (`client_environment`), within `STOP_TIMEOUT` seconds. The short id is the first eight
characters of the session id (`short_id`): the stop command accepts only the id the session listing
prints for a background session, and answers `No job matching '<id>'` to the full one. A failed stop
is `StopFailed` with a one-line reason: `claude-account is not installed`, `the stop did not return
within <n> s`, the last non-empty stderr line, or `the stop exited <n>`. `stop_listed(names,
registry, stop)` reads `registry()` fresh and calls `stop(session_id, profile)` for each listed
session whose name is in `names` (profile `default` when the record has none), attempts every one
even after a failure, then raises the first `StopFailed`; a name not listed needs no stop.
`stopper_for(platform)` is `stop_session` where `supported(platform)`, else None: the owner's stop
of a sprint (#892) uses it through the console service.
`remove_session(session_id, profile)` runs `claude-account run rm <short id>` under the session's
own profile within `REMOVE_TIMEOUT` seconds, and its failures are `RemoveFailed` (a `StopFailed`)
with the four reasons. `stop_listed(..., stopped)` appends each stop that succeeded as
`{"session_id", "profile"}` unless an unremoved entry for that id under that profile is already
there (a retry that stops the same id under another profile records it too).
`remove_stopped(stopped, remove)` removes each entry not marked `"removed": true`, marks each
success, tries every one and raises the first failure. `mark_removed` marks a removal made outside
`remove_stopped`, matching the entry by id and profile. Both loops call an optional `before()`
ahead of each call and let its exception end the loop; `finish_guard(clock, run_start, budget,
save)` is that `before` for a check's finish: it saves the check's state, then raises
`OutOfTime` when one more 60-second call could end past
`max(FINISH_LIMIT, budget + FINISH_SECONDS)` seconds of the run (590 with the default budget of
540), because verify-pending kills a run after 600. The verify checks use these to remove the
record of each test manager they stopped. The console's own withdrawal removes nothing
(ADR-console-018).

`run_in_own_group(argv, *, timeout, check=False, **kwargs)` is the one runner nudges and probes
share for a command started in its own session: a timeout kills the whole process group, not only
the immediate child, because the account wrapper waits for its Claude child.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent_tools.console.event_log import Event
from agent_tools.console.sessions import DEFAULT_PROFILE, GONE, HOOK, PROFILE, SEEN

CHOICE_FILE = "chosen-profile"

PROMPT_LEAD = ("You are the manager of one sprint, started by the console. "
               'Run "sprint contract" first and follow what it prints. The goal: ')
TAKEOVER_LEAD = ("You take over one sprint whose manager is gone, started by the console. "
                 'Run "sprint contract" first, then "sprint recap", and follow what they print. '
                 "The goal: ")
ID_ENV = "CONSOLE_SPRINT_ID"
SECRET_ENV = "CONSOLE_SPRINT_SECRET"
ACCOUNT_ENV = "CLAUDE_ACCOUNT"
LAUNCH_TIMEOUT = 60
STOP_TIMEOUT = 60
CANCEL_POLL_SECONDS = 0.25
REMOVE_TIMEOUT = 60
FINISH_LIMIT = 590
FINISH_SECONDS = 50
SHORT_ID_LENGTH = 8
SETTINGS_SUFFIX = ".settings.json"
LAUNCH_TOOLS = ("bash", "dirname", "mkdir", "chmod", "ln", "systemd-run")

OUT_OF_TIME_TEXT = "this run has no time left for the next stop or removal"
REFUSAL = ("Nobody watches this session, so the permission prompt was refused: do the step "
           "another way that needs no permission, or bring the choice to the owner with "
           "`sprint ask`.")

UNAVAILABLE_TEXT = "managers are not available on this host yet"
FAILED_TEXT = "could not start a manager"
WAITING_TEXT = "waiting on quota until"
MISSING_TEXT = "the manager is not running"

_DROPPED_ENV = ("CLAUDE_CONFIG_DIR", ID_ENV, SECRET_ENV)


class LaunchFailed(Exception):
    """The manager did not start; `str` is the one-line reason."""


class StopFailed(Exception):
    """A manager's background session could not be stopped; `str` is the one-line reason."""


class RemoveFailed(StopFailed):
    """A stopped session's record could not be removed; `str` is the one-line reason."""


class OutOfTime(Exception):
    """A run has no time left for the next stop or removal (not a `StopFailed`)."""


@dataclass(frozen=True)
class Launch:
    sprint_id: str
    project_id: str
    cwd: str
    profile: str
    session_name: str
    prompt: str
    settings: Path
    env: Mapping[str, str] = field(repr=False)
    takeover: bool = False
    seen_after: int = 0


@dataclass(frozen=True)
class Wait:
    until: str | None


def session_name(project_id: str, sprint_id: str) -> str:
    return f"{project_id} sprint {sprint_id}"


def settings_path(directory: Path, sprint_id: str) -> Path:
    return directory / (sprint_id + SETTINGS_SUFFIX)


def remove_settings(directory: Path, sprint_id: str) -> None:
    settings_path(directory, sprint_id).unlink(missing_ok=True)


def new_launch(sprint_id: str, project_id: str, goal: str, root: str, profile: str,
               secret: str, settings_dir: Path, takeover: bool = False,
               seen_after: int = 0) -> Launch:
    return Launch(
        sprint_id=sprint_id, project_id=project_id, cwd=root, profile=profile,
        session_name=session_name(project_id, sprint_id),
        prompt=(TAKEOVER_LEAD if takeover else PROMPT_LEAD) + goal,
        settings=settings_path(settings_dir, sprint_id),
        env={ID_ENV: sprint_id, SECRET_ENV: secret}, takeover=takeover,
        seen_after=seen_after)


def choose_profile(capacity: Mapping, last_use: Mapping[str, str]) -> str | Wait:
    if capacity["all_out"]:
        return Wait(capacity["resumes_at"])
    chosen = session_profile(capacity, last_use)
    return Wait(None) if chosen is None else chosen


@dataclass(frozen=True)
class ProfileUse:
    last: Mapping[str, str]
    owner: Mapping[str, str]


def profile_use(events: Iterable[Event], use: ProfileUse | None = None) -> ProfileUse:
    last = dict(use.last) if use else {}
    owner = dict(use.owner) if use else {}
    for event in events:
        session_id = event.payload.get("session_id")
        if not isinstance(session_id, str):
            continue
        if event.kind == GONE:
            owner.pop(session_id, None)
            continue
        if event.kind not in (SEEN, HOOK, PROFILE):
            continue
        profile = event.payload.get("profile")
        if event.kind in (SEEN, PROFILE) and isinstance(profile, str):
            owner[session_id] = profile
        name = owner.get(session_id)
        if name is None:
            continue
        moment = _instant(event.at)
        if moment is None:
            continue
        known = _instant(last[name]) if name in last else None
        if known is None or moment > known:
            last[name] = event.at
    return ProfileUse(last=last, owner=owner)


def _instant(value) -> float | None:
    try:
        moment = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (ValueError, TypeError, AttributeError):
        return None
    if moment.tzinfo is None:
        return None
    return moment.timestamp()


def _signin(entry: Mapping) -> str:
    return (entry.get("signin") or {}).get("state", "unknown")


def has_room(entry: Mapping) -> bool:
    return (entry["state"] in ("ok", "reset") and _signin(entry) != "signed_out"
            and not entry.get("excluded"))


def session_profile(capacity: Mapping, last_use: Mapping[str, str]) -> str | None:
    entries = [entry for entry in capacity["profiles"] if not entry.get("excluded")]
    for entry in entries:
        if entry.get("pinned") and has_room(entry):
            return entry["profile"]
    room = [entry for entry in entries if has_room(entry)]
    if room:
        def key(entry):
            return (entry["week_left"] if entry["week_left"] is not None else -1,
                    entry["five_hour_left"] if entry["five_hour_left"] is not None else -1)
        best = max(key(entry) for entry in room)
        return min(entry["profile"] for entry in room if key(entry) == best)
    signed_in = [entry["profile"] for entry in entries if _signin(entry) == "signed_in"]
    if signed_in:
        def rank(name):
            instant = _instant(last_use.get(name))
            return (instant is not None, instant or 0.0)
        best = max(rank(name) for name in signed_in)
        return min(name for name in signed_in if rank(name) == best)
    return None


def write_choice(path: Path, profile: str | None) -> None:
    """Replace the file at `path` with `profile` and a newline; remove it for None. `OSError` propagates."""
    if profile is None:
        path.unlink(missing_ok=True)
        return
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(profile + "\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_choice(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return (lines[0].strip() or None) if lines else None


def quota_wait(capacity: Mapping, profile: str | None) -> Wait | None:
    """Where a manager on `profile` waits for quota (#929): `Wait(out_until)` when `capacity`
    holds an entry for `profile` whose `state` is `out`, else None (no profile, an unknown one or
    one that has room)."""
    for entry in capacity["profiles"]:
        if entry["profile"] == profile:
            return Wait(entry["out_until"]) if entry["state"] == "out" else None
    return None


def supported(platform: str) -> bool:
    return platform.startswith("linux")


def launch_command(launch: Launch, platform: str) -> list[str] | None:
    if not supported(platform):
        return None
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--description=agent manager {launch.session_name}", "--",
            "claude-account", "run", "--bg", "--name", launch.session_name,
            "--settings", str(launch.settings), launch.prompt]


def stopper_for(platform: str) -> Callable[[str, str], None] | None:
    return stop_session if supported(platform) else None


def launcher_for(platform: str) -> Callable[[Launch], None] | None:
    return run_launch if supported(platform) else None


def settings_document(env: Mapping[str, str]) -> dict:
    """The settings a manager's session runs under: its environment, no isolation guard, no prompts."""
    refusal = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "deny", "message": REFUSAL}}})
    return {"env": dict(env),
            "worktree": {"bgIsolation": "none"},
            "hooks": {"PermissionRequest": [{"hooks": [{
                "type": "command", "command": f"printf '%s\\n' {shlex.quote(refusal)}"}]}]}}


def write_settings(path: Path, env: Mapping[str, str]) -> None:
    """Replace the file at `path` with `settings_document(env)`; `LaunchFailed` when it cannot be written."""
    document = json.dumps(settings_document(env))
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".", suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(document)
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise LaunchFailed(
            f"cannot write the manager's settings: {error.strerror or error}") from error
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def client_environment(profile: str, environ: Mapping[str, str]) -> dict[str, str]:
    env = {key: value for key, value in environ.items() if key not in _DROPPED_ENV}
    env[ACCOUNT_ENV] = profile
    home = environ.get("HOME")
    if home:
        path = environ.get("PATH")
        env["PATH"] = f"{home}/.agents/bin" + (f":{path}" if path else "")
    return env


def run_in_own_group(argv: list[str], *, timeout: float, check: bool = False,
                     cancel: threading.Event | None = None,
                     **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` for a command started with `start_new_session`: a timeout ends its whole group.

    `subprocess.run` kills only the immediate child, and the account wrapper waits for its Claude
    child instead of replacing itself, so the child would outlive the failure and could still send.
    A `cancel` event that is set (checked every `CANCEL_POLL_SECONDS`) ends the whole group the same
    way, and the call returns with the killed status once the group is reaped. The result carries
    what `communicate` returned (`stdout` and `stderr` for the streams that were piped, None for the
    others and after a cancel), so a caller that pipes `stdout` reads it from the result.
    """
    assert not check, "the caller reads the exit status"
    with subprocess.Popen(argv, **kwargs) as process:
        deadline = time.monotonic() + timeout
        out = err = None
        while True:
            if cancel is not None and cancel.is_set():
                _kill_group(process)
                break
            remaining = deadline - time.monotonic()
            try:
                out, err = process.communicate(
                    timeout=remaining if cancel is None else min(remaining, CANCEL_POLL_SECONDS))
                break
            except subprocess.TimeoutExpired:
                if deadline - time.monotonic() <= 0:
                    _kill_group(process)
                    raise
        return subprocess.CompletedProcess(argv, process.returncode, out, err)


def _kill_group(process: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run_launch(launch: Launch, *, platform: str = sys.platform, run=subprocess.run,
               environ: Mapping[str, str] = os.environ) -> None:
    secret = launch.env[SECRET_ENV]

    def fail(reason: str) -> LaunchFailed:
        return LaunchFailed(reason.replace(secret, "<secret>") if secret else reason)

    argv = launch_command(launch, platform)
    if argv is None:
        raise fail(UNAVAILABLE_TEXT)
    if not Path(launch.cwd).is_dir():
        raise fail(f"the project root {launch.cwd} is not a directory")
    try:
        write_settings(launch.settings, launch.env)
    except LaunchFailed as error:
        raise fail(str(error)) from error
    env = client_environment(launch.profile, environ)
    with tempfile.TemporaryFile() as err:
        try:
            result = run(argv, cwd=launch.cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=err, start_new_session=True,
                         timeout=LAUNCH_TIMEOUT, check=False)
        except FileNotFoundError as error:
            raise fail(f"{argv[0]} is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise fail(f"the launch did not return within {LAUNCH_TIMEOUT} s") from error
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode != 0:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        raise fail(lines[-1] if lines else f"the launch exited {result.returncode}")


def short_id(session_id: str) -> str:
    return session_id[:SHORT_ID_LENGTH]


def stop_session(session_id: str, profile: str, *, run=subprocess.run,
                 environ: Mapping[str, str] = os.environ) -> None:
    argv = ["claude-account", "run", "stop", short_id(session_id)]
    with tempfile.TemporaryFile() as err:
        try:
            result = run(argv, env=client_environment(profile, environ),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                         timeout=STOP_TIMEOUT, check=False)
        except FileNotFoundError:
            raise StopFailed(f"{argv[0]} is not installed") from None
        except subprocess.TimeoutExpired:
            raise StopFailed(f"the stop did not return within {STOP_TIMEOUT} s") from None
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode != 0:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        raise StopFailed(lines[-1] if lines else f"the stop exited {result.returncode}")


def remove_session(session_id: str, profile: str, *, run=subprocess.run,
                   environ: Mapping[str, str] = os.environ) -> None:
    argv = ["claude-account", "run", "rm", short_id(session_id)]
    with tempfile.TemporaryFile() as err:
        try:
            result = run(argv, env=client_environment(profile, environ),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                         timeout=REMOVE_TIMEOUT, check=False)
        except FileNotFoundError:
            raise RemoveFailed(f"{argv[0]} is not installed") from None
        except subprocess.TimeoutExpired:
            raise RemoveFailed(f"the removal did not return within {REMOVE_TIMEOUT} s") from None
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode != 0:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        raise RemoveFailed(lines[-1] if lines else f"the removal exited {result.returncode}")


def stop_listed(names, registry: Callable[[], Mapping],
                stop: Callable[[str, str], None], stopped: list | None = None,
                before: Callable[[], None] | None = None) -> None:
    wanted = set(names)
    failure = None
    for observation in registry().values():
        if observation.name in wanted:
            profile = observation.profile or DEFAULT_PROFILE
            if before is not None:
                before()
            try:
                stop(observation.session_id, profile)
            except StopFailed as error:
                failure = failure or error
                continue
            if stopped is not None and not any(
                    entry["session_id"] == observation.session_id
                    and entry["profile"] == profile and not entry.get("removed")
                    for entry in stopped):
                stopped.append({"session_id": observation.session_id, "profile": profile})
    if failure is not None:
        raise failure


def remove_stopped(stopped: list, remove: Callable[[str, str], None],
                   before: Callable[[], None] | None = None) -> None:
    failure = None
    for entry in stopped:
        if entry.get("removed"):
            continue
        if before is not None:
            before()
        try:
            remove(entry["session_id"], entry["profile"])
        except StopFailed as error:
            failure = failure or error
            continue
        entry["removed"] = True
    if failure is not None:
        raise failure


def mark_removed(stopped: list, session_id: str, profile: str) -> None:
    for entry in stopped:
        if (entry["session_id"] == session_id and entry["profile"] == profile
                and not entry.get("removed")):
            entry["removed"] = True
            return
    stopped.append({"session_id": session_id, "profile": profile, "removed": True})


def finish_guard(clock: Callable[[], float], run_start: float, budget: float,
                 save: Callable[[], None]) -> Callable[[], None]:
    def before() -> None:
        save()
        limit = max(FINISH_LIMIT, budget + FINISH_SECONDS)
        if clock() - run_start + max(STOP_TIMEOUT, REMOVE_TIMEOUT) > limit:
            raise OutOfTime(OUT_OF_TIME_TEXT)

    return before
