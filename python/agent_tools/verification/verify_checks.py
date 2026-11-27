"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`: an `sh` script committed with mode `100755`. A wrapper runs
from the repository root at the block's commit, so `PYTHONPATH=python` is that commit's source, and
its logic lives in `agent_tools`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`keepalive-end-turn-cap` is documented in `agent_tools.hosts.keepalive_pings`.

`platform-status` runs the installed `resolve-project platform-status` (from `~/.agents/bin`,
prepended to `PATH`) and passes its output and exit through, so a block judges it with `expect`.

`devenv-shell --probe commit|clean [--repo-root R] [--timeout-seconds N]` (`verify_checks.devenv_shell`,
issue 1447) is met when a commit made through the project's devenv shell is signed and leaves its
worktree clean (`commit`), or when a shell leaves a fresh worktree clean (`clean`). It never runs
in R: it makes a shared-object clone of R at R's `HEAD` in a temporary directory, with a git
configuration and object database of its own, and removes that directory afterwards (a removal
that fails is a fixture error), leaving R's HEAD, branch, index, status and configuration
unchanged and every registration of R's worktrees alone. Every git call and every shell
runs under the caller's environment without the eight repository-location names
(`GIT_DIR`, `GIT_WORK_TREE`, ...), so `HOME`, `PATH`, the git configuration and the ssh agent reach
the shell and an inherited redirect cannot point git at the caller's branch. The `commit` probe
runs `devenv shell -- git commit --allow-empty -m probe`; its report names the exit, whether a new
commit exists (HEAD is a commit whose sole parent is the starting commit and whose message is
`probe`, so a shell that moves HEAD elsewhere has made none), whether its header carries a
signature, the porcelain status read before the clone is removed, and the clone's `core.hooksPath`
read outside the shell and, when the commit shell exited 0, inside a second shell run (a
difference is `hooks_changed`). The reason is
the first that applies: `devenv_missing`, `timeout`, `shell_failed`, then for `commit`
`no_commit`, `unsigned`, `dirty`, `hooks_changed`, for `clean` `dirty`; it is null exactly when
met. Each shell runs under a leash in its own process group (`adopt_apply.run_leashed`) bounded by
`--timeout-seconds` (1 to 300, the contract's commit-environment bound): the group is killed with
SIGKILL once the run ends and when the check itself dies, SIGKILL included, so nothing it started
outlives it; a SIGTERM, SIGHUP or SIGINT to the check ends the live shell's group and exits 128
plus the signal after the clone is removed. It exits 0 when met, 1 when
not and 2 on a usage or fixture error.

`console_state(port)` is met when `GET http://127.0.0.1:N/api/state` answers 200 within 5 seconds, not met on
any other status or no answer; it reads only that endpoint, and `owner-services` uses it.

`owner-services --console-port N --proxy-port N --merge SHA [--launchctl PATH] [--lsof PATH]`
(`verify_checks.owner_services`, issue 1290) is met when the owner's services run at boot on a Mac with nobody
logged in at its screen. It only reads, every child's output is captured (the runner publishes the check's output
in an issue comment), and a child that cannot start or times out reads as a failed reading. It reads the owner's
login session (`launchctl print gui/UID` exits 0: a session now; exit 112, 113 or 125: no domain; any other exit,
a timeout or a missing tool is `gui_unread`, not met, so an unreadable domain is never taken for a logout), each
boot daemon `org.nixos.agent-console`,
`org.nixos.claude-cache-proxy`, `org.nixos.sops-nix` and `org.nixos.verify-pending` (`launchctl print
system/LABEL` exits 0: loaded), the console (its state endpoint answers, read by `console_state`) and the cache proxy
(`GET /_proxy/health` is 2xx with a JSON object whose `service` is `cache-proxy`), each owned (its daemon has a
`pid` and that pid is the only listener `lsof` reports on the port, so a hand-run process beside a daemon that
failed to bind does not count), the owner's `~/.ssh/id_ed25519` resolving to a file, and the activation record
of `~/.agents/state/console` (`activation.result` and `activation.log`). The record is read only when it is a
qualifying activation: the result is a JSON object with a 40 hex `commit`, an integer `exit` of 0 and no `error`;
`merge` is an ancestor of that commit (`git merge-base --is-ancestor`); the console's newest `activation.finished` row in
`events.sqlite3` beside them is `ok` for that same commit (the command's exit 0 is not the console's verdict: it
then checks the revision the host runs); the log reads, is no newer than the
result, and the result is unchanged when read again (a new activation unlinks it before it truncates the log).
Otherwise it is `unread`. A read record is `logged_in` when a log line holds `ownerServices: the owner has a login
session`, else `unmarked` when no line holds `ownerServices: the owner has no login session` (the lines the
activation cleanup of `hosts/common/darwin-owner-services.nix` prints), else `domain_lines` when a line holds
`Domain does not support specified action`, else `clean`. The verdict, in this order: a login session now is
`logged_in` (75); an `unread` or `logged_in` record is `not_yet` (75), so no service reading is graded before a
qualifying activation; then a daemon not loaded, a console or proxy that does not answer or is not owned, a
`ssh_key` that does not resolve, or an `unmarked` or `domain_lines` record is `not_met` (1); else `met` (0).
The report is `{"met", "verdict", "daemons", "console", "proxy", "ssh_key", "activation"}` of booleans and the
strings above. It names no path, pid, project or account, since the repository is public. A bad port or a
`--merge` that is not 40 lowercase hex characters is a usage error (2).

`console-failed-start --port N` (`verify_checks.console_failed_start`, issue 1182) reads
`GET http://127.0.0.1:N/api/state` (no answer, a status other than 200 or a body that is not a JSON object
is `unreachable`, exit 75) and applies `failed_start_state` to it: with no open failed-start inbox card it is
`not_yet` (75); otherwise each card must have a running sprint entry whose `now_text` reads the failed start,
whose `ball` is the owner's and whose `retry` is true, and whose `last_reason` is one of the console's plain reasons
(`FAILED_START_REASONS`). It is `met` (0) when every card does and `not_met` (1) with the sorted failed members
(`line`, `ball`, `retry`, `reason`) otherwise. It reads only that endpoint and its report never names a
project, root, title or reason, since the repository is public.

