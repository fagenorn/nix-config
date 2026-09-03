#!/usr/bin/env python3
"""The conformance evaluators: one function per registered check.

Every `check_*` here answers with an `Outcome` and nothing else — it neither
assembles a report nor decides an exit status, both of which belong to the
entry module. The resolver ladder is the one stateful evaluator:
`check_contract_resolvable` runs the resolver once and caches every stage it
settles, and the five dependent evaluators are pure reads of that cache (D17).

`conformance` loads this module through its `SourceFileLoader` helper, having
registered `conformance_registry` in `sys.modules` first, which is what the
`from conformance_registry import` below resolves against (D2, D40).
"""

from __future__ import annotations

import fcntl
import fnmatch
import json
import os
from pathlib import Path
import subprocess

from conformance_registry import (
    CHILD_TIMEOUT_SECONDS, CODE_STAGES, Context, LIVE_OWNER,
    NESTED_LEDGER_FINDINGS, NIX_STORE_PREFIX, Outcome, POLICY_PATH_MEMBERS,
    REGISTRY_BY_ID, RESOLVABLE_CHECK_ID, STAGE_CHECKS, STAGE_ORDER,
    TERMINAL_RESIDUE, TOOL_REASON_CODES, UNACKNOWLEDGED_RESIDUE, bound_fact,
    bound_facts,
)


def bounded_run(argv: list[str], cwd, env: dict | None = None):
    """Contract: a completed read-only child, or None when it could not run.

    Every child the engine starts is read-only and bounded; a failure to
    launch, a timeout or a signal yields None so the caller records a null
    fact or a finding rather than letting an environment fact escape (D19).
    """
    try:
        return subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True,
                              text=True, timeout=CHILD_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------
# The resolver ladder
# --------------------------------------------------------------------------


def dedup_violations(violations: list[dict]) -> list[dict]:
    """The list with each `(pointer, message)` kept once, in first-seen order.

    `validate_contract` re-runs `validate_schema_version` internally, so a
    malformed version would otherwise be counted twice in the `violations`
    fact.
    """
    seen = set()
    ordered = []
    for item in violations:
        key = (item["pointer"], item["message"])
        if key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


def stage_repair_id(stage: str, reason_code: str) -> str:
    """The repair the stage's own check declares for that code (D31)."""
    return dict(REGISTRY_BY_ID[STAGE_CHECKS[stage]].findings)[reason_code]


def suppress_unset_stages(context: Context, suppressed_by: str) -> None:
    """Every stage still unset becomes `suppressed` by the named check.

    Those *before* the failing stage in ladder order as well as those after:
    an unparseable contract fails `valid` while `schema_supported` never ran,
    and an unset stage is a hole an evaluator would raise on (D33).
    """
    for name in STAGE_ORDER:
        if context.stages[name] is None:
            context.stages[name] = Outcome(
                "suppressed", facts={"suppressed_by": suppressed_by})


def settle(context: Context, error) -> bool:
    """Record one resolver refusal against the stage its code names (D33).

    Returns False for a code no stage owns, which the caller reports on
    `repository.contract.resolvable` itself.
    """
    stage = CODE_STAGES.get(error.code)
    if stage is None:
        return False
    check_id = STAGE_CHECKS[stage]
    # Overwrites a `passed` recording when the code names an earlier stage:
    # `validate_projections` refuses `invalid_contract` after `valid` passed.
    context.stages[stage] = Outcome(
        "failed", error.code, stage_repair_id(stage, error.code),
        {"violations": len(error.violations),
         "first_pointer": bound_fact(error.violations[0]["pointer"])})
    suppress_unset_stages(context, check_id)
    return True


