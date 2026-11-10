"""The GitHub Actions deploy-watch adapter (issue 465 D2, D6-D8, D14; issue 555 D3, D6, D9): `describe`, `inspect`, `invoke`.

These three functions are the adapter's whole public surface (#124 D7). `describe()` returns a
fresh descriptor with one operation, `deploy`: a watch-only `publication_triggered` activation
unit a release profile may bind (issue 555 D3). It is supported for `inspect`, and `invoke`
refuses every request (`watch_only`), so the adapter never changes the world. It also answers
the `running_subject_identity` predicate by reading the health commit of the released commit.
Its closed config is `workflow`, `branch`, `services` (a `string_list`), `health_url` and
`health_commit_field`.

This module imports only the standard library, `agent_tools.canonical` and
`agent_tools.release_merge`: the registry in
`release_adapter` imports it, never the reverse, so its inner checks are its own (D14).

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid`; a predicate request naming anything but `running_subject_identity`
is `unknown`/`predicate_unsupported`, and every non-`satisfied` answer for that predicate stays in
its derived reason space (D9). The released commit is `candidate.commit`, or, when the candidate
binds a `merge`, the merge commit of that release PR (D6). Otherwise it runs `gh run list` by
name with the caller's environment unchanged (the caller applies the tracker's credential
binding, D10) and, only when the newest run at the released commit on the configured branch is
completed, one `GET` of the health URL that follows no redirect and reads at most
`HEALTH_BODY_LIMIT` bytes, all under one `COLLECTION_BUDGET_SECONDS` deadline. `satisfied` needs a `success` run whose commit the health
endpoint also reports (D6, D7).

`invoke(request)` refuses every request with `unsupported_operation` and starts no child process.

It is registered as `github-actions-health` at contract version 1.1.0. Its closed config is
all required; `services` is the `string_list` config type, a non-empty list of unique
non-empty strings. The target is a `github_repository` of `kind`, `repository` and `branch`
with one optional `handle`, the name the compiled profile carries and `CoreBinding` forwards;
a `handle` that is not a non-empty string is `parameters_invalid`. The candidate is exactly
`{commit}`, `{version, commit}` or `{version, commit, merge}`, where `merge` is `{pr,
base_tip}`.

With a `merge`, the released commit is the merge commit of that release PR (issue 555 D6):
`gh pr view <pr> --json state,baseRefName,mergeCommit`, then for `MERGED` one `gh api
repos/<slug>/git/commits/<oid>`, all under the one budget. `OPEN` is `absent`
(`release_unmerged`); `CLOSED`, another base branch or parents other than `[merge.base_tip,
candidate.commit]` is `diverged` (`release_merge_mismatch`); any other state or a malformed
`mergeCommit` or parents list is `unknown` (`payload_invalid`); and a failed read is `unknown`
with the run-list read statuses. An unresolved merge reads neither the run list nor the health
URL. Every effect observation's `facts.released` is the released commit, or `None` when
unresolved.

`running_subject_identity` makes no run-list read: it reads the merge (when bound) and one
health URL, and is `satisfied` (`running`) when the health commit names the released commit,
`unsatisfied` (`subject_mismatch`) when it does not, and otherwise `unknown`
(`identity_unobservable`). `release_adapter.watch_operation(descriptor)` names a descriptor's
single inspectable `publication_triggered` operation, or returns `None` when there is none or
more than one.

`inspect` answers `parameters_invalid` unless the request carries a target and candidate of
the shapes above, with a 40-lowercase-hex candidate `commit`, a `vMAJOR.MINOR.PATCH` `version`
when present, and a config of exactly the five members, whose `string` members are non-empty
and free of control characters, whose `services` is a non-empty list of unique non-empty
strings, whose `branch` equals the target's, and whose `health_url` parses with
`urllib.parse.urlsplit` and is `http` or `https` with a host. It then makes at most two reads
under one 30-second budget. The first is `gh run list --repo <repository> --workflow
<workflow> --branch <branch> --limit 5 --json databaseId,status,conclusion,headSha,headBranch,
createdAt`, run by name; the adapter strips no variable, and the release driver applies
`bindings.tracker.credential_env` (D10). The second, made only when the newest run at the
candidate on that branch is completed, is one `GET <health_url>` that follows no redirect,
reads at most 65,536 bytes and loads the body strictly through the `canonical` hooks (D8).
Runs are ordered newest first by `createdAt`, which must be an ISO 8601 time with an offset
(D14), and a commit matches when it is 7 to 40 hex characters and the candidate starts with
it, case-insensitively (D7).

The outcome follows the spec's classification table (D6): `absent` (`run_absent`);
`in_progress` (`run_in_progress`); `satisfied` (`deployed`) only for a `success` run whose
health commit matches; `diverged` (`superseded`) for a completed, unsatisfied run that a run at
another commit followed; otherwise `diverged` (`health_commit_mismatch`, `silent_rollback` or
`run_failed`) or `unknown` (`health_unreachable` or `health_payload_invalid`). A failed run-list
read is `unknown`, with `facts.detail` bounded to 240 characters: `lookup_failed` carries the
stderr of a non-zero exit, or `gh could not be started: <error>` when the operating system
refuses the argument list; `lookup_timeout` carries an empty detail; `executable_missing`
carries the operating-system error; and `payload_invalid` carries the stderr when stdout is
not JSON, or the first shape violation (for example `run 0 headSha is not 40 hex characters`)
when the JSON is not the closed run-list shape. Every effect observation's `facts` hold `runs`
(each `{id, status, commit, branch, createdAt}`, newest first), `run`, `health`, the
configured `services` and `released`. `tests/actions_world.py` is its fake `gh`, which logs
token visibility, and loopback HTTP server.
"""