`console-manager-merge --repo OWNER/NAME --since SHA [--log PATH] [--repo-root DIR]`
(`verify_checks.console_manager_merge`, issue 1377) is met when a sprint's manager merged its own sprint's pull
request through the console's permit after the change was activated. It reads the console's event log read-only
(`--log`, default `events.sqlite3` under the console's state directory), the repository at `--repo-root` (default
`.`) and the forge's pull request. The anchor is the earliest `activation.finished` row that is `ok` and whose
`commit` has `--since` as an ancestor or equal (`git merge-base --is-ancestor`: its exit 1 means not an ancestor,
any other failure, a missing object included, is an unreadable git, 2); with none the check is `not_yet` (75). The
window is from that row's time to seven days after it. Any sprint counts, whichever issues it delivered, once a
`sprint.reported` row of it lists at least one issue at or before the judged row (the permit grants only the issues
of the newest report). It is met (0) when, inside the window, a `permit.judged` row of such a sprint with verb
`merge`, decision `allow`, `repo` equal to `--repo` and a `tool_use_id` names a session that a `session.seen` row
called `<project> sprint <that row's sprint id>`, a `permit.landed` row with the same sprint, session, repo, target
and `tool_use_id` (the one tool call that ran, as the client reports it after the call succeeded) is at or after
it, and the forge's `repos/REPO/pulls/PR` is merged at the target's head with a `merged_at` from the judged second
to the landed time. Otherwise it is `not_yet` (75) while the verifier's clock is inside the window and `not_met`
(1) once it is past, whenever the verifier runs. The report is `{"met", "verdict", "pr", "head", "judged_at",
"landed_at", "merged_at", "activated_at"}`, the last six null unless met, and names no project, root, sprint or
session. A malformed `--repo` or `--since` is a usage error (2) before any read; an unreadable log, git or forge
is 2.

`engine-direct-past-implement --since SHA [--runs-root DIR] [--log PATH] [--repo-root DIR]`
(`verify_checks.engine_direct_past_implement`) is met when the first direct-lane engine delivery after activation
entered a step other than `preflight` and `implement` within two days of the activation. The anchor is found as
`console-manager-merge` finds it (none: `not_yet`, 75). The runs are those under `--runs-root` (default the engine's
runs root) whose `run.json` has procedure `direct` and a `started` at or after the anchor; one counts unless its
`results/implement.1.json` is `ineligible`. Only the first such run by `(started, id)` is judged, whatever step it
reached (a run that never entered `implement` is judged too, and no later run stands in for it): a first `outcome_graded` of `implement` that is not `done` is not met (1);
else the first `step_entered` after that grade, at or before anchor plus two days, is met (0), a later one not met;
with none it is not met once the clock is past that bound, else `not_yet`. The report is `{"met", "verdict",
"anchor", "run", "implement", "entered", "at"}`.

`engine-deliver-past-setup --since SHA [--runs-root DIR] [--log PATH] [--repo-root DIR]`
(`verify_checks.engine_deliver_past_setup`) is met when the first direct-lane engine delivery after activation had a
direct child run enter a step within two days of the activation. The anchor is found as `engine-direct-past-implement`
finds it (none: `not_yet`, 75). The roots are the runs under `--runs-root` whose `run.json` has procedure `deliver`, no
`parent` and a `started` at or after the anchor, by `(started, id)`. A root whose first `lane` grade is `standard` or
whose last `stop_reached` is `standard-not-on-engine` or `look-not-on-engine` is skipped; the first other root is
judged and no later root stands in for it. With lane `direct`, the first `step_entered` among the root's direct child
runs (`parent` the root, procedure `direct`), at or before anchor plus two days, is met (0), a later one not met (1);
with none it is not met once the clock is past that bound, else `not_yet`. A root with no lane grade (it stopped in
setup, or is still before the grade) is `not_yet` (75) while it has no stop and the clock is inside the window, else
`lane_unknown` (75), since the record cannot tell a direct issue from a standard one. The report is `{"met",
"verdict", "anchor", "run", "lane", "stop", "child", "entered", "at"}`.

