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

`worktree-mapping [--red-pending] --repo-root R...` (issue 585) states the #130 checklist C7 rule
over each root through `agent_tools.worktree_mapping`, read-only, using the verdicts of
`workflow-state migrate --repo-root R`. It exits 0 when every root is green, 1 when one is red,
75 when none is red and one is human-pending, and 2 on a tool error. Under `--red-pending` any
root that is not green exits 75.

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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from agent_tools import forge_markers
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


def _git(root: Path, environ: Mapping[str, str], *args: str) -> subprocess.CompletedProcess:
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
    done = _git(root, environ, "ls-files", "--", SKILLS_CONFIG)
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
    done = _git(root, environ, "grep", "-n", "-F", RETIRED_COMMAND, "--", *scope)
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
    mapping = checks.add_parser(
        "worktree-mapping",
        help="issue 585: every retained worktree has a strict-path ledger mapping (C7)")
    mapping.add_argument("--repo-root", type=Path, action="append", required=True)
    mapping.add_argument("--red-pending", action="store_true")
    retired = checks.add_parser(
        "deprecations-retired",
        help="issue 582: the deprecated paths have zero users in every root (C11)")
    retired.add_argument("--repo-root", type=Path, action="append", required=True)
    retired.add_argument("--watch-adapter")
    retired.add_argument("--red-pending", action="store_true")
    args = parser.parse_args(argv)
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
