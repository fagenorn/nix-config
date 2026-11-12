"""A sprint's manager: which profile it runs under and how it is launched (#888).

Reads no clock: capacity arrives as the `capacity.capacity_view` dict the caller built.

Profile (rule P7). `choose_profile(capacity, bound)` returns a profile name or a `Wait`. A profile
has room when its state is `ok` or `reset`. With room, the profile with the most `week_left`, then
the most `five_hour_left` (an unknown value counts below 0) wins, and among equal keys the
smallest name. With no room and `all_out` set, the answer is `Wait(resumes_at)`. Otherwise it is
`bound`, unless `bound` is listed as `out`, when it is the smallest-named `unknown` profile (and
`bound` again when none is). `bound_profile(root)` mirrors the launcher's `bound_account`: the
account bound to the directory's main checkout (a linked worktree reads its owner's binding,
`sessions.main_checkout`) or the nearest bound parent in `bindings.tsv` of the accounts
directory (`$CLAUDE_ACCOUNTS_DIR`, else `~/.claude-accounts`), else `default`.

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
Code applies a settings file's `env` to that session. Only the path is on argv.

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

Stopping. A withdrawal only appends `goal.withdrawn`: it does not end the manager's background
session, so a check that states a real goal stops its test manager first (ADR-console-016).
`stop_session(session_id, profile)` runs `claude-account run stop <short id>` under the session's own
profile (`client_environment`), within `STOP_TIMEOUT` seconds. The short id is the first eight
characters of the session id (`short_id`): the stop command accepts only the id the session listing
prints for a background session, and answers `No job matching '<id>'` to the full one. A failed stop
is `StopFailed` with a one-line reason: `claude-account is not installed`, `the stop did not return
within <n> s`, the last non-empty stderr line, or `the stop exited <n>`. `stop_listed(names,
registry, stop)` reads `registry()` fresh and calls `stop(session_id, profile)` for each listed
session whose name is in `names` (profile `default` when the record has none), attempts every one
even after a failure, then raises the first `StopFailed`; a name not listed needs no stop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from agent_tools.console.sessions import DEFAULT_PROFILE, main_checkout

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
SHORT_ID_LENGTH = 8
SETTINGS_SUFFIX = ".settings.json"
LAUNCH_TOOLS = ("bash", "dirname", "mkdir", "chmod", "ln", "systemd-run")

UNAVAILABLE_TEXT = "managers are not available on this host yet"
FAILED_TEXT = "could not start a manager"
WAITING_TEXT = "waiting on quota until"
MISSING_TEXT = "the manager is not running"

_DROPPED_ENV = ("CLAUDE_CONFIG_DIR", ID_ENV, SECRET_ENV)


class LaunchFailed(Exception):
    """The manager did not start; `str` is the one-line reason."""


class StopFailed(Exception):
    """A manager's background session could not be stopped; `str` is the one-line reason."""


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


def choose_profile(capacity: Mapping, bound: str) -> str | Wait:
    profiles = capacity["profiles"]
    room = [entry for entry in profiles if entry["state"] in ("ok", "reset")]
    if room:
        def key(entry):
            return (entry["week_left"] if entry["week_left"] is not None else -1,
                    entry["five_hour_left"] if entry["five_hour_left"] is not None else -1)
        best = max(key(entry) for entry in room)
        return min(entry["profile"] for entry in room if key(entry) == best)
    if capacity["all_out"]:
        return Wait(capacity["resumes_at"])
    if any(entry["profile"] == bound and entry["state"] == "out" for entry in profiles):
        unknown = sorted(entry["profile"] for entry in profiles if entry["state"] == "unknown")
        if unknown:
            return unknown[0]
    return bound


def bound_profile(root: str, accounts_dir: Path | None = None) -> str:
    if accounts_dir is None:
        accounts_dir = Path(os.environ.get("CLAUDE_ACCOUNTS_DIR")
                            or Path.home() / ".claude-accounts")
    try:
        lines = (accounts_dir / "bindings.tsv").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return DEFAULT_PROFILE
    bindings: dict[str, str] = {}
    for line in lines:
        fields = line.split("\t")
        if len(fields) >= 2:
            bindings.setdefault(fields[0], fields[1])
    start = Path(main_checkout(root) or root)
    for directory in (start, *start.parents):
        if str(directory) in bindings:
            return bindings[str(directory)]
    return DEFAULT_PROFILE


def supported(platform: str) -> bool:
    return platform.startswith("linux")


def launch_command(launch: Launch, platform: str) -> list[str] | None:
    if not supported(platform):
        return None
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--description=agent manager {launch.session_name}", "--",
            "claude-account", "run", "--bg", "--name", launch.session_name,
            "--settings", str(launch.settings), launch.prompt]


def launcher_for(platform: str) -> Callable[[Launch], None] | None:
    return run_launch if supported(platform) else None


def _write_settings(launch: Launch) -> None:
    directory = launch.settings.parent
    document = json.dumps({"env": dict(launch.env)})
    temporary = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=directory, prefix=".", suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(document)
        os.replace(temporary, launch.settings)
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
        _write_settings(launch)
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


def stop_listed(names, registry: Callable[[], Mapping],
                stop: Callable[[str, str], None]) -> None:
    wanted = set(names)
    failure = None
    for observation in registry().values():
        if observation.name in wanted:
            try:
                stop(observation.session_id, observation.profile or DEFAULT_PROFILE)
            except StopFailed as error:
                failure = failure or error
    if failure is not None:
        raise failure
