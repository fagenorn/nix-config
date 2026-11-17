"""`permission_check`: the verify check that the first manager started under the permission change runs in its logged mode (#1151, AC4).

`python -m agent_tools.console.permission_check --project ID [--log PATH] [--accounts DIR] [--home DIR]`
prints one stdout line of JSON with sorted keys; exit 0 met, 1 not met, 75 not yet, 2 a bad argument.
Defaults: `--log` `<state_root()>/console/events.sqlite3`, `--accounts` `$CLAUDE_ACCOUNTS_DIR` else
`$HOME/.claude-accounts`, `--home` `$HOME`. It is read only: the event log is opened `mode=ro` and
nothing is written anywhere.

The judged manager (plan D4, ADR-console-059) is the first (lowest seq) `manager.started` row of
`--project` whose payload has a string `sprint_id` and `session_name`, an int `seen_after` (not a
bool, at least 0) and a `permission` that `permission.from_payload` accepts. Only code that carries
the permission change writes `permission`, so a manager started before the activation never
qualifies; the log is append-only, so every run judges the same row, and a later started row never
replaces it, whatever its outcome.

Its session follows the fold's `seen_after` rule: the candidates are `session.seen` rows whose
`name` is the row's `session_name`, with a string `session_id` and `seq` above the row's
`seen_after` (a session seen before the launcher returned counts, the predecessor's never does);
when a later `manager.started` row of the same `sprint_id` exists, a candidate's `seq` is also at
most that row's `seen_after`. The judged session is the candidate with the lowest seq. Its
transcript is `<accounts>/profiles/*/projects/*/<session_id>.jsonl` or
`<home>/.claude/projects/*/<session_id>.jsonl`; the first line (file order, lines that are not JSON
objects skipped) with a string `permissionMode` gives the session's mode.

The first unmet step wins and is exit 75 `{"status": "not_yet", "reason": ...}`, carrying `sprint_id`
once a row is selected: `no_log` (the log is absent or cannot be opened), `no_manager` (no qualifying
started row), `not_seen` (no candidate session), `no_transcript` (no transcript file), `no_mode` (no
line with a `permissionMode`). Otherwise the check is met when that mode equals the row's
`permission.mode`: exit 0 `{"status": "met", "sprint_id", "session_id", "mode", "text"}`; else exit 1
`{"status": "not_met", "sprint_id", "session_id", "mode": <the transcript's>, "expected": <the
row's>, "text"}`. `text` is `Permission.text`.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

from agent_tools.console import permission
from agent_tools.project_contract import agent_platform

NOT_YET = 75


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="permission_check", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project id whose manager is judged")
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--accounts", type=Path, default=None)
    parser.add_argument("--home", type=Path, default=None)
    return parser


def _payload(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _seen_after(payload: dict) -> int | None:
    value = payload.get("seen_after")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _qualifies(payload: dict) -> bool:
    return (isinstance(payload.get("sprint_id"), str) and isinstance(payload.get("session_name"), str)
            and _seen_after(payload) is not None and permission.from_payload(payload.get("permission")) is not None)


def _rows(log: Path, project: str) -> tuple[list, list] | None:
    """`(started, seen)` as `(seq, payload)` lists in seq order, None when the log cannot be read."""
    try:
        connection = sqlite3.connect(f"{log.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return None
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT seq, kind, project, payload FROM events "
            "WHERE kind IN ('manager.started', 'session.seen') ORDER BY seq").fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    started, seen = [], []
    for seq, kind, row_project, text in rows:
        payload = _payload(text)
        if payload is None:
            continue
        if kind == "manager.started" and row_project == project:
            started.append((seq, payload))
        elif kind == "session.seen":
            seen.append((seq, payload))
    return started, seen


def _transcripts(session_id: str, accounts: Path, home: Path) -> list[str]:
    name = glob.escape(session_id) + ".jsonl"
    return sorted(
        glob.glob(os.path.join(glob.escape(str(accounts)), "profiles", "*", "projects", "*", name))
        + glob.glob(os.path.join(glob.escape(str(home)), ".claude", "projects", "*", name)))


def _first_mode(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                entry = _payload(line)
                if entry is not None and isinstance(entry.get("permissionMode"), str):
                    return entry["permissionMode"]
    except OSError:
        return None
    return None


def verdict(project: str, log: Path, accounts: Path, home: Path) -> tuple[int, dict]:
    rows = _rows(log, project)
    if rows is None:
        return NOT_YET, {"status": "not_yet", "reason": "no_log"}
    started, seen = rows
    chosen = next(((seq, payload) for seq, payload in started if _qualifies(payload)), None)
    if chosen is None:
        return NOT_YET, {"status": "not_yet", "reason": "no_manager"}
    seq, payload = chosen
    sprint_id, name, floor = payload["sprint_id"], payload["session_name"], payload["seen_after"]
    expected = permission.from_payload(payload["permission"])

    def not_yet(reason: str) -> tuple[int, dict]:
        return NOT_YET, {"status": "not_yet", "reason": reason, "sprint_id": sprint_id}

    ceiling = next((later["seen_after"] for later_seq, later in started
                    if later_seq > seq and later.get("sprint_id") == sprint_id
                    and _seen_after(later) is not None), None)
    predecessors = {row["session_id"] for at, row in seen
                    if row.get("name") == name and isinstance(row.get("session_id"), str)
                    and at <= floor}
    candidates = [(at, row["session_id"]) for at, row in seen
                  if row.get("name") == name and isinstance(row.get("session_id"), str)
                  and at > floor and (ceiling is None or at <= ceiling)
                  and row["session_id"] not in predecessors]
    if not candidates:
        return not_yet("not_seen")
    session_id = candidates[0][1]
    files = _transcripts(session_id, accounts, home)
    if not files:
        return not_yet("no_transcript")
    mode = next((found for found in map(_first_mode, files) if found is not None), None)
    if mode is None:
        return not_yet("no_mode")
    output = {"sprint_id": sprint_id, "session_id": session_id, "mode": mode, "text": expected.text}
    if mode == expected.mode:
        return 0, {"status": "met", **output}
    return 1, {"status": "not_met", **output, "expected": expected.mode}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = args.home or Path(os.environ["HOME"])
    accounts = args.accounts or Path(os.environ.get("CLAUDE_ACCOUNTS_DIR") or home / ".claude-accounts")
    log = args.log or agent_platform.state_root() / "console" / "events.sqlite3"
    code, output = verdict(args.project, log, accounts, home)
    print(json.dumps(output, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
