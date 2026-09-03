#!/usr/bin/env python3
"""The conformance engine: judge a project against the closed check registry.

This module owns the `ConformanceReport` — its closed vocabularies, its exact
member sets, and the invariants a report must satisfy beyond its field shapes.
`validate-report` is the schema validator every consumer and every test checks
a report against, so the schema has exactly one executable definition and no
consumer re-derives it.

A schema refusal prints the resolver's refusal shape — one JSON object
carrying an `error` member — on stdout and exits 2. An argparse usage error
also exits 2 but prints no JSON, which is how a caller tells the two apart.

Nothing here reads a clock: no report member and no source line carries a
timestamp, and `FORBIDDEN_MEMBER_NAMES` is validated at every object depth so
none can be added later without the validator refusing it.
"""

from __future__ import annotations

import argparse
import dataclasses
import fcntl
import fnmatch
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


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
ENGINE_FAILURE_MESSAGE = "the conformance engine failed unexpectedly"


class ReportError(Exception):
    """One schema refusal: ordered violations against a candidate report."""

    def __init__(self, violations: list[dict]) -> None:
        ordered = sorted(violations, key=lambda item: item["pointer"])
        super().__init__(f"{len(ordered)} violation(s)")
        self.violations = ordered


# --------------------------------------------------------------------------
# Violation collection
#
# The validator is one collecting pass: a helper appends what it can see and
# reports whether the value it judged is sound enough for its dependents, so
# one broken member never hides the rest of the report.
# --------------------------------------------------------------------------


def violation(pointer: str, message: str) -> dict:
    return {"pointer": pointer, "message": message}


def exact_members(value: object, pointer: str, expected: tuple[str, ...],
                  violations: list[dict]) -> bool:
    """Refuse a non-object, every absent member and every unexpected one.

    A member whose name is in FORBIDDEN_MEMBER_NAMES is refused here, so the
    rule holds at every object depth rather than only at the top.
    """
    if not isinstance(value, dict):
        violations.append(violation(pointer, "must be an object"))
        return False
    sound = True
    for name in expected:
        if name not in value:
            violations.append(violation(
                f"{pointer}/{name}", "required member is absent"))
            sound = False
    for name in sorted(value):
        if name in FORBIDDEN_MEMBER_NAMES:
            violations.append(violation(
                f"{pointer}/{name}", "this schema carries no timestamp"))
            sound = False
        elif name not in expected:
            violations.append(violation(
                f"{pointer}/{name}", "member is not part of this schema"))
            sound = False
    return sound


def closed_value(value: object, pointer: str, allowed: tuple[str, ...],
                 violations: list[dict]) -> bool:
    if isinstance(value, str) and value in allowed:
        return True
    violations.append(violation(
        pointer, "must be one of: " + ", ".join(allowed)))
    return False


def non_empty_string(value: object, pointer: str, violations: list[dict]) -> bool:
    if isinstance(value, str) and value:
        return True
    violations.append(violation(pointer, "must be a non-empty string"))
    return False


def nullable_string(value: object, pointer: str, violations: list[dict]) -> bool:
    if value is None or (isinstance(value, str) and value):
        return True
    violations.append(violation(pointer, "must be null or a non-empty string"))
    return False


def boolean(value: object, pointer: str, violations: list[dict]) -> bool:
    if isinstance(value, bool):
        return True
    violations.append(violation(pointer, "must be a boolean"))
    return False


def string_list(value: object, pointer: str, violations: list[dict]) -> bool:
    if not isinstance(value, list):
        violations.append(violation(pointer, "must be a list"))
        return False
    sound = True
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry:
            violations.append(violation(
                f"{pointer}/{index}", "must be a non-empty string"))
            sound = False
    return sound


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
# Report validation
# --------------------------------------------------------------------------


def is_fact_value(value: object) -> bool:
    """A bool, an int, a bounded string, or a bounded list of bounded strings."""
    if isinstance(value, int):  # a bool is an int here, and both are facts
        return True
    if isinstance(value, str):
        return len(value) <= MAX_FACT_STRING
    if isinstance(value, list):
        return len(value) <= MAX_FACT_LIST and all(
            isinstance(entry, str) and len(entry) <= MAX_FACT_STRING
            for entry in value)
    return False


