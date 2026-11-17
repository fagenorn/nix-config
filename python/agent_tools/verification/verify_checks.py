"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`: an `sh` script committed with mode `100755`. A wrapper runs
from the repository root at the block's commit, so `PYTHONPATH=python` is that commit's source, and
its logic lives in `agent_tools`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`required-checks --repo R --base B --since T` is met when the first pull request merged into B
after T had every required check pass before its merge, each from the app its protection binds
it to. It only reads the forge, across every page of each listing, and refuses an incomplete or
truncated listing rather than judging it. It is `verify_checks.required_checks`: it finds the first
pull request merged into B after T through the search API, read across every page, and refuses an
incomplete or truncated listing of the search or of the head's check runs. It is met when every
check that B's protection requires has a successful check run from the app it binds (any app when
it binds none), or, for a check bound to no app, a latest status of success, completed no later
than the merge (a commit status names no app, so it never satisfies a bound check, and the legacy
`contexts` list never loosens one); not met otherwise (and when nothing is required); not yet when
no pull request has merged; and it exits 2 on a forge error.

`keepalive-end-turn-cap` is documented in `agent_tools.hosts.keepalive_pings`.

`platform-status` runs the installed `resolve-project platform-status` (from `~/.agents/bin`,
prepended to `PATH`) and passes its output and exit through, so a block judges it with `expect`.

`managed-pre-push-hook --slug S` (`verify_checks.managed_pre_push_hook`, issue 672) is met when the
global `core.hooksPath` is the
managed `-agent-git-hooks` directory and, in a local fixture of S whose own git configuration
holds only that hooks path, an agent push of `main` is refused by its `pre-push` with the
remote unchanged while a feature-branch push is admitted; the fixture's transport is a fake `ssh`
limited to `ssh:file`, so no URL rewrite reaches the network. It exits 0 when met, 1 when not and 2
on a usage or fixture error, writes only to a temporary directory, and S's owner must be an
authorized owner in the installed guard policy.

`cutover-manifest [--repo-root R] [--branch B] [--main-ref REV]` (`verify_checks.cutover_manifest`,
issue 579, C4.a) is met (0, `green`)
when the manifest at the tip of origin's candidate branch is a major-2 manifest whose `removals`
are non-empty and each equal, in all six members, to a `deprecations` entry of a major-1 manifest
on main. It is 75 when anything of that is not yet so (`absent` when the branch does not exist) and
2 when a manifest cannot be read. It only reads: it fetches objects, and writes no ref. The candidate
sha is read with `git ls-remote origin refs/heads/B` (B defaults to `cutover-130-candidate`; no ref
is 75 with verdict `absent`) and fetched as objects only. `--main-ref REV` reads REV and fetches
nothing for it; otherwise `git fetch --no-tags --refmap= origin refs/heads/main` is read as
`FETCH_HEAD`. `manifest_verdict` is 0 (`green`) only when main is major 1, the candidate is major 2,
the candidate's `removals` are non-empty and every removal equals, in all six members, a
`deprecations` entry of main; any other readable pair is 75 (`red`, with the unmatched ids in
`undeclared`), and a manifest that is not an object or lacks a member is 2 (`unreadable`).

`cutover-preflight [--repo-root R] [--branch B]` (`verify_checks.cutover_preflight`, issue 579, C4.b)
is met when `cutover-manifest` is green and both the installed bridge and the candidate's own code
judge every registered project compatible, with no removed use. It is 75 otherwise, and 0 only when
green. It computes the manifest report from the same fetch, unpacks `python/` and the manifest at
the candidate sha into a temporary directory that is always removed, and runs two
`platform-status --fleet` reports, each with a 120-second timeout: the installed `resolve-project`
found on `PATH` (with `PYTHONPATH` removed) and the candidate's `python3 -m agent_tools.project_contract.resolve_project`
(`agent_tools.resolve_project` for a candidate cut before the domain layout) `... --manifest <tmp>/...` with `PYTHONPATH=<tmp>/python` and `cwd=<tmp>`. A side that exits non-zero,
times out or prints something other than a JSON object is 75 with verdict `unreadable` and `side`
naming it. `preflight_verdict` is 0 (`green`) only when C4.a is green, the bridge is major 1 and at
least `1.2.0`, the candidate is major 2, both fleets are non-empty and name the same `(project_id,
root)` set, every row is compatible on both sides, and every candidate row's `removed_uses` is `[]`;
otherwise 75 (`not_yet`), and each row's `reason` is the first rule it fails (`bridge_missing`,
`candidate_missing`, `bridge_incompatible`, `candidate_incompatible`, `removed_use`). The wrapper
`cutover-preflight` runs it with `~/.agents/bin` prepended to `PATH`.

`cutover-bundle [--repo-root R] [--branch B]` (issue 579, C3) is met (0, `green`) when a `*-bundle.json`
under `.agents/artifacts/evidence/` at origin's main verifies, through `agent_gate_bundle.verify_bundle`,
as `approved` and binds the commit at the tip of origin's candidate branch. The state is the verifier's
return value, never the document's own `state` field; a bundle the verifier refuses is `unreadable` and
never counts. It is 75 otherwise (`absent` when the branch does not exist) and 2 when git cannot be
driven. It only reads: it fetches objects, and writes no ref. A gate-version-2 (claude-only) bundle is
verified as the cutover kind, under the no-regression criterion.

`self-hosted-runner --repo R --runner N --label L [--label L ...]` (`verify_checks.self_hosted_runner`,
issue 680) is met when R lists a runner
named N whose status is online and whose labels include `self-hosted` and every L; not met when
it is online but lacks one (a wrong registration), and not yet when it is unlisted or not online.
It only reads one paginated runner listing and refuses a truncated or malformed one.

`guard-policy-fleet [--repo-root R] [--branch B] [--registry FILE]` (`verify_checks.guard_policy_fleet`,
issue 765, C13.a) is met (0, `green`)
when, with the candidate's own `python/` and platform manifest unpacked from origin's candidate branch into a
temporary `HOME`, `python -m agent_tools.guard.guard_policy derive --repository S`
(`agent_tools.guard_policy` for a candidate cut before the domain layout) exits 0 with a derived row for
every slug S named by a registry entry's `origin` (the host's own registry unless `--registry` names another
file). Any other exit, outcome or unreadable answer makes that row, and the check, 1 (`red`); a candidate
branch that does not exist is 75 (`absent`) and an unreadable registry or unpackable candidate is 75
(`unreadable`). The installed bridge is never asked: it still accepts what the candidate refuses. Like the
lifecycle guard, `derive` writes the objects and remote-tracking refs it fetches into the registered checkouts.
The candidate's `python/` and manifest are unpacked as `cutover-preflight` does, after fetching the
sha as objects, into a temporary `HOME` holding that manifest and a copy of the registry. A row is
green only on exit 0, outcome `derived` and a row object; an entry whose `origin` names no slug is a
red `origin_unproven` row. The child keeps the host's `GH_CONFIG_DIR` and `GIT_CONFIG_GLOBAL`
(defaulting to the real `HOME`'s) so the temporary `HOME` does not strand the forge login.

`registry-agreement --registry HOST=FILE... [--intentional PROJECT_ID]...`
(`verify_checks.registry_agreement`, issue 765, C13.b) is met (0,
`green`) when every project registered on more than one of the named hosts carries the same `branch_override`
(absent counts as a value) in each of those registries; a project whose registries differ is `red` (1)
unless its id is named by `--intentional`, which records the difference as `intentional`. It reads only the
files, and exits 2 on a file it cannot read.

`deprecations-retired [--red-pending] [--watch-adapter A] --repo-root R...`
(`verify_checks.deprecations_retired_check`, issue 582) states the
#130 checklist C11 rule over each root, read-only: no deprecated use reported by
`resolve-project platform-status` (a), no tracked legacy skills config (b), `bindings.deploy.adapter`
resolved to `none` or absent from a schema 2 snapshot (c), and no skill text naming the retired command (d); with `--watch-adapter A`
it also reads whether the release target A is adopted and available. Concretely: `resolve-project
platform-status` reports no `project.deprecated_uses` (a), `.claude/skills.config.json` is not
tracked (b), `resolve-project resolve` exits 0 with `bindings.deploy.adapter` `none` (c), and `git
grep` finds no `release deploy inspect` (d) outside `.agents/artifacts`, narrowed to
`home/common/agent-skills/skills` for `fagenorn/nix-config` (the checklist's documented pathspec,
keyed on the resolved `project.id`). With `--watch-adapter A` a fifth reading is pending until a
`release.targets[]` entry names A and red unless that release capability is `available`. It exits 0 when every root is
green, 1 when one is red, 75 when none is red and one is pending, and 2 on a tool error. Under
`--red-pending` any root that is not green exits 75.

`darwin-shell-path [--zsh PATH]` (`verify_checks.darwin_shell_path`, issue 810) reads two fresh login
interactive zsh shells (`PATH` defaults to `/bin/zsh`) of the current user, each run as
`zsh -l -i -c` with `HOME`, `USER`, `LOGNAME`, `SHELL` and `TERM=dumb` and nothing else inherited: a `clean`
probe whose `PATH` is launchd's `/usr/bin:/bin:/usr/sbin:/sbin`, and an `inherited` probe that also sets
`__NIX_DARWIN_SET_ENVIRONMENT_DONE=1` with a path_helper-ordered `PATH` that lists the Nix profile directories last,
the state a child of an already polluted terminal starts in. A probe is met when `/etc/profiles/per-user/<user>/bin` is
a `PATH` entry ahead of `/usr/bin` and `python3` reports version 3.13 or later; the check is met only
when both probes are. It exits 0 when met, 1 when not and 2 when a probe is unreadable (no sentinel lines in
its output, a timeout or a shell that cannot be run). It never writes a file.

`railway-project-read [--system-path PATH]` (`verify_checks.railway_project_read`, issue 1124) is met when
no host-wide `railway` exists and every Railway deploy watch the registered projects declare reads its
deploys from the project's own dev shell. It first searches `PATH` (the host's system and profile bin
directories, `RAILWAY_SYSTEM_DIRS`, unless `--system-path` names another) for `railway`: one found is not met (1)
and nothing else runs. Otherwise, for each project of the host's registry it reads the contract at the
integration branch commit that the registered `origin` lists, through `verify_exec.project_source`, in a
scratch export (never the checkout, so a local branch cannot hide a watch), and takes each `railway-deploy`
release target's activation units through the packaged `release profile inspect`. A unit is read, with the
packaged `release adapter inspect railway-deploy deploy` run as `devenv shell -- env PYTHONPATH=... <sibling>` in
the project's root, so the adapter finds the `railway` the dev shell provides; both packaged siblings run through
`siblings.sibling_argv` with an absolute `PYTHONPATH`, and nothing runs from `~/.agents/bin`. A project with no
`devenv.nix` has the reason `no_dev_shell` and is not read. A unit counts as read when its observation lists
services and none of them carries an unread reason (`RAILWAY_UNREAD_REASONS`, such as `executable_missing` or
`railway_unauthorized`). It exits 0 when there is at least one unit and every unit is read, 1 when a unit is not
read or a system `railway` exists, 75 when no registered project has a Railway unit, and 2 when a step cannot be
read, with only `{"met": false, "error": CODE}` (`registry_unreadable`, `contract_unreadable`,
`inspection_unreadable`, `devenv_missing`, `read_failed` or `read_timeout`). The whole collection is bounded by
`RAILWAY_READ_BUDGET` seconds, short enough that a source read still running at the deadline ends before
`verify_exec.TIMEOUT` kills the check, and a child that outlasts it is killed with its process group and reports
`read_timeout`. The report carries counts and reason codes only: it never names a project, root, repository,
profile, handle or Railway project, environment or service, since the repository is public.

