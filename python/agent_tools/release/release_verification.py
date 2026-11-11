"""The candidate's required-CI receipt (#128 spec §3, D22).

`observe` reads three GitHub API paths, in this order, each as `gh api <path>` and nothing
else, and folds them into one closed `release-verification/v1` receipt:

1. `repos/<repository>/git/ref/heads/<integration_branch>`: the tip must be the candidate
   `commit`, else `candidate_stale`, and reads 2 and 3 never run;
2. `repos/<repository>/branches/<default_branch>/protection`: the required status checks,
   `required_status_checks.checks`, a non-empty list of `{context, app_id}` (other members
   are ignored; any other entry shape is refused), kept in protection's order;
3. `repos/<repository>/commits/<commit>/check-runs?per_page=100`: one page only, so a
   `total_count` above `PAGE_SIZE` is refused rather than paged.

Every other failure is `verification_unavailable`: a non-zero exit, a timeout, an `OSError`,
bad JSON, a missing floor or an unexpected shape. The three reads share one monotonic
deadline of `READ_BUDGET_SECONDS`, each read gets the time remaining as its timeout, and
none is started once nothing remains. The child environment is `os.environ` without
`STRIPPED`, so `gh` authenticates only through its own credential store.

Per required context, the matching runs are those named by the context (and, when `app_id`
is set, created by that app); the run with the largest integer `id` decides, and no match is
`missing`. `result` is `passed` when every check is a completed success, `failed` when some
check completed with another conclusion, and `pending` otherwise. The receipt carries no
detail beyond that, so its digest is the evidence id.

`observe_merge` is the read side of a two-branch release (issue 554 D3), for a profile whose
merge step consumes the candidate's `merge`. It makes three reads under a deadline of its own,
`READ_BUDGET_SECONDS`, and a refusal stops the later ones:

1. `repos/<repository>/pulls?state=open&base=<default_branch>&head=<owner>:<integration_branch>
   &per_page=2`: exactly one open pull request, whose head is the candidate `commit`. No
   pull request is `release_pr_missing`, a head elsewhere is `release_pr_stale`, and two
   pull requests or an entry of another shape is `verification_unavailable`;
2. `repos/<repository>/git/ref/heads/<default_branch>`: its tip is the `base_tip`;
3. `repos/<repository>/compare/<base_tip>...<commit>`: the status must be `ahead`, else
   `release_pr_behind`, since the default branch has moved past what the pull request merges.

It returns `{pr, base_tip}`. Every failed read is `verification_unavailable`, as for `observe`.

A `release_pr_behind` refusal makes one more read, `repos/<repository>/pulls?state=open
&base=<integration_branch>&per_page=100`, and names every open pull request whose head is a sync
branch of this branch pair (`forge_adapter.SYNC_BRANCH`), so the refusal says what to merge
(issue 845). With none, or when that read fails, it says to merge the default branch into the
integration branch, as before.
"""

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.release import forge_adapter
from agent_tools.release.transaction_history import format_at

SCHEMA = "release-verification/v1"
READ_BUDGET_SECONDS = 30
PAGE_SIZE = 100
STRIPPED = ("GITHUB_TOKEN", "GH_TOKEN")
DETAIL_LIMIT = 240
UNAVAILABLE = "verification_unavailable"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class VerificationRefused(Exception):
    """`code` is `candidate_stale`, `verification_unavailable`, `release_pr_missing`,
    `release_pr_stale` or `release_pr_behind`; `detail` is at most 240 characters."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail[:DETAIL_LIMIT]


def _unavailable(path: str, reason: str) -> VerificationRefused:
    return VerificationRefused(UNAVAILABLE, f"{path}: {reason}"[:DETAIL_LIMIT])


def _read(path: str, deadline: float) -> Any:
    """The parsed JSON of `gh api <path>`, within what is left of `deadline`."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _unavailable(path, "the read budget is spent")
    env = {name: value for name, value in os.environ.items() if name not in STRIPPED}
    try:
        done = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                              timeout=remaining, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise _unavailable(path, "the read timed out") from None
    except OSError as error:
        raise _unavailable(path, str(error)) from error
    if done.returncode != 0:
        raise _unavailable(path, f"exit {done.returncode}: {done.stderr.strip()}")
    try:
        return json.loads(done.stdout)
    except ValueError as error:
        raise _unavailable(path, f"the answer is not JSON: {error}") from error


