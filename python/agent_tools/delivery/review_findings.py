"""The closed kind list of a review finding and its computed disposition.

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
- `dropped`: a minor finding, or one naming only criteria of other kinds than code, nobody acted on.
- `open`: still open when the run stopped.

A disposition is never set by hand and never asked of a model. A finding is
named `<step>:<n>` (the review step and its 1-based place in that step's list),
as the fix and re-review prompts teach; the names are unique within one round
of review, and recur across the rounds of a step that is visited again. The
later findings-record step builds the `Round`s from a run's stored results (the
last stored visit of a step that is asked again). A procedure that files a
follow-up issue from a finding writes the finding's rule and kind into the issue
body and passes its name in that round's `filed`.

`usable` copies the rule of the direct re-review route (`engine_graders`), including its drop of a
finding naming only non-code criteria of `acceptance`, rather than importing it, so this module
imports no engine module; a test holds the copy to the grader. The landing route's re-review (`LANDING_REREVIEWS`) takes any `pass` or `findings`
verdict and stops on `findings`, so it is judged by that verdict, not by `usable`. A minor
finding, or one dropped by kind, that a re-review restates as a blocker keeps the restatement as its own finding. Nothing here reads a file, starts a process or reads a clock, and an
odd shape never raises.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

NON_CODE_KINDS: tuple[str, ...] = ("evidence", "human", "note")

KINDS: tuple[str, ...] = (
    "edge-or-failure-path", "weak-test", "missing-test", "contract-mismatch", "stale-docs", "security",
    "concurrency", "plan-step-not-executable", "other")

# Re-review steps of a route that stops on `findings` (the landing route) instead of looping on a usable reply.
LANDING_REREVIEWS: frozenset[str] = frozenset({"merge-rereview"})

DISPOSITIONS: tuple[str, ...] = ("fixed", "declined", "filed", "dropped", "open")


@dataclass(frozen=True)
class Round:
    """The stored results of one review round: each review step's id and result (`None` for no reply),
    the fix step's result, the re-review step's id and result, the names filed as follow-up issues, and the
    run's `implement.acceptance` (given only for a round of the direct route)."""

    reviews: tuple[tuple[str, object], ...]
    fix: object = None
    rereview: tuple[str, object] | None = None
    filed: frozenset[str] = frozenset()
    acceptance: object = None


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


def _names(text: str, cid: str) -> bool:
    """Whether `cid` occurs in `text` with no ASCII letter, digit or underscore right before or after it."""
    start = text.find(cid)
    while start >= 0:
        end = start + len(cid)
        around = [text[start - 1] if start else "", text[end] if end < len(text) else ""]
        if not any(ch.isascii() and (ch.isalnum() or ch == "_") for ch in around):
            return True
        start = text.find(cid, start + 1)
    return False


def _restates_a_finding(text: str) -> bool:
    """Whether `text` holds a finding name, `<step>:<n>`: a step name (a lowercase letter first) and a place of 1 or more."""
    for place, ch in enumerate(text):
        if ch != ":" or text[place + 1:place + 2] not in tuple("123456789"):
            continue
        start = place
        while start and (text[start - 1] in "-0123456789" or "a" <= text[start - 1] <= "z"):
            start -= 1
        if any("a" <= c <= "z" for c in text[start:place]):
            return True
    return False


def _kinds(acceptance: object) -> dict[str, object]:
    if not isinstance(acceptance, list):
        return {}
    kinds: dict[str, object] = {}
    for c in acceptance:
        if isinstance(c, Mapping) and isinstance(c.get("id"), str) and c["id"].strip():
            kinds[c["id"]] = c.get("kind") if kinds.setdefault(c["id"], c.get("kind")) == c.get("kind") else None
    return kinds


def _drops(finding: Mapping[str, object], kinds: Mapping[str, object]) -> bool:
    restates = finding.get("restates")
    if isinstance(restates, str) and _restates_a_finding(restates):
        return False
    texts = [finding[m] for m in ("restates", "summary") if isinstance(finding.get(m), str)]
    named = [cid for cid in kinds if any(_names(text, cid) for text in texts)]
    return bool(named) and all(kinds[cid] in NON_CODE_KINDS for cid in named)


def usable(rereview: object, acceptance: object = None) -> bool:
    """Whether the re-review route would accept this reply instead of discarding it and asking again."""
    if not isinstance(rereview, Mapping) or rereview.get("verdict") not in ("pass", "findings"):
        return False
    findings = rereview.get("findings")
    if not isinstance(findings, list):
        return False
    kinds = _kinds(acceptance)
    return not any(isinstance(f, Mapping) and not _drops(f, kinds) and not _minor(f)
                   and _blank(f.get("file")) and _blank(f.get("failing_input")) for f in findings)


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
        declined = _declined(one.fix)
        closes = one.rereview is not None and (
            _answered(one.rereview[1]) if one.rereview[0] in LANDING_REREVIEWS
            else usable(one.rereview[1], one.acceptance))
        kinds = _kinds(one.acceptance)
        again = _named(*one.rereview) if closes else []
        landing = one.rereview is not None and one.rereview[0] in LANDING_REREVIEWS
        # A direct re-review settles clean past a finding it drops, so that finding restates, and holds, nothing.
        settled = [(n, f) for n, f in again if landing or not (_minor(f) or _drops(f, kinds))]
        restated = {f["restates"] for _, f in settled if isinstance(f.get("restates"), str)}
        for name, finding in reviewed:
            if name in one.filed:
                value = "filed"
            elif _minor(finding) or _drops(finding, kinds):
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
            dropping = _minor(finding) or _drops(finding, kinds)
            represented = original is not None and (
                _minor(finding) or not (_minor(original) or _drops(original, kinds)))
            if represented and (landing or not dropping):
                continue
            value = "filed" if name in one.filed else "dropped" if dropping else "open"
            disposed.append(Disposed(place, name, finding, value))
    return tuple(disposed)
