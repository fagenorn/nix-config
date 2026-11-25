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
- `verify-fixed`: a verify fix reply -> unrelated (a test and its evidence), not-done or done.
- `verify-narrowing`: the fix review, the round and the fix's range -> findings, rerun-failed-only
  or rerun-all (a rerun of only the failing ids needs every condition, else all).
- `lane-rule`: the issue step's body, marker and lane paths -> direct or
  standard, by `lane_rule.choose`, with an unknown marker read as marked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from agent_tools.delivery import lane_rule


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


def _verify_fixed(results: Mapping[str, object]) -> str:
    unrelated = results.get("fix.unrelated")
    if isinstance(unrelated, Mapping) and not _blank(unrelated.get("test")) and not _blank(unrelated.get("evidence")):
        return "unrelated"
    return _direct_fixed(results)


def _failed_only(results: Mapping[str, object]) -> bool:
    rows = results.get("round.results")
    if results.get("round.clean") is not True or not isinstance(rows, list):
        return False
    if not all(isinstance(r, Mapping) and r.get("status") in ("pass", "fail", "skipped")
               and r.get("no_slot") is not True for r in rows):
        return False
    failed = [r for r in rows if r.get("status") == "fail"]
    named = [r.get("named") for r in failed]
    if not failed or not any(r.get("status") == "pass" for r in rows):
        return False
    if not all(isinstance(n, list) and n and all(isinstance(x, str) for x in n) for n in named):
        return False
    paths = results.get("ws-check.changed_paths")
    return (results.get("ws-check.whitespace_only") is True and isinstance(paths, list) and bool(paths)
            and all(isinstance(p, str) and p.strip() in {x for n in named for x in n} for p in paths)
            and results.get("fix-review.whitespace_insignificant") is True
            and not _blank(results.get("fix-review.whitespace_evidence")))


def _verify_narrowing(results: Mapping[str, object]) -> str:
    findings = results.get("fix-review.findings")
    if not isinstance(findings, list) or any(
            not isinstance(f, Mapping) or f.get("severity") != "minor" for f in findings):
        return "findings"
    return "rerun-failed-only" if _failed_only(results) else "rerun-all"


def _lane_rule(results: Mapping[str, object]) -> str:
    return lane_rule.choose(results.get("issue.body"), marked=results.get("issue.marked") is not False,
                            lane_paths=results.get("issue.lane_paths")).lane


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
    "verify-fixed": Grader(("unrelated", "not-done", "done"), _verify_fixed),
    "verify-narrowing": Grader(("findings", "rerun-failed-only", "rerun-all"), _verify_narrowing),
    "lane-rule": Grader(("direct", "standard"), _lane_rule),
}
