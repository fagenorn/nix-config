#!/usr/bin/env python3
"""Validate current bridge and research evidence artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence


BRIDGE_KIND = "bridge-smoke"
RESEARCH_KIND = "research-observations"
REQUIRED_OPERATIONS = frozenset({"plan-review", "diff-review"})
SUCCESS_STATUSES = frozenset({"completed", "succeeded"})
FAILURE_STATUSES = frozenset({"failed", "cancelled", "timed_out"})
TERMINAL_STATUSES = SUCCESS_STATUSES | FAILURE_STATUSES


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str


def _add(
    diagnostics: list[Diagnostic], code: str, path: str, message: str
) -> None:
    diagnostics.append(Diagnostic(code, path, message))


def _mapping(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _add(diagnostics, "FIELD_TYPE", path, "expected an object")
        return None
    return value


def _list(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> list[Any] | None:
    if not isinstance(value, list):
        _add(diagnostics, "FIELD_TYPE", path, "expected an array")
        return None
    return value


def _required_mapping(
    parent: dict[str, Any], key: str, path: str, diagnostics: list[Diagnostic]
) -> dict[str, Any] | None:
    field_path = f"{path}.{key}"
    if key not in parent:
        _add(diagnostics, "FIELD_REQUIRED", field_path, "field is required")
        return None
    return _mapping(parent[key], field_path, diagnostics)


def _required_list(
    parent: dict[str, Any], key: str, path: str, diagnostics: list[Diagnostic]
) -> list[Any] | None:
    field_path = f"{path}.{key}"
    if key not in parent:
        _add(diagnostics, "FIELD_REQUIRED", field_path, "field is required")
        return None
    return _list(parent[key], field_path, diagnostics)


def _nonempty_string(
    parent: dict[str, Any], key: str, path: str, diagnostics: list[Diagnostic]
) -> str | None:
    field_path = f"{path}.{key}"
    if key not in parent:
        _add(diagnostics, "FIELD_REQUIRED", field_path, "field is required")
        return None
    value = parent[key]
    if not isinstance(value, str):
        _add(diagnostics, "FIELD_TYPE", field_path, "expected a string")
        return None
    if not value.strip():
        _add(diagnostics, "FIELD_VALUE_INVALID", field_path, "must not be empty")
        return None
    return value


def _parse_timestamp_value(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> datetime | None:
    if not isinstance(value, str):
        _add(diagnostics, "FIELD_TYPE", path, "expected a timestamp string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _add(
            diagnostics,
            "TIMESTAMP_INVALID",
            path,
            "expected an ISO 8601 timestamp",
        )
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _add(
            diagnostics,
            "TIMESTAMP_TIMEZONE_REQUIRED",
            path,
            "timestamp must include a UTC offset",
        )
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        _add(
            diagnostics,
            "TIMESTAMP_INVALID",
            path,
            "timestamp is outside the supported UTC range",
        )
        return None


def _timestamp(
    parent: dict[str, Any], key: str, path: str, diagnostics: list[Diagnostic]
) -> datetime | None:
    field_path = f"{path}.{key}"
    if key not in parent:
        _add(diagnostics, "FIELD_REQUIRED", field_path, "field is required")
        return None
    return _parse_timestamp_value(parent[key], field_path, diagnostics)


def _validate_common(
    document: object, expected_kind: str, diagnostics: list[Diagnostic]
) -> tuple[dict[str, Any] | None, str | None]:
    root = _mapping(document, "$", diagnostics)
    if root is None:
        return None, None

    if "schema_version" not in root:
        _add(
            diagnostics,
            "FIELD_REQUIRED",
            "$.schema_version",
            "field is required",
        )
    elif type(root["schema_version"]) is not int:
        _add(
            diagnostics,
            "FIELD_TYPE",
            "$.schema_version",
            "expected an integer",
        )
    elif root["schema_version"] != 1:
        _add(
            diagnostics,
            "SCHEMA_VERSION_UNSUPPORTED",
            "$.schema_version",
            "only schema version 1 is supported",
        )

    kind = root.get("kind")
    if "kind" not in root:
        _add(diagnostics, "FIELD_REQUIRED", "$.kind", "field is required")
    elif not isinstance(kind, str):
        _add(diagnostics, "FIELD_TYPE", "$.kind", "expected a string")
    elif kind != expected_kind:
        _add(
            diagnostics,
            "KIND_MISMATCH",
            "$.kind",
            f"expected {expected_kind!r}",
        )

    evidence_id = _nonempty_string(root, "evidence_id", "$", diagnostics)
    _timestamp(root, "captured_at", "$", diagnostics)
    return root, evidence_id


def _validate_bridge_record(
    value: object,
    path: str,
    diagnostics: list[Diagnostic],
    *,
    mediated: bool,
) -> bool | None:
    record = _mapping(value, path, diagnostics)
    if record is None:
        return None

    _nonempty_string(record, "execution_id", path, diagnostics)
    _timestamp(record, "observed_at", path, diagnostics)
    status = _nonempty_string(record, "status", path, diagnostics)
    if status is None:
        return None
    if status not in TERMINAL_STATUSES:
        _add(
            diagnostics,
            "BRIDGE_RECORD_NONTERMINAL",
            f"{path}.status",
            "status must be a terminal outcome",
        )
        return None

    successful = status in SUCCESS_STATUSES
    payload_key = "result" if successful else "failure"
    opposite_key = "failure" if successful else "result"
    payload = _nonempty_string(record, payload_key, path, diagnostics)
    if payload is None:
        _add(
            diagnostics,
            "BRIDGE_RECORD_PAYLOAD_REQUIRED",
            f"{path}.{payload_key}",
            f"terminal status {status!r} requires a non-empty {payload_key}",
        )
    if opposite_key in record:
        _add(
            diagnostics,
            "BRIDGE_RECORD_PAYLOAD_MISMATCH",
            f"{path}.{opposite_key}",
            f"terminal status {status!r} must not carry {opposite_key}",
        )

    if mediated and successful:
        job_id = _nonempty_string(record, "job_id", path, diagnostics)
        if job_id is None:
            _add(
                diagnostics,
                "BRIDGE_JOB_ID_REQUIRED",
                f"{path}.job_id",
                "successful mediated records require a job ID",
            )

    if payload is None or opposite_key in record:
        return None
    return successful


def validate_bridge(document: object) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    root, _ = _validate_common(document, BRIDGE_KIND, diagnostics)
    if root is None:
        return sorted(diagnostics)

    deployment = _required_mapping(root, "deployment", "$", diagnostics)
    deployment_times: list[datetime] = []
    if deployment is not None:
        for component in ("skill", "agent", "plugin"):
            component_path = f"$.deployment.{component}"
            deployed = _required_mapping(
                deployment, component, "$.deployment", diagnostics
            )
            if deployed is None:
                continue
            _nonempty_string(deployed, "revision", component_path, diagnostics)
            instant = _timestamp(
                deployed, "deployed_at", component_path, diagnostics
            )
            if instant is not None:
                deployment_times.append(instant)

    session_time: datetime | None = None
    session = _required_mapping(root, "session", "$", diagnostics)
    if session is not None:
        _nonempty_string(session, "id", "$.session", diagnostics)
        session_time = _timestamp(
            session, "started_at", "$.session", diagnostics
        )

    if len(deployment_times) == 3 and session_time is not None:
        if session_time < max(deployment_times):
            _add(
                diagnostics,
                "BRIDGE_SESSION_STALE",
                "$.session.started_at",
                "session started before all deployed bridge components",
            )

    claim_status: str | None = None
    claim = _required_mapping(root, "claim", "$", diagnostics)
    if claim is not None:
        claim_status = _nonempty_string(claim, "status", "$.claim", diagnostics)
        if claim_status is not None and claim_status not in {"certified", "rejected"}:
            _add(
                diagnostics,
                "BRIDGE_CLAIM_STATUS_INVALID",
                "$.claim.status",
                "status must be 'certified' or 'rejected'",
            )
            claim_status = None

    operations = _required_list(root, "operations", "$", diagnostics)
    named_operations: dict[str, tuple[int, dict[str, Any]]] = {}
    mediated_outcomes: dict[str, bool | None] = {}
    if operations is not None:
        for index, value in enumerate(operations):
            operation_path = f"$.operations[{index}]"
            operation = _mapping(value, operation_path, diagnostics)
            if operation is None:
                continue
            name = _nonempty_string(operation, "name", operation_path, diagnostics)
            if name is not None:
                if name not in REQUIRED_OPERATIONS:
                    _add(
                        diagnostics,
                        "BRIDGE_OPERATION_UNKNOWN",
                        f"{operation_path}.name",
                        f"unknown bridge operation {name!r}",
                    )
                elif name in named_operations:
                    _add(
                        diagnostics,
                        "BRIDGE_OPERATION_DUPLICATE",
                        f"{operation_path}.name",
                        f"operation {name!r} appears more than once",
                    )
                else:
                    named_operations[name] = (index, operation)

            layer_outcomes: dict[str, bool | None] = {}
            for layer in ("direct", "agent_mediated"):
                layer_path = f"{operation_path}.{layer}"
                if layer not in operation:
                    _add(
                        diagnostics,
                        "BRIDGE_LAYER_REQUIRED",
                        layer_path,
                        f"operation requires exactly one {layer} record",
                    )
                    layer_outcomes[layer] = None
                    continue
                layer_outcomes[layer] = _validate_bridge_record(
                    operation[layer],
                    layer_path,
                    diagnostics,
                    mediated=layer == "agent_mediated",
                )
            if name in REQUIRED_OPERATIONS and name not in mediated_outcomes:
                mediated_outcomes[name] = layer_outcomes.get("agent_mediated")

    for required_name in sorted(REQUIRED_OPERATIONS):
        if required_name not in named_operations:
            _add(
                diagnostics,
                "BRIDGE_OPERATION_REQUIRED",
                "$.operations",
                f"exactly one {required_name!r} operation is required",
            )

    complete_mediated_outcomes = (
        set(named_operations) == REQUIRED_OPERATIONS
        and set(mediated_outcomes) == REQUIRED_OPERATIONS
        and all(outcome is not None for outcome in mediated_outcomes.values())
    )
    if complete_mediated_outcomes:
        mediated_success = all(mediated_outcomes.values())
        if not mediated_success:
            for name in sorted(
                operation
                for operation, outcome in mediated_outcomes.items()
                if outcome is False
            ):
                index, _ = named_operations[name]
                _add(
                    diagnostics,
                    "BRIDGE_MEDIATED_REQUIRED",
                    f"$.operations[{index}].agent_mediated",
                    f"{name} requires a successful agent-mediated terminal result",
                )
        expected_claim = "certified" if mediated_success else "rejected"
        if claim_status is not None and claim_status != expected_claim:
            _add(
                diagnostics,
                "BRIDGE_CLAIM_MISMATCH",
                "$.claim.status",
                f"mediated outcomes require claim status {expected_claim!r}",
            )

    return sorted(diagnostics)


def validate_research(document: object) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    root, _ = _validate_common(document, RESEARCH_KIND, diagnostics)
    if root is None:
        return sorted(diagnostics)

    _nonempty_string(root, "question", "$", diagnostics)

    classification: str | None = None
    claim_ids: list[Any] | None = None
    claim = _required_mapping(root, "claim", "$", diagnostics)
    if claim is not None:
        classification = _nonempty_string(
            claim, "classification", "$.claim", diagnostics
        )
        if classification is not None and classification not in {
            "transient",
            "standing",
        }:
            _add(
                diagnostics,
                "RESEARCH_CLASSIFICATION_INVALID",
                "$.claim.classification",
                "classification must be 'transient' or 'standing'",
            )
            classification = None
        _nonempty_string(claim, "conclusion", "$.claim", diagnostics)
        claim_ids = _required_list(
            claim, "observation_ids", "$.claim", diagnostics
        )
        if classification == "transient":
            follow_up = _nonempty_string(
                claim, "follow_up", "$.claim", diagnostics
            )
            if follow_up is None:
                _add(
                    diagnostics,
                    "RESEARCH_FOLLOW_UP_REQUIRED",
                    "$.claim.follow_up",
                    "transient claims require an independent follow-up",
                )

    observations = _required_list(root, "observations", "$", diagnostics)
    observations_by_id: dict[str, dict[str, Any]] = {}
    seen_execution_ids: dict[str, str] = {}
    seen_timestamps: dict[datetime, str] = {}
    if observations is not None:
        for index, value in enumerate(observations):
            observation_path = f"$.observations[{index}]"
            observation = _mapping(value, observation_path, diagnostics)
            if observation is None:
                continue

            observation_id = _nonempty_string(
                observation, "id", observation_path, diagnostics
            )
            execution_id = _nonempty_string(
                observation, "execution_id", observation_path, diagnostics
            )
            observed_at = _timestamp(
                observation, "observed_at", observation_path, diagnostics
            )
            _nonempty_string(observation, "source", observation_path, diagnostics)
            _nonempty_string(observation, "outcome", observation_path, diagnostics)

            if observation_id is not None:
                if observation_id in observations_by_id:
                    _add(
                        diagnostics,
                        "RESEARCH_OBSERVATION_ID_DUPLICATE",
                        f"{observation_path}.id",
                        f"observation ID {observation_id!r} is duplicated",
                    )
                else:
                    observations_by_id[observation_id] = observation
            if execution_id is not None:
                if execution_id in seen_execution_ids:
                    _add(
                        diagnostics,
                        "RESEARCH_EXECUTION_ID_DUPLICATE",
                        f"{observation_path}.execution_id",
                        f"execution ID {execution_id!r} is duplicated",
                    )
                else:
                    seen_execution_ids[execution_id] = observation_path
            if observed_at is not None:
                if observed_at in seen_timestamps:
                    _add(
                        diagnostics,
                        "RESEARCH_TIMESTAMP_DUPLICATE",
                        f"{observation_path}.observed_at",
                        "normalized observation timestamp is duplicated",
                    )
                else:
                    seen_timestamps[observed_at] = observation_path

    referenced_ids: list[str] = []
    if claim_ids is not None:
        for index, value in enumerate(claim_ids):
            reference_path = f"$.claim.observation_ids[{index}]"
            if not isinstance(value, str):
                _add(diagnostics, "FIELD_TYPE", reference_path, "expected a string")
                continue
            if not value.strip():
                _add(
                    diagnostics,
                    "FIELD_VALUE_INVALID",
                    reference_path,
                    "must not be empty",
                )
                continue
            if value in referenced_ids:
                _add(
                    diagnostics,
                    "RESEARCH_CLAIM_REFERENCE_DUPLICATE",
                    reference_path,
                    f"observation reference {value!r} is duplicated",
                )
            else:
                referenced_ids.append(value)
            if value not in observations_by_id:
                _add(
                    diagnostics,
                    "RESEARCH_OBSERVATION_REFERENCE_UNKNOWN",
                    reference_path,
                    f"observation {value!r} does not exist",
                )

    if classification == "transient" and len(referenced_ids) != 1:
        _add(
            diagnostics,
            "RESEARCH_TRANSIENT_SCOPE_REQUIRED",
            "$.claim.observation_ids",
            "transient claims must reference exactly one observation",
        )
    elif classification == "standing" and len(referenced_ids) < 2:
        _add(
            diagnostics,
            "RESEARCH_CORROBORATION_REQUIRED",
            "$.claim.observation_ids",
            "standing claims require at least two independent observations",
        )

    return sorted(diagnostics)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_artifact(path: Path) -> tuple[object | None, list[Diagnostic]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return None, [Diagnostic("ARTIFACT_READ_ERROR", "$", str(error))]
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys), []
    except (json.JSONDecodeError, ValueError) as error:
        return None, [Diagnostic("JSON_INVALID", "$", str(error))]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("bridge", "research"))
    parser.add_argument("artifact", type=Path)
    arguments = parser.parse_args(argv)

    document, diagnostics = _load_artifact(arguments.artifact)
    if not diagnostics:
        validator = validate_bridge if arguments.kind == "bridge" else validate_research
        diagnostics = validator(document)

    if diagnostics:
        for diagnostic in sorted(diagnostics):
            print(
                f"{diagnostic.code} {diagnostic.path}: {diagnostic.message}",
                file=sys.stderr,
            )
        return 2

    assert isinstance(document, dict)
    print(f"VALID {arguments.kind} {document['evidence_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
