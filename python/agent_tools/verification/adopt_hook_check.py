"""The verify check that an adoption installed a project's missing git hooks and its commit ran them.

`python -m agent_tools.verification.adopt_hook_check --since <sha> --marker <text>` reads the stored
adoption plans at `agent_platform.state_root()/adopt/plans/*.json` and reports whether one of them
records a hook install and a commit output that shows the project's hook running.

`--since` is a 40-character lowercase hex commit; T is its committer time (`git show -s --format=%ct`,
the one command the check runs, in the working directory it is started in). `--marker` is the name
the fresh project's dev-shell-only hook prints when it runs; pre-commit and prek print a run hook as
`<name>....Passed`. A plan is met when all of these hold:

- its file modification time is at or after T, so a plan stored before the commit never counts;
- the file is at most 1 MiB and holds a JSON object;
- `verification.hook_install.installed` is a non-empty list of strings;
- `verification.commit_output.lines` is a list of strings and one of them contains the marker.

The marker ties the recorded output to the hook. The adoption's commit runs as `devenv shell -- ...
git commit` with stderr merged, so a non-empty output can be the dev shell's own messages alone, and
git's trace2 names only the managed chain hook, never the project hook it passes through to. Output
without the marker never counts.

Output is one stdout line of JSON with sorted keys; the exits are 0 met, 75 not yet, 2 usage:

- met: `{"installed": [...], "lines": [...], "marker": <marker>, "plan_id": <id or null>,
  "status": "met"}` for the newest plan that qualifies;
- not yet: `{"status": "waiting"}` when none qualifies or there is no plan directory;
- error: `{"detail": <words>, "status": "error"}` for a `--since` that is not 40 lowercase hex, a
  commit git cannot read, or a `--marker` that is empty, over 200 characters or holds a newline.

An unreadable, oversized or malformed plan file is skipped, never an error. The check only reads: it
writes nothing. The rerun that serves the acceptance run registers the fresh project through the
activated console of the host, so its plan lands under that host's state root; the check is run on
that host.
"""
import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_tools.project_contract import agent_platform

MAX_PLAN_BYTES = 1024 * 1024
MAX_MARKER = 200
GIT_TIMEOUT_SECONDS = 30
SHA = re.compile(r"[0-9a-f]{40}")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _emit(document: dict) -> None:
    print(json.dumps(document, sort_keys=True))


def _fail(detail: str) -> int:
    _emit({"detail": detail, "status": "error"})
    return 2


def _commit_time(sha: str) -> int | None:
    try:
        done = subprocess.run(["git", "-C", ".", "show", "-s", "--format=%ct", sha],
                              capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
        return int(done.stdout.strip()) if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _qualifies(path: Path, since: int, marker: str):
    """The (mtime, document) of a plan file that meets the rule, else None."""
    try:
        status = path.stat()
        if status.st_mtime < since or status.st_size > MAX_PLAN_BYTES:
            return None
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    verification = document.get("verification") if isinstance(document, dict) else None
    if not isinstance(verification, dict):
        return None
    install = verification.get("hook_install")
    output = verification.get("commit_output")
    installed = install.get("installed") if isinstance(install, dict) else None
    lines = output.get("lines") if isinstance(output, dict) else None
    if not (_strings(installed) and installed and _strings(lines)):
        return None
    if not any(marker in line for line in lines):
        return None
    return status.st_mtime, document


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(prog="adopt_hook_check", description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True)
    parser.add_argument("--marker", required=True)
    try:
        args = parser.parse_args(argv)
    except ValueError as error:
        return _fail(str(error))
    if not SHA.fullmatch(args.since):
        return _fail("--since must be a 40-character lowercase hex commit")
    marker = args.marker
    if not marker or len(marker) > MAX_MARKER or "\n" in marker or "\r" in marker:
        return _fail("--marker must be 1 to 200 characters on one line")
    since = _commit_time(args.since)
    if since is None:
        return _fail("git cannot read the --since commit")
    found = []
    directory = agent_platform.state_root() / "adopt" / "plans"
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        hit = _qualifies(path, since, marker)
        if hit is not None:
            found.append(hit)
    if not found:
        _emit({"status": "waiting"})
        return 75
    _, document = max(found, key=lambda hit: hit[0])
    plan = document.get("plan")
    plan_id = plan.get("plan_id") if isinstance(plan, dict) else None
    _emit({
        "installed": document["verification"]["hook_install"]["installed"],
        "lines": document["verification"]["commit_output"]["lines"],
        "marker": marker,
        "plan_id": plan_id,
        "status": "met",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