`console-notice-lists --port N --notice PROJECT=N1,N2,... [--notice ...]` (`verify_checks.console_notice_lists`,
issue 1291) reads `GET http://127.0.0.1:N/api/state` (no answer, a status other than 200 or a body that is not a
JSON object is `unreachable`, exit 75) and looks up each wanted project among the entries of `"type": "project"`,
at the top level or inside the `projects` of an entry of `"type": "quiet_group"`. A project is covered when one of
its notices with `owner` true names every wanted issue as `#N` not followed by a digit (`#611` does not cover 61 or
6110); a manager's notice never covers. The report is `{"verdict": "covered" | "missing", "projects": {ID:
{"notice": ID | null}}}`: `covered` (0) when every wanted project is covered, else `missing` (75), since the owner
may not have posted yet. A `--notice` that is not `PROJECT=` and comma-separated positive integers, or a project
given twice, is a usage error (2).

`host-mentions --repo R --phrase P [--phrase P ...] --gone G [--exempt N ...]`
(`verify_checks.host_mentions`, issue 1291) reads every page of `repos/R/issues?state=open&per_page=100`
(pull requests skipped) and reports `{"mentioning", "offenders"}`, both ascending issue numbers. An issue
mentions when any P occurs, ignoring case, in its title or body; it is an offender when it mentions, is
not named by `--exempt` and either its body does not contain G, ignoring case, or an open criterion of
its body (an unchecked task-list item, `- [ ]`, that does not itself contain G) contains a P: a criterion
still naming the host is not answered by a separate paragraph saying it is gone. Exit 0 when there is no offender,
1 otherwise. A page that is not a list, an element that is not an object or a `number` that is not an
integer is a `payload_invalid` forge error (exit 2), as is any other forge error.

`host-prompts --repo R [--repo R ...] --host H` (`verify_checks.host_prompts`, issue 1291) lists the open
issues of each R as `host-mentions` does, pull requests included (the console inbox shows a marker on one), reads one comment listing per open issue (whatever its labels),
and reports `{"host", "live": [{"repo", "issue", "comment", "reason"}]}` sorted by repo, issue and comment.
A live `owner-action` marker counts when its `host` field, or one `+`-separated member of it, is H: a
runner prompt (`verify_answer.is_runner_prompt`) only from an OWNER or MEMBER comment and live over the
markers of those comments, any other owner-action marker only from an OWNER, MEMBER or COLLABORATOR comment
and live over the markers of those, as the console inbox reads each. Exit 0 when nothing is live, 1
otherwise, 2 on a forge error.
"""
from __future__ import annotations

import argparse
import functools
import http.client
import json
import os
import pwd
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.project_contract import agent_platform
from agent_tools.project_contract.adopt_apply import run_leashed
from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.claims import forge_markers, forge_owner_action
from agent_tools.system import forge_api
from agent_tools.verification import verify_answer, verify_issues

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
                 merged_at: datetime | None, passed: Sequence[str] = ("success",)) -> bool:
    """Met by a run concluding in `passed`, or for an unbound check a latest successful status, each
    completed no later than `merged_at` (no time bound when it is None)."""
    context, app_id = requirement
    for run in runs:
        if not isinstance(run, dict) or run.get("name") != context:
            continue
        app = run.get("app")
        if app_id is not None and not (isinstance(app, dict) and app.get("id") == app_id):
            continue
        if (run.get("status") == "completed" and run.get("conclusion") in passed
                and (merged_at is None
                     or _forge_time(run.get("completed_at"), "check run completed_at") <= merged_at)):
            return True
    if app_id is not None:
        return False  # a commit status names no app, so it cannot satisfy a bound check
    latest = None
    for status in statuses:
        if not isinstance(status, dict) or status.get("context") != context:
            continue
        updated = _forge_time(status.get("updated_at"), "status updated_at")
        if (merged_at is None or updated <= merged_at) and (latest is None or updated > latest[0]):
            latest = (updated, status.get("state"))
    return latest is not None and latest[1] == "success"


_RUN_PASSED = ("success", "neutral", "skipped")
_STATUS_STATES = ("success", "failure", "error", "pending")


def _ruleset_checks(repo: str, base: str) -> set[Requirement]:
    """The checks the active rulesets of `base` require, `integration_id` being the app binding
    (absent or null is any app); classic branch protection is read apart, by `_required_checks`."""
    pages = forge_api.api_pages(f"repos/{repo}/rules/branches/{base}?per_page=100")
    if not all(isinstance(page, list) for page in pages):
        raise _invalid("rules page is not a list")
    found: set[Requirement] = set()
    for rule in (rule for page in pages for rule in page):
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        listed = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
        for entry in listed or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("context"), str):
                continue
            app_id = entry.get("integration_id")
            if app_id is not None and not _is_int(app_id):
                raise _invalid("ruleset required check integration_id is not an integer or null")
            found.add((entry["context"], app_id))
    return found


def _stamp(moment: datetime) -> str:
    """An RFC 3339 UTC string of `moment`, keeping any fraction of a second."""
    utc = moment.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return utc.strftime(_STAMP)


def pr_green_state(repo: str, pr: int) -> tuple[str, dict]:
    """The one green rule for a pull request's head: `failed`, else `pending`, else `green`.

    Failed: a completed check run concluded outside success, neutral and skipped, or the latest
    status of a context is failure or error. Pending: a run not completed, the latest status of a
    context pending, a required check not met at the head (no time bound; classic protection and
    the active rulesets both count, and a neutral or skipped run meets it), or no run and no status
    at all. Green otherwise, at the latest run completion or latest status update."""
    pull = forge_api.api_get(f"repos/{repo}/pulls/{pr}")
    head = pull.get("head") if isinstance(pull, dict) else None
    base = pull.get("base") if isinstance(pull, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    if not isinstance(sha, str) or not sha or not isinstance(ref, str) or not ref:
        raise _invalid(f"pull request {pr} has no head sha and base ref")
    required = {*_required_checks(repo, ref), *_ruleset_checks(repo, ref)}
    runs = _counted_pages(forge_api.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    status_pages = forge_api.api_pages(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    if not all(isinstance(page, list) for page in status_pages):
        raise _invalid("status page is not a list")
    statuses = [entry for page in status_pages for entry in page]
    failing: set[str] = set()
    pending: set[str] = set()
    moments: list[datetime] = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("name"), str):
            raise _invalid("check run has no name")
        if run.get("status") != "completed":
            pending.add(run["name"])
        elif run.get("conclusion") not in _RUN_PASSED:
            failing.add(run["name"])
        else:
            moments.append(_forge_time(run.get("completed_at"), "check run completed_at"))
    latest: dict[str, tuple[datetime, str]] = {}
    for entry in statuses:
        if (not isinstance(entry, dict) or not isinstance(entry.get("context"), str)
                or entry.get("state") not in _STATUS_STATES):
            raise _invalid("status has no context and state")
        updated = _forge_time(entry.get("updated_at"), "status updated_at")
        if entry["context"] not in latest or updated > latest[entry["context"]][0]:
            latest[entry["context"]] = (updated, entry["state"])
    for context, (updated, state) in latest.items():
        moments.append(updated)
        if state in ("failure", "error"):
            failing.add(context)
        elif state == "pending":
            pending.add(context)
    missing = sorted({r[0] for r in required if not _context_met(r, runs, statuses, None, _RUN_PASSED)})
    if not runs and not statuses:
        pending.add("no check run or status")
    state = "failed" if failing else "pending" if pending or missing else "green"
    report = {"pr": pr, "head": sha, "base": ref,
              "green_at": _stamp(max(moments)) if state == "green" else None,
              "failing": sorted(failing), "pending": sorted(pending), "missing": missing}
    return state, report


def _open_issues(repo: str, pulls: bool = False) -> list[dict]:
    """Every open issue of `repo` in listing order, pull requests skipped unless `pulls`, the shape checked."""
    found = []
    for page in forge_api.api_pages(f"repos/{repo}/issues?state=open&per_page=100"):
        if not isinstance(page, list):
            raise _invalid("issue page is not a list")
        for issue in page:
            if not isinstance(issue, dict):
                raise _invalid("issue is not an object")
            if "pull_request" in issue and not pulls:
                continue
            number = issue.get("number")
            if isinstance(number, bool) or not isinstance(number, int):
                raise _invalid("issue number is not an integer")
            found.append(issue)
    return found


OPEN_CRITERION = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[ \]")


def host_mentions(repo: str, phrases: Sequence[str], gone: str, exempt: Sequence[int]) -> tuple[int, dict]:
    """Met when every open issue naming a phrase is exempt or carries the `gone` line in its body and has
    no open criterion (an unchecked task-list item other than the `gone` line) naming a phrase."""
    needles = [p.lower() for p in phrases]
    mentioning, offenders = [], []
    for issue in _open_issues(repo):
        title, body = issue.get("title") or "", issue.get("body") or ""
        text = f"{title}\n{body}".lower()
        if not any(needle in text for needle in needles):
            continue
        mentioning.append(issue["number"])
        criteria = [line.lower() for line in body.splitlines()
                    if OPEN_CRITERION.match(line) and gone.lower() not in line.lower()]
        if issue["number"] not in exempt and (
                gone.lower() not in body.lower() or any(n in line for line in criteria for n in needles)):
            offenders.append(issue["number"])
    return (0 if not offenders else 1), {"mentioning": sorted(mentioning), "offenders": sorted(offenders)}


def _names_host(marker: forge_markers.Marker, host: str) -> bool:
    named = marker.fields.get("host", "")
    return named == host or host in named.split("+")


def host_prompts(repos: Sequence[str], host: str) -> tuple[int, dict]:
    """Met when no open issue holds a live owner-action prompt that names `host`."""
    live = []
    for repo in repos:
        for issue in _open_issues(repo, pulls=True):
            comments = forge_markers.list_comments(repo, issue["number"])

            def read(trusted):
                parsed = (forge_markers.parse(c) for c in comments if c.get("author_association") in trusted)
                return [m for m in parsed if m is not None]
            runner = read(verify_issues.TRUSTED)
            forge = read(forge_owner_action.TRUSTED)
            for markers, wanted in ((runner, True), (forge, False)):
                for marker in markers:
                    if (marker.kind == forge_owner_action.KIND
                            and verify_answer.is_runner_prompt(marker) == wanted
                            and _names_host(marker, host)
                            and forge_markers.is_live(marker, markers)):
                        live.append({"repo": repo, "issue": issue["number"], "comment": marker.comment_id,
                                     "reason": marker.fields.get("reason", "")})
    live.sort(key=lambda row: (row["repo"], row["issue"], row["comment"]))
    return (0 if not live else 1), {"host": host, "live": live}


class FixtureError(Exception):
    """The check could not build or drive its fixture; the caller exits 2."""


DEVENV_SHELL_TIMEOUT_SECONDS = 300
DEVENV_SHELL_REPOSITORY_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
DEVENV_SHELL_TERMINATION = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
DEVENV_SHELL_TAIL_LINES = 5
COMMIT_PROBE_MESSAGE = "probe"


def _devenv_run(argv: list[str], cwd: Path, env: Mapping[str, str], stdout: Path, log: Path,
                timeout: float) -> tuple[int | None, float]:
    """One leashed shell run: (exit or None on timeout, elapsed seconds).

    The leash ends the shell's whole process tree when the run ends and when this process dies."""
    started = time.monotonic()
    try:
        with open(stdout, "ab") as out, open(log, "ab") as err:
            try:
                code: int | None = run_leashed(argv, cwd=str(cwd), env=dict(env), stdout=out,
                                               stderr=err, timeout=timeout)
            except subprocess.TimeoutExpired:
                code = None
    except OSError as error:
        raise FixtureError(f"{argv[0]}: {type(error).__name__}") from error
    return code, round(time.monotonic() - started, 1)


def _tail(log: Path) -> list[str]:
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
    return lines[-DEVENV_SHELL_TAIL_LINES:]


def _config_hooks_path(worktree: Path, env: Mapping[str, str]) -> str | None:
    done = _git(worktree, "config", "--get", "core.hooksPath", environ=env)
    return done.stdout.strip() or None if done.returncode == 0 else None


def devenv_shell(probe: str, repo_root: Path, *, devenv_bin: str | None,
                 environ: Mapping[str, str], timeout: float) -> tuple[int, dict]:
    """Met when a commit through the devenv shell is signed and clean, or a shell leaves a clean tree.

    Raises FixtureError when the scratch clone cannot be made, driven or removed, GitError when git fails."""
    commit = probe == "commit"
    report: dict = {"probe": probe, "exit": None, "elapsed_seconds": 0.0}
    if commit:
        report.update(new_commit=False, signed=False)
    report["status"] = []
    if commit:
        report["hooks_path"] = {"outside": None, "inside": None}
    report.update(output_tail=[], reason=None, met=False)
    if devenv_bin is None:
        report["reason"] = "devenv_missing"
        return 1, report
    env = {key: value for key, value in environ.items() if key not in DEVENV_SHELL_REPOSITORY_ENV}

    def terminate(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = {signum: signal.signal(signum, terminate) for signum in DEVENV_SHELL_TERMINATION}
    leftover: OSError | None = None
    try:
        try:
            tmp = Path(tempfile.mkdtemp(prefix="verify-devenv-shell-"))
        except OSError as error:
            raise FixtureError(f"mkdtemp: {type(error).__name__}") from error
        worktree = tmp / "wt"
        try:
            sha = _git_ok(repo_root, "rev-parse", "HEAD", environ=env).strip()
            # A clone of its own: its configuration and object database are not the caller's, so
            # nothing the shell writes (core.hooksPath included) outlives the scratch directory.
            for where, args in (
                    (repo_root, ("clone", "--quiet", "--shared", "--no-checkout",
                                 str(repo_root.resolve()), str(worktree))),
                    (worktree, ("checkout", "--quiet", "--detach", sha))):
                made = _git(where, "-c", "core.hooksPath=/dev/null", *args, environ=env)
                if made.returncode != 0:
                    detail = made.stderr.strip().splitlines()
                    raise FixtureError(
                        f"scratch clone failed: {detail[0] if detail else made.returncode}")
            log = tmp / "shell.log"
            outside = _config_hooks_path(worktree, env) if commit else None
            argv = ([devenv_bin, "shell", "--", "git", "commit", "--allow-empty", "-m", COMMIT_PROBE_MESSAGE]
                    if commit else [devenv_bin, "shell", "--", "true"])
            code, report["elapsed_seconds"] = _devenv_run(argv, worktree, env, log, log, timeout)
            report["exit"] = code
            report["status"] = _git_ok(worktree, "status", "--porcelain",
                                       environ=env).splitlines()
            report["output_tail"] = _tail(log)
            hooks_changed = False
            if commit:
                head = _git_ok(worktree, "rev-parse", "HEAD", environ=env).strip()
                parents = _git_ok(worktree, "rev-list", "--parents", "-n", "1", "HEAD",
                                  environ=env).split()[1:]
                message = _git_ok(worktree, "show", "-s", "--format=%B", "HEAD",
                                  environ=env).strip()
                report["new_commit"] = (head != sha and parents == [sha]
                                        and message == COMMIT_PROBE_MESSAGE)
                if report["new_commit"]:
                    header = _git_ok(worktree, "cat-file", "commit", "HEAD",
                                     environ=env).split("\n\n", 1)[0]
                    report["signed"] = any(line.startswith(("gpgsig ", "gpgsig-sha256 "))
                                           for line in header.splitlines())
                report["hooks_path"]["outside"] = outside
                if code == 0:
                    hooks_out = tmp / "hooks.out"
                    inside_code, _ = _devenv_run(
                        [devenv_bin, "shell", "--", "git", "config", "--get", "core.hooksPath"],
                        worktree, env, hooks_out, log, timeout)
                    lines = [line for line in hooks_out.read_text(
                        encoding="utf-8", errors="replace").splitlines() if line.strip()]
                    report["hooks_path"]["inside"] = lines[-1] if lines else None
                    hooks_changed = (inside_code not in (0, 1)
                                     or report["hooks_path"]["inside"] != outside)
        finally:
            try:
                shutil.rmtree(tmp)
            except OSError as error:
                leftover = error
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    if leftover is not None:
        raise FixtureError(f"scratch clone not removed: {type(leftover).__name__}")
    if report["exit"] is None:
        report["reason"] = "timeout"
    elif report["exit"] != 0:
        report["reason"] = "shell_failed"
    elif commit and not report["new_commit"]:
        report["reason"] = "no_commit"
    elif commit and not report["signed"]:
        report["reason"] = "unsigned"
    elif report["status"]:
        report["reason"] = "dirty"
    elif hooks_changed:
        report["reason"] = "hooks_changed"
    report["met"] = report["reason"] is None
    return (0 if report["met"] else 1), report


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


class ToolError(Exception):
    """The check could not judge: `kind` is the stderr label, the caller exits 2."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


def _repo(value: str) -> str:
    if not REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _nonempty(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")
    return value


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


OWNER_SERVICE_LABELS = ("org.nixos.agent-console", "org.nixos.claude-cache-proxy",
                        "org.nixos.sops-nix", "org.nixos.verify-pending")
DOMAIN_LINE = "Domain does not support specified action"
NO_SESSION_LINE = "ownerServices: the owner has no login session"
SESSION_LINE = "ownerServices: the owner has a login session"
_JOB_PID = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)
# `launchctl print gui/UID` exits with one of these when the domain is not there (no session): 112 no such
# domain, 113 no such service, 125 "Domain does not support specified action". Any other exit is unreadable.
NO_DOMAIN_EXITS = (112, 113, 125)


def _finished_outcome(store: Path) -> tuple[str, bool] | None:
    """The console's newest `activation.finished` row as (commit, ok), or None when it cannot be read."""
    try:
        connection = sqlite3.connect(f"{store.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError):
        return None
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute("SELECT payload FROM events WHERE kind = 'activation.finished' "
                                 "ORDER BY seq DESC LIMIT 1").fetchone()
        payload = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        connection.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("commit"), str):
        return None
    return payload["commit"], payload.get("ok") is True


def _activation_state(home: Path, merge: str, repo_root: Path, run) -> str:
    """Issue 1290: `unread` unless a qualifying activation is on record, else what its log says."""
    state = home / ".agents" / "state" / "console"
    result, log = state / "activation.result", state / "activation.log"
    try:
        first = result.read_bytes()
        record = json.loads(first)
        result_ns = result.stat().st_mtime_ns
    except (OSError, ValueError):
        return "unread"
    if not isinstance(record, dict):
        return "unread"
    commit, code = record.get("commit"), record.get("exit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return "unread"
    if isinstance(code, bool) or not isinstance(code, int) or code != 0 or "error" in record:
        return "unread"
    outcome = _finished_outcome(state / "events.sqlite3")
    if outcome != (commit, True):
        return "unread"
    try:
        ancestor = run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", merge, commit])
    except (OSError, subprocess.TimeoutExpired):
        return "unread"
    if ancestor.returncode != 0:
        return "unread"
    try:
        if not log.is_file():
            return "unread"
        text = log.read_text(encoding="utf-8", errors="replace")
        if log.stat().st_mtime_ns > result_ns:
            return "unread"
        if result.read_bytes() != first:
            return "unread"
    except OSError:
        return "unread"
    lines = text.splitlines()
    if any(SESSION_LINE in line for line in lines):
        return "logged_in"
    if not any(NO_SESSION_LINE in line for line in lines):
        return "unmarked"
    if any(DOMAIN_LINE in line for line in lines):
        return "domain_lines"
    return "clean"


MANAGER_MERGE_WINDOW = timedelta(days=7)
_MANAGER_MERGE_EMPTY = {"pr": None, "head": None, "judged_at": None, "landed_at": None,
                        "merged_at": None, "activated_at": None}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log_rows(store: Path, kinds: Sequence[str]) -> list[tuple[datetime, str, dict]]:
    """The (time, kind, payload) of every row of `kinds` in sequence order; rows that do not parse are dropped."""
    try:
        connection = sqlite3.connect(f"{store.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError) as error:
        raise ToolError("log_unreadable", type(error).__name__) from error
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            f"SELECT at, kind, payload FROM events WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY seq",
            tuple(kinds)).fetchall()
    except sqlite3.Error as error:
        raise ToolError("log_unreadable", type(error).__name__) from error
    finally:
        connection.close()
    found = []
    for at, kind, text in rows:
        try:
            payload = json.loads(text)
            when = parse_rfc3339_utc(at)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            found.append((when, kind, payload))
    return found


def _manager_merge_anchor(rows, since: str, repo_root: Path) -> datetime | None:
    """The time of the earliest ok `activation.finished` whose commit has `since` as an ancestor, or None."""
    for when, kind, payload in rows:
        commit = payload.get("commit")
        if (kind != "activation.finished" or payload.get("ok") is not True or not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}", commit)):
            continue
        done = _git(repo_root, "merge-base", "--is-ancestor", since, commit)
        if done.returncode == 0:
            return when
        if done.returncode != 1:
            raise GitError(f"git merge-base: exit {done.returncode}")
    return None


def _reported_sprints(rows) -> dict[str, datetime]:
    """Each sprint id with the time of its first `sprint.reported` row that lists an issue."""
    found: dict[str, datetime] = {}
    for when, kind, payload in rows:
        report = payload.get("report")
        listed = report.get("issues") if isinstance(report, dict) else None
        if (kind == "sprint.reported" and isinstance(payload.get("sprint_id"), str)
                and isinstance(listed, list)
                and any(isinstance(entry, dict) and _is_int(entry.get("issue")) for entry in listed)):
            found.setdefault(payload["sprint_id"], when)
    return found


def console_manager_merge(repo: str, since: str, *, log: Path | None = None,
                          repo_root: Path = Path(".")) -> tuple[int, dict]:
    """Issue 1377: a manager merged its own sprint's pull request through the console's permit after activation."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    rows = _log_rows(store, ("activation.finished", "session.seen", "sprint.reported", "permit.judged",
                             "permit.landed"))
    start = _manager_merge_anchor(rows, since, repo_root)
    if start is None:
        return 75, {"met": False, "verdict": "not_yet", **_MANAGER_MERGE_EMPTY}
    end = start + MANAGER_MERGE_WINDOW
    named = {(payload.get("session_id"), payload.get("name"))
             for _, kind, payload in rows if kind == "session.seen"}
    reported = _reported_sprints(rows)

    def target_of(payload):
        target = payload.get("target")
        if (isinstance(target, dict) and _is_int(target.get("pr")) and isinstance(target.get("head"), str)):
            return target["pr"], target["head"]
        return None

    def in_window(when):
        return start <= when <= end

    landings = [(when, payload, target_of(payload)) for when, kind, payload in rows
                if kind == "permit.landed" and in_window(when)]
    for judged_at, kind, judged in rows:
        sprint, session, target = judged.get("sprint_id"), judged.get("session_id"), target_of(judged)
        call = judged.get("tool_use_id")
        if (kind != "permit.judged" or not in_window(judged_at) or judged.get("verb") != "merge"
                or judged.get("decision") != "allow" or judged.get("repo") != repo or target is None
                or not isinstance(sprint, str) or not isinstance(session, str)
                or sprint not in reported or reported[sprint] > judged_at
                or not isinstance(call, str) or not call
                or not any(seen == session and isinstance(name, str) and name.endswith(f" sprint {sprint}")
                           and len(name) > len(f" sprint {sprint}") for seen, name in named)):
            continue
        for landed_at, landed, landed_target in landings:
            if (landed_at < judged_at or landed_target != target or landed.get("sprint_id") != sprint
                    or landed.get("session_id") != session or landed.get("repo") != repo
                    or landed.get("tool_use_id") != call):
                continue
            pull = forge_api.api_get(f"repos/{repo}/pulls/{target[0]}")
            head = pull.get("head") if isinstance(pull, dict) else None
            if (not isinstance(pull, dict) or pull.get("merged") is not True or not isinstance(head, dict)
                    or head.get("sha") != target[1]):
                continue
            merged_at = _forge_time(pull.get("merged_at"), "merged_at")
            # The forge reports whole seconds, the log microseconds: compare at the forge's resolution.
            if judged_at.replace(microsecond=0) <= merged_at <= landed_at:
                return 0, {"met": True, "verdict": "met", "pr": target[0], "head": target[1],
                           "judged_at": judged_at.isoformat(), "landed_at": landed_at.isoformat(),
                           "merged_at": merged_at.isoformat(), "activated_at": start.isoformat()}
    if _utcnow() <= end:
        return 75, {"met": False, "verdict": "not_yet", **_MANAGER_MERGE_EMPTY}
    return 1, {"met": False, "verdict": "not_met", **_MANAGER_MERGE_EMPTY}


PAST_IMPLEMENT_WINDOW = timedelta(days=2)


def _past_implement_events(run_dir: Path) -> list[tuple[str, str, datetime | None, dict]]:
    """The (event, step, time, whole line) of each parsing line of a run's `events.jsonl`, in file order."""
    found = []
    try:
        text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return found
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            continue
        try:
            at = parse_rfc3339_utc(event.get("at"))
        except ValueError:
            at = None
        found.append((event["event"], event.get("step"), at, event))
    return found


def _past_implement_runs(runs_root: Path, anchor: datetime) -> list[tuple[datetime, str, Path]]:
    """The (started, id, directory) of each direct run started at or after `anchor`, earliest first."""
    runs = []
    try:
        names = sorted(path for path in runs_root.iterdir() if path.is_dir())
    except OSError:
        return runs
    for run_dir in names:
        try:
            document = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            started = parse_rfc3339_utc(document["started"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(document, dict) and document.get("procedure") == "direct" and started >= anchor:
            runs.append((started, run_dir.name, run_dir))
    return sorted(runs)


def _implement_ineligible(run_dir: Path) -> bool:
    try:
        reply = json.loads((run_dir / "results" / "implement.1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(reply, dict) and reply.get("ineligible") is True


def past_implement_verdict(runs_root: Path, anchor: datetime, now: datetime) -> tuple[int, dict]:
    """The first direct engine run from `anchor` on, ineligible ones aside, got past `implement` in time."""
    report = {"met": False, "verdict": "not_yet", "anchor": _stamp(anchor), "run": None,
              "implement": None, "entered": None, "at": None}
    for started, run_id, run_dir in _past_implement_runs(runs_root, anchor):
        events = _past_implement_events(run_dir)
        if _implement_ineligible(run_dir):
            continue
        report["run"] = run_id
        grade = next((index for index, (kind, step, _, _) in enumerate(events)
                      if kind == "outcome_graded" and step == "implement"), None)
        graded = events[grade][3].get("outcome") if grade is not None else None
        report["implement"] = graded if isinstance(graded, str) else None
        if graded is not None and graded != "done":
            return 1, {**report, "verdict": "not_met"}
        end = anchor + PAST_IMPLEMENT_WINDOW
        for kind, step, at, _ in (events[grade:] if grade is not None else ()):
            if kind == "step_entered" and step not in ("preflight", "implement"):
                report.update(entered=step, at=None if at is None else _stamp(at))
                if at is not None and at <= end:
                    return 0, {**report, "met": True, "verdict": "met"}
                return 1, {**report, "verdict": "not_met"}
        if now > end:
            return 1, {**report, "verdict": "not_met"}
        return 75, report
    return 75, report


def engine_direct_past_implement(since: str, *, runs_root: Path | None = None, log: Path | None = None,
                                 repo_root: Path = Path("."), now: datetime | None = None) -> tuple[int, dict]:
    """The first direct engine delivery after activation of `since` got past `implement` within two days."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    anchor = _manager_merge_anchor(_log_rows(store, ("activation.finished",)), since, repo_root)
    if anchor is None:
        return 75, {"met": False, "verdict": "not_yet", "anchor": None, "run": None,
                    "implement": None, "entered": None, "at": None}
    return past_implement_verdict(runs_root if runs_root is not None else agent_platform.engine_runs_root(), anchor,
                                  now if now is not None else _utcnow())


NOT_DIRECT_STOPS = ("standard-not-on-engine", "look-not-on-engine")


def _engine_runs(runs_root: Path) -> list[tuple[datetime, str, Path, dict]]:
    """The (started, id, directory, run.json) of each run under `runs_root` that parses, earliest first."""
    runs = []
    try:
        names = sorted(path for path in runs_root.iterdir() if path.is_dir())
    except OSError:
        return runs
    for run_dir in names:
        try:
            document = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            started = parse_rfc3339_utc(document["started"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(document, dict):
            runs.append((started, run_dir.name, run_dir, document))
    return sorted(runs, key=lambda run: run[:2])


def _root_lane_and_stop(events) -> tuple[str | None, str | None]:
    """The outcome of a run's first `lane` grade and the `stop` of its last `stop_reached`, each None if absent."""
    lane = next((event.get("outcome") for kind, step, _, event in events
                 if kind == "outcome_graded" and step == "lane"), None)
    stops = [event.get("stop") for kind, _, _, event in events if kind == "stop_reached"]
    stop = stops[-1] if stops else None
    return (lane if isinstance(lane, str) else None), (stop if isinstance(stop, str) else None)


def past_setup_verdict(runs_root: Path, anchor: datetime, now: datetime) -> tuple[int, dict]:
    """The first direct-lane delivery from `anchor` on had a direct child run enter a step in time."""
    report = {"met": False, "verdict": "not_yet", "anchor": _stamp(anchor), "run": None, "lane": None,
              "stop": None, "child": None, "entered": None, "at": None}
    end = anchor + PAST_IMPLEMENT_WINDOW
    runs = _engine_runs(runs_root)
    for started, run_id, run_dir, document in runs:
        if document.get("procedure") != "deliver" or "parent" in document or started < anchor:
            continue
        lane, stop = _root_lane_and_stop(_past_implement_events(run_dir))
        if lane == "standard" or stop in NOT_DIRECT_STOPS:
            continue
        report.update(run=run_id, lane=lane, stop=stop)
        if lane != "direct":
            if stop is None and now <= end:
                return 75, report
            return 75, {**report, "verdict": "lane_unknown"}
        for _, child_id, child_dir, child in runs:
            if child.get("parent") != run_id or child.get("procedure") != "direct":
                continue
            for kind, step, at, _ in _past_implement_events(child_dir):
                if kind == "step_entered":
                    report.update(child=child_id, entered=step, at=None if at is None else _stamp(at))
                    if at is not None and at <= end:
                        return 0, {**report, "met": True, "verdict": "met"}
                    return 1, {**report, "verdict": "not_met"}
        if now > end:
            return 1, {**report, "verdict": "not_met"}
        return 75, report
    return 75, report


def engine_deliver_past_setup(since: str, *, runs_root: Path | None = None, log: Path | None = None,
                              repo_root: Path = Path("."), now: datetime | None = None) -> tuple[int, dict]:
    """The first direct engine delivery after activation of `since` got past setup within two days."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    anchor = _manager_merge_anchor(_log_rows(store, ("activation.finished",)), since, repo_root)
    if anchor is None:
        return 75, {"met": False, "verdict": "not_yet", "anchor": None, "run": None, "lane": None,
                    "stop": None, "child": None, "entered": None, "at": None}
    return past_setup_verdict(runs_root if runs_root is not None else agent_platform.engine_runs_root(), anchor,
                              now if now is not None else _utcnow())


def _proxy_answers(port: int, timeout: float) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/_proxy/health")
        response = connection.getresponse()
        body = response.read()
        if not 200 <= response.status < 300:
            return False
        payload = json.loads(body)
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()
    return isinstance(payload, dict) and payload.get("service") == "cache-proxy"


def owner_services(*, console_port: int, proxy_port: int, merge: str, home: Path, uid: int,
                   repo_root: Path, launchctl: str = "/bin/launchctl", lsof: str = "/usr/sbin/lsof",
                   run=None, timeout: float = 5.0) -> tuple[int, dict]:
    """Issue 1290: the owner's boot services run with nobody logged in at the screen."""
    if run is None:
        run = functools.partial(subprocess.run, capture_output=True, text=True,
                                timeout=timeout, check=False)

    def read(argv):
        try:
            return run(argv)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def loaded(label):
        done = read([launchctl, "print", f"system/{label}"])
        if done is None or done.returncode != 0:
            return False, None
        match = _JOB_PID.search(done.stdout or "")
        return True, int(match.group(1)) if match else None

    def listeners(port):
        done = read([lsof, "-nP", "-a", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
        if done is None or done.returncode != 0:
            return set()
        return {int(line[1:]) for line in (done.stdout or "").splitlines()
                if re.fullmatch(r"p\d+", line)}

    def owned(pid, port):
        return pid is not None and listeners(port) == {pid}

    gui = read([launchctl, "print", f"gui/{uid}"])
    if gui is None or (gui.returncode != 0 and gui.returncode not in NO_DOMAIN_EXITS):
        return 1, {"met": False, "verdict": "gui_unread"}
    session = gui.returncode == 0
    jobs = {label: loaded(label) for label in OWNER_SERVICE_LABELS}
    console_pid = jobs["org.nixos.agent-console"][1]
    proxy_pid = jobs["org.nixos.claude-cache-proxy"][1]
    console = {"answers": console_state(console_port, timeout=timeout)[0] == 0,
               "owned": owned(console_pid, console_port)}
    proxy = {"answers": _proxy_answers(proxy_port, timeout), "owned": owned(proxy_pid, proxy_port)}
    try:
        ssh_key = (home / ".ssh/id_ed25519").resolve(strict=True).is_file()
    except (OSError, RuntimeError):
        ssh_key = False
    activation = _activation_state(home, merge, repo_root, run)
    daemons = {label: jobs[label][0] for label in OWNER_SERVICE_LABELS}
    if session:
        code, verdict = 75, "logged_in"
    elif activation in ("unread", "logged_in"):
        code, verdict = 75, "not_yet"
    elif (not all(daemons.values()) or not all(console.values()) or not all(proxy.values())
          or not ssh_key or activation in ("unmarked", "domain_lines")):
        code, verdict = 1, "not_met"
    else:
        code, verdict = 0, "met"
    return code, {"met": code == 0, "verdict": verdict, "daemons": daemons, "console": console,
                  "proxy": proxy, "ssh_key": ssh_key, "activation": activation}


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


FAILED_START_REASON = "failed_start"
FAILED_START_NOW = "waiting for you: the manager failed to start"
# The console's `manager.PLAIN_TEXTS`, copied because this area may not import the console's.
FAILED_START_REASONS = (
    "this account does not trust the project's folder",
    "a program the manager needs is missing on this host",
    "the launch did not answer in time",
    "the project's folder is missing",
    "the console could not write the manager's settings",
    "the sprint's secret is missing",
    "the client refused to start the manager",
    "managers are not available on this host yet")


def failed_start_state(view: object) -> tuple[int, dict]:
    """Issue 1182: every open failed-start card's sprint line reads the failed start, 0 met, 1 not met, 75 not yet."""
    opened = view.get("inbox", {}).get("open") if isinstance(view, dict) and isinstance(view.get("inbox"), dict) else None
    cards = [item for item in opened if isinstance(item, dict) and item.get("reason") == FAILED_START_REASON] \
        if isinstance(opened, list) else []
    if not cards:
        return 75, {"verdict": "not_yet", "cards": 0}
    running = {sprint["sprint_id"]: sprint for sprint in _sprint_entries(view)
               if sprint.get("ended_at") is None and isinstance(sprint.get("sprint_id"), str)}
    problems: set[str] = set()
    for card in cards:
        card_sprint = card.get("sprint_id")
        sprint = running.get(card_sprint) if isinstance(card_sprint, str) else None
        if sprint is None or sprint.get("now_text") != FAILED_START_NOW:
            problems.add("line")
        if sprint is not None:
            if sprint.get("ball") != "owner":
                problems.add("ball")
            if sprint.get("retry") is not True:
                problems.add("retry")
        if card.get("last_reason") not in FAILED_START_REASONS:
            problems.add("reason")
    if not problems:
        return 0, {"verdict": "met", "cards": len(cards)}
    return 1, {"verdict": "not_met", "cards": len(cards), "problems": sorted(problems)}


def console_failed_start(port: int, *, timeout: float = 5.0) -> tuple[int, dict]:
    """Issue 1182: `failed_start_state` of the live console's view; an unreachable console is not yet (75)."""
    unreachable = 75, {"verdict": "unreachable", "cards": 0}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        status, body = response.status, response.read()
    except (OSError, http.client.HTTPException):
        return unreachable
    finally:
        connection.close()
    if status != 200:
        return unreachable
    try:
        view = json.loads(body)
    except ValueError:
        return unreachable
    return failed_start_state(view) if isinstance(view, dict) else unreachable


def _notice_names_all(text: object, numbers: Sequence[int]) -> bool:
    """Issue 1291: the text names every number as `#N` not followed by a digit."""
    return isinstance(text, str) and all(re.search(rf"#{number}(?!\d)", text) for number in numbers)


