"""The nudge: one fixed sentence that tells a sprint's manager to read its inbox (#889).

The owner's words never travel in a nudge. A nudge carries `NUDGE_TEXT`, one fixed sentence that
names no sprint, project or owner text; the manager runs `sprint inbox` (which authenticates with
the sprint's secret) and reads the message there. `Nudge` has no text member: the route chooses
the sentence (`relay` and `wake` carry `NUDGE_TEXT`, `continue` carries `CONTINUE_TEXT`, `revive`
carries `RESTART_TEXT`), and no argv element or environment value carries anything for the manager
but that one sentence.
`continue` is the one other fixed sentence a relay carries: `CONTINUE_TEXT`, the idle nudge (#929).

Four routes, chosen by the caller (this module only runs the one it is given):

    relay: claude-account run -p --allowedTools SendMessage --no-session-persistence "<prompt>"

`relay_prompt(session_name)` is `Use the SendMessage tool exactly once, to the peer session named
"<name>", with this message and nothing else: ` + `NUDGE_TEXT` + ` Then print SENT on its own
line if the tool reported the message sent or accepted, otherwise print FAILED.` The relay sends
by session name (the tool's recipient accepts a peer session name) and is delivered only when its
last non-empty stdout line is exactly `SENT`.

    continue: the relay command with `CONTINUE_TEXT` in place of `NUDGE_TEXT`

`CONTINUE_TEXT` is `The console found you idle while your sprint has work. Run "sprint recap", then
"sprint inbox", and go on with the next step.` The continue is sent to a listed idle manager the
console found quiet (#929); it follows the relay's rules in every respect (stdout captured,
`RELAY_TIMEOUT`, delivered only on `SENT`, else `NudgeFailed(UNCONFIRMED_TEXT)`) and needs no
session id.

    wake: systemd-run --user --scope --quiet --collect --description=agent manager <name> --
          claude-account run --resume <session id> --bg [--name <name> --settings <file>]
          "<NUDGE_TEXT>"

The wake resumes by session id inside a transient user scope, so a supervisor it starts outlives
the console unit (ADR-console-015). `--resume <id> --bg` wakes a stopped session in place under
the same id, but starts a copy of a session that is running; the caller must therefore use the
wake only for a session the session listing does not show (issue #831). A wake with no session id
raises `NudgeFailed(UNKNOWN_SESSION)` and runs nothing.

`Nudge.settings` is the sprint's settings file path, or None for a bare wake. With a path the argv
carries `--name <session name> --settings <path>` right after `--bg` and before the sentence (the
sentence stays last); the relay ignores it. `--resume <id> --bg` with name and settings restores
both under the same id only when the session's record is gone; on a session whose record exists
the client keeps the saved options and starts a copy. The caller therefore passes `settings` only
for a session the full listing does not show (issue #949).

    revive: the wake command with `RESTART_TEXT` in place of `NUDGE_TEXT`

`RESTART_TEXT` is `The console restarted this session because it had stopped while its sprint had
work. Run "sprint contract", then "sprint recap", and go on.` The revive resumes a stopped manager
the console brings back, not one that was told of a message; it follows the wake's rules in every
other respect (the same command shape, `WAKE_TIMEOUT`, stdout to the null device, no `SENT` check,
and a revive with no session id raises `NudgeFailed(UNKNOWN_SESSION)` and runs nothing).

Runner. `run_nudge` starts the command with no terminal (`stdin` to the null device; `stdout` to
a temporary file for the relay and to the null device for the wake; stderr to a temporary file,
never a pipe), in its own session, in the project root, within `RELAY_TIMEOUT` or `WAKE_TIMEOUT`
seconds (a command that exceeds them has its whole process group killed, `run_in_own_group`), in the environment `manager.client_environment(profile, environ)`. `NUDGE_TOOLS` names
every program a nudge runs by name on `PATH`. `nudger_for(platform)` is `run_nudge` on Linux and
None elsewhere.

Full listing. `read_full_entries(profile, cwd)` and `read_full_listing(profile, cwd)` run `claude-account run agents --json --all` (the
command `listing_command()`) in the project root with no terminal, in its own session, stdout and
stderr to temporary files, in `manager.client_environment(profile, environ)`, within
`LISTING_TIMEOUT` (30) seconds. `read_full_entries` returns every entry of the JSON array that is
an object, in order; `read_full_listing` returns the `sessionId` of every such entry with a
non-empty string `sessionId`, whatever its `kind` or `state` (a completed background session is
listed too); other entries are skipped. `full_lister_for(platform)` is
`read_full_listing` on Linux and None elsewhere. Its failures are `ListingUnreadable` with a
one-line reason: `the project root <cwd> is not a directory` (nothing run),
`claude-account is not installed`, `the listing did not return within 30 s`, the last non-empty
stderr line of a listing that failed else `the listing exited <n>`, or `the listing is not a JSON
array`.

Failures are `NudgeFailed` with a one-line reason: the host is not Linux
(`manager.UNAVAILABLE_TEXT`), `the manager's session is not known`, `the project root <cwd> is not
a directory`, `<program> is not installed`, `the nudge did not return within <n> s`, the last
non-empty stderr line of a nudge that failed, `the nudge exited <n>`, or, for a relay that exited
0 without `SENT`, `the relay did not confirm the message`.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.console import manager

NUDGE_TEXT = ('The owner left you a message on the console. Run "sprint inbox" now and act on '
              "what it returns.")
RESTART_TEXT = ('The console restarted this session because it had stopped while its sprint had '
                'work. Run "sprint contract", then "sprint recap", and go on.')
CONTINUE_TEXT = ('The console found you idle while your sprint has work. Run "sprint recap", '
                 'then "sprint inbox", and go on with the next step.')
RELAY = "relay"
CONTINUE = "continue"
WAKE = "wake"
REVIVE = "revive"
RELAY_TIMEOUT = 180
WAKE_TIMEOUT = 60
SENT_MARK = "SENT"
NUDGE_TOOLS = ("claude-account", "systemd-run")
UNKNOWN_SESSION = "the manager's session is not known"
UNCONFIRMED_TEXT = "the relay did not confirm the message"
LISTING_TIMEOUT = 30


class NudgeFailed(Exception):
    """The manager was not nudged; `str` is the one-line reason."""


class ListingUnreadable(Exception):
    """The full session listing could not be read; `str` is the one-line reason."""


@dataclass(frozen=True)
class Nudge:
    sprint_id: str
    route: str
    session_name: str
    session_id: str | None
    profile: str
    cwd: str
    settings: str | None = None


def relay_prompt(session_name: str, text: str = NUDGE_TEXT) -> str:
    return ('Use the SendMessage tool exactly once, to the peer session named "' + session_name
            + '", with this message and nothing else: ' + text
            + " Then print SENT on its own line if the tool reported the message sent or "
              "accepted, otherwise print FAILED.")


def nudge_command(nudge: Nudge, platform: str) -> list[str] | None:
    if not manager.supported(platform):
        return None
    if nudge.route in (RELAY, CONTINUE):
        text = CONTINUE_TEXT if nudge.route == CONTINUE else NUDGE_TEXT
        return ["claude-account", "run", "-p", "--allowedTools", "SendMessage",
                "--no-session-persistence", relay_prompt(nudge.session_name, text)]
    text = RESTART_TEXT if nudge.route == REVIVE else NUDGE_TEXT
    flags = (["--name", nudge.session_name, "--settings", nudge.settings]
             if nudge.settings is not None else [])
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--description=agent manager {nudge.session_name}", "--",
            "claude-account", "run", "--resume", nudge.session_id, "--bg", *flags, text]


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def run_in_own_group(argv: list[str], *, timeout: float, check: bool = False,
                     **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` for a command started with `start_new_session`: a timeout ends its whole group.

    `subprocess.run` kills only the immediate child, and the account wrapper waits for a Claude child
    instead of replacing itself, so the child would outlive the failure and could still send.
    """
    assert not check, "a nudge's exit status is read by the caller"
    with subprocess.Popen(argv, **kwargs) as process:
        try:
            process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        return subprocess.CompletedProcess(argv, process.returncode)


