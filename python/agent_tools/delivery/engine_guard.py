"""The engine's lifecycle-guard seam: locate the hook and judge one command (issue 1515).

The engine asks the installed lifecycle guard before it runs a command, so a
command the guard refuses in a Claude Code session is refused here too.

  D4  The guard is found by its generated name: the one Bash command hook of
      `~/.claude/settings.json` whose command ends with
      `/bin/claude-bash-lifecycle-guard`. Any other settings shape is
      `Unavailable`, and `locate` never raises. A settings document with a hook
      switch on loads no user hook, a Bash hook with an `if` filter may be
      skipped, and an asynchronous Bash hook (`async` or `asyncRewake` set) may refuse
      after the tool has run, so all three are `Unavailable` too. Given the launch
      directory, its project settings (`PROJECT_SETTINGS`) are read too: one that cannot
      be read as a JSON object or that turns a hook switch on is `Unavailable`.
  D5  `judge` runs that hook as a subprocess with the Bash PreToolUse payload on
      stdin and `directory` as its working directory. Only exit 0 allows; exit 2
      refuses with the guard's stderr minus one line ending; any other exit, a
      timeout or a spawn failure refuses with a sentence. The guard's group and
      every descendant it has, whatever session each runs in, are killed and its
      child reaped on a timeout, on any interrupt and on SIGTERM. Given `stop`, the
      wait polls it and raises `engine_stop.Stopped` once it is true, the guard reaped.
  D6  `judge` never raises on the guard's account and never writes to the
      caller's stdout or stderr: both guard pipes are captured and stdout is
      never read.

The guard program itself is never imported; it is only run.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import engine_stop

SETTINGS = Path(".claude") / "settings.json"
PROJECT_SETTINGS = (Path(".claude") / "settings.json", Path(".claude") / "settings.local.json")
MAX_TIMEOUT_SECONDS = 3600
GUARD_SUFFIX = "/bin/claude-bash-lifecycle-guard"
HOOK_SWITCHES = ("allowManagedHooksOnly", "disableAllHooks")
ASYNC_KEYS = ("async", "asyncRewake")


@dataclass(frozen=True)
class Hook:
    command: str
    timeout: float


@dataclass(frozen=True)
class Unavailable:
    reason: str


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None


def settings_path(environ: Mapping[str, str]) -> Path | Unavailable:
    """`$HOME/.claude/settings.json`, or `Unavailable` unless HOME is an absolute path.

    A relative or empty HOME would resolve against the invocation directory, so the
    checkout could supply the settings that select its own authorizing executable.
    """
    home = environ.get("HOME", "")
    if not home or not os.path.isabs(home):
        return Unavailable("The settings cannot be located: HOME is not an absolute path.")
    return Path(home) / SETTINGS


def _timeout_defect(timeout: object) -> str | None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        return "its timeout is not a number"
    try:
        seconds = float(timeout)
    except OverflowError:
        return "its timeout is too large"
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        return f"its timeout is not above 0 and at most {MAX_TIMEOUT_SECONDS} seconds"
    return None


def _defect(document: object) -> tuple[Hook | None, str]:
    if not isinstance(document, dict):
        return None, "it is not a JSON object"
    for name in HOOK_SWITCHES:
        if name in document and document[name] is not False:
            return None, f"its {name} switch is on"
    hooks = document.get("hooks")
    entries = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        return None, "it has no hooks.PreToolUse list"
    bash = [e for e in entries if isinstance(e, dict) and e.get("matcher") == "Bash"]
    if len(bash) != 1:
        return None, f"it has {len(bash)} Bash entries, not one"
    items = bash[0].get("hooks")
    commands = [h for h in items if isinstance(h, dict) and h.get("type") == "command"] \
        if isinstance(items, list) else []
    if len(commands) != 1:
        return None, f"its Bash entry has {len(commands)} command hooks, not one"
    hook = commands[0]
    if "if" in hook or "if" in bash[0]:
        return None, "its Bash hook has an if filter"
    command = hook.get("command")
    if not isinstance(command, str) or not command.startswith("/") \
            or any(c.isspace() for c in command) or "\x00" in command:
        return None, "its Bash hook command is not one absolute path"
    if not command.endswith(GUARD_SUFFIX):
        return None, f"the Bash hook {command} is not the lifecycle guard"
    if "args" in hook and hook["args"] != []:
        return None, "its Bash hook has arguments"
    for name in ASYNC_KEYS:
        if name in hook and hook[name] is not False:
            return None, f"its Bash hook is asynchronous ({name})"
    problem = _timeout_defect(hook.get("timeout"))
    if problem:
        return None, f"its Bash hook {problem}"
    return Hook(command, float(hook["timeout"])), ""


def _project_defect(directory: str) -> Unavailable | None:
    for relative in PROJECT_SETTINGS:
        path = Path(directory) / relative
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"),
                                  object_pairs_hook=reject_duplicate_keys,
                                  parse_constant=reject_nonfinite_literal)
        except (OSError, ValueError, RecursionError) as error:
            return Unavailable(f"The project settings {path} cannot be read: {str(error).rstrip('.')}.")
        if not isinstance(document, dict):
            return Unavailable(f"The project settings {path} are not a JSON object.")
        for name in HOOK_SWITCHES:
            if name in document and document[name] is not False:
                return Unavailable(f"The project settings {path} turn the hooks off: "
                                   f"their {name} switch is on.")
    return None


def locate(settings: Path | Unavailable, directory: str | None = None) -> Hook | Unavailable:
    if isinstance(settings, Unavailable):
        return settings
    if directory is not None and (defect := _project_defect(directory)) is not None:
        return defect
    try:
        document = json.loads(settings.read_text(encoding="utf-8"),
                              object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError, RecursionError) as error:
        return Unavailable(f"The settings {settings} cannot be read: {str(error).rstrip('.')}.")
    hook, defect = _defect(document)
    if hook is None:
        return Unavailable(f"The settings {settings} name no usable guard: {defect}.")
    return hook


def payload(text: str, directory: str) -> bytes:
    return json.dumps({"cwd": directory, "hook_event_name": "PreToolUse",
                       "tool_input": {"command": text}, "tool_name": "Bash"},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _descendants(root: int) -> list[int]:
    """Every process below `root` in the process tree, whatever session it runs in."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                                 text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        words = line.split()
        if len(words) == 2 and all(word.isdigit() for word in words):
            children.setdefault(int(words[1]), []).append(int(words[0]))
    found, pending = [], [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found.append(child)
                pending.append(child)
    return found


def _reap(process: subprocess.Popen) -> None:
    # The guard runs its policy row check in a session of its own, so the group kill
    # below misses it. Stop the guard first so it starts nothing more, take its
    # descendants while it still parents them, then kill them all.
    try:
        os.kill(process.pid, signal.SIGSTOP)
    except (ProcessLookupError, PermissionError):
        pass
    for pid in _descendants(process.pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.kill()
    except ProcessLookupError:
        pass
    process.wait()
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


def judge(guard: Hook | Unavailable, text: str, directory: str,
          stop: Callable[[], bool] | None = None) -> Verdict:
    if isinstance(guard, Unavailable):
        return Verdict(False, guard.reason)
    try:
        previous = signal.signal(signal.SIGTERM, _terminate)
    except ValueError:  # not the main thread: no handler can be installed
        previous = None
    try:
        try:
            process = subprocess.Popen([guard.command], cwd=directory, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
        except (OSError, ValueError) as error:
            return Verdict(False, f"The lifecycle guard {guard.command} cannot be run: {error}.")
        try:
            _, stderr = engine_stop.communicate(process, payload(text, directory), stop=stop,
                                                timeout=guard.timeout)
        except subprocess.TimeoutExpired:
            _reap(process)
            return Verdict(False, f"The lifecycle guard {guard.command} did not answer within "
                                  f"{guard.timeout:g} seconds.")
        except BaseException:  # a stop raises `engine_stop.Stopped` once the guard is reaped
            if process.returncode is None:  # a guard already waited for has no group to reap
                _reap(process)
            raise
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    code = process.returncode
    if code == 0:
        return Verdict(True, None)
    said = stderr.decode("utf-8", "replace")
    for ending in ("\r\n", "\n"):
        if said.endswith(ending):
            said = said[:-len(ending)]
            break
    if code == 2:
        if said.strip():
            return Verdict(False, said)
        return Verdict(False, f"The lifecycle guard {guard.command} refused with no reason.")
    return Verdict(False, f"The lifecycle guard {guard.command} exited {code}: "
                          f"{said if said.strip() else 'no output'}.")
