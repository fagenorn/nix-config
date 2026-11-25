"""The closed kind list of a review finding and its computed disposition (issue 1416, issue 1535).

This module is the home of `KINDS`, the closed list of kinds a reviewer gives
each finding. Every review reply schema under `procedures/` copies the list into
its `kind` enum; no engine module imports this module, so the engine reads the
schema alone. It imports only the standard library.

It also computes what became of each finding, its disposition, from the stored
results of a run. The five values:

- `fixed`: a re-review that the route accepted no longer raises it.
- `declined`: the implementer declined it in the fix reply's `declines` and the
  re-reviewer did not restate it.
- `filed`: it became a follow-up issue.
- `dropped`: a minor finding nobody acted on.
- `open`: still open when the run stopped.

A disposition is never set by hand and never asked of a model. A finding is
named `<step>:<n>` (the review step and its 1-based place in that step's list),
as the fix and re-review prompts teach; the names are unique within one round
of review, and recur across the rounds of a step that is visited again. The
later findings-record step builds the `Round`s from a run's stored results (the
last stored visit of a step that is asked again). A procedure that files a
follow-up issue from a finding writes the finding's rule and kind into the issue
body and passes its name in that round's `filed`.

`usable` copies the rule of the direct re-review route (`engine_graders`) rather than
importing it, so this module imports no engine module; a test holds the copy to
the grader. The landing route's re-review (`LANDING_REREVIEWS`) takes any `pass` or `findings`
verdict and stops on `findings`, so it is judged by that verdict, not by `usable`. A minor
finding a re-review restates as a blocker keeps the restatement as its own finding. Nothing here reads a file, starts a process or reads a clock, and an
odd shape never raises.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

KINDS: tuple[str, ...] = (
    "edge-or-failure-path", "weak-test", "missing-test", "contract-mismatch", "stale-docs", "security",
    "concurrency", "plan-step-not-executable", "other")

# Re-review steps of a route that stops on `findings` (the landing route) instead of looping on a usable reply.
LANDING_REREVIEWS: frozenset[str] = frozenset({"merge-rereview"})

DISPOSITIONS: tuple[str, ...] = ("fixed", "declined", "filed", "dropped", "open")


@dataclass(frozen=True)
class Round:
    """The stored results of one review round: each review step's id and result (`None` for no reply),
    the fix step's result, the re-review step's id and result, and the names filed as follow-up issues."""

    reviews: tuple[tuple[str, object], ...]
    fix: object = None
    rereview: tuple[str, object] | None = None
    filed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Disposed:
    """One finding and its disposition; `round` is the 1-based place of its round."""

    round: int
    name: str
    finding: Mapping[str, object]
    disposition: str


def finding_name(step: str, position: int) -> str:
    return f"{step}:{position}"


def _blank(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


def _minor(finding: Mapping[str, object]) -> bool:
    return finding.get("severity") == "minor"


def usable(rereview: object) -> bool:
    """Whether the re-review route would accept this reply instead of discarding it and asking again."""
    if not isinstance(rereview, Mapping) or rereview.get("verdict") not in ("pass", "findings"):
        return False
    findings = rereview.get("findings")
    if not isinstance(findings, list):
        return False
    return not any(isinstance(f, Mapping) and not _minor(f) and _blank(f.get("file")) and _blank(f.get("failing_input"))
                   for f in findings)


def _answered(rereview: object) -> bool:
    """Whether the landing route took this re-review's verdict, which it does for any `pass` or `findings`."""
    return (isinstance(rereview, Mapping) and rereview.get("verdict") in ("pass", "findings")
            and isinstance(rereview.get("findings"), list))


def _named(step: str, result: object) -> list[tuple[str, Mapping[str, object]]]:
    findings = result.get("findings") if isinstance(result, Mapping) else None
    if not isinstance(findings, list):
        return []
    return [(finding_name(step, i), f) for i, f in enumerate(findings, 1) if isinstance(f, Mapping)]


def _declined(fix: object) -> set[str]:
    declines = fix.get("declines") if isinstance(fix, Mapping) else None
    if not isinstance(declines, list):
        return set()
    return {d["finding"] for d in declines if isinstance(d, Mapping) and isinstance(d.get("finding"), str)}


def dispositions(rounds: Sequence[Round]) -> tuple[Disposed, ...]:
    """Each finding of each round with its disposition: round order, review order, list order, new findings last."""
    disposed: list[Disposed] = []
    for place, one in enumerate(rounds, 1):
        reviewed = [item for step, result in one.reviews for item in _named(step, result)]
        names = {name for name, _ in reviewed}
        declined = _declined(one.fix)
        closes = one.rereview is not None and (
            _answered(one.rereview[1]) if one.rereview[0] in LANDING_REREVIEWS else usable(one.rereview[1]))
        again = _named(*one.rereview) if closes else []
        restated = {f["restates"] for _, f in again if isinstance(f.get("restates"), str)}
        for name, finding in reviewed:
            if name in one.filed:
                value = "filed"
            elif _minor(finding):
                value = "dropped"
            elif closes and name not in restated:
                value = "declined" if name in declined else "fixed"
            else:
                value = "open"
            disposed.append(Disposed(place, name, finding, value))
        originals = dict(reviewed)
        for name, finding in again:
            restates = finding.get("restates")
            original = originals.get(restates) if isinstance(restates, str) else None
            if original is not None and (_minor(finding) or not _minor(original)):
                continue
            value = "filed" if name in one.filed else "dropped" if _minor(finding) else "open"
            disposed.append(Disposed(place, name, finding, value))
    return tuple(disposed)