def run_nudge(nudge: Nudge, *, platform: str = sys.platform, run=run_in_own_group,
              environ: Mapping[str, str] = os.environ) -> None:
    argv = nudge_command(nudge, platform)
    if argv is None:
        raise NudgeFailed(manager.UNAVAILABLE_TEXT)
    if nudge.route in (WAKE, REVIVE) and nudge.session_id is None:
        raise NudgeFailed(UNKNOWN_SESSION)
    if not Path(nudge.cwd).is_dir():
        raise NudgeFailed(f"the project root {nudge.cwd} is not a directory")
    relay = nudge.route in (RELAY, CONTINUE)
    timeout = RELAY_TIMEOUT if relay else WAKE_TIMEOUT
    env = manager.client_environment(nudge.profile, environ)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = run(argv, cwd=nudge.cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=out if relay else subprocess.DEVNULL, stderr=err,
                         start_new_session=True, timeout=timeout, check=False)
        except FileNotFoundError as error:
            raise NudgeFailed(f"{argv[0]} is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise NudgeFailed(f"the nudge did not return within {timeout} s") from error
        out.seek(0)
        stdout = out.read().decode("utf-8", errors="replace")
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise NudgeFailed(_last_line(stderr) or f"the nudge exited {result.returncode}")
    if relay and _last_line(stdout) != SENT_MARK:
        raise NudgeFailed(UNCONFIRMED_TEXT)


def listing_command() -> list[str]:
    return ["claude-account", "run", "agents", "--json", "--all"]


def read_full_entries(profile: str, cwd: str, *, run=run_in_own_group,
                      environ: Mapping[str, str] = os.environ) -> list[dict]:
    if not Path(cwd).is_dir():
        raise ListingUnreadable(f"the project root {cwd} is not a directory")
    argv = listing_command()
    env = manager.client_environment(profile, environ)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                         stderr=err, start_new_session=True, timeout=LISTING_TIMEOUT,
                         check=False)
        except FileNotFoundError:
            raise ListingUnreadable(f"{argv[0]} is not installed") from None
        except subprocess.TimeoutExpired:
            raise ListingUnreadable(
                f"the listing did not return within {LISTING_TIMEOUT} s") from None
        out.seek(0)
        stdout = out.read()
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise ListingUnreadable(_last_line(stderr) or f"the listing exited {result.returncode}")
    try:
        entries = json.loads(stdout.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        entries = None
    if not isinstance(entries, list):
        raise ListingUnreadable("the listing is not a JSON array")
    return [entry for entry in entries if isinstance(entry, dict)]


def read_full_listing(profile: str, cwd: str, *, run=run_in_own_group,
                      environ: Mapping[str, str] = os.environ) -> frozenset[str]:
    entries = read_full_entries(profile, cwd, run=run, environ=environ)
    return frozenset(entry["sessionId"] for entry in entries
                     if isinstance(entry.get("sessionId"), str) and entry["sessionId"])


def full_lister_for(platform: str) -> Callable[[str, str], frozenset[str]] | None:
    return read_full_listing if manager.supported(platform) else None


def nudger_for(platform: str) -> Callable[[Nudge], None] | None:
    return run_nudge if manager.supported(platform) else None
