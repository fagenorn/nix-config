"""Graders: the pure functions a `decide` step names (procedure format F10).

A grader declares the outcomes it can produce and grades a mapping of the
step's input paths to their values. It reads only its argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


@dataclass(frozen=True)
class Grader:
    outcomes: tuple[str, ...]
    grade: Callable[[Mapping[str, object]], str]


def _toy_tally(results: Mapping[str, object]) -> str:
    return "accept" if all(value == "approve" for value in results.values()) else "revise"


GRADERS: Mapping[str, Grader] = {
    "toy-tally": Grader(("accept", "revise"), _toy_tally),
}
