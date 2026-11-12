"""The nudge: one fixed sentence that tells a sprint's manager to read its inbox (#889).

The owner's words never travel in a nudge. A nudge carries `NUDGE_TEXT`, one fixed sentence that
names no sprint, project or owner text; the manager runs `sprint inbox` (which authenticates with
the sprint's secret) and reads the message there. `Nudge` has no text member, and no argv element
or environment value carries anything for the manager but `NUDGE_TEXT`.

Two routes, chosen by the caller (this module only runs the one it is given):

    relay: claude-account run -p --allowedTools SendMessage --no-session-persistence "<prompt>"

`relay_prompt(session_name)` is `Use the SendMessage tool exactly once, to the peer session named
"<name>", with this message and nothing else: ` + `NUDGE_TEXT` + ` Then print SENT on its own
line if the tool reported the message sent or accepted, otherwise print FAILED.` The relay sends
by session name (the tool's recipient accepts a peer session name) and is delivered only when its
last non-empty stdout line is exactly `SENT`.

    wake: systemd-run --user --scope --quiet --collect --description=agent manager <name> --
          claude-account run --resume <session id> --bg "<NUDGE_TEXT>"

The wake resumes by session id inside a transient user scope, so a supervisor it starts outlives
the console unit (ADR-console-015). `--resume <id> --bg` wakes a stopped session in place under
the same id, but starts a copy of a session that is running; the caller must therefore use the
wake only for a session the session listing does not show (issue #831). A wake with no session id
raises `NudgeFailed(UNKNOWN_SESSION)` and runs nothing.

Runner. `run_nudge` starts the command with no terminal (`stdin` to the null device; `stdout` to
a temporary file for the relay and to the null device for the wake; stderr to a temporary file,
never a pipe), in its own session, in the project root, within `RELAY_TIMEOUT` or `WAKE_TIMEOUT`
seconds (a command that exceeds them has its whole process group killed, `run_in_own_group`), in the environment `manager.client_environment(profile, environ)`. `NUDGE_TOOLS` names
every program a nudge runs by name on `PATH`. `nudger_for(platform)` is `run_nudge` on Linux and
None elsewhere.

Failures are `NudgeFailed` with a one-line reason: the host is not Linux
(`manager.UNAVAILABLE_TEXT`), `the manager's session is not known`, `the project root <cwd> is not
a directory`, `<program> is not installed`, `the nudge did not return within <n> s`, the last
non-empty stderr line of a nudge that failed, `the nudge exited <n>`, or, for a relay that exited
0 without `SENT`, `the relay did not confirm the message`.
"""

from __future__ import annotations

import contextlib
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
RELAY = "relay"
WAKE = "wake"
RELAY_TIMEOUT = 180
WAKE_TIMEOUT = 60
SENT_MARK = "SENT"
NUDGE_TOOLS = ("claude-account", "systemd-run")
UNKNOWN_SESSION = "the manager's session is not known"
UNCONFIRMED_TEXT = "the relay did not confirm the message"


class NudgeFailed(Exception):
    """The manager was not nudged; `str` is the one-line reason."""


@dataclass(frozen=True)
class Nudge:
    sprint_id: str
    route: str
    session_name: str
    session_id: str | None
    profile: str
    cwd: str


def relay_prompt(session_name: str) -> str:
    return ('Use the SendMessage tool exactly once, to the peer session named "' + session_name
            + '", with this message and nothing else: ' + NUDGE_TEXT
            + " Then print SENT on its own line if the tool reported the message sent or "
              "accepted, otherwise print FAILED.")


def nudge_command(nudge: Nudge, platform: str) -> list[str] | None:
    if not manager.supported(platform):
        return None
    if nudge.route == RELAY:
        return ["claude-account", "run", "-p", "--allowedTools", "SendMessage",
                "--no-session-persistence", relay_prompt(nudge.session_name)]
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--description=agent manager {nudge.session_name}", "--",
            "claude-account", "run", "--resume", nudge.session_id, "--bg", NUDGE_TEXT]


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
    if nudge.route == WAKE and nudge.session_id is None:
        raise NudgeFailed(UNKNOWN_SESSION)
    if not Path(nudge.cwd).is_dir():
        raise NudgeFailed(f"the project root {nudge.cwd} is not a directory")
    relay = nudge.route == RELAY
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


def nudger_for(platform: str) -> Callable[[Nudge], None] | None:
    return run_nudge if manager.supported(platform) else None
