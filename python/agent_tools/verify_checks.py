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
driven. It only reads: it fetches objects, and writes no ref.

`worktree-mapping [--red-pending] --repo-root R...` (issue 585) states the #130 checklist C7 rule
over each root through `agent_tools.worktree_mapping`, read-only, using the verdicts of
`workflow-state migrate --repo-root R`. It exits 0 when every root is green, 1 when one is red,
75 when none is red and one is human-pending, and 2 on a tool error. Under `--red-pending` any
root that is not green exits 75.
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

from agent_tools import forge_markers
from agent_tools.agent_gate_bundle import BundleIntegrityError, verify_bundle
from agent_tools.agent_platform import DEPRECATION_MEMBERS, parse_semver
from agent_tools.agent_costs import parse_rfc3339_utc
from agent_tools.push_fixture import make_push_fixture
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
    """The version, deprecations and removals of a readable manifest, else None."""
    if not isinstance(manifest, dict):
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
        archive = _git(repo_root, "archive", "--format=tar", sha, "python", MANIFEST_PATH,
                       environ=environ, text=False)
        if archive.returncode != 0:
            return _preflight_failure("unreadable", sha, "candidate", manifest)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
                tar.extractall(tmp_path, filter="data")
        except (tarfile.TarError, OSError):
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
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")


def bundle_verdict(bundles: Mapping[str, object], candidate_sha: str) -> tuple[int, dict]:
    """C3: some emitted bundle verifies `approved` and binds `candidate_sha`.

    Each value goes through `verify_bundle`, the one verifier of an emitted bundle: the id is
    recomputed over the body and the state re-decided from the bundle's own evidence. The state
    read is its return value, never `document["state"]`."""
    approved: list[str] = []
    other: list[dict] = []
    unreadable: list[dict] = []
    for path in sorted(bundles):
        document = bundles[path]
        try:
            state = verify_bundle(document)
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
            rows.append(classify_root(root, report))
        except MappingError as error:
            raise ToolError("mapping_error", str(error)) from None
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


def _rfc3339(value: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an RFC 3339 instant with Z or an offset") from None


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
    mapping = checks.add_parser(
        "worktree-mapping",
        help="issue 585: every retained worktree has a strict-path ledger mapping (C7)")
    mapping.add_argument("--repo-root", type=Path, action="append", required=True)
    mapping.add_argument("--red-pending", action="store_true")
    args = parser.parse_args(argv)
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
        code, report = required_checks(args.repo, args.base, args.since)
    except forge_markers.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
