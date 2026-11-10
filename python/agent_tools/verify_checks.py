"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`required-checks --repo R --base B --since T` is met when the first pull request merged into B
after T had every required check pass before its merge, each from the app its protection binds
it to. It only reads the forge, across every page of each listing, and refuses an incomplete or
truncated listing rather than judging it.

`managed-pre-push-hook --slug S` (issue 672) is met when the global `core.hooksPath` is the
managed `-agent-git-hooks` directory and, in a local fixture of S whose own git configuration
holds only that hooks path, an agent push of `main` is refused by its `pre-push` with the
remote unchanged while a feature-branch push is admitted. It exits 2 on a fixture error.

`cutover-manifest [--repo-root R] [--branch B] [--main-ref REV]` (issue 579, C4.a) is met (0, `green`)
when the manifest at the tip of origin's candidate branch is a major-2 manifest whose `removals`
are non-empty and each equal, in all six members, to a `deprecations` entry of a major-1 manifest
on main. It is 75 when anything of that is not yet so (`absent` when the branch does not exist) and
2 when a manifest cannot be read. It only reads: it fetches objects, and writes no ref.

`cutover-preflight [--repo-root R] [--branch B]` (issue 579, C4.b) is met when `cutover-manifest` is
green and both the installed bridge and the candidate's own code judge every registered project
compatible, with no removed use. It is 75 otherwise, and 0 only when green.

`cutover-bundle [--repo-root R] [--branch B]` (issue 579, C3) is met (0, `green`) when a `*-bundle.json`
under `.agents/artifacts/evidence/` at origin's main verifies, through `agent_gate_bundle.verify_bundle`,
as `approved` and binds the commit at the tip of origin's candidate branch. The state is the verifier's
return value, never the document's own `state` field; a bundle the verifier refuses is `unreadable` and
never counts. It is 75 otherwise (`absent` when the branch does not exist) and 2 when git cannot be
driven. It only reads: it fetches objects, and writes no ref. A gate-version-2 (claude-only) bundle is
verified as the cutover kind, under the no-regression criterion.

`self-hosted-runner --repo R --runner N --label L...` (issue 680) is met when R lists a runner
named N whose status is online and whose labels include `self-hosted` and every L; not met when
it is online but lacks one (a wrong registration), and not yet when it is unlisted or not online.
It only reads one paginated runner listing and refuses a truncated or malformed one.

`guard-policy-fleet [--repo-root R] [--branch B] [--registry FILE]` (issue 765, C13.a) is met (0, `green`)
when, with the candidate's own `python/` and platform manifest unpacked from origin's candidate branch into a
temporary `HOME`, `python -m agent_tools.guard_policy derive --repository S` exits 0 with a derived row for
every slug S named by a registry entry's `origin` (the host's own registry unless `--registry` names another
file). Any other exit, outcome or unreadable answer makes that row, and the check, 1 (`red`); a candidate
branch that does not exist is 75 (`absent`) and an unreadable registry or unpackable candidate is 75
(`unreadable`). The installed bridge is never asked: it still accepts what the candidate refuses. Like the
lifecycle guard, `derive` writes the objects and remote-tracking refs it fetches into the registered checkouts.

`registry-agreement --registry HOST=FILE... [--intentional PROJECT_ID]...` (issue 765, C13.b) is met (0,
`green`) when every project registered on more than one of the named hosts carries the same `branch_override`
(absent counts as a value) in each of those registries; a project whose registries differ is `red` (1)
unless its id is named by `--intentional`, which records the difference as `intentional`. It reads only the
files, and exits 2 on a file it cannot read.

`worktree-mapping [--red-pending] --repo-root R...` (issue 585) states the #130 checklist C7 rule
over each root through `agent_tools.worktree_mapping`, read-only, using the verdicts of
`workflow-state migrate --repo-root R`. It exits 0 when every root is green, 1 when one is red,
75 when none is red and one is human-pending, and 2 on a tool error. Under `--red-pending` any
root that is not green exits 75.

Issue 710 adds the `forge` class (reasons `claim`, `open_pr`, `declared`), read through
`agent_tools.worktree_forge`: only a path the ledgers leave `unmapped` is upgraded, and only
when its branch is named by (D5) the winning claim marker of an open `in-progress` issue, whose
author association is `OWNER` or `MEMBER` (a released or `end`-ed claim and an untrusted
author's claim map nothing), (D6) an open pull request headed in the same repository (a fork's
pull request maps nothing), or (D7) a branch of the declared table (`cutover-130-candidate`
for `fagenorn/nix-config`) whose declaring issue is still open. The forge reads are GET-only,
and a root without a GitHub `origin` reads no forge. A forge failure or a malformed payload is
a tool error, exit 2 (`verify-checks: forge_error:`), never an unmapped reading.

