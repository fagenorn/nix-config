"""The Railway deploy-watch adapter (issue 582 P1-P7; the issue 555 watch design): `describe`, `inspect`, `invoke`.

These three functions are the adapter's whole public surface (#124 D7). `describe()` returns a
fresh descriptor with one operation, `deploy`: a watch-only `publication_triggered` activation
unit a release profile may bind. It is supported for `inspect`, and `invoke` refuses every
request (`watch_only`), so the adapter never changes the world. It also answers the
`running_subject_identity` predicate from the same reading. Its closed config is `project`,
`environment` and `services` (a `string_list`); its target is the `github_repository` the
release was published on, which resolves the released commit exactly as the issue 555 adapter does.

This module imports only the standard library, `agent_tools.canonical` and
`agent_tools.release.release_merge`: the registry in `release_adapter` imports it, never the reverse.

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid` for an effect and `unknown`/`identity_unobservable` for a
predicate (whose derived reason space has no `parameters_invalid`); a predicate naming anything
but `running_subject_identity` is `unknown`/`predicate_unsupported`. Neither starts a child
process. Otherwise, under one `COLLECTION_BUDGET_SECONDS` deadline and with the caller's
environment unchanged, it resolves the released commit, reads `railway status --json` to check
the linked project and environment, then one `railway deployment list ... --json` per service
and classifies each service by plan P5, in order. Only read-only `railway` verbs are ever run.

A `SKIPPED` deployment is `satisfied` only with affirmative evidence that the service serves
what the released commit would build. Railway skips a push both when no watched path changed
and after failed or timed-out CI, so a skip alone proves nothing. Two routes explain one:

- the CI route (plan P5.5): the released commit's GitHub check runs (every attempt, re-runs
  included) are all green with no check ever re-run, and the serving deployment is the skipped
  push's immediate predecessor at the released commit's first parent;
- the watch-path route (ADR-release-013), tried when the CI route has a gap: Railway states
  `meta.skippedReason` `No changes to watched files` on the skipped row; the first older row
  that is not itself `SKIPPED` is serving, on the target branch, with a commit and the same
  `meta.rootDirectory`; the skipped row's `meta.serviceManifest.build.watchPatterns` is absent
  or exactly `["**"]`; and GitHub's compare of the serving commit with the released commit
  shows the serving commit is an ancestor and fewer than `COMPARE_FILE_LIMIT` changed files,
  none of them (nor a rename's previous name) under the root directory or equal to
  `meta.configFile`. Which release deployed the serving row, and how that release was
  disposed, is not read: a `SUCCESS` row is the service's own evidence.

A failed check is `diverged`/`skipped_after_ci_failure` on either route. Anything short of one
complete route is `unknown`/`skip_unexplained`, a conservative answer the driver waits on and
then parks, never a false success; its references then end with one
`railway-skip:<service>/<ci gap>/<watch gap>` entry per unexplained service, so the park reason
names what was missing.

It is registered as `railway-deploy` at contract version 1.0.0, a second watch-only adapter
beside `github-actions-health`. Its target is a `github_repository` (`kind`, `repository`,
`branch`, plus the compiled `handle`), so the released commit resolves through
`release_merge` exactly as it does there (issue 555 D6). Its closed config is `project`,
`environment` and `services` (a non-empty `string_list`), all required. Its executables are
`gh` and `railway`.

The `railway` it runs is the one on the release's PATH, which the project's dev shell provides:
no host installs it system-wide (issue 1124). A missing command is `unknown`
(`executable_missing`), and a nonzero exit carrying Railway's `Unauthorized` or `Not
authenticated` marker is `unknown` (`railway_unauthorized`). Each of them, whether it ends the
status read or any service's read, ends the observation's references with one `next-step:`
entry (after every other reference, once), so the park reason says what to do: run the release
from the project's dev shell, or run `railway login` there. No other reason carries one, and the
`running_subject_identity` answer carries the same references.

`inspect` reads `railway status --json` first, whose linked project `name` must equal
`config.project` and which must list an environment named `config.environment` (else
`unknown`, `project_mismatch`), then `railway deployment list --service <s> --environment
<env> --json` once per service in config order, under one 30-second budget. Each service is
classified newest first by `createdAt`, then `id`, in this order:

- no deployment at the released commit on the target branch is `absent`
  (`deployment_absent`);
- a serving (`SUCCESS` or `SLEEPING`) deployment newer than the matched one is `diverged`
  (`superseded`), before the matched status is read;
- `QUEUED`, `WAITING`, `INITIALIZING`, `BUILDING`, `DEPLOYING` or `NEEDS_APPROVAL` is
  `in_progress` (`deployment_in_progress`);
- `SUCCESS` or `SLEEPING` is `satisfied` (`deployed`);
- `SKIPPED` is `satisfied` (`skipped`) only by one of the two routes above, otherwise `unknown`
  (`skip_unexplained`) or, after a failed check, `diverged` (`skipped_after_ci_failure`);
- `FAILED` or `CRASHED` is `diverged` (`silent_rollback` with an older serving deployment,
  else `deployment_failed`);
- `REMOVED` or `REMOVING` is `diverged` (`removed`);
- any other status is `unknown` (`status_unrecognized`).

The services aggregate with the precedence `diverged`, `unknown`, `in_progress`, `absent`,
`satisfied`, and the reason is the first service's, in config order, at the winning outcome.
`running_subject_identity` is `satisfied` (`running`) when every service is deployed or a
benign skip, `unknown` (`identity_unobservable`) when any service is unobservable, and
otherwise `unsatisfied` (`subject_mismatch`). The release driver waits on `in_progress` and
`absent` within the unit's `observation_deadline_ms` and parks `attention_required` past it,
so an absent deployment is never a success. `tests/railway_world.py` is its fake `gh` and
`railway`.
"""

