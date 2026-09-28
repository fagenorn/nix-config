"""The administrative protocol's vocabulary for the transaction core (#206 D1, D4): the
inspection outcomes, effect results, error classes and refusal reasons, the retry budget
(`MAX_ATTEMPTS` attempts within `RETRY_WINDOW_MS`), the action name and parameter rule
(`action_violation`) and the deterministic action id (`action_id`) that is also the
idempotency key an effect receives. It reads no file, lock or clock.
"""

from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_storage import StateInvalid, json_object_violation

OUTCOMES = ("absent", "in_progress", "satisfied", "diverged", "unknown")
RESULTS = ("accepted", "rejected", "unknown")
ERROR_CLASSES = ("transient_transport", "provider_throttled", "provider_unavailable",
                 "invalid_input", "authorization_denied", "precondition_failed",
                 "unsupported_operation")
RETRY_SAFE_CLASSES = frozenset(ERROR_CLASSES[:3])
MAX_ATTEMPTS = 3
RETRY_WINDOW_MS = 900_000
EFFECT_STATES = ("publishing", "activating")
REFUSAL_REASONS = ("inspection_required", "not_absent", "not_retryable",
                   "budget_exhausted", "window_closed", "state_not_effectful",
                   "attempt_in_flight")


def action_violation(name: Any, parameters: Any) -> str | None:
    """The first rule an action's name or parameters break, or None (#206 D4)."""
    if type(name) is not str or not name:
        return f"name {name!r} is not a non-empty string"
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return f"name {name!r} is not encodable as UTF-8"
    violation = json_object_violation(parameters)
    return None if violation is None else f"parameters {violation}"


def action_id(transaction_id: str, name: str, parameters: dict) -> str:
    """`act_` + the first 32 hex digits of the digest of [transaction id, name,
    parameters]; also the idempotency key an effect receives (#206 D4)."""
    if type(transaction_id) is not str or not transaction_id:
        raise StateInvalid(f"{transaction_id!r}: action_id: transaction_id is not a "
                           f"non-empty string")
    violation = action_violation(name, parameters)
    if violation is not None:
        raise StateInvalid(f"{transaction_id}: action_id: {violation}")
    return "act_" + telemetry_digest([transaction_id, name, parameters])[7:39]
