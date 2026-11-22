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

Tracker. `GitHubTracker(slug)` lists the open issues of `<owner>/<name>` through
`agent_tools.system.forge_api.api_pages` and files through
`forge_api.create_issue`, with no label. It reads every page before it decides
anything, keeps an item that is no pull request and has a trusted author, and
raises `ForgeError("payload_invalid", ...)` for a page that is not a list of
objects, a kept item whose number is not an integer or whose body is neither text
nor null (a null body reads as empty). An author is trusted (`trusted`) when the
login is `FILER`, the account the workflow token files as, or the author
association is one of `TRUSTED` (`OWNER`, `MEMBER`); a marker in an issue by
anyone else is invisible to `file` and `open`. The command reads no environment
token: `forge_api` drops `GITHUB_TOKEN` and `GH_TOKEN`, so `gh` answers from its
stored credential alone.

Command. `cleanup-issue <subcommand>`, also `python3 -m
agent_tools.delivery.cleanup_issue`:

- `file --repo-root <absolute dir> --repo <owner/name> [--revision HEAD]` runs
  `run` on the snapshot at the revision and prints one JSON line
  `{"action": ..., "issue": ..., "rule": ...}`; it exits 0. It never asks,
  labels, comments or closes anything.
- `counts --repo-root <absolute dir> [--revision HEAD]` prints `<rule> <count>`
  per rule, in the order of `RULES`; it exits 0.
- `violations --repo-root <absolute dir> --rule <id> [--revision HEAD]` prints
  the `Violation.text` of each violation of that rule, one per line in the
  enforcer's order; it exits 0. It is the measurement a filed issue's criterion
  names.
- `open --repo <owner/name>` prints `{"open": [<numbers ascending>]}` of the open
  cleanup issues by trusted authors; it exits 0 when exactly one is open and 1
  for none or several.

Every failure exits 2 with one line `cleanup-issue: <reason>` on stderr and
nothing on stdout: a relative root, a root that is not a directory, a root below
its repository's top level, a revision that does not resolve or a snapshot that
cannot be read, a `--rule` that is not in `RULES`, a `--repo` that is not
`<owner>/<name>`, and any `ForgeError`; after a failed or malformed listing no
issue is created. A usage error keeps argparse's exit 2.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Protocol

from agent_tools.delivery import never_rise, size_lint
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation
from agent_tools.system import forge_api

COMMAND = "cleanup-issue"
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
FILER = "github-actions[bot]"
TRUSTED: tuple[str, ...] = ("OWNER", "MEMBER")
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


def trusted(item: Mapping) -> bool:
    user = item.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return login == FILER or item.get("author_association") in TRUSTED


class GitHubTracker:
    def __init__(self, slug: str) -> None:
        self.slug = slug

    def open_issues(self) -> list[Issue]:
        pages = forge_api.api_pages(f"repos/{self.slug}/issues?state=open&per_page=100")
        if not all(isinstance(page, list) and all(isinstance(item, dict) for item in page)
                   for page in pages):
            raise forge_api.ForgeError("payload_invalid", "issues are not an array of objects")
        issues = []
        for page in pages:
            for item in page:
                if "pull_request" in item or not trusted(item):
                    continue
                number, body = item.get("number"), item.get("body")
                if isinstance(number, bool) or not isinstance(number, int):
                    raise forge_api.ForgeError("payload_invalid", "an issue has no number")
                if body is not None and not isinstance(body, str):
                    raise forge_api.ForgeError("payload_invalid", f"issue {number} has no text body")
                issues.append(Issue(number, body or ""))
        return issues

    def create(self, title: str, body: str) -> int:
        return forge_api.create_issue(self.slug, title, body)


class Refusal(Exception):
    pass


def snapshot_at(args: argparse.Namespace) -> Snapshot:
    root = Path(args.repo_root)
    if not root.is_absolute():
        raise Refusal(f"--repo-root must be absolute: {root}")
    if not root.is_dir():
        raise Refusal(f"not a directory: {root}")
    if never_rise.in_subdirectory(root, timeout=None):
        raise Refusal(f"--repo-root is not the repository top level: {root}")
    sha = never_rise.resolve_commit(root, args.revision, timeout=None)
    snapshot = never_rise.read_snapshot(root, sha, timeout=None) if sha else None
    if snapshot is None:
        raise Refusal(f"cannot read {args.revision} in {root}")
    return snapshot


def tracker_for(args: argparse.Namespace) -> GitHubTracker:
    if not SLUG.fullmatch(args.repo):
        raise Refusal(f"--repo is not <owner>/<name>: {args.repo}")
    return GitHubTracker(args.repo)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog=COMMAND)
    commands = top.add_subparsers(dest="command", required=True)
    for name, wants_root, wants_repo in (("file", True, True), ("counts", True, False),
                                         ("violations", True, False), ("open", False, True)):
        sub = commands.add_parser(name)
        if wants_root:
            sub.add_argument("--repo-root", required=True)
            sub.add_argument("--revision", default="HEAD")
        if wants_repo:
            sub.add_argument("--repo", required=True)
        if name == "violations":
            sub.add_argument("--rule", required=True)
    return top


def execute(args: argparse.Namespace) -> tuple[int, list[str]]:
    if args.command == "open":
        numbers = open_cleanup(tracker_for(args).open_issues())
        return (0 if len(numbers) == 1 else 1), [json.dumps({"open": numbers})]
    if args.command == "violations":
        if args.rule not in {rule.enforcer.rule for rule in RULES}:
            raise Refusal(f"unknown rule: {args.rule}")
        return 0, [v.text() for v in counts(snapshot_at(args))[args.rule]]
    tracker = tracker_for(args) if args.command == "file" else None
    snapshot = snapshot_at(args)
    if tracker is None:
        return 0, [f"{rule} {len(found)}" for rule, found in counts(snapshot).items()]
    outcome = run(tracker, snapshot)
    return 0, [json.dumps({"action": outcome.action, "issue": outcome.issue, "rule": outcome.rule})]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        code, lines = execute(args)
    except Refusal as refusal:
        print(f"{COMMAND}: {refusal}", file=sys.stderr)
        return 2
    except forge_api.ForgeError as error:
        print(f"{COMMAND}: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
