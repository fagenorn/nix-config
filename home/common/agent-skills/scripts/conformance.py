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
import json
from pathlib import Path
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
# Subcommands
# --------------------------------------------------------------------------


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
    validate = subparsers.add_parser(
        "validate-report",
        help="refuse unless the named file is a schema-valid ConformanceReport")
    validate.add_argument(
        "--input", required=True, metavar="PATH",
        help="the candidate report file, as UTF-8 JSON")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    handlers = {"validate-report": command_validate_report}
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"unknown subcommand: {args.command!r}")
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