import json
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agent_tools.release import release_merge
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

COLLECTION_BUDGET_SECONDS = 30
DETAIL_LIMIT = release_merge.DETAIL_LIMIT
CHECK_RUN_LIMIT = 100
BENIGN_CONCLUSIONS = ("success", "neutral", "skipped")
SKIP_REASON_UNWATCHED = "No changes to watched files"
COMPARE_FILE_LIMIT = 300
WHOLE_ROOT_PATTERNS = (None, ["**"])
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
# The Railway CLI's own auth-failure markers: `AUTH_FAILURE_MARKERS` in railwayapp/cli
# `src/errors.rs`, which prints `Unauthorized. Please login with `railway login`` and the like.
AUTH_FAILURE_MARKERS = ("Unauthorized", "Not authenticated")
NEXT_STEPS = {
    "executable_missing": (
        "next-step:no railway command was found on PATH; no host installs railway "
        "system-wide, so run the release from the project's own environment (its dev shell, "
        "for example devenv shell), which provides railway"),
    "railway_unauthorized": (
        "next-step:Railway refused the sign-in; run `railway login` in the project's own "
        "environment, then run the release again"),
}


def deployment_argv(service: str, environment: str) -> list[str]:
    """The read-only deployment list of one service (plan P4)."""
    return ["deployment", "list", "--service", service, "--environment", environment, "--json"]


def check_runs_argv(repository: str, commit: str) -> list[str]:
    """The check runs of a commit as an explicit GET, run through `release_merge.gh`.

    `filter=all` keeps the superseded attempts of a re-run: the default `latest` hides an
    earlier failure once the same check turns green.
    """
    return ["api", "-X", "GET", f"repos/{repository}/commits/{commit}/check-runs", "-f",
            f"per_page={CHECK_RUN_LIMIT}", "-f", "filter=all"]


def parent_argv(repository: str, commit: str) -> list[str]:
    """The git commit (its parents) as an explicit GET, run through `release_merge.gh`."""
    return ["api", "-X", "GET", f"repos/{repository}/git/commits/{commit}"]


