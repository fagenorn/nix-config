"""The `verify` block grammar: parsing a hold comment and checking its structure.

`parse_block` extracts the block from a hold comment (or a bare JSON text) and
`lint_block` walks it, collecting every finding as `{"field", "code",
"message"}`. A finding's `field` is a path into the block
(`checks[0].when.not_before`); an unknown member's path is its own path.
"""

import json
import re
from datetime import datetime

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

SHA = re.compile(r"^[0-9a-f]{40}$")
HOST = re.compile(r"^[a-z0-9-]+$")
AC = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
REASONS = ("senses", "hands", "credentials", "money", "taste")

FENCE = re.compile(r"(?ms)^```verify[ \t]*\n(.*?)^```[ \t]*$")

TOP_FIELDS = ("v", "merge", "checks")
TOP_REQUIRED = ("v", "merge", "checks")
CHECK_FIELDS = (
    "ac", "kind", "host", "when", "run", "expect", "effects", "mode",
    "on_fail", "expires_after_days", "on_expire", "reason",
)
CHECK_REQUIRED = ("ac", "kind", "host", "when", "run")
WHEN_FIELDS = ("deployed_includes", "released_includes", "ci_run_includes", "not_before", "days_after")
CI_FIELDS = ("workflow", "branch", "sha")
DAYS_AFTER_FIELDS = ("event", "days")
EXPECT_FIELDS = ("json",)
TEST_FIELDS = ("pointer", "equals", "min_len")

KINDS = ("evidence", "human")
EFFECTS = ("none", "live", "paid")
MODES = ("assert", "observe")
ON_FAIL = ("label", "ask")
ON_EXPIRE = ("close", "ask")
EVENTS = ("deployed", "released")


