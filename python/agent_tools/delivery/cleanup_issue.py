"""Cleanup issues for the violations a rule already holds (#1462).

The never-rise check (`agent_tools.delivery.never_rise`) stops a branch from
adding violations; it does not clear the ones the project already has. This
module turns them into work: one open cleanup issue at a time, for the rule with
the fewest violations, listing whole files.

Rules. `RULES` is one `CleanupRule` per never-rise enforcer: the enforcer, the
batch (the most violations one issue lists) and the guidance that tells an
implementer what to change. A test pins `RULES` to the never-rise enforcers.

Counts. `counts` reads every rule's violations from a `Snapshot` through
`never_rise.counted`, the number the never-rise gate compares (ADR-project-contract-019):
the findings a reasoned suppression leaves in place, then the violations of bare markers,
in the order of the rules, a rule at zero present with an empty list. An enforcer that emits another rule's violation raises
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
in its body, and a fix change the line `<!-- agent:cleanup-fix v1 rule=<id> -->`;
`forge_markers.body_markers` parses both. `is_cleanup` and `is_fix_change` are
true when any line of the body, after trailing spaces, tabs and carriage returns
are dropped, is exactly that marker with the one field `rule`; the same text
inside a longer line, another version, another kind or with another field is no
marker, so a hand-filed issue is never taken for a cleanup issue.

Body. `draft` renders the title `Clear <n> of the <count> violations of rule
<id>` and a body of the marker line, a summary line naming the count and the
revision, the guidance, the listed violations in a `text` block, one per line as
`Violation.text` renders them, and one acceptance criterion. The criterion
bounds both promises: the rule has at most `count - n` violations, and none is
in a listed file, measured by `cleanup-issue violations --repo-root <checkout>
--rule <id>` at the merge commit.

Fix change. `fix_draft` renders a fix change for a rule whose enforcer has an autofix.
For rule `R`, `count` violations, `fix.fixed` of them fixed and `k` changed files, the
branch is `cleanup-fix-<R lowercased, each run of other characters one "-", trimmed>-<the
first 12 characters of the revision>`, the title `Fix <fixed> of the <count> violations
of rule <R> with its autofix`, and the body the marker line, a summary line naming the
count, the revision and `k`, a `## Count` list (`- Before: <count>`, `- After: <count -
fixed>`) and a `## Files` `text` block of the sorted changed paths, each through
`never_rise.escape_path`.

Run. `run` lists the open issues and the open changes first. Any open cleanup issue or
fix change answers `Outcome("open", <lowest number>, None)` and opens and files nothing.
Otherwise, with no rule above zero it answers `Outcome("clean", None, None)`; else it
asks the tracker two questions: `trusted_writer` (an issue by an account that `trusted`
would drop is invisible to the next run, so a filer that would not be trusted files
nothing and `run` raises `Refusal`) and `current` (the revision is still the tip of the
integration branch; a delayed run for an older commit answers `Outcome("stale", None,
None)`, so completed work is never filed again). For the selected rule it then drafts
the issue and, when the enforcer has an autofix, runs it on exactly the listed files
(a changed file outside them raises `ValueError`). Changed files with a tracker whose
pull requests start no checks answer `Outcome("deferred", None, <rule id>)`; otherwise
`open_change` opens the fix change and answers `Outcome("opened", <pull number>, <rule
id>)`, or `Outcome("taken", None, <rule id>)` when another writer holds its branch.
Without changed files, `fix_only` answers `Outcome("unfixable", None, <rule id>)` and
files nothing; else the issue is filed and the answer is `Outcome("filed", <issue
number>, <rule id>)`.

Tracker. `GitHubTracker(slug, branch)` reads the open items of `<owner>/<name>` once, through
`agent_tools.system.forge_api.api_pages`, and caches them on the instance: `open_issues` are the
items that are no pull request and `open_changes` the pull requests. It reads every page before it
decides anything, keeps an item whose author is trusted, and raises `ForgeError("payload_invalid",
...)` for a page that is not a list of objects, a kept item (a pull request included) whose number
is not an integer, whose body is absent or is neither text nor null (a null body reads as empty;
an absent one is an incomplete listing, and an item whose body is unknown could hold a marker). An
author is trusted (`trusted`) when the login is `FILER`, the account the workflow token files as,
or the author association is one of `TRUSTED` (`OWNER`, `MEMBER`); a marker by anyone else is
invisible to `file`, `fix` and `open`, a fix marker on a pull request included. `create` files
through `forge_api.create_issue`, with no label. The writer is trusted (`trusted_writer`) when
`GET user` answers 403 (the workflow token, which files as `FILER`), or answers `FILER`, the owner
of a user-owned repository, or an active member of the owning organization. `starts_checks` is
false when `GET user` answers 403 or `FILER`, the accounts whose pull requests start no workflow
run, and true for any other login. `open_change` opens a fix change through the API alone: it
refuses without a branch, creates the ref `refs/heads/<branch>` at the revision
(`forge_markers.create_ref`; a ref that exists is `taken`, answered `None`, and nothing more is
written), then `forge_api.commit_files` appends one commit of the changed files and
`forge_api.create_pull` opens the pull request against the integration branch. The command reads
no environment token: `forge_api` drops `GITHUB_TOKEN` and `GH_TOKEN`, so `gh` answers from its
stored credential alone.

Command. `cleanup-issue <subcommand>`, also `python3 -m
agent_tools.delivery.cleanup_issue`:

- `file --repo-root <absolute dir> --repo <owner/name> [--revision HEAD]
  [--branch <name>]` runs `run` on the snapshot at the revision (with `--branch`,
  `current` is true only while the revision is that branch's tip on the forge;
  without it, always) and prints one JSON line
  `{"action": ..., "issue": ..., "rule": ...}`; it exits 0 for every outcome. Its `action`
  is `open`, `clean`, `stale`, `filed`, `opened`, `taken` or `deferred`; a `deferred` one
  also writes `cleanup-issue: rule <id> needs a fix change; the verify-pending pass opens
  it from a host whose pull requests start checks` to stderr. It never asks, labels,
  comments or closes anything.
- `fix --project <id> --repo <owner/name> --branch <name>` is the host run of the same
  pick, for a host whose pull requests start checks. The root is the `root` of the
  registry entry (`agent_platform.read_registry`) whose `project_id` is `<id>`; it must
  pass the checks of `--repo-root`. The command fetches `refs/heads/<name>` from `origin`
  with no token variable (120 seconds), reads the branch's tip on the forge, runs `run`
  with `fix_only` on the snapshot at that tip and prints the same JSON line, exit 0; an
  `unfixable` pick files nothing. It makes no forge call before the registry, the root
  and the fetch have passed.
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
nothing on stdout: an enforcer that cannot judge (`EnforcerFailed`, such as `ruff-lint:
ruff_unavailable` when `AGENT_PLATFORM_TOOLS` names no pinned Ruff), a relative root, a root that is not a directory, a root below
its repository's top level, a revision that does not resolve or a snapshot that
cannot be read, a `--rule` that is not in `RULES`, a `--repo` that is not
`<owner>/<name>`, a `--project` the registry does not hold, a fetch that fails, a fix change
without `--branch`, a filer that is not trusted, and any `ForgeError`; after a failed or malformed
listing no issue is created. A usage error keeps argparse's exit 2.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Protocol
from urllib.parse import quote

from agent_tools.claims import forge_markers
from agent_tools.delivery import (
    comment_lint, copied_test_lint, never_rise, node_lint, record_lint, ruff_lint,
    size_lint, skipped_test_lint)
from agent_tools.delivery.never_rise import Enforcer, Fix, Snapshot, Violation
from agent_tools.project_contract import agent_platform
from agent_tools.system import forge_api

COMMAND = "cleanup-issue"
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
FILER = "github-actions[bot]"
TRUSTED: tuple[str, ...] = ("OWNER", "MEMBER")
CLEANUP_KIND = "cleanup"
FIX_KIND = "cleanup-fix"
FETCH_TIMEOUT = 120
DEFERRAL_NOTICE = ("rule {rule} needs a fix change; the verify-pending pass opens it from a host "
                   "whose pull requests start checks")
# The wire form of the cleanup marker, kept for reference; `forge_markers.body_markers` parses it.
MARKER = re.compile(r"<!-- agent:cleanup v1 rule=(?P<rule>[A-Za-z0-9._:/@+-]+) -->")
B17_GUIDANCE = ("Split each listed file so that no file is over 1,500 lines, without changing "
                "behaviour. Move code with its history (B9) and keep every test.")


@dataclass(frozen=True)
class CleanupRule:
    enforcer: Enforcer
    batch: int
    guidance: str


TEST_BATCH = 5
TEST_GUIDANCE = {
    skipped_test_lint.RULE_ID: "Delete each listed skipped or disabled test, or make it run and "
                               "pass, so that no test is skipped, disabled, focused or excluded.",
    copied_test_lint.RULE_ID: "Give each listed test's case to the test it copies as data, or "
                              "change it to check something else, so that no two tests share a "
                              "body.",
}

RUFF_BATCH = 10
RUFF_GUIDANCE = {
    "PY6": "Import each name explicitly, one module per statement, above every statement but "
           "the docstring and the `__future__` imports, and only the names the module reads.",
    "PY7": "Compare with `None`, `True` and `False` by `is`, test a type with `isinstance`, "
           "write `not in` and `is not`, catch a named exception, bind a function with `def`, "
           "put one statement on a line and never name anything `l`, `O` or `I`.",
    "PY8": "Make each listed file read and parse: fix the syntax error, or the string "
           "annotation that does not parse.",
    "PY9": "Make each `%` or `str.format` template's placeholders match its arguments, and "
           "write an f-string with no placeholder as a plain string.",
    "PY10": "Make each listed statement do what it reads as: no `assert` or `if` on a tuple, "
            "`==` rather than `is` against a literal, no repeated dict key, `raise "
            "NotImplementedError`, and `break`, `continue`, `return` and `yield` only inside "
            "the construct each needs.",
    "PY11": "Bind every name before it is read, and delete or use each variable or import that "
            "is rebound before a read or assigned and never read.",
    "PY12": "Delete the commented-out code; version control keeps it.",
    "PY13": "Make each suppression name the code of every check it silences and then give, in "
            "the same comment, the reason the line is right as written.",
}

COMMENT_BATCH = 10
COMMENT_GUIDANCE = {
    comment_lint.REFERENCE_RULE: "Reword each listed comment so it names no issue or pull request; "
                                 "say in the comment what the code does or why.",
    comment_lint.LENGTH_RULE: "Cut each listed comment block to at most five lines and each line "
                              "to at most 120 characters, keeping the reason and dropping the "
                              "narration.",
    comment_lint.MARKER_RULE: "Do the work each listed placeholder marker stands for, or delete "
                              "the comment that holds it.",
}

RECORD_BATCH = 5
RECORD_GUIDANCE = {
    record_lint.RECORD_SIZE_RULE: "Cut each listed decision record to at most 1,500 bytes, "
                                  "keeping the decision and the alternative it rejected and "
                                  "dropping the narration.",
    record_lint.RECORD_FORM_RULE: "Rewrite each listed decision record as its title header, an "
                                  "optional `**Formerly:**` line and one paragraph: no section "
                                  "heading, status line, list, quote, fence or second paragraph.",
}

NODE_BATCH = 10
NODE_GUIDANCE = {
    node_lint.PARSE_RULE: "Make each listed program parse as the runtime loads it: fix the syntax "
                          "error, and keep the `export const meta` line.",
    node_lint.UNUSED_RULE: "Delete each listed variable, parameter, label or private member that "
                           "nothing reads, or use it.",
    node_lint.NAMES_RULE: "Declare each listed name once and use it as its kind: define what is "
                          "undeclared, rename a redeclaration and stop assigning to a constant.",
    node_lint.LIKELY_BUG_RULE: "Fix each listed construct ESLint's recommended set calls a likely "
                               "bug, such as unreachable code or a constant condition.",
    node_lint.DIRECTIVE_RULE: "Make each listed suppression name the rules it silences and give "
                              "its reason after ` -- `, or delete it and fix the finding.",
}

# The comment enforcers are built without the tracker repository, so B18 counts only the
# shorthand references here; the never-rise check passes the contract's repository.
RULES: tuple[CleanupRule, ...] = (
    CleanupRule(size_lint.ENFORCER, 1, B17_GUIDANCE),
    *(CleanupRule(enforcer, TEST_BATCH, TEST_GUIDANCE[enforcer.rule])
      for enforcer in (skipped_test_lint.ENFORCER, copied_test_lint.ENFORCER)),
    *(CleanupRule(enforcer, RUFF_BATCH, RUFF_GUIDANCE[enforcer.rule])
      for enforcer in ruff_lint.ENFORCERS),
    *(CleanupRule(enforcer, COMMENT_BATCH, COMMENT_GUIDANCE[enforcer.rule])
      for enforcer in comment_lint.enforcers(None)),
    *(CleanupRule(enforcer, RECORD_BATCH, RECORD_GUIDANCE[enforcer.rule])
      for enforcer in record_lint.RECORD_ENFORCERS),
    *(CleanupRule(enforcer, NODE_BATCH, NODE_GUIDANCE[enforcer.rule])
      for enforcer in node_lint.enforcers()),
)


class Refusal(Exception):
    pass


class Issue(NamedTuple):
    number: int
    body: str


class Tracker(Protocol):
    def open_issues(self) -> list[Issue]: ...

    def open_changes(self) -> list[Issue]: ...

    def starts_checks(self) -> bool: ...

    def open_change(self, branch: str, revision: str, title: str, body: str,
                    files: Mapping[str, bytes]) -> int | None: ...

    def trusted_writer(self) -> bool: ...

    def current(self, revision: str) -> bool: ...

    def create(self, title: str, body: str) -> int: ...


class Draft(NamedTuple):
    rule: str
    count: int
    listed: tuple[Violation, ...]
    title: str
    body: str


class FixDraft(NamedTuple):
    rule: str
    count: int
    after: int
    branch: str
    title: str
    body: str


class Outcome(NamedTuple):
    action: str
    issue: int | None
    rule: str | None


def counts(snapshot: Snapshot, rules: Sequence[CleanupRule] = RULES) -> dict[str, list[Violation]]:
    found: dict[str, list[Violation]] = {}
    for rule in rules:
        kept, marked = never_rise.counted(rule.enforcer, snapshot)
        found[rule.enforcer.rule] = [*kept, *marked]
    return found


def _has_rule_marker(body: str, kind: str) -> bool:
    return any(set(fields) == {"rule"} for fields in forge_markers.body_markers(body, kind))


def is_cleanup(body: str) -> bool:
    return _has_rule_marker(body, CLEANUP_KIND)


def is_fix_change(body: str) -> bool:
    return _has_rule_marker(body, FIX_KIND)


def open_cleanup(issues: Iterable[Issue]) -> list[int]:
    return sorted(issue.number for issue in issues if is_cleanup(issue.body))


def open_fix_changes(changes: Iterable[Issue]) -> list[int]:
    return sorted(change.number for change in changes if is_fix_change(change.body))


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


def fix_draft(rule: CleanupRule, count: int, fix: Fix, revision: str) -> FixDraft:
    rule_id = rule.enforcer.rule
    after = count - fix.fixed
    slug = re.sub(r"[^a-z0-9]+", "-", rule_id.lower()).strip("-")
    paths = "".join(f"{never_rise.escape_path(path)}\n" for path in sorted(fix.changed))
    body = (f"<!-- agent:cleanup-fix v1 rule={rule_id} -->\n"
            f"Rule {rule_id} has {count} violations at {revision}. This change holds only what the "
            f"rule's autofix wrote to {len(fix.changed)} files.\n"
            "\n"
            "## Count\n"
            "\n"
            f"- Before: {count}\n"
            f"- After: {after}\n"
            "\n"
            "## Files\n"
            "\n"
            "```text\n"
            f"{paths}"
            "```\n")
    return FixDraft(rule_id, count, after, f"cleanup-fix-{slug}-{revision[:12]}",
                    f"Fix {fix.fixed} of the {count} violations of rule {rule_id} with its autofix",
                    body)


def run(tracker: Tracker, snapshot: Snapshot, rules: Sequence[CleanupRule] = RULES,
        fix_only: bool = False) -> Outcome:
    held = sorted(open_cleanup(tracker.open_issues()) + open_fix_changes(tracker.open_changes()))
    if held:
        return Outcome("open", held[0], None)
    found = counts(snapshot, rules)
    rule = select(found, rules)
    if rule is None:
        return Outcome("clean", None, None)
    if not tracker.trusted_writer():
        raise Refusal("the filer is not a trusted author: its issue would be invisible to the next run")
    if not tracker.current(snapshot.revision):
        return Outcome("stale", None, None)
    issue = draft(rule, found[rule.enforcer.rule], snapshot.revision)
    if rule.enforcer.fix is not None:
        paths = tuple(dict.fromkeys(v.path for v in issue.listed))
        result = rule.enforcer.fix(snapshot, paths)
        if not set(result.changed) <= set(paths):
            raise ValueError(f"the autofix of {issue.rule} changed files outside the listing")
        if result.changed:
            if not tracker.starts_checks():
                return Outcome("deferred", None, issue.rule)
            change = fix_draft(rule, issue.count, result, snapshot.revision)
            number = tracker.open_change(change.branch, snapshot.revision, change.title,
                                         change.body, result.changed)
            return Outcome("taken" if number is None else "opened", number, issue.rule)
    if fix_only:
        return Outcome("unfixable", None, issue.rule)
    return Outcome("filed", tracker.create(issue.title, issue.body), issue.rule)


def trusted(item: Mapping) -> bool:
    return forge_markers.trusted_author(item, (FILER,), TRUSTED)


class GitHubTracker:
    def __init__(self, slug: str, branch: str | None = None) -> None:
        self.slug = slug
        self.branch = branch
        self._kept: list[tuple[bool, Issue]] | None = None

    def trusted_writer(self) -> bool:
        user = forge_api.api_get("user", allow=(403,))
        if user is None:
            return True
        login = user.get("login") if isinstance(user, dict) else None
        repository = forge_api.api_get(f"repos/{self.slug}")
        owner = repository.get("owner") if isinstance(repository, dict) else None
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        if not (isinstance(login, str) and login and isinstance(owner_login, str) and owner_login):
            raise forge_api.ForgeError("payload_invalid", "no authenticated login or repository owner")
        if login == FILER:
            return True
        if owner.get("type") != "Organization":
            return login.lower() == owner_login.lower()
        membership = forge_api.api_get(
            f"user/memberships/orgs/{quote(owner_login, safe='')}", allow=(403, 404))
        return isinstance(membership, dict) and membership.get("state") == "active"

    def starts_checks(self) -> bool:
        user = forge_api.api_get("user", allow=(403,))
        if user is None:
            return False
        login = user.get("login") if isinstance(user, dict) else None
        if not (isinstance(login, str) and login):
            raise forge_api.ForgeError("payload_invalid", "no authenticated login")
        return login != FILER

    def tip(self) -> str:
        if self.branch is None:
            raise Refusal("the tip of the integration branch needs --branch")
        ref = forge_api.api_get(f"repos/{self.slug}/git/ref/heads/{quote(self.branch, safe='/')}")
        target = ref.get("object") if isinstance(ref, dict) else None
        sha = target.get("sha") if isinstance(target, dict) else None
        if not isinstance(sha, str):
            raise forge_api.ForgeError("payload_invalid", f"branch {self.branch} has no commit")
        return sha

    def current(self, revision: str) -> bool:
        return self.branch is None or self.tip() == revision

    def _items(self) -> list[tuple[bool, Issue]]:
        if self._kept is None:
            pages = forge_api.api_pages(f"repos/{self.slug}/issues?state=open&per_page=100")
            if not all(isinstance(page, list) and all(isinstance(item, dict) for item in page)
                       for page in pages):
                raise forge_api.ForgeError("payload_invalid", "issues are not an array of objects")
            kept = []
            for page in pages:
                for item in page:
                    if not trusted(item):
                        continue
                    number, body = item.get("number"), item.get("body")
                    if isinstance(number, bool) or not isinstance(number, int):
                        raise forge_api.ForgeError("payload_invalid", "an issue has no number")
                    if "body" not in item:
                        raise forge_api.ForgeError("payload_invalid", f"issue {number} has no body field")
                    if body is not None and not isinstance(body, str):
                        raise forge_api.ForgeError("payload_invalid", f"issue {number} has no text body")
                    kept.append(("pull_request" in item, Issue(number, body or "")))
            self._kept = kept
        return self._kept

    def open_issues(self) -> list[Issue]:
        return [issue for is_change, issue in self._items() if not is_change]

    def open_changes(self) -> list[Issue]:
        return [issue for is_change, issue in self._items() if is_change]

    def open_change(self, branch: str, revision: str, title: str, body: str,
                    files: Mapping[str, bytes]) -> int | None:
        if self.branch is None:
            raise Refusal("a fix change needs --branch, the integration branch it targets")
        if not forge_markers.create_ref(self.slug, f"refs/heads/{branch}", revision):
            return None
        forge_api.commit_files(self.slug, branch, revision, title, files)
        return forge_api.create_pull(self.slug, title, body, branch, self.branch)

    def create(self, title: str, body: str) -> int:
        return forge_api.create_issue(self.slug, title, body)


def checked_root(path: str) -> Path:
    root = Path(path)
    if not root.is_absolute():
        raise Refusal(f"--repo-root must be absolute: {root}")
    if not root.is_dir():
        raise Refusal(f"not a directory: {root}")
    if never_rise.in_subdirectory(root, timeout=None):
        raise Refusal(f"--repo-root is not the repository top level: {root}")
    return root


def snapshot_in(root: Path, revision: str) -> Snapshot:
    sha = never_rise.resolve_commit(root, revision, timeout=None)
    snapshot = never_rise.read_snapshot(root, sha, timeout=None) if sha else None
    if snapshot is None:
        raise Refusal(f"cannot read {revision} in {root}")
    return snapshot


def snapshot_at(args: argparse.Namespace) -> Snapshot:
    return snapshot_in(checked_root(args.repo_root), args.revision)


def registered_root(project: str) -> str:
    try:
        entries = agent_platform.read_registry()
    except agent_platform.PlatformManifestError as error:
        raise Refusal(f"the fleet registry is refused: {error.repair_id}") from None
    for entry in entries:
        if entry.get("project_id") == project:
            return entry["root"]
    raise Refusal(f"project not registered: {project}")


def fetch_branch(root: Path, branch: str) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "fetch", "--quiet", "--no-tags", "origin", f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=FETCH_TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except (subprocess.TimeoutExpired, OSError):
        raise Refusal(f"cannot fetch {branch} in {root}") from None
    if done.returncode:
        raise Refusal(f"cannot fetch {branch} in {root}")


def fix_snapshot(args: argparse.Namespace, tracker: GitHubTracker) -> Snapshot:
    root = checked_root(registered_root(args.project))
    fetch_branch(root, args.branch)
    return snapshot_in(root, tracker.tip())


def tracker_for(args: argparse.Namespace) -> GitHubTracker:
    if not SLUG.fullmatch(args.repo):
        raise Refusal(f"--repo is not <owner>/<name>: {args.repo}")
    return GitHubTracker(args.repo, getattr(args, "branch", None))


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog=COMMAND)
    commands = top.add_subparsers(dest="command", required=True)
    for name, wants_root, wants_repo in (("file", True, True), ("counts", True, False),
                                         ("violations", True, False), ("open", False, True),
                                         ("fix", False, True)):
        sub = commands.add_parser(name)
        if wants_root:
            sub.add_argument("--repo-root", required=True)
            sub.add_argument("--revision", default="HEAD")
        if name == "file":
            sub.add_argument("--branch")
        if name == "fix":
            sub.add_argument("--project", required=True)
            sub.add_argument("--branch", required=True)
        if wants_repo:
            sub.add_argument("--repo", required=True)
        if name == "violations":
            sub.add_argument("--rule", required=True)
    return top


def answer(outcome: Outcome) -> str:
    return json.dumps({"action": outcome.action, "issue": outcome.issue, "rule": outcome.rule})


def execute(args: argparse.Namespace) -> tuple[int, list[str]]:
    if args.command == "open":
        numbers = open_cleanup(tracker_for(args).open_issues())
        return (0 if len(numbers) == 1 else 1), [json.dumps({"open": numbers})]
    if args.command == "fix":
        tracker = tracker_for(args)
        return 0, [answer(run(tracker, fix_snapshot(args, tracker), fix_only=True))]
    if args.command == "violations":
        if args.rule not in {rule.enforcer.rule for rule in RULES}:
            raise Refusal(f"unknown rule: {args.rule}")
        return 0, [v.text() for v in counts(snapshot_at(args))[args.rule]]
    tracker = tracker_for(args) if args.command == "file" else None
    snapshot = snapshot_at(args)
    if tracker is None:
        return 0, [f"{rule} {len(found)}" for rule, found in counts(snapshot).items()]
    outcome = run(tracker, snapshot)
    if outcome.action == "deferred":
        print(f"{COMMAND}: {DEFERRAL_NOTICE.format(rule=outcome.rule)}", file=sys.stderr)
    return 0, [answer(outcome)]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        code, lines = execute(args)
    except Refusal as refusal:
        print(f"{COMMAND}: {refusal}", file=sys.stderr)
        return 2
    except (forge_api.ForgeError, never_rise.EnforcerFailed) as error:
        print(f"{COMMAND}: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