def check_contract_resolvable(context: Context) -> Outcome:
    """Run the resolver ladder once and cache every stage it settles (D17).

    This is the engine's one declared exception to the single boundary in
    `main`: a failure *of the resolver* is this check's finding, while a
    failure of anything else is the refusal (D29).
    """
    resolver = context.resolver
    stage = "present"
    try:
        root = resolver.discover_root(context.root_arg)
        context.root = root
        context.stages["present"] = Outcome("passed")

        stage = "schema_supported"
        source = resolver.load_contract(root)
        context.contract = source
        violations: list[dict] = []
        resolver.validate_schema_version(source, violations)
        context.stages["schema_supported"] = Outcome("passed")

        stage = "valid"
        violations += resolver.validate_contract(source)
        resolver.raise_for_violations(dedup_violations(violations))
        context.stages["valid"] = Outcome("passed")

        stage = "projection_fresh"
        context.bindings = resolver.normalize_bindings(source["bindings"], root)
        context.capabilities = resolver.compute_capabilities(
            context.bindings, root, source["capabilities"])
        resolver.validate_projections(root, source)
        context.stages["projection_fresh"] = Outcome("passed")

        stage = "capability_required"
        resolver.raise_for_unavailable(list(context.required), context.capabilities)
        context.stages["capability_required"] = Outcome("passed")
    except resolver.ContractError as error:
        if not settle(context, error):
            return resolver_failed(context, stage)
    except Exception:
        return resolver_failed(context, stage)
    return Outcome("passed")


def resolver_failed(context: Context, stage: str) -> Outcome:
    """The ladder itself broke: every unsettled stage suppresses under it."""
    suppress_unset_stages(context, RESOLVABLE_CHECK_ID)
    return Outcome("failed", "resolver_failure", "conformance.internal",
                   {"stage": stage})


def stage_result(context: Context, stage: str) -> Outcome:
    """The cached verdict for `stage`.

    After `check_contract_resolvable` returns, no stage is unset; finding one
    here is a control-flow bug in the ladder, not a finding about the subject.
    """
    outcome = context.stages[stage]
    if outcome is None:
        raise ValueError(f"the ladder left the {stage!r} stage unsettled")
    return outcome


def check_contract_present(context: Context) -> Outcome:
    return stage_result(context, "present")


def check_schema_supported(context: Context) -> Outcome:
    return stage_result(context, "schema_supported")


def check_contract_valid(context: Context) -> Outcome:
    return stage_result(context, "valid")


def check_projection_fresh(context: Context) -> Outcome:
    return stage_result(context, "projection_fresh")


def check_capability_required(context: Context) -> Outcome:
    return stage_result(context, "capability_required")


# --------------------------------------------------------------------------
# Host installation
#
# Both checks depend on `repository.contract.valid`, so the authored contract
# is parsed and the resolver's capability states are computed before either
# runs. Neither opens a file, follows a link to read its target, or starts a
# process.
# --------------------------------------------------------------------------


def declared_policy_paths(contract: dict) -> list[str]:
    """Every repository-relative policy path the contract declares, sorted.

    Read from the authored contract rather than `context.bindings`, whose
    entries are already absolute: an absolute path in `facts` would leak the
    caller's home directory.
    """
    paths = contract["bindings"]["paths"]
    subjects = {entry for member in POLICY_PATH_MEMBERS for entry in paths[member]}
    subjects.update(projection["source"] for projection in contract["projections"])
    return sorted(subjects)


def first_symlinked_component(root: Path, relative: str) -> tuple[int, Path] | None:
    """The 1-based depth and path of `relative`'s first symlinked component.

    The walk accumulates from `root` and never tests `root` itself or any of
    its parents (D18). The resolver resolves the root before any evaluator sees
    it, so today the bound is defense-in-depth rather than a falsifiable
    invariant (D39). A component that does not exist ends the walk without a
    finding: an absent knowledge path is the resolver's own refusal, not a
    symlinked one.
    """
    current = root
    for depth, part in enumerate(Path(relative).parts, start=1):
        current = current / part
        if current.is_symlink():       # an lstat: the link is never followed
            return depth, current
        if not current.exists():
            return None
    return None


