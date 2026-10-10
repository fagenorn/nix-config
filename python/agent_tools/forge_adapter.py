"""The GitHub forge adapter (#124 D8, D19): its static descriptor.

`describe()` is the adapter's whole declared surface for this task: which operations it
carries, which it refuses, and what a profile may bind. `pr_merge` is declared but
`unsupported` (`target_cas_unproven`), so a profile that names it is a grammar violation
(D8). `tag` and `release` are the two supported publication operations, both `index`
mode, both irreversible and create-if-absent.

The descriptor is built fresh on every call, so a caller may mutate what it receives.
This module imports only the standard library, apart from one call-time import of
`adopt_planning.normalize_remote_url` inside `invoke`: the registry in `release_adapter`
imports this module, never the reverse (D7), and `adopt_planning` reaches the registry.

`inspect(request)` is the read half (D11, D17, D25, spec section 7). It issues only
`gh api` and `gh pr view` reads, by name, with `GITHUB_TOKEN` and `GH_TOKEN` removed from
the child environment so the keyring credential answers. It never mutates, never reads a
Release's `target_commitish`, never calls the guard, and runs every read of one call under
a single `COLLECTION_BUDGET_SECONDS` deadline. Whatever it cannot read it reports as
`unknown`, never raises. It imports no `host_admission` or `launch_*` module (AC9).

`invoke(request)` is the write half (D8, D9, D11, D22, D23, spec section 7). It follows the
spec's ordered steps and stops at the first refusal: request shape, working checkout, same
repository, containment (`tag`), the local annotated tag (`tag`), the rendered command, the
`claude-bash-lifecycle-guard` verdict, and then one mutation. It makes at most one provider
mutation, never retries, never reads the target (`tag.ref`, `tag.object`, `release.view`) and
returns only `accepted`, `rejected` or `unknown`: that a mutation landed is the core's to
observe afterwards (#85, #206). Every child runs with the token variables removed.
"""

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from typing import Any

CHILD_TIMEOUT_SECONDS = 30
COLLECTION_BUDGET_SECONDS = 30
DETAIL_LIMIT = 240
TOKEN_VARIABLES = ("GITHUB_TOKEN", "GH_TOKEN")
HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")
TARGET_MEMBERS = frozenset(("kind", "repository", "branch", "handle"))
TOLERATED = frozenset(("action", "operation", "config"))
REQUIRED = {"tag": ("target", "candidate"),
            "release": ("target", "candidate", "title", "notes"),
            "pr_merge": ("target", "pr", "expected_base_tip", "expected_head")}
PR_FIELDS = "state,baseRefName,headRefName,headRefOid,mergeCommit,url,statusCheckRollup"


def _publication_operation(candidate_members: list[str]) -> dict[str, Any]:
    return {"mode": "index", "support": "supported", "inspect": "supported", "reason": None,
            "mutability": "create_if_absent", "config_schema_version": 1,
            "config_schema": {"members": {}, "required": []},
            "effects": ["irreversible"], "recovery_capable": False,
            "candidate_members": candidate_members}


def describe() -> dict[str, Any]:
    """The forge descriptor (#124 D8, D19), a fresh plain dict."""
    return {
        "name": "github-forge",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "pr_merge": {"mode": "materialize", "support": "unsupported", "inspect": "supported",
                         "reason": "target_cas_unproven", "mutability": "pointer_cas",
                         "config_schema_version": 1,
                         "config_schema": {"members": {}, "required": []},
                         "effects": ["irreversible"], "recovery_capable": False,
                         "candidate_members": []},
            "tag": _publication_operation([]),
            "release": _publication_operation(["notes", "title"]),
        },
        "predicates": {
            "publication_visible": {"support": "supported", "reason": None},
            "running_subject_identity": {"support": "unsupported", "reason": "no_activation_mode"},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"github_repository": ["branch", "repository"]},
        "credential_classes": ["gh_keyring"],
        "executables": ["claude-bash-lifecycle-guard", "gh", "git"],
        "host_capacity": "not_required",
    }