`console-state --port N` (`verify_checks.console_state`, issue 856) is met when
`GET http://127.0.0.1:N/api/state` answers 200 within 5 seconds, not met on any other status or no
answer; it reads only that endpoint.

`console-first-screen --port N [--browser PATH]` (`verify_checks.console_first_screen`, issue 1031) reads
`GET http://127.0.0.1:N/api/state` (no answer, a status other than 200 or a body that is not a JSON object is
`unreachable`, exit 1), applies `first_screen_state` to it (any code other than 0 is returned as it is and no
browser starts), then loads `http://127.0.0.1:N/` in headless Chromium at 1440x900 (the browser is `PATH`, else
`chromium` on the PATH, else `nix shell n#chromium --command chromium`; none that runs is `no_browser`, exit 1),
polls until the lead card exists, saves a PNG screenshot and measures it. It is met when the lead card is the
long-goal sprint's open question (its ask equals the item's headline) and its whole ask and every option of its
first question sit inside the 900 pixel fold, the ask not clipped, and no part of a long goal (characters 200 to
300) is in the rendered text; exit 0. Not met (1) names the `fold_ask`, `fold_options` or `visible_goal` members.
A page led by another item, or none, is not yet (75). The check sends no input to the page, keeps the screenshot
(`first-screen-1440.png`, its path in every report from the browser) and removes the browser's profile.

`issue-closed --repo R --issue N` (`verify_checks.issue_closed`, issue 1010) is met when issue N of R
was closed as completed after the verify run verified its held block: a closed state with reason
`completed` alone is not enough, since an owner can close an issue that way by hand. It reads
`repos/R/issues/N` and, for a completed closure, every page of `repos/R/issues/N/comments`, and only
reads the forge. The held block is the newest trusted one (`verify_issues.select`) and the closure is
verified when a live `verify-closed` marker by a trusted author names that block's version with
outcome `verified`; a block that is absent or unparsable, a marker of an older block version, an
untrusted marker or any other outcome is not. Exit 0 when `closed` as `completed` and verified; 1
when `closed` with any other reason (its comments unread), or as `completed` unverified; 75 when
`open`. The report is `{"issue", "state", "state_reason"}`, plus `"verified"` once the comments were
read. A payload that is not an object, or whose state is neither `open` nor `closed`, or a malformed
comment page, is a `payload_invalid` forge error (exit 2), as is any other forge error; a bad `--repo`
or `--issue` (a positive integer) is a usage error (2).

`suite-regressions --repo R --workflow W --job J --branch B --merge SHA --n N`
(`verify_checks.suite_regressions`, issue 1215) is met when no member of the agent workflow suite failed in
any of the first N completed push runs of workflow W on branch B from the merge's run on that passed, in
a run of the N before it, and failed in none. It only reads the forge. The merge's run is the earliest
push run listed at `--merge` (none: 75). The after runs are the runs created from its time on, oldest
first: a run with a job J still unfinished in any attempt stops the scan, a run whose attempts all ended
other than `success` or `failure` (cancelled, skipped) is passed over, and every other run counts, until N
count (fewer: 75). The before runs are the runs listed before that time, newest first, counted the same
way, and a candidate with any counted attempt whose log has no complete summary is listed in
`before_skipped` and never counted; fewer than N before runs with complete logs is a `payload_invalid`
forge error, so the baseline is always N runs of complete logs. Every attempt of a counted run is read, a
run counts once toward N however many attempts it has, and a failure followed by a passing rerun still
counts as the failure. A log is read as the timestamped text of job J: a leading BOM and each line's
timestamp are dropped, every line from `suite-runner: begin M` to `suite-runner: end M ` is skipped, and
outside those blocks the `suite-runner: <wall>s wall <cpu>s cpu passed|failed M` rows give each member's
state and the `suite-runner: summary members=.. passed=.. failed=..` line closes them. The summary is
complete only when it agrees with the rows (one row per member, `members=` rows, `passed=` and `failed=`
matching the rows). A regression is a member failed in some attempt of a counted after run and passed in at
least one attempt of a before run and failed in none. An after attempt that failed with no complete summary
cannot be attributed and is listed in `unattributed`, never passed. Exit 0 when neither `regressions` nor
`unattributed` is set, 1 when one is, 75 as above, 2 on a forge error. The report is `{"merge_run",
"before", "before_skipped", "after", "regressions": {member: [after run ids]}, "unattributed"}`, one JSON
line; a malformed payload is a `payload_invalid` forge error. A bad `--repo`, an empty `--workflow`,
`--job` or `--branch`, a `--merge` that is not 40 lowercase hex characters, or an `--n` that is not a
positive integer is a usage error (2).
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import http.client
import io
import json
import os
import pwd
import re
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from agent_tools.delivery.agent_gate_bundle import BundleIntegrityError, verify_bundle
from agent_tools.project_contract.agent_platform import DEPRECATION_MEMBERS, validate_manifest, validate_registry
from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.guard.push_fixture import make_push_fixture
from agent_tools.system import forge_api, github_remote, siblings
from agent_tools.system.semver import parse_semver
from agent_tools.verification import verify_exec, verify_issues

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _invalid(detail: str) -> forge_api.ForgeError:
    return forge_api.ForgeError("payload_invalid", detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _forge_time(value: object, what: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)  # type: ignore[arg-type]
    except ValueError:
        raise _invalid(f"{what} is not an RFC 3339 instant") from None


def _counted_pages(pages: Sequence[object], key: str, what: str) -> list[object]:
    """The items of `key` over every page, refused when fewer than the first page's total_count."""
    found: list[object] = []
    total = None
    for page in pages:
        if (not isinstance(page, dict) or not isinstance(page.get(key), list)
                or not _is_int(page.get("total_count"))):
            raise _invalid(f"{what} page has no {key} list and total_count")
        if total is None:
            total = page["total_count"]
        found.extend(page[key])
    if total is not None and len(found) < total:
        raise _invalid(f"{what} is truncated: {len(found)} of {total}")
    return found


def _merged_pull_numbers(repo: str, base: str, since: datetime) -> list[int]:
    since_z = since.astimezone(timezone.utc).strftime(_STAMP)
    query = quote(f"repo:{repo} is:pr is:merged base:{base} merged:>{since_z}", safe="")
    pages = forge_api.api_pages(
        f"search/issues?q={query}&sort=created&order=asc&per_page=100")
    for page in pages:
        if isinstance(page, dict) and page.get("incomplete_results") is not False:
            raise _invalid("search listing reports incomplete results")
    numbers = []
    for item in _counted_pages(pages, "items", "search listing"):
        if not isinstance(item, dict) or not _is_int(item.get("number")):
            raise _invalid("search item has no number")
        numbers.append(item["number"])
    return numbers


Requirement = tuple[str, int | None]  # (context, app_id); None accepts any app


def _required_checks(repo: str, base: str) -> list[Requirement]:
    """The protection's required checks: `checks` entries keep their app binding (an absent,
    null or -1 `app_id` is any app), and a `contexts` name already in `checks` adds nothing,
    since that legacy list carries no app and must not loosen a bound check."""
    payload = forge_api.api_get(
        f"repos/{repo}/branches/{base}/protection/required_status_checks")
    if not isinstance(payload, dict):
        raise _invalid("required_status_checks is not an object")
    found: set[Requirement] = set()
    for entry in payload.get("checks") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("context"), str):
            continue
        app_id = entry.get("app_id")
        if app_id is not None and not _is_int(app_id):
            raise _invalid("required check app_id is not an integer or null")
        found.add((entry["context"], None if app_id == -1 else app_id))
    named = {context for context, _ in found}
    for context in payload.get("contexts") or []:
        if isinstance(context, str) and context not in named:
            found.add((context, None))
    return sorted(found, key=lambda item: (item[0], item[1] is not None, item[1] or 0))


def _context_met(requirement: Requirement, runs: Sequence[object], statuses: Sequence[object],
                 merged_at: datetime) -> bool:
    context, app_id = requirement
    for run in runs:
        if not isinstance(run, dict) or run.get("name") != context:
            continue
        app = run.get("app")
        if app_id is not None and not (isinstance(app, dict) and app.get("id") == app_id):
            continue
        if (run.get("status") == "completed" and run.get("conclusion") == "success"
                and _forge_time(run.get("completed_at"), "check run completed_at") <= merged_at):
            return True
    if app_id is not None:
        return False  # a commit status names no app, so it cannot satisfy a bound check
    latest = None
    for status in statuses:
        if not isinstance(status, dict) or status.get("context") != context:
            continue
        updated = _forge_time(status.get("updated_at"), "status updated_at")
        if updated <= merged_at and (latest is None or updated > latest[0]):
            latest = (updated, status.get("state"))
    return latest is not None and latest[1] == "success"


