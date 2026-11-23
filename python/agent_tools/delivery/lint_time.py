"""The lint stopwatch: how long each never-rise lint takes on both sides of the comparison.

A lint is a never-rise enforcer (`agent_tools.delivery.never_rise.Enforcer`), run
once on the merge base and once on the branch. `Stopwatch.timed` wraps each
enforcer's `find` so its elapsed time is kept under the enforcer's rule. The
comparison reads the base side first, so the first `find` call of a rule is its
base time and every later call adds to its branch time. A `find` that raises is
timed too, and its exception propagates unchanged.

Each side is `int(round(seconds * 1000))` milliseconds, and a lint's `ms` is the
sum of its two sides. `record()` answers `None` when no wrapped `find` ran.

The record is one line, `RECORD_PREFIX` and a compact JSON object with sorted keys:

    lint-times v1 {"lints":[{"base_ms":2000,"branch_ms":3000,"lint":"A"}],"total_ms":5000}

`total_ms` is the sum of every lint's two sides. `conformance run --lint-times`
prints that line on stderr. `parse_log` reads one back from a job log: it takes
the one line that starts with the prefix after an optional leading BOM and an
optional GitHub timestamp, answers `None` for none and raises `ValueError` for
two, or for a payload that is not an object with exactly `lints` and `total_ms`,
whose `lints` is a non-empty list of objects with exactly `base_ms`, `branch_ms`
and `lint`, each `lint` a distinct non-empty string, each `*_ms` a non-negative
`int` that is not a `bool`, and whose `total_ms` is their exact sum.
"""

import dataclasses
import json
import re
import time
from collections.abc import Callable, Sequence
from typing import NamedTuple

from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation

RECORD_PREFIX = "lint-times v1 "
LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ")
BOM = "\ufeff"


class LintTime(NamedTuple):
    lint: str
    base_ms: int
    branch_ms: int

    @property
    def ms(self) -> int:
        return self.base_ms + self.branch_ms


class Record(NamedTuple):
    lints: tuple[LintTime, ...]

    @property
    def total_ms(self) -> int:
        return sum(lint.ms for lint in self.lints)


def milliseconds(seconds: float) -> int:
    return int(round(seconds * 1000))


class Stopwatch:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._calls: dict[str, list[float]] = {}

    def timed(self, enforcers: Sequence[Enforcer]) -> tuple[Enforcer, ...]:
        """Each enforcer with a `find` that keeps its elapsed time under its rule."""
        return tuple(dataclasses.replace(e, find=self._wrap(e)) for e in enforcers)

    def _wrap(self, enforcer: Enforcer) -> Callable[[Snapshot], list[Violation]]:
        def find(snapshot: Snapshot) -> list[Violation]:
            start = self._clock()
            try:
                return enforcer.find(snapshot)
            finally:
                self._calls.setdefault(enforcer.rule, []).append(self._clock() - start)

        return find

    def record(self) -> Record | None:
        """The lints in the order they first ran, or `None` when none ran."""
        if not self._calls:
            return None
        return Record(tuple(
            LintTime(rule, milliseconds(calls[0]), sum(milliseconds(c) for c in calls[1:]))
            for rule, calls in self._calls.items()))


def record_line(record: Record) -> str:
    payload = {
        "lints": [
            {"base_ms": lint.base_ms, "branch_ms": lint.branch_ms, "lint": lint.lint}
            for lint in record.lints],
        "total_ms": record.total_ms,
    }
    return RECORD_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def milliseconds_of(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} is not a non-negative integer")
    return value


def lint_time_of(entry: object) -> LintTime:
    if not isinstance(entry, dict) or set(entry) != {"base_ms", "branch_ms", "lint"}:
        raise ValueError("a lint is not an object of base_ms, branch_ms and lint")
    lint = entry["lint"]
    if not isinstance(lint, str) or not lint:
        raise ValueError("a lint name is not a non-empty string")
    return LintTime(
        lint, milliseconds_of(entry["base_ms"], "base_ms"),
        milliseconds_of(entry["branch_ms"], "branch_ms"))


def parse_payload(text: str) -> Record:
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ValueError(f"the record is not JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"lints", "total_ms"}:
        raise ValueError("the record is not an object of lints and total_ms")
    entries = payload["lints"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("lints is not a non-empty list")
    lints = tuple(lint_time_of(entry) for entry in entries)
    if len({lint.lint for lint in lints}) != len(lints):
        raise ValueError("a lint is repeated")
    record = Record(lints)
    if payload["total_ms"] != record.total_ms or isinstance(payload["total_ms"], bool):
        raise ValueError("total_ms is not the sum of the lints")
    return record


def parse_log(text: str) -> Record | None:
    """The one record line of a job log, `None` for none, `ValueError` for two or a bad one."""
    payloads = []
    for line in text.removeprefix(BOM).splitlines():
        body = LOG_STAMP.sub("", line, count=1)
        if body.startswith(RECORD_PREFIX):
            payloads.append(body[len(RECORD_PREFIX):])
    if len(payloads) > 1:
        raise ValueError("the log holds more than one lint-times record")
    return parse_payload(payloads[0]) if payloads else None