def points_into_nix_store(component: Path) -> bool:
    """Whether the link points into the Nix store — the bool only, never the
    store path itself, which would be an absolute path in `facts` (D9)."""
    target = os.readlink(component)
    if not os.path.isabs(target):
        target = os.path.join(str(component.parent), target)
    return target.startswith(NIX_STORE_PREFIX)


def check_policy_path_no_follow_readable(context: "Context") -> "Outcome":
    """Contract: failed when any declared policy path reaches its target through
    a symlink at or below the project root, never above it (D18)."""
    offending: list[str] = []
    first: tuple[int, Path] | None = None
    for relative in declared_policy_paths(context.contract):
        found = first_symlinked_component(context.root, relative)
        if found is None:
            continue
        offending.append(relative)
        if first is None:
            first = found
    if first is None:
        return Outcome("passed")
    depth, component = first
    return Outcome("failed", "policy_path_symlinked", "host.policy_path.materialize",
                   {"paths": bound_facts(offending),
                    "count": len(offending),
                    "link_depth": depth,
                    "in_nix_store": points_into_nix_store(component)})


def check_executor_helper_on_path(context: "Context") -> "Outcome":
    """Contract: failed when the resolver computed a capability as blocked for a
    tool-shaped reason; performs no PATH search of its own."""
    offending = [name for name, entry in sorted(context.capabilities.items())
                 if entry["state"] == "blocked"
                 and entry["reason_code"] in TOOL_REASON_CODES]
    if not offending:
        return Outcome("passed")
    codes = {context.capabilities[name]["reason_code"] for name in offending}
    return Outcome("failed", "helper_missing", "host.helper.install",
                   {"capabilities": bound_facts(offending),
                    "count": len(offending),
                    "reason_codes": bound_facts(codes)})


# --------------------------------------------------------------------------
# The tracker credential
#
# The one network-flagged check (D7): the only evaluator that starts a child
# reaching beyond this machine. `TRACKERS` is the closed dispatch on
# `tracker.kind`, so the kind, its subcommand and its hostname have a single
# home and an unrecognised kind cannot fall back onto another tracker's.
# --------------------------------------------------------------------------


TRACKERS: dict[str, dict] = {
    "github": {"argv": ("auth", "status"), "host": "github.com"},
}


def check_tracker_credential(context: "Context") -> "Outcome":
    """Contract: passed when the declared tracker CLI reports an authenticated
    credential; not_run for a tracker kind this engine cannot interrogate.
    Records a boolean and a hostname from the closed table, never CLI output."""
    tracker = context.contract["bindings"]["tracker"]
    kind, cli = tracker["kind"], tracker["cli"]
    if kind not in TRACKERS:
        # Authored data the resolver accepts as a free string, so a finding
        # rather than an engine bug — and never a pass (D20).
        return Outcome("not_run", "unsupported_tracker_kind",
                       "host.tracker.authenticate",
                       {"kind": bound_fact(kind), "cli": bound_fact(cli)})
    env = dict(os.environ)
    for name in tracker["credential_env"]["unset_before_invocation"]:
        env.pop(name, None)   # the contract is the single home for the scrub
    proc = bounded_run([cli, *TRACKERS[kind]["argv"]], cwd=context.root, env=env)
    if proc is None:
        # A tracker CLI that cannot be spawned is host.executor.helper_on_path's
        # finding, not this one's.
        return Outcome("not_run", "tracker_credential_missing",
                       "host.tracker.authenticate",
                       {"authenticated": False, "cli_invoked": False})
    # The table, never stdout: `gh auth status` prints the account name.
    host = TRACKERS[kind]["host"]
    if proc.returncode == 0:
        return Outcome("passed", None, None,
                       {"authenticated": True, "cli_invoked": True,
                        "host": host})
    return Outcome("failed", "tracker_credential_missing",
                   "host.tracker.authenticate",
                   {"authenticated": False, "cli_invoked": True, "host": host})


# --------------------------------------------------------------------------
# Repository policy
#
# Three pure reads of the working tree and the authored contract: no process,
# no write, no network. Every fact is a repository-relative path, an ignore
# rule or a command id — never an absolute path, and never a command's argv.
# --------------------------------------------------------------------------


