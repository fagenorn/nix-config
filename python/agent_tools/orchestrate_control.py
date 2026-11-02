"""`orchestrate-control`: the control surface of the orchestrate-issues skill (issue 403).

    orchestrate-control start --repo-root R [N ... | --label L | --milestone M] [--run-id I]
    orchestrate-control step --repo-root R --input -

`start` runs four steps in order and stops at the first that refuses:
`bindings` (resolve the project in process and read the orchestration, tracker
and worktree bindings), `route` (`workflow-state host-route --route claude-code`,
its reply validated), `issues` (the explicit numbers in the caller's order, or
the open issues a label or milestone sweep lists, ascending) and `bootstrap`
(`workflow-state init-run`: the run for the issue set, or with `--run-id` the
run that id names, which is re-entered and never created).

`step` reads one JSON object on stdin, `{session, first_sweep, owners,
contracts_due, refused_contracts}`, and runs eight steps in order, stopping at the
first that refuses: `bindings`, `bootstrap` (`init-run --run-id` for the session's
run), `tracker` (the session issues' state and open blockers, one GraphQL call per
100 issues), `forge` (the repository's pull requests, one paginated call, matched
to the issues by branch name), `worktrees` (each issue's recorded or candidate
worktree, from `git worktree list` and the local branches), `contracts` (one
`workflow-state build-delivery --kind contract` per issue that needs a pair before
the first call: on `first_sweep` every session requirement with a null
`contract_digest`, and every `contracts_due` issue, never one in `refused_contracts`),
`control` (one `workflow-state control` round over those facts, its reply validated
and required to be this run's control response) and `project` (the reply's action
kinds checked against the closed set, then one dispatch per `spawn`, `resume`,
`retry` and `delivery_remainder` action in returned order: its owner object as
`artifact-budget validate-report` prints it, and for a `resume` the `workflow-state
resume-pack` text, null when that child fails; any other failure refuses and prints
no dispatches).

A builder that exits 2 with no output has refused that issue: it joins
`refused_contracts` and `contract_refusals` with the line it printed, and the run goes
on without a pair for it. Any other builder failure refuses at `contracts`, before the
first `control` call, or at `control` once the first reply is in hand. When the first
reply's only action is `delivery_contract`, the issues it lists are built (those not
already built or refused) and, when any of them has a pair, `control` is called a second
time and last: the same facts, `owners` empty (the observations ride the first call
only), and a pair for each issue whose first-reply summary asks for one. A reply with any
dispatch is never followed by a second call, and a failure in the second round refuses at
`control` carrying the first reply.

Ready (exit 0): `{"command":"step","outcome":"ready","run_id","control_calls","response",
"dispatches","contracts_due","refused_contracts","contract_refusals","ends_run"}`:
`response` is the latest reply, `contracts_due` the issues it still asks a contract for
less the refused ones, and `ends_run` is true when its only action is `delivery_contract`
for issues that are all refused. A refusal carries the latest validated control reply as
`response` once `control` has answered, else null.

Stdout is one compact JSON object and a newline. Ready (exit 0):
`{"command":"start","outcome":"ready","session":{interface_version, run_id,
issues, human_directed, source}}`. A host without the route (exit 0):
`{"command":"start","outcome":"unsupported","route":<the validated host_route>}`,
with no run created. Refused (exit 2): `{command, outcome:"refused", step,
detail, completed_steps, response}`, `detail` being one line of at most 300
characters. An invalid invocation prints `orchestrate-control: invalid
invocation` on stderr, nothing on stdout, and exits 2.

The command resolves the project in process, runs `workflow-state`,
`artifact-budget`, `git` and the bound tracker CLI by name on `PATH`, removes every
name in the contract's `unset_before_invocation` from each tracker-CLI child's
environment, and writes no file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_tools import resolve_project
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

INVALID = "orchestrate-control: invalid invocation\n"
DETAIL_LIMIT = 300
TAIL_LIMIT = 120
ROUTE = "claude-code"
INTERFACE_VERSION = 1
LISTING_LIMIT = 1000
ISSUE_NUMBER = re.compile(r"[1-9][0-9]*")
DECISION_LABELS = frozenset({"wayfinder:research", "wayfinder:prototype", "wayfinder:grilling",
                             "wayfinder:task"})
TRACKER_CHUNK = 100
CONTROL_VERSION = 3
CLOSED_KINDS = ("spawn", "resume", "retry", "delivery_remainder", "delivery_contract", "wait",
                "finalize")
DISPATCH_KINDS = ("spawn", "resume", "retry")
CANDIDATE_SUFFIXES = ("", *(f"-{n}" for n in range(2, 10)))
MERGE_OID = re.compile(r"[0-9a-f]{40}")
FORGE_QUERY = (
    "query($owner: String!, $name: String!, $endCursor: String) { "
    "repository(owner: $owner, name: $name) { "
    "pullRequests(first: 100, after: $endCursor) { pageInfo { hasNextPage endCursor } "
    "nodes { number headRefName isCrossRepository state url mergeCommit { oid } } } } }")


class InvocationError(Exception):
    """The command line is not a valid `orchestrate-control` invocation."""


class Refusal(Exception):
    """One step refused: its name, a one-line detail and the response it carries, if any."""

    def __init__(self, step: str, detail: str, *, response: dict | None = None) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail
        self.response = response


@dataclass(frozen=True)
class Bindings:
    """The contract members the command reads, every one required and none defaulted."""

    project_root: str
    max_parallel: int
    attempt_budget_minutes: int
    tracker_kind: str
    tracker_cli: str
    repo_slug: str
    unset: tuple[str, ...]
    worktree_root: str
    worktree_prefix: str


def _member(snapshot: Mapping, *pointer: str) -> object:
    """The snapshot member at `pointer`, or a refusal at `bindings` naming it."""
    value: object = snapshot
    for key in pointer:
        if not isinstance(value, Mapping) or key not in value:
            raise Refusal("bindings", "missing binding /" + "/".join(pointer))
        value = value[key]
    return value


def _integer(snapshot: Mapping, *pointer: str) -> int:
    value = _member(snapshot, *pointer)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise Refusal("bindings", "missing binding /" + "/".join(pointer))
    return value


def _text(snapshot: Mapping, *pointer: str, empty: bool = False) -> str:
    value = _member(snapshot, *pointer)
    if not isinstance(value, str) or not (value or empty):
        raise Refusal("bindings", "missing binding /" + "/".join(pointer))
    return value


def load_bindings(repo_root: str) -> Bindings:
    """Resolve the project at `repo_root` and read the bindings this command needs."""
    try:
        snapshot = resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        raise Refusal("bindings", f"resolve-project refused: {error.code} "
                                  f"{error.repair_id}") from error
    project_root = _text(snapshot, "project", "root")
    unset = _member(snapshot, "bindings", "tracker", "credential_env", "unset_before_invocation")
    if not isinstance(unset, list) or not all(isinstance(name, str) for name in unset):
        raise Refusal("bindings", "missing binding /bindings/tracker/credential_env"
                                  "/unset_before_invocation")
    repo_slug = _text(snapshot, "bindings", "tracker", "repo_slug")
    owner, _, name = repo_slug.partition("/")
    if not owner or not name or "/" in name:
        raise Refusal("bindings", "missing binding /bindings/tracker/repo_slug")
    worktree_root = _text(snapshot, "bindings", "vcs", "worktree", "root")
    return Bindings(
        project_root=project_root,
        max_parallel=_integer(snapshot, "bindings", "workflow", "orchestration", "max_parallel"),
        attempt_budget_minutes=_integer(snapshot, "bindings", "workflow", "orchestration",
                                        "attempt_budget_minutes"),
        tracker_kind=_text(snapshot, "bindings", "tracker", "kind"),
        tracker_cli=_text(snapshot, "bindings", "tracker", "cli"),
        repo_slug=repo_slug,
        unset=tuple(unset),
        worktree_root=os.path.normpath(os.path.join(project_root, worktree_root)),
        worktree_prefix=_text(snapshot, "bindings", "vcs", "worktree", "prefix", empty=True))


def strict_json(raw: bytes) -> object:
    """Parse `raw` as UTF-8 JSON, refusing duplicate keys and non-finite constants."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal)


