"""Cleanup issues for the violations a rule already holds (#1462).

The never-rise check (`agent_tools.delivery.never_rise`) stops a branch from
adding violations; it does not clear the ones the project already has. This
module turns them into work: one open cleanup issue at a time, for the rule with
the fewest violations, listing whole files.

Rules. `RULES` is one `CleanupRule` per never-rise enforcer: the enforcer, the
batch (the most violations one issue lists) and the guidance that tells an
implementer what to change. A test pins `RULES` to the never-rise enforcers.

Counts. `counts` reads every rule's violations from a `Snapshot` through
`never_rise.violations`, in the order of the rules, a rule at zero present with
an empty list. An enforcer that emits another rule's violation raises
`ValueError`, which `counts` lets propagate.

Selection. `select` takes the rule with the smallest count above zero; equal
counts take the earlier rule. No rule above zero selects none.

Listing. `listing` groups violations by file and orders the files by their
violation count, then by their last violation's line, then by path, so the
smallest file comes first; within a file the violations are ordered by line. The
first file is always listed whole, even when it alone has more violations than
the batch; each later file is listed whole while the running total stays within
the batch, and the listing stops at the first file that does not fit. A file is
never cut, so a file listed is a file cleared.

Marker. A cleanup issue carries the line `<!-- agent:cleanup v1 rule=<id> -->`
in its body. `is_cleanup` is true when any line of the body, after trailing
spaces, tabs and carriage returns are dropped, is exactly that marker; the same
text inside a longer line, another version or another kind is no marker, so a
hand-filed issue is never taken for a cleanup issue.

Body. `draft` renders the title `Clear <n> of the <count> violations of rule
<id>` and a body of the marker line, a summary line naming the count and the
revision, the guidance, the listed violations in a `text` block, one per line as
`Violation.text` renders them, and one acceptance criterion. The criterion
bounds both promises: the rule has at most `count - n` violations, and none is
in a listed file, measured by `cleanup-issue violations --repo-root <checkout>
--rule <id>` at the merge commit.

Run. `run` lists the open issues first. Any open cleanup issue answers
`Outcome("open", <lowest issue number>, None)` and files nothing. Otherwise, with
no rule above zero it answers `Outcome("clean", None, None)` and files nothing;
else it files exactly one issue for the selected rule and answers
`Outcome("filed", <issue number>, <rule id>)`.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from agent_tools.delivery import never_rise, size_lint
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation

MARKER = re.compile(r"<!-- agent:cleanup v1 rule=(?P<rule>[A-Za-z0-9._:/@+-]+) -->")
B17_GUIDANCE = ("Split each listed file so that no file is over 1,500 lines, without changing "
                "behaviour. Move code with its history (B9) and keep every test.")


@dataclass(frozen=True)
class CleanupRule:
    enforcer: Enforcer
    batch: int
    guidance: str


RULES: tuple[CleanupRule, ...] = (CleanupRule(size_lint.ENFORCER, 1, B17_GUIDANCE),)


class Issue(NamedTuple):
    number: int
    body: str


class Tracker(Protocol):
    def open_issues(self) -> list[Issue]: ...

    def create(self, title: str, body: str) -> int: ...


class Draft(NamedTuple):
    rule: str
    count: int
    listed: tuple[Violation, ...]
    title: str
    body: str


class Outcome(NamedTuple):
    action: str
    issue: int | None
    rule: str | None


def counts(snapshot: Snapshot, rules: Sequence[CleanupRule] = RULES) -> dict[str, list[Violation]]:
    return {rule.enforcer.rule: never_rise.violations(rule.enforcer, snapshot) for rule in rules}


def is_cleanup(body: str) -> bool:
    return any(MARKER.fullmatch(line.rstrip(" \r\t")) for line in body.splitlines())


def open_cleanup(issues: Iterable[Issue]) -> list[int]:
    return sorted(issue.number for issue in issues if is_cleanup(issue.body))


def select(found: Mapping[str, Sequence[Violation]],
           rules: Sequence[CleanupRule] = RULES) -> CleanupRule | None:
    chosen = None
    for rule in rules:
        count = len(found[rule.enforcer.rule])
        if count and (chosen is None or count < len(found[chosen.enforcer.rule])):
            chosen = rule
    return chosen


def listing(violations: Sequence[Violation], batch: int) -> tuple[Violation, ...]:
    groups: dict[str, list[Violation]] = defaultdict(list)
    for violation in violations:
        groups[violation.path].append(violation)
    files = sorted(
        ((path, sorted(group, key=lambda v: v.line)) for path, group in groups.items()),
        key=lambda item: (len(item[1]), max(v.line for v in item[1]), item[0]))
    listed: list[Violation] = []
    for path, group in files:
        if listed and len(listed) + len(group) > batch:
            break
        listed.extend(group)
    return tuple(listed)


def draft(rule: CleanupRule, violations: Sequence[Violation], revision: str) -> Draft:
    rule_id = rule.enforcer.rule
    count = len(violations)
    listed = listing(violations, rule.batch)
    n = len(listed)
    title = f"Clear {n} of the {count} violations of rule {rule_id}"
    body = (f"<!-- agent:cleanup v1 rule={rule_id} -->\n"
            f"Rule {rule_id} has {count} violations at {revision}. This issue clears {n} of them.\n"
            "\n"
            "## What to change\n"
            "\n"
            f"{rule.guidance}\n"
            "\n"
            "## Violations\n"
            "\n"
            "```text\n"
            + "".join(f"{v.text()}\n" for v in listed) +
            "```\n"
            "\n"
            "## Acceptance criteria\n"
            "\n"
            f"- [ ] [code] Rule {rule_id} has at most {count - n} violations and none in the listed files"
            f" — measured: `cleanup-issue violations --repo-root <checkout> --rule {rule_id}`"
            f" at the merge commit prints at most {count - n} lines and no line naming a listed file\n")
    return Draft(rule_id, count, listed, title, body)


def run(tracker: Tracker, snapshot: Snapshot, rules: Sequence[CleanupRule] = RULES) -> Outcome:
    open_numbers = open_cleanup(tracker.open_issues())
    if open_numbers:
        return Outcome("open", open_numbers[0], None)
    found = counts(snapshot, rules)
    rule = select(found, rules)
    if rule is None:
        return Outcome("clean", None, None)
    issue = draft(rule, found[rule.enforcer.rule], snapshot.revision)
    return Outcome("filed", tracker.create(issue.title, issue.body), issue.rule)