def _tip(payload: Any, path: str) -> str:
    target = payload.get("object") if isinstance(payload, dict) else None
    sha = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(sha, str):
        raise _unavailable(path, "the answer carries no object.sha")
    return sha


def _required(payload: Any, path: str) -> list[dict[str, Any]]:
    section = payload.get("required_status_checks") if isinstance(payload, dict) else None
    checks = section.get("checks") if isinstance(section, dict) else None
    if not isinstance(checks, list) or not checks:
        raise _unavailable(path, "no required status checks are established")
    required = []
    for entry in checks:
        valid = (isinstance(entry, dict) and isinstance(entry.get("context"), str)
                 and entry["context"] != "" and "app_id" in entry
                 and (entry["app_id"] is None
                      or (isinstance(entry["app_id"], int) and not isinstance(entry["app_id"], bool))))
        if not valid:
            raise _unavailable(path, "a required check is not {context, app_id}")
        required.append({"context": entry["context"], "app_id": entry["app_id"]})
    return required


def _runs(payload: Any, path: str) -> list[dict[str, Any]]:
    total = payload.get("total_count") if isinstance(payload, dict) else None
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    if not isinstance(total, int) or isinstance(total, bool) or not isinstance(runs, list):
        raise _unavailable(path, "the answer is not a check-run page")
    if total > PAGE_SIZE:
        raise _unavailable(path, f"{total} check runs exceed one page of {PAGE_SIZE}")
    return [run for run in runs if isinstance(run, dict)]


def _matches(run: dict[str, Any], requirement: Mapping[str, Any]) -> bool:
    app = run.get("app")
    return (run.get("name") == requirement["context"]
            and isinstance(run.get("id"), int) and not isinstance(run["id"], bool)
            and (requirement["app_id"] is None
                 or (isinstance(app, dict) and app.get("id") == requirement["app_id"])))


def _check(requirement: Mapping[str, Any], runs: list[dict[str, Any]], path: str
           ) -> dict[str, Any]:
    matching = [run for run in runs if _matches(run, requirement)]
    context = requirement["context"]
    if not matching:
        return {"context": context, "status": "missing", "conclusion": None}
    decisive = max(matching, key=lambda run: run["id"])
    status, conclusion = decisive.get("status"), decisive.get("conclusion")
    if not isinstance(status, str) or not (conclusion is None or isinstance(conclusion, str)):
        raise _unavailable(path, f"the run for {context} has no usable status")
    return {"context": context, "status": status, "conclusion": conclusion}


def _result(checks: list[dict[str, Any]]) -> str:
    if all(c["status"] == "completed" and c["conclusion"] == "success" for c in checks):
        return "passed"
    if any(c["status"] == "completed" and c["conclusion"] != "success" for c in checks):
        return "failed"
    return "pending"