def validate_facts(facts: object, pointer: str, violations: list[dict]) -> None:
    """The whole no-secrets guarantee: a structural bound, no content heuristic (D9)."""
    if not isinstance(facts, dict):
        violations.append(violation(pointer, "must be an object"))
        return
    if len(facts) > MAX_FACT_KEYS:
        violations.append(violation(
            pointer, f"must carry at most {MAX_FACT_KEYS} keys"))
    for key in sorted(facts):
        key_pointer = f"{pointer}/{key}"
        if key in FORBIDDEN_MEMBER_NAMES:
            violations.append(violation(
                key_pointer, "this schema carries no timestamp"))
            continue
        if not is_fact_value(facts[key]):
            violations.append(violation(
                key_pointer,
                "must be a boolean, an integer, a string of at most "
                f"{MAX_FACT_STRING} characters, or a list of at most "
                f"{MAX_FACT_LIST} such strings"))


def validate_subject(subject: object, violations: list[dict]) -> None:
    exact_members(subject, "/subject", SUBJECT_MEMBERS, violations)
    if not isinstance(subject, dict):
        return
    if "project_id" in subject:
        value = subject["project_id"]
        if value is not None and not isinstance(value, str):
            violations.append(violation(
                "/subject/project_id", "must be null or a string"))
    if "root" in subject:
        non_empty_string(subject["root"], "/subject/root", violations)
    if "revision" in subject:
        value = subject["revision"]
        if not (value is None or (isinstance(value, str)
                                  and len(value) == REVISION_LENGTH
                                  and set(value) <= HEX_DIGITS)):
            violations.append(violation(
                "/subject/revision",
                f"must be null or {REVISION_LENGTH} lowercase hex characters"))
    if "platform" in subject:
        platform = subject["platform"]
        if exact_members(platform, "/subject/platform", PLATFORM_MEMBERS,
                         violations):
            for name in PLATFORM_MEMBERS:
                non_empty_string(
                    platform[name], f"/subject/platform/{name}", violations)


def validate_request(request: object, violations: list[dict]) -> None:
    exact_members(request, "/request", REQUEST_MEMBERS, violations)
    if not isinstance(request, dict):
        return
    if "purpose" in request:
        closed_value(request["purpose"], "/request/purpose", PURPOSES, violations)
    if "offline" in request:
        boolean(request["offline"], "/request/offline", violations)
    if "required_capabilities" in request:
        pointer = "/request/required_capabilities"
        names = request["required_capabilities"]
        # Membership in the resolver's CAPABILITY_NAMES is deliberately not
        # judged here: sourcing it would load the resolver and cost this
        # function its purity. The closed argparse `choices` is that gate.
        if string_list(names, pointer, violations):
            if list(names) != sorted(names):
                violations.append(violation(pointer, "must be sorted ascending"))
            elif len(set(names)) != len(names):
                violations.append(violation(pointer, "must not repeat a name"))
    if "platform_target" in request:
        non_empty_string(
            request["platform_target"], "/request/platform_target", violations)


def validate_check(check: object, pointer: str, violations: list[dict]) -> None:
    exact_members(check, pointer, CHECK_MEMBERS, violations)
    if not isinstance(check, dict):
        return
    if "id" in check:
        non_empty_string(check["id"], f"{pointer}/id", violations)
    if "domain" in check:
        closed_value(check["domain"], f"{pointer}/domain", DOMAINS, violations)
    if "subject_kind" in check:
        closed_value(check["subject_kind"], f"{pointer}/subject_kind",
                     SUBJECT_KINDS, violations)
    if "requirement" in check:
        closed_value(check["requirement"], f"{pointer}/requirement",
                     REQUIREMENTS, violations)
    known_status = "status" in check and closed_value(
        check["status"], f"{pointer}/status", STATUSES, violations)
    if "reason_code" in check:
        nullable_string(check["reason_code"], f"{pointer}/reason_code", violations)
    if "repair_id" in check:
        nullable_string(check["repair_id"], f"{pointer}/repair_id", violations)
    if "facts" in check:
        validate_facts(check["facts"], f"{pointer}/facts", violations)
    if known_status:
        validate_check_consistency(check, pointer, violations)