def _view_projects(view: dict) -> Iterator[dict]:
    """Issue 1291: the project entries of the view, at the top level or inside a quiet group."""
    entries = view.get("entries")
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "project":
            yield entry
        elif entry.get("type") == "quiet_group":
            members = entry.get("projects")
            for member in members if isinstance(members, list) else ():
                if isinstance(member, dict) and member.get("type") == "project":
                    yield member


def console_notice_lists(port: int, wanted: Mapping[str, Sequence[int]], *,
                         timeout: float = 5.0) -> tuple[int, dict]:
    """Issue 1291: each wanted project has one owner notice naming all its issues, 0 covered, 75 missing or unreachable."""
    unreachable = 75, {"verdict": "unreachable"}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        status, body = response.status, response.read()
    except (OSError, http.client.HTTPException):
        return unreachable
    finally:
        connection.close()
    if status != 200:
        return unreachable
    try:
        view = json.loads(body)
    except ValueError:
        return unreachable
    if not isinstance(view, dict):
        return unreachable
    notices: dict[object, list[dict]] = {}
    for entry in _view_projects(view):
        listed = entry.get("notices")
        if isinstance(listed, list):
            notices.setdefault(entry.get("project_id"), []).extend(
                item for item in listed if isinstance(item, dict))
    projects: dict[str, dict] = {}
    for project, numbers in wanted.items():
        covering = next((item.get("id") for item in notices.get(project, ())
                         if item.get("owner") is True and _notice_names_all(item.get("text"), numbers)), None)
        projects[project] = {"notice": covering}
    covered = all(report["notice"] is not None for report in projects.values())
    return (0 if covered else 75), {"verdict": "covered" if covered else "missing", "projects": projects}


