#!/usr/bin/env python3
"""Validate and trace the repository-owned pipeline agent model matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


MATRIX_PATH = Path("home/common/agent-skills/model-matrix.json")
AGENTS_PATH = Path("home/common/claude-code/agents")
TOP_LEVEL_FIELDS = {"roles", "dispatch_sites", "scenarios"}
ROLE_FIELDS = {"model", "effort", "eligible", "prohibited"}
DISPATCH_FIELDS = {
    "call",
    "id",
    "path",
    "marker",
    "role",
    "model",
    "effort",
    "requires",
}
EVENT_FIELDS = {"id", "role", "model", "effort", "requires"}
REVIEWER_LITE_REQUIREMENTS = {"named-prior-findings", "bounded-fix-diff"}
EXPECTED_ROLE_TIERS = {
    "issue-owner": ("opus", "high"),
    "ship-owner": ("opus", "high"),
    "implementer": ("opus", "high"),
    "reviewer": ("opus", "high"),
    "reviewer-lite": ("sonnet", "medium"),
    "mechanic": ("sonnet", "medium"),
    "explorer": ("haiku", "medium"),
    "codex-transport": ("sonnet", "medium"),
}
CUSTOM_AGENT_ROLES = {"implementer", "reviewer", "reviewer-lite", "mechanic"}
EXPECTED_SCENARIOS = {"orchestration", "from-issue", "sdd", "shipping"}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _repository_root(root: str | Path | None) -> Path:
    start = Path.cwd() if root is None else Path(root)
    start = start.resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / MATRIX_PATH).is_file():
            return candidate
    raise ValueError(f"repository root containing {MATRIX_PATH} not found from {start}")


def load_matrix(root: str | Path | None = None) -> dict[str, Any]:
    """Load the matrix as strict JSON, rejecting duplicate object keys."""
    repository = _repository_root(root)
    path = repository / MATRIX_PATH
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"cannot load {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    return data


def _frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return {}, [f"{path}: cannot read: {error}"]
    if not lines or lines[0] != "---":
        return {}, [f"{path}: missing opening frontmatter delimiter"]
    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:], 2):
        if line == "---":
            return metadata, errors
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not key:
            errors.append(f"{path}:{line_number}: malformed frontmatter field")
            continue
        if key in metadata:
            errors.append(f"{path}:{line_number}: duplicate frontmatter field {key!r}")
            continue
        metadata[key] = value.strip()
    errors.append(f"{path}: missing closing frontmatter delimiter")
    return metadata, errors


def _safe_manifest_path(root: Path, value: object, label: str) -> tuple[Path | None, list[str]]:
    if not isinstance(value, str) or not value:
        return None, [f"{label}: path must be a non-empty string"]
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None, [f"{label}: path must be repository-relative and may not contain '..'"]
    return root / relative, []


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        return [f"{label}: must be an array of non-empty strings"]
    if len(value) != len(set(value)):
        return [f"{label}: contains duplicate values"]
    return []


def _validate_selection(
    item: dict[str, Any], label: str, roles: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    role = item.get("role")
    if not isinstance(role, str) or role not in roles:
        errors.append(f"{label}: unknown role {role!r}")
        return errors
    role_spec = roles[role]
    if not isinstance(role_spec, dict):
        errors.append(f"{label}: role {role!r} has an invalid specification")
        return errors
    for field in ("model", "effort"):
        value = item.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"{label}: omitted {field}")
        elif value != role_spec.get(field):
            errors.append(
                f"{label}: {field} {value!r} does not match role {role!r} "
                f"({role_spec.get(field)!r})"
            )
    requirements = item.get("requires")
    errors.extend(_string_list(requirements, f"{label}.requires"))
    if role == "reviewer-lite" and isinstance(requirements, list):
        missing = REVIEWER_LITE_REQUIREMENTS - set(requirements)
        if missing:
            errors.append(
                f"{label}: reviewer-lite requires " + ", ".join(sorted(missing))
            )
    return errors


def _matrix_errors(root: Path, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(data) != TOP_LEVEL_FIELDS:
        errors.append(
            "matrix: top-level fields must be exactly "
            + ", ".join(sorted(TOP_LEVEL_FIELDS))
        )

    roles_value = data.get("roles")
    roles = roles_value if isinstance(roles_value, dict) else {}
    if not isinstance(roles_value, dict) or not roles:
        errors.append("matrix.roles: must be a non-empty object")
    if set(roles) != set(EXPECTED_ROLE_TIERS):
        errors.append(
            "matrix.roles: role names must be exactly "
            + ", ".join(sorted(EXPECTED_ROLE_TIERS))
        )
    for role, spec in roles.items():
        label = f"matrix.roles.{role}"
        if not isinstance(role, str) or not role or role.lower() != role:
            errors.append(f"{label}: role name must be lowercase")
        if not isinstance(spec, dict):
            errors.append(f"{label}: must be an object")
            continue
        if set(spec) != ROLE_FIELDS:
            errors.append(
                f"{label}: fields must be exactly " + ", ".join(sorted(ROLE_FIELDS))
            )
        for field in ("model", "effort"):
            value = spec.get(field)
            if not isinstance(value, str) or not value or value.lower() != value:
                errors.append(f"{label}.{field}: must be a non-empty lowercase string")
        if role in EXPECTED_ROLE_TIERS:
            actual_tier = (spec.get("model"), spec.get("effort"))
            if actual_tier != EXPECTED_ROLE_TIERS[role]:
                errors.append(
                    f"{label}: tier {actual_tier!r} must be "
                    f"{EXPECTED_ROLE_TIERS[role]!r}"
                )
        for field in ("eligible", "prohibited"):
            errors.extend(_string_list(spec.get(field), f"{label}.{field}"))

    dispatch_value = data.get("dispatch_sites")
    dispatch_sites = dispatch_value if isinstance(dispatch_value, list) else []
    if not isinstance(dispatch_value, list):
        errors.append("matrix.dispatch_sites: must be an array")
    dispatch_ids: set[str] = set()
    dispatch_calls: set[tuple[str, str]] = set()
    manifested_calls: dict[Path, dict[str, str]] = {}
    for index, site in enumerate(dispatch_sites):
        label = f"matrix.dispatch_sites[{index}]"
        if not isinstance(site, dict):
            errors.append(f"{label}: must be an object")
            continue
        if set(site) != DISPATCH_FIELDS:
            errors.append(
                f"{label}: fields must be exactly "
                + ", ".join(sorted(DISPATCH_FIELDS))
            )
        site_id = site.get("id")
        if not isinstance(site_id, str) or not site_id:
            errors.append(f"{label}.id: must be a non-empty string")
        elif site_id in dispatch_ids:
            errors.append(f"{label}: duplicate id {site_id!r}")
        else:
            dispatch_ids.add(site_id)
        errors.extend(_validate_selection(site, label, roles))
        manifest, path_errors = _safe_manifest_path(root, site.get("path"), label)
        errors.extend(path_errors)
        if manifest is not None:
            if not manifest.is_file():
                errors.append(f"{label}: manifest path does not exist: {site.get('path')}")
            else:
                text = manifest.read_text(encoding="utf-8")
                lines = text.splitlines()
                marker = site.get("marker")
                if not isinstance(marker, str) or not marker:
                    errors.append(f"{label}: marker must be a non-empty string")
                else:
                    count = lines.count(marker)
                    if count != 1:
                        errors.append(
                            f"{label}: marker {marker!r} occurs {count} times in "
                            f"{site.get('path')}; expected exactly 1"
                        )
                call = site.get("call")
                if not isinstance(call, str) or not call or "Agent(" not in call:
                    errors.append(
                        f"{label}: call must be a non-empty literal Agent(...) line"
                    )
                else:
                    call_key = (site["path"], call)
                    if call_key in dispatch_calls:
                        errors.append(
                            f"{label}: duplicate call anchor {call!r} in {site['path']}"
                        )
                    dispatch_calls.add(call_key)
                    count = lines.count(call)
                    if count != 1:
                        errors.append(
                            f"{label}: call {call!r} occurs {count} times in "
                            f"{site.get('path')}; expected exactly 1"
                        )
                    manifested_calls.setdefault(manifest, {})[call] = (
                        marker if isinstance(marker, str) else ""
                    )
                    if (
                        isinstance(marker, str)
                        and lines.count(marker) == 1
                        and count == 1
                        and lines.index(call) != lines.index(marker) + 1
                    ):
                        errors.append(
                            f"{label}: call must be immediately after marker in "
                            f"{site.get('path')}"
                        )

    for manifest, calls in manifested_calls.items():
        for line_number, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "Agent(" in line and line not in calls:
                errors.append(f"{manifest}:{line_number}: unmarked Agent call {line!r}")

    scenarios_value = data.get("scenarios")
    scenarios = scenarios_value if isinstance(scenarios_value, dict) else {}
    if not isinstance(scenarios_value, dict):
        errors.append("matrix.scenarios: must be an object")
    if set(scenarios) != EXPECTED_SCENARIOS:
        errors.append(
            "matrix.scenarios: scenario names must be exactly "
            + ", ".join(sorted(EXPECTED_SCENARIOS))
        )
    event_ids: set[str] = set()
    for scenario, events in scenarios.items():
        label = f"matrix.scenarios.{scenario}"
        if not isinstance(scenario, str) or not scenario:
            errors.append(f"{label}: scenario name must be a non-empty string")
        if not isinstance(events, list):
            errors.append(f"{label}: must be an array")
            continue
        for index, event in enumerate(events):
            event_label = f"{label}[{index}]"
            if not isinstance(event, dict):
                errors.append(f"{event_label}: must be an object")
                continue
            if set(event) != EVENT_FIELDS:
                errors.append(
                    f"{event_label}: fields must be exactly "
                    + ", ".join(sorted(EVENT_FIELDS))
                )
            event_id = event.get("id")
            if not isinstance(event_id, str) or not event_id:
                errors.append(f"{event_label}.id: must be a non-empty string")
            elif event_id in event_ids:
                errors.append(f"{event_label}: duplicate id {event_id!r}")
            else:
                event_ids.add(event_id)
            errors.extend(_validate_selection(event, event_label, roles))
    return errors


def _agent_errors(root: Path, roles: dict[str, Any]) -> list[str]:
    directory = root / AGENTS_PATH
    if not directory.is_dir():
        return [f"{AGENTS_PATH}: agent manifest directory does not exist"]
    errors: list[str] = []
    seen_roles: set[str] = set()
    for path in sorted(directory.glob("*.md")):
        metadata, parse_errors = _frontmatter(path)
        errors.extend(parse_errors)
        role = metadata.get("name")
        if not role:
            errors.append(f"{path}: omitted name")
            continue
        if role not in roles:
            errors.append(f"{path}: unknown role {role!r}")
            continue
        role_spec = roles[role]
        if not isinstance(role_spec, dict):
            errors.append(f"{path}: role {role!r} has an invalid specification")
            continue
        if role in seen_roles:
            errors.append(f"{path}: duplicate agent role {role!r}")
        seen_roles.add(role)
        if path.stem != role:
            errors.append(f"{path}: filename must match agent role {role!r}")
        for field in ("model", "effort"):
            value = metadata.get(field)
            if not value:
                errors.append(f"{path}: omitted {field}")
            elif value != role_spec.get(field):
                errors.append(
                    f"{path}: {field} {value!r} does not match role {role!r} "
                    f"({role_spec.get(field)!r})"
                )
    missing = CUSTOM_AGENT_ROLES - seen_roles
    extra = seen_roles - CUSTOM_AGENT_ROLES
    if missing:
        errors.append("agent manifests: missing roles " + ", ".join(sorted(missing)))
    if extra:
        errors.append("agent manifests: unexpected roles " + ", ".join(sorted(extra)))
    return errors


def validate(root: str | Path | None = None) -> list[str]:
    """Return every matrix, dispatch, and custom-agent contract violation."""
    try:
        repository = _repository_root(root)
        data = load_matrix(repository)
    except ValueError as error:
        return [str(error)]
    errors = _matrix_errors(repository, data)
    roles = data.get("roles")
    errors.extend(_agent_errors(repository, roles if isinstance(roles, dict) else {}))
    return errors


def trace(root: str | Path | None, scenario: str) -> list[dict[str, str]]:
    """Return the scenario's deterministic role/model/effort event trace."""
    repository = _repository_root(root)
    data = load_matrix(repository)
    errors = _matrix_errors(repository, data)
    if errors:
        raise ValueError("invalid model matrix:\n" + "\n".join(errors))
    scenarios = data["scenarios"]
    if scenario not in scenarios:
        raise ValueError(f"unknown scenario {scenario!r}")
    return [
        {field: event[field] for field in ("id", "role", "model", "effort")}
        for event in scenarios[scenario]
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate the matrix")
    validate_parser.add_argument("--root", type=Path)
    trace_parser = subparsers.add_parser("trace", help="emit a scenario as JSONL")
    trace_parser.add_argument("scenario")
    trace_parser.add_argument("--root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        errors = validate(args.root)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("agent model matrix: valid")
        return 0
    try:
        events = trace(args.root, args.scenario)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    for event in events:
        print(json.dumps(event, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