def compare_argv(repository: str, base: str, head: str) -> list[str]:
    """The comparison of two commits (ancestry and changed files) as an explicit GET."""
    return ["api", "-X", "GET", f"repos/{repository}/compare/{base}...{head}"]


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
    or `lookup_failed`, `lookup_timeout`, `payload_invalid`, `executable_missing` and
    `railway_unauthorized` with a payload of `None`. `railway_unauthorized` is a nonzero exit
    whose stderr or stdout carries one of `AUTH_FAILURE_MARKERS`; any other nonzero exit is
    `lookup_failed`, and a zero exit is never `railway_unauthorized`. The child inherits the
    environment unchanged.
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
        refused = any(marker in done.stderr or marker in done.stdout
                      for marker in AUTH_FAILURE_MARKERS)
        return ("railway_unauthorized" if refused else "lookup_failed"), None, detail
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
    `branch` are `None`, so the row never matches. The watch-path members (`skipped_reason`,
    `root`, `patterns`, `config_file`) are read leniently: `root` and `patterns` are `False`
    when present in another shape, which the watch-path route refuses.
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
        scope = _watch_scope(meta or {})
        if meta:
            commit, branch = meta.get("commitHash"), meta.get("branch")
            if commit is not None and not (isinstance(commit, str)
                                           and ROW_SHA.fullmatch(commit) is not None):
                raise _Invalid(f"deployment {index} meta.commitHash is not 40 hex characters")
            if branch is not None and not isinstance(branch, str):
                raise _Invalid(f"deployment {index} meta.branch is not a string")
            commit = commit.lower() if commit is not None else None
        rows.append({"key": (created, entry["id"]), "id": entry["id"],
                     "status": entry["status"], "commit": commit, "branch": branch, **scope})
    rows.sort(key=lambda row: row["key"], reverse=True)
    return rows


def _watch_patterns(manifest: Any) -> Any:
    """The skipped row's `build.watchPatterns`: `None` when a member is absent or null, `False`
    when a container or the list itself is present in another shape (never read as absent)."""
    if manifest is None:
        return None
    if not isinstance(manifest, dict):
        return False
    build = manifest.get("build")
    if build is None:
        return None
    if not isinstance(build, dict):
        return False
    patterns = build.get("watchPatterns")
    if patterns is not None and not (isinstance(patterns, list)
                                     and all(isinstance(item, str) for item in patterns)):
        return False
    return patterns


def _watch_scope(meta: dict[str, Any]) -> dict[str, Any]:
    """What a row says about its skip and its watched tree (ADR-release-013)."""
    reason, root, config = (meta.get("skippedReason"), meta.get("rootDirectory"),
                            meta.get("configFile"))
    patterns = _watch_patterns(meta.get("serviceManifest"))
    if root is None:
        root = ""
    root = _clean_path(root)
    if config is not None:
        config = _clean_path(config)
        config = None if config == "" else config
    return {"skipped_reason": reason if isinstance(reason, str) else None,
            "root": root,
            "patterns": patterns,
            "config_file": config}


