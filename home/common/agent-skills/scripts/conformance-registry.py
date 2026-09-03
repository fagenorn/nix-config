#!/usr/bin/env python3
"""The conformance registry: the vocabulary every other module reads.

This module is the engine's leaf (D40). It owns the closed vocabularies the
`ConformanceReport` schema is spelled in, the fact bound every authored value
passes through, the `Check` declarations that make up the registry, the
purpose table that selects from it, and the repair catalogue those checks name.
It declares no evaluator and imports no sibling, so the dependency order
`conformance-registry` -> `conformance-checks` -> `conformance` stays acyclic.

Nothing here reads a clock: no report member and no source line carries a
timestamp, and `FORBIDDEN_MEMBER_NAMES` is what the validator refuses at every
object depth so none can be added later.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path


SCHEMA_VERSION = 1
DOMAINS = ("repository", "compatibility", "host", "verification")
REQUIREMENTS = ("required", "optional")
STATUSES = ("passed", "warning", "failed", "not_run", "suppressed")
OUTCOME_STATUSES = ("passed", "failed", "incomplete")
SAFETY_CLASSES = ("read_only", "worktree", "user_action", "destructive")
PURPOSES = ("workflow_entry", "adoption", "local", "ci", "fleet", "doctor")
SUBJECT_KINDS = ("contract", "projection", "path", "capability", "host_tool",
                 "tracker", "release_profile", "residue", "command")
REPORT_MEMBERS = ("schema_version", "subject", "request", "outcome", "checks", "repairs")
SUBJECT_MEMBERS = ("project_id", "root", "revision", "platform")
PLATFORM_MEMBERS = ("system", "machine")
REQUEST_MEMBERS = ("purpose", "offline", "required_capabilities", "platform_target")
OUTCOME_MEMBERS = ("status", "primary_check_id")
CHECK_MEMBERS = ("id", "domain", "subject_kind", "requirement", "status",
                 "reason_code", "repair_id", "facts")
REPAIR_MEMBERS = ("repair_id", "module", "safety_class", "operation")
OPERATION_MEMBERS = ("subcommand", "args")
REPAIR_MODULES = ("conformance", "resolve-project")
FORBIDDEN_MEMBER_NAMES = ("created_at", "generated_at", "time", "timestamp")
MAX_FACT_KEYS = 8
MAX_FACT_STRING = 200
MAX_FACT_LIST = 8

REVISION_LENGTH = 40
HEX_DIGITS = frozenset("0123456789abcdef")

# Every contract member naming policy a reader opens, plus each projection
# source. A projection target is generated and rewritten by the project, so
# it is not policy and is deliberately absent.
POLICY_PATH_MEMBERS = ("context", "standards", "architecture", "operations",
                       "hints", "rejections")
# The capability reason codes that mean "a helper is not on PATH". A
# capability blocked for any other code is not this check's subject.
TOOL_REASON_CODES = ("command_missing", "tracker_cli_missing")
NIX_STORE_PREFIX = "/nix/store/"

CHILD_TIMEOUT_SECONDS = 15


# --------------------------------------------------------------------------
# Fact bounding
#
# The one route from an authored or filesystem-derived value into `facts`
# (D30). Only an engine-authored literal — a registry id, a closed-set member,
# a repair id — may become a fact without passing through here.
# --------------------------------------------------------------------------


def bound_fact(value: str) -> str:
    """Contract: `value` truncated to MAX_FACT_STRING characters."""
    return value[:MAX_FACT_STRING]


def bound_facts(values, limit: int = MAX_FACT_LIST) -> list[str]:
    """Contract: the first `limit` of `sorted(values)`, each through bound_fact."""
    return [bound_fact(value) for value in sorted(values)[:limit]]


# --------------------------------------------------------------------------
# The ladder's cached stages
#
# One stage per structural check the resolver ladder settles, in ladder order.
# `check_contract_resolvable` is the only writer; the five dependent
# evaluators are pure reads of the cache (D17).
# --------------------------------------------------------------------------


RESOLVABLE_CHECK_ID = "repository.contract.resolvable"
REQUIRED_CAPABILITY_CHECK_ID = "host.capability.required"
STAGE_CHECKS = {
    "present": "repository.contract.present",
    "schema_supported": "compatibility.contract.schema_supported",
    "valid": "repository.contract.valid",
    "projection_fresh": "repository.projection.fresh",
    "capability_required": REQUIRED_CAPABILITY_CHECK_ID,
}
STAGE_ORDER = tuple(STAGE_CHECKS)
# Which stage a resolver refusal names. The raising call site does not decide
# it: `load_contract` refuses `invalid_contract` before the schema stage has
# run, and `validate_projections` refuses it from a later call site (D33).
CODE_STAGES = {
    "not_onboarded": "present",
    "unsupported_schema": "schema_supported",
    "invalid_contract": "valid",
    "invalid_projection": "projection_fresh",
    "capability_unavailable": "capability_required",
}


# --------------------------------------------------------------------------
# Check declarations
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Check:
    """One check declaration: what it judges, what it needs, what it may emit.

    `findings` is the declaration-ordered `(reason_code, repair_id)` mapping
    and the single source for what this check may emit (D31): the evaluation
    guard, report construction and `repair_ids_for` all read it and none
    restates it. `run` names the evaluator, resolved with `getattr`.
    """

    id: str
    domain: str
    subject_kind: str
    requirement: str
    depends_on: tuple[str, ...]
    findings: tuple[tuple[str, str], ...]
    run: str
    network: bool = False

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.findings)


def repair_ids_for(check: Check) -> tuple[str, ...]:
    """Contract: the distinct repair ids `check` declares, sorted ascending."""
    return tuple(sorted({repair_id for _, repair_id in check.findings
                         if repair_id is not None}))


@dataclasses.dataclass(frozen=True)
class Outcome:
    """One evaluator's verdict, before it becomes a check object."""

    status: str
    reason_code: str | None = None
    repair_id: str | None = None
    facts: dict | None = None