def validate_check_consistency(check: dict, pointer: str,
                               violations: list[dict]) -> None:
    """Status against reason code, repair and facts (D37)."""
    status = check["status"]
    if status in ("passed", "suppressed"):
        if check.get("reason_code") is not None:
            violations.append(violation(
                f"{pointer}/reason_code", f"must be null for a {status} check"))
        if check.get("repair_id") is not None:
            violations.append(violation(
                f"{pointer}/repair_id", f"must be null for a {status} check"))
    elif status in ("failed", "warning", "not_run"):
        if check.get("reason_code") is None:
            violations.append(violation(
                f"{pointer}/reason_code",
                f"must name a reason code for a {status} check"))
    else:
        raise ValueError(f"unknown check status: {status!r}")
    if status == "suppressed":
        facts = check.get("facts")
        if not (isinstance(facts, dict) and list(facts) == ["suppressed_by"]
                and isinstance(facts["suppressed_by"], str)
                and facts["suppressed_by"]):
            violations.append(violation(
                f"{pointer}/facts",
                "a suppressed check carries exactly a non-empty suppressed_by"))


def validate_operation(operation: object, pointer: str,
                       violations: list[dict]) -> None:
    if operation is None:
        return
    exact_members(operation, pointer, OPERATION_MEMBERS, violations)
    if not isinstance(operation, dict):
        return
    if "subcommand" in operation:
        non_empty_string(operation["subcommand"], f"{pointer}/subcommand", violations)
    if "args" in operation:
        string_list(operation["args"], f"{pointer}/args", violations)


def validate_repair(repair: object, pointer: str, violations: list[dict]) -> None:
    exact_members(repair, pointer, REPAIR_MEMBERS, violations)
    if not isinstance(repair, dict):
        return
    if "repair_id" in repair:
        non_empty_string(repair["repair_id"], f"{pointer}/repair_id", violations)
    if "module" in repair:
        closed_value(repair["module"], f"{pointer}/module", REPAIR_MODULES,
                     violations)
    if "safety_class" in repair:
        closed_value(repair["safety_class"], f"{pointer}/safety_class",
                     SAFETY_CLASSES, violations)
    if "operation" in repair:
        validate_operation(repair["operation"], f"{pointer}/operation", violations)


def ordered_unique(names: list[str], pointer: str, subject: str,
                   violations: list[dict]) -> None:
    if list(names) != sorted(names):
        violations.append(violation(pointer, f"must be sorted ascending by {subject}"))
    elif len(set(names)) != len(names):
        violations.append(violation(pointer, f"must not repeat a {subject}"))


def expected_outcome(checks: list[dict]) -> tuple[str, str | None]:
    """Outcome precedence over the emitted checks; a warning never counts."""
    for check in checks:
        if check["status"] == "failed":
            return "failed", check["id"]
    for check in checks:
        if check["status"] == "not_run" and check["requirement"] == "required":
            return "incomplete", check["id"]
    return "passed", None


def is_comparable(check: object) -> bool:
    """Whether a check is sound enough to take part in the outcome invariants."""
    return (isinstance(check, dict)
            and isinstance(check.get("id"), str)
            and check.get("status") in STATUSES
            and check.get("requirement") in REQUIREMENTS)


def validate_outcome(outcome: object, checks: object,
                     violations: list[dict]) -> None:
    exact_members(outcome, "/outcome", OUTCOME_MEMBERS, violations)
    if not isinstance(outcome, dict):
        return
    if "status" in outcome:
        known = closed_value(outcome["status"], "/outcome/status",
                             OUTCOME_STATUSES, violations)
    else:
        known = False
    if "primary_check_id" in outcome:
        nullable_string(
            outcome["primary_check_id"], "/outcome/primary_check_id", violations)
    if not known or "primary_check_id" not in outcome:
        return
    if not (isinstance(checks, list) and all(is_comparable(c) for c in checks)):
        # A check the field-shape pass already refused cannot be judged for
        # precedence; its own violation is the report the caller needs.
        return
    status, primary = expected_outcome(checks)
    if outcome["status"] != status:
        violations.append(violation(
            "/outcome/status",
            f"the emitted checks imply {status}"))
        return
    if outcome["primary_check_id"] != primary:
        violations.append(violation(
            "/outcome/primary_check_id",
            "must name the first failed check in emitted order, else the "
            "first required not_run check, else be null"))


