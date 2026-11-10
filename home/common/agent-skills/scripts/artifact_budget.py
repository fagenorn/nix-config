#!/usr/bin/env python3
"""Artifact budget and producer-report validation for the skills that call it.

The design, grill-with-docs, writing-plans and handoff skills are the callers. The
surface is `check` (measure a design-spec, an implementation-plan or a handoff
against the policy; exit 0 within budget, 3 over budget) and `validate-report
--boundary producer` (a phase report holding exactly `state`, `artifact` and
`notes`). Standard library only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable, Mapping, Sequence


KINDS = ("design-spec", "implementation-plan", "handoff")
# One row per violation code: the code, the limit it is measured against and the
# measured quantity. `violations` and `overages` both derive from it (issue 472 D6).
_BOUNDS: tuple[tuple[str, str, Callable[[Mapping[str, int]], int]], ...] = (
    ("root_bytes", "root_max_bytes", lambda metrics: metrics["root_bytes"]),
    ("member_bytes", "member_max_bytes", lambda metrics: metrics["largest_member_bytes"]),
    ("member_count", "max_members", lambda metrics: metrics["file_count"] - 1),
    ("aggregate_bytes", "aggregate_max_bytes", lambda metrics: metrics["total_bytes"]),
)
VIOLATIONS = tuple(code for code, _, _ in _BOUNDS)
PLAN_MEMBER_RE = re.compile(r"task-([1-9][0-9]*)\.md\Z")


class ArtifactBudgetError(Exception):
    """Expected policy, schema, package, invocation, or input error."""


class InputReadError(ArtifactBudgetError):
    """No-follow input could not be read."""


@dataclass(frozen=True)
class ArtifactLimits:
    root_max_bytes: int
    member_max_bytes: int
    max_members: int
    aggregate_max_bytes: int


@dataclass(frozen=True)
class CheckResult:
    kind: str
    status: str
    metrics: Mapping[str, int]
    violations: Sequence[str]
    overages: Mapping[str, Mapping[str, int]]

    def to_dict(self) -> dict[str, object]:
        return {
            "interface_version": 1,
            "kind": self.kind,
            "status": self.status,
            "metrics": dict(self.metrics),
            "violations": list(self.violations),
            "overages": {code: dict(entry) for code, entry in self.overages.items()},
        }


@dataclass(frozen=True)
class CapturedArtifact:
    path: Path
    raw: bytes
    device: int
    inode: int
    signature: tuple[int, int, int, int, int, int]

    @property
    def size(self) -> int:
        return len(self.raw)


def _exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _integer(value: object, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactBudgetError(f"duplicate key {json.dumps(key)}")
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise ArtifactBudgetError("non-standard constant")


def _decode_json(raw: bytes, subject: str = "JSON") -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates,
                          parse_constant=_reject_constant)
    except UnicodeDecodeError as exc:
        raise ArtifactBudgetError(
            f"invalid {subject}: invalid UTF-8 at byte {exc.start}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactBudgetError(
            f"invalid {subject}: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    except ArtifactBudgetError as exc:
        raise ArtifactBudgetError(f"invalid {subject}: {exc}") from exc


def _os_reason(exc: Exception) -> str:
    """The OS error string of a failed open or read, never the path it names (issue 472 D2)."""
    return getattr(exc, "strerror", None) or "path cannot be opened"


def _read_regular(path: Path, *, limit: int | None = None) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise InputReadError(_os_reason(exc)) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InputReadError("not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read() if limit is None else handle.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise ArtifactBudgetError(f"input exceeds the {limit}-byte wire bound")
        return raw
    except OSError as exc:
        raise InputReadError(_os_reason(exc)) from exc
    finally:
        os.close(descriptor)


def _load_policy(path: Path) -> tuple[dict[str, ArtifactLimits], int, int]:
    try:
        raw = _read_regular(path)
    except InputReadError as exc:
        raise ArtifactBudgetError(f"cannot read policy: {exc}") from exc
    return _parse_policy(raw)


def _parse_policy(raw: bytes) -> tuple[dict[str, ArtifactLimits], int, int]:
    value = _decode_json(raw, "policy JSON")
    if not _exact_keys(value, {"schema_version", "unit", "artifacts", "phase_reports"}):
        raise ArtifactBudgetError("invalid policy keys")
    assert isinstance(value, dict)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ArtifactBudgetError("invalid policy version")
    if value["unit"] != "bytes":
        raise ArtifactBudgetError("invalid policy unit")
    artifacts = value["artifacts"]
    if not _exact_keys(artifacts, set(KINDS)):
        raise ArtifactBudgetError("invalid policy artifact kinds")
    assert isinstance(artifacts, dict)
    limits: dict[str, ArtifactLimits] = {}
    entry_keys = {"root_max_bytes", "member_max_bytes", "max_members", "aggregate_max_bytes"}
    for kind in KINDS:
        entry = artifacts[kind]
        if not _exact_keys(entry, entry_keys):
            raise ArtifactBudgetError("invalid artifact policy")
        assert isinstance(entry, dict)
        if not _integer(entry["root_max_bytes"], minimum=1):
            raise ArtifactBudgetError("invalid policy root limit")
        if not _integer(entry["member_max_bytes"]):
            raise ArtifactBudgetError("invalid policy member limit")
        if not _integer(entry["max_members"]):
            raise ArtifactBudgetError("invalid policy member count")
        if not _integer(entry["aggregate_max_bytes"], minimum=1):
            raise ArtifactBudgetError("invalid policy aggregate limit")
        if entry["aggregate_max_bytes"] < entry["root_max_bytes"]:
            raise ArtifactBudgetError("policy aggregate below root")
        one_file = kind in {"design-spec", "handoff"}
        if one_file != (entry["member_max_bytes"] == 0 and entry["max_members"] == 0):
            raise ArtifactBudgetError("inconsistent policy member limits")
        if one_file and entry["aggregate_max_bytes"] != entry["root_max_bytes"]:
            raise ArtifactBudgetError("inconsistent policy one-file aggregate limit")
        if not one_file and (entry["member_max_bytes"] == 0 or entry["max_members"] == 0):
            raise ArtifactBudgetError("inconsistent policy package limits")
        limits[kind] = ArtifactLimits(**entry)
    reports = value["phase_reports"]
    if not _exact_keys(reports, {"notes_max_characters", "wire_max_bytes"}):
        raise ArtifactBudgetError("invalid report policy")
    assert isinstance(reports, dict)
    notes = reports["notes_max_characters"]
    wire = reports["wire_max_bytes"]
    if not _integer(notes, minimum=1) or not _integer(wire, minimum=1):
        raise ArtifactBudgetError("invalid policy report limits")
    return limits, notes, wire


def _default_policy_path() -> Path:
    return Path.home() / ".agents/share/artifact-budget-policy.json"


def _policy_path(policy_path: str | os.PathLike[str] | None) -> Path:
    if policy_path is not None:
        return Path(policy_path)
    try:
        return _default_policy_path().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArtifactBudgetError("cannot resolve installed policy") from exc


def load_limits(policy_path: str | os.PathLike[str] | None = None) -> dict[str, ArtifactLimits]:
    """Load and strictly validate the shared policy's artifact limits."""
    return _load_policy(_policy_path(policy_path))[0]


