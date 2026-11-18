"""`launch_profile_check`: the verify check that `claude` launches under the console's profile (#894, after #1012).

`python -m agent_tools.console.launch_profile_check [--url URL]` asks the console which profile a new
session takes (`GET <url>/api/profile`, default `http://127.0.0.1:27184`, which equals the installed
launcher's constant; `http` on `127.0.0.1` or `localhost` at port 27184, the only console the installed
launcher can ask, else exit 2) and launches `claude` twice, each
time with a stub in place of the real client, so no model is reached and nothing of the owner's is written.

Isolation. Every launch runs from an empty working directory in one temporary directory that is removed
at the end, with `HOME` there, `CLAUDE_ACCOUNTS_DIR` there (an empty directory for each of the real
accounts root's named profiles, the names matching `[a-z0-9_-]+` other than `default`, and a
`chosen-profile` file naming the first of them that is not the console's profile, so the launcher's
fallback differs from the console's answer and a launch that ignores `/api/profile` cannot pass on the
fallback), `CLAUDE_BIN` the stub, `CLAUDE_CACHE_PROXY=0`, and `CLAUDE_ACCOUNT`,
`CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_PLUGIN_DIRS`, `CONSOLE_SPRINT_ID` and `CONSOLE_SPRINT_SECRET` removed.
The stub writes the `CLAUDE_CONFIG_DIR` it was started with, as one line, to the file the launch names.

Launches. A is the installed entry point, `claude`, with the console as it is. B is a copy of the whole
packaged launcher module (found through `claude-account` on `PATH`: the launcher itself, or the module
a two-line wrapper executes) whose one `CONSOLE_URL=http://127.0.0.1:27184` line points at a loopback
port the check bound and closed, so no console answers: `claude-account run`.

Verdict. A is met when its client was started under the isolated root's profile directory of the console's
profile; B is met when its client was started under the profile directory of any named profile (the choice
file or the first name, never `default`). One stdout JSON line with sorted keys: `{"status",
"console_profile", "launched", "fallback"}`, plus `reason` when not met.

Exits: 0 met; 1 not met (`the console's profile is not a configured profile`, `the console's profile
answer is malformed`, `the launcher's mod is not found`, `the launcher's console address line is not
found`, `the online launch exited <rc>`, `the offline launch exited <rc>`, `the launch did not reach the
client`, `the launch did not use the console's profile`, `the launch with the console stopped did not use
a named profile`); 75 not yet, with `{"status": ...}` alone: `no_profiles` (no named profile), `one_profile` (the only named profile is the console's, so no fallback can differ from it), `not_running`
(no 200 answer), `no_profile_chosen` (the answer `{"profile": null}`, ADR-console-023 D2), `not_installed`
(no `claude`, or no `claude-account` on `PATH`); 2 a bad argument.

The `run`, `fetch`, `which` and `environ` of `main` are seams for tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import manager_check

DEFAULT_URL = manager_check.DEFAULT_URL
NOT_YET = manager_check.NOT_YET
LAUNCHER_PORT = 27184
TIMEOUT = 60
FETCH_SECONDS = 5
NAME = re.compile(r"[a-z0-9_-]+")
EXEC_LINE = re.compile(r"^exec (/\S+)/bin/claude-account( |$)", re.MULTILINE)
CONSOLE_LINE = "\nCONSOLE_URL=" + DEFAULT_URL + "\n"
DROPPED = ("CLAUDE_ACCOUNT", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_PLUGIN_DIRS",
           "CONSOLE_SPRINT_ID", "CONSOLE_SPRINT_SECRET")
STUB = '#!/bin/sh\nprintf \'%s\\n\' "${CLAUDE_CONFIG_DIR-}" > "$LAUNCH_PROFILE_OUT"\nexit 0\n'


def default_fetch(url: str) -> bytes | None:
    """The body of `GET <url>/api/profile` on a 200 answer, else None."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/profile", timeout=FETCH_SECONDS) as reply:
            return reply.read() if reply.status == 200 else None
    except (OSError, ValueError):
        return None


def named_profiles(root: Path) -> list[str]:
    """The named profiles of an accounts root, sorted: the launcher's `valid_name` directories."""
    try:
        entries = (root / "profiles").iterdir()
        return sorted(p.name for p in entries
                      if NAME.fullmatch(p.name) and p.name != "default" and p.is_dir())
    except OSError:
        return []


def isolated_accounts(real_root: Path, into: Path, choice: str) -> tuple[Path, list[str]]:
    """`into/accounts`: an empty directory per named profile of `real_root` and a choice file naming `choice`."""
    names = named_profiles(real_root)
    accounts = into / "accounts"
    for name in names:
        (accounts / "profiles" / name).mkdir(parents=True)
    accounts.mkdir(exist_ok=True)
    (accounts / "chosen-profile").write_text(choice + "\n")
    return accounts, names


def stub_client(into: Path) -> Path:
    client = into / "client"
    client.write_text(STUB)
    client.chmod(0o755)
    return client


def launch_env(environ: Mapping[str, str], accounts: Path, home: Path, client: Path, out: Path) -> dict[str, str]:
    env = {key: value for key, value in environ.items() if key not in DROPPED}
    env.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(accounts), CLAUDE_BIN=str(client),
               CLAUDE_CACHE_PROXY="0", LAUNCH_PROFILE_OUT=str(out))
    return env


def launch(run: Callable, argv: list[str], cwd: Path, env: dict[str, str]) -> int:
    return run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=False, start_new_session=True).returncode