def validate_closure(checks: object, repairs: object,
                     violations: list[dict]) -> None:
    """`repairs` and the repairs the checks name are the same set, both ways."""
    if not (isinstance(checks, list) and isinstance(repairs, list)):
        return
    named = set()
    for check in checks:
        if not isinstance(check, dict):
            return
        repair_id = check.get("repair_id")
        if repair_id is not None:
            if not isinstance(repair_id, str):
                return
            named.add(repair_id)
    declared = set()
    for repair in repairs:
        if not isinstance(repair, dict) or not isinstance(repair.get("repair_id"), str):
            return
        declared.add(repair["repair_id"])
    for repair_id in sorted(named - declared):
        violations.append(violation(
            "/repairs", f"a check names the absent repair {repair_id}"))
    for repair_id in sorted(declared - named):
        violations.append(violation(
            "/repairs", f"the repair {repair_id} is named by no check"))


def validate_report(report: object) -> None:
    """Contract: returns None for a schema-valid report; otherwise raises
    ReportError whose violations are sorted byte-wise ascending by pointer."""
    violations: list[dict] = []
    if not isinstance(report, dict):
        raise ReportError([violation("", "the report must be an object")])
    exact_members(report, "", REPORT_MEMBERS, violations)
    if "schema_version" in report:
        version = report["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int) \
                or version != SCHEMA_VERSION:
            violations.append(violation(
                "/schema_version", f"must be the integer {SCHEMA_VERSION}"))
    if "subject" in report:
        validate_subject(report["subject"], violations)
    if "request" in report:
        validate_request(report["request"], violations)
    checks = report.get("checks")
    if "checks" in report:
        if isinstance(checks, list):
            for index, check in enumerate(checks):
                validate_check(check, f"/checks/{index}", violations)
            if all(isinstance(c, dict) and isinstance(c.get("id"), str)
                   for c in checks):
                ordered_unique([c["id"] for c in checks], "/checks", "id",
                               violations)
        else:
            violations.append(violation("/checks", "must be a list"))
    repairs = report.get("repairs")
    if "repairs" in report:
        if isinstance(repairs, list):
            for index, repair in enumerate(repairs):
                validate_repair(repair, f"/repairs/{index}", violations)
            if all(isinstance(r, dict) and isinstance(r.get("repair_id"), str)
                   for r in repairs):
                ordered_unique([r["repair_id"] for r in repairs], "/repairs",
                               "repair_id", violations)
        else:
            violations.append(violation("/repairs", "must be a list"))
    if "outcome" in report:
        validate_outcome(report["outcome"], checks, violations)
    validate_closure(checks, repairs, violations)
    if violations:
        raise ReportError(violations)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"),
              allow_nan=False)
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict]) -> int:
    emit_json({"error": {"code": code, "repair_id": repair_id,
                         "violations": violations}})
    return 2


# --------------------------------------------------------------------------
# The resolver, in process
# --------------------------------------------------------------------------


RESOLVER_NAMES = ("resolve-project.py", "resolve_project.py", "resolve-project")
RESOLVER_MODULE_NAME = "conformance_resolve_project"
_RESOLVER = None