# The four lifecycle classes are closed (#72): a path matching none of them is
# a finding, never a new implicit class. The four names unpack from the tuple,
# so no class can exist outside it.
LIFECYCLE_CLASSES = ("canonical_tracked", "tracked_projection",
                     "ignored_runtime", "allowlisted_bookkeeping")
(CANONICAL_TRACKED, TRACKED_PROJECTION,
 IGNORED_RUNTIME, ALLOWLISTED_BOOKKEEPING) = LIFECYCLE_CLASSES

AGENTS_DIR = ".agents"
CANONICAL_AGENTS_PREFIXES = (
    "project.json", "instructions/", "skills/", "adapters/",
    "extensions/", "knowledge/", "artifacts/",
)
RUNTIME_PREFIX = "runtime/"
ARTIFACTS_PREFIX = "artifacts/"
# The buckets `artifacts/` admits; any other second segment is unclassified.
ARTIFACTS_BUCKETS = ("specs", "plans", "evidence", "handoffs", "notes")
# Closed and empty in v1: nothing outside .agents/ is admitted as
# non-behavioral bookkeeping yet.
BOOKKEEPING_ALLOWLIST: tuple[str, ...] = ()

RUNTIME_IGNORE_PATTERNS = (".agents/runtime/", ".agents/runtime",
                           "/.agents/runtime/", "/.agents/runtime")
OVERBROAD_IGNORE_PATTERNS = (".agents/*", "/.agents/*", ".claude/*", "/.claude/*")
RUNTIME_SENTINEL_BYTES = b"*\n"

SHELL_ARGV0 = ("sh", "bash", "zsh", "dash", "ksh")
SHELL_METACHARACTERS = (";", "|", "&&", "`", "$(")


def classify_agents_relative(relative: str) -> str | None:
    """The lifecycle class of a path relative to `<root>/.agents/`, or None."""
    if relative.startswith(RUNTIME_PREFIX):
        return IGNORED_RUNTIME
    if relative.startswith(ARTIFACTS_PREFIX):
        segments = relative.split("/")
        if len(segments) > 1 and segments[1] in ARTIFACTS_BUCKETS:
            return CANONICAL_TRACKED
        return None
    for prefix in CANONICAL_AGENTS_PREFIXES:
        if relative == prefix or (prefix.endswith("/")
                                  and relative.startswith(prefix)):
            return CANONICAL_TRACKED
    return None


def classify_path(relative: str, targets: frozenset) -> str | None:
    """Contract: `relative`'s lifecycle class, or None when it matches none of
    the four. `relative` and every member of `targets` are repository-relative,
    so a projection target that lives under `.agents/` classifies as the
    projection it is rather than as an unadmitted file."""
    if relative in targets:
        return TRACKED_PROJECTION
    if relative in BOOKKEEPING_ALLOWLIST:
        return ALLOWLISTED_BOOKKEEPING
    if relative.startswith(AGENTS_DIR + "/"):
        return classify_agents_relative(relative[len(AGENTS_DIR) + 1:])
    return None


def agents_tree_paths(root: Path) -> set[str]:
    """Every file under `<root>/.agents/`, repository-relative.

    A path carrying a `.git` component is skipped: a nested repository's own
    bookkeeping is not this repository's classification subject.
    """
    found = set()
    for path in (root / AGENTS_DIR).rglob("*"):
        relative = path.relative_to(root)
        if ".git" not in relative.parts and path.is_file():
            found.add(relative.as_posix())
    return found


def check_paths_classified(context: "Context") -> "Outcome":
    """Contract: failed when a file under .agents/ or a declared projection
    target matches none of the four closed lifecycle classes (#72)."""
    targets = frozenset(projection["target"]
                        for projection in context.contract["projections"])
    subjects = agents_tree_paths(context.root) | targets
    offending = [relative for relative in sorted(subjects)
                 if classify_path(relative, targets) is None]
    if not offending:
        return Outcome("passed")
    return Outcome("failed", "unclassified_path", "lifecycle.path.classify",
                   {"paths": bound_facts(offending), "count": len(offending)})


