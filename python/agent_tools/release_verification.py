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
"""

import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_history import format_at

SCHEMA = "release-verification/v1"
READ_BUDGET_SECONDS = 30
PAGE_SIZE = 100
STRIPPED = ("GITHUB_TOKEN", "GH_TOKEN")
DETAIL_LIMIT = 240
UNAVAILABLE = "verification_unavailable"


class VerificationRefused(Exception):
    """`code` is `candidate_stale` or `verification_unavailable`; `detail` is at most 240
    characters."""

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


def canonical_text(receipt: Mapping[str, Any]) -> str:
    """The receipt as sorted, compact, ASCII JSON with no newline."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def evidence_id(receipt: Mapping[str, Any]) -> str:
    return "verification:" + telemetry_digest(receipt)
