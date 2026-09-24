"""Canonical JSON primitives for the delivery model."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import re
from typing import Any

MODEL_INTERFACE_VERSION = 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

class DeliveryModelError(ValueError):
    """A delivery object is structurally or semantically invalid."""


def _reject(message: str = "invalid") -> None:
    raise DeliveryModelError(message)


def canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes:
    candidate = copy.deepcopy(value)
    if omit_derived is not None:
        if not isinstance(candidate, dict) or omit_derived not in candidate:
            _reject(f"missing derived member: {omit_derived}")
        del candidate[omit_derived]
    try:
        return (json.dumps(candidate, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeliveryModelError("value is not canonical JSON") from error


def canonical_digest(value: object, *, omit_derived: str | None = None) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, omit_derived=omit_derived)).hexdigest()


def _members(value: str) -> set[str]:
    return set(value.split())


def _object(value: Any, keys: set[str], label: str = "object") -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _reject(f"invalid {label} keys")
    return value


def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _reject(f"invalid {label}")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _reject(f"invalid {label}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        _reject(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _reject(f"invalid {label}")
    return value


def _utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        _reject(f"invalid {label}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise DeliveryModelError(f"invalid {label}") from error
    return value


def _derived(value: dict[str, Any], label: str, field: str = "id") -> None:
    _digest(value[field], f"{label} {field}")
    if value[field] != canonical_digest(value, omit_derived=field):
        _reject(f"invalid {label} {field}")


def _sorted_unique(values: Any, label: str, *, key=lambda item: item) -> list[Any]:
    if not isinstance(values, list):
        _reject(f"invalid {label}")
    keys = [key(item) for item in values]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _reject(f"invalid {label} order")
    return values


def _ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        _reject(f"invalid {label}")
    if value["kind"] == "none":
        return _object(value, _members("kind"), label)
    if value["kind"] == "literal":
        _object(value, _members("kind value"), label); _string(value["value"], label)
        return value
    _reject(f"invalid {label} kind")


def _data_ref(value: Any, label: str, *, allow_slot: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        _reject(f"invalid {label}")
    kind = value["kind"]
    if kind == "none":
        return _object(value, _members("kind"), label)
    if kind == "literal":
        _object(value, _members("kind digest classification audience"), label)
        _digest(value["digest"], f"{label} digest")
    elif kind == "selected_output_slot" and allow_slot:
        _object(value, _members("kind slot_id classification audience"), label)
        _string(value["slot_id"], f"{label} slot")
    else:
        _reject(f"invalid {label} kind")
    _string(value["classification"], f"{label} classification")
    _string(value["audience"], f"{label} audience")
    return value