def find_mod(which: Callable[[str], str | None]) -> Path | None:
    """The packaged launcher module: the launcher's own directory tree, or the one a wrapper executes."""
    found = which("claude-account")
    if found is None:
        return None
    real = Path(os.path.realpath(found))
    try:
        text = real.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    if CONSOLE_LINE in "\n" + text:
        return real.parent.parent
    match = EXEC_LINE.search(text)
    return Path(os.path.realpath(match.group(1))) if match else None


def closed_url() -> str:
    """A loopback URL whose port was bound and closed just now, so nothing listens on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return "http://127.0.0.1:%d" % probe.getsockname()[1]


def copy_mod(mod: Path, into: Path, console_url: str) -> Path:
    """A writable copy of the whole `mod` at `into/mod` whose launcher asks `console_url`; the launcher's path."""
    copy = into / "mod"
    shutil.copytree(mod, copy, symlinks=True)
    for directory in [copy, *(p for p in copy.rglob("*") if p.is_dir() and not p.is_symlink())]:
        directory.chmod(directory.stat().st_mode | 0o700)
    launcher = copy / "bin" / "claude-account"
    launcher.chmod(launcher.stat().st_mode | 0o200)
    text = launcher.read_text()
    if text.count(CONSOLE_LINE) != 1:
        raise LookupError("the launcher's console address line is not found")
    launcher.write_text(text.replace(CONSOLE_LINE, "\nCONSOLE_URL=" + console_url + "\n"))
    return launcher


def _print(document: dict) -> None:
    manager_check._print(document)


def _launcher_url(text: str) -> str:
    """A loopback URL at the port the installed launcher asks, the only console this check can read."""
    url = manager_check._loopback_url(text)
    if urlsplit(url).port != LAUNCHER_PORT:
        raise argparse.ArgumentTypeError(
            f"the installed launcher asks port {LAUNCHER_PORT} only, so no other console can be checked")
    return url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="launch_profile_check", description=__doc__.splitlines()[0])
    parser.add_argument("--url", type=_launcher_url, default=DEFAULT_URL)
    return parser


def _recorded(out: Path) -> str | None:
    try:
        return out.read_text().rstrip("\n")
    except OSError:
        return None


def _name_of(line: str | None, accounts: Path) -> str | None:
    """The profile a recorded line is the directory of, else the line itself."""
    if line is not None and Path(line).parent == accounts / "profiles":
        return Path(line).name
    return line


def main(argv: list[str] | None = None, *, run: Callable = subprocess.run,
         fetch: Callable[[str], bytes | None] = default_fetch,
         which: Callable[[str], str | None] = shutil.which,
         environ: Mapping[str, str] = os.environ) -> int:
    args = build_parser().parse_args(argv)
    home = environ.get("HOME") or str(Path.home())
    real_root = Path(environ.get("CLAUDE_ACCOUNTS_DIR") or Path(home) / ".claude-accounts")
    names = named_profiles(real_root)
    if not names:
        _print({"status": "no_profiles"})
        return NOT_YET
    body = fetch(args.url)
    if body is None:
        _print({"status": "not_running"})
        return NOT_YET
    try:
        answer = json.loads(body)
    except ValueError:
        answer = None
    if answer == {"profile": None}:
        _print({"status": "no_profile_chosen"})
        return NOT_YET
    report = {"console_profile": None, "fallback": None, "launched": None, "status": "not_met"}

    def not_met(reason: str) -> int:
        _print({**report, "reason": reason})
        return 1

    if not (isinstance(answer, dict) and list(answer) == ["profile"] and isinstance(answer["profile"], str)):
        return not_met("the console's profile answer is malformed")
    console = answer["profile"]
    report["console_profile"] = console
    if console not in names:
        return not_met("the console's profile is not a configured profile")
    decoy = next((name for name in names if name != console), None)
    if decoy is None:
        _print({"status": "one_profile"})
        return NOT_YET
    with tempfile.TemporaryDirectory() as made:
        t = Path(made)
        accounts, _ = isolated_accounts(real_root, t, decoy)
        (t / "home").mkdir()
        (t / "work").mkdir()
        client = stub_client(t)

        def start(argv: list[str], label: str) -> tuple[str | None, str | None]:
            """(the recorded line, a reason it is not met)."""
            out = t / ("out-" + label)
            code = launch(run, argv, t / "work", launch_env(environ, accounts, t / "home", client, out))
            if code != 0:
                return None, f"the {label} launch exited {code}"
            line = _recorded(out)
            return line, None if line is not None else "the launch did not reach the client"

        try:
            online, reason = start(["claude"], "online")
        except FileNotFoundError:
            _print({"status": "not_installed"})
            return NOT_YET
        if reason:
            return not_met(reason)
        report["launched"] = _name_of(online, accounts)
        mod = find_mod(which)
        if mod is None:
            if which("claude-account") is None:
                _print({"status": "not_installed"})
                return NOT_YET
            return not_met("the launcher's mod is not found")
        try:
            launcher = copy_mod(mod, t, closed_url())
        except LookupError as error:
            return not_met(str(error))
        offline, reason = start([str(launcher), "run"], "offline")
        if reason:
            return not_met(reason)
        report["fallback"] = _name_of(offline, accounts)
        if online != str(accounts / "profiles" / console):
            return not_met("the launch did not use the console's profile")
        if report["fallback"] not in names or offline != str(accounts / "profiles" / report["fallback"]):
            return not_met("the launch with the console stopped did not use a named profile")
    report["status"] = "met"
    _print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