def ignore_rules(path: Path) -> list[str]:
    """Every stripped, non-empty, non-comment line of `path`.

    An unreadable or absent file yields an empty rule list rather than an
    exception: a repository carrying no ignore file states no rule.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    stripped = (line.strip() for line in text.splitlines())
    return [rule for rule in stripped if rule and not rule.startswith("#")]


def holds_runtime_sentinel(path: Path) -> bool:
    """Whether `path` is #72's committed sentinel: exactly the bytes `*\\n`."""
    try:
        return path.read_bytes() == RUNTIME_SENTINEL_BYTES
    except OSError:
        return False


def check_ignore_runtime_sentinel(context: "Context") -> "Outcome":
    """Contract: failed for a broad .agents/* or .claude/* ignore rule, or when
    .agents/runtime/ is covered by neither a root rule nor the committed
    sentinel; the overbroad finding outranks the missing one.

    Only the tracked ignore files are read. `.git/info/exclude` is deliberately
    not consulted: a machine-local rule cannot be the repository's own
    classification of a path.
    """
    root_gitignore = context.root / ".gitignore"
    rules = ignore_rules(root_gitignore)
    offending = [rule for rule in rules if rule in OVERBROAD_IGNORE_PATTERNS]
    if offending:
        return Outcome("failed", "overbroad_ignore", "lifecycle.ignore.repair",
                       {"rules": bound_facts(offending), "count": len(offending)})
    # Either spelling covers the subtree, so a conformant repository that
    # commits only one of the two is not failed for the other's absence.
    sentinel = context.root / AGENTS_DIR / "runtime" / ".gitignore"
    if (any(rule in RUNTIME_IGNORE_PATTERNS for rule in rules)
            or holds_runtime_sentinel(sentinel)):
        return Outcome("passed")
    return Outcome("failed", "runtime_ignore_missing", "lifecycle.ignore.repair",
                   {"root_gitignore": root_gitignore.exists(),
                    "sentinel": sentinel.exists()})


def reaches_through_a_shell(argv: list) -> bool:
    """Whether `argv` reaches its command through a shell rather than naming it.

    `argv` is non-empty and every word is a string: the resolver validated
    command shape before `repository.contract.valid` passed, which this check
    declares as its dependency, so the two never re-implement one another.
    """
    if Path(argv[0]).name in SHELL_ARGV0 and "-c" in argv[1:]:
        return True
    return any(meta in word for word in argv for meta in SHELL_METACHARACTERS)


def check_commands_no_shell_indirection(context: "Context") -> "Outcome":
    """Contract: failed when a declared command's argv[0] is a shell invoked
    with -c, or any argv element carries a shell metacharacter.

    Read from the authored contract rather than `context.bindings`:
    normalization rewrites `cwd` and leaves `argv` alone, so the authored form
    keeps the reported ids and the authored text in one correspondence.
    """
    offending = [command_id for command_id, entry
                 in sorted(context.contract["bindings"]["commands"].items())
                 if reaches_through_a_shell(entry["argv"])]
    if not offending:
        return Outcome("passed")
    return Outcome("failed", "shell_indirection", "contract.commands.destructure",
                   {"commands": bound_facts(offending), "count": len(offending)})


# --------------------------------------------------------------------------
# Residue
# --------------------------------------------------------------------------

# The ledger's own terminal vocabulary. Only `merged` admits the removal
# repair: a run that stopped or failed terminated without the outcome the
# lifecycle was after, and a reader — not the engine — decides what it owes.
TERMINAL_LEDGER_STATES = ("merged", "stopped", "failed")
REMOVABLE_LEDGER_STATE = "merged"