@dataclasses.dataclass
class Context:
    """Everything an evaluator may read, and the ladder's one cache.

    `root_arg` is `--repo-root` verbatim — None when the flag was omitted, so
    the resolver's ancestor walk runs — while `root` starts at the caller's
    directory and is replaced by the discovered root (D28).
    """

    root: Path
    root_arg: str | None
    offline: bool
    required: tuple[str, ...]
    resolver: object
    stages: dict = dataclasses.field(
        default_factory=lambda: {name: None for name in STAGE_ORDER})
    contract: dict | None = None
    bindings: dict | None = None
    capabilities: dict | None = None


REPAIRS = {
    "conformance.internal": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "onboarding.contract.missing": {
        "module": "resolve-project", "safety_class": "user_action",
        "operation": None},
    "contract.schema.unsupported": {
        "module": "resolve-project", "safety_class": "user_action",
        "operation": None},
    "contract.invalid": {
        "module": "resolve-project", "safety_class": "user_action",
        "operation": None},
    "projection.regenerate": {
        "module": "resolve-project", "safety_class": "worktree",
        "operation": {"subcommand": "write-projections", "args": []}},
    "capability.required.unavailable": {
        "module": "resolve-project", "safety_class": "user_action",
        "operation": None},
    # No command materialises a store-linked policy file or installs a helper,
    # so both operations are null (D25).
    "host.policy_path.materialize": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "host.helper.install": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    # A rerun repeats the caller's own request without --offline, so no fixed
    # argv performs it and bare `run` is an argparse usage error (D25).
    "conformance.rerun_online": {
        "module": "conformance", "safety_class": "read_only",
        "operation": None},
    "host.tracker.authenticate": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    # No engine subcommand admits a path into a class, edits an ignore file or
    # destructures a command, so all three operations are null (D25). Editing
    # an ignore file changes the working tree, which is why only the middle one
    # is `worktree`.
    "lifecycle.path.classify": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "lifecycle.ignore.repair": {
        "module": "conformance", "safety_class": "worktree",
        "operation": None},
    "contract.commands.destructure": {
        "module": "resolve-project", "safety_class": "user_action",
        "operation": None},
    # v1 reports residue and executes nothing, so all three operations are null
    # and none is `destructive` (D10). Retaining is the reader's own call;
    # removing touches only the worktree the run directory lives in (D26).
    "lifecycle.residue.nested_ledger.retain": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "lifecycle.residue.nested_ledger.remove": {
        "module": "conformance", "safety_class": "worktree",
        "operation": None},
    "lifecycle.residue.root_scratch": {
        "module": "conformance", "safety_class": "worktree",
        "operation": None},
    # Every release-profile repair is an edit to an authored profile this
    # engine neither reads nor writes, so all three are `user_action` with a
    # null operation (D25).
    "release_profile.compensate.add": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "release_profile.materialize.add": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
    "release_profile.deadline.require": {
        "module": "conformance", "safety_class": "user_action",
        "operation": None},
}


