"""Graders: the pure functions a `decide` step names (procedure format F10).

A grader declares the outcomes it can produce and grades a mapping of the
step's input paths to their values. It reads only its argument, and any value
may be `None` (a group member that sent no reply reads as `None`, D6).

- `direct-implemented`: the implement reply -> ineligible, task, lite or full.
- `direct-lite-tally`: the lite review and the independent one -> no-review,
  unusable, escalate, codex-unavailable, findings or clean.
- `direct-escalated-tally`: the same without `no-review` and `escalate`
  (`escalated` is no group member, so its no reply never reaches the tally).
- `direct-full-tally`: the full review and its independent one, no `escalate`.
- `direct-fixed`: a fix reply -> done or not-done (keys on the suffixes).
- `direct-settled`: a re-review reply -> unusable, findings or clean (keys on
  the suffixes).
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


def _review_capability(results: Mapping[str, object]) -> str:
    capabilities = results.get("contract.capabilities")
    if not isinstance(capabilities, Mapping):
        return "clear"
    for name in ("review.code", "review.plan"):
        entry = capabilities.get(name)
        if isinstance(entry, Mapping) and entry.get("state") == "blocked":
            return "blocked"
    return "clear"


def _blank(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


def _suffixed(results: Mapping[str, object], suffix: str) -> object:
    return next((value for path, value in results.items() if path.endswith(suffix)), None)


def _blocking(findings: object) -> list[Mapping[str, object]]:
    if not isinstance(findings, list):
        return []
    return [f for f in findings if isinstance(f, Mapping) and f.get("severity") != "minor"]


def _absent(verdict: object, findings: object) -> bool:
    return verdict not in ("pass", "findings") or not isinstance(findings, list)


def _unusable(findings: object) -> bool:
    return any(_blank(f.get("file")) and _blank(f.get("failing_input")) for f in _blocking(findings))


def _ungraded(criteria: object, graded: object) -> list[object]:
    entries = [g for g in graded if isinstance(g, Mapping)] if isinstance(graded, list) else []
    missing = []
    for criterion in criteria if isinstance(criteria, list) else []:
        if not isinstance(criterion, Mapping) or criterion.get("kind") != "code":
            continue
        met = any(g.get("id") == criterion.get("id") and g.get("met") is True
                  and not _blank(g.get("evidence")) for g in entries)
        if not met:
            missing.append(criterion.get("id"))
    return missing


def _tally(results: Mapping[str, object], review: str, independent: str, *,
           absent: str, escalates: bool) -> str:
    verdict, findings = results.get(f"{review}.verdict"), results.get(f"{review}.findings")
    if _absent(verdict, findings):
        return absent
    if _unusable(findings):
        return "unusable"
    if escalates and results.get(f"{review}.escalate") is True:
        return "escalate"
    if results.get(f"{independent}.verdict") not in ("pass", "findings", "none"):
        return "codex-unavailable"
    ungraded = _ungraded(results.get("implement.acceptance"), results.get(f"{review}.acceptance"))
    if _blocking(findings) or ungraded or _blocking(results.get(f"{independent}.findings")):
        return "findings"
    return "clean"


def _direct_implemented(results: Mapping[str, object]) -> str:
    if results.get("implement.ineligible") is True:
        return "ineligible"
    if (results.get("implement.status") != "done" or _blank(results.get("implement.start_head"))
            or _blank(results.get("implement.commit"))):
        return "task"
    acceptance = results.get("implement.acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        return "task"
    return "full" if results.get("implement.sensitive") is True else "lite"


def _direct_lite_tally(results: Mapping[str, object]) -> str:
    return _tally(results, "lite-review", "lite-independent", absent="no-review", escalates=True)


def _direct_escalated_tally(results: Mapping[str, object]) -> str:
    return _tally(results, "escalated", "lite-independent", absent="unusable", escalates=False)


def _direct_full_tally(results: Mapping[str, object]) -> str:
    return _tally(results, "full-review", "full-independent", absent="no-review", escalates=False)


def _direct_fixed(results: Mapping[str, object]) -> str:
    done = (_suffixed(results, ".status") == "done" and not _blank(_suffixed(results, ".start_head"))
            and not _blank(_suffixed(results, ".commit")))
    return "done" if done else "not-done"


def _direct_settled(results: Mapping[str, object]) -> str:
    verdict, findings = _suffixed(results, ".verdict"), _suffixed(results, ".findings")
    if _absent(verdict, findings):
        return "findings"
    if _unusable(findings):
        return "unusable"
    return "findings" if _blocking(findings) else "clean"


GRADERS: Mapping[str, Grader] = {
    "toy-tally": Grader(("accept", "revise"), _toy_tally),
    "review-capability": Grader(("clear", "blocked"), _review_capability),
    "direct-implemented": Grader(("ineligible", "task", "lite", "full"), _direct_implemented),
    "direct-lite-tally": Grader(
        ("no-review", "unusable", "escalate", "codex-unavailable", "findings", "clean"),
        _direct_lite_tally),
    "direct-escalated-tally": Grader(
        ("unusable", "codex-unavailable", "findings", "clean"), _direct_escalated_tally),
    "direct-full-tally": Grader(
        ("no-review", "unusable", "codex-unavailable", "findings", "clean"), _direct_full_tally),
    "direct-fixed": Grader(("done", "not-done"), _direct_fixed),
    "direct-settled": Grader(("unusable", "findings", "clean"), _direct_settled),
}
