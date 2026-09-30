"""Identity-pinned external artifact-budget authority for review operations."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.review_pack import ReviewLimits, canonical_manifest


DESCRIPTION_WIRE_MAX_BYTES = 4096
_LIMIT_KEYS = {"root_max_bytes", "member_max_bytes", "max_members", "aggregate_max_bytes"}
_METRIC_KEYS = {"root_bytes", "total_bytes", "file_count", "largest_member_bytes"}
_VIOLATIONS = ("root_bytes", "member_bytes", "member_count", "aggregate_bytes")


class BudgetError(Exception):
    """The external authority refused or violated its pinned wire contract."""


def _object(raw: bytes, bound: int) -> dict[str, object]:
    if not raw or len(raw) > bound:
        raise BudgetError("budget response exceeds wire bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
        if not isinstance(value, dict) or canonical_manifest(value) != raw:
            raise ValueError("noncanonical object")
        return value
    except (ValueError, UnicodeError) as exc:
        raise BudgetError("invalid budget response") from exc


def _invoke(argv: list[str], *, payload: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["artifact-budget", *argv], input=payload,
                              capture_output=True, check=False)
    except OSError as exc:
        raise BudgetError("budget authority unavailable") from exc


@dataclass(frozen=True)
class BudgetCheck:
    kind: str
    status: str
    metrics: Mapping[str, int]
    violations: tuple[str, ...]


@dataclass(frozen=True)
class BudgetAuthority:
    limits: ReviewLimits
    policy_sha256: str
    report_wire_max_bytes: int
    policy: str | None = None

    def _arguments(self) -> list[str]:
        args = ["--expected-policy-sha256", self.policy_sha256]
        if self.policy is not None:
            args += ["--policy", self.policy]
        return args

    def check(self, kind: str, root: Path) -> BudgetCheck:
        result = _invoke(["check", "--kind", kind, "--root", str(root), "--format", "json",
                          *self._arguments()])
        if result.returncode not in {0, 3} or result.stderr:
            raise BudgetError("budget check failed")
        value = _object(result.stdout, self.report_wire_max_bytes)
        if (set(value) != {"interface_version", "kind", "status", "metrics", "violations"}
                or type(value["interface_version"]) is not int or value["interface_version"] != 1
                or value["kind"] != kind):
            raise BudgetError("invalid budget check")
        metrics, violations = value["metrics"], value["violations"]
        if (not isinstance(metrics, dict) or set(metrics) != _METRIC_KEYS
                or any(type(n) is not int or n < 0 for n in metrics.values())
                or not isinstance(violations, list)
                or violations != [name for name in _VIOLATIONS if name in violations]
                or value["status"] != ("over_budget" if violations else "within_budget")
                or result.returncode != (3 if violations else 0)):
            raise BudgetError("invalid budget check")
        return BudgetCheck(kind, value["status"], metrics, tuple(violations))

    def validate_report(self, raw: bytes, boundary: str) -> bytes:
        value = _object(raw, self.report_wire_max_bytes)
        result = _invoke(["validate-report", "--boundary", boundary, "--input", "-",
                          *self._arguments()], payload=raw)
        if result.returncode != 0 or result.stderr:
            raise BudgetError("report validation failed")
        if _object(result.stdout, self.report_wire_max_bytes) != value:
            raise BudgetError("report validation changed input")
        return result.stdout

    def validate_detail(self, raw: bytes | Path) -> dict[str, object]:
        # File inputs stay at the external no-follow boundary.
        result = _invoke(["validate-detail-input", "--input",
                          str(raw) if isinstance(raw, Path) else "-", *self._arguments()],
                         payload=None if isinstance(raw, Path) else raw)
        if result.returncode != 0 or result.stderr:
            raise BudgetError("detail validation failed")
        value = _object(result.stdout, self.report_wire_max_bytes)
        if not isinstance(raw, Path) and value != _object(raw, self.report_wire_max_bytes):
            raise BudgetError("detail validation changed input")
        return value


def describe(kind: str, *, policy: str | None = None) -> BudgetAuthority:
    argv = ["describe", "--kind", kind, "--format", "json"]
    if policy is not None:
        argv += ["--policy", policy]
    result = _invoke(argv)
    if result.returncode != 0 or result.stderr:
        raise BudgetError("budget description failed")
    value = _object(result.stdout, DESCRIPTION_WIRE_MAX_BYTES)
    if (set(value) != {"schema_version", "kind", "artifact_kind", "limits",
                      "report_wire_max_bytes", "policy_sha256"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["kind"] != "artifact-budget-description" or value["artifact_kind"] != kind):
        raise BudgetError("invalid budget description")
    limits, wire, identity = value["limits"], value["report_wire_max_bytes"], value["policy_sha256"]
    if (not isinstance(limits, dict) or set(limits) != _LIMIT_KEYS
            or any(type(n) is not int or n < 0 for n in limits.values())
            or limits["root_max_bytes"] < 1
            or limits["aggregate_max_bytes"] < limits["root_max_bytes"]
            or type(wire) is not int or wire < 1
            or not isinstance(identity, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None):
        raise BudgetError("invalid budget description")
    return BudgetAuthority(ReviewLimits(**limits), identity, wire, policy)