def load_resolver():
    """Contract: the sibling `resolve-project` module, imported once (D2).

    The three names are tried in that order so an extensionless Nix-installed
    link loads identically to the repository file, whose `main()` is
    `__main__`-guarded — executing the module therefore runs nothing. The
    directory is `__file__`'s parent unresolved, because the installed
    binary is a symlink into the store while its sibling resolver is not.
    """
    global _RESOLVER
    if _RESOLVER is not None:
        return _RESOLVER
    directory = Path(__file__).parent.resolve()
    for name in RESOLVER_NAMES:
        path = directory / name
        if path.is_file():
            break
    else:
        raise RuntimeError(f"no resolver module beside {directory}")
    spec = importlib.util.spec_from_loader(
        RESOLVER_MODULE_NAME, SourceFileLoader(RESOLVER_MODULE_NAME, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _RESOLVER = module
    return _RESOLVER


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
# The registry
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
}


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


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def evaluator(name: str):
    """The evaluator a check declares, resolved through this module's globals.

    `globals()` rather than `sys.modules[__name__]`: the S3 loader builds a
    fresh module instance per call under one shared name, so resolving through
    `sys.modules` would fetch the newest instance's function and silently
    bypass a rebind made on the instance under test.
    """
    return globals()[name]


def failed_ancestor(check: Check, results: dict, selected: set) -> str | None:
    """The first failed check in `check`'s dependency closure, REGISTRY order.

    The closure is taken over the *selected* set: a check a purpose does not
    run cannot suppress one it does.
    """
    seen: set = set()
    pending = [name for name in check.depends_on if name in selected]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(name for name in REGISTRY_BY_ID[current].depends_on
                       if name in selected)
    for ancestor in REGISTRY:
        if ancestor.id in seen and results[ancestor.id].status == "failed":
            return ancestor.id
    return None


def guard_finding(check: Check, outcome: Outcome) -> None:
    """Refuse an outcome the check's own `findings` does not declare (D31)."""
    if outcome.reason_code is None:
        if outcome.repair_id is not None:
            raise ValueError(
                f"{check.id} named repair {outcome.repair_id!r} with no reason code")
        return
    if (outcome.reason_code, outcome.repair_id) not in check.findings:
        raise ValueError(
            f"{check.id} emitted the undeclared finding "
            f"({outcome.reason_code!r}, {outcome.repair_id!r})")


def as_check(check: Check, outcome: Outcome) -> dict:
    return {
        "id": check.id,
        "domain": check.domain,
        "subject_kind": check.subject_kind,
        "requirement": check.requirement,
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "repair_id": outcome.repair_id,
        "facts": dict(outcome.facts) if outcome.facts else {},
    }


def evaluate(purpose: str, context: Context) -> list[dict]:
    """Contract: the check objects `purpose` emits, sorted by id.

    Evaluation walks REGISTRY order, which is topological, so every ancestor
    has a result before its dependent asks for one (D24). `workflow_entry`
    stops at the first `failed` or `not_run` and carries that one root cause;
    `suppressed` never stops it, because it names a step the ladder skipped
    rather than the cause (D3, D33). A network-flagged check is `not_run`
    whenever `context.offline` holds, decided before the dispatch (D7).
    """
    checks = select(purpose, context.required)
    selected = {check.id for check in checks}
    results: dict = {}
    emitted: list[dict] = []
    for check in checks:
        blocker = failed_ancestor(check, results, selected)
        if blocker is not None:
            outcome = Outcome("suppressed", facts={"suppressed_by": blocker})
        elif context.offline and check.network:
            # Before the dispatch, so a skipped probe can never become a pass.
            outcome = Outcome("not_run", "offline_constraint",
                              "conformance.rerun_online")
        else:
            outcome = evaluator(check.run)(context)
        guard_finding(check, outcome)
        results[check.id] = outcome
        emitted.append(as_check(check, outcome))
        if purpose == "workflow_entry" and outcome.status in ("failed", "not_run"):
            return [emitted[-1]]
    return sorted(emitted, key=lambda check: check["id"])


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def contract_project_id(contract) -> str | None:
    """The authored project id, or None when the ladder never parsed one.

    A parsed contract can still be invalid, so every step is checked: an
    explicit null beats a fabricated identity (D23).
    """
    if not isinstance(contract, dict):
        return None
    project = contract.get("project")
    if not isinstance(project, dict):
        return None
    value = project.get("id")
    return value if isinstance(value, str) else None


def head_revision(root: Path) -> str | None:
    """The checked-out commit, or None outside a repository (D19, D23)."""
    completed = bounded_run(["git", "-C", str(root), "rev-parse", "HEAD"], root)
    if completed is None or completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    if len(value) == REVISION_LENGTH and set(value) <= HEX_DIGITS:
        return value
    return None


def build_report(purpose: str, context: Context, checks: list[dict]) -> dict:
    """Contract: the six-member report for `checks`, ready for validate_report.

    It runs after `evaluate` because `subject.root` is the root the ladder
    discovered, not the directory the caller stood in (D28).
    """
    repair_ids = sorted({check["repair_id"] for check in checks
                         if check["repair_id"] is not None})
    status, primary = expected_outcome(checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": {
            "project_id": contract_project_id(context.contract),
            "root": str(context.root),
            "revision": head_revision(context.root),
            "platform": {"system": platform.system(),
                         "machine": platform.machine()},
        },
        "request": {
            "purpose": purpose,
            "offline": context.offline,
            "required_capabilities": list(context.required),
            "platform_target": f"{platform.system()}/{platform.machine()}",
        },
        "outcome": {"status": status, "primary_check_id": primary},
        "checks": checks,
        "repairs": [{"repair_id": repair_id, **REPAIRS[repair_id]}
                    for repair_id in repair_ids],
    }


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def command_run(args: argparse.Namespace) -> int:
    """Contract: prints one schema-valid report and returns 0, or 2 for a
    non-passing workflow_entry. It catches nothing: an unexpected exception
    reaches main's single boundary and becomes the D15 refusal (D29)."""
    context = Context(
        root=(Path(args.repo_root).resolve() if args.repo_root
              else Path.cwd().resolve()),
        root_arg=args.repo_root,
        offline=args.offline,
        required=tuple(sorted(set(args.require))),
        resolver=load_resolver(),
    )
    report = build_report(args.purpose, context, evaluate(args.purpose, context))
    validate_report(report)
    emit_json(report)
    if args.purpose == "workflow_entry" and report["outcome"]["status"] != "passed":
        return 2
    return 0


