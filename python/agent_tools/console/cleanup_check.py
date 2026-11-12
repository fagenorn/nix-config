"""`cleanup_check`: the verify script that no test manager's session record is left (#970, AC).

`python -m agent_tools.console.cleanup_check --project ID [--checks-dir PATH]` runs the three
console host checks, one per run, on this project's own files, then reads every profile's full
session listing and reports whether a record named for a test sprint is still listed.

Result read. Each host check writes a result file whose `"cleared"` member is
`{"project": str, "names": [str], "profiles": [str]}`: the project it ran for, the session names of
the test managers it stopped and removed, and the profiles it stopped them in. A result is fresh
when its file parses as a JSON object whose `cleared` is an object with `project` equal to the
requested project, a nonempty list `names` of nonempty strings and a list `profiles`. An absent,
unreadable, old-shape or other-project result is not fresh, and neither is one that cleared no test
sprint (a check whose goal creation failed): with no name to look for, a listing proves nothing, so
the check runs again.

Files. The checks dir defaults to `manager_check._state_dir() / "checks" / "cleanup"`, apart from
the default files other verify holds of these checks use. Under it, `project_dir(checks_dir,
project)` is the quoted project id; the state file of check `<name>` is `<project dir>/<name>.json`
and its result file `<project dir>/<name>-result.json`, passed to the check as `--state-file` and
`--result-file`, so neither another project's run nor another hold's default files stand for this
one. `CHECKS` is the fixed order: `manager-start`, `owner-message`, `manager-revive`.

One check per run. The first check in `CHECKS` order whose result is not fresh is run through
`run_check(module, project, state_file, result_file)`; the run prints `{"check", "check_exit",
"status": "waiting"}` and exits 75, and the listing is not read. A run never starts a second host
check: verify-pending kills a run after 600 seconds and each host check uses up to 590 (its budget
of 540 and its finish guard). `default_run_check` launches the check as a child through
`siblings.sibling_argv` with stdin and stdout to the null device and stderr inherited; it has no
timeout of its own, the host check bounds itself.

Listing. When all three results are fresh, `names` is the sorted union of their `names` and the
profiles to read are the sorted union of `profiles()` (every configured profile) and every
result's `profiles`: a manager never listed at a finish leaves its profile out of `cleared`, and is
read all the same. For each profile in order, `lister(profile, os.getcwd())` reads the full listing
(not filtered by the working directory, so the runner's temporary worktree is a valid one). `left`
is the sorted distinct `name` of the entries, under any profile, whose `name` is in `names`.

Output and exits, one JSON line with sorted keys, and no file written. 0 met
`{"names", "profiles", "status": "met"}` (the profiles read); 1 not met `{"left", "status":
"not_met"}`; 75 not yet: `{"check", "check_exit", "status": "waiting"}`, `{"status":
"no_profiles"}` (met is never reported without reading a listing) or `{"profile", "reason",
"status": "no_listing"}` (`nudge.ListingUnreadable`); 2 a usage error. The seams of `main` are
`run_check`, `lister` and `profiles`.
"""

import argparse
import json
import os
import subprocess
import urllib.parse
from pathlib import Path

from agent_tools.console import manager_check, nudge, service, sessions
from agent_tools.system import siblings

CHECKS = (("manager-start", "console.manager_check"),
          ("owner-message", "console.message_check"),
          ("manager-revive", "console.revive_check"))
NOT_YET = manager_check.NOT_YET


def project_dir(checks_dir: Path, project: str) -> Path:
    return checks_dir / urllib.parse.quote(project, safe="")


def default_run_check(module: str, project: str, state_file: Path, result_file: Path) -> int:
    return subprocess.run(
        [*siblings.sibling_argv(module), "start", "--project", project,
         "--state-file", str(state_file), "--result-file", str(result_file)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=False).returncode


def configured_profiles() -> list[str]:
    return sorted({sessions.profile_name(d) for d in service.default_profile_dirs()})


def _fresh_cleared(result_file: Path, project: str) -> dict | None:
    try:
        document = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cleared = document.get("cleared") if isinstance(document, dict) else None
    if (isinstance(cleared, dict) and cleared.get("project") == project
            and isinstance(cleared.get("names"), list) and cleared["names"]
            and all(isinstance(n, str) and n for n in cleared["names"])
            and isinstance(cleared.get("profiles"), list)):
        return cleared
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cleanup_check", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project id the checks run for")
    parser.add_argument("--checks-dir", type=Path, default=None)
    return parser


def main(argv=None, *, run_check=default_run_check, lister=nudge.read_full_entries,
         profiles=configured_profiles) -> int:
    args = build_parser().parse_args(argv)
    checks_dir = args.checks_dir or manager_check._state_dir() / "checks" / "cleanup"
    pdir = project_dir(checks_dir, args.project)
    cleared = []
    for name, module in CHECKS:
        state_file, result_file = pdir / f"{name}.json", pdir / f"{name}-result.json"
        found = _fresh_cleared(result_file, args.project)
        if found is None:
            code = run_check(module, args.project, state_file, result_file)
            manager_check._print({"check": name, "check_exit": code, "status": "waiting"})
            return NOT_YET
        cleared.append(found)
    names = sorted({n for found in cleared for n in found["names"] if isinstance(n, str)})
    to_read = sorted({*profiles(), *(p for found in cleared for p in found["profiles"]
                                     if isinstance(p, str))})
    if not to_read:
        manager_check._print({"status": "no_profiles"})
        return NOT_YET
    left: set[str] = set()
    for profile in to_read:
        try:
            entries = lister(profile, os.getcwd())
        except nudge.ListingUnreadable as error:
            manager_check._print({"profile": profile, "reason": str(error),
                                  "status": "no_listing"})
            return NOT_YET
        left.update(entry["name"] for entry in entries
                    if isinstance(entry.get("name"), str) and entry["name"] in names)
    if left:
        manager_check._print({"left": sorted(left), "status": "not_met"})
        return 1
    manager_check._print({"names": names, "profiles": to_read, "status": "met"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