class _Unknown(Exception):
    """A read that cannot be judged: the observation is `unknown` with this reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail[:DETAIL_LIMIT]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _observation(outcome: str, reason: str, subject: dict[str, Any], references: list[str],
                 facts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "reason": reason, "observed_subject": subject,
            "references": references, "observed_at": _now_ms(), "facts": facts or {}}


def _unknown(reason: str, detail: str = "", subject: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    return _observation("unknown", reason, subject or {}, [],
                        {"detail": detail[:DETAIL_LIMIT]} if detail else {})


def _gh(argv: list[str], deadline: float) -> tuple[Any, Any, str]:
    """Run `gh <argv>` within what is left of `deadline`: `(status, payload, detail)`.

    `status` is `"ok"` with the parsed JSON payload, or the HTTP status (404, 403) of a
    failed call, or one of `lookup_failed`, `lookup_timeout`, `payload_invalid` and
    `executable_missing`, with a payload of `None`. `detail` is bounded stderr.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", None, ""
    env = {name: value for name, value in os.environ.items() if name not in TOKEN_VARIABLES}
    try:
        done = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=remaining,
                              env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", None, ""
    except OSError as error:
        return "executable_missing", None, str(error)
    detail = done.stderr.strip()[:DETAIL_LIMIT]
    if done.returncode != 0:
        match = HTTP_STATUS.search(done.stderr)
        status = int(match.group(1)) if match else 0
        return (status if status in (403, 404) else "lookup_failed"), None, detail
    try:
        return "ok", json.loads(done.stdout), detail
    except ValueError:
        return "payload_invalid", None, detail


def _read(argv: list[str], deadline: float, allow: tuple[int, ...] = ()) -> tuple[Any, Any]:
    """`(status, payload)` of one read; any status but `ok` and `allow` ends the inspection."""
    status, payload, detail = _gh(argv, deadline)
    if status != "ok" and status not in allow:
        raise _Unknown(status if isinstance(status, str) else "lookup_failed", detail)
    return status, payload


def _field(value: Any, *path: str, kind: type = str) -> Any:
    for step in path:
        if not isinstance(value, dict) or step not in value:
            raise _Unknown("payload_invalid", f"missing {'.'.join(path)}")
        value = value[step]
    if type(value) is not kind:
        raise _Unknown("payload_invalid", f"{'.'.join(path)} is not a {kind.__name__}")
    return value


def _sha(value: str, where: str) -> str:
    if SHA.fullmatch(value) is None:
        raise _Unknown("payload_invalid", f"{where} is not a 40-character commit id")
    return value


def _tag_state(slug: str, tag: str, commit: str, deadline: float
               ) -> tuple[str, str, str | None, list[str]]:
    """`(outcome, reason, peeled commit, references)` of the tag, read from its own objects."""
    ref_path = f"repos/{slug}/git/ref/tags/{tag}"
    references = [ref_path]
    status, ref = _read(["api", ref_path], deadline, allow=(404,))
    if status == 404:
        return "absent", "tag_absent", None, references
    sha = _sha(_field(ref, "object", "sha"), "tag ref object")
    kind = _field(ref, "object", "type")
    if kind == "commit":
        return "diverged", "tag_not_annotated", sha, references
    if kind != "tag":
        raise _Unknown("payload_invalid", f"tag ref object type {kind!r}")
    object_path = f"repos/{slug}/git/tags/{sha}"
    references.append(object_path)
    _, annotated = _read(["api", object_path], deadline)
    peeled = _sha(_field(annotated, "object", "sha"), "tag object target")
    if peeled == commit:
        return "satisfied", "observed", peeled, references
    return "diverged", "tag_target_mismatch", peeled, references