def run_child(step: str, argv: Sequence[str], *, stdin: bytes | None = None,
              env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run `argv` capturing its output, with `stdin` as its input or no input at all."""
    options: dict = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        return subprocess.run(list(argv), capture_output=True, check=False, env=env, **options)
    except (OSError, ValueError) as error:  # ValueError: an argument holds a NUL
        raise Refusal(step, f"cannot run {argv[0]}: {error}") from error


def why(done: subprocess.CompletedProcess) -> str:
    """The tail of a failed child's stderr as `: <tail>` on one line, or `` when it said nothing."""
    tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-TAIL_LIMIT:]
    return f": {tail}" if tail else ""


def validate_bytes(step: str, raw: bytes) -> bytes:
    """`raw` as the artifact-budget authority validates it at the `workflow-response` boundary."""
    done = run_child(step, ["artifact-budget", "validate-report", "--boundary",
                            "workflow-response", "--input", "-"], stdin=raw)
    if done.returncode != 0:
        raise Refusal(step, f"validate-report refused (exit {done.returncode}){why(done)}")
    return done.stdout


def workflow_response(step: str, *argv: str, stdin: bytes | None = None) -> dict:
    """The validated JSON object `workflow-state <argv>` printed; no field is read before it
    has passed `validate-report` (D13)."""
    done = run_child(step, ["workflow-state", *argv], stdin=stdin)
    if done.returncode != 0:
        raise Refusal(step, f"workflow-state exit {done.returncode}{why(done)}")
    try:
        reply = strict_json(validate_bytes(step, done.stdout))
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        raise Refusal(step, "validate-report did not print one JSON object")
    return reply


