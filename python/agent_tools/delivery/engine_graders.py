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
- `plan-settled`: a plan review's reply, as `direct-settled` grades it, except that a `findings` verdict with no
  finding at all is unusable.
- The drop rule: a finding naming at least one criterion of `implement.acceptance` (its id in `restates` or
  `summary`, with no ASCII letter, digit or underscore beside it) and only criteria whose kind is in
  `NON_CODE_KINDS` is dropped, whatever its severity. A finding whose `restates` names an earlier finding
  (`<step>:<n>`) names no criterion, and an id declared with two kinds has no kind, so both are kept. The four
  review graders above (the tallies and `direct-settled`) grade as if it were absent, and their `drops` lists each
  one as `<step>:<place>`.
- `verify-fixed`: a verify fix reply -> unrelated (a test and its evidence), not-done or done.
- `verify-narrowing`: the fix review (read by the suffixes `.findings`, `.whitespace_insignificant` and
  `.whitespace_evidence`, so a second ask of the review is graded the same), the round and the fix's range -> unusable (a finding that is not minor
  and names neither a file nor a failing input), findings, rerun-failed-only or rerun-all (a rerun of only the
  failing ids needs every condition, else all).
- `lane-rule`: the issue step's body, marker and lane paths -> direct or
  standard, by `lane_rule.choose`, with an unknown marker read as marked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from agent_tools.delivery import lane_rule


NON_CODE_KINDS: tuple[str, ...] = ("evidence", "human", "note")


def _no_drops(results: Mapping[str, object]) -> tuple[dict, ...]:
    return ()


@dataclass(frozen=True)
class Grader:
    outcomes: tuple[str, ...]
    grade: Callable[[Mapping[str, object]], str]
    drops: Callable[[Mapping[str, object]], tuple[dict, ...]] = _no_drops


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
    """Each criterion id and its kind; an id declared with two kinds has none, so its findings are kept."""
    if not isinstance(acceptance, list):
        return {}
    kinds: dict[str, object] = {}
    for c in acceptance:
        if isinstance(c, Mapping) and isinstance(c.get("id"), str) and c["id"].strip():
            kinds[c["id"]] = c.get("kind") if kinds.setdefault(c["id"], c.get("kind")) == c.get("kind") else None
    return kinds


def _named(finding: Mapping[str, object], kinds: Mapping[str, object]) -> list[str]:
    """The criteria a finding is about: those its `restates` or `summary` names, none when it restates a finding."""
    restates = finding.get("restates")
    if isinstance(restates, str) and _restates_a_finding(restates):
        return []
    texts = [finding[m] for m in ("restates", "summary") if isinstance(finding.get(m), str)]
    return [cid for cid in kinds if any(_names(text, cid) for text in texts)]


def _drops(finding: Mapping[str, object], kinds: Mapping[str, object]) -> bool:
    named = _named(finding, kinds)
    return bool(named) and all(kinds[cid] in NON_CODE_KINDS for cid in named)


def dropped(results: Mapping[str, object]) -> tuple[dict, ...]:
    """Each finding naming only criteria of other kinds than code, as `<step>:<place>` and the criteria named."""
    kinds = _kinds(results.get("implement.acceptance"))
    found = []
    for path, value in results.items():
        if not path.endswith(".findings") or not isinstance(value, list):
            continue
        for place, finding in enumerate(value, 1):
            if isinstance(finding, Mapping) and _drops(finding, kinds):
                found.append({"finding": f"{path[:-len('.findings')]}:{place}", "criteria": _named(finding, kinds)})
    return tuple(found)


def _kept(results: Mapping[str, object]) -> dict[str, object]:
    """A copy of `results` whose `.findings` lists omit the findings `dropped` lists."""
    kinds = _kinds(results.get("implement.acceptance"))
    return {path: [f for f in value if not (isinstance(f, Mapping) and _drops(f, kinds))]
            if path.endswith(".findings") and isinstance(value, list) else value
            for path, value in results.items()}


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
    results = _kept(results)
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
    results = _kept(results)
    verdict, findings = _suffixed(results, ".verdict"), _suffixed(results, ".findings")
    if _absent(verdict, findings):
        return "findings"
    if _unusable(findings):
        return "unusable"
    return "findings" if _blocking(findings) else "clean"


def _plan_settled(results: Mapping[str, object]) -> str:
    """`direct-settled`, except that a `findings` verdict naming no finding at all is `unusable`, never `clean`."""
    if _suffixed(results, ".verdict") == "findings" and _suffixed(results, ".findings") == []:
        return "unusable"
    return _direct_settled(results)


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
            and all(isinstance(p, str) and p in {x for n in named for x in n} for p in paths)
            and _suffixed(results, ".whitespace_insignificant") is True
            and not _blank(_suffixed(results, ".whitespace_evidence")))


def _verify_narrowing(results: Mapping[str, object]) -> str:
    findings = _suffixed(results, ".findings")
    if not isinstance(findings, list) or any(
            not isinstance(f, Mapping) or f.get("severity") != "minor" for f in findings):
        return "unusable" if _unusable(findings) else "findings"
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
        _direct_lite_tally, drops=dropped),
    "direct-escalated-tally": Grader(
        ("unusable", "codex-unavailable", "findings", "clean"), _direct_escalated_tally, drops=dropped),
    "direct-full-tally": Grader(
        ("no-review", "unusable", "codex-unavailable", "findings", "clean"), _direct_full_tally, drops=dropped),
    "direct-fixed": Grader(("done", "not-done"), _direct_fixed),
    "direct-settled": Grader(("unusable", "findings", "clean"), _direct_settled, drops=dropped),
    "plan-settled": Grader(("unusable", "findings", "clean"), _plan_settled),
    "verify-fixed": Grader(("unrelated", "not-done", "done"), _verify_fixed),
    "verify-narrowing": Grader(("unusable", "findings", "rerun-failed-only", "rerun-all"), _verify_narrowing),
    "lane-rule": Grader(("direct", "standard"), _lane_rule),
}