def _inspect_tag(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    subject = {"tag": tag, "commit": None}
    try:
        outcome, reason, peeled, references = _tag_state(
            slug, tag, parameters["candidate"]["commit"], deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    return _observation(outcome, reason, {"tag": tag, "commit": peeled}, references)


def _inspect_release(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    subject = {"tag": tag, "commit": None}
    path = f"repos/{slug}/releases/tags/{tag}"
    try:
        status, release = _read(["api", path], deadline, allow=(404,))
        if status == 404:
            return _observation("absent", "release_absent", subject, [path])
        draft, name = _field(release, "draft", kind=bool), _field(release, "tag_name")
        url = release.get("html_url")
        references = [path] if not isinstance(url, str) else [url, path]
        if draft:
            return _observation("diverged", "release_draft", subject, references)
        if name != tag:
            return _observation("diverged", "release_tag_mismatch", subject, references)
        outcome, reason, peeled, tag_references = _tag_state(
            slug, tag, parameters["candidate"]["commit"], deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    return _observation(outcome, reason, {"tag": tag, "commit": peeled},
                        references + tag_references)


def _protection(slug: str, base: str, deadline: float) -> dict[str, Any]:
    status, payload, detail = _gh(["api", f"repos/{slug}/branches/{base}/protection"], deadline)
    if status == 404:
        return {"status": "unprotected", "required_contexts": [], "enforce_admins": False}
    if status == 403:
        return {"status": "inaccessible", "required_contexts": [], "enforce_admins": False}
    if status != "ok":
        raise _Unknown(status, detail)
    checks = payload.get("required_status_checks") if isinstance(payload, dict) else None
    contexts = checks.get("contexts") if isinstance(checks, dict) else None
    admins = payload.get("enforce_admins") if isinstance(payload, dict) else None
    return {"status": "protected",
            "required_contexts": sorted(contexts) if isinstance(contexts, list) else [],
            "enforce_admins": isinstance(admins, dict) and admins.get("enabled") is True}


def _inspect_pr_merge(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, number = parameters["target"]["repository"], parameters["pr"]
    subject = {"pr": number, "merge_commit": None}
    try:
        _, view = _read(["pr", "view", str(number), "--repo", slug, "--json", PR_FIELDS], deadline)
        state = _field(view, "state")
        if state not in ("OPEN", "MERGED", "CLOSED"):
            raise _Unknown("payload_invalid", f"PR state {state!r}")
        base, head = _field(view, "baseRefName"), _field(view, "headRefName")
        head_oid = _sha(_field(view, "headRefOid"), "headRefOid")
        if BRANCH.fullmatch(base) is None or ".." in base:
            raise _Unknown("payload_invalid", "baseRefName is not a branch name")
        base_path = f"repos/{slug}/git/ref/heads/{base}"
        _, base_ref = _read(["api", base_path], deadline)
        base_tip = _sha(_field(base_ref, "object", "sha"), "base ref")
        references = [view["url"]] if isinstance(view.get("url"), str) else []
        references.append(base_path)
        parents = None
        if state == "MERGED":
            merge = view.get("mergeCommit")
            oid = _sha(_field(merge, "oid"), "mergeCommit.oid")
            subject["merge_commit"] = oid
            commit_path = f"repos/{slug}/git/commits/{oid}"
            references.append(commit_path)
            _, commit = _read(["api", commit_path], deadline)
            listed = commit.get("parents") if isinstance(commit, dict) else None
            if not isinstance(listed, list):
                raise _Unknown("payload_invalid", "parents is not a list")
            parents = [_sha(_field(parent, "sha"), "parent") for parent in listed]
        protection = _protection(slug, base, deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    facts = {"state": state, "base": base, "head": head, "head_oid": head_oid,
             "base_tip": base_tip, "protection": protection}
    if state == "OPEN":
        outcome, reason = "absent", "pr_open"
    elif state == "CLOSED":
        outcome, reason = "diverged", "pr_closed"
    elif parents == [parameters["expected_base_tip"], parameters["expected_head"]]:
        outcome, reason = "satisfied", "observed"
    else:
        outcome, reason = "diverged", "merge_parents_mismatch"
    return _observation(outcome, reason, subject, references, facts)


def _target_problem(target: Any) -> str | None:
    if not isinstance(target, dict) or not set(target) <= TARGET_MEMBERS:
        return "target is not a github_repository object"
    if target.get("kind") != "github_repository":
        return "target kind is not github_repository"
    slug, branch = target.get("repository"), target.get("branch")
    if not isinstance(slug, str) or SLUG.fullmatch(slug) is None or ".." in slug:
        return "target repository is not an owner/name slug"
    if not isinstance(branch, str) or BRANCH.fullmatch(branch) is None or ".." in branch:
        return "target branch is not a branch name"
    return None


def _parameters_problem(operation: str, parameters: Any) -> str | None:
    """Why `parameters` are not the closed set for `operation`, or None."""
    required = REQUIRED[operation]
    if not isinstance(parameters, dict):
        return "parameters are not an object"
    missing = [name for name in required if name not in parameters]
    unknown = sorted(set(parameters) - set(required) - TOLERATED)
    if missing or unknown:
        return "parameters " + "; ".join(
            part for part in (f"miss {', '.join(missing)}" if missing else "",
                              f"have unknown {', '.join(unknown)}" if unknown else "") if part)
    problem = _target_problem(parameters["target"])
    if problem is not None:
        return problem
    if operation == "pr_merge":
        number = parameters["pr"]
        if type(number) is not int or number < 1:
            return "pr is not a positive integer"
        for name in ("expected_base_tip", "expected_head"):
            if not isinstance(parameters[name], str) or SHA.fullmatch(parameters[name]) is None:
                return f"{name} is not a 40-character commit id"
        return None
    candidate = parameters["candidate"]
    if not (isinstance(candidate, dict) and set(candidate) == {"version", "commit"}
            and isinstance(candidate["version"], str) and VERSION.fullmatch(candidate["version"])
            and isinstance(candidate["commit"], str) and SHA.fullmatch(candidate["commit"])):
        return "candidate is not {version vMAJOR.MINOR.PATCH, commit 40-hex}"
    if operation == "release" and not (isinstance(parameters["title"], str)
                                       and isinstance(parameters["notes"], str)):
        return "title and notes are not strings"
    return None


def _effect(operation: str, parameters: Any, deadline: float) -> dict[str, Any]:
    if operation not in REQUIRED:
        return _unknown("parameters_invalid", f"unknown operation {operation!r}")
    problem = _parameters_problem(operation, parameters)
    if problem is not None:
        return _unknown("parameters_invalid", problem)
    reader = {"tag": _inspect_tag, "release": _inspect_release, "pr_merge": _inspect_pr_merge}
    return reader[operation](parameters, deadline)


def _predicate(request: dict[str, Any], deadline: float) -> dict[str, Any]:
    def result(outcome: str, reason: str, references: list[str] | None = None) -> dict[str, Any]:
        return {"outcome": outcome, "reason": reason, "references": references or [],
                "observed_at": _now_ms()}

    if request.get("predicate") != "publication_visible":
        return result("unknown", "store_unreachable")
    observed = _effect(request.get("operation"), request.get("parameters"), deadline) \
        if isinstance(request.get("operation"), str) else _unknown("parameters_invalid")
    references = observed["references"]
    if observed["outcome"] == "satisfied":
        return result("satisfied", "observed", references)
    if observed["outcome"] == "absent":
        return result("unsatisfied", "ref_absent", references)
    if observed["outcome"] == "diverged":
        if observed["reason"] == "tag_not_annotated":
            return result("unsatisfied", "ref_not_immutable", references)
        return result("unsatisfied", "subject_mismatch", references)
    return result("unknown", "store_unreachable", references)


def inspect(request: Any) -> dict[str, Any]:
    """The effect or predicate `Observation` for one adapter request (#124 D7, D11, D25).

    Never raises and never mutates: a request outside the closed shape, or a read that cannot
    be judged, is `unknown`.
    """
    deadline = time.monotonic() + COLLECTION_BUDGET_SECONDS
    kind = request.get("kind") if isinstance(request, dict) else None
    if kind == "predicate" and set(request) == {"kind", "predicate", "operation", "parameters"}:
        return _predicate(request, deadline)
    if kind == "effect" and set(request) == {"kind", "operation", "parameters"}:
        operation = request["operation"]
        return _effect(operation if isinstance(operation, str) else "", request["parameters"],
                       deadline)
    if kind == "predicate":
        return {"outcome": "unknown", "reason": "store_unreachable", "references": [],
                "observed_at": _now_ms()}
    return _unknown("parameters_invalid", "request is not a closed effect or predicate request")


class _Refusal(Exception):
    """An `invoke` that ends here: the closed `InvokeResult` to return."""

    def __init__(self, result: str, error_class: str, reference: str) -> None:
        super().__init__(reference)
        self.answer = {"result": result, "error_class": error_class,
                       "reference": reference[:DETAIL_LIMIT] or "refused"}


FORBIDDEN_TITLE = frozenset('"$`\\\x00\r\n')


def _run_child(argv: list[str], cwd: str | None, stdin: str | None = None
               ) -> tuple[str, subprocess.CompletedProcess | None, str]:
    """Run `argv` by name within `CHILD_TIMEOUT_SECONDS`: `(status, process, detail)`.

    `status` is `ok` (the process finished, whatever its exit), `timeout` or `missing`.
    """
    env = {name: value for name, value in os.environ.items() if name not in TOKEN_VARIABLES}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=CHILD_TIMEOUT_SECONDS, env=env, cwd=cwd, input=stdin,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "timeout", None, "timed out"
    except OSError as error:
        return "missing", None, str(error)
    return "ok", done, done.stderr.strip()[:DETAIL_LIMIT]


def _precondition_read(argv: list[str], cwd: str | None) -> str:
    """Stdout of one precondition read; nothing was mutated, so a failed read is a refusal."""
    status, done, detail = _run_child(argv, cwd)
    name = " ".join(argv[:2])
    if status == "timeout":
        raise _Refusal("rejected", "transient_transport", f"{name}: timed out")
    if status == "missing" or done.returncode != 0:
        raise _Refusal("rejected", "provider_unavailable", f"{name}: {detail or 'failed'}")
    return done.stdout


def _invoke_shape(request: Any) -> tuple[str, dict[str, Any]]:
    """The operation and parameters of a request that is a supported, valid effect."""
    if not (isinstance(request, dict) and set(request) == {"kind", "operation", "parameters"}
            and request["kind"] == "effect" and isinstance(request["operation"], str)):
        raise _Refusal("rejected", "invalid_input", "request is not a closed effect request")
    operation, parameters = request["operation"], request["parameters"]
    entry = describe()["operations"].get(operation)
    if entry is None or entry["support"] != "supported":
        reason = "unknown_operation" if entry is None else entry["reason"]
        raise _Refusal("rejected", "unsupported_operation", f"{operation}: {reason}")
    problem = _parameters_problem(operation, parameters)
    if problem is None and operation == "release":
        if any(char in FORBIDDEN_TITLE for char in parameters["title"]):
            problem = "title has a character that cannot be quoted"
        else:
            try:
                parameters["notes"].encode("utf-8")
            except UnicodeEncodeError:
                problem = "notes are not UTF-8 text"
    if problem is not None:
        raise _Refusal("rejected", "invalid_input", problem)
    return operation, parameters


def _same_repository(slug: str, checkout: str) -> None:
    from agent_tools.adopt_planning import normalize_remote_url  # call time: import cycle

    origin = _precondition_read(["git", "remote", "get-url", "origin"], checkout)
    pushes = [line for line in _precondition_read(
        ["git", "remote", "get-url", "--push", "--all", "origin"], checkout).splitlines()
        if line.strip()]
    named = _precondition_read(
        ["gh", "api", f"repos/{slug}", "--jq", ".full_name"], checkout).strip()
    if len(pushes) != 1:
        raise _Refusal("rejected", "precondition_failed", f"origin has {len(pushes)} push urls")
    for what, found in (("origin", normalize_remote_url(origin)),
                        ("push url", normalize_remote_url(pushes[0])), ("repository", named)):
        if found != slug:
            raise _Refusal("rejected", "precondition_failed",
                           f"{what} is {found}, not {slug}")


def _contained(parameters: dict[str, Any], checkout: str) -> None:
    slug, branch = parameters["target"]["repository"], parameters["target"]["branch"]
    commit = parameters["candidate"]["commit"]
    status = _precondition_read(
        ["gh", "api", f"repos/{slug}/compare/{commit}...{branch}", "--jq", ".status"],
        checkout).strip()
    if not status:
        raise _Refusal("rejected", "provider_unavailable", "compare returned no status")
    if status not in ("identical", "ahead"):
        raise _Refusal("rejected", "precondition_failed", f"{commit} is {status} of {branch}")


def _local_tag(tag: str, commit: str, checkout: str) -> None:
    """Reuse an annotated local tag at `commit`, create it when absent, else refuse (D25)."""
    kind = _precondition_read(
        ["git", "for-each-ref", "--format=%(objecttype)", f"refs/tags/{tag}"], checkout).strip()
    if not kind:
        _precondition_read(["git", "tag", "-a", tag, commit, "-m", f"release: {tag}"], checkout)
        return
    peeled = _precondition_read(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"],
                                checkout).strip() if kind == "tag" else None
    if peeled is not None and SHA.fullmatch(peeled) is None:
        raise _Refusal("rejected", "provider_unavailable", "rev-parse did not return a commit id")
    if peeled != commit:
        raise _Refusal("rejected", "precondition_failed",
                       f"local tag {tag} is not an annotated tag at {commit}")


def _guard(raw: str, checkout: str) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": raw}, "cwd": checkout})
    status, done, detail = _run_child(["claude-bash-lifecycle-guard"], checkout, payload)
    if status == "ok" and done.returncode == 0:
        return
    if status == "ok" and not detail:
        detail = f"exit {done.returncode}"
    raise _Refusal("rejected", "authorization_denied", f"guard: {detail}")


def _mutate(argv: list[str], raw: str, checkout: str, operation: str, tag: str) -> dict[str, Any]:
    _guard(raw, checkout)
    status, done, detail = _run_child(argv, checkout)
    name = " ".join(argv[:2])
    if status == "timeout":
        return {"result": "unknown", "error_class": "transient_transport",
                "reference": f"{name}: timed out"}
    if status == "missing":
        # the spawn failed before any child ran, so nothing was applied
        return {"result": "rejected", "error_class": "provider_unavailable",
                "reference": f"{name}: {detail}"[:DETAIL_LIMIT]}
    if done.returncode == 0:
        url = done.stdout.strip().splitlines()[:1]
        if operation == "release":
            reference = url[0].strip() if url and url[0].startswith("http") else f"release:{tag}"
        else:
            reference = f"refs/tags/{tag}"
        return {"result": "accepted", "error_class": None, "reference": reference}
    marker = "already exists" if operation == "tag" else "HTTP 422"
    if marker in done.stderr:
        return {"result": "rejected", "error_class": "precondition_failed",
                "reference": f"{name}: {marker}"}
    return {"result": "unknown", "error_class": "transient_transport",
            "reference": f"{name}: {detail or 'exit ' + str(done.returncode)}"[:DETAIL_LIMIT]}


def _invoke(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    commit = parameters["candidate"]["commit"]
    toplevel = _precondition_read(["git", "rev-parse", "--show-toplevel"], None).strip()
    if not os.path.isabs(toplevel):
        raise _Refusal("rejected", "provider_unavailable", "rev-parse did not return a directory")
    _same_repository(slug, toplevel)
    if operation == "tag":
        _contained(parameters, toplevel)
        _local_tag(tag, commit, toplevel)
        argv, raw = ["git", "push", "origin", f"refs/tags/{tag}"], f"git push origin refs/tags/{tag}"
        return _mutate(argv, raw, toplevel, operation, tag)
    descriptor, path = tempfile.mkstemp(prefix="forge-release-notes-", suffix=".md")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(parameters["notes"])
        argv = ["gh", "release", "create", tag, "--repo", slug, "--verify-tag", "--title",
                parameters["title"], "--notes-file", path]
        raw = (f'gh release create {tag} --repo {slug} --verify-tag '
               f'--title "{parameters["title"]}" --notes-file {shlex.quote(path)}')
        if shlex.split(raw) != argv:
            raise _Refusal("rejected", "invalid_input", "rendered command does not match its argv")
        return _mutate(argv, raw, toplevel, operation, tag)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def invoke(request: Any) -> dict[str, Any]:
    """The `InvokeResult` of one effect request: `{result, error_class, reference}` (#124 D8, D9).

    A refusal at any step returns before the mutation, which is made at most once and never
    retried. Whether it landed is the core's to observe afterwards (#85, #206).
    """
    try:
        operation, parameters = _invoke_shape(request)
        return _invoke(operation, parameters)
    except _Refusal as refusal:
        return refusal.answer