def command_validate_report(args: argparse.Namespace) -> int:
    """Judge one candidate report file against the schema.

    The three ways the file itself can defeat the parser each become a single
    violation at the empty pointer, so a caller distinguishes an unusable file
    from a report the schema refused by reading the pointer, not the message.
    """
    try:
        text = Path(args.input).read_text(encoding="utf-8")
    except OSError:
        return emit_error("resolver_failure", "conformance.internal",
                          [violation("", "the report file could not be read")])
    except UnicodeDecodeError:
        return emit_error("resolver_failure", "conformance.internal",
                          [violation("", "the report file is not valid UTF-8")])
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return emit_error("resolver_failure", "conformance.internal",
                          [violation("", "the report file is not valid JSON")])
    try:
        validate_report(report)
    except ReportError as error:
        return emit_error("resolver_failure", "conformance.internal",
                          error.violations)
    return emit_json({"valid": True})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conformance",
        description="Judge a project against the closed conformance registry.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    judge = subparsers.add_parser(
        "run", help="judge a project and print one ConformanceReport")
    judge.add_argument(
        "--purpose", required=True, choices=PURPOSES,
        help="the declared purpose whose check ladder the engine selects")
    judge.add_argument(
        "--repo-root", default=None, metavar="PATH",
        help="the project root; omitted, the resolver discovers it (D28)")
    judge.add_argument(
        "--offline", action="store_true",
        help="declare the network unavailable; never inferred, never probed")
    judge.add_argument(
        "--require", action="append", default=[], metavar="CAPABILITY",
        choices=load_resolver().CAPABILITY_NAMES,
        help="a capability this run demands; repeatable")
    validate = subparsers.add_parser(
        "validate-report",
        help="refuse unless the named file is a schema-valid ConformanceReport")
    validate.add_argument(
        "--input", required=True, metavar="PATH",
        help="the candidate report file, as UTF-8 JSON")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    handlers = {"run": command_run, "validate-report": command_validate_report}
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"unknown subcommand: {args.command!r}")
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    """The engine's one exception boundary (D15, D29).

    Resolver loading, parser construction and dispatch all sit inside it —
    `--require`'s choices come from the resolver, so a resolver that will not
    load refuses in this shape rather than tracebacking. The violation is the
    fixed sentence, never the exception text, which can name a path. The one
    declared exception is the ladder's own catch (D17).
    """
    try:
        return dispatch(build_parser().parse_args(argv))
    except SystemExit:
        raise                      # argparse usage: exit 2, no JSON
    except Exception:
        return emit_error("resolver_failure", "conformance.internal",
                          [violation("", ENGINE_FAILURE_MESSAGE)])


if __name__ == "__main__":
    sys.exit(main())