def tracker_env(bindings: Bindings) -> dict[str, str]:
    """This process's environment less every name the contract says to unset for the tracker."""
    return {key: value for key, value in os.environ.items() if key not in bindings.unset}


def require_github(step: str, bindings: Bindings) -> None:
    if bindings.tracker_kind != "github":
        raise Refusal(step, f"tracker kind {bindings.tracker_kind} is not supported")


def sweep(bindings: Bindings, flag: str, value: str) -> list[int]:
    """The open issues `flag value` selects (`--label` or `--milestone`), ascending."""
    require_github("issues", bindings)
    cli = bindings.tracker_cli
    done = run_child("issues", [cli, "issue", "list", "--repo", bindings.repo_slug, "--state",
                                "open", flag, value, "--json", "number", "--limit",
                                str(LISTING_LIMIT)], env=tracker_env(bindings))
    if done.returncode != 0:
        raise Refusal("issues", f"{cli} exit {done.returncode}{why(done)}")
    try:
        listing = strict_json(done.stdout)
    except ValueError:
        listing = None
    if not (isinstance(listing, list) and all(
            isinstance(row, dict) and isinstance(row.get("number"), int)
            and not isinstance(row["number"], bool) and row["number"] >= 1 for row in listing)):
        raise Refusal("issues", f"{cli} did not list issue numbers")
    if len(listing) >= LISTING_LIMIT:
        raise Refusal("issues", f"the listing reached its {LISTING_LIMIT}-issue limit")
    return sorted({row["number"] for row in listing})


def _issues(args: argparse.Namespace, bindings: Bindings) -> tuple[list[int], bool, dict]:
    """The session's issue numbers, whether a human named them, and where they came from."""
    if args.numbers:
        issues = list(args.numbers)
        for number in issues:
            if issues.count(number) > 1:
                raise Refusal("issues", f"duplicate issue number {number}")
        reference = "invocation:/orchestrate-issues " + " ".join(map(str, issues))
        return issues, True, {"kind": "explicit_user", "reference": reference}
    flag, value = ("--label", args.label) if args.label is not None else \
        ("--milestone", args.milestone)
    issues = sweep(bindings, flag, value)
    if not issues:
        raise Refusal("issues", "the issue set is empty")
    return issues, False, {"kind": "standing_repository",
                           "reference": f"sweep:{flag.removeprefix('--')}:{value}"}


def _bootstrap(args: argparse.Namespace, issues: list[int]) -> str:
    """The run id `init-run` answers for the run `--run-id` names or the issue set."""
    handle = ["--run-id", args.run_id] if args.run_id is not None else \
        ["--issue-set", "-".join(map(str, issues))]
    reply = workflow_response("bootstrap", "init-run", "--repo-root", args.repo_root, *handle)
    if reply.get("kind") != "workflow_bootstrap" \
            or (args.run_id is not None and reply.get("run_id") != args.run_id):
        raise Refusal("bootstrap", "init-run did not answer the requested run")
    return reply["run_id"]


def start(args: argparse.Namespace, done: list[str]) -> dict:
    """Open an orchestrate-issues session; `done` collects the steps that finished."""
    bindings = load_bindings(args.repo_root)
    done.append("bindings")
    route = workflow_response("route", "host-route", "--route", ROUTE)
    if route.get("support") == "unsupported":
        return {"command": "start", "outcome": "unsupported", "route": route}
    if route.get("support") != "supported":
        raise Refusal("route", "host-route did not report a support value")
    done.append("route")
    issues, human_directed, source = _issues(args, bindings)
    done.append("issues")
    run_id = _bootstrap(args, issues)
    done.append("bootstrap")
    return {"command": "start", "outcome": "ready",
            "session": {"interface_version": INTERFACE_VERSION, "run_id": run_id,
                        "issues": issues, "human_directed": human_directed, "source": source}}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class StepInput:
    """What the adapter carries between `step` calls (D4)."""

    session: dict
    first_sweep: bool
    owners: list[dict]
    contracts_due: tuple[int, ...]
    refused_contracts: tuple[int, ...]