"""Issue 1031: run the browser with the pipes on descriptors 3 and 4. dash's `3<&10` is "Bad fd number", so no shell does it."""


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


def _notice_spec(value: str) -> tuple[str, tuple[int, ...]]:
    project, separator, numbers = value.partition("=")
    parts = numbers.split(",")
    if not (project and separator and all(part.isascii() and part.isdigit() and int(part) >= 1 for part in parts)):
        raise argparse.ArgumentTypeError("must be PROJECT=N1,N2,... with positive integers")
    return project, tuple(int(part) for part in parts)


def _merge_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError("must be a 40-character lowercase hex sha")
    return value


def _devenv_timeout(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        seconds = 0
    if not 1 <= seconds <= DEVENV_SHELL_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be an integer from 1 to {DEVENV_SHELL_TIMEOUT_SECONDS}")
    return seconds


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-checks")
    checks = parser.add_subparsers(dest="check", required=True)
    devenv = checks.add_parser(
        "devenv-shell",
        help="issue 1447: a commit through the devenv shell is signed and leaves a clean worktree")
    devenv.add_argument("--probe", choices=("commit", "clean"), required=True)
    devenv.add_argument("--repo-root", type=Path, default=Path("."))
    devenv.add_argument("--timeout-seconds", type=_devenv_timeout,
                        default=DEVENV_SHELL_TIMEOUT_SECONDS)
    owner = checks.add_parser(
        "owner-services",
        help="issue 1290: the owner's services run at boot with nobody logged in")
    owner.add_argument("--console-port", type=_port, required=True)
    owner.add_argument("--proxy-port", type=_port, required=True)
    owner.add_argument("--merge", type=_merge_sha, required=True)
    owner.add_argument("--launchctl", default="/bin/launchctl")
    owner.add_argument("--lsof", default="/usr/sbin/lsof")
    failed = checks.add_parser(
        "console-failed-start",
        help="issue 1182: an open failed-start card's sprint line reads the failed start, with Retry")
    failed.add_argument("--port", type=_port, required=True)
    manager_merge = checks.add_parser(
        "console-manager-merge",
        help="issue 1377: a manager merged its sprint's pull request through the console's permit "
             "after activation")
    manager_merge.add_argument("--repo", type=_repo, required=True)
    manager_merge.add_argument("--since", type=_merge_sha, required=True)
    manager_merge.add_argument("--log", type=Path)
    manager_merge.add_argument("--repo-root", type=Path, default=Path("."))
    past_implement = checks.add_parser(
        "engine-direct-past-implement",
        help="the first direct engine delivery after activation entered a step after implement in time")
    past_implement.add_argument("--since", type=_merge_sha, required=True)
    past_implement.add_argument("--runs-root", type=Path)
    past_implement.add_argument("--log", type=Path)
    past_implement.add_argument("--repo-root", type=Path, default=Path("."))
    past_setup = checks.add_parser(
        "engine-deliver-past-setup",
        help="the first direct engine delivery after activation had a direct child run enter a step in time")
    past_setup.add_argument("--since", type=_merge_sha, required=True)
    past_setup.add_argument("--runs-root", type=Path)
    past_setup.add_argument("--log", type=Path)
    past_setup.add_argument("--repo-root", type=Path, default=Path("."))
    notices = checks.add_parser(
        "console-notice-lists",
        help="issue 1291: the owner's notice for each project names every one of its issues")
    notices.add_argument("--port", type=_port, required=True)
    notices.add_argument("--notice", type=_notice_spec, action="append", required=True,
                         metavar="PROJECT=N1,N2,...")
    mentions = checks.add_parser(
        "host-mentions",
        help="issue 1291: every open issue naming a retired host is exempt or carries its gone line")
    mentions.add_argument("--repo", type=_repo, required=True)
    mentions.add_argument("--phrase", type=_nonempty, action="append", required=True)
    mentions.add_argument("--gone", type=_nonempty, required=True)
    mentions.add_argument("--exempt", type=_issue_number, action="append", default=[])
    prompts = checks.add_parser(
        "host-prompts",
        help="issue 1291: no open issue holds a live owner prompt that names a retired host")
    prompts.add_argument("--repo", type=_repo, action="append", required=True)
    prompts.add_argument("--host", type=_nonempty, required=True)
    args = parser.parse_args(argv)
    if args.check == "owner-services":
        code, report = owner_services(
            console_port=args.console_port, proxy_port=args.proxy_port, merge=args.merge,
            home=Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir), uid=os.getuid(),
            repo_root=Path("."), launchctl=args.launchctl, lsof=args.lsof)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "console-failed-start":
        code, report = console_failed_start(args.port)
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "console-manager-merge":
        try:
            code, report = console_manager_merge(args.repo, args.since, log=args.log,
                                                 repo_root=args.repo_root)
        except (ToolError, GitError) as error:
            print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
            return 2
        except forge_api.ForgeError as error:
            print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "engine-direct-past-implement":
        try:
            code, report = engine_direct_past_implement(args.since, runs_root=args.runs_root, log=args.log,
                                                        repo_root=args.repo_root)
        except (ToolError, GitError) as error:
            print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "engine-deliver-past-setup":
        try:
            code, report = engine_deliver_past_setup(args.since, runs_root=args.runs_root, log=args.log,
                                                     repo_root=args.repo_root)
        except (ToolError, GitError) as error:
            print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "console-notice-lists":
        wanted = [project for project, _ in args.notice]
        if len(set(wanted)) != len(wanted):
            parser.error("--notice names a project twice")
        code, report = console_notice_lists(args.port, dict(args.notice))
        print(json.dumps(report, sort_keys=True))
        return code
    if args.check == "devenv-shell":
        devenv_bin = shutil.which("devenv", path=os.environ.get("PATH"))
        try:
            code, report = devenv_shell(args.probe, args.repo_root, devenv_bin=devenv_bin,
                                        environ=os.environ, timeout=args.timeout_seconds)
        except (FixtureError, GitError) as error:
            print(f"verify-checks: fixture_error: {str(error).splitlines()[0]}", file=sys.stderr)
            return 2
        print(json.dumps(report, sort_keys=True))
        return code
    try:
        if args.check == "host-mentions":
            code, report = host_mentions(args.repo, args.phrase, args.gone, args.exempt)
        elif args.check == "host-prompts":
            code, report = host_prompts(args.repo, args.host)
        else:
            raise AssertionError(args.check)
    except forge_api.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code

if __name__ == "__main__":
    sys.exit(main())