def _clean_path(path: Any) -> str | bool:
    """A repository-relative path without empty or `.` segments, or `False` when it is not a
    string or climbs out with `..` (never read as absent)."""
    if not isinstance(path, str):
        return False
    segments = [part for part in path.split("/") if part not in ("", ".")]
    return False if ".." in segments else "/".join(segments)


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
        self.watch_evidence: str | None = None
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
        if self.watch_evidence is not None:
            entry["watch_evidence"] = self.watch_evidence
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

    `verdict` is `failed` (the latest attempt of a check completed outside
    `BENIGN_CONCLUSIONS`), `complete` (every run completed and benign, and no check was ever
    re-run) or the missing piece: `checks_unread`, `checks_none`, `checks_over_limit`,
    `checks_incomplete` or `checks_rerun`. A re-run is never `complete`: CI that failed, caused
    Railway's skip and then turned green leaves the older serving row without the candidate's
    changes, and no reading shows that the skip was about unchanged watch paths instead.

    A check is one name within one check suite (`check_suite.id`, absent read as one shared
    suite): a re-run adds a run of the same name to the same suite, while two workflows that
    each publish a job of one name have a suite each and are two checks, not a re-run. A new
    workflow run of the same commit is a new suite, so its earlier failure stays the latest
    of its own check and reads `failed`.
    """
    status, payload, _ = release_merge.gh(check_runs_argv(repository, commit), deadline)
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    total = payload.get("total_count") if isinstance(payload, dict) else None
    if (status != "ok" or type(total) is not int or not isinstance(runs, list)
            or not all(isinstance(run, dict) and type(run.get("id")) is int
                       and _text(run.get("name")) and isinstance(run.get("status"), str)
                       and "conclusion" in run
                       and (run["conclusion"] is None or isinstance(run["conclusion"], str))
                       for run in runs)):
        return "checks_unread", None
    conclusions: dict[str, int] = {}
    latest: dict[tuple[int | None, str], dict[str, Any]] = {}
    for run in runs:
        label = run["conclusion"] or run["status"]
        conclusions[label] = conclusions.get(label, 0) + 1
        suite = run.get("check_suite")
        suite = suite.get("id") if isinstance(suite, dict) else None
        check = (suite if type(suite) is int else None, run["name"])
        if check not in latest or run["id"] > latest[check]["id"]:
            latest[check] = run
    facts = {"total": total, "conclusions": conclusions}
    if any(run["status"] == "completed" and run["conclusion"] is not None
           and run["conclusion"] not in BENIGN_CONCLUSIONS for run in latest.values()):
        return "failed", facts
    if total == 0:
        return "checks_none", facts
    if total > CHECK_RUN_LIMIT:
        return "checks_over_limit", facts
    if (len(runs) != total or any(run["status"] != "completed" or run["conclusion"] is None
                                  for run in runs)):
        return "checks_incomplete", facts
    if len(latest) != len(runs):
        return "checks_rerun", facts
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


def _watch_serving(service: _Service, branch: str) -> dict[str, Any] | str:
    """The row serving under the skip, or the gap that leaves it unproven (ADR-release-013).

    Older `SKIPPED` rows are stepped over: a skipped push never served anything, and the
    comparison spans every commit between the serving row and the released one. Any other row
    that is not serving (failed, crashed, removed, in progress) stops the search, since the
    service may then be serving nothing.
    """
    matched = service.rows[service.matched]  # type: ignore[index]
    if matched["skipped_reason"] != SKIP_REASON_UNWATCHED:
        return "skip_reason_unstated"
    if (matched["root"] is False or matched["config_file"] is False
            or matched["patterns"] not in WHOLE_ROOT_PATTERNS):
        return "watch_patterns_unsupported"
    for row in service.rows[service.matched + 1:]:  # type: ignore[operator]
        if row["status"] == "SKIPPED":
            continue
        if row["status"] not in SERVING:
            return "intervening_deployment"
        if row["commit"] is None or row["branch"] != branch:
            return "serving_identity_unknown"
        if row["root"] != matched["root"]:
            return "root_directory_changed"
        return row
    return "no_serving_deployment"


def _compare(repository: str, base: str, head: str, deadline: float) -> list[str] | str:
    """Every path changed from `base` to `head`, or the gap: `base` must be an ancestor.

    GitHub returns at most `COMPARE_FILE_LIMIT` files, so a full page is unproven, not clean.
    """
    status, payload, _ = release_merge.gh(compare_argv(repository, base, head), deadline)
    files = payload.get("files") if isinstance(payload, dict) else None
    merge_base = payload.get("merge_base_commit") if isinstance(payload, dict) else None
    if (status != "ok" or not isinstance(files, list) or not isinstance(merge_base, dict)
            or not isinstance(payload.get("status"), str)
            or type(payload.get("behind_by")) is not int
            or not all(isinstance(entry, dict) and _text(entry.get("filename"))
                       and isinstance(entry.get("previous_filename", ""), str)
                       and (entry.get("status") != "renamed"
                            or _text(entry.get("previous_filename")))
                       for entry in files)):
        return "diff_unread"
    if (payload["status"] not in ("ahead", "identical") or payload["behind_by"] != 0
            or merge_base.get("sha") != base):
        return "serving_not_ancestor"
    if len(files) >= COMPARE_FILE_LIMIT:
        return "diff_over_limit"
    return [path for entry in files
            for path in (entry["filename"], entry.get("previous_filename")) if path]


def _watch_gap(service: _Service, target: dict[str, Any], released: str, deadline: float,
               reading: "_Reading") -> str | None:
    """The first missing piece of the watch-path evidence, or None (ADR-release-013)."""
    serving = _watch_serving(service, target["branch"])
    if isinstance(serving, str):
        return serving
    repository, base = target["repository"], serving["commit"]
    if base not in reading.comparisons:
        reading.comparisons[base] = _compare(repository, base, released, deadline)
        reading.references.append(f"github:{repository}/compare/{base}...{released}")
    changed = reading.comparisons[base]
    if isinstance(changed, str):
        return changed
    matched = service.rows[service.matched]  # type: ignore[index]
    prefix = f"{matched['root']}/" if matched["root"] else ""
    if any(path.startswith(prefix) or path == matched["config_file"] for path in changed):
        return "watched_path_changed"
    return None


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
        self.comparisons: dict[str, list[str] | str] = {}


def _next_step(reading: _Reading, reason: str) -> None:
    """End the references with the next step `reason` names, once (none for other reasons)."""
    step = NEXT_STEPS.get(reason)
    if step is not None and step not in reading.references:
        reading.references.append(step)


def linkage_problem(payload: object, config: Mapping[str, Any]) -> str | None:
    """Why the `railway status --json` payload is not the configured project and environment, or
    None when it is: the payload's `name` must equal `config["project"]`, and
    `config["environment"]` must be among `environments.edges[].node.name` (edges or nodes of
    another shape are skipped). `inspect` and `host-readiness` both apply this one rule."""
    edges = (payload.get("environments", {}).get("edges")
             if isinstance(payload, dict) and isinstance(payload.get("environments"), dict)
             else None)
    names = ([edge["node"].get("name") for edge in edges
              if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]
             if isinstance(edges, list) else [])
    if (not isinstance(payload, dict) or payload.get("name") != config["project"]
            or config["environment"] not in names):
        return (f"the linked project is not {config['project']} with "
                f"environment {config['environment']}")
    return None


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
        _next_step(reading, status)
        return reading
    problem = linkage_problem(payload, config)
    if problem is not None:
        reading.failure = {"outcome": "unknown", "reason": "project_mismatch", "detail": problem}
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
    for service in reading.services:
        _next_step(reading, service.reason)
    return reading


def _settle_skips(reading: _Reading, pending: list[_Service], target: dict[str, Any],
                  released: str, deadline: float) -> None:
    """Classify each pending skip: the CI route (plan P5.5), else the watch-path route."""
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
            continue
        watch = _watch_gap(service, target, released, deadline, reading)
        if watch is None:
            service.set("satisfied", "skipped")
            service.skip_evidence = "watch_paths_unchanged"
            continue
        service.set("unknown", "skip_unexplained",
                    f"skip evidence: {gap}; watch evidence: {watch}")
        service.skip_evidence, service.watch_evidence = gap, watch
    reading.references.extend(
        f"railway-skip:{service.name}/{service.skip_evidence}/{service.watch_evidence}"
        for service in pending if service.outcome == "unknown")


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