def observe(*, project_id: str, profile_id: str, profile_digest: str, repository: str,
            integration_branch: str, default_branch: str, commit: str, version: str,
            clock: Callable[[], int] | None = None) -> dict[str, Any]:
    """The receipt for `commit` as `version`, or `VerificationRefused`."""
    clock = clock or (lambda: time.time_ns() // 1_000_000)
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    tip_path = f"repos/{repository}/git/ref/heads/{integration_branch}"
    tip = _tip(_read(tip_path, deadline), tip_path)
    if tip != commit:
        raise VerificationRefused(
            "candidate_stale", f"{integration_branch} is at {tip}, not the candidate {commit}")
    protection_path = f"repos/{repository}/branches/{default_branch}/protection"
    required = _required(_read(protection_path, deadline), protection_path)
    runs_path = f"repos/{repository}/commits/{commit}/check-runs?per_page={PAGE_SIZE}"
    runs = _runs(_read(runs_path, deadline), runs_path)
    checks = [_check(requirement, runs, runs_path) for requirement in required]
    return {"schema": SCHEMA, "project": project_id, "profile": profile_id,
            "profile_digest": profile_digest,
            "candidate": {"commit": commit, "version": version}, "required": required,
            "checks": checks, "result": _result(checks), "observed_at": format_at(clock())}


def _release_pr(payload: Any, path: str, *, owner: str, integration_branch: str,
                default_branch: str, commit: str) -> int:
    if not isinstance(payload, list):
        raise _unavailable(path, "the answer is not a list of pull requests")
    if not payload:
        raise VerificationRefused(
            "release_pr_missing",
            f"no open pull request from {owner}:{integration_branch} into {default_branch}")
    entry = payload[0]
    head = entry.get("head") if isinstance(entry, dict) else None
    number = entry.get("number") if isinstance(entry, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if (len(payload) > 1 or not isinstance(number, int) or isinstance(number, bool)
            or number < 1 or not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None):
        raise _unavailable(path, "not exactly one open pull request of {number, head.sha}")
    if sha != commit:
        raise VerificationRefused(
            "release_pr_stale", f"pull request {number} is at {sha}, not the candidate {commit}")
    return number


def _behind_repair(repository: str, integration_branch: str, default_branch: str,
                   deadline: float) -> str:
    """What to do about a release PR that is behind: merge the open sync pull requests of this
    branch pair when there are any, else merge the default branch by hand (issue 845)."""
    prefix = forge_adapter.SYNC_BRANCH.format(default=default_branch,
                                              integration=integration_branch, version="")
    path = f"repos/{repository}/pulls?state=open&base={integration_branch}&per_page={PAGE_SIZE}"
    try:
        payload = _read(path, deadline)
    except VerificationRefused:
        payload = None
    found = []
    for entry in payload if isinstance(payload, list) else []:
        head = entry.get("head") if isinstance(entry, dict) else None
        ref = head.get("ref") if isinstance(head, dict) else None
        number = entry.get("number") if isinstance(entry, dict) else None
        if (isinstance(ref, str) and ref.startswith(prefix)
                and forge_adapter.BRANCH.fullmatch(ref) is not None
                and isinstance(number, int) and not isinstance(number, bool)):
            found.append(f"{number} ({ref})")
    if not found:
        return (f"merge {default_branch} into {integration_branch}, push, wait for CI and "
                "preview again")
    return (f"merge the open sync pull request{'s' if len(found) > 1 else ''} "
            f"{', '.join(found)} into {integration_branch}, wait for CI and preview again")


def observe_merge(*, repository: str, integration_branch: str, default_branch: str,
                  commit: str) -> dict[str, Any]:
    """The open release pull request and the default tip it will merge onto, as
    `{pr, base_tip}`, or `VerificationRefused` (issue 554 D3)."""
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    owner = repository.split("/")[0]
    pulls_path = (f"repos/{repository}/pulls?state=open&base={default_branch}"
                  f"&head={owner}:{integration_branch}&per_page=2")
    pr = _release_pr(_read(pulls_path, deadline), pulls_path, owner=owner,
                     integration_branch=integration_branch, default_branch=default_branch,
                     commit=commit)
    tip_path = f"repos/{repository}/git/ref/heads/{default_branch}"
    base_tip = _tip(_read(tip_path, deadline), tip_path)
    if SHA_PATTERN.fullmatch(base_tip) is None:
        raise _unavailable(tip_path, "object.sha is not 40 lowercase hex digits")
    compare_path = f"repos/{repository}/compare/{base_tip}...{commit}"
    payload = _read(compare_path, deadline)
    status = payload.get("status") if isinstance(payload, dict) else None
    if not isinstance(status, str):
        raise _unavailable(compare_path, "the answer carries no status")
    if status != "ahead":
        repair = _behind_repair(repository, integration_branch, default_branch, deadline)
        raise VerificationRefused(
            "release_pr_behind",
            f"{integration_branch} is {status} relative to {default_branch} at {base_tip}: {repair}")
    return {"pr": pr, "base_tip": base_tip}


def canonical_text(receipt: Mapping[str, Any]) -> str:
    """The receipt as sorted, compact, ASCII JSON with no newline."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def evidence_id(receipt: Mapping[str, Any]) -> str:
    return "verification:" + telemetry_digest(receipt)
