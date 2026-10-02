"""The `failed` disposition (#209): the reserved reason `failure_disposed` and the two rules
that keep `failed` closed. `disposition_advance_violation` refuses an `advance` into `failed`
or with the reserved reason, and `disposition_pairing_violation` binds `failure_disposed` to
the transition right after it, every transition into `failed` and every transition with the
reserved reason to the event right before it (D8, D21). `failure_disposed` is not yet a
dispatched event type, so no history can enter `failed`.
"""

from collections.abc import Mapping

FAILURE_REASON = "failure_disposed"

_DISPOSED = ("attention_required", "failed", FAILURE_REASON, "known")


def disposition_advance_violation(target: str, reason: str) -> str | None:
    """Why `advance` may not take a transaction to `target` with `reason`, or None (D8,
    D21): `failed` and the reserved reason are `dispose_failed`'s alone."""
    if target == "failed":
        return "failed is entered only through dispose_failed"
    if reason == FAILURE_REASON:
        return f"reserved reason {FAILURE_REASON} is written only by dispose_failed"
    return None


def disposition_pairing_violation(previous: Mapping | None,
                                  event: Mapping | None) -> str | None:
    """How `event`, the one after `previous` (None past the end), breaks the disposition
    pairing, or None (D21): `failure_disposed` comes immediately before `attention_required
    -> failed` with reason `failure_disposed` and external state `known`, every transition
    into `failed` immediately after it, and a transition with the reserved reason
    immediately after its event."""
    kind = None if previous is None else previous.get("type")
    edge = None
    if event is not None and event.get("type") == "transitioned":
        edge = tuple(event.get(key) for key in ("from", "to", "reason", "external_state"))
    if kind == FAILURE_REASON and edge != _DISPOSED:
        return (f"{FAILURE_REASON} is not immediately followed by attention_required -> "
                f"failed with reason {FAILURE_REASON} and external state known")
    if edge is not None and edge[1] == "failed" and kind != FAILURE_REASON:
        return f"transition into failed does not immediately follow {FAILURE_REASON}"
    if edge is not None and edge[2] == FAILURE_REASON and kind != FAILURE_REASON:
        return f"reserved reason {FAILURE_REASON} does not immediately follow its event"
    return None
