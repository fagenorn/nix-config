"""The Railway deploy-watch adapter (issue 582 P1-P7; the issue 555 watch design): `describe`, `inspect`, `invoke`.

These three functions are the adapter's whole public surface (#124 D7). `describe()` returns a
fresh descriptor with one operation, `deploy`: a watch-only `publication_triggered` activation
unit a release profile may bind. It is supported for `inspect`, and `invoke` refuses every
request (`watch_only`), so the adapter never changes the world. It also answers the
`running_subject_identity` predicate from the same reading. Its closed config is `project`,
`environment` and `services` (a `string_list`); its target is the `github_repository` the
release was published on, which resolves the released commit exactly as the issue 555 adapter does.

This module imports only the standard library, `agent_tools.canonical` and
`agent_tools.release_merge`: the registry in `release_adapter` imports it, never the reverse.

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid` for an effect and `unknown`/`identity_unobservable` for a
predicate (whose derived reason space has no `parameters_invalid`); a predicate naming anything
but `running_subject_identity` is `unknown`/`predicate_unsupported`. Neither starts a child
process. Otherwise, under one `COLLECTION_BUDGET_SECONDS` deadline and with the caller's
environment unchanged, it resolves the released commit, reads `railway status --json` to check
the linked project and environment, then one `railway deployment list ... --json` per service
and classifies each service by plan P5, in order. Only read-only `railway` verbs are ever run.

A `SKIPPED` deployment is `satisfied` only with two kinds of affirmative evidence (plan P5.5):
the released commit's GitHub check runs are all green, and the serving deployment is the
skipped push's immediate predecessor at the released commit's first parent. Railway skips a push
both when no watched path changed and after failed or timed-out CI, so a skip alone proves
nothing. Anything short of both is `unknown`/`skip_unexplained`, a conservative answer the
driver waits on and then parks, never a false success.
"""

import json
import re
import subprocess
import time
from datetime import datetime
from typing import Any

from agent_tools import release_merge
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