# --------------------------------------------------------------------------
# The residue findings
# --------------------------------------------------------------------------


LIVE_OWNER = "live_owner"
UNACKNOWLEDGED_RESIDUE = "unacknowledged_residue"
TERMINAL_RESIDUE = "terminal_residue"
# Declaration order is severity order, and this tuple is the check's own
# `findings` (D31): the evaluator reads the first class it counted, so a report
# naming a removable run while another is live never offers the removal repair.
NESTED_LEDGER_FINDINGS = (
    (LIVE_OWNER, "lifecycle.residue.nested_ledger.retain"),
    (UNACKNOWLEDGED_RESIDUE, "lifecycle.residue.nested_ledger.retain"),
    (TERMINAL_RESIDUE, "lifecycle.residue.nested_ledger.remove"),
)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


REGISTRY: tuple[Check, ...] = (
    Check(RESOLVABLE_CHECK_ID, "repository", "contract", "required", (),
          (("resolver_failure", "conformance.internal"),),
          "check_contract_resolvable"),
    Check("repository.contract.present", "repository", "contract", "required",
          (RESOLVABLE_CHECK_ID,),
          (("not_onboarded", "onboarding.contract.missing"),),
          "check_contract_present"),
    Check("compatibility.contract.schema_supported", "compatibility", "contract",
          "required", ("repository.contract.present",),
          (("unsupported_schema", "contract.schema.unsupported"),),
          "check_schema_supported"),
    Check("repository.contract.valid", "repository", "contract", "required",
          ("compatibility.contract.schema_supported",),
          (("invalid_contract", "contract.invalid"),),
          "check_contract_valid"),
    Check("repository.projection.fresh", "repository", "projection", "required",
          ("repository.contract.valid",),
          (("invalid_projection", "projection.regenerate"),),
          "check_projection_fresh"),
    Check(REQUIRED_CAPABILITY_CHECK_ID, "host", "capability", "required",
          ("repository.contract.valid",),
          (("capability_unavailable", "capability.required.unavailable"),),
          "check_capability_required"),
    Check("host.policy_path.no_follow_readable", "host", "path", "required",
          ("repository.contract.valid",),
          (("policy_path_symlinked", "host.policy_path.materialize"),),
          "check_policy_path_no_follow_readable"),
    Check("host.executor.helper_on_path", "host", "host_tool", "required",
          ("repository.contract.valid",),
          (("helper_missing", "host.helper.install"),),
          "check_executor_helper_on_path"),
    Check("host.tracker.credential", "host", "tracker", "required",
          ("repository.contract.valid",),
          (("offline_constraint", "conformance.rerun_online"),
           ("unsupported_tracker_kind", "host.tracker.authenticate"),
           ("tracker_credential_missing", "host.tracker.authenticate")),
          "check_tracker_credential", network=True),
    Check("repository.paths.classified", "repository", "path", "required",
          ("repository.contract.valid",),
          (("unclassified_path", "lifecycle.path.classify"),),
          "check_paths_classified"),
    Check("repository.ignore.runtime_sentinel", "repository", "path", "required",
          ("repository.contract.valid",),
          (("runtime_ignore_missing", "lifecycle.ignore.repair"),
           ("overbroad_ignore", "lifecycle.ignore.repair")),
          "check_ignore_runtime_sentinel"),
    Check("verification.commands.no_shell_indirection", "verification", "command",
          "required", ("repository.contract.valid",),
          (("shell_indirection", "contract.commands.destructure"),),
          "check_commands_no_shell_indirection"),
    Check("repository.residue.nested_ledger", "repository", "residue", "optional",
          ("repository.contract.valid",), NESTED_LEDGER_FINDINGS,
          "check_residue_nested_ledger"),
    # Its pattern set is a constant rather than contract-derived, so it still
    # reports on a repository whose contract is invalid.
    Check("repository.residue.root_scratch", "repository", "residue", "optional",
          ("repository.contract.present",),
          (("root_scratch_present", "lifecycle.residue.root_scratch"),),
          "check_residue_root_scratch"),
    # The third code of each trio is emitted by the compiler slice; declaring
    # it now is what closes the registry rather than growing it later (D5).
    Check("repository.release_profile.rolled_back_reachable", "repository",
          "release_profile", "optional", ("repository.contract.valid",),
          (("subject_absent", "release_profile.compensate.add"),
           ("profile_unsupported", "release_profile.compensate.add"),
           ("rolled_back_unreachable", "release_profile.compensate.add")),
          "check_release_profile_rolled_back_reachable"),
    Check("repository.release_profile.restore_anchor", "repository",
          "release_profile", "optional", ("repository.contract.valid",),
          (("subject_absent", "release_profile.materialize.add"),
           ("profile_unsupported", "release_profile.materialize.add"),
           ("restore_anchor_destroyed", "release_profile.materialize.add")),
          "check_release_profile_restore_anchor"),
    Check("repository.release_profile.observation_deadline", "repository",
          "release_profile", "optional", ("repository.contract.valid",),
          (("subject_absent", "release_profile.deadline.require"),
           ("profile_unsupported", "release_profile.deadline.require"),
           ("observation_deadline_optional", "release_profile.deadline.require")),
          "check_release_profile_observation_deadline"),
)
REGISTRY_BY_ID = {check.id: check for check in REGISTRY}