`deprecations-retired [--red-pending] [--watch-adapter A] --repo-root R...` (issue 582) states the
#130 checklist C11 rule over each root, read-only: no deprecated use reported by
`resolve-project platform-status` (a), no tracked legacy skills config (b), `bindings.deploy.adapter`
resolved to `none` (c), and no skill text naming the retired command (d); with `--watch-adapter A`
it also reads whether the release target A is adopted and available. It exits 0 when every root is
green, 1 when one is red, 75 when none is red and one is pending, and 2 on a tool error. Under
`--red-pending` any root that is not green exits 75.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from agent_tools import forge_markers, github_remote
from agent_tools.agent_gate_bundle import BundleIntegrityError, verify_bundle
from agent_tools.agent_platform import (
    DEPRECATION_MEMBERS, parse_semver, validate_manifest, validate_registry)
from agent_tools.agent_costs import parse_rfc3339_utc
from agent_tools.push_fixture import make_push_fixture
from agent_tools import worktree_forge
from agent_tools.worktree_mapping import MappingError, classify_root

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


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
    pages = forge_markers.api_pages(
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
    payload = forge_markers.api_get(
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
        pull = forge_markers.api_get(f"repos/{repo}/pulls/{number}")
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
    runs = _counted_pages(forge_markers.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    status_pages = forge_markers.api_pages(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    if not all(isinstance(page, list) for page in status_pages):
        raise _invalid("status page is not a list")
    statuses = [entry for page in status_pages for entry in page]
    report["missing"] = sorted({r[0] for r in required
                                if not _context_met(r, runs, statuses, merged_at)})
    return (0 if not report["missing"] else 1), report


def self_hosted_runner(repo: str, runner: str, labels: Sequence[str]) -> tuple[int, dict]:
    """Met when `runner` is listed on `repo`, online, and carries `self-hosted` and every label."""
    required = {"self-hosted", *labels}
    entries = _counted_pages(forge_markers.api_pages(
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
            [sys.executable, "-m", "agent_tools.resolve_project", "platform-status", "--fleet",
             "--manifest", str(tmp_path / MANIFEST_PATH)],
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


WORKFLOW_STATE_TIMEOUT = 300


def _migrate_report(root: Path, environ: Mapping[str, str]) -> dict:
    """The dry-run report of `workflow-state migrate --repo-root root`; ToolError when unusable."""
    binary = shutil.which("workflow-state", path=environ.get("PATH"))
    if binary is None:
        raise ToolError("tool_error", "workflow-state not found")
    try:
        done = subprocess.run([binary, "migrate", "--repo-root", str(root)], env=dict(environ),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=WORKFLOW_STATE_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError("tool_error", f"workflow-state failed: {error}") from None
    if done.returncode != 0:
        raise ToolError("tool_error", f"workflow-state exit {done.returncode}: {done.stderr.strip()}")
    try:
        parsed = json.loads(done.stdout)
    except ValueError:
        raise ToolError("mapping_error", f"workflow-state printed non-JSON for {root}") from None
    if not isinstance(parsed, dict):
        raise ToolError("mapping_error", f"workflow-state report for {root} is not an object")
    return parsed


class ToolError(Exception):
    """The check could not judge: `kind` is the stderr label, the caller exits 2."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


def worktree_mapping_check(roots: Sequence[Path], environ: Mapping[str, str], *,
                           red_pending: bool) -> tuple[int, dict]:
    """The C7 rule over each root. Raises ToolError when a root cannot be judged."""
    rows = []
    for root in roots:
        report = _migrate_report(root, environ)
        try:
            rows.append(classify_root(root, report, forge=worktree_forge.forge_facts))
        except MappingError as error:
            raise ToolError("mapping_error", str(error)) from None
        except forge_markers.ForgeError as error:
            raise ToolError("forge_error", str(error)) from None
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
    green = done.returncode == 0 and adapter == "none"
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


def _derive_row(slug: str, child_env: Mapping[str, str], cwd: Path) -> dict:
    row: dict = {"repository": slug, "exit": None, "outcome": "unreadable", "reason_codes": []}
    try:
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.guard_policy", "derive", "--repository", slug],
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
        rows.extend(_derive_row(slug, child_env, tmp_path) for slug in slugs)
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
    mapping = checks.add_parser(
        "worktree-mapping",
        help="issue 585/710: every retained worktree has a ledger mapping, a live claim, an open PR or a declared branch (C7)")
    mapping.add_argument("--repo-root", type=Path, action="append", required=True)
    mapping.add_argument("--red-pending", action="store_true")
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
    args = parser.parse_args(argv)
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
    if args.check == "worktree-mapping":
        try:
            code, report = worktree_mapping_check(args.repo_root, os.environ,
                                                  red_pending=args.red_pending)
        except ToolError as error:
            print(f"verify-checks: {error.kind}: {error}", file=sys.stderr)
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
        else:
            code, report = required_checks(args.repo, args.base, args.since)
    except forge_markers.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