def _directory_entries(path: Path) -> list[Path]:
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ArtifactBudgetError("member path is not a real directory")
        return [path / name for name in os.listdir(path)]
    except (OSError, ValueError) as exc:
        raise ArtifactBudgetError("cannot inspect member directory") from exc


def _stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _capture_artifact(path: Path) -> CapturedArtifact:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise ArtifactBudgetError("artifact is unreadable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactBudgetError("artifact is not a non-symlink regular file")
        if not os.access(path, os.R_OK, follow_symlinks=False):
            raise ArtifactBudgetError("artifact is unreadable")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read()
        after = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ArtifactBudgetError("artifact changed during read") from exc
        if (_stat_signature(before) != _stat_signature(after)
                or _stat_signature(after) != _stat_signature(current)
                or len(raw) != after.st_size):
            raise ArtifactBudgetError("artifact changed during read")
        return CapturedArtifact(path, raw, after.st_dev, after.st_ino,
                                _stat_signature(after))
    except OSError as exc:
        raise ArtifactBudgetError("artifact is unreadable") from exc
    finally:
        os.close(descriptor)


def _assert_artifact_current(artifact: CapturedArtifact) -> None:
    try:
        current = artifact.path.lstat()
    except OSError as exc:
        raise ArtifactBudgetError("artifact changed after read") from exc
    if _stat_signature(current) != artifact.signature:
        raise ArtifactBudgetError("artifact changed after read")


def _discover_plan(root: Path, root_raw: bytes) -> list[Path]:
    directory = root.with_suffix(".tasks")
    entries = _directory_entries(directory)
    numbered: dict[int, Path] = {}
    for entry in entries:
        match = PLAN_MEMBER_RE.fullmatch(entry.name)
        if match is None:
            raise ArtifactBudgetError("unknown plan member")
        number = int(match.group(1))
        if number in numbered:
            raise ArtifactBudgetError("duplicate plan member number")
        numbered[number] = entry
    count = len(numbered)
    if set(numbered) != set(range(1, count + 1)):
        raise ArtifactBudgetError("gapped plan members")
    try:
        text = root_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ArtifactBudgetError("malformed UTF-8 plan") from exc
    if text.splitlines().count("## Task index") != 1:
        raise ArtifactBudgetError("plan must contain exactly one task index")
    if count == 0:
        raise ArtifactBudgetError("plan must contain at least one task member")
    expected = [f"{directory.name}/task-{number}.md" for number in range(1, count + 1)]
    references: list[str] = []
    row_re = re.compile(
        r"^Task ([1-9][0-9]*)\s+—\s+.+\s+—\s+.+\s+—\s+.+\s+—\s+"
        r"\[task-([1-9][0-9]*)\.md\]\(([^)]+)\)\s*$"
    )
    in_index = False
    for line in text.splitlines():
        if line == "## Task index":
            in_index = True
            continue
        if in_index and line.startswith("## "):
            break
        if in_index and line.startswith("Task "):
            match = row_re.fullmatch(line)
            if match is None or match.group(1) != match.group(2):
                raise ArtifactBudgetError("invalid task index row")
            references.append(match.group(3))
    if references != expected:
        raise ArtifactBudgetError("plan references do not match discovered members")
    return [numbered[number] for number in range(1, count + 1)]


def _quoted(names: set[str]) -> str:
    return ", ".join(json.dumps(name) for name in sorted(names))


def _members_fault(value: object, keys: set[str], subject: str) -> str | None:
    """Why `value` is not an object with exactly `keys`, or None (issue 472 D2, D3)."""
    if not isinstance(value, dict):
        return f"{subject} must be a JSON object"
    missing, unexpected = keys - set(value), set(value) - keys
    parts = ([f"missing {_quoted(missing)}"] if missing else []) + (
        [f"unexpected {_quoted(unexpected)}"] if unexpected else [])
    return f"{subject} members: {'; '.join(parts)}" if parts else None


def _require_members(value: object, keys: set[str], subject: str) -> None:
    fault = _members_fault(value, keys, subject)
    if fault is not None:
        raise ArtifactBudgetError(fault)


def _require_notes(value: object, maximum: int) -> None:
    """Refuse notes that are not a string of at most `maximum` characters (issue 472 D3)."""
    if not isinstance(value, str):
        raise ArtifactBudgetError("notes must be a string")
    if len(value) > maximum:
        raise ArtifactBudgetError(f"notes has {len(value)} characters; the bound is {maximum}")


def check_artifact(kind: str, root: str | os.PathLike[str],
                   policy_path: str | os.PathLike[str] | None = None) -> CheckResult:
    """Validate shape, measure encoded bytes, and classify one artifact root."""
    limits = load_limits(policy_path)
    return _check_artifact(kind, root, limits)


def _check_artifact(kind: str, root: str | os.PathLike[str],
                    limits: Mapping[str, ArtifactLimits]) -> CheckResult:
    if kind not in limits:
        raise ArtifactBudgetError("unknown artifact kind")
    root_path = Path(root)
    root_artifact = _capture_artifact(root_path)
    root_raw = root_artifact.raw
    members: list[CapturedArtifact]
    if kind in {"design-spec", "handoff"}:
        try:
            root_raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ArtifactBudgetError("malformed UTF-8 root") from exc
        members = []
    else:
        if root_path.suffix != ".md" or not root_path.stem:
            raise ArtifactBudgetError("invalid plan root name")
        members = [_capture_artifact(path) for path in _discover_plan(root_path, root_raw)]
    identities = {(root_artifact.device, root_artifact.inode)}
    member_sizes: list[int] = []
    for member in members:
        identity = (member.device, member.inode)
        if identity in identities:
            raise ArtifactBudgetError("duplicate resolved member identity")
        identities.add(identity)
        member_sizes.append(member.size)
    for artifact in [root_artifact, *members]:
        _assert_artifact_current(artifact)
    metrics = {
        "root_bytes": root_artifact.size,
        "total_bytes": root_artifact.size + sum(member_sizes),
        "file_count": 1 + len(member_sizes),
        "largest_member_bytes": max(member_sizes, default=0),
    }
    policy = limits[kind]
    overages: dict[str, dict[str, int]] = {}
    for code, limit_name, measure in _BOUNDS:
        limit = getattr(policy, limit_name)
        measured = measure(metrics)
        if measured > limit:
            overages[code] = {"limit": limit, "over_by": measured - limit}
    violations = list(overages)
    return CheckResult(kind, "over_budget" if violations else "within_budget", metrics,
                       violations, overages)


def _valid_metrics(value: object) -> bool:
    keys = {"root_bytes", "total_bytes", "file_count", "largest_member_bytes"}
    if not _exact_keys(value, keys) or not all(_integer(value[key]) for key in keys):  # type: ignore[index]
        return False
    return (value["file_count"] >= 1 and value["total_bytes"] >= value["root_bytes"]  # type: ignore[index]
            and (value["file_count"] != 1 or value["largest_member_bytes"] == 0))  # type: ignore[index]


def _valid_path(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "\x00" not in value


def _artifact_fault(value: object, *, kinds: Sequence[str], over: bool,
                    root_only: bool = False) -> str | None:
    """Why `value` is not an artifact of one of `kinds`, or None (issue 472 D3).

    `over` selects the over-budget shape, `root_only` the root-only shape of a
    failed producer report.
    """
    expected = {"kind", "path"} if root_only else {"kind", "path", "metrics", "budget_status"}
    if over and not root_only:
        expected.add("violations")
    fault = _members_fault(value, expected, "artifact")
    if fault is not None:
        return fault
    assert isinstance(value, dict)
    if not (isinstance(value["kind"], str) and value["kind"] in tuple(kinds)):
        return f"artifact.kind must be {' or '.join(kinds)}"
    if not _valid_path(value["path"]):
        return "artifact.path must be a non-empty string without NUL"
    if root_only:
        return None
    if not _valid_metrics(value["metrics"]):
        return "artifact.metrics must be four non-negative integer counts of one measurement"
    status = "over_budget" if over else "within_budget"
    if value["budget_status"] != status:
        return f"artifact.budget_status must be {status}"
    if over:
        violations = value["violations"]
        if not (isinstance(violations, list) and bool(violations)
                and violations == [name for name in VIOLATIONS if name in violations]
                and len(set(violations)) == len(violations)):
            return "artifact.violations must be distinct violation codes in checker order"
    return None


# Each producer state's allowed artifact kinds and budget side; `failed` takes a
# root-only artifact or null (issue 472 D3).
_PRODUCER_ARTIFACTS = {
    "complete": (KINDS, False),
    "decompose_required": (("design-spec", "implementation-plan"), True),
    "stopped": (("handoff",), True),
}


def validate_producer_report(value: Mapping[str, object], notes_max_characters: int) -> None:
    _require_members(value, {"state", "artifact", "notes"}, "producer report")
    _require_notes(value["notes"], notes_max_characters)
    state, artifact = value["state"], value["artifact"]
    if state == "failed":
        fault = None if artifact is None else _artifact_fault(
            artifact, kinds=KINDS, over=False, root_only=True)
    elif isinstance(state, str) and state in _PRODUCER_ARTIFACTS:
        kinds, over = _PRODUCER_ARTIFACTS[state]
        fault = _artifact_fault(artifact, kinds=kinds, over=over)
    else:
        raise ArtifactBudgetError("state must be complete, decompose_required, stopped or failed")
    if fault is not None:
        raise ArtifactBudgetError(f"{fault} for state {state}")


def _canonical(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ArtifactBudgetError("invalid Unicode string") from exc


def _input_bytes(path: str, wire_max: int, read_stdin: Callable[[int], bytes]) -> bytes:
    if path == "-":
        raw = read_stdin(wire_max + 1)
        if len(raw) > wire_max:
            raise ArtifactBudgetError(f"input exceeds the {wire_max}-byte wire bound")
        return raw
    return _read_regular(Path(path), limit=wire_max)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ArtifactBudgetError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="artifact-budget", add_help=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--kind", choices=KINDS, required=True)
    check.add_argument("--root", required=True)
    check.add_argument("--policy")
    check.add_argument("--format", choices=("json",), required=True)
    report = subparsers.add_parser("validate-report")
    report.add_argument("--boundary", choices=("producer",), required=True)
    report.add_argument("--input", required=True)
    report.add_argument("--policy")
    return parser


@dataclass(frozen=True)
class Outcome:
    """What one artifact-budget run produces: its exit code, its stdout bytes and
    its stderr text (issue 498 D3)."""

    exit_code: int
    stdout: bytes
    stderr: str


def _refuse(label: str, exc: BaseException) -> Outcome:
    """The one refusal: exit 2, no stdout, and the stderr line
    `artifact-budget: <label>: <reason>`.

    The reason is the error's message with each whitespace run collapsed to one
    space, or the error's class name when the message is empty (issue 472 D1, D2).
    """
    reason = " ".join(str(exc).split()) or type(exc).__name__
    return Outcome(2, b"", f"artifact-budget: {label}: {reason}\n")


def invoke(argv: Sequence[str], read_stdin: Callable[[int], bytes]) -> Outcome:
    """Run one artifact-budget command and return its outcome instead of writing
    it (issue 498 D3).

    `argv` excludes the program name. `read_stdin(size)` is called once, and only
    for `--input -`. Nothing is written to a process stream and nothing exits,
    except argparse's own `-h`/`--help`. Only an `ArtifactBudgetError` becomes a
    refusal; any other exception propagates.
    """
    try:
        args = _parser().parse_args(argv)
        try:
            limits, notes_max, wire_max = _load_policy(_policy_path(args.policy))
        except ArtifactBudgetError as exc:
            if args.command == "check":
                raise
            return _refuse("invalid report", exc)
        if args.command == "check":
            result = _check_artifact(args.kind, args.root, limits)
            return Outcome(0 if result.status == "within_budget" else 3,
                           _canonical(result.to_dict()), "")
        try:
            raw = _input_bytes(args.input, wire_max, read_stdin)
        except InputReadError as exc:
            return _refuse("cannot read report", exc)
        except ArtifactBudgetError as exc:
            return _refuse("invalid report", exc)
        try:
            value = _decode_json(raw)
            if not isinstance(value, dict):
                raise ArtifactBudgetError("JSON root is not an object")
            validate_producer_report(value, notes_max)
            output = _canonical(value)
            if len(output) > wire_max:
                raise ArtifactBudgetError(f"canonical output exceeds the {wire_max}-byte wire bound")
        except ArtifactBudgetError as exc:
            return _refuse("invalid report", exc)
        return Outcome(0, output, "")
    except ArtifactBudgetError as exc:
        return _refuse("invalid input", exc)


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI: `invoke` over this process's arguments and binary stdin, with the
    outcome written to stdout and stderr."""
    outcome = invoke(sys.argv[1:] if argv is None else argv,
                     lambda size: sys.stdin.buffer.read(size))
    sys.stdout.buffer.write(outcome.stdout)
    sys.stderr.write(outcome.stderr)
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
