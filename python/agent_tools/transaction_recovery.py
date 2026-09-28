"""Recovery (#208): for now, the derived `recovery` view of one transaction.

`recovery_view` reads the `created` event's `recovery_plan_digest` and `recovers`
back-link, the latest `recovery_started` event's `effect_snapshot` and `selected` units,
and every `roll_forward_linked` event's child transaction id, in history order. It reads
those events by type only; the snapshot fold derives it on every load and it is never
stored (D12). Every function here is pure: the module reads no file, lock or clock.
"""

import copy
from typing import Any


def recovery_view(document: dict) -> dict[str, Any]:
    """`{"plan_digest", "recovers", "effect_snapshot", "selected", "children"}` for a
    validated `document`; `effect_snapshot` is None and `selected` empty before any
    recovery starts (D12)."""
    events = document["events"]
    created = events[0]
    started = [event for event in events if event["type"] == "recovery_started"]
    latest = started[-1] if started else None
    return {
        "plan_digest": created["recovery_plan_digest"],
        "recovers": created["recovers"],
        "effect_snapshot": None if latest is None else copy.deepcopy(latest["effect_snapshot"]),
        "selected": [] if latest is None else copy.deepcopy(latest["selected"]),
        "children": [event["child_transaction_id"] for event in events
                     if event["type"] == "roll_forward_linked"],
    }