COLLECTION_BUDGET_SECONDS = 30
DETAIL_LIMIT = release_merge.DETAIL_LIMIT
CHECK_RUN_LIMIT = 100
BENIGN_CONCLUSIONS = ("success", "neutral", "skipped")
STATUS_ARGV = ["status", "--json"]
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}")
ROW_SHA = re.compile(r"[0-9A-Fa-f]{40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
CONFIG_MEMBERS = {"project": "string", "environment": "string", "services": "string_list"}
TARGET_MEMBERS = frozenset(("kind", "repository", "branch"))
MERGE_MEMBERS = frozenset(("pr", "base_tip"))
CANDIDATE_SHAPES = (frozenset(("commit",)), frozenset(("version", "commit")),
                    frozenset(("version", "commit", "merge")))
REQUIRED = frozenset(("target", "candidate", "config"))
TOLERATED = frozenset(("action", "operation"))
IN_PROGRESS = ("QUEUED", "WAITING", "INITIALIZING", "BUILDING", "DEPLOYING", "NEEDS_APPROVAL")
SERVING = ("SUCCESS", "SLEEPING")
FAILED = ("FAILED", "CRASHED")
REMOVED = ("REMOVED", "REMOVING")
PRECEDENCE = ("diverged", "unknown", "in_progress", "absent", "satisfied")


def deployment_argv(service: str, environment: str) -> list[str]:
    """The read-only deployment list of one service (plan P4)."""
    return ["deployment", "list", "--service", service, "--environment", environment, "--json"]


def check_runs_argv(repository: str, commit: str) -> list[str]:
    """The check runs of a commit as an explicit GET, run through `release_merge.gh`."""
    return ["api", "-X", "GET", f"repos/{repository}/commits/{commit}/check-runs", "-f",
            f"per_page={CHECK_RUN_LIMIT}"]


def parent_argv(repository: str, commit: str) -> list[str]:
    """The git commit (its parents) as an explicit GET, run through `release_merge.gh`."""
    return ["api", "-X", "GET", f"repos/{repository}/git/commits/{commit}"]


def describe() -> dict[str, Any]:
    """The `railway-deploy` descriptor, a fresh plain dict."""
    return {
        "name": "railway-deploy",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "deploy": {"mode": "publication_triggered", "support": "supported",
                       "inspect": "supported", "reason": None,
                       "mutability": "in_place", "config_schema_version": 1,
                       "config_schema": {"members": dict(CONFIG_MEMBERS),
                                         "required": list(CONFIG_MEMBERS)},
                       "effects": ["reversible_no_incremental_spend"],
                       "recovery_capable": False, "candidate_members": []},
        },
        "predicates": {
            "publication_visible": {"support": "unsupported", "reason": "no_publication_mode"},
            "running_subject_identity": {"support": "supported", "reason": None},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"github_repository": ["branch", "repository"]},
        "credential_classes": ["gh_cli", "railway_cli"],
        "executables": ["gh", "railway"],
        "host_capacity": "not_required",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _hex40(value: object) -> bool:
    return isinstance(value, str) and CANDIDATE_SHA.fullmatch(value) is not None


def _candidate_problem(candidate: Any) -> str | None:
    """The first way `candidate` departs from the three closed candidate shapes, or None."""
    if not isinstance(candidate, dict) or frozenset(candidate) not in CANDIDATE_SHAPES:
        return "candidate is not {commit}, {version, commit} or {version, commit, merge}"
    if not _hex40(candidate["commit"]):
        return "candidate commit is not 40 lowercase hex characters"
    if "version" in candidate and not (isinstance(candidate["version"], str)
                                       and VERSION.fullmatch(candidate["version"])):
        return "candidate version is not vMAJOR.MINOR.PATCH"
    if "merge" in candidate:
        merge = candidate["merge"]
        if not isinstance(merge, dict) or set(merge) != MERGE_MEMBERS:
            return "merge is not {pr, base_tip}"
        if type(merge["pr"]) is not int or merge["pr"] < 1:
            return "merge pr is not a positive integer"
        if not _hex40(merge["base_tip"]):
            return "merge base_tip is not 40 lowercase hex characters"
    return None


def _parameters_problem(parameters: Any) -> str | None:
    """The first way `parameters` departs from the closed deploy shape, or None."""
    if not isinstance(parameters, dict):
        return "parameters is not an object"
    missing, undeclared = sorted(REQUIRED - set(parameters)), sorted(
        set(parameters) - REQUIRED - TOLERATED, key=str)
    if missing:
        return f"parameters is missing {missing[0]}"
    if undeclared:
        return f"parameters has an undeclared member {undeclared[0]}"
    target = parameters["target"]
    if (not isinstance(target, dict)
            or not TARGET_MEMBERS <= set(target) <= TARGET_MEMBERS | {"handle"}
            or target["kind"] != "github_repository"):
        return ("target is not a github_repository of exactly kind, repository and branch, "
                "and an optional handle")
    if "handle" in target and not _text(target["handle"]):
        return "target handle is not a non-empty string"
    repository, branch = target["repository"], target["branch"]
    if not isinstance(repository, str) or SLUG.fullmatch(repository) is None or ".." in repository:
        return "target repository is not an owner/name slug"
    if not isinstance(branch, str) or BRANCH.fullmatch(branch) is None or ".." in branch:
        return "target branch is not a branch name"
    problem = _candidate_problem(parameters["candidate"])
    if problem is not None:
        return problem
    config = parameters["config"]
    if not isinstance(config, dict) or set(config) != set(CONFIG_MEMBERS):
        return f"config is not exactly {', '.join(CONFIG_MEMBERS)}"
    for name, kind in CONFIG_MEMBERS.items():
        value = config[name]
        if kind == "string" and not (_text(value) and CONTROL.search(value) is None):
            return f"config {name} is not a non-empty string without control characters"
        if kind == "string_list" and not (
                isinstance(value, list) and value and all(_text(item) for item in value)
                and len(set(value)) == len(value)):
            return f"config {name} is not a non-empty list of unique non-empty strings"
    return None


def _railway(args: list[str], deadline: float) -> tuple[str, Any, str]:
    """Run `railway <args>` within what is left of `deadline`: `(status, payload, detail)`.

    The status vocabulary is `release_merge.gh`'s: `"ok"` with the strictly parsed JSON payload,
    or `lookup_failed`, `lookup_timeout`, `payload_invalid` and `executable_missing` with a
    payload of `None`. The child inherits the environment unchanged.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", None, ""
    try:
        done = subprocess.run(["railway", *args], capture_output=True, text=True,
                              errors="replace", timeout=remaining, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", None, ""
    except OSError as error:
        return "executable_missing", None, str(error)
    except ValueError as error:
        return "lookup_failed", None, f"railway could not be started: {error}"
    detail = done.stderr.strip()[:DETAIL_LIMIT]
    if done.returncode != 0:
        return "lookup_failed", None, detail
    try:
        return "ok", json.loads(done.stdout, object_pairs_hook=reject_duplicate_keys,
                                parse_constant=reject_nonfinite_literal), detail
    except (ValueError, RecursionError):
        return "payload_invalid", None, detail


class _Invalid(Exception):
    """A payload outside the closed shape: `payload_invalid` with this detail."""


def _rows(payload: Any) -> list[dict[str, Any]]:
    """The deployment rows, newest first by `(createdAt, id)` (plan P4).

    A `null` or absent `meta` is unavailable identity, not a violation: its `commit` and
    `branch` are `None`, so the row never matches.
    """
    if not isinstance(payload, list):
        raise _Invalid("deployment list is not a list")
    rows = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise _Invalid(f"deployment {index} is not an object")
        for name in ("id", "status", "createdAt"):
            if not _text(entry.get(name)):
                raise _Invalid(f"deployment {index} {name} is not a non-empty string")
        try:
            created = datetime.fromisoformat(entry["createdAt"].replace("Z", "+00:00"))
        except ValueError:
            created = None
        if created is None or created.tzinfo is None:
            raise _Invalid(f"deployment {index} createdAt is not an ISO 8601 time with an offset")
        meta = entry.get("meta")
        if meta is not None and not isinstance(meta, dict):
            raise _Invalid(f"deployment {index} meta is not an object or null")
        commit = branch = None
        if meta:
            commit, branch = meta.get("commitHash"), meta.get("branch")
            if commit is not None and not (isinstance(commit, str)
                                           and ROW_SHA.fullmatch(commit) is not None):
                raise _Invalid(f"deployment {index} meta.commitHash is not 40 hex characters")
            if branch is not None and not isinstance(branch, str):
                raise _Invalid(f"deployment {index} meta.branch is not a string")
            commit = commit.lower() if commit is not None else None
        rows.append({"key": (created, entry["id"]), "id": entry["id"],
                     "status": entry["status"], "commit": commit, "branch": branch})
    rows.sort(key=lambda row: row["key"], reverse=True)
    return rows


class _Service:
    """One service's reading and classification; `public()` is its `facts.services` entry."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.outcome, self.reason, self.detail = "unknown", "lookup_failed", ""
        self.rows: list[dict[str, Any]] = []
        self.matched: int | None = None
        self.serving: dict[str, Any] | None = None
        self.pending_skip = False
        self.skip_evidence: str | None = None
        self.code_gap: str | None = None

    def set(self, outcome: str, reason: str, detail: str = "") -> None:
        self.outcome, self.reason, self.detail = outcome, reason, detail

    @property
    def deployment(self) -> str | None:
        return None if self.matched is None else self.rows[self.matched]["id"]

    def public(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "service": self.name, "outcome": self.outcome, "reason": self.reason,
            "deployment": self.deployment,
            "status": None if self.matched is None else self.rows[self.matched]["status"],
            "serving": self.serving}
        if self.skip_evidence is not None:
            entry["skip_evidence"] = self.skip_evidence
        return entry


def _classify(service: _Service, rows: list[dict[str, Any]], released: str, branch: str) -> None:
    """Plan P5 steps 1 to 8, in order, except that a skip stays pending its evidence."""
    service.rows = rows
    serving = next((index for index, row in enumerate(rows) if row["status"] in SERVING), None)
    if serving is not None:
        service.serving = {"id": rows[serving]["id"], "commit": rows[serving]["commit"]}
    matched = next((index for index, row in enumerate(rows)
                    if row["commit"] == released and row["branch"] == branch), None)
    service.matched = matched
    if matched is None:
        service.set("absent", "deployment_absent")
        return
    if serving is not None and serving < matched:
        service.set("diverged", "superseded")
        return
    status = rows[matched]["status"]
    if status in IN_PROGRESS:
        service.set("in_progress", "deployment_in_progress")
    elif status in SERVING:
        service.set("satisfied", "deployed")
    elif status == "SKIPPED":
        service.pending_skip = True
        service.set("unknown", "skip_unexplained")
    elif status in FAILED:
        service.set("diverged", "silent_rollback" if serving is not None else "deployment_failed")
    elif status in REMOVED:
        service.set("diverged", "removed")
    else:
        service.set("unknown", "status_unrecognized", f"deployment status {status!r}")


def _code_gap(service: _Service, branch: str) -> str | None:
    """The first missing piece of the code evidence that needs no read, or None (plan P5.5)."""
    older = service.matched + 1  # type: ignore[operator]
    if older >= len(service.rows):
        return "no_serving_deployment"
    row = service.rows[older]
    if row["status"] not in SERVING:
        return "intervening_deployment"
    if row["commit"] is None or row["branch"] != branch:
        return "serving_identity_unknown"
    return None


def _check_runs(repository: str, commit: str, deadline: float
                ) -> tuple[str, dict[str, Any] | None]:
    """`(verdict, facts)` of the released commit's check runs, read once.

    `verdict` is `failed` (a completed run outside `BENIGN_CONCLUSIONS`), `complete` (every
    run completed and benign) or the missing piece: `checks_unread`, `checks_none`,
    `checks_over_limit` or `checks_incomplete`.
    """
    status, payload, _ = release_merge.gh(check_runs_argv(repository, commit), deadline)
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    total = payload.get("total_count") if isinstance(payload, dict) else None
    if (status != "ok" or type(total) is not int or not isinstance(runs, list)
            or not all(isinstance(run, dict) and isinstance(run.get("status"), str)
                       and (run.get("conclusion") is None
                            or isinstance(run.get("conclusion"), str)) for run in runs)):
        return "checks_unread", None
    conclusions: dict[str, int] = {}
    for run in runs:
        label = run["conclusion"] or run["status"]
        conclusions[label] = conclusions.get(label, 0) + 1
    facts = {"total": total, "conclusions": conclusions}
    if any(run["status"] == "completed" and run["conclusion"] is not None
           and run["conclusion"] not in BENIGN_CONCLUSIONS for run in runs):
        return "failed", facts
    if total == 0:
        return "checks_none", facts
    if total > CHECK_RUN_LIMIT:
        return "checks_over_limit", facts
    if (len(runs) != total or any(run["status"] != "completed" or run["conclusion"] is None
                                  for run in runs)):
        return "checks_incomplete", facts
    return "complete", facts


def _first_parent(repository: str, commit: str, deadline: float) -> str | None:
    """The first parent of `commit`, or None when it cannot be read as a list of shas."""
    status, payload, _ = release_merge.gh(parent_argv(repository, commit), deadline)
    parents = payload.get("parents") if isinstance(payload, dict) else None
    if (status != "ok" or not isinstance(parents, list) or not parents
            or not all(isinstance(parent, dict) and _hex40(parent.get("sha"))
                       for parent in parents)):
        return None
    return parents[0]["sha"]


class _Reading:
    """What one inspect read: the released commit, the services, the evidence and references."""

    def __init__(self, parameters: dict[str, Any]) -> None:
        self.services_config = list(parameters["config"]["services"])
        self.released: str | None = None
        self.failure: dict[str, str] | None = None
        self.references: list[str] = []
        self.services: list[_Service] = []
        self.check_runs: dict[str, Any] | None = None
        self.evidence_references: list[str] = []


def _read(parameters: dict[str, Any], deadline: float) -> _Reading:
    """Plan steps 1 to 4: the released commit, the linkage, each service and the skip evidence."""
    reading = _Reading(parameters)
    target, config = parameters["target"], parameters["config"]
    released, failure, reading.references = release_merge.released_commit(parameters, deadline)
    reading.released = released
    if failure is not None:
        reading.failure = failure
        return reading
    assert released is not None
    status, payload, detail = _railway(list(STATUS_ARGV), deadline)
    if status != "ok":
        reading.failure = {"outcome": "unknown", "reason": status, "detail": detail}
        return reading
    edges = (payload.get("environments", {}).get("edges")
             if isinstance(payload, dict) and isinstance(payload.get("environments"), dict)
             else None)
    names = ([edge["node"].get("name") for edge in edges
              if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]
             if isinstance(edges, list) else [])
    if (not isinstance(payload, dict) or payload.get("name") != config["project"]
            or config["environment"] not in names):
        reading.failure = {"outcome": "unknown", "reason": "project_mismatch",
                           "detail": f"the linked project is not {config['project']} with "
                                     f"environment {config['environment']}"}
        return reading
    for name in config["services"]:
        service = _Service(name)
        reading.services.append(service)
        status, payload, detail = _railway(deployment_argv(name, config["environment"]),
                                           deadline)
        if status != "ok":
            service.set("unknown", status, detail)
            continue
        try:
            rows = _rows(payload)
        except _Invalid as error:
            service.set("unknown", "payload_invalid", str(error))
            continue
        _classify(service, rows, released, target["branch"])
    for service in reading.services:
        if service.deployment is not None:
            reading.references.append(
                f"railway:{config['project']}/{config['environment']}/{service.name}/"
                f"{service.deployment}")
    pending = [service for service in reading.services if service.pending_skip]
    if pending:
        _settle_skips(reading, pending, target, released, deadline)
    return reading


def _settle_skips(reading: _Reading, pending: list[_Service], target: dict[str, Any],
                  released: str, deadline: float) -> None:
    """Plan P5.5: classify each pending skip by its CI evidence and its code evidence."""
    repository = target["repository"]
    verdict, reading.check_runs = _check_runs(repository, released, deadline)
    reading.references.append(f"github:{repository}/commits/{released}/check-runs")
    if verdict == "failed":
        for service in pending:
            service.set("diverged", "skipped_after_ci_failure")
        return
    for service in pending:
        service.code_gap = _code_gap(service, target["branch"])
    parent = None
    if any(service.code_gap is None for service in pending):
        parent = _first_parent(repository, released, deadline)
        reading.references.append(f"github:{repository}/git/commits/{released}")
    for service in pending:
        gap = service.code_gap
        if gap is None:
            if parent is None:
                gap = "parent_unread"
            elif service.serving is None or service.serving["commit"] != parent:
                gap = "serving_not_parent"
        if gap is None and verdict != "complete":
            gap = verdict
        if gap is None:
            service.set("satisfied", "skipped")
            service.skip_evidence = "complete"
        else:
            service.set("unknown", "skip_unexplained", f"skip evidence: {gap}")
            service.skip_evidence = gap


def _aggregate(services: list[_Service]) -> _Service:
    """The service that decides the answer (plan P6): the first at the winning outcome."""
    for outcome in PRECEDENCE:
        for service in services:
            if service.outcome == outcome:
                return service
    raise ValueError("no services")


def _observation(reading: _Reading, outcome: str, reason: str, detail: str | None
                 ) -> dict[str, Any]:
    facts: dict[str, Any] = {"released": reading.released,
                             "services": [service.public() for service in reading.services]}
    if reading.check_runs is not None:
        facts["check_runs"] = reading.check_runs
    if detail:
        facts["detail"] = detail[:DETAIL_LIMIT]
    deployments = {name: None for name in reading.services_config}
    deployments.update({service.name: service.deployment for service in reading.services})
    return {"outcome": outcome, "reason": reason,
            "observed_subject": {"commit": reading.released, "deployments": deployments},
            "references": reading.references, "observed_at": _now_ms(), "facts": facts}


def _invalid(detail: str) -> dict[str, Any]:
    return {"outcome": "unknown", "reason": "parameters_invalid",
            "observed_subject": {"commit": None, "deployments": {}}, "references": [],
            "observed_at": _now_ms(), "facts": {"released": None, "services": [],
                                                "detail": detail[:DETAIL_LIMIT]}}


def _deploy(parameters: Any, deadline: float) -> dict[str, Any]:
    """The effect observation of one deploy request (plan P5, P6)."""
    problem = _parameters_problem(parameters)
    if problem is not None:
        return _invalid(problem)
    reading = _read(parameters, deadline)
    if reading.failure is not None:
        failure = reading.failure
        return _observation(reading, failure["outcome"], failure["reason"], failure["detail"])
    decisive = _aggregate(reading.services)
    return _observation(reading, decisive.outcome, decisive.reason, decisive.detail)


def _running_state(service: _Service) -> str:
    """`running`, `not_running` or `unobservable` for one service (plan P7)."""
    if service.outcome == "satisfied":
        return "running"
    if service.outcome == "unknown":
        return "unobservable"
    return "not_running"


def _running(parameters: Any, deadline: float) -> dict[str, Any]:
    """The `running_subject_identity` answer, always in its derived reason space (plan P7)."""
    reading = _read(parameters, deadline)
    states = [_running_state(service) for service in reading.services]
    if reading.failure is not None or "unobservable" in states:
        outcome, reason = "unknown", "identity_unobservable"
    elif "not_running" in states:
        outcome, reason = "unsatisfied", "subject_mismatch"
    else:
        outcome, reason = "satisfied", "running"
    return {"outcome": outcome, "reason": reason, "references": reading.references,
            "observed_at": _now_ms()}


def inspect(request: Any) -> dict[str, Any]:
    """The observation of one request. Never raises and never mutates."""
    deadline = time.monotonic() + COLLECTION_BUDGET_SECONDS
    if isinstance(request, dict) and request.get("kind") == "predicate":
        if request.get("predicate") != "running_subject_identity":
            return {"outcome": "unknown", "reason": "predicate_unsupported", "references": [],
                    "observed_at": _now_ms()}
        if (set(request) == {"kind", "predicate", "operation", "parameters"}
                and request["operation"] == "deploy"
                and _parameters_problem(request["parameters"]) is None):
            return _running(request["parameters"], deadline)
        return {"outcome": "unknown", "reason": "identity_unobservable", "references": [],
                "observed_at": _now_ms()}
    if (isinstance(request, dict) and set(request) == {"kind", "operation", "parameters"}
            and request["kind"] == "effect"):
        if request["operation"] == "deploy":
            return _deploy(request["parameters"], deadline)
        return _invalid(f"unknown operation {request['operation']!r}")
    return _invalid("request is not a closed effect or predicate request")


def invoke(request: Any) -> dict[str, Any]:
    """Refuse every request: the deploy operation is watch-only and starts no child process."""
    return {"result": "rejected", "error_class": "unsupported_operation",
            "reference": "deploy: watch_only"}