LEDGER_RUNS_RELATIVE = (".superpowers", "workflows")
LEDGER_STATE_FILE = "state.json"
LEDGER_LOCK_FILE = "state.lock"

# The fact key each class is counted under; the codes read as reason codes and
# the keys read as a tally, so neither borrows the other's spelling.
RESIDUE_FACT_KEYS = {LIVE_OWNER: "live_owner",
                     UNACKNOWLEDGED_RESIDUE: "unacknowledged",
                     TERMINAL_RESIDUE: "terminal"}

ROOT_SCRATCH_PATTERNS = ("producer-report-*.json", "review-package-report-*.json",
                         "*.tmp.??????", ".resolve-project.*.tmp")


def listed(directory: Path) -> list:
    """Contract: `directory`'s children sorted by path, or none at all.

    `Path.is_dir` swallows an OSError and answers False, so it never protects
    the listing that follows it: an absent path, a file, and a directory that
    stats fine but cannot be read all land here. None of the three is an engine
    bug — an unlistable directory is an environment fact that contributes no
    subject, exactly as an unreadable ledger records no attempt (D19, D32).
    """
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def nested_ledger_runs(context: "Context") -> list:
    """Every ledger run directory living inside a worktree, sorted by path.

    A run in the primary checkout is where the ledger belongs; only a copy
    that a worktree carried away is residue.
    """
    worktree_root = (context.root
                     / context.contract["bindings"]["vcs"]["worktree"]["root"])
    return [run
            for worktree in listed(worktree_root)
            for run in listed(worktree.joinpath(*LEDGER_RUNS_RELATIVE))
            if run.is_dir()]


def ledger_attempts(run: Path) -> list | None:
    """Every attempt the run's ledger records, or None when it records none.

    An absent, unreadable, non-JSON or unexpectedly-shaped ledger is None
    rather than an exception: a ledger nothing can read proves nothing, which
    is exactly what an unacknowledged run means (D19).
    """
    try:
        state = json.loads(
            (run / LEDGER_STATE_FILE).read_text(encoding="utf-8"))
        return [attempt for issue in state["issues"].values()
                for attempt in issue["attempts"]]
    except (OSError, UnicodeDecodeError, ValueError,
            TypeError, AttributeError, KeyError):
        return None


def durably_merged(attempts) -> bool:
    """Contract: whether every attempt is merged and says so twice (D34).

    An attempt carrying no result, or a result whose state disagrees with the
    attempt's, is a termination nobody wrote down — the ledger's own validator
    refuses that shape, and D10 admits removal only against a record.
    """
    if not attempts:
        return False
    for attempt in attempts:
        if not isinstance(attempt, dict):
            return False
        result = attempt.get("result")
        if (attempt.get("state") != REMOVABLE_LEDGER_STATE
                or not isinstance(result, dict)
                or result.get("state") != attempt.get("state")):
            return False
    return True


def classify_residue_run(run: Path) -> str:
    """Contract: `run`'s residue class, proved by a lock and then by a ledger.

    The lock is opened read-only and never created: a run with no `state.lock`
    proved nothing and is unacknowledged, because creating one to probe would
    be a write under the subject root and reading its absence as freedom would
    offer removal with no evidence at all behind it (D34). Elapsed time is
    consulted nowhere.
    """
    lock = run / LEDGER_LOCK_FILE
    if not lock.is_file():
        return UNACKNOWLEDGED_RESIDUE
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:  # a lock this process cannot even open proves nothing
        return UNACKNOWLEDGED_RESIDUE
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # BlockingIOError included: someone else holds it
            return LIVE_OWNER
        return (TERMINAL_RESIDUE if durably_merged(ledger_attempts(run))
                else UNACKNOWLEDGED_RESIDUE)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def check_residue_nested_ledger(context: "Context") -> "Outcome":
    """Contract: warning when a ledger run directory lives inside a worktree.
    A run is removable only when a non-blocking flock on its existing
    state.lock succeeded and every attempt is merged with a matching durable
    result; anything less is unacknowledged. Nothing is deleted, no lock is
    created, and elapsed time is never consulted (D10, D34)."""
    runs = nested_ledger_runs(context)
    if not runs:
        return Outcome("passed")
    counts = {code: 0 for code, _ in NESTED_LEDGER_FINDINGS}
    for run in runs:
        counts[classify_residue_run(run)] += 1
    reason_code, repair_id = next(
        finding for finding in NESTED_LEDGER_FINDINGS if counts[finding[0]])
    facts = {"runs": bound_facts(run.relative_to(context.root).as_posix()
                                 for run in runs),
             "count": len(runs)}
    facts.update((RESIDUE_FACT_KEYS[code], counts[code]) for code in counts)
    return Outcome("warning", reason_code, repair_id, facts)