def finding(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def parse_block(text: str) -> tuple[object | None, list[dict]]:
    """Extract and strictly parse the block; on failure `(None, [finding])`."""
    fences = FENCE.findall(text)
    if len(fences) > 1:
        return None, [finding("block", "fence_count", f"{len(fences)} verify fences; exactly one is allowed")]
    body = fences[0] if fences else text
    try:
        block = json.loads(
            body, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal
        )
    except ValueError as error:
        return None, [finding("block", "not_json", f"the block is not strict JSON: {error}")]
    return block, []


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_sha(value: object) -> bool:
    return isinstance(value, str) and SHA.match(value) is not None


def is_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def closed_object(value: object, path: str, fields: tuple, required: tuple, errors: list) -> bool:
    """Check `value` is an object with only `fields` and all `required`; True when it is an object."""
    where = path or "block"
    if not isinstance(value, dict):
        errors.append(finding(where, "invalid_value", "must be an object"))
        return False
    for name in value:
        if name not in fields:
            errors.append(finding(join(path, name), "unknown_field", f"{name!r} is not a member of this object"))
    for name in required:
        if name not in value:
            errors.append(finding(join(path, name), "missing_field", f"{name!r} is required"))
    return True


def invalid(errors: list, path: str, message: str) -> None:
    errors.append(finding(path, "invalid_value", message))


def check_iso(value: object, path: str, errors: list) -> None:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        moment = None
    if moment is None:
        invalid(errors, path, "must be an ISO 8601 time")
    elif moment.utcoffset() is None:
        invalid(errors, path, "must carry a UTC offset")


def check_choice(value: object, path: str, choices: tuple, errors: list) -> None:
    if not isinstance(value, str) or value not in choices:
        invalid(errors, path, f"must be one of {', '.join(choices)}")


def check_when(when: object, path: str, errors: list) -> None:
    if not closed_object(when, path, WHEN_FIELDS, (), errors):
        return
    if not when:
        invalid(errors, path, "must not be empty")
        return
    for name in ("deployed_includes", "released_includes"):
        if name in when and not is_sha(when[name]):
            invalid(errors, join(path, name), "must be a 40-character lowercase hex sha")
    if "ci_run_includes" in when:
        ci_path = join(path, "ci_run_includes")
        ci = when["ci_run_includes"]
        if closed_object(ci, ci_path, CI_FIELDS, CI_FIELDS, errors):
            for name in ("workflow", "branch"):
                if name in ci and not is_text(ci[name]):
                    invalid(errors, join(ci_path, name), "must be a non-empty string")
            if "sha" in ci and not is_sha(ci["sha"]):
                invalid(errors, join(ci_path, "sha"), "must be a 40-character lowercase hex sha")
    if "not_before" in when:
        check_iso(when["not_before"], join(path, "not_before"), errors)
    if "days_after" in when:
        days_path = join(path, "days_after")
        days_after = when["days_after"]
        if closed_object(days_after, days_path, DAYS_AFTER_FIELDS, DAYS_AFTER_FIELDS, errors):
            if "event" in days_after:
                check_choice(days_after["event"], join(days_path, "event"), EVENTS, errors)
            if "days" in days_after and not (is_int(days_after["days"]) and days_after["days"] >= 1):
                invalid(errors, join(days_path, "days"), "must be an integer of at least 1")


def check_expect(expect: object, path: str, errors: list) -> None:
    if not closed_object(expect, path, EXPECT_FIELDS, ("json",), errors):
        return
    if "json" not in expect:
        return
    tests_path = join(path, "json")
    tests = expect["json"]
    if not isinstance(tests, list) or not tests:
        invalid(errors, tests_path, "must be a non-empty list of tests")
        return
    for index, test in enumerate(tests):
        test_path = f"{tests_path}[{index}]"
        if not closed_object(test, test_path, TEST_FIELDS, ("pointer",), errors):
            continue
        pointer = test.get("pointer")
        if "pointer" in test and not (isinstance(pointer, str) and (pointer == "" or pointer.startswith("/"))):
            invalid(errors, join(test_path, "pointer"), 'must be "" or start with "/"')
        if ("equals" in test) == ("min_len" in test):
            invalid(errors, test_path, "needs exactly one of equals and min_len")
        elif "min_len" in test and not (is_int(test["min_len"]) and test["min_len"] >= 0):
            invalid(errors, join(test_path, "min_len"), "must be an integer of at least 0")


def check_host(check: dict, path: str, errors: list) -> None:
    host = check["host"]
    host_path = join(path, "host")
    if isinstance(host, str):
        valid = host == "any" or HOST.match(host) is not None
    elif isinstance(host, list):
        valid = (
            bool(host)
            and all(isinstance(name, str) and HOST.match(name) for name in host)
            and len(set(host)) == len(host)
        )
    else:
        valid = False
    if not valid:
        invalid(errors, host_path, "must be a hostname, 'any', or a non-empty list of distinct hostnames")
        return
    concrete = isinstance(host, str) and host != "any" and HOST.match(host) is not None
    if check.get("effects") in ("paid", "live") and not concrete:
        errors.append(finding(host_path, "host_not_concrete", "a live or paid check must name exactly one host"))


def check_run(run: object, path: str, kind: object, errors: list) -> None:
    if not isinstance(run, dict):
        invalid(errors, path, "must be an object")


def check_reason(check: dict, path: str, errors: list) -> None:
    kind = check.get("kind")
    reason_path = join(path, "reason")
    if kind == "human":
        if check.get("reason") not in REASONS:
            errors.append(finding(reason_path, "reason_required", f"a human check needs a reason, one of {', '.join(REASONS)}"))
    elif kind == "evidence" and "reason" in check:
        errors.append(finding(reason_path, "reason_not_allowed", "an evidence check takes no reason"))


def check_one(check: object, path: str, errors: list) -> None:
    if not closed_object(check, path, CHECK_FIELDS, CHECK_REQUIRED, errors):
        return
    if "ac" in check and not (isinstance(check["ac"], str) and AC.match(check["ac"])):
        invalid(errors, join(path, "ac"), "must match [A-Za-z][A-Za-z0-9_.-]*")
    if "kind" in check:
        check_choice(check["kind"], join(path, "kind"), KINDS, errors)
    if "host" in check:
        check_host(check, path, errors)
    if "when" in check:
        check_when(check["when"], join(path, "when"), errors)
    if "run" in check:
        check_run(check["run"], join(path, "run"), check.get("kind"), errors)
    if "expect" in check:
        check_expect(check["expect"], join(path, "expect"), errors)
    for name, choices in (("effects", EFFECTS), ("mode", MODES), ("on_fail", ON_FAIL), ("on_expire", ON_EXPIRE)):
        if name in check:
            check_choice(check[name], join(path, name), choices, errors)
    if "expires_after_days" in check:
        days = check["expires_after_days"]
        if not (is_int(days) and days >= 1):
            invalid(errors, join(path, "expires_after_days"), "must be an integer of at least 1")
    check_reason(check, path, errors)


def lint_block(block: object) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    if closed_object(block, "", TOP_FIELDS, TOP_REQUIRED, errors):
        if "v" in block and not (is_int(block["v"]) and block["v"] == 1):
            invalid(errors, "v", "must be the integer 1")
        if "merge" in block and not is_sha(block["merge"]):
            invalid(errors, "merge", "must be a 40-character lowercase hex sha")
        if "checks" in block:
            checks = block["checks"]
            if not isinstance(checks, list) or not checks:
                invalid(errors, "checks", "must be a non-empty list of checks")
            else:
                for index, check in enumerate(checks):
                    check_one(check, f"checks[{index}]", errors)
    return {"ok": not errors, "errors": errors, "warnings": warnings}