def required_checks(repo: str, base: str, since: datetime) -> tuple[int, dict]:
    """Met when the first pull request merged into `base` after `since` passed every required check."""
    report: dict = {"pr": None, "merged_at": None, "required": [], "missing": []}
    first = None
    for number in _merged_pull_numbers(repo, base, since):
        pull = forge_api.api_get(f"repos/{repo}/pulls/{number}")
        if not isinstance(pull, dict):
            raise _invalid(f"pull request {number} is not an object")
        if pull.get("merged_at") is None:
            continue
        merged_at = _forge_time(pull["merged_at"], "merged_at")
        if merged_at > since and (first is None or merged_at < first[0]):
            first = (merged_at, number, pull)
    if first is None:
        return 75, report
    merged_at, number, pull = first
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not sha:
        raise _invalid("pull request has no head sha")
    report.update(pr=number, merged_at=pull["merged_at"])
    required = _required_checks(repo, base)
    report["required"] = sorted({context for context, _ in required})
    if not required:
        return 1, report
    runs = _counted_pages(forge_api.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    status_pages = forge_api.api_pages(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    if not all(isinstance(page, list) for page in status_pages):
        raise _invalid("status page is not a list")
    statuses = [entry for page in status_pages for entry in page]
    report["missing"] = sorted({r[0] for r in required
                                if not _context_met(r, runs, statuses, merged_at)})
    return (0 if not report["missing"] else 1), report


def issue_closed(repo: str, issue: int) -> tuple[int, dict]:
    """Met when `issue` is closed as completed after its held block was verified by the verify run."""
    found = forge_api.api_get(f"repos/{repo}/issues/{issue}")
    state = found.get("state") if isinstance(found, dict) else None
    if state not in ("open", "closed"):
        raise _invalid(f"issue {issue} has no open or closed state")
    reason = found.get("state_reason")
    report = {"issue": issue, "state": state, "state_reason": reason}
    if state == "open":
        return 75, report
    if reason != "completed":
        return 1, report
    comments = verify_issues.comments_from_rest(forge_api.api_pages(
        f"repos/{repo}/issues/{issue}/comments?per_page=100"))
    held = verify_issues.select(comments)
    closing = (verify_issues.live_one(held.markers, verify_issues.CLOSED, {"block": held.key})
               if held is not None else None)
    report["verified"] = closing is not None and closing.fields.get("outcome") == "verified"
    return (0 if report["verified"] else 1), report


SUITE_ROW = re.compile(r"^suite-runner:\s+[0-9.]+s wall\s+[0-9.]+s cpu (passed|failed) (\S+)$")
SUITE_SUMMARY = re.compile(
    r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) jobs=\d+ wall=[0-9.]+s cpu=[0-9.]+s$")
SUITE_BEGIN = re.compile(r"^suite-runner: begin (.+)$")
LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ")


def suite_results(log: str) -> dict[str, bool] | None:
    """Member to passed from a job log, or None when the log has no complete, consistent summary."""
    rows: dict[str, bool] = {}
    duplicate = False
    summary = None
    ending = None
    for line in log.removeprefix("\ufeff").splitlines():
        line = LOG_STAMP.sub("", line, count=1)
        if ending is not None:
            if line.startswith(ending):
                ending = None
            continue
        begun = SUITE_BEGIN.match(line)
        if begun:
            ending = f"suite-runner: end {begun[1]} "
            continue
        row = SUITE_ROW.match(line)
        if row:
            duplicate = duplicate or row[2] in rows
            rows[row[2]] = row[1] == "passed"
            continue
        found = SUITE_SUMMARY.match(line)
        if found:
            summary = tuple(int(part) for part in found.groups())
    if summary is None or duplicate:
        return None
    passed = sum(1 for state in rows.values() if state)
    if summary != (len(rows), passed, len(rows) - passed):
        return None
    return rows


def _suite_run(entry: object) -> tuple[datetime, int, int, str]:
    if not isinstance(entry, dict) or not _is_int(entry.get("id")):
        raise _invalid("workflow run has no id")
    attempts = entry.get("run_attempt")
    if not _is_int(attempts) or attempts < 1:
        raise _invalid("workflow run has no run_attempt of at least 1")
    created = _forge_time(entry.get("created_at"), "run created_at")
    return created, entry["id"], attempts, entry["created_at"]


def _suite_runs(listing: object) -> list[tuple[datetime, int, int, str]]:
    if not isinstance(listing, dict) or not isinstance(listing.get("workflow_runs"), list):
        raise _invalid("run listing has no workflow_runs list")
    return sorted(_suite_run(entry) for entry in listing["workflow_runs"])


def _suite_attempts(repo: str, job: str, run: tuple[datetime, int, int, str]
                    ) -> tuple[bool, list[tuple[int, str]]]:
    """(pending, counted attempts as (job id, conclusion)) of one run's job across every attempt."""
    counted: list[tuple[int, str]] = []
    for attempt in range(1, run[2] + 1):
        listing = forge_api.api_get(
            f"repos/{repo}/actions/runs/{run[1]}/attempts/{attempt}/jobs?per_page=100")
        if not isinstance(listing, dict) or not isinstance(listing.get("jobs"), list):
            raise _invalid("attempt job listing has no jobs list")
        for entry in listing["jobs"]:
            if not isinstance(entry, dict):
                raise _invalid("attempt job is not an object")
            if entry.get("name") != job:
                continue
            if not _is_int(entry.get("id")) or not isinstance(entry.get("status"), str):
                raise _invalid("job has no id and status")
            if entry["status"] != "completed":
                return True, []
            if entry.get("conclusion") in ("success", "failure"):
                counted.append((entry["id"], entry["conclusion"]))
    return False, counted


def _suite_log(repo: str, job_id: int) -> str:
    status, text = forge_api.run_gh(["api", f"repos/{repo}/actions/jobs/{job_id}/logs"])
    if status != 0:
        raise forge_api.ForgeError("gh_failed", f"job {job_id} log")
    return text


def suite_regressions(repo: str, workflow: str, job: str, branch: str, merge: str,
                      n: int) -> tuple[int, dict]:
    """Met when no member passing in the N push runs before `merge` failed in the N runs from it on."""
    listing = f"repos/{repo}/actions/workflows/{workflow}/runs?branch={branch}&event=push"
    report: dict = {"merge_run": None, "before": [], "before_skipped": [], "after": [],
                    "regressions": {}, "unattributed": []}
    at_merge = _suite_runs(forge_api.api_get(f"{listing}&head_sha={merge}&per_page=100"))
    if not at_merge:
        return 75, report
    report["merge_run"] = at_merge[0][1]
    start = at_merge[0][3]
    after: list[tuple[int, list[tuple[int, str]]]] = []
    pages = _counted_pages(forge_api.api_pages(f"{listing}&created>={start}&per_page=100"),
                           "workflow_runs", "run listing")
    for run in sorted(_suite_run(entry) for entry in pages):
        pending, counted = _suite_attempts(repo, job, run)
        if pending:
            break
        if counted:
            after.append((run[1], counted))
            if len(after) == n:
                break
    report["after"] = [run_id for run_id, _ in after]
    if len(after) < n:
        return 75, report
    passed_before: set[str] = set()
    failed_before: set[str] = set()
    counted_before = 0
    candidates = _suite_runs(forge_api.api_get(f"{listing}&created=<{start}&per_page=100"))
    for run in reversed(candidates):
        if counted_before == n:
            break
        pending, counted = _suite_attempts(repo, job, run)
        if pending or not counted:
            continue
        results = [suite_results(_suite_log(repo, job_id)) for job_id, _ in counted]
        if any(result is None for result in results):
            report["before_skipped"].append(run[1])
            continue
        counted_before += 1
        report["before"].append(run[1])
        for result in results:
            for member, state in result.items():  # type: ignore[union-attr]
                (passed_before if state else failed_before).add(member)
    if counted_before < n:
        raise _invalid(f"only {counted_before} before runs with complete logs, need {n}")
    for run_id, counted in after:
        for job_id, conclusion in counted:
            if conclusion != "failure":
                continue
            result = suite_results(_suite_log(repo, job_id))
            if result is None:
                if run_id not in report["unattributed"]:
                    report["unattributed"].append(run_id)
                continue
            for member, state in result.items():
                if not state and member in passed_before and member not in failed_before:
                    seen = report["regressions"].setdefault(member, [])
                    if run_id not in seen:
                        seen.append(run_id)
    return (1 if report["regressions"] or report["unattributed"] else 0), report


def self_hosted_runner(repo: str, runner: str, labels: Sequence[str]) -> tuple[int, dict]:
    """Met when `runner` is listed on `repo`, online, and carries `self-hosted` and every label."""
    required = {"self-hosted", *labels}
    entries = _counted_pages(forge_api.api_pages(
        f"repos/{repo}/actions/runners?per_page=100"), "runners", "runner listing")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise _invalid("runner entry has no name")
    report: dict = {"repo": repo, "runner": runner, "required": sorted(required), "found": False,
                    "status": None, "labels": [], "missing": []}
    found = next((entry for entry in entries if entry["name"] == runner), None)  # type: ignore[index]
    if found is None:
        report["missing"] = sorted(required)
        return 75, report
    status, listed = found.get("status"), found.get("labels")
    if not isinstance(status, str):
        raise _invalid("runner has no status")
    if (not isinstance(listed, list)
            or not all(isinstance(label, dict) and isinstance(label.get("name"), str)
                       for label in listed)):
        raise _invalid("runner labels are not a list of named objects")
    names = {label["name"] for label in listed}
    report.update(found=True, status=status, labels=sorted(names), missing=sorted(required - names))
    if status != "online":
        return 75, report
    return (0 if not report["missing"] else 1), report


MANAGED_HOOKS_SUFFIX = "-agent-git-hooks"
PRE_PUSH_REFUSAL = "lifecycle guard pre-push: unsafe push: refusing to push the default branch main"
CONTROL_BRANCH = "verify-pre-push-control"


class FixtureError(Exception):
    """The check could not build or drive its fixture; the caller exits 2."""


def _global_hooks_path(git_bin: str, environ: Mapping[str, str]) -> str | None:
    done = subprocess.run(
        [git_bin, "config", "--global", "--get", "core.hooksPath"], env=dict(environ),
        capture_output=True, text=True, timeout=60, check=False)
    value = done.stdout.strip() if done.returncode == 0 else ""
    return value or None


def _is_managed(hooks_path: str | None) -> bool:
    if hooks_path is None:
        return False
    hooks = Path(hooks_path)
    pre_push = hooks / "pre-push"
    return (hooks.is_dir() and hooks.name.endswith(MANAGED_HOOKS_SUFFIX)
            and pre_push.is_file() and os.access(pre_push, os.X_OK))


def managed_pre_push_hook(slug: str, *, git_bin: str,
                          environ: Mapping[str, str]) -> tuple[int, dict]:
    """Met when the global hooks path is the managed one and its pre-push judges a fixture push.

    Raises FixtureError when the fixture cannot be built or driven."""
    hooks_path = _global_hooks_path(git_bin, environ)
    report: dict = {"hooks_path": hooks_path, "managed": _is_managed(hooks_path),
                    "refused": False, "remote_unchanged": False, "control_admitted": False,
                    "met": False}
    if not report["managed"]:
        return 1, report
    agent = {"CLAUDECODE": "1"}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = make_push_fixture(Path(tmp), slug, git_bin=git_bin, env=environ,
                                        hooks_path=Path(hooks_path))
            before = fixture.remote_ref(slug, "refs/heads/main")
            fixture.commit("verify: a default-branch push")
            judged = fixture.git("push", "origin", "main", extra_env=agent)
            report["refused"] = judged.returncode != 0 and PRE_PUSH_REFUSAL in judged.stderr
            report["remote_unchanged"] = (before is not None
                                          and fixture.remote_ref(slug, "refs/heads/main") == before)
            fixture._checked("checkout", "-q", "-b", CONTROL_BRANCH)
            fixture.commit("verify: a feature-branch push")
            control = fixture.git("push", "origin", CONTROL_BRANCH, extra_env=agent)
            report["control_admitted"] = (
                control.returncode == 0
                and fixture.remote_ref(slug, f"refs/heads/{CONTROL_BRANCH}") is not None)
    except (subprocess.SubprocessError, OSError, RuntimeError) as error:
        raise FixtureError(str(error).strip().splitlines()[0] if str(error).strip()
                           else type(error).__name__) from error
    report["met"] = all(report[key] for key in
                        ("managed", "refused", "remote_unchanged", "control_admitted"))
    return (0 if report["met"] else 1), report


MANIFEST_PATH = "home/common/agent-skills/platform-manifest.json"
CANDIDATE_BRANCH = "cutover-130-candidate"
SIDE_TIMEOUT = 120
_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def _manifest_facts(manifest: object) -> tuple[str, list[dict], list[dict]] | None:
    """The version, deprecations and removals of a readable manifest, else None.

    Readable means the platform's own manifest validator accepts it, so a
    manifest missing a required member is unreadable however its records compare."""
    if not isinstance(manifest, dict) or validate_manifest(manifest):
        return None
    version = manifest.get("platform_version")
    if parse_semver(version) is None:
        return None
    lists = []
    for name in ("deprecations", "removals"):
        entries = manifest.get(name)
        if not isinstance(entries, list) or not all(
                isinstance(item, dict) and isinstance(item.get("id"), str) for item in entries):
            return None
        lists.append(entries)
    return version, lists[0], lists[1]


def manifest_verdict(main: object, candidate: object) -> tuple[int, dict]:
    """C4.a: every removal of the major-2 candidate was a deprecation on major-1 main."""
    main_facts = _manifest_facts(main)
    candidate_facts = _manifest_facts(candidate)
    report: dict = {
        "verdict": "unreadable",
        "main_version": main_facts[0] if main_facts else None,
        "candidate_version": candidate_facts[0] if candidate_facts else None,
        "removal_ids": [], "undeclared": []}
    if main_facts is None or candidate_facts is None:
        return 2, report
    deprecated = {entry["id"]: entry for entry in main_facts[1]}
    removals = candidate_facts[2]
    report["removal_ids"] = [entry["id"] for entry in removals]
    report["undeclared"] = [
        entry["id"] for entry in removals
        if not (entry["id"] in deprecated and all(
            member in entry and member in deprecated[entry["id"]]
            and entry[member] == deprecated[entry["id"]][member]
            for member in DEPRECATION_MEMBERS))]
    green = (parse_semver(main_facts[0])[0] == 1 and parse_semver(candidate_facts[0])[0] == 2
             and bool(removals) and not report["undeclared"])
    report["verdict"] = "green" if green else "red"
    return (0 if green else 75), report


class GitError(Exception):
    """A git call the cutover checks depend on failed; the caller exits 2."""


def _git(repo_root: Path, *args: str, environ: Mapping[str, str] | None = None,
         text: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            env=dict(os.environ if environ is None else environ),
            capture_output=True, text=text, timeout=300, check=False)
    except (subprocess.SubprocessError, OSError) as error:
        raise GitError(f"git {args[0]}: {type(error).__name__}") from error


def _git_ok(repo_root: Path, *args: str, environ: Mapping[str, str] | None = None) -> str:
    done = _git(repo_root, *args, environ=environ)
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()
        raise GitError(f"git {args[0]} failed: {detail[0] if detail else done.returncode}")
    return done.stdout


def _candidate_sha(repo_root: Path, branch: str, environ: Mapping[str, str] | None) -> str | None:
    ref = f"refs/heads/{branch}"
    for line in _git_ok(repo_root, "ls-remote", "origin", ref, environ=environ).splitlines():
        found, _, name = line.partition("\t")
        if name == ref and _OBJECT_ID.fullmatch(found):
            return found
    return None


def _show_manifest(repo_root: Path, rev: str, environ: Mapping[str, str] | None) -> object:
    """The manifest at `rev`, or None when it cannot be read or is not JSON."""
    done = _git(repo_root, "show", f"{rev}:{MANIFEST_PATH}", environ=environ)
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def _absent_manifest_report() -> dict:
    return {"verdict": "absent", "main_version": None, "candidate_version": None,
            "removal_ids": [], "undeclared": []}


def _fetch_manifests(repo_root: Path, sha: str, main_ref: str | None,
                     environ: Mapping[str, str] | None) -> tuple[object, object]:
    """Both sides' manifests. Fetches objects only: `--refmap=` keeps the main
    fetch from updating a remote-tracking ref, and a bare sha names no ref."""
    _git_ok(repo_root, "fetch", "--quiet", "--no-tags", "origin", sha, environ=environ)
    candidate = _show_manifest(repo_root, sha, environ)
    if main_ref is None:
        _git_ok(repo_root, "fetch", "--quiet", "--no-tags", "--refmap=", "origin",
                "refs/heads/main", environ=environ)
        main_ref = "FETCH_HEAD"
    return _show_manifest(repo_root, main_ref, environ), candidate


def cutover_manifest(repo_root: Path, branch: str = CANDIDATE_BRANCH,
                     main_ref: str | None = None) -> tuple[int, dict]:
    """C4.a over the candidate branch on origin and main (or `main_ref`).

    Raises GitError when git cannot be driven; the caller exits 2."""
    sha = _candidate_sha(repo_root, branch, None)
    if sha is None:
        return 75, _absent_manifest_report()
    return manifest_verdict(*_fetch_manifests(repo_root, sha, main_ref, None))


def _roster(report: dict) -> dict[tuple[object, object], dict]:
    rows = report.get("fleet") if isinstance(report, dict) else None
    found: dict[tuple[object, object], dict] = {}
    for item in rows if isinstance(rows, list) else []:
        if isinstance(item, dict) and isinstance(item.get("project_id"), str):
            found[(item["project_id"], item.get("root"))] = item
    return found


def _platform_version(report: dict) -> str | None:
    platform = report.get("platform") if isinstance(report, dict) else None
    version = platform.get("platform_version") if isinstance(platform, dict) else None
    return version if parse_semver(version) is not None else None


def preflight_verdict(bridge: dict, candidate: dict, candidate_sha: str,
                      manifest: dict) -> tuple[int, dict]:
    """C4.b over the two `platform-status --fleet` reports and the C4.a report."""
    bridge_version = _platform_version(bridge)
    candidate_version = _platform_version(candidate)
    bridge_rows = _roster(bridge)
    candidate_rows = _roster(candidate)
    rows = []
    for key in sorted(set(bridge_rows) | set(candidate_rows), key=lambda k: (k[0], str(k[1]))):
        old, new = bridge_rows.get(key), candidate_rows.get(key)
        removed = new.get("removed_uses") if new else None
        if old is None:
            reason = "bridge_missing"
        elif new is None:
            reason = "candidate_missing"
        elif old.get("compatible") is not True:
            reason = "bridge_incompatible"
        elif new.get("compatible") is not True:
            reason = "candidate_incompatible"
        elif removed != []:
            reason = "removed_use"
        else:
            reason = None
        rows.append({
            "project_id": key[0], "root": key[1],
            "bridge_compatible": None if old is None else old.get("compatible"),
            "candidate_compatible": None if new is None else new.get("compatible"),
            "removed_uses": removed, "reason": reason})
    # A project in only one fleet has a row whose reason is `bridge_missing` or
    # `candidate_missing`, so equal rosters need no rule of their own.
    green = (isinstance(manifest, dict) and manifest.get("verdict") == "green"
             and bridge_version is not None
             and parse_semver(bridge_version)[0] == 1 and parse_semver(bridge_version) >= (1, 2, 0)
             and candidate_version is not None and parse_semver(candidate_version)[0] == 2
             and bool(bridge_rows) and bool(candidate_rows)
             and all(row["reason"] is None for row in rows))
    report = {"verdict": "green" if green else "not_yet", "candidate": candidate_sha,
              "bridge_version": bridge_version, "candidate_version": candidate_version,
              "manifest": manifest, "rows": rows}
    return (0 if green else 75), report


def _preflight_failure(verdict: str, sha: str | None, side: str | None = None,
                       manifest: dict | None = None) -> tuple[int, dict]:
    report: dict = {"verdict": verdict, "candidate": sha, "bridge_version": None,
                    "candidate_version": None, "manifest": manifest, "rows": []}
    if side is not None:
        report["side"] = side
    return 75, report


def _run_side(argv: list[str], env: Mapping[str, str], cwd: Path) -> dict | None:
    """One side's `platform-status --fleet` report, or None when it is not a clean JSON object."""
    try:
        done = subprocess.run(argv, env=dict(env), cwd=cwd, capture_output=True, text=True,
                              timeout=SIDE_TIMEOUT, check=False)
        report = json.loads(done.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    return report if done.returncode == 0 and isinstance(report, dict) else None


def _candidate_module(candidate_python: Path, area: str, name: str) -> str:
    """The dotted module that runs `name` in the unpacked candidate's own layout.

    A candidate cut before the domain layout holds the flat `agent_tools/<name>.py`; a later one
    holds `agent_tools/<area>/<name>.py`. The candidate's code is judged as it stands, so the
    module is named from the files it carries, never from this checkout's layout."""
    if (candidate_python / "agent_tools" / area / f"{name}.py").is_file():
        return f"agent_tools.{area}.{name}"
    return f"agent_tools.{name}"


def cutover_preflight(repo_root: Path, branch: str = CANDIDATE_BRANCH, *,
                      environ: Mapping[str, str]) -> tuple[int, dict]:
    """C4.b: the bridge and the candidate's own code judge every registered project compatible.

    Raises GitError when git cannot be driven; the caller exits 2."""
    sha = _candidate_sha(repo_root, branch, environ)
    if sha is None:
        return _preflight_failure("absent", None)
    main, candidate = _fetch_manifests(repo_root, sha, None, environ)
    _, manifest = manifest_verdict(main, candidate)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        if not _unpack_candidate(repo_root, sha, tmp_path, environ):
            return _preflight_failure("unreadable", sha, "candidate", manifest)
        bridge_env = {key: value for key, value in environ.items() if key != "PYTHONPATH"}
        bridge_bin = shutil.which("resolve-project", path=environ.get("PATH"))
        bridge = (None if bridge_bin is None else _run_side(
            [bridge_bin, "platform-status", "--fleet"], bridge_env, repo_root))
        if bridge is None:
            return _preflight_failure("unreadable", sha, "bridge", manifest)
        candidate_report = _run_side(
            [sys.executable, "-m",
             _candidate_module(tmp_path / "python", "project_contract", "resolve_project"),
             "platform-status", "--fleet", "--manifest", str(tmp_path / MANIFEST_PATH)],
            {**environ, "PYTHONPATH": str(tmp_path / "python")}, tmp_path)
        if candidate_report is None:
            return _preflight_failure("unreadable", sha, "candidate", manifest)
    return preflight_verdict(bridge, candidate_report, sha, manifest)


EVIDENCE_DIR = ".agents/artifacts/evidence"
CUTOVER_BUNDLE_KIND = "cutover"
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")


def bundle_verdict(bundles: Mapping[str, object], candidate_sha: str) -> tuple[int, dict]:
    """C3: some emitted bundle verifies `approved` and binds `candidate_sha`.

    Each value goes through `verify_bundle`, the one verifier of an emitted bundle: the id is
    recomputed over the body and the state re-decided from the bundle's own evidence. The state
    read is its return value, never `document["state"]`. The check is the cutover reader, so a
    gate-version-2 bundle verifies only as the cutover kind (issue 725): any other kind is unreadable."""
    approved: list[str] = []
    other: list[dict] = []
    unreadable: list[dict] = []
    for path in sorted(bundles):
        document = bundles[path]
        try:
            state = verify_bundle(document, kind=CUTOVER_BUNDLE_KIND)
            bound = document["identity"]["bound"]["commit"]["candidate"]  # type: ignore[index]
            if not (isinstance(bound, str) and _COMMIT_ID.fullmatch(bound)):
                raise BundleIntegrityError("identity.bound.commit.candidate is not a commit id")
        except BundleIntegrityError as error:
            unreadable.append({"path": path, "error": str(error)})
            continue
        except (KeyError, TypeError):
            unreadable.append({"path": path,
                               "error": "identity.bound.commit.candidate is missing"})
            continue
        if state == "approved" and bound == candidate_sha:
            approved.append(path)
        else:
            other.append({"path": path, "state": state, "candidate": bound})
    green = bool(approved)
    return (0 if green else 75), {
        "verdict": "green" if green else "red", "candidate": candidate_sha,
        "approved": approved, "other": other, "unreadable": unreadable}


def cutover_bundle(repo_root: Path, branch: str = CANDIDATE_BRANCH) -> tuple[int, dict]:
    """C3 over origin's candidate branch and the bundles committed at origin's main.

    Fetches objects and `FETCH_HEAD` only (`--refmap=` keeps it from updating a remote-tracking
    ref). Raises GitError when git cannot be driven; the caller exits 2."""
    sha = _candidate_sha(repo_root, branch, None)
    if sha is None:
        return 75, {"verdict": "absent", "candidate": None, "approved": [], "other": [],
                    "unreadable": []}
    _git_ok(repo_root, "fetch", "--quiet", "--no-tags", "--refmap=", "origin", "refs/heads/main")
    listing = _git(repo_root, "ls-tree", "--name-only", f"FETCH_HEAD:{EVIDENCE_DIR}/")
    names = sorted(name for name in listing.stdout.splitlines()
                   if listing.returncode == 0 and name.endswith("-bundle.json"))
    bundles: dict[str, object] = {}
    unparsed: list[dict] = []
    for name in names:
        path = f"{EVIDENCE_DIR}/{name}"
        shown = _git(repo_root, "show", f"FETCH_HEAD:{path}")
        try:
            if shown.returncode != 0:
                raise ValueError(f"git show failed: {shown.returncode}")
            bundles[path] = json.loads(shown.stdout)
        except ValueError as error:
            unparsed.append({"path": path, "error": f"not JSON: {error}"})
    code, report = bundle_verdict(bundles, sha)
    report["unreadable"] = sorted(report["unreadable"] + unparsed, key=lambda item: item["path"])
    return code, report


class ToolError(Exception):
    """The check could not judge: `kind` is the stderr label, the caller exits 2."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


SKILLS_CONFIG = ".claude/skills.config.json"
RETIRED_COMMAND = "release deploy inspect"
C11D_DEFAULT_SCOPE = (".", ":!.agents/artifacts")
# The #130 checklist (.agents/artifacts/evidence/cutover-130-checklist.md, C11) documents the
# per-root pathspec: "for `fagenorn/nix-config` its pathspec is `home/common/agent-skills/skills`".
# Keyed on the resolved `project.id`, so the command's own constant, this adapter and the tests
# never count as users of the retired command.
C11D_SCOPES = {"fagenorn/nix-config": ("home/common/agent-skills/skills",)}
C11_TIMEOUT = 120
C11_MAX_HITS = 20


def _run_child(argv: Sequence[str], environ: Mapping[str, str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), env=dict(environ), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=C11_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError("tool_error", f"{Path(argv[0]).name} failed: {error}") from None


def _c11_git(root: Path, environ: Mapping[str, str], *args: str) -> subprocess.CompletedProcess:
    git_bin = shutil.which("git", path=environ.get("PATH"))
    if git_bin is None:
        raise ToolError("tool_error", "git not found")
    return _run_child([git_bin, "--no-optional-locks", "-C", str(root), *args], environ)


def _as_object(text: str, what: str) -> dict:
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ToolError("tool_error", f"{what} printed non-JSON") from None
    if not isinstance(parsed, dict):
        raise ToolError("tool_error", f"{what} did not print an object")
    return parsed


def _deprecated_uses_reading(binary: str, root: Path, environ: Mapping[str, str]) -> dict:
    done = _run_child([binary, "platform-status", "--repo-root", str(root)], environ)
    project = _as_object(done.stdout, "resolve-project platform-status").get("project")
    uses = project.get("deprecated_uses") if isinstance(project, dict) else None
    if not isinstance(uses, list):
        raise ToolError("tool_error", "platform-status has no project.deprecated_uses list")
    return {"exit": done.returncode, "deprecated_uses": uses,
            "status": "green" if not uses else "red"}


def _legacy_config_reading(root: Path, environ: Mapping[str, str]) -> dict:
    done = _c11_git(root, environ, "ls-files", "--", SKILLS_CONFIG)
    if done.returncode != 0:
        raise ToolError("tool_error", f"git ls-files exit {done.returncode}: {done.stderr.strip()}")
    tracked = done.stdout.split()
    return {"tracked": tracked, "status": "green" if not tracked else "red"}


def _resolve_reading(binary: str, root: Path,
                     environ: Mapping[str, str]) -> tuple[dict, dict | None]:
    """Reading `c` and the snapshot it came from (None unless the resolve exited 0 with an object)."""
    done = _run_child([binary, "resolve", "--repo-root", str(root)], environ)
    snapshot = None
    try:
        parsed = json.loads(done.stdout)
        if isinstance(parsed, dict):
            snapshot = parsed
    except ValueError:
        pass
    if done.returncode == 0 and snapshot is None:
        raise ToolError("tool_error", "resolve-project resolve printed no JSON object")
    if done.returncode != 0:
        snapshot = None
    bindings = snapshot.get("bindings") if snapshot else None
    deploy = bindings.get("deploy") if isinstance(bindings, dict) else None
    adapter = deploy.get("adapter") if isinstance(deploy, dict) else None
    # Schema 2 moved deploy targets to `release.targets`: a snapshot of integer `schema_version` 2 or
    # later with a `bindings` object and no `deploy` member is the retired state, as
    # `adapter == "none"` is for schema 1, where an absent `deploy` is not.
    version = snapshot.get("schema_version") if snapshot else None
    no_deploy_binding = (isinstance(bindings, dict) and "deploy" not in bindings
                         and type(version) is int and version >= 2)
    green = done.returncode == 0 and (adapter == "none" or no_deploy_binding)
    return ({"exit": done.returncode, "adapter": adapter,
             "status": "green" if green else "red"}, snapshot)


def _retired_command_reading(root: Path, environ: Mapping[str, str],
                             snapshot: dict | None) -> dict:
    project = snapshot.get("project") if snapshot else None
    project_id = project.get("id") if isinstance(project, dict) else None
    scope = C11D_SCOPES.get(project_id, C11D_DEFAULT_SCOPE) if isinstance(project_id, str) \
        else C11D_DEFAULT_SCOPE
    done = _c11_git(root, environ, "grep", "-n", "-F", RETIRED_COMMAND, "--", *scope)
    if done.returncode not in (0, 1):
        raise ToolError("tool_error", f"git grep exit {done.returncode}: {done.stderr.strip()}")
    hits = done.stdout.splitlines()[:C11_MAX_HITS] if done.returncode == 0 else []
    return {"scope": list(scope), "hits": hits, "status": "green" if done.returncode == 1 else "red"}


def _watch_reading(snapshot: dict | None, adapter: str) -> dict:
    release = snapshot.get("release") if snapshot else None
    targets = release.get("targets") if isinstance(release, dict) else None
    adopted = [t for t in targets or [] if isinstance(t, dict) and t.get("adapter") == adapter]
    if not adopted:
        return {"adapter": adapter, "status": "pending"}
    capabilities = snapshot.get("capabilities") if snapshot else None
    state_row = capabilities.get("release") if isinstance(capabilities, dict) else None
    row = state_row if isinstance(state_row, dict) else {}
    state = row.get("state")
    return {"adapter": adapter, "state": state, "reason_code": row.get("reason_code"),
            "status": "green" if state == "available" else "red"}


def deprecations_retired_check(roots: Sequence[Path], environ: Mapping[str, str], *,
                               watch_adapter: str | None, red_pending: bool) -> tuple[int, dict]:
    """The C11 rule over each root. Raises ToolError when a root cannot be judged."""
    binary = shutil.which("resolve-project", path=environ.get("PATH"))
    if binary is None:
        raise ToolError("tool_error", "resolve-project not found")
    rows = []
    for root in roots:
        readings: dict = {"a": _deprecated_uses_reading(binary, root, environ),
                          "b": _legacy_config_reading(root, environ)}
        readings["c"], snapshot = _resolve_reading(binary, root, environ)
        readings["d"] = _retired_command_reading(root, environ, snapshot)
        readings["watch"] = (_watch_reading(snapshot, watch_adapter)
                             if watch_adapter is not None else None)
        statuses = [r["status"] for r in readings.values() if r is not None]
        verdict = ("red" if "red" in statuses
                   else "pending" if "pending" in statuses else "green")
        rows.append({"root": str(root), "readings": readings, "verdict": verdict})
    verdicts = [row["verdict"] for row in rows]
    green = all(v == "green" for v in verdicts)
    if green:
        code = 0
    elif red_pending:
        code = 75
    elif "red" in verdicts:
        code = 1
    else:
        code = 75
    return code, {"met": green, "roots": rows}


def _repo(value: str) -> str:
    if not REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _nonempty(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def _rfc3339(value: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an RFC 3339 instant with Z or an offset") from None


GUARD_DERIVE_TIMEOUT = 300


def _unpack_candidate(repo_root: Path, sha: str, destination: Path,
                      environ: Mapping[str, str]) -> bool:
    """Unpack `python/` and the manifest at `sha` into `destination`; False when it cannot."""
    archive = _git(repo_root, "archive", "--format=tar", sha, "python", MANIFEST_PATH,
                   environ=environ, text=False)
    if archive.returncode != 0:
        return False
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(destination, filter="data")
    except (tarfile.TarError, OSError):
        return False
    return True


def _read_registry(path: Path, *, absent_ok: bool = False) -> dict | None:
    """The registry document at `path`, or None when it is unreadable or fails the guard's own
    `validate_registry`. A missing file is the empty fleet only when `absent_ok` (the host's
    implicit default registry); a path the operator named that is missing is unreadable."""
    try:
        document = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {"schema_version": 1, "projects": []} if absent_ok else None
    except (OSError, ValueError):
        return None
    return None if validate_registry(document) else document


def _registry_entries(path: Path, *, absent_ok: bool = False) -> list[dict] | None:
    """The `projects` of the registry file at `path`, or None when it is unreadable."""
    document = _read_registry(path, absent_ok=absent_ok)
    return None if document is None else document["projects"]


def _entry_slug(entry: dict, environ: Mapping[str, str]) -> str | None:
    """The github slug of the entry's `origin` fetch url, read in the entry's own root."""
    root = entry.get("root")
    if not isinstance(root, str):
        return None
    try:
        done = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root,
                              env=dict(environ), capture_output=True, text=True,
                              timeout=C11_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return github_remote.github_slug(done.stdout) if done.returncode == 0 else None


def _candidate_env(environ: Mapping[str, str], candidate_home: Path,
                   candidate_python: Path) -> dict[str, str]:
    """`environ` with the candidate's `HOME` and `PYTHONPATH`. The temporary `HOME` must not
    strand the forge and git configuration the host reads from its real one."""
    env = {**environ, "HOME": str(candidate_home), "PYTHONPATH": str(candidate_python)}
    home = environ.get("HOME")
    if home and "GH_CONFIG_DIR" not in env:
        env["GH_CONFIG_DIR"] = str(Path(home) / ".config/gh")
    if home and "GIT_CONFIG_GLOBAL" not in env and (Path(home) / ".gitconfig").is_file():
        env["GIT_CONFIG_GLOBAL"] = str(Path(home) / ".gitconfig")
    return env


def _derive_row(slug: str, child_env: Mapping[str, str], cwd: Path, module: str) -> dict:
    row: dict = {"repository": slug, "exit": None, "outcome": "unreadable", "reason_codes": []}
    try:
        done = subprocess.run(
            [sys.executable, "-m", module, "derive", "--repository", slug],
            env=dict(child_env), cwd=cwd, capture_output=True, text=True,
            timeout=GUARD_DERIVE_TIMEOUT, check=False)
        report = json.loads(done.stdout)
        outcome, refused = report["outcome"], report["refused"]
        row.update(exit=done.returncode, outcome=outcome,
                   reason_codes=sorted({r["reason_code"] for r in refused}))
        derived = done.returncode == 0 and outcome == "derived" and isinstance(report["row"], dict)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        derived = False
    row["verdict"] = "green" if derived else "red"
    return row


def guard_policy_fleet(repo_root: Path, branch: str = CANDIDATE_BRANCH, *,
                       environ: Mapping[str, str],
                       registry: Path | None = None) -> tuple[int, dict]:
    """C13.a: the candidate's own `guard-policy derive` yields a row for every registered slug.

    Raises GitError when git cannot be driven; the caller exits 2."""
    sha = _candidate_sha(repo_root, branch, environ)
    report: dict = {"verdict": "absent", "candidate": None, "rows": []}
    if sha is None:
        return 75, report
    report["candidate"] = sha
    _git_ok(repo_root, "fetch", "--quiet", "--no-tags", "origin", sha, environ=environ)
    home = environ.get("HOME", "")
    document = (_read_registry(registry) if registry is not None else
                _read_registry(Path(home) / ".agents/state/fleet/registry.json", absent_ok=True))
    if document is None:
        return 75, {**report, "verdict": "unreadable", "side": "registry"}
    entries = document["projects"]
    slugs: dict[str, None] = {}
    rows: list[dict] = []
    for entry in entries:
        slug = _entry_slug(entry, environ)
        if slug is None:
            rows.append({"repository": None, "project_id": entry.get("project_id"),
                         "exit": None, "outcome": "origin_unproven", "reason_codes": [],
                         "verdict": "red"})
        else:
            slugs[slug] = None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        if not _unpack_candidate(repo_root, sha, tmp_path, environ):
            return 75, {**report, "verdict": "unreadable", "side": "candidate"}
        candidate_home = tmp_path / "home"
        manifest = candidate_home / ".agents/share/platform-manifest.json"
        manifest.parent.mkdir(parents=True)
        shutil.copy(tmp_path / MANIFEST_PATH, manifest)
        registry_copy = candidate_home / ".agents/state/fleet/registry.json"
        registry_copy.parent.mkdir(parents=True)
        registry_copy.write_text(json.dumps(document), encoding="utf-8")
        child_env = _candidate_env(environ, candidate_home, tmp_path / "python")
        module = _candidate_module(tmp_path / "python", "guard", "guard_policy")
        rows.extend(_derive_row(slug, child_env, tmp_path, module) for slug in slugs)
    rows.sort(key=lambda r: (r["repository"] is None, r["repository"] or ""))
    green = all(row["verdict"] == "green" for row in rows)
    return (0 if green else 1), {**report, "verdict": "green" if green else "red", "rows": rows}


def registry_agreement(registries: Mapping[str, Sequence[Mapping]],
                       intentional: Sequence[str] = ()) -> tuple[int, dict]:
    """C13.b: each project on more than one host has the same `branch_override` on all of them."""
    seen: dict[str, dict[str, object]] = {}
    for host, entries in registries.items():
        for entry in entries:
            seen.setdefault(str(entry.get("project_id")), {})[host] = entry.get("branch_override")
    rows = []
    for project_id, overrides in sorted(seen.items()):
        if len(overrides) < 2:
            continue
        distinct = {json.dumps(value, sort_keys=True) for value in overrides.values()}
        verdict = ("green" if len(distinct) == 1
                   else "intentional" if project_id in intentional else "red")
        rows.append({"project_id": project_id, "branch_override": overrides, "verdict": verdict})
    red = any(row["verdict"] == "red" for row in rows)
    return (1 if red else 0), {"verdict": "red" if red else "green", "rows": rows}


SHELL_PROBE = ('print -r -- "__VERIFY_PATH__=$PATH"; '
               'print -r -- "__VERIFY_PYTHON__=$(python3 --version 2>&1)"')
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
INHERITED_PATH = ("/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
                  "/etc/profiles/per-user/{user}/bin:/run/current-system/sw/bin")
_UNREADABLE_PROBE = {"readable": False, "path": None, "profile_before_usr_bin": False,
                     "python": None, "python_ok": False, "met": False}


def shell_path_verdict(path_value: str, python_version: str, user: str) -> dict:
    """One probe's reading: the user's profile dir ahead of /usr/bin, and python3 3.13 or later."""
    entries = path_value.split(":")
    profile = f"/etc/profiles/per-user/{user}/bin"
    profile_first = (profile in entries and "/usr/bin" in entries
                     and entries.index(profile) < entries.index("/usr/bin"))
    found = re.search(r"Python (\d+)\.(\d+)(?:\.(\d+))?", python_version)
    python = ".".join(part for part in found.groups() if part is not None) if found else None
    python_ok = found is not None and (int(found.group(1)), int(found.group(2))) >= (3, 13)
    return {"readable": True, "path": path_value, "profile_before_usr_bin": profile_first,
            "python": python, "python_ok": python_ok, "met": profile_first and python_ok}


def _sentinel(stdout: str, prefix: str) -> str | None:
    value = None
    for line in stdout.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):]
    return value


def _shell_probe(zsh_bin: str, env: Mapping[str, str], user: str, timeout: int) -> dict:
    try:
        done = subprocess.run([zsh_bin, "-l", "-i", "-c", SHELL_PROBE], env=dict(env),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return dict(_UNREADABLE_PROBE)
    path_value = _sentinel(done.stdout, "__VERIFY_PATH__=")
    python_version = _sentinel(done.stdout, "__VERIFY_PYTHON__=")
    if path_value is None or python_version is None:
        return dict(_UNREADABLE_PROBE)
    return shell_path_verdict(path_value, python_version, user)


def darwin_shell_path(*, user: str, home: str, zsh_bin: str = "/bin/zsh",
                      timeout: int = 60) -> tuple[int, dict]:
    """Issue 810: a fresh login zsh puts the Nix profiles before /usr/bin, also from an inherited PATH."""
    clean = {"HOME": home, "USER": user, "LOGNAME": user, "SHELL": zsh_bin, "TERM": "dumb",
             "PATH": BASE_PATH}
    inherited = {**clean, "__NIX_DARWIN_SET_ENVIRONMENT_DONE": "1",
                 "PATH": INHERITED_PATH.format(user=user)}
    probes = {"clean": _shell_probe(zsh_bin, clean, user, timeout),
              "inherited": _shell_probe(zsh_bin, inherited, user, timeout)}
    met = all(probe["met"] for probe in probes.values())
    unreadable = not all(probe["readable"] for probe in probes.values())
    return (2 if unreadable else 0 if met else 1), {"met": met, "probes": probes}


RAILWAY_UNREAD_REASONS = ("executable_missing", "railway_unauthorized", "lookup_failed",
                          "lookup_timeout", "payload_invalid", "project_mismatch",
                          "parameters_invalid")
# The seconds the whole collection may take. One source read still running at the deadline can hold
# three network git children (`ls-remote`, the default branch's fetch and the integration branch's
# fetch in `adopt_verify.remote_source`), each bounded by `verify_exec.GIT_TIMEOUT`, so the budget plus
# three of them stays under `verify_exec.TIMEOUT`, which kills the check's process group.
RAILWAY_READ_BUDGET = 200
# The host's non-project system and profile bin directories: every non-store entry of the
# verify-pending runner's PATH, plus the per-user, XDG and Homebrew profiles railway can be installed in.
RAILWAY_SYSTEM_DIRS = ("/run/current-system/sw/bin", "/etc/profiles/per-user/{user}/bin",
                       "{home}/.nix-profile/bin", "{home}/.local/state/nix/profile/bin",
                       "/nix/var/nix/profiles/default/bin", "/opt/homebrew/bin", "/usr/local/bin",
                       "/usr/bin", "/bin", "/usr/sbin", "/sbin")


class _ReadTimeout(Exception):
    """A child outlasted the collection's deadline."""


def railway_system_path(user: str, home: str, prefix: str = "") -> str:
    """`RAILWAY_SYSTEM_DIRS` as a PATH; `prefix` roots the absolute entries (a test seam)."""
    entries = []
    for entry in RAILWAY_SYSTEM_DIRS:
        entries.append((home + entry[len("{home}"):]) if entry.startswith("{home}")
                       else prefix + entry.format(user=user))
    return ":".join(entries)


def _run_bounded(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str],
                 deadline: float) -> subprocess.CompletedProcess:
    """Run `argv` until `deadline`; kill its process group and raise `_ReadTimeout` past it."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _ReadTimeout
    proc = subprocess.Popen(list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        raise _ReadTimeout from None
    return subprocess.CompletedProcess(list(argv), proc.returncode, out or "", err or "")


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _railway_profile_inspection(contract_root: Path, profile_id: str, env: Mapping[str, str],
                                deadline: float) -> dict | None:
    """`release profile inspect` of the packaged sibling at `contract_root`, or None when unreadable."""
    argv = [*siblings.sibling_argv("release.release"), "profile", "inspect", profile_id,
            "--repo-root", str(contract_root)]
    try:
        done = _run_bounded(argv, cwd=contract_root, env=env, deadline=deadline)
    except OSError:
        return None
    return _json_object(done.stdout) if done.returncode == 0 else None


def _railway_units(inspection: dict, target: dict) -> list[tuple[str, dict]] | None:
    """`(node id, config)` of each railway-deploy deploy unit of the target, or None when malformed."""
    try:
        adapters = inspection["bindings"]["adapters"]
        nodes = inspection["graphs"]["activation"]
        handle = target["target"]["handle"]
        units = []
        for node in nodes:
            alias = adapters.get(node["adapter"])
            if (isinstance(alias, dict) and alias.get("adapter") == "railway-deploy"
                    and node["operation"] == "deploy" and node["target"] == handle):
                units.append((node["id"], alias["config"][node["id"]]))
        return units
    except (KeyError, TypeError, AttributeError):
        return None


def _railway_read(observation: dict) -> tuple[bool, str]:
    """Whether the observation read the unit's services, and its reason."""
    reason = observation.get("reason")
    reason = reason if isinstance(reason, str) else "payload_invalid"
    facts = observation.get("facts")
    services = facts.get("services") if isinstance(facts, dict) else None
    if not isinstance(services, list) or not services:
        return False, reason
    for service in services:
        if not isinstance(service, dict) or service.get("reason") in RAILWAY_UNREAD_REASONS:
            return False, reason
    return True, reason


def railway_project_read(*, user: str, home: str, system_path: str | None = None,
                         environ: Mapping[str, str] | None = None,
                         source=verify_exec.project_source,
                         inspect_profile=_railway_profile_inspection,
                         budget: float = RAILWAY_READ_BUDGET) -> tuple[int, dict]:
    """Issue 1124: no system railway, and every registered Railway unit reads from its dev shell."""
    deadline = time.monotonic() + budget
    path = system_path or railway_system_path(user, home)
    found = shutil.which("railway", path=path)
    if found:
        return 1, {"met": False, "system_railway": found, "units": 0, "read": 0, "reasons": []}

    def failed(code: str) -> tuple[int, dict]:
        return 2, {"met": False, "error": code}
    entries = _registry_entries(Path(home) / ".agents/state/fleet/registry.json", absent_ok=True)
    if entries is None:
        return failed("registry_unreadable")
    base = dict(os.environ if environ is None else environ)
    pythonpath = ":".join(os.path.abspath(part) for part in base.get("PYTHONPATH", "").split(":")
                          if part)
    env = {**base, "PATH": path, "PYTHONPATH": pythonpath}
    outcomes: list[tuple[bool, str]] = []
    try:
        for entry in entries:
            if time.monotonic() >= deadline:
                return failed("read_timeout")
            work: list[tuple[Path, dict]] = []
            try:
                with source(entry) as src:
                    release = src.snapshot.get("release")
                    targets = release.get("targets") if isinstance(release, dict) else None
                    for target in targets if isinstance(targets, list) else []:
                        if not isinstance(target, dict) or target.get("adapter") != "railway-deploy":
                            continue
                        inspection = inspect_profile(src.contract_root, target.get("profile"),
                                                     env, deadline)
                        units = None if inspection is None else _railway_units(inspection, target)
                        if units is None:
                            return failed("inspection_unreadable")
                        for _, config in units:
                            ground = target["target"]
                            work.append((Path(entry["root"]), {
                                "target": {"kind": ground["kind"],
                                           "repository": ground["repository"],
                                           "branch": ground["branch"]},
                                "candidate": {"commit": src.commit}, "config": config}))
            except verify_exec.SourceError:
                return failed("contract_unreadable")
            for root, parameters in work:
                if not (root / "devenv.nix").is_file():
                    outcomes.append((False, "no_dev_shell"))
                    continue
                if shutil.which("devenv", path=path) is None:
                    return failed("devenv_missing")
                argv = ["devenv", "shell", "--", "env", f"PYTHONPATH={pythonpath}",
                        *siblings.sibling_argv("release.release"), "adapter", "inspect",
                        "railway-deploy", "deploy", "--parameters",
                        json.dumps(parameters, sort_keys=True)]
                try:
                    done = _run_bounded(argv, cwd=root, env=env, deadline=deadline)
                except OSError:
                    return failed("read_failed")
                lines = [line for line in done.stdout.splitlines() if line.strip()]
                observation = _json_object(lines[-1]) if lines else None
                if done.returncode != 0 or observation is None:
                    return failed("read_failed")
                outcomes.append(_railway_read(observation))
    except _ReadTimeout:
        return failed("read_timeout")
    read = sum(1 for ok, _ in outcomes if ok)
    code = 75 if not outcomes else 0 if read == len(outcomes) else 1
    return code, {"met": code == 0, "system_railway": None, "units": len(outcomes), "read": read,
                  "reasons": sorted({reason for _, reason in outcomes})}


def console_state(port: int, *, timeout: float = 5.0) -> tuple[int, dict]:
    """Issue 856: the console's state endpoint answers 200 on loopback (0), else 1."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/api/state")
        status = connection.getresponse().status
    except (OSError, http.client.HTTPException) as error:
        return 1, {"port": port, "status": None, "error": f"{type(error).__name__}: {error}"}
    finally:
        connection.close()
    return (0 if status == 200 else 1), {"port": port, "status": status}


LONG_GOAL_CHARS = 1000
NEEDLE = slice(200, 300)


def _sprint_entries(view: object) -> list[dict]:
    """Issue 1031: every sprint entry of the live view, the same dict objects as in `view`."""
    if not isinstance(view, dict) or not isinstance(view.get("entries"), list):
        return []
    projects: list[object] = []
    for entry in view["entries"]:
        if isinstance(entry, dict) and entry.get("type") == "quiet_group":
            members = entry.get("projects")
            projects.extend(members if isinstance(members, list) else [])
        else:
            projects.append(entry)
    found: list[dict] = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        finished = project.get("finished_sprints")
        for group in (project.get("sprints"),
                      finished.get("sprints") if isinstance(finished, dict) else None):
            if isinstance(group, list):
                found.extend(sprint for sprint in group if isinstance(sprint, dict))
    return found


def _walk_strings(value: object, path: str, exempt: set[int]) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, member in value.items():
            if key == "goal" and id(value) in exempt:
                continue
            yield from _walk_strings(member, f"{path}.{key}" if path else str(key), exempt)
    elif isinstance(value, list):
        for index, member in enumerate(value):
            yield from _walk_strings(member, f"{path}[{index}]", exempt)


def _strings(value: object, path: str = "") -> Iterator[tuple[str, str]]:
    """Every decoded string in `value` with its dotted path, bar each sprint entry's own goal."""
    return _walk_strings(value, path, {id(entry) for entry in _sprint_entries(value)})


def _collapse(text: str) -> str:
    """Issue 1031: `text` as rendered prose, every run of whitespace one space, the ends trimmed."""
    return " ".join(text.split())


def _short(value: object, low: int, high: int, *, stripped: bool = False) -> bool:
    return isinstance(value, str) and low <= len((value.strip() if stripped else value)) <= high


def _question_members(item: dict, sprint_title: object) -> list[str]:
    members: list[str] = []
    if "goal" in item:
        members.append("goal")
    if not _short(item.get("title"), 1, 60) or item["title"] != sprint_title:
        members.append("title")
    if not _short(item.get("headline"), 1, 140, stripped=True):
        members.append("headline")
    questions = item.get("questions")
    if (not isinstance(questions, list) or not questions
            or not all(isinstance(q, dict) and _short(q.get("question"), 1, 140, stripped=True)
                       for q in questions)):
        members.append("questions")
    options_ok = all(
        isinstance(q.get("options"), list) and 2 <= len(q["options"]) <= 4
        and all(_short(o, 1, 80, stripped=True) for o in q["options"])
        for q in (questions if isinstance(questions, list) else ()) if isinstance(q, dict))
    if not options_ok:
        members.append("options")
    context = item.get("context")
    if context is not None and not _short(context, 0, 400):
        members.append("context")
    return members


def _long_goal_questions(view: object) -> tuple[list[dict], dict[object, dict], list[dict]]:
    """Issue 1031: the sprint entries, the long-goal ones by id and their open question items."""
    sprints = _sprint_entries(view)
    long_sprints = {sprint.get("sprint_id"): sprint for sprint in sprints
                    if isinstance(sprint.get("sprint_id"), str) and isinstance(sprint.get("goal"), str) and len(sprint["goal"]) > LONG_GOAL_CHARS}
    inbox = view.get("inbox") if isinstance(view, dict) else None
    opened = inbox.get("open") if isinstance(inbox, dict) else None
    candidates = [item for item in opened if isinstance(item, dict) and item.get("reason") == "question"
                  and isinstance(item.get("sprint_id"), str) and item["sprint_id"] in long_sprints] if isinstance(opened, list) else []
    return sprints, long_sprints, candidates


def first_screen_state(view: object) -> tuple[int, dict]:
    """Issue 1031: a long-goal question reads by title with a short ask, 0 met, 1 not met, 75 not yet."""
    sprints, long_sprints, candidates = _long_goal_questions(view)
    if not candidates:
        return 75, {"verdict": "not_yet", "questions": 0}
    problems: list[dict] = []
    for item in candidates:
        sprint_id = item["sprint_id"]
        for member in _question_members(item, long_sprints[sprint_id].get("title")):
            problems.append({"sprint_id": sprint_id, "member": member})
    for sprint in sprints:
        goal = sprint.get("goal")
        if not (isinstance(goal, str) and len(goal) > LONG_GOAL_CHARS):
            continue
        needle = goal[NEEDLE]
        for path, text in _strings(view):
            if needle in text:
                problems.append({"sprint_id": sprint.get("sprint_id"), "member": "goal_text", "path": path})
    if not problems:
        return 0, {"verdict": "met", "questions": len(candidates)}
    return 1, {"verdict": "not_met", "questions": len(candidates), "problems": problems}


class BrowserError(Exception):
    """Issue 1031: the headless browser failed, closed its pipe or did not answer in time."""


def browser_command() -> list[str]:
    """Issue 1031: `chromium` from the PATH, else Chromium through `nix shell`."""
    found = shutil.which("chromium")
    return [found] if found is not None else ["nix", "shell", "n#chromium", "--command", "chromium"]


MEASURE_JS = """(() => {
  const lead = document.querySelector(".lead");
  const ask = lead && lead.querySelector("h2.q");
  const title = lead && lead.querySelector(".head .sprint-title");
  const box = (node) => { const r = node.getBoundingClientRect(); return {top: r.top, bottom: r.bottom}; };
  return {
    viewport: {width: window.innerWidth, height: window.innerHeight},
    lead: ask ? {
      title: title ? title.textContent : null,
      ask: Object.assign({text: ask.textContent,
                          clipped: ask.scrollHeight > ask.clientHeight + 1 || ask.scrollWidth > ask.clientWidth + 1},
                         box(ask)),
      options: Array.from(lead.querySelectorAll("button.opt")).map((b) =>
        Object.assign({text: (b.querySelector(".ot") || b).textContent}, box(b))),
    } : null,
    text: document.body.innerText,
  };
})()"""

GRACE = 10.0


class _Pipe:
    """The DevTools pipe transport: `\\0`-terminated JSON objects, written to fd 3 and read from fd 4 of the browser."""

    def __init__(self, write_fd: int, read_fd: int) -> None:
        self.write_fd, self.read_fd = write_fd, read_fd
        self.buffer = b""
        self.next_id = 0

    def call(self, method: str, deadline: float, params: dict, session: str | None = None) -> dict:
        self.next_id += 1
        message: dict = {"id": self.next_id, "method": method, "params": params}
        if session is not None:
            message["sessionId"] = session
        try:
            os.write(self.write_fd, json.dumps(message).encode() + b"\0")
        except OSError as error:
            raise BrowserError(f"{method}: {type(error).__name__}: {error}") from error
        while True:
            reply = self._read(method, deadline)
            if reply.get("id") != self.next_id:
                continue
            if "error" in reply:
                raise BrowserError(f"{method}: {reply['error']}")
            result = reply.get("result")
            return result if isinstance(result, dict) else {}

    def _read(self, method: str, deadline: float) -> dict:
        while b"\0" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.read_fd], [], [], remaining)[0]:
                raise BrowserError(f"{method}: no reply")
            try:
                chunk = os.read(self.read_fd, 65536)
            except OSError as error:
                raise BrowserError(f"{method}: {type(error).__name__}: {error}") from error
            if not chunk:
                raise BrowserError(f"{method}: the browser closed its pipe")
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\0", 1)
        try:
            reply = json.loads(raw)
        except ValueError as error:
            raise BrowserError(f"{method}: an unreadable reply: {error}") from error
        return reply if isinstance(reply, dict) else {}


