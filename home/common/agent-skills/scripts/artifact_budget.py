#!/usr/bin/env python3
"""Authoritative artifact budget and phase-report validation (D1/D2/D7/D8/D11/D13-D15)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Mapping, Sequence


KINDS = ("design-spec", "implementation-plan", "handoff", "review-package")
VIOLATIONS = ("root_bytes", "member_bytes", "member_count", "aggregate_bytes")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PLAN_MEMBER_RE = re.compile(r"task-([1-9][0-9]*)\.md\Z")
SHARD_RE = re.compile(r"shard-([0-9]{3})\.(diff|jsonl)\Z")


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

    def to_dict(self) -> dict[str, object]:
        return {
            "interface_version": 1,
            "kind": self.kind,
            "status": self.status,
            "metrics": dict(self.metrics),
            "violations": list(self.violations),
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


def _string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactBudgetError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise ArtifactBudgetError("non-standard JSON constant")


def _decode_json(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates,
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ArtifactBudgetError) as exc:
        raise ArtifactBudgetError("invalid JSON") from exc


def _read_regular(path: Path, *, limit: int | None = None) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise InputReadError("cannot open regular file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InputReadError("not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read() if limit is None else handle.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise ArtifactBudgetError("input exceeds byte limit")
        return raw
    except OSError as exc:
        raise InputReadError("cannot read regular file") from exc
    finally:
        os.close(descriptor)


def _load_policy(path: Path) -> tuple[dict[str, ArtifactLimits], int, int]:
    try:
        value = _decode_json(_read_regular(path))
    except InputReadError as exc:
        raise ArtifactBudgetError("cannot read policy") from exc
    if not _exact_keys(value, {"schema_version", "unit", "artifacts", "phase_reports"}):
        raise ArtifactBudgetError("invalid policy keys")
    assert isinstance(value, dict)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ArtifactBudgetError("invalid policy version")
    if value["unit"] != "bytes":
        raise ArtifactBudgetError("invalid policy unit")
    artifacts = value["artifacts"]
    if not _exact_keys(artifacts, set(KINDS)):
        raise ArtifactBudgetError("invalid artifact kinds")
    assert isinstance(artifacts, dict)
    limits: dict[str, ArtifactLimits] = {}
    entry_keys = {"root_max_bytes", "member_max_bytes", "max_members", "aggregate_max_bytes"}
    for kind in KINDS:
        entry = artifacts[kind]
        if not _exact_keys(entry, entry_keys):
            raise ArtifactBudgetError("invalid artifact policy")
        assert isinstance(entry, dict)
        if not _integer(entry["root_max_bytes"], minimum=1):
            raise ArtifactBudgetError("invalid root limit")
        if not _integer(entry["member_max_bytes"]):
            raise ArtifactBudgetError("invalid member limit")
        if not _integer(entry["max_members"]):
            raise ArtifactBudgetError("invalid member count")
        if not _integer(entry["aggregate_max_bytes"], minimum=1):
            raise ArtifactBudgetError("invalid aggregate limit")
        if entry["aggregate_max_bytes"] < entry["root_max_bytes"]:
            raise ArtifactBudgetError("aggregate below root")
        one_file = kind in {"design-spec", "handoff"}
        if one_file != (entry["member_max_bytes"] == 0 and entry["max_members"] == 0):
            raise ArtifactBudgetError("inconsistent member limits")
        if one_file and entry["aggregate_max_bytes"] != entry["root_max_bytes"]:
            raise ArtifactBudgetError("inconsistent one-file aggregate limit")
        if not one_file and (entry["member_max_bytes"] == 0 or entry["max_members"] == 0):
            raise ArtifactBudgetError("inconsistent package limits")
        limits[kind] = ArtifactLimits(**entry)
    reports = value["phase_reports"]
    if not _exact_keys(reports, {"notes_max_characters", "wire_max_bytes"}):
        raise ArtifactBudgetError("invalid report policy")
    assert isinstance(reports, dict)
    notes = reports["notes_max_characters"]
    wire = reports["wire_max_bytes"]
    if not _integer(notes, minimum=1) or not _integer(wire, minimum=1):
        raise ArtifactBudgetError("invalid report limits")
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


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _nonnegative_fields(value: object, keys: set[str]) -> bool:
    return _exact_keys(value, keys) and all(_integer(value[key]) for key in keys)  # type: ignore[index]


def _validate_finding(value: object) -> None:
    keys = {"axis", "severity", "status", "text", "ruling"}
    if not _exact_keys(value, keys):
        raise ArtifactBudgetError("invalid finding keys")
    assert isinstance(value, dict)
    if value["axis"] not in {"conformance", "correctness", "ship"}:
        raise ArtifactBudgetError("invalid finding axis")
    if value["severity"] not in {"Critical", "Important", "Minor", "Blocking", "Should-fix", "Discussion"}:
        raise ArtifactBudgetError("invalid finding severity")
    if value["status"] not in {"parked", "residual", "discussion", "minor"}:
        raise ArtifactBudgetError("invalid finding status")
    if not _string(value["text"]):
        raise ArtifactBudgetError("invalid finding text")
    ruling = value["ruling"]
    if ruling is not None and not _string(ruling):
        raise ArtifactBudgetError("invalid finding ruling")
    if value["status"] == "parked" and not _string(ruling):
        raise ArtifactBudgetError("parked finding requires ruling")


def validate_detail_input(value: Mapping[str, object]) -> None:
    """Validate the sole D15 non-empty detail-input shape."""
    if not _exact_keys(value, {"interface_version", "findings"}):
        raise ArtifactBudgetError("invalid detail input keys")
    if type(value["interface_version"]) is not int or value["interface_version"] != 1:
        raise ArtifactBudgetError("invalid detail input version")
    findings = value["findings"]
    if not isinstance(findings, list) or not findings:
        raise ArtifactBudgetError("detail findings must be non-empty")
    for finding in findings:
        _validate_finding(finding)


def _validate_ef_designer_side(value: object) -> None:
    keys = {
        "blob_sha", "bytes", "content_sha256", "migration_id", "product_version",
        "entity_types", "properties", "indexes", "foreign_keys", "tables",
    }
    if not _exact_keys(value, keys):
        raise ArtifactBudgetError("invalid generated evidence side")
    assert isinstance(value, dict)
    if not _sha(value["blob_sha"]):
        raise ArtifactBudgetError("invalid generated evidence blob")
    if (not isinstance(value["content_sha256"], str)
            or SHA256_RE.fullmatch(value["content_sha256"]) is None):
        raise ArtifactBudgetError("invalid generated evidence digest")
    if not _string(value["migration_id"]):
        raise ArtifactBudgetError("invalid generated migration id")
    if value["product_version"] is not None and not _string(value["product_version"]):
        raise ArtifactBudgetError("invalid generated product version")
    for key in {"bytes", "entity_types", "properties", "indexes", "foreign_keys", "tables"}:
        if not _integer(value[key]):
            raise ArtifactBudgetError("invalid generated evidence metric")


def _validate_generated_evidence(value: object) -> None:
    if not _exact_keys(value, {"path", "kind", "source_diff_bytes", "base", "head"}):
        raise ArtifactBudgetError("invalid generated evidence")
    assert isinstance(value, dict)
    path = value["path"]
    if (not _string(path) or "\x00" in path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts)
            or str(PurePosixPath(path)) != path):
        raise ArtifactBudgetError("invalid generated evidence path")
    if value["kind"] != "ef-core-migration-designer":
        raise ArtifactBudgetError("invalid generated evidence kind")
    if not _integer(value["source_diff_bytes"], minimum=1):
        raise ArtifactBudgetError("invalid generated source bytes")
    if value["base"] is None and value["head"] is None:
        raise ArtifactBudgetError("generated evidence has no side")
    for side in (value["base"], value["head"]):
        if side is not None:
            _validate_ef_designer_side(side)


def _validate_manifest(root: Path, root_raw: bytes) -> list[CapturedArtifact]:
    manifest = _decode_json(root_raw)
    if not isinstance(manifest, dict):
        raise ArtifactBudgetError("manifest is not an object")
    purpose = manifest.get("purpose")
    version = manifest.get("interface_version")
    if purpose == "diff-review" and version == 1:
        expected_keys = {"interface_version", "kind", "purpose", "range", "commits", "stat",
                         "shards", "total_diff_bytes", "coverage"}
        suffix = "diff"
        total_key = "total_diff_bytes"
    elif purpose == "diff-review" and version == 2:
        expected_keys = {
            "interface_version", "kind", "purpose", "range", "commits", "stat",
            "shards", "source_diff_bytes", "total_review_bytes", "generated_evidence",
            "coverage",
        }
        suffix = "diff"
        total_key = "total_review_bytes"
    elif purpose == "diff-review" and version == 3:
        expected_keys = {
            "interface_version", "kind", "purpose", "range", "commits", "stat",
            "shards", "source_diff_bytes", "total_review_bytes", "generated_evidence",
            "packaging", "coverage",
        }
        suffix = "diff"
        total_key = "total_review_bytes"
    elif purpose == "delivery-detail":
        expected_keys = {"interface_version", "kind", "purpose", "context", "shards",
                         "total_detail_bytes", "coverage"}
        suffix = "jsonl"
        total_key = "total_detail_bytes"
    else:
        raise ArtifactBudgetError("invalid review purpose")
    if not _exact_keys(manifest, expected_keys):
        raise ArtifactBudgetError("invalid manifest keys")
    if type(manifest["interface_version"]) is not int:
        raise ArtifactBudgetError("invalid manifest version")
    if purpose == "delivery-detail" and manifest["interface_version"] != 1:
        raise ArtifactBudgetError("invalid manifest version")
    if manifest["kind"] != "review-package":
        raise ArtifactBudgetError("invalid manifest kind")
    if purpose == "diff-review":
        range_value = manifest["range"]
        if not _exact_keys(range_value, {"base", "head"}) or not _sha(range_value["base"]) or not _sha(range_value["head"]):  # type: ignore[index]
            raise ArtifactBudgetError("invalid diff range")
        commits = manifest["commits"]
        if not isinstance(commits, list):
            raise ArtifactBudgetError("invalid commits")
        for commit in commits:
            if (not _exact_keys(commit, {"sha", "subject"}) or not _sha(commit["sha"])
                    or not isinstance(commit["subject"], str)):  # type: ignore[index]
                raise ArtifactBudgetError("invalid commit")
        if not _nonnegative_fields(manifest["stat"], {"files_changed", "insertions", "deletions"}):
            raise ArtifactBudgetError("invalid stat")
        coverage = manifest["coverage"]
        if version == 1:
            if (not _exact_keys(coverage, {"complete", "file_diff_count"})
                    or coverage["complete"] is not True
                    or not _integer(coverage["file_diff_count"])):  # type: ignore[index]
                raise ArtifactBudgetError("invalid diff coverage")
        else:
            if version == 3:
                packaging = manifest["packaging"]
                if (not _exact_keys(packaging, {"context_lines", "shard_strategy"})
                        or packaging["context_lines"] not in {0, 1, 3, 5, 7}  # type: ignore[index]
                        or type(packaging["context_lines"]) is not int  # type: ignore[index]
                        or packaging["shard_strategy"]  # type: ignore[index]
                        != "stable-first-fit-whole-file"):
                    raise ArtifactBudgetError("invalid adaptive packaging")
            coverage_keys = {
                "complete", "file_diff_count", "byte_complete_file_count",
                "generated_evidence_file_count",
            }
            if (not _exact_keys(coverage, coverage_keys)
                    or coverage["complete"] is not True
                    or any(not _integer(coverage[key]) for key in coverage_keys - {"complete"})):  # type: ignore[index]
                raise ArtifactBudgetError("invalid diff coverage")
            generated = manifest["generated_evidence"]
            if (not isinstance(generated, list)
                    or (version == 2 and not generated)):
                raise ArtifactBudgetError("missing generated evidence")
            for item in generated:
                _validate_generated_evidence(item)
            paths = [item["path"] for item in generated]
            if len(set(paths)) != len(paths):
                raise ArtifactBudgetError("duplicate generated evidence path")
            if coverage["generated_evidence_file_count"] != len(generated):
                raise ArtifactBudgetError("inconsistent generated evidence coverage")
            if (coverage["byte_complete_file_count"] + len(generated)
                    != coverage["file_diff_count"]):
                raise ArtifactBudgetError("inconsistent byte coverage")
            if (not _integer(manifest["source_diff_bytes"])
                    or manifest["source_diff_bytes"]
                    < sum(item["source_diff_bytes"] for item in generated)):
                raise ArtifactBudgetError("invalid source diff bytes")
        if manifest["stat"]["files_changed"] != coverage["file_diff_count"]:  # type: ignore[index]
            raise ArtifactBudgetError("inconsistent diff coverage")
    else:
        context = manifest["context"]
        if (not _exact_keys(context, {"issue", "branch", "producer"})
                or not _integer(context["issue"], minimum=1)  # type: ignore[index]
                or not _string(context["branch"])  # type: ignore[index]
                or context["producer"] not in {"sdd", "ship-review"}):  # type: ignore[index]
            raise ArtifactBudgetError("invalid detail context")
        coverage = manifest["coverage"]
        if (not _exact_keys(coverage, {"complete", "finding_count"})
                or coverage["complete"] is not True or not _integer(coverage["finding_count"], minimum=1)):  # type: ignore[index]
            raise ArtifactBudgetError("invalid detail coverage")
    directory = root.with_suffix(".shards")
    entries = _directory_entries(directory)
    numbered: dict[int, Path] = {}
    for entry in entries:
        match = SHARD_RE.fullmatch(entry.name)
        if match is None or match.group(2) != suffix:
            raise ArtifactBudgetError("unknown review member")
        number = int(match.group(1))
        if number < 1 or number in numbered:
            raise ArtifactBudgetError("invalid review member number")
        numbered[number] = entry
    count = len(numbered)
    if set(numbered) != set(range(1, count + 1)):
        raise ArtifactBudgetError("gapped review members")
    shards = manifest["shards"]
    if not isinstance(shards, list) or len(shards) != count:
        raise ArtifactBudgetError("manifest shards do not match discovery")
    paths = [numbered[number] for number in range(1, count + 1)]
    members = [_capture_artifact(path) for path in paths]
    sizes: list[int] = []
    for number, (entry, member) in enumerate(zip(shards, members), 1):
        if not _exact_keys(entry, {"path", "bytes"}):
            raise ArtifactBudgetError("invalid shard entry")
        expected_path = f"{directory.name}/shard-{number:03d}.{suffix}"
        if entry["path"] != expected_path or not _integer(entry["bytes"]):  # type: ignore[index]
            raise ArtifactBudgetError("invalid shard reference")
        size = member.size
        if entry["bytes"] != size:  # type: ignore[index]
            raise ArtifactBudgetError("stale shard bytes")
        sizes.append(size)
        if suffix == "jsonl":
            raw = member.raw
            lines = raw.splitlines(keepends=True)
            if not lines or any(not line.endswith(b"\n") for line in lines):
                raise ArtifactBudgetError("invalid JSONL shard")
            findings = []
            for line in lines:
                finding = _decode_json(line)
                _validate_finding(finding)
                canonical = _canonical(finding)
                if line != canonical:
                    raise ArtifactBudgetError("non-canonical JSONL finding")
                findings.append(finding)
            if not findings:
                raise ArtifactBudgetError("empty detail shard")
    if not _integer(manifest[total_key]) or manifest[total_key] != sum(sizes):
        raise ArtifactBudgetError("invalid declared total")
    if (purpose == "diff-review" and version in {2, 3}
            and manifest["source_diff_bytes"] < manifest["total_review_bytes"]):
        raise ArtifactBudgetError("invalid review byte reduction")
    if suffix == "jsonl":
        all_findings: list[object] = []
        for member in members:
            all_findings.extend(_decode_json(line) for line in member.raw.splitlines())
        validate_detail_input({"interface_version": 1, "findings": all_findings})
        if manifest["coverage"]["finding_count"] != len(all_findings):  # type: ignore[index]
            raise ArtifactBudgetError("inconsistent detail coverage")
    return members


def check_artifact(kind: str, root: str | os.PathLike[str],
                   policy_path: str | os.PathLike[str] | None = None) -> CheckResult:
    """Validate shape, measure encoded bytes, and classify one artifact root."""
    limits = load_limits(policy_path)
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
    elif kind == "implementation-plan":
        if root_path.suffix != ".md" or not root_path.stem:
            raise ArtifactBudgetError("invalid plan root name")
        members = [_capture_artifact(path) for path in _discover_plan(root_path, root_raw)]
    else:
        if root_path.suffix != ".json" or not root_path.stem:
            raise ArtifactBudgetError("invalid review root name")
        members = _validate_manifest(root_path, root_raw)
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
    violations: list[str] = []
    if metrics["root_bytes"] > policy.root_max_bytes:
        violations.append("root_bytes")
    if member_sizes and max(member_sizes) > policy.member_max_bytes:
        violations.append("member_bytes")
    if len(member_sizes) > policy.max_members:
        violations.append("member_count")
    if metrics["total_bytes"] > policy.aggregate_max_bytes:
        violations.append("aggregate_bytes")
    return CheckResult(kind, "over_budget" if violations else "within_budget", metrics, violations)


def _valid_metrics(value: object) -> bool:
    keys = {"root_bytes", "total_bytes", "file_count", "largest_member_bytes"}
    if not _exact_keys(value, keys) or not all(_integer(value[key]) for key in keys):  # type: ignore[index]
        return False
    return (value["file_count"] >= 1 and value["total_bytes"] >= value["root_bytes"]  # type: ignore[index]
            and (value["file_count"] != 1 or value["largest_member_bytes"] == 0))  # type: ignore[index]


def _valid_path(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "\x00" not in value


def _valid_artifact(value: object, *, kind: str | None = None,
                    over: bool | None = None, root_only: bool = False) -> bool:
    if root_only:
        return (_exact_keys(value, {"kind", "path"}) and value["kind"] in KINDS  # type: ignore[index]
                and _valid_path(value["path"]))  # type: ignore[index]
    expected = {"kind", "path", "metrics", "budget_status"}
    if over is True:
        expected.add("violations")
    if not _exact_keys(value, expected):
        return False
    assert isinstance(value, dict)
    if value["kind"] not in KINDS or (kind is not None and value["kind"] != kind):
        return False
    if not _valid_path(value["path"]) or not _valid_metrics(value["metrics"]):
        return False
    if over is True:
        violations = value["violations"]
        return (value["budget_status"] == "over_budget" and isinstance(violations, list)
                and bool(violations) and violations == [name for name in VIOLATIONS if name in violations]
                and len(set(violations)) == len(violations))
    return value["budget_status"] == "within_budget"


def _notes(value: object, maximum: int) -> bool:
    return isinstance(value, str) and len(value) <= maximum


def validate_producer_report(value: Mapping[str, object], notes_max_characters: int) -> None:
    if not _exact_keys(value, {"state", "artifact", "notes"}) or not _notes(value["notes"], notes_max_characters):
        raise ArtifactBudgetError("invalid producer report")
    state, artifact = value["state"], value["artifact"]
    valid = False
    if state == "complete":
        valid = _valid_artifact(artifact, over=False)
    elif state == "decompose_required":
        valid = any(_valid_artifact(artifact, kind=kind, over=True)
                    for kind in ("design-spec", "implementation-plan", "review-package"))
    elif state == "stopped":
        valid = _valid_artifact(artifact, kind="handoff", over=True)
    elif state == "failed":
        valid = artifact is None or _valid_artifact(artifact, root_only=True)
    if not valid:
        raise ArtifactBudgetError("invalid producer state")


def _relative_path(value: object, *, durable: bool) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        return False
    prefix = (".superpowers", "issue-delivery")
    in_delivery_home = len(path.parts) >= 2 and path.parts[:2] == prefix
    is_durable = len(path.parts) > 2 and in_delivery_home
    is_retained = len(path.parts) > 1 and path.parts[0] == ".superpowers" and not in_delivery_home
    return is_durable if durable else is_retained


def _detail_fields(value: Mapping[str, object], notes_max: int,
                   *, allow_unpublished: bool) -> bool:
    state, path, notes = value["detail_state"], value["report_path"], value["notes"]
    if not _notes(notes, notes_max):
        return False
    if state == "none":
        return path is None
    if state == "present":
        return _relative_path(path, durable=True) and path in notes  # type: ignore[operator]
    if allow_unpublished and state == "unpublished":
        return _relative_path(path, durable=False) and path in notes  # type: ignore[operator]
    return False


def validate_sdd_report(value: Mapping[str, object], notes_max_characters: int) -> None:
    keys = {"state", "review_state", "conformance_verdict", "correctness_verdict",
            "verification_state", "base_sha", "head_sha", "detail_state", "report_path", "notes"}
    if not _exact_keys(value, keys) or not _detail_fields(value, notes_max_characters, allow_unpublished=True):
        raise ArtifactBudgetError("invalid SDD report")
    state, review = value["state"], value["review_state"]
    axes = (value["conformance_verdict"], value["correctness_verdict"])
    verification = value["verification_state"]
    base, head = value["base_sha"], value["head_sha"]
    detail = value["detail_state"]
    valid = False
    if state == "complete" and review == "clean":
        valid = axes == ("clean", "clean") and verification == "passed" and _sha(base) and _sha(head) and detail in {"none", "present"}
    elif state == "residuals" and review == "residuals":
        valid = (all(axis in {"clean", "findings"} for axis in axes) and "findings" in axes
                 and verification in {"passed", "failed"} and _sha(base) and _sha(head) and detail == "present")
    elif state == "failed" and review == "unknown":
        if axes == ("not_run", "not_run") and verification == "not_run" and base is None and head is None:
            valid = detail == "none"
        elif (_sha(base) and _sha(head) and verification in {"passed", "failed"}
              and all(axis in {"not_run", "clean", "findings"} for axis in axes)
              and axes != ("clean", "clean")):
            if detail == "unpublished":
                valid = "findings" in axes
            elif detail == "none":
                valid = all(axis in {"not_run", "clean"} for axis in axes)
            else:
                valid = detail == "present"
    if not valid:
        raise ArtifactBudgetError("invalid SDD state")


def validate_ship_handoff_report(value: Mapping[str, object], notes_max_characters: int) -> None:
    keys = {"state", "ledger_repo_root", "run_id", "attempt", "owner", "owner_worktree",
            "action_id", "issue_number", "branch", "worktree_path", "spec_artifact",
            "plan_artifact", "head_sha", "review_state", "auto", "report_path", "notes"}
    if not _exact_keys(value, keys) or not _notes(value["notes"], notes_max_characters):
        raise ArtifactBudgetError("invalid ship handoff")
    lifecycle = [value[name] for name in
                 ("ledger_repo_root", "run_id", "attempt", "owner", "owner_worktree", "action_id")]
    if not (all(item is None for item in lifecycle)
            or (_string(lifecycle[0]) and _string(lifecycle[1]) and _integer(lifecycle[2], minimum=1)
                and _string(lifecycle[3]) and _string(lifecycle[4]) and _string(lifecycle[5]))):
        raise ArtifactBudgetError("invalid lifecycle identity")
    if (not _integer(value["issue_number"], minimum=1) or not _string(value["branch"])
            or not _string(value["worktree_path"]) or type(value["auto"]) is not bool):
        raise ArtifactBudgetError("invalid ship handoff scalars")
    report = value["report_path"]
    if report is not None and (not _relative_path(report, durable=True) or report not in value["notes"]):  # type: ignore[operator]
        raise ArtifactBudgetError("invalid ship handoff report path")
    state = value["state"]
    both = (_valid_artifact(value["spec_artifact"], kind="design-spec", over=False)
            and _valid_artifact(value["plan_artifact"], kind="implementation-plan", over=False))
    review_detail_valid = value["review_state"] != "residuals" or report is not None
    if state == "complete":
        valid = (both and _sha(value["head_sha"])
                 and value["review_state"] in {"clean", "residuals"} and review_detail_valid)
    elif state == "failed":
        before = (value["spec_artifact"] is None and value["plan_artifact"] is None
                  and value["head_sha"] is None and value["review_state"] == "unknown")
        after = both and _sha(value["head_sha"]) and value["review_state"] in {"unknown", "clean", "residuals"}
        valid = before or (after and review_detail_valid)
    else:
        valid = False
    if not valid:
        raise ArtifactBudgetError("invalid ship handoff state")


def validate_ship_summary_report(value: Mapping[str, object], notes_max_characters: int) -> None:
    keys = {"issue", "state", "pr_url", "merge_sha", "issue_closed", "discussion_items",
            "detail_state", "report_path", "notes"}
    if (not _exact_keys(value, keys) or not _integer(value["issue"], minimum=1)
            or value["discussion_items"] != [] or type(value["issue_closed"]) is not bool
            or not _detail_fields(value, notes_max_characters, allow_unpublished=True)):
        raise ArtifactBudgetError("invalid ship summary")
    pr = value["pr_url"]
    if pr is not None and not _string(pr):
        raise ArtifactBudgetError("invalid PR URL")
    state = value["state"]
    if state == "merged":
        valid = _string(pr) and _sha(value["merge_sha"]) and value["issue_closed"] is True and value["detail_state"] in {"none", "present"}
    elif state in {"stopped", "failed"}:
        valid = value["merge_sha"] is None and value["issue_closed"] is False
    else:
        valid = False
    if not valid:
        raise ArtifactBudgetError("invalid ship summary state")


def _canonical(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ArtifactBudgetError("invalid Unicode string") from exc


def _input_bytes(path: str, wire_max: int) -> bytes:
    if path == "-":
        raw = sys.stdin.buffer.read(wire_max + 1)
        if len(raw) > wire_max:
            raise ArtifactBudgetError("input exceeds wire bound")
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
    report.add_argument("--boundary", choices=("producer", "sdd", "ship-handoff", "ship-summary"), required=True)
    report.add_argument("--input", required=True)
    report.add_argument("--policy")
    detail = subparsers.add_parser("validate-detail-input")
    detail.add_argument("--input", required=True)
    detail.add_argument("--policy")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "check":
            result = check_artifact(args.kind, args.root, args.policy)
            sys.stdout.buffer.write(_canonical(result.to_dict()))
            return 0 if result.status == "within_budget" else 3
        try:
            _, notes_max, wire_max = _load_policy(_policy_path(args.policy))
        except ArtifactBudgetError:
            label = "report" if args.command == "validate-report" else "detail input"
            sys.stderr.write(f"artifact-budget: invalid {label}\n")
            return 2
        try:
            raw = _input_bytes(args.input, wire_max)
        except InputReadError:
            label = "report" if args.command == "validate-report" else "detail input"
            sys.stderr.write(f"artifact-budget: cannot read {label}\n")
            return 2
        except ArtifactBudgetError:
            label = "report" if args.command == "validate-report" else "detail input"
            sys.stderr.write(f"artifact-budget: invalid {label}\n")
            return 2
        try:
            value = _decode_json(raw)
            if not isinstance(value, dict):
                raise ArtifactBudgetError("JSON root is not an object")
            if args.command == "validate-detail-input":
                validate_detail_input(value)
            else:
                validators = {"producer": validate_producer_report, "sdd": validate_sdd_report,
                              "ship-handoff": validate_ship_handoff_report,
                              "ship-summary": validate_ship_summary_report}
                validators[args.boundary](value, notes_max)
            output = _canonical(value)
            if len(output) > wire_max:
                raise ArtifactBudgetError("canonical wire object exceeds bound")
        except ArtifactBudgetError:
            label = "report" if args.command == "validate-report" else "detail input"
            sys.stderr.write(f"artifact-budget: invalid {label}\n")
            return 2
        sys.stdout.buffer.write(output)
        return 0
    except ArtifactBudgetError as exc:
        sys.stderr.write(f"artifact-budget: invalid input: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