def _exact(value: object, members: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != members:
        raise InvocationError(f"expected an object with exactly {sorted(members)}")
    return value


def _issue_numbers(value: object, allowed: Sequence[int] | None) -> list[int]:
    """A list of unique issue numbers, drawn from `allowed` when it is given."""
    if not (isinstance(value, list) and all(_is_int(n) and n >= 1 for n in value)
            and len(set(value)) == len(value)
            and (allowed is None or set(value) <= set(allowed))):
        raise InvocationError("expected a list of unique issue numbers of the session")
    return value


def _session(value: object) -> dict:
    session = _exact(value, {"interface_version", "run_id", "issues", "human_directed",
                             "source"})
    issues = _issue_numbers(session["issues"], None)
    source = _exact(session["source"], {"kind", "reference"})
    human = session["human_directed"]
    if not (_is_int(session["interface_version"]) and session["interface_version"] == 1
            and isinstance(session["run_id"], str) and session["run_id"]
            and "\0" not in session["run_id"] and issues
            and isinstance(human, bool)
            and source["kind"] == ("explicit_user" if human else "standing_repository")
            and isinstance(source["reference"], str) and source["reference"]):
        raise InvocationError("not a session")
    return session


def read_step_input(raw: bytes) -> StepInput:
    """The `step` stdin object, or an `InvocationError` when it is not exactly that."""
    try:
        value = strict_json(raw)
    except ValueError as error:
        raise InvocationError(f"stdin is not strict JSON: {error}") from error
    body = _exact(value, {"session", "first_sweep", "owners", "contracts_due",
                          "refused_contracts"})
    session = _session(body["session"])
    issues = session["issues"]
    owners = body["owners"]
    if not isinstance(body["first_sweep"], bool) or not (
            isinstance(owners, list) and all(
                isinstance(owner, dict) and _is_int(owner.get("issue"))
                and owner["issue"] in issues for owner in owners)):
        raise InvocationError("first_sweep must be a boolean and owners session observations")
    return StepInput(session=session, first_sweep=body["first_sweep"], owners=owners,
                     contracts_due=tuple(_issue_numbers(body["contracts_due"], issues)),
                     refused_contracts=tuple(_issue_numbers(body["refused_contracts"], issues)))


def _at(step: str, value: object, *path: str, expect: type = dict) -> Any:
    """The `expect`-typed member of `value` at `path`, or a refusal at `step` naming it."""
    where = "/" + "/".join(path)
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise Refusal(step, f"the reply has no {where}")
        value = value[key]
    if not isinstance(value, expect) or (expect is int and isinstance(value, bool)):
        raise Refusal(step, f"the reply's {where} is not a {expect.__name__}")
    return value


def _graphql(step: str, b: Bindings, query: str, *, paginate: bool = False) -> object:
    """The JSON the tracker CLI's `api graphql <query>` printed, for the bound repository."""
    owner, _, name = b.repo_slug.partition("/")
    flags = ["--paginate", "--slurp"] if paginate else []
    done = run_child(step, [b.tracker_cli, "api", "graphql", *flags, "-f", "query=" + query,
                            "-f", "owner=" + owner, "-f", "name=" + name],
                     env=tracker_env(b))
    if done.returncode != 0:
        raise Refusal(step, f"{b.tracker_cli} exit {done.returncode}{why(done)}")
    try:
        return strict_json(done.stdout)
    except ValueError:
        raise Refusal(step, f"{b.tracker_cli} did not print JSON") from None


def _issue_fields(number: int) -> str:
    return (f"i{number}: issueOrPullRequest(number: {number}) {{ __typename ... on Issue "
            "{ number state blockedBy(first: 50) { pageInfo { hasNextPage } nodes { number "
            "state url repository { nameWithOwner } labels(first: 25) { pageInfo "
            "{ hasNextPage } nodes { name } } } } } }")


def _tracker_entry(b: Bindings, number: int, node: object) -> dict:
    if not isinstance(node, dict):
        raise Refusal("tracker", f"issue {number} not found")
    if node.get("__typename") != "Issue":
        raise Refusal("tracker", f"#{number} is not an issue")
    state = _at("tracker", node, "state", expect=str)
    if state not in ("OPEN", "CLOSED"):
        raise Refusal("tracker", f"issue {number} has state {state}")
    if _at("tracker", node, "blockedBy", "pageInfo", "hasNextPage", expect=bool):
        raise Refusal("tracker", f"issue {number} has more blockers than one page lists")
    open_blockers: list[int] = []
    decisions: list[dict] = []
    for blocker in _at("tracker", node, "blockedBy", "nodes", expect=list):
        blocked_by = _at("tracker", blocker, "number", expect=int)
        if _at("tracker", blocker, "labels", "pageInfo", "hasNextPage", expect=bool):
            raise Refusal("tracker", f"blocker #{blocked_by} of issue {number} has more "
                                     "labels than one page lists")
        if _at("tracker", blocker, "state", expect=str) != "OPEN":
            continue
        repository = _at("tracker", blocker, "repository", "nameWithOwner", expect=str)
        if repository.casefold() != b.repo_slug.casefold():
            raise Refusal("tracker", f"issue {number} is blocked by #{blocked_by} in "
                                     f"{repository}, outside {b.repo_slug}")
        labels = {_at("tracker", label, "name", expect=str)
                  for label in _at("tracker", blocker, "labels", "nodes", expect=list)}
        if labels & DECISION_LABELS:
            decisions.append({"issue": blocked_by,
                              "url": _at("tracker", blocker, "url", expect=str)})
        else:
            open_blockers.append(blocked_by)
    return {"issue": number, "state": state.lower(), "open_blockers": sorted(open_blockers),
            "decision_blockers": sorted(decisions, key=lambda d: d["issue"])}


def tracker_facts(b: Bindings, issues: Sequence[int]) -> list[dict]:
    """Each session issue's state and open blockers, one GraphQL call per `TRACKER_CHUNK`."""
    facts: list[dict] = []
    for start in range(0, len(issues), TRACKER_CHUNK):
        chunk = issues[start:start + TRACKER_CHUNK]
        query = ("query($owner: String!, $name: String!) { repository(owner: $owner, "
                 "name: $name) { " + " ".join(map(_issue_fields, chunk)) + " } }")
        repository = _at("tracker", _graphql("tracker", b, query), "data", "repository")
        facts += [_tracker_entry(b, number, repository.get(f"i{number}")) for number in chunk]
    return facts


def _pull_state(pull: dict) -> dict:
    state = _at("forge", pull, "state", expect=str)
    url = _at("forge", pull, "url", expect=str)
    if state in ("OPEN", "CLOSED"):
        return {"state": state.lower(), "url": url, "merge_sha": None}
    oid = _at("forge", pull, "mergeCommit", "oid", expect=str) if state == "MERGED" else None
    if oid is None or MERGE_OID.fullmatch(oid) is None:
        raise Refusal("forge", f"pull request #{pull['number']} has state {state} and merge "
                               f"commit {oid}")
    return {"state": "merged", "url": url, "merge_sha": oid}


def forge_facts(b: Bindings, issues: Sequence[int]) -> dict[str, dict]:
    """Each session issue's newest same-repository pull request, matched by branch name, from
    one complete paginated listing."""
    pages = _graphql("forge", b, FORGE_QUERY, paginate=True)
    # `--slurp` prints one array of pages, and a repository with no pull request still
    # answers one page with empty `nodes`: only an array of zero pages (or no array) refuses.
    if not isinstance(pages, list) or not pages:
        raise Refusal("forge", "the pull-request listing printed no page")
    pulls = [pull for page in pages for pull in _at(
        "forge", page, "data", "repository", "pullRequests", "nodes", expect=list)]
    if _at("forge", pages[-1], "data", "repository", "pullRequests", "pageInfo", "hasNextPage",
           expect=bool):
        raise Refusal("forge", "the pull-request listing is incomplete")
    for pull in pulls:
        _at("forge", pull, "number", expect=int)
        _at("forge", pull, "headRefName", expect=str)
        _at("forge", pull, "isCrossRepository", expect=bool)
    facts: dict[str, dict] = {}
    for number in issues:
        matches = [pull for pull in pulls if not pull["isCrossRepository"]
                   and pull["headRefName"].removeprefix(b.worktree_prefix)
                   .startswith(f"issue-{number}-")]
        facts[str(number)] = _pull_state(max(matches, key=lambda pull: pull["number"])) \
            if matches else {"state": "none", "url": None, "merge_sha": None}
    return facts


def _git_fields(repo_root: str, separator: bytes, *argv: str) -> list[str]:
    """`git <argv>`'s output split on `separator`, each field decoded as the filesystem
    encodes paths, so a path with a newline or undecodable bytes survives unchanged."""
    done = run_child("worktrees", ["git", "-C", repo_root, *argv])
    if done.returncode != 0:
        raise Refusal("worktrees", f"git {argv[0]} exit {done.returncode}{why(done)}")
    return [os.fsdecode(field) for field in done.stdout.split(separator) if field]


def _live_worktrees(repo_root: str) -> tuple[set[str], dict[str, str | None]]:
    """Every registered worktree's real path, and each live one's mapped to its branch, None
    when it is detached, from the NUL-delimited listing (`launch_scope.worktree_paths` reads
    it the same way). A registration git marks `prunable` (its checkout's `.git` is gone) is
    registered but not live, so a stale record never matches its issue's branch."""
    branches: dict[str, str | None] = {}
    prunable: set[str] = set()
    path: str | None = None
    for field in _git_fields(repo_root, b"\0", "worktree", "list", "--porcelain", "-z"):
        if field.startswith("worktree "):
            path = os.path.realpath(field.removeprefix("worktree "))
            branches[path] = None
        elif field.startswith("branch ") and path is not None:
            branches[path] = field.removeprefix("branch ").removeprefix("refs/heads/")
        elif (field == "prunable" or field.startswith("prunable ")) and path is not None:
            prunable.add(path)
    return set(branches), {p: b for p, b in branches.items() if p not in prunable}


def worktree_facts(repo_root: str, b: Bindings, issues: Sequence[int],
                   requirements: Sequence[dict]) -> list[dict]:
    """Each session issue's recorded worktree normalized to a state, or its first free
    candidate path (D10, D19, D21)."""
    registered, live = _live_worktrees(repo_root)
    # A ref name cannot hold a newline or other control byte, so one ref per line is exact.
    branches = {name.removeprefix("refs/heads/") for name in _git_fields(
        repo_root, b"\n", "for-each-ref", "--format=%(refname)", "refs/heads")}
    recorded = {r["issue"]: r["recorded_worktree"] for r in requirements
                if r["recorded_worktree"]}
    taken = {os.path.realpath(path) for path in recorded.values()}

    def strip(name: str) -> str:
        return name.removeprefix(b.worktree_prefix)

    facts = []
    for number in issues:
        if number in recorded:
            path = recorded[number]
            branch = live.get(os.path.realpath(path))
            state = ("absent" if not os.path.lexists(path) else
                     "matching_issue_branch" if branch is not None
                     and strip(branch).startswith(f"issue-{number}-") else "mismatch")
            facts.append({"issue": number, "recorded": {"path": path, "state": state},
                          "candidate": None})
            continue
        for suffix in CANDIDATE_SUFFIXES:
            path = os.path.normpath(os.path.join(
                b.worktree_root, f"{b.worktree_prefix}issue-{number}-orchestrated{suffix}"))
            real, name = os.path.realpath(path), os.path.basename(path)
            if not (os.path.lexists(path) or real in registered or real in taken
                    or name in branches or strip(name) in branches):
                taken.add(real)
                facts.append({"issue": number, "recorded": None,
                              "candidate": {"path": path, "state": "absent"}})
                break
        else:
            raise Refusal("worktrees", f"no free candidate worktree for issue {number} "
                                       "(-orchestrated through -9 are taken)")
    return facts


def control_request(b: Bindings, session: dict, tracker: list, forge: dict, worktrees: list,
                    owners: list, pairs: Mapping[int, dict], *, human_directed: bool) -> dict:
    """The interface-3 `control` request: the facts, the bound policy, the built pairs and
    `human_directed`, which only an explicit session's first sweep sets (issue 458 D4)."""
    issues = session["issues"]

    def keyed(value) -> dict:
        return {str(number): value(number) for number in issues}
    return {
        "interface_version": CONTROL_VERSION, "host_route": ROUTE,
        "max_parallel": b.max_parallel, "attempt_budget_minutes": b.attempt_budget_minutes,
        "human_directed": human_directed, "issues": list(issues),
        "tracker": tracker, "owners": owners, "worktrees": worktrees, "forge": forge,
        "delivery_contracts": keyed(lambda n: pairs[n]["contract"] if n in pairs else None),
        "authorization_intents": keyed(
            lambda n: [pairs[n]["initial_intent"]] if n in pairs else []),
        "authority_observations": keyed(lambda n: []),
        "reevaluation_evidence": keyed(lambda n: []),
        "delivery_observations": keyed(lambda n: []),
        "requested_scopes": keyed(lambda n: None), "recoveries": keyed(lambda n: None)}


def run_control(repo_root: str, run_id: str, request: dict, *,
                previous: dict | None = None) -> dict:
    """One `workflow-state control` round; any refusal carries `previous`, the latest reply."""
    body = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode()
    try:
        reply = workflow_response("control", "control", "--repo-root", repo_root, "--run-id",
                                  run_id, "--request-file", "-", stdin=body)
    except Refusal as refusal:
        raise Refusal(refusal.step, refusal.detail, response=previous) from refusal
    # The validator accepts every workflow response, so the reply is checked to be this run's.
    if not ("kind" not in reply and _is_int(reply.get("interface_version"))
            and reply["interface_version"] == CONTROL_VERSION and reply.get("run_id") == run_id
            and isinstance(reply.get("actions"), list)
            and isinstance(reply.get("summaries"), list)):
        raise Refusal("control", "control returned a reply that is not this run's control "
                                 "response", response=previous)
    return reply


def asks_for_contract(summary: dict) -> bool:
    """Whether an issue summary still waits for a delivery contract."""
    return any(requirement.get("reason_code") == "delivery_contract_required"
               for requirement in summary["requirements"])


def owner_object(action: dict, repo_root: str, run_id: str) -> dict:
    """The interface-2 owner object for a `spawn`, `resume` or `retry` action: the action less
    `id` and `kind`, which become `action_id` and `launch_kind`, with the ledger and run bound."""
    value = {key: member for key, member in action.items() if key not in ("id", "kind")}
    value.update(action_id=action["id"], launch_kind=action["kind"], kind="owner",
                 interface_version=2, ledger_repo_root=repo_root, run_id=run_id)
    return value


def resume_pack(repo_root: str, run_id: str, action_id: str) -> str | None:
    """The `workflow-state resume-pack` text for a resumed action, or None when it cannot be had;
    a pack is context for the owner, so its absence never stops a dispatch."""
    try:
        done = run_child("project", ["workflow-state", "resume-pack", "--repo-root", repo_root,
                                     "--run-id", run_id, "--action-id", action_id])
        return done.stdout.decode("utf-8") if done.returncode == 0 else None
    except (Refusal, UnicodeDecodeError):
        return None


def _dispatch(action: dict, repo_root: str, run_id: str) -> dict:
    """One dispatch entry: the validated owner object text and the envelope that names it (D17)."""
    kind = action["kind"]
    if kind == "delivery_remainder":
        value, handle = action, {"action_id": action["custody"]["action_id"],
                                 "attempt": action["source_attempt"], "handoff_path": None}
    else:
        value, handle = owner_object(action, repo_root, run_id), {
            "action_id": action["id"], "attempt": action["attempt"],
            "handoff_path": action["handoff_path"]}
    text = validate_bytes("project", json.dumps(value, separators=(",", ":"),
                                                ensure_ascii=False).encode()).decode("utf-8")
    return {"action_id": handle["action_id"], "launch_kind": kind, "issue": action["issue"],
            "attempt": handle["attempt"], "owner": action["owner"],
            "worktree": action["worktree"], "handoff_path": handle["handoff_path"],
            "owner_object": text.removesuffix("\n"),
            "resume_pack": resume_pack(repo_root, run_id, action["id"])
            if kind == "resume" else None}


def project(response: dict, repo_root: str, run_id: str) -> list[dict]:
    """The dispatches a control reply asks for, in returned order, once every action kind is in
    the closed set; any failure refuses with the response and returns no partial list (D23)."""
    actions = response["actions"]
    for action in actions:
        kind = action.get("kind") if isinstance(action, dict) else None
        if kind not in CLOSED_KINDS:
            raise Refusal("project", f"unknown action kind {kind!r}", response=response)
    dispatches = []
    for action in actions:
        if action["kind"] not in (*DISPATCH_KINDS, "delivery_remainder"):
            continue
        label = action.get("id", action["kind"])
        try:
            dispatches.append(_dispatch(action, repo_root, run_id))
        except Refusal as refusal:
            raise Refusal("project", f"cannot project {label}: {refusal.detail}",
                          response=response) from refusal
        except (KeyError, TypeError, UnicodeDecodeError) as error:
            raise Refusal("project", f"cannot project {label}: {type(error).__name__} {error}",
                          response=response) from error
    return dispatches


def build_pair(step: str, repo_root: str, issue: int, worktree: str,
               session: dict) -> tuple[dict | None, str | None]:
    """`(pair, None)` from `workflow-state build-delivery`, or `(None, <its stderr line>)` when
    it refused the issue (exit 2, no output); any other failure refuses at `step`."""
    done = run_child(step, ["workflow-state", "build-delivery", "--repo-root", repo_root,
                            "--kind", "contract", "--input", "-"],
                     stdin=json.dumps({"issue": issue, "worktree": worktree,
                                       "source_kind": session["source"]["kind"],
                                       "source_reference": session["source"]["reference"]}
                                      ).encode())
    if done.returncode == 2 and not done.stdout:
        return None, done.stderr.decode("utf-8", "replace").removesuffix("\n")
    if done.returncode != 0:
        raise Refusal(step, f"build-delivery exit {done.returncode}{why(done)}")
    try:
        pair = strict_json(done.stdout)
    except ValueError:
        pair = None
    if not (isinstance(pair, dict) and set(pair) == {"contract", "initial_intent"}
            and all(isinstance(member, dict) for member in pair.values())):
        raise Refusal(step, "build-delivery printed no contract pair")
    return pair, None


@dataclass
class Contracts:
    """The delivery pairs one `step` call has built, and the issues whose build refused (D4)."""

    repo_root: str
    session: dict
    paths: Mapping[int, str]
    refused: set[int]
    pairs: dict[int, dict]
    refusals: list[dict]

    def attempt(self, step: str, issue: int) -> None:
        pair, line = build_pair(step, self.repo_root, issue, self.paths[issue], self.session)
        if pair is None:
            self.refused.add(issue)
            self.refusals.append({"issue": issue, "detail": line})
        else:
            self.pairs[issue] = pair

    def build(self, step: str, issues: Sequence[int]) -> None:
        """Build for each of `issues` not already built or refused."""
        for issue in issues:
            if issue in self.paths and issue not in self.refused and issue not in self.pairs:
                self.attempt(step, issue)


def action_kinds(reply: dict) -> list:
    """The kind of each action in `reply`, None for one that is not an object."""
    return [action.get("kind") if isinstance(action, dict) else None
            for action in reply["actions"]]


def control_rounds(args: argparse.Namespace, bindings: Bindings, request: StepInput,
                   facts: tuple[list, dict, list], contracts: Contracts) -> tuple[dict, int]:
    """The final control reply and the number of `control` calls made: the first, and one more
    when it only asks for delivery contracts and some of those issues now have a pair (D6, D18)."""
    session, run_id = request.session, request.session["run_id"]
    directed = session["human_directed"] and request.first_sweep
    first = run_control(args.repo_root, run_id, control_request(
        bindings, session, *facts, request.owners, contracts.pairs, human_directed=directed))
    if action_kinds(first) != ["delivery_contract"]:
        return first, 1
    try:
        contracts.build("control", first["actions"][0]["issues"])
    except Refusal as refusal:
        raise Refusal("control", refusal.detail, response=first) from refusal
    if not set(first["actions"][0]["issues"]) & set(contracts.pairs):
        return first, 1
    asked = {summary["issue"] for summary in first["summaries"] if asks_for_contract(summary)}
    send = {issue: pair for issue, pair in contracts.pairs.items() if issue in asked}
    return run_control(args.repo_root, run_id, control_request(
        bindings, session, *facts, [], send, human_directed=directed), previous=first), 2


def step(args: argparse.Namespace, done: list[str]) -> dict:
    """Gather the facts for the session's issues and run one control round over them."""
    request = read_step_input(sys.stdin.buffer.read())
    session, issues = request.session, request.session["issues"]
    run_id = session["run_id"]
    bindings = load_bindings(args.repo_root)
    done.append("bindings")
    boot = workflow_response("bootstrap", "init-run", "--repo-root", args.repo_root,
                             "--run-id", run_id)
    if boot.get("kind") != "workflow_bootstrap" or boot.get("run_id") != run_id:
        raise Refusal("bootstrap", "init-run did not answer the session's run")
    done.append("bootstrap")
    require_github("tracker", bindings)
    tracker = tracker_facts(bindings, issues)
    done.append("tracker")
    forge = forge_facts(bindings, issues)
    done.append("forge")
    worktrees = worktree_facts(args.repo_root, bindings, issues, boot["requirements"])
    done.append("worktrees")
    contracts = Contracts(
        args.repo_root, session,
        {w["issue"]: (w["recorded"] or w["candidate"])["path"] for w in worktrees},
        set(request.refused_contracts), {}, [])
    undigested = {r["issue"] for r in boot["requirements"] if r["contract_digest"] is None}
    contracts.build("contracts", [issue for issue in issues if issue in request.contracts_due
                                  or (request.first_sweep and issue in undigested)])
    done.append("contracts")
    reply, calls = control_rounds(args, bindings, request, (tracker, forge, worktrees), contracts)
    done.append("control")
    dispatches = project(reply, args.repo_root, run_id)
    actions = reply["actions"]
    return {"command": "step", "outcome": "ready", "run_id": run_id, "control_calls": calls,
            "response": reply, "dispatches": dispatches,
            "contracts_due": sorted(summary["issue"] for summary in reply["summaries"]
                                    if asks_for_contract(summary)
                                    and summary["issue"] not in contracts.refused),
            "refused_contracts": sorted(contracts.refused),
            "contract_refusals": contracts.refusals,
            "ends_run": [a["kind"] for a in actions] == ["delivery_contract"]
            and set(actions[0]["issues"]) <= contracts.refused}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


def _issue_number(value: str) -> int:
    if ISSUE_NUMBER.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("not an issue number")
    return int(value)


def _parser() -> _Parser:
    parser = _Parser(prog="orchestrate-control",
                     description="The control surface of the orchestrate-issues skill.")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start", help="open a session and its run")
    start_parser.add_argument("--repo-root", required=True)
    start_parser.add_argument("numbers", nargs="*", type=_issue_number, metavar="N")
    sweeps = start_parser.add_mutually_exclusive_group()
    sweeps.add_argument("--label")
    sweeps.add_argument("--milestone")
    start_parser.add_argument("--run-id")
    step_parser = commands.add_parser("step", help="gather facts and run one control round")
    step_parser.add_argument("--repo-root", required=True)
    step_parser.add_argument("--input", required=True)
    return parser


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    args = _parser().parse_args(argv)
    if args.command == "step":
        if not os.path.isabs(args.repo_root) or args.input != "-":
            raise InvocationError("step takes an absolute --repo-root and --input -")
        return args
    given = [bool(args.numbers), args.label is not None, args.milestone is not None]
    if not os.path.isabs(args.repo_root) or sum(given) != 1:
        raise InvocationError("start takes an absolute --repo-root and exactly one of "
                              "numbers, --label and --milestone")
    # An empty value is no selector: gh would apply no filter, and init-run no run id.
    if "" in (args.label, args.milestone, args.run_id):
        raise InvocationError("--label, --milestone and --run-id take a non-empty value")
    return args


def _print(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, run the subcommand, print its one JSON object and return the exit code."""
    try:
        args = _parse(argv)
    except InvocationError:
        sys.stderr.write(INVALID)
        return 2
    done: list[str] = []
    try:
        result = {"start": start, "step": step}[args.command](args, done)
    except InvocationError:
        sys.stderr.write(INVALID)
        return 2
    except Refusal as refusal:
        _print({"command": args.command, "outcome": "refused", "step": refusal.step,
                "detail": " ".join(refusal.detail.split())[:DETAIL_LIMIT],
                "completed_steps": list(done), "response": refusal.response})
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