EXEC_ON_PIPE_FDS = (
    "import os, sys\n"
    "os.dup2(int(sys.argv[1]), 3)\n"
    "os.dup2(int(sys.argv[2]), 4)\n"
    "os.execvp(sys.argv[3], sys.argv[3:])"
)
"""Issue 1031: run the browser with the pipes on descriptors 3 and 4. dash's `3<&10` is "Bad fd number", so no shell does it."""


def _high_fd(fd: int) -> int:
    """Move `fd` to a number of 10 or more, so the launcher's dup2 onto 3 and 4 cannot clash with it."""
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(fd)
    return moved


def chromium_first_screen(url: str, *, width: int, height: int, screenshot: Path,
                          browser: Sequence[str], timeout: float = 300.0) -> dict:
    """Issue 1031: load `url` headless at width x height, save a PNG and return `MEASURE_JS` once the lead card exists.

    The browser is driven over `--remote-debugging-pipe` and is sent no input event; its profile is
    removed and the browser ended on every path. One deadline, `timeout` seconds from the start, bounds
    every reply read up to the end of the polling; the last evaluation, the screenshot and the close each get `GRACE` more.
    Raises `BrowserError` naming the method that failed.
    """
    profile = tempfile.mkdtemp()
    to_browser_read, to_browser_write = (_high_fd(fd) for fd in os.pipe())
    from_browser_read, from_browser_write = (_high_fd(fd) for fd in os.pipe())
    process: subprocess.Popen | None = None
    owned = [to_browser_read, to_browser_write, from_browser_read, from_browser_write]
    try:
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", EXEC_ON_PIPE_FDS, str(to_browser_read), str(from_browser_write), *browser,
                 "--headless=new", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
                 "--hide-scrollbars", f"--user-data-dir={profile}", f"--window-size={width},{height}",
                 "about:blank"],
                pass_fds=(to_browser_read, from_browser_write),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            for fd in (to_browser_read, from_browser_write):
                os.close(fd)
                owned.remove(fd)
        pipe = _Pipe(to_browser_write, from_browser_read)
        deadline = time.monotonic() + timeout
        target = pipe.call("Target.createTarget", deadline, {"url": "about:blank"}).get("targetId")
        session = pipe.call("Target.attachToTarget", deadline, {"targetId": target, "flatten": True}).get("sessionId")
        pipe.call("Emulation.setDeviceMetricsOverride", deadline,
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session)
        pipe.call("Page.navigate", deadline, {"url": url}, session)
        measure = None
        while True:
            result = pipe.call("Runtime.evaluate", max(deadline, time.monotonic() + GRACE), {"expression": MEASURE_JS, "returnByValue": True}, session)
            value = result.get("result", {}).get("value") if isinstance(result.get("result"), dict) else None
            if isinstance(value, dict):
                measure = value
                if value.get("lead") is not None:
                    break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if measure is None:
            raise BrowserError("Runtime.evaluate: no measurement")
        data = pipe.call("Page.captureScreenshot", max(deadline, time.monotonic()) + GRACE, {"format": "png"}, session).get("data")
        if not isinstance(data, str):
            raise BrowserError("Page.captureScreenshot: no image data")
        screenshot.write_bytes(base64.b64decode(data))
        try:
            pipe.call("Browser.close", time.monotonic() + GRACE, {})
        except BrowserError:
            pass
        return measure
    finally:
        for fd in owned:
            os.close(fd)
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            else:
                process.wait()
        shutil.rmtree(profile, ignore_errors=True)