import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from agent_tools import release_merge
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

COLLECTION_BUDGET_SECONDS = 30
DETAIL_LIMIT = release_merge.DETAIL_LIMIT
HEALTH_BODY_LIMIT = 65536
RUN_LIMIT = 5
RUN_FIELDS = "databaseId,status,conclusion,headSha,headBranch,createdAt"
USER_AGENT = "agent-tools-github-actions-health/1.1.0"
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}")
RUN_SHA = re.compile(r"[0-9A-Fa-f]{40}")
REPORTED_SHA = re.compile(r"[0-9A-Fa-f]{7,40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
CONFIG_MEMBERS = {"workflow": "string", "branch": "string", "services": "string_list",
                  "health_url": "string", "health_commit_field": "string"}
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
TARGET_MEMBERS = frozenset(("kind", "repository", "branch"))
MERGE_MEMBERS = frozenset(("pr", "base_tip"))
CANDIDATE_SHAPES = (frozenset(("commit",)), frozenset(("version", "commit")),
                    frozenset(("version", "commit", "merge")))
REQUIRED = frozenset(("target", "candidate", "config"))
TOLERATED = frozenset(("action", "operation"))


def describe() -> dict[str, Any]:
    """The `github-actions-health` descriptor (issue 465 D2), a fresh plain dict."""
    return {
        "name": "github-actions-health",
        "adapter_contract_version": "1.1.0",
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
        "credential_classes": ["gh_cli"],
        "executables": ["gh"],
        "host_capacity": "not_required",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _observation(outcome: str, reason: str, *, runs: list[dict[str, Any]] | None = None,
                 run: dict[str, Any] | None = None, health: dict[str, Any] | None = None,
                 services: list[str] | None = None, references: list[str] | None = None,
                 detail: str | None = None, released: str | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {"runs": runs or [], "run": run, "health": health,
                             "services": services or [], "released": released}
    if detail is not None:
        facts["detail"] = detail[:DETAIL_LIMIT]
    return {"outcome": outcome, "reason": reason,
            "observed_subject": {"commit": health["commit"] if health else None,
                                 "run": run["id"] if run else None},
            "references": references or [], "observed_at": _now_ms(), "facts": facts}


def _matches(reported: str, commit: str) -> bool:
    """Whether a reported 7 to 40 hex prefix names `commit`, case-insensitively (D7)."""
    return REPORTED_SHA.fullmatch(reported) is not None and commit.startswith(reported.lower())


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
    """The first way `parameters` departs from the closed deploy shape, or None (D14)."""
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
    if config["branch"] != branch:
        return "config branch differs from the target branch"
    try:
        split = urllib.parse.urlsplit(config["health_url"])
        host = split.hostname
    except ValueError as error:
        return f"config health_url does not parse: {error}"
    if split.scheme not in ("http", "https") or not host:
        return "config health_url is not an http or https URL with a host"
    return None


def _run_list(slug: str, workflow: str, branch: str, deadline: float) -> tuple[str, Any, str]:
    """`gh run list` for the workflow on the branch: the `release_merge.gh` answer."""
    return release_merge.gh(["run", "list", "--repo", slug, "--workflow", workflow,
                             "--branch", branch, "--limit", str(RUN_LIMIT), "--json",
                             RUN_FIELDS], deadline)


class _Invalid(Exception):
    """A run-list payload outside the closed entry shape: `payload_invalid` with this detail."""


def _entries(payload: Any) -> list[tuple[tuple[datetime, int], bool, dict[str, Any]]]:
    """`(sort key, completed, mapped entry)` per run, newest first (D14)."""
    if not isinstance(payload, list):
        raise _Invalid("run list is not a list")
    entries = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise _Invalid(f"run {index} is not an object")
        run_id = entry.get("databaseId")
        if type(run_id) is not int or run_id < 1:
            raise _Invalid(f"run {index} databaseId is not a positive integer")
        for name in ("status", "headBranch", "createdAt"):
            if not _text(entry.get(name)):
                raise _Invalid(f"run {index} {name} is not a non-empty string")
        sha = entry.get("headSha")
        if not isinstance(sha, str) or RUN_SHA.fullmatch(sha) is None:
            raise _Invalid(f"run {index} headSha is not 40 hex characters")
        completed = entry["status"] == "completed"
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or (completed and not conclusion):
            raise _Invalid(f"run {index} conclusion is not a string, non-empty when completed")
        try:
            created = datetime.fromisoformat(entry["createdAt"])
        except ValueError:
            created = None
        if created is None or created.tzinfo is None:
            raise _Invalid(f"run {index} createdAt is not an ISO 8601 time with an offset")
        entries.append(((created, run_id), completed, {
            "id": run_id, "status": conclusion if completed else entry["status"],
            "commit": sha, "branch": entry["headBranch"], "createdAt": entry["createdAt"]}))
    entries.sort(key=lambda item: item[0], reverse=True)
    return entries


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow no redirect: urllib then raises the 3xx as an `HTTPError` (D8)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _health(url: str, field: str, deadline: float) -> dict[str, Any]:
    """`{status, http_status, commit, detail}` of one strict, bounded health read (D8)."""
    def result(status: str, http_status: int | None = None, commit: str | None = None,
               detail: str | None = None) -> dict[str, Any]:
        return {"status": status, "http_status": http_status, "commit": commit,
                "detail": None if detail is None else detail[:DETAIL_LIMIT]}

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return result("health_unreachable", detail="the collection budget is spent")
    seen: dict[str, Any] = {}

    def read() -> None:
        """The read, in a daemon thread joined for the remaining budget (D18)."""
        request = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": USER_AGENT})
        try:
            with urllib.request.build_opener(_NoRedirect).open(request,
                                                               timeout=remaining) as response:
                seen["http_status"] = response.status
                seen["body"] = response.read(HEALTH_BODY_LIMIT + 1)
        except urllib.error.HTTPError as error:
            seen["http_status"] = error.code
            try:
                text = error.read(DETAIL_LIMIT * 4).decode("utf-8", "replace")
                seen["failure"] = f"HTTP {error.code}: {text}"
            except (OSError, ValueError, http.client.HTTPException) as failure:
                seen["failure"] = f"HTTP {error.code}: {str(failure) or type(failure).__name__}"
            finally:
                error.close()
        except (OSError, ValueError, http.client.HTTPException) as error:
            seen["failure"] = str(error) or type(error).__name__

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        return result("health_unreachable", seen.get("http_status"),
                      detail="the budget ran out during the health read")
    if "body" not in seen:
        return result("health_unreachable", seen.get("http_status"),
                      detail=seen.get("failure", "no body was read"))
    status, body = seen["http_status"], seen["body"]
    if status != 200:
        text = body[:DETAIL_LIMIT * 4].decode("utf-8", "replace")
        return result("health_unreachable", status, detail=f"HTTP {status}: {text}")
    if len(body) > HEALTH_BODY_LIMIT:
        return result("health_payload_invalid", status,
                      detail=f"the body exceeds {HEALTH_BODY_LIMIT} bytes")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError) as error:
        return result("health_payload_invalid", status, detail=f"the body is not strict JSON: {error}")
    commit = value.get(field) if isinstance(value, dict) else None
    if not isinstance(commit, str) or REPORTED_SHA.fullmatch(commit) is None:
        return result("health_payload_invalid", status,
                      detail=f"top-level {field} is not 7 to 40 hex characters")
    return result("ok", status, commit)


def _deploy(parameters: Any, deadline: float) -> dict[str, Any]:
    """The effect observation of one deploy request (D6): the spec's classification table."""
    problem = _parameters_problem(parameters)
    if problem is not None:
        return _observation("unknown", "parameters_invalid", detail=problem)
    target, config = parameters["target"], parameters["config"]
    services = list(config["services"])
    commit, failure, merge_references = release_merge.released_commit(parameters, deadline)
    if failure is not None:
        return _observation(failure["outcome"], failure["reason"], services=services,
                            references=merge_references, detail=failure["detail"])
    status, payload, detail = _run_list(target["repository"], config["workflow"],
                                        config["branch"], deadline)
    if status != "ok":
        return _observation("unknown", status, services=services, references=merge_references,
                            detail=detail, released=commit)
    try:
        entries = _entries(payload)
    except _Invalid as error:
        return _observation("unknown", "payload_invalid", services=services,
                            references=merge_references, detail=str(error), released=commit)
    runs = [entry for _, _, entry in entries]
    selected = next((index for index, (_, _, entry) in enumerate(entries)
                     if _matches(entry["commit"], commit) and entry["branch"] == config["branch"]),
                    None)
    if selected is None:
        return _observation("absent", "run_absent", runs=runs, services=services,
                            references=merge_references, released=commit)
    _, completed, run = entries[selected]
    references = [*merge_references, f"repos/{target['repository']}/actions/runs/{run['id']}"]
    if not completed:
        return _observation("in_progress", "run_in_progress", runs=runs, run=run,
                            services=services, references=references, released=commit)
    health = _health(config["health_url"], config["health_commit_field"], deadline)
    references.append(config["health_url"])
    matched = health["status"] == "ok" and _matches(health["commit"], commit)
    newer = any(not _matches(entry["commit"], commit) for _, _, entry in entries[:selected])
    if run["status"] == "success" and matched:
        outcome, reason = "satisfied", "deployed"
    elif newer:
        outcome, reason = "diverged", "superseded"
    elif run["status"] == "success":
        outcome, reason = (("diverged", "health_commit_mismatch") if health["status"] == "ok"
                           else ("unknown", health["status"]))
    elif health["status"] == "ok" and not matched:
        outcome, reason = "diverged", "silent_rollback"
    else:
        outcome, reason = "diverged", "run_failed"
    return _observation(outcome, reason, runs=runs, run=run, health=health, services=services,
                        references=references, released=commit)


def _running(parameters: Any, deadline: float) -> dict[str, Any]:
    """The `running_subject_identity` answer: the health commit against the released commit.

    Every non-`satisfied` answer is in the derived reason space (issue 555 D9): an unresolved
    merge and a health read that is not `ok` are `identity_unobservable`. No run list is read.
    """
    def answer(outcome: str, reason: str, references: list[str]) -> dict[str, Any]:
        return {"outcome": outcome, "reason": reason, "references": references,
                "observed_at": _now_ms()}

    commit, failure, references = release_merge.released_commit(parameters, deadline)
    if failure is not None:
        return answer("unknown", "identity_unobservable", references)
    config = parameters["config"]
    health = _health(config["health_url"], config["health_commit_field"], deadline)
    references = [*references, config["health_url"]]
    if health["status"] != "ok":
        return answer("unknown", "identity_unobservable", references)
    if _matches(health["commit"], commit):
        return answer("satisfied", "running", references)
    return answer("unsatisfied", "subject_mismatch", references)


def inspect(request: Any) -> dict[str, Any]:
    """The observation of one request. Never raises and never mutates (issue 465 D6)."""
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
        return _observation("unknown", "parameters_invalid",
                            detail=f"unknown operation {request['operation']!r}")
    return _observation("unknown", "parameters_invalid",
                        detail="request is not a closed effect or predicate request")


def invoke(request: Any) -> dict[str, Any]:
    """Refuse every request: the deploy operation is watch-only and starts no child process (D3)."""
    return {"result": "rejected", "error_class": "unsupported_operation",
            "reference": "deploy: watch_only"}
