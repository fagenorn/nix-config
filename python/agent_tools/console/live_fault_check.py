"""`live_fault_check`: the verify script that the first live-fault delivery reached a green pull request within the hour (#1433, AC5).

`python -m agent_tools.console.live_fault_check --repo OWNER/NAME [--store PATH]` finds the first
declared live fault of this host that a pull request answers, and reports the time from its
declaration to the pull request's green head. It reads the console's event log and the forge only.

Usage. `--repo` is `<owner>/<name>` of `[A-Za-z0-9_.-]`, else a usage error (exit 2) before any read.
`--store` is the event log, by default `service.default_store()`. It is opened read-only (SQLite
`mode=ro` with `query_only`), so the check never writes, creates or journals it. A store that is absent
or unreadable holds no declaration on this host yet: `{"verdict": "not_yet"}`, exit 75.

Declarations. The `fault.declared` rows in `seq` order. The marker of a declaration is the line
`Live-fault lane: declaration <seq> of sprint <payload.sprint_id> for issue #<payload.fault.issue>,
declared <row at>`. A pull request, of any state, is that declaration's when a line of its body,
stripped, equals the marker exactly, so a marker of another store (another sprint id), another issue or
another `at` is not counted.

First use. The first declaration in `seq` order that has a pull request, through its lowest-numbered
pull request. The selection never moves to a later declaration: a later or faster pull request never
replaces it. With none, `{"verdict": "not_yet"}`, exit 75.

Decision. `elapsed` is the green time minus the declaration's `at`, in unrounded seconds, and
`verify_checks.pr_green_state` reads the pull request's state. `green`: exit 0 when
`0 <= elapsed <= 3600`, else exit 1. Any other state: exit 1 when the time now is more than 3600
seconds after the declaration (it can no longer be within the hour), else exit 75.

Output. Once a first use is selected, one JSON line `{"declaration", "sprint_id", "issue", "pr",
"state", "declared_at", "green_at", "seconds"}`, where `declaration` is the row's `seq`, `declared_at`
its `at`, and `green_at` and `seconds` are null unless the state is green. Exit 2 is a usage error, or
a forge error from the pull request listing or the green read (one stderr line). The seams of `main`
are `_pulls`, `pr_green_state` and `_now`.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import service
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification.verify_checks import pr_green_state

NOT_YET = 75
HOUR = 3600
FAULT_DECLARED = "fault.declared"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def _pulls(repo: str) -> list[dict]:
    """Every pull request of the repo, of any state."""
    pages = forge_api.api_pages(f"repos/{repo}/pulls?state=all&per_page=100")
    pulls = [item for page in pages if isinstance(page, list) for item in page]
    if not all(isinstance(item, dict) and isinstance(item.get("number"), int) for item in pulls):
        raise ForgeError("payload_invalid", "the pull request listing holds an entry with no number")
    return pulls


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(text) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        raise ForgeError("payload_invalid", f"{text!r} is not a time") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def declarations(store: Path) -> list[tuple[int, str, str, int]]:
    """`(seq, at, sprint_id, issue)` of each `fault.declared` row in `seq` order; empty when unreadable."""
    try:
        connection = sqlite3.connect(f"{store.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return []
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT seq, at, payload FROM events WHERE kind = ? ORDER BY seq", (FAULT_DECLARED,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    found = []
    for seq, at, payload in rows:
        try:
            body = json.loads(payload)
            sprint, issue = body["sprint_id"], body["fault"]["issue"]
        except (TypeError, ValueError, KeyError):
            continue
        if isinstance(sprint, str) and isinstance(issue, int) and not isinstance(issue, bool):
            found.append((seq, at, sprint, issue))
    return found


def marker(seq: int, at: str, sprint: str, issue: int) -> str:
    return f"Live-fault lane: declaration {seq} of sprint {sprint} for issue #{issue}, declared {at}"


def _emit(code: int, out: dict) -> int:
    print(json.dumps(out, sort_keys=True))
    return code


def _first_use(store: Path, pulls: list[dict]):
    """`(declaration, lowest pull number)` of the first declaration a pull request names, or None."""
    lines = {pull["number"]: {line.strip() for line in str(pull.get("body") or "").splitlines()}
             for pull in pulls}
    for declaration in declarations(store):
        named = sorted(number for number, found in lines.items() if marker(*declaration) in found)
        if named:
            return declaration, named[0]
    return None


def main(argv=None) -> int:
    parser = _Parser(prog="live_fault_check", add_help=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--store")
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        if not REPO.fullmatch(args.repo):
            raise Usage("--repo is not owner/name")
    except Usage as error:
        print(f"live_fault_check: {error}", file=sys.stderr)
        return 2
    store = Path(args.store) if args.store else service.default_store()
    if not store.exists():
        return _emit(NOT_YET, {"verdict": "not_yet"})
    try:
        found = _first_use(store, _pulls(args.repo))
        if found is None:
            return _emit(NOT_YET, {"verdict": "not_yet"})
        (seq, at, sprint, issue), number = found
        declared = _time(at)
        state, report = pr_green_state(args.repo, number)
        green_at = report.get("green_at") if state == "green" else None
        seconds = (_time(green_at) - declared).total_seconds() if green_at is not None else None
    except ForgeError as error:
        print(f"live_fault_check: {error}", file=sys.stderr)
        return 2
    out = {"declaration": seq, "sprint_id": sprint, "issue": issue, "pr": number, "state": state,
           "declared_at": at, "green_at": green_at, "seconds": seconds}
    if state == "green":
        return _emit(0 if 0 <= seconds <= HOUR else 1, out)
    return _emit(1 if (_now() - declared).total_seconds() > HOUR else NOT_YET, out)


if __name__ == "__main__":
    sys.exit(main())