FOLD = 900


def console_first_screen(port: int, *, browser: Sequence[str] | None = None, timeout: float = 300.0,
                         out_dir: Path | None = None) -> tuple[int, dict]:
    """Issue 1031: the live first screen at 1440x900 shows the long-goal question whole above the fold (0), else 1 or 75."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    status: int | None = None
    try:
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        status = response.status
        body = response.read()
        view = json.loads(body) if status == 200 else None
        error = None if isinstance(view, dict) else f"status {status}: not a JSON object"
    except (OSError, http.client.HTTPException, ValueError) as caught:
        view, error = None, f"{type(caught).__name__}: {caught}"
    finally:
        connection.close()
    if not isinstance(view, dict):
        return 1, {"verdict": "unreachable", "port": port, "status": status, "error": error or f"status {status}"}
    code, report = first_screen_state(view)
    if code != 0:
        return code, {**report, "port": port}
    out = out_dir if out_dir is not None else Path(tempfile.mkdtemp(prefix="console-first-screen-"))
    screenshot = out / "first-screen-1440.png"
    try:
        out.mkdir(parents=True, exist_ok=True)
        measure = chromium_first_screen(f"http://127.0.0.1:{port}/", width=1440, height=900, screenshot=screenshot,
                                        browser=list(browser) if browser else browser_command(), timeout=timeout)
    except (BrowserError, OSError) as caught:
        return 1, {"verdict": "no_browser", "port": port, "error": f"{type(caught).__name__}: {caught}"}
    _, long_sprints, candidates = _long_goal_questions(view)
    lead = measure.get("lead")
    ask = lead.get("ask") if isinstance(lead, dict) else None
    ask_text = ask.get("text") if isinstance(ask, dict) and isinstance(ask.get("text"), str) else None
    title_text = lead.get("title") if isinstance(lead, dict) and isinstance(lead.get("title"), str) else None
    asked = [c for c in candidates if ask_text is not None and ask_text.strip() == str(c.get("headline")).strip()]
    chosen = next((c for c in asked if title_text is not None and title_text.strip() == str(c.get("title")).strip()),
                  asked[0] if asked else None)
    if chosen is None:
        return 75, {"verdict": "not_yet", "lead": "other", "screenshot": str(screenshot)}
    problems: list[dict] = []
    if title_text is None or title_text.strip() != str(chosen.get("title")).strip():
        problems.append({"member": "lead_title"})
    if ask["top"] < 0 or ask["bottom"] > FOLD or ask.get("clipped"):
        problems.append({"member": "fold_ask"})
    options = lead.get("options") if isinstance(lead.get("options"), list) else []
    if ([str(option.get("text", "")).strip() for option in options] != chosen["questions"][0]["options"]
            or any(option.get("bottom", FOLD + 1) > FOLD for option in options)):
        problems.append({"member": "fold_options"})
    text = _collapse(measure.get("text") if isinstance(measure.get("text"), str) else "")
    needles = (_collapse(sprint["goal"][NEEDLE]) for sprint in long_sprints.values())
    if any(needle and needle in text for needle in needles):
        problems.append({"member": "visible_goal"})
    if not problems:
        return 0, {"verdict": "met", "port": port, "screenshot": str(screenshot), "viewport": measure.get("viewport")}
    return 1, {"verdict": "not_met", "port": port, "screenshot": str(screenshot), "problems": problems}


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 65535")
    return port


def _issue_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _merge_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError("must be a 40-character lowercase hex sha")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-checks")
    checks = parser.add_subparsers(dest="check", required=True)
    required = checks.add_parser("required-checks",
                                 help="issue 627: required checks passed before the merge")
    required.add_argument("--repo", type=_repo, required=True)
    required.add_argument("--base", required=True)
    required.add_argument("--since", type=_rfc3339, required=True)
    hook = checks.add_parser(
        "managed-pre-push-hook",
        help="issue 672: the managed pre-push hook refuses an agent default-branch push")
    hook.add_argument("--slug", type=_repo, required=True)
    for name, help_text in (
            ("cutover-manifest", "issue 579 C4.a: the candidate's removals were main's deprecations"),
            ("cutover-preflight", "issue 579 C4.b: the bridge and the candidate judge the fleet"),
            ("cutover-bundle", "issue 579 C3: an approved bundle binds the candidate")):
        cutover = checks.add_parser(name, help=help_text)
        cutover.add_argument("--repo-root", type=Path, default=Path("."))
        cutover.add_argument("--branch", default=CANDIDATE_BRANCH)
        if name == "cutover-manifest":
            cutover.add_argument("--main-ref", default=None)
    runner = checks.add_parser(
        "self-hosted-runner",
        help="issue 680: a named self-hosted runner is registered, online and labelled")
    runner.add_argument("--repo", type=_repo, required=True)
    runner.add_argument("--runner", type=_nonempty, required=True)
    runner.add_argument("--label", type=_nonempty, action="append", required=True)
    retired = checks.add_parser(
        "deprecations-retired",
        help="issue 582: the deprecated paths have zero users in every root (C11)")
    retired.add_argument("--repo-root", type=Path, action="append", required=True)
    retired.add_argument("--watch-adapter")
    retired.add_argument("--red-pending", action="store_true")
    fleet = checks.add_parser(
        "guard-policy-fleet",
        help="issue 765 C13.a: the candidate derives a guard policy row for every registered slug")
    fleet.add_argument("--repo-root", type=Path, default=Path("."))
    fleet.add_argument("--branch", default=CANDIDATE_BRANCH)
    fleet.add_argument("--registry", type=Path)
    agreement = checks.add_parser(
        "registry-agreement",
        help="issue 765 C13.b: registries agree on branch_override per project across hosts")
    agreement.add_argument("--registry", nargs="+", required=True, metavar="HOST=FILE")
    agreement.add_argument("--intentional", action="append", default=[], metavar="PROJECT_ID")
    shell = checks.add_parser(
        "darwin-shell-path",
        help="issue 810: a fresh login zsh puts the Nix profiles before /usr/bin")
    shell.add_argument("--zsh", default="/bin/zsh")
    railway = checks.add_parser(
        "railway-project-read",
        help="issue 1124: no system railway, and every registered Railway unit reads its deploys "
             "from its dev shell")
    railway.add_argument("--system-path", default=None)
    console = checks.add_parser(
        "console-state",
        help="issue 856: the console's state endpoint answers 200 on loopback")
    console.add_argument("--port", type=_port, required=True)
    first = checks.add_parser(
        "console-first-screen",
        help="issue 1031: the live console's first screen shows a long-goal question whole above the fold")
    first.add_argument("--port", type=_port, required=True)
    first.add_argument("--browser", type=_nonempty)
    closed = checks.add_parser(
        "issue-closed",
        help="issue 1010: an issue was closed as completed, by its own verify run")
    closed.add_argument("--repo", type=_repo, required=True)
    closed.add_argument("--issue", type=_issue_number, required=True)
    regress = checks.add_parser(
        "suite-regressions",
        help="issue 1215: no suite member that passed before the merge failed in the runs from it on")
    regress.add_argument("--repo", type=_repo, required=True)
    regress.add_argument("--workflow", type=_nonempty, required=True)
    regress.add_argument("--job", type=_nonempty, required=True)
    regress.add_argument("--branch", type=_nonempty, required=True)
    regress.add_argument("--merge", type=_merge_sha, required=True)
    regress.add_argument("--n", type=_issue_number, required=True)  # a positive integer
    args = parser.parse_args(argv)
    if args.check == "console-state":
        code, report = console_state(args.port)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "console-first-screen":
        code, report = console_first_screen(args.port, browser=[args.browser] if args.browser else None)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "darwin-shell-path":
        entry = pwd.getpwuid(os.getuid())
        code, report = darwin_shell_path(user=entry.pw_name, home=entry.pw_dir, zsh_bin=args.zsh)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "railway-project-read":
        entry = pwd.getpwuid(os.getuid())
        code, report = railway_project_read(
            user=entry.pw_name, home=os.environ.get("HOME") or entry.pw_dir,
            system_path=args.system_path)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "registry-agreement":
        registries: dict[str, list[dict]] = {}
        for spec in args.registry:
            host, _, path = spec.partition("=")
            entries = _registry_entries(Path(path)) if host and path else None
            if entries is None:
                print(f"verify-checks: tool_error: {spec!r} is not a readable HOST=FILE registry",
                      file=sys.stderr)
                return 2
            registries[host] = entries
        code, report = registry_agreement(registries, args.intentional)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "guard-policy-fleet":
        try:
            code, report = guard_policy_fleet(args.repo_root, args.branch, environ=os.environ,
                                              registry=args.registry)
        except GitError as error:
            print(f"verify-checks: git_error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "deprecations-retired":
        try:
            code, report = deprecations_retired_check(
                args.repo_root, os.environ, watch_adapter=args.watch_adapter,
                red_pending=args.red_pending)
        except ToolError as error:
            print(f"verify-checks: {error.kind}: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check in ("cutover-manifest", "cutover-preflight", "cutover-bundle"):
        try:
            if args.check == "cutover-manifest":
                code, report = cutover_manifest(args.repo_root, args.branch, args.main_ref)
            elif args.check == "cutover-bundle":
                code, report = cutover_bundle(args.repo_root, args.branch)
            else:
                code, report = cutover_preflight(args.repo_root, args.branch, environ=os.environ)
        except GitError as error:
            print(f"verify-checks: git_error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "managed-pre-push-hook":
        git_bin = shutil.which("git", path=os.environ.get("PATH"))
        if git_bin is None:
            print("verify-checks: fixture_error: git not found", file=sys.stderr)
            return 2
        try:
            code, report = managed_pre_push_hook(args.slug, git_bin=git_bin, environ=os.environ)
        except FixtureError as error:
            print(f"verify-checks: fixture_error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    try:
        if args.check == "self-hosted-runner":
            code, report = self_hosted_runner(args.repo, args.runner, args.label)
        elif args.check == "issue-closed":
            code, report = issue_closed(args.repo, args.issue)
        elif args.check == "suite-regressions":
            code, report = suite_regressions(args.repo, args.workflow, args.job, args.branch,
                                             args.merge, args.n)
        else:
            code, report = required_checks(args.repo, args.base, args.since)
    except forge_api.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
