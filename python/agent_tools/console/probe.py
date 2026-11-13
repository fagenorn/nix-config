"""The console's capacity probe: one small request under an account profile, so an idle or exhausted profile gets a limit reading (#1009, ADR-console-006).

Command. `probe_command(Probe(profile, session_id))` is `claude-account run -p --session-id
<session_id> --no-session-persistence --strict-mcp-config --model haiku --max-turns 1 "Reply with
the single word OK."` (`MODEL`, `PROMPT`). The client's own login signs the request; nothing here
reads a credential, and nothing reads a clock (`now` and `started_at` are arguments).

Environment. `probe_environment(profile, environ)` is `manager.client_environment(profile, environ)`
without `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`, and with
`CLAUDE_CACHE_PROXY=required` (over any inherited value): `claude-account` routes the launch through
the cache proxy or refuses it without starting Claude, so a probe never reaches the API direct
when the proxy is down.

Runner. `run_probe(probe, *, run, environ, timeout)` calls `run` once, by default
`manager.run_in_own_group`, never plain `subprocess.run`: in a new empty temporary directory
(`console-probe-*`, removed after the call), with no terminal and nothing read back (`stdin`,
`stdout` and `stderr` to the null device), in its own session, within `timeout` (`PROBE_TIMEOUT`,
120) seconds. A timeout kills and reaps the whole process group, the launcher and the Claude
child it waits on, before `run_probe` raises, so no process of the probe is left that could still
send. It opens no file of its own besides the temporary directory.

Failures are `ProbeFailed(kind)` with `kind` one of `KINDS`, and `str(error) == kind`:
`not_installed` (`claude-account` is not on `PATH`), `timed_out` (the probe did not return in time),
`unavailable` (any other `OSError`), `exited` (a non-zero exit status). Exit 0 returns None.
`prober_for(platform)` is `run_probe` where `manager.supported(platform)`, else None.

Schedule. `due_profiles(profiles, in_flight, last_started, started_at, now)` returns, sorted, each
profile not in `in_flight` that is either in `last_started` with `now - last_started[p] >=
PROBE_SECONDS` (600), or not in `last_started` with `now - started_at >= PROBE_FIRST_SECONDS` (30).
`PROBE_MEMORY` (256) is the number of probe sessions the service remembers.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from agent_tools.console import manager

PROBE_SECONDS = 600
PROBE_FIRST_SECONDS = 30
PROBE_TIMEOUT = 120
PROBE_MEMORY = 256
MODEL = "haiku"
PROMPT = "Reply with the single word OK."
KINDS = ("not_installed", "timed_out", "unavailable", "exited")

_DROPPED_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True)
class Probe:
    profile: str
    session_id: str


class ProbeFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def probe_command(probe: Probe) -> list[str]:
    return ["claude-account", "run", "-p", "--session-id", probe.session_id,
            "--no-session-persistence", "--strict-mcp-config", "--model", MODEL,
            "--max-turns", "1", PROMPT]


def probe_environment(profile: str, environ: Mapping[str, str]) -> dict[str, str]:
    env = manager.client_environment(profile, environ)
    for key in _DROPPED_ENV:
        env.pop(key, None)
    env["CLAUDE_CACHE_PROXY"] = "required"
    return env


def run_probe(probe: Probe, *, run=manager.run_in_own_group,
              environ: Mapping[str, str] = os.environ, timeout: float = PROBE_TIMEOUT) -> None:
    argv = probe_command(probe)
    env = probe_environment(probe.profile, environ)
    with tempfile.TemporaryDirectory(prefix="console-probe-") as cwd:
        try:
            result = run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, timeout=timeout, check=False)
        except FileNotFoundError as error:
            raise ProbeFailed("not_installed") from error
        except subprocess.TimeoutExpired as error:
            raise ProbeFailed("timed_out") from error
        except OSError as error:
            raise ProbeFailed("unavailable") from error
    if result.returncode != 0:
        raise ProbeFailed("exited")


def prober_for(platform: str) -> Callable[[Probe], None] | None:
    return run_probe if manager.supported(platform) else None


def due_profiles(profiles: Iterable[str], in_flight: Collection[str],
                 last_started: Mapping[str, float], started_at: float, now: float) -> list[str]:
    due = []
    for profile in profiles:
        if profile in in_flight:
            continue
        if profile in last_started:
            if now - last_started[profile] >= PROBE_SECONDS:
                due.append(profile)
        elif now - started_at >= PROBE_FIRST_SECONDS:
            due.append(profile)
    return sorted(due)