# --------------------------------------------------------------------------
# Purpose selection
# --------------------------------------------------------------------------


WORKFLOW_ENTRY_LADDER = (
    "repository.contract.resolvable", "repository.contract.present",
    "compatibility.contract.schema_supported", "repository.contract.valid",
    "repository.projection.fresh", "host.capability.required",
)
PURPOSE_DOMAINS = {
    "adoption": ("repository", "compatibility"),
    "ci":       ("repository", "compatibility", "verification"),
    "fleet":    ("repository", "compatibility"),
    "doctor":   DOMAINS,
}


def select(purpose: str, required: tuple[str, ...] = ()) -> tuple[Check, ...]:
    """Contract: the checks `purpose` runs, in REGISTRY (dependency) order.

    Every purpose but `workflow_entry` selects by domain rather than by a
    hand-maintained id list, so registering a check is enough for it to be
    picked up (D21). `local` is the entry ladder plus every host check.

    A non-empty `required` adds the capability check whatever the purpose's
    domains are (D38): `adoption`, `ci` and `fleet` carry no `host` domain, and
    without this union they would answer `passed` while a caller-declared
    required capability is unsupported or blocked.
    """
    if purpose == "workflow_entry":
        chosen = set(WORKFLOW_ENTRY_LADDER)
    elif purpose == "local":
        chosen = set(WORKFLOW_ENTRY_LADDER) | {
            check.id for check in REGISTRY if check.domain == "host"}
    elif purpose in PURPOSE_DOMAINS:
        chosen = {check.id for check in REGISTRY
                  if check.domain in PURPOSE_DOMAINS[purpose]}
    else:
        raise ValueError(f"unknown purpose: {purpose!r}")
    if required:
        chosen.add(REQUIRED_CAPABILITY_CHECK_ID)
    return tuple(check for check in REGISTRY if check.id in chosen)
