"""`interrupted-reruns`: the post-deploy verify check of verify-pending's interrupted runs.

`python3 -m agent_tools.verification.interrupted_reruns_check [--log FILE]...` reads the runner log
and prints one JSON line. With no `--log` it reads `$HOME/.agents/state/verify-pending/runner.log.1`
then `runner.log`; each `--log` is read in the order given. A missing file is skipped. A path that
exists but cannot be read as UTF-8 text is exit 2 with a message on stderr and nothing on stdout.

A line `<stamp> pass start host=<host>` opens a pass; lines before the first one belong to a leading
pass. Within a pass the `interrupted` lines are grouped by repository, issue and check in file
order, and a group's `then` values must be `["rerun"]` or `["rerun", "held"]`: a check a signal
ended is started once more and then held, never started a third time and never held first.

Exit 75 with `{"verdict": "not_yet", "interrupted": 0}` when no log has an `interrupted` line.
Exit 0 with `{"verdict": "met", "interrupted": <lines>, "checks": <groups>}` when every group
holds. Exit 1 with the same members, verdict `not_met` and `violations` (the first line's `at`,
`repo`, `issue`, `check` and the group's `then`, in file order) otherwise. The check writes nothing.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from agent_tools.verification import verify_interrupt

LOGS = (".agents/state/verify-pending/runner.log.1", ".agents/state/verify-pending/runner.log")
MET = 0
NOT_MET = 1
NOT_YET = 75
UNREADABLE = 2
PASS_START = re.compile(r"^\S+ pass start host=\S+$")
VALID = (["rerun"], ["rerun", "held"])


def read_lines(paths):
    """The lines of every log in order; a missing file adds none, an unreadable one raises OSError."""
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except UnicodeDecodeError as error:
            raise OSError(f"{path}: {error}") from error
        yield from text.splitlines()


def passes(lines):
    """The `interrupted` entries of each pass, a pass opening at every `pass start` line."""
    current = []
    found = [current]
    for line in lines:
        if PASS_START.match(line):
            current = []
            found.append(current)
            continue
        parsed = verify_interrupt.parse_line(line)
        if parsed is not None:
            current.append(parsed)
    return found


def groups(entries):
    """One pass's entries grouped by repository, issue and check, in order of first appearance."""
    grouped = {}
    for entry in entries:
        grouped.setdefault((entry["repo"], entry["issue"], entry["check"]), []).append(entry)
    return grouped


def verdict(lines):
    """The `(exit code, report)` of the log lines."""
    interrupted = 0
    checks = 0
    violations = []
    for entries in passes(lines):
        interrupted += len(entries)
        for (repo, issue, check), members in groups(entries).items():
            checks += 1
            then = [member["then"] for member in members]
            if then not in VALID:
                violations.append({"at": members[0]["at"], "repo": repo, "issue": issue, "check": check, "then": then})
    if interrupted == 0:
        return NOT_YET, {"verdict": "not_yet", "interrupted": 0}
    report = {"interrupted": interrupted, "checks": checks}
    if violations:
        return NOT_MET, {**report, "verdict": "not_met", "violations": violations}
    return MET, {**report, "verdict": "met"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="interrupted-reruns", description=__doc__.splitlines()[0])
    parser.add_argument("--log", action="append", type=Path, help="a runner log to read, in order; repeatable")
    args = parser.parse_args(argv)
    paths = args.log if args.log else [Path.home() / name for name in LOGS]
    try:
        lines = list(read_lines(paths))
    except OSError as error:
        print(f"interrupted-reruns: cannot read a log: {error}", file=sys.stderr)
        return UNREADABLE
    code, report = verdict(lines)
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
