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
finding of kind `other` naming only non-code criteria of `acceptance` (or restating earlier findings, held by
name, that are so dropped), rather than importing it, so this module
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


def _refs(text: str) -> list[str]:
    """Each finding name `<step>:<n>` in `text`: a step name (a lowercase letter in it) and a place of 1 or more."""
    refs = []
    for place, ch in enumerate(text):
        if ch != ":" or text[place + 1:place + 2] not in tuple("123456789"):
            continue
        start, end = place, place + 1
        while start and (text[start - 1] in "-0123456789" or "a" <= text[start - 1] <= "z"):
            start -= 1
        while text[end:end + 1] != "" and text[end] in "0123456789":
            end += 1
        if any("a" <= c <= "z" for c in text[start:place]):
            refs.append(text[start:end])
    return refs


def _restates_a_finding(text: str) -> bool:
    return bool(_refs(text))


def _kinds(acceptance: object) -> dict[str, object]:
    if not isinstance(acceptance, list):
        return {}
    kinds: dict[str, object] = {}
    for c in acceptance:
        if isinstance(c, Mapping) and isinstance(c.get("id"), str) and c["id"].strip():
            kinds[c["id"]] = c.get("kind") if kinds.setdefault(c["id"], c.get("kind")) == c.get("kind") else None
    return kinds


def _criteria(finding: Mapping[str, object], kinds: Mapping[str, object]) -> list[str]:
    texts = [finding[m] for m in ("restates", "summary") if isinstance(finding.get(m), str)]
    return [cid for cid in kinds if any(_names(text, cid) for text in texts)]


def _own(finding: Mapping[str, object], kinds: Mapping[str, object]) -> bool:
    """Whether a finding of kind `other`, restating none, names only non-code criteria and at least one."""
    restates = finding.get("restates")
    if finding.get("kind", "other") != "other" or (isinstance(restates, str) and _restates_a_finding(restates)):
        return False
    named = _criteria(finding, kinds)
    return bool(named) and all(kinds[cid] in NON_CODE_KINDS for cid in named)


def _drops(finding: Mapping[str, object], kinds: Mapping[str, object],
           earlier: Mapping[str, Mapping[str, object]]) -> bool:
    """The grader's drop: the finding's own (`_own`), or, for a kind `other` finding restating findings, every one
    of them held in `earlier` (name -> finding) and dropped by `_own`."""
    restates = finding.get("restates")
    refs = _refs(restates) if isinstance(restates, str) else []
    if not refs:
        return _own(finding, kinds)
    return (finding.get("kind", "other") == "other"
            and all(kinds[cid] in NON_CODE_KINDS for cid in _criteria(finding, kinds))
            and all(name in earlier and _own(earlier[name], kinds) for name in refs))


def usable(rereview: object, acceptance: object = None,
           earlier: Mapping[str, Mapping[str, object]] | None = None) -> bool:
    """Whether the re-review route would accept this reply instead of discarding it and asking again; `earlier`
    holds the findings it may restate, by name."""
    if not isinstance(rereview, Mapping) or rereview.get("verdict") not in ("pass", "findings"):
        return False
    findings = rereview.get("findings")
    if not isinstance(findings, list):
        return False
    kinds, held = _kinds(acceptance), earlier or {}
    return not any(isinstance(f, Mapping) and not _drops(f, kinds, held) and not _minor(f)
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
        originals = dict(reviewed)
        closes = one.rereview is not None and (
            _answered(one.rereview[1]) if one.rereview[0] in LANDING_REREVIEWS
            else usable(one.rereview[1], one.acceptance, originals))
        kinds = _kinds(one.acceptance)
        again = _named(*one.rereview) if closes else []
        landing = one.rereview is not None and one.rereview[0] in LANDING_REREVIEWS
        # A direct re-review settles clean past a finding it drops, so that finding restates, and holds, nothing.
        settled = [(n, f) for n, f in again if landing or not (_minor(f) or _drops(f, kinds, originals))]
        restated = {f["restates"] for _, f in settled if isinstance(f.get("restates"), str)}
        for name, finding in reviewed:
            if name in one.filed:
                value = "filed"
            elif _minor(finding) or _drops(finding, kinds, originals):
                value = "dropped"
            elif closes and name not in restated:
                value = "declined" if name in declined else "fixed"
            else:
                value = "open"
            disposed.append(Disposed(place, name, finding, value))
        for name, finding in again:
            restates = finding.get("restates")
            original = originals.get(restates) if isinstance(restates, str) else None
            dropping = _minor(finding) or _drops(finding, kinds, originals)
            represented = original is not None and (
                _minor(finding) or not (_minor(original) or _drops(original, kinds, originals)))
            if represented and (landing or not dropping):
                continue
            value = "filed" if name in one.filed else "dropped" if dropping else "open"
            disposed.append(Disposed(place, name, finding, value))
    return tuple(disposed)
