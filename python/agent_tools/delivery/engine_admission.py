"""Hands out the indexes of a call's items in list order."""

from __future__ import annotations

import threading

from agent_tools.delivery import engine_session


class Admission:
    """Hands out the indexes of a call's items in list order, none once a fault is noted or the engine ends.

    A sequential admission also hands out none once told of a child end other than `done`."""

    def __init__(self, count: int, sequential: bool = False) -> None:
        self._count = count
        self._sequential = sequential
        self._next = 0
        self._stopped = False
        self._lock = threading.Lock()

    def take(self) -> int | None:
        with self._lock:
            if self._stopped or self._next >= self._count or engine_session.ending():
                return None
            index = self._next
            self._next += 1
            return index

    def ended(self, end: str) -> None:
        if self._sequential and end != "done":
            self.fail()

    def fail(self) -> None:
        with self._lock:
            self._stopped = True