def check_residue_root_scratch(context: "Context") -> "Outcome":
    """Contract: warning when an immediate child file of the project root
    matches the closed scratch pattern set.

    Never recursive: these are `mktemp` outputs that escaped `$TMPDIR` into the
    repository root and nowhere else, and a deeper walk would sweep in the real
    homes the same names legitimately have.
    """
    names = [entry.name for entry in listed(context.root)
             if entry.is_file()
             and any(fnmatch.fnmatch(entry.name, pattern)
                     for pattern in ROOT_SCRATCH_PATTERNS)]
    if not names:
        return Outcome("passed")
    return Outcome("warning", "root_scratch_present", "lifecycle.residue.root_scratch",
                   {"files": bound_facts(names), "count": len(names)})


# --------------------------------------------------------------------------
# The release-profile lint items
#
# Three #86 findings registered with a declared subject and nothing more. This
# slice ships no profile compiler, so every one of them reports `not_run`:
# `subject_absent` where the contract declares no release command at all, and
# `profile_unsupported` where it declares one this engine cannot read (D27).
# Each also declares the code it will emit once a compiler exists, which is
# what closes the registry now rather than growing it later (D5, D31).
# --------------------------------------------------------------------------


def find_release_profile(context: "Context") -> tuple[str, str | None]:
    """Contract: ("absent", None) when the contract declares no release command,
    else ("unsupported", <the declared command id>). This slice ships no profile
    compiler, so a declared release command is a subject it cannot read (D27)."""
    command_id = context.contract["bindings"]["workflow"]["release"]
    if command_id is None:
        return ("absent", None)
    return ("unsupported", command_id)


def release_profile_outcome(context: "Context", repair_id: str) -> "Outcome":
    """The verdict every release-profile item shares, given its own repair.

    Neither branch can read as a pass, and neither drives `incomplete`, because
    all three checks are optional (D6).
    """
    state, command_id = find_release_profile(context)
    if state == "absent":
        return Outcome("not_run", "subject_absent", repair_id, {"declared": False})
    if state == "unsupported":
        return Outcome("not_run", "profile_unsupported", repair_id,
                       {"declared": True, "release_command": bound_fact(command_id)})
    raise ValueError(f"unknown release profile state: {state!r}")


def check_release_profile_rolled_back_reachable(context: "Context") -> "Outcome":
    """Will fail a publication unit that has activation and immutable
    publication but no residue-only compensate edge, which makes rolled_back
    structurally unreachable (#86). This slice ships no profile compiler, so it
    reports not_run."""
    return release_profile_outcome(context, "release_profile.compensate.add")


def check_release_profile_restore_anchor(context: "Context") -> "Outcome":
    """Will fail a publication unit that destroys the anchor its restore edge
    returns to, which the profile has to materialize before the unit runs
    (#86). This slice ships no profile compiler, so it reports not_run."""
    return release_profile_outcome(context, "release_profile.materialize.add")


def check_release_profile_observation_deadline(context: "Context") -> "Outcome":
    """Will fail a publication unit whose observation phase leaves its deadline
    optional, so an observation that never concludes never resolves the unit
    (#86). This slice ships no profile compiler, so it reports not_run."""
    return release_profile_outcome(context, "release_profile.deadline.require")
