"""`hook_cost`: the verify check that a stopped console adds no cost to a session's hook calls (#857).

`python -m agent_tools.console.hook_cost [--settings PATH] [--calls N] [--budget-ms MS]` reads the
Claude Code settings (default `$HOME/.claude/settings.json`), selects the console's hooks and times
each one `--calls` (default 10) times in two modes. The reason (decision P9, #838 item 6: at most
10 ms added per hook call): a tool call pays the console only through these hooks, so a hook
delivery to a closed port is exactly what a stopped console adds to a session.

Selection (`console_hooks`): an HTTP hook whose url is `http` on a loopback host (`127.0.0.1` or
`localhost`) with the path `service.HOOK_PATH`, and a command hook whose `command` is one path (no
whitespace) with a basename ending `-console-session-start`. Every other hook, under any event, is
ignored, and a malformed shape is ignored, never fatal; the module therefore runs no command but a
selected console script and contacts no address but `127.0.0.1` on a port it chose. An HTTP hook is
always timed against `127.0.0.1`, whatever its url names.

Stopped mode targets a free loopback port (bound to port 0 and closed), never the deployed
console's port. Running mode targets a scratch console (a temporary store and registry, `port=0`,
no session directories) that is closed and deleted afterwards. An HTTP hook POSTs a recorded
`PermissionRequest` payload, a command hook gets a recorded `SessionStart` payload on stdin and
the port as its argument; both carry the temporary directory as `cwd`. Errors are swallowed and the
call is still timed.

Output is one stdout line of JSON with sorted keys. Settings that are absent, unreadable, not JSON
or that select no console HTTP hook are `{"status": "not_deployed"}` and exit 75; nothing is run or
contacted. Otherwise `{"budget_ms", "calls", "hooks": [{"event", "kind", "running": {"max",
"median"}, "stopped": {"max", "median"}}], "status"}`, one member per selected hook, in
`(event, kind)` order, times in milliseconds. `status` is `met` (exit 0) exactly when every selected
hook's stopped-mode median is at most `budget_ms` (default 10.0), else `not_met` (exit 1); running
figures are reported and never gate. A bad argument is exit 2. Nothing is written outside the
temporary directory.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import service

SCRIPT_SUFFIX = "-console-session-start"
LOOPBACK = ("127.0.0.1", "localhost")
DEFAULT_CALLS = 10
DEFAULT_BUDGET_MS = 10.0
DEFAULT_TIMEOUT = 2.0
COMMAND_TIMEOUT = 10.0
NOT_YET = 75

_COMMON = {"session_id": "6f1c2a9e-0000-4000-8000-000000000001",
           "transcript_path": "/home/u/.claude/projects/-srv-p00/6f1c2a9e.jsonl",
           "prompt_id": "p-1", "permission_mode": "auto"}
PERMISSION_REQUEST = {**_COMMON, "hook_event_name": "PermissionRequest", "tool_name": "Bash",
                      "tool_input": {"command": "rm -rf build"},
                      "permission_suggestions": [{"type": "addRules"}]}
SESSION_START = {**_COMMON, "hook_event_name": "SessionStart", "source": "startup",
                 "model": "claude-opus-5-5"}


def _is_console_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == "http" and parts.hostname in LOOPBACK
                and parts.path == service.HOOK_PATH)
    except ValueError:
        return False


def _is_console_script(command: object) -> bool:
    return (isinstance(command, str) and len(command.split()) == 1
            and os.path.basename(command).endswith(SCRIPT_SUFFIX))


def _timeout(value: object) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    return float(value) if ok else DEFAULT_TIMEOUT


def console_hooks(settings: Mapping) -> list[dict]:
    """Every console hook of `settings`, sorted by (event, kind); everything else is ignored."""
    found: list[dict] = []
    events = settings.get("hooks") if isinstance(settings, Mapping) else None
    if not isinstance(events, Mapping):
        return found
    for event, matchers in events.items():
        if not isinstance(event, str) or not isinstance(matchers, list):
            continue
        for matcher in matchers:
            hooks = matcher.get("hooks") if isinstance(matcher, Mapping) else None
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, Mapping):
                    continue
                if hook.get("type") == "http" and _is_console_url(hook.get("url")):
                    found.append({"event": event, "kind": "http",
                                  "path": urlsplit(hook["url"]).path,
                                  "timeout": _timeout(hook.get("timeout"))})
                elif hook.get("type") == "command" and _is_console_script(hook.get("command")):
                    found.append({"event": event, "kind": "command",
                                  "command": hook["command"]})
    return sorted(found, key=lambda hook: (hook["event"], hook["kind"]))


def time_http(path: str, port: int, timeout: float, body: bytes, calls: int) -> list[float]:
    """Milliseconds of `calls` POSTs of `body` to 127.0.0.1:`port`; errors are swallowed and timed."""
    times = []
    for _ in range(calls):
        started = time.perf_counter()
        connection = http.client.HTTPConnection(service.HOST, port, timeout=timeout)
        try:
            connection.request("POST", path, body=body,
                               headers={"Content-Type": "application/json"})
            connection.getresponse().read()
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        times.append((time.perf_counter() - started) * 1000)
    return times


def time_command(command: str, port: int, body: bytes, calls: int) -> list[float]:
    """Milliseconds of `calls` runs of `command PORT` with `body` on stdin; errors are swallowed."""
    times = []
    for _ in range(calls):
        started = time.perf_counter()
        try:
            subprocess.run([command, str(port)], input=body, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        times.append((time.perf_counter() - started) * 1000)
    return times


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((service.HOST, 0))
        return probe.getsockname()[1]


def _figures(times: list[float]) -> dict:
    return {"max": float(max(times)), "median": float(statistics.median(times))}


def _measure(hook: dict, port: int, bodies: dict, calls: int) -> dict:
    if hook["kind"] == "http":
        return _figures(time_http(hook["path"], port, hook["timeout"], bodies["http"], calls))
    return _figures(time_command(hook["command"], port, bodies["command"], calls))


def _load(path: Path) -> Mapping | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, Mapping) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hook_cost", description=__doc__.splitlines()[0])
    parser.add_argument("--settings", type=Path,
                        default=Path(os.path.expanduser("~")) / ".claude" / "settings.json",
                        help="Claude Code settings to read (default: %(default)s)")
    parser.add_argument("--calls", type=int, default=DEFAULT_CALLS,
                        help="timed calls per hook and mode (default: %(default)s)")
    parser.add_argument("--budget-ms", type=float, default=DEFAULT_BUDGET_MS,
                        help="stopped-mode median allowed per hook (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.calls < 1:
        parser.error("--calls must be at least 1")
    if not args.budget_ms >= 0:
        parser.error("--budget-ms must not be negative")
    settings = _load(args.settings)
    hooks = [] if settings is None else console_hooks(settings)
    if not any(hook["kind"] == "http" for hook in hooks):
        print(json.dumps({"status": "not_deployed"}, sort_keys=True))
        return NOT_YET
    directory = Path(tempfile.mkdtemp(prefix="console-hook-cost-"))
    try:
        bodies = {"http": json.dumps({**PERMISSION_REQUEST, "cwd": str(directory)}).encode(),
                  "command": json.dumps({**SESSION_START, "cwd": str(directory)}).encode()}
        stopped_port = _free_port()
        scratch = service.ConsoleService(
            directory / "events.sqlite3", directory / "registry.json", port=0,
            session_dirs=lambda: [])
        try:
            scratch.start()
            running_port = scratch.address[1]
            report = [{"event": hook["event"], "kind": hook["kind"],
                       "running": _measure(hook, running_port, bodies, args.calls),
                       "stopped": _measure(hook, stopped_port, bodies, args.calls)}
                      for hook in hooks]
        finally:
            scratch.close()
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    met = all(entry["stopped"]["median"] <= args.budget_ms for entry in report)
    print(json.dumps({"budget_ms": float(args.budget_ms), "calls": args.calls, "hooks": report,
                      "status": "met" if met else "not_met"}, sort_keys=True))
    return 0 if met else 1


if __name__ == "__main__":
    sys.exit(main())
