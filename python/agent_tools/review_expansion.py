"""The expansion budget of the retained compact payloads (issue 256).

`MEMBER_MAX_BYTES` is the decode bound of a retained bundle member; `review_witness` imports it from here. A
`Budget` is the per-call budget that `expand_100` and `expand_121` charge each row they build to: at most
`MEMBER_MAX_BYTES` canonical bytes, read when the budget is created.
"""
from __future__ import annotations

from typing import Callable

from agent_tools.review_forecast import canonical_bytes

MEMBER_MAX_BYTES = 1048576


class Budget:
    """Canonical bytes one expansion has built, at most `MEMBER_MAX_BYTES` as read when it is created."""

    def __init__(self, refusal: Callable[[], Exception]) -> None:
        self._limit, self._spent, self._refusal = MEMBER_MAX_BYTES, 0, refusal

    def add(self, size: int) -> None:
        self._spent += size
        if self._spent > self._limit:
            raise self._refusal()

    def charge(self, value):
        try:
            size = len(canonical_bytes(value))
        except (TypeError, ValueError) as exc:
            raise self._refusal() from exc
        self.add(size)
        return value
