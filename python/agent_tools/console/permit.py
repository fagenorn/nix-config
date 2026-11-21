"""The permit judge: which Bash commands a manager's session may run (#1377, ADR-console-094).

A manager's session may run exactly three commands, and `judge(command, grant, forge)` decides each
one without touching the network, the clock or a file beyond the injected `Forge` readers and
`os.path.realpath`. Everything it needs about the sprint is in the `Grant`.

The three shapes (D3), judged only over the literal-word grammar of `words`:

1. Merge: `gh pr merge <n> --repo <slug> --<strategy> --match-head-commit <40 lowercase hex>`, then
   `--delete-branch` exactly when `grant.delete_branch` is true. `<n>` is digits with no leading zero.
2. Rerun: `gh run rerun <id> --failed --repo <slug>`.
3. Release: `release transaction run` with `--repo-root`, the four candidate flags `--commit
   --version --title --notes-file`, at least one `--confirm`, and optionally `--profile`; nothing else.

`words(command)` is a small scanner, not `shlex` (which accepts expansions and comments the shell
would act on). It splits on spaces and tabs only. A word is a plain run of `[A-Za-z0-9_./:@%+=,-]`
not beginning with `=`, a single-quoted run, or a double-quoted run without `$`, a backtick, a
backslash or `!`; a quote must open and close a whole word, so none is glued to another character.
It returns the words with their quotes removed, or None for anything else (an operator, a
redirection, an expansion, a glob, a comment, a tilde, a brace, a newline outside quotes).

`mentions(command)` is True when, after deleting every quote and backslash and splitting on
whitespace and on `;|&()<>$`, the backtick, `,`, `[`, `]`, `{` and `}`, some word whose basename is `gh` is followed by `pr
merge` or `run rerun`, or the release verb is reached. The release verb fails closed: it is reached
by the words `transaction run` or `transaction abandon` side by side, however the program is named or
reached (`xargs release`, `r=release; $r ...`, `runpy.run_module(...)`); by a word that is the `release`
program, `release.py` or the module `agent_tools.release.release` (alone, glued to `-m` or assigned,
`r=release`) beside any `$` or backtick anywhere in the command; or by such a word followed later by
`transaction` and a word other than `status` or `preview`. Only the `release` executable's own literal
form is ever granted: every other spelling that `mentions` is `DENY` with `ALONE`, never undecided.

`judge` returns a `Verdict`. A command that `mentions` no granted verb gets `Verdict(None, "", None, {})`
and no reader is called. A command that does is `ALLOW` only in a granted shape and `DENY` otherwise,
never None. The checks run in this order, the first that applies deciding:

- Every verb: the words are None, or do not begin with the verb's own words: `ALONE`.
- Merge: `--admin` anywhere is `ADMIN`; no `grant.slug` or `grant.strategy` is `NOT_GRANTED`; a
  `--repo` (or `-R`) value other than the slug is `OTHER_REPO`; words other than the exact shape are
  `NOT_GRANTED`. Then `forge.read_pr` is read: a head repository other than the slug, a branch that
  carries no issue under `grant.branch_pattern`, or an issue not in `grant.issues` is `NOT_OWN_PR`,
  except that an issue in `grant.others` is `SHARED_ISSUE`; a pull request whose head differs from
  the command's `--match-head-commit` is `STALE_HEAD`. Else `ALLOW` with target `{"pr", "head"}`.
- Rerun: another `--repo` is `OTHER_REPO`; other words are `NOT_GRANTED`. Then `read_run`: an event
  other than `pull_request` is `DEPLOY_RERUN`; another repository or an issue not own is
  `NOT_OWN_RUN` (`SHARED_ISSUE` for an issue in `others`); no pull request among the run's whose
  `read_pr` has the slug as repository and the run's branch is `NOT_OWN_RUN`; that pull request's
  head other than the run's head is `STALE_RUN`; no job that the rerun would run (every job of the
  run's latest attempt, all pages, whose conclusion is not `success`: a failed rerun also runs the
  skipped dependents of a failed job) or one not named by `read_required(slug, base)` is
  `NOT_CHECK_RUN`. Else `ALLOW` with target `{"run", "pr"}`.
- Release: `abandon`, or `--dispose` or `--reference`, is `OWNERS_RELEASE_STEP`. A flag outside the
  six above, a flag with no value, or a repeated flag other than `--confirm` is `NOT_GRANTED`; none
  of the four candidate flags is `RESUME`; some but not all is `NOT_GRANTED`; a `--repo-root` that is
  not an absolute path (the console's working directory is not the manager's) or whose real path
  differs from `grant.root`'s is `WRONG_ROOT`; no `--confirm` is `NOT_GRANTED`; no
  `ReleaseApproval` with the same commit, version and title and exactly the `--confirm` values as
  its confirmations is `NO_CARD`. Else `ALLOW` with target `{"commit", "version"}`.
- A reader raising `ForgeUnreadable` is `DENY` with `FORGE_UNREADABLE`.

`Verdict.payload()` is `{"verb", "decision", "reason", "target"}`; `verb` is `merge`, `rerun` or
`release`. `merge_target(command, grant)` is `{"pr", "head"}` when the command is exactly the granted
merge shape and None otherwise. `NOT_ACTIVE`, `NOT_MANAGER` and `MOVED` are the reasons the console
itself gives (the sprint is not active, the caller is not its manager, the sprint changed between
the first judgement and the second).

`verb_of(command)` is the verb `mentions` found (`merge`, `rerun` or `release`), None when it found none.

`memoized(forge)` caches each reader's result, or the `ForgeUnreadable` it raised, by its arguments;
its `.frozen()` is a `Forge` over the same cache that raises `ForgeUnreadable("not read before")`
for a call not already cached, so the console judges again without a second forge read.

Readers (`read_pr`, `read_run`, `read_required`) read the forge once and raise `ForgeUnreadable` with
a fixed sentence for a failed read or a missing or malformed member; no raw forge text reaches a
reason. `read_run`'s `rerun` is the names of the jobs a failed-job rerun would run, read across every
page of the run's jobs. `read_required` names only the checks a GitHub Actions job can satisfy: a
check bound to another app is left out, even when the legacy `contexts` list repeats its name. `merge_binding(root)` is the project contract's `bindings.vcs.merge` `strategy` and
`delete_branch`, `(None, False)` on any failure.
"""
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from agent_tools.console import deliveries
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api

ALLOW = "allow"
DENY = "deny"

ALONE = "This command runs only alone, spelled exactly as the permitted form, with no operator, expansion or wrapper."
NOT_GRANTED = "The permit grants only the exact merge, rerun and release forms, and this one differs."
ADMIN = "An administrator merge is never permitted."
OTHER_REPO = "The command names another repository than this sprint's project."
NOT_OWN_PR = "Pull request {pr} is not this sprint's own pull request."
SHARED_ISSUE = "Issue {issue} belongs to another open sprint."
DEPLOY_RERUN = "Run {run} is a {event} run, not a pull request check run, so it is not rerun."
NOT_OWN_RUN = "Run {run} is not a check run of this sprint's own pull request."
STALE_RUN = "Run {run} is not at the head of its pull request."
NOT_CHECK_RUN = "Run {run} would rerun a job that is not a required check."
STALE_HEAD = "Pull request {pr} is not at the head the merge names."
NO_CARD = "No release card the owner approved names commit {commit} at version {version} with this preview."
RESUME = "A release resume names no release, so no approved card covers it."
OWNERS_RELEASE_STEP = "Abandoning or disposing of a release is the owner's step."
WRONG_ROOT = "The release runs in another repository root than this project's, or names it by a relative path."
FORGE_UNREADABLE = "The forge could not be read to judge this command: {reason}"
NOT_ACTIVE = "This sprint is not active."
NOT_MANAGER = "Only the sprint's manager session may run this command."
MOVED = "The sprint changed while the command was judged."

MERGE, RERUN, RELEASE = "merge", "rerun", "release"
ACTIONS_APP, ANY_APP = 15368, -1

_PLAIN = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")
_NUMBER = re.compile(r"[1-9][0-9]*")
_SHA = re.compile(r"[0-9a-f]{40}")
_SEPARATORS = " \t"
_DOUBLE_QUOTED_BARRED = "$`\\!"
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_RELEASE_FLAGS = ("--repo-root", "--commit", "--version", "--title", "--notes-file", "--confirm",
                  "--profile")
_CANDIDATE_FLAGS = ("--commit", "--version", "--title", "--notes-file")


class ForgeUnreadable(Exception):
    """A forge read failed or answered a malformed reply; `str(error)` is the fixed reason."""


@dataclass(frozen=True)
class ReleaseApproval:
    commit: str
    version: str
    title: str
    confirmations: frozenset[str]


@dataclass(frozen=True)
class Grant:
    slug: str | None
    root: str
    strategy: str | None
    delete_branch: bool
    branch_pattern: str | None
    issues: frozenset[int]
    others: frozenset[int]
    releases: frozenset[ReleaseApproval]


@dataclass(frozen=True)
class Verdict:
    decision: str | None
    reason: str
    verb: str | None
    target: Mapping[str, object]

    def payload(self) -> dict:
        return {"verb": self.verb, "decision": self.decision, "reason": self.reason,
                "target": dict(self.target)}


def _no_decision() -> Verdict:
    return Verdict(None, "", None, {})


def _allow(verb: str, target: Mapping[str, object]) -> Verdict:
    return Verdict(ALLOW, "", verb, target)


def _deny(verb: str | None, reason: str) -> Verdict:
    return Verdict(DENY, reason, verb, {})


# --- the reads ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Forge:
    read_pr: Callable[[str, int], Mapping]
    read_run: Callable[[str, int], Mapping]
    read_required: Callable[[str, str], frozenset[str]]


@dataclass(frozen=True)
class Memoized(Forge):
    cache: dict = field(repr=False, compare=False)

    def frozen(self) -> Forge:
        def cached(name: str) -> Callable:
            def read(*args):
                return _replay(self.cache.get((name, args)))
            return read
        return Forge(cached("pr"), cached("run"), cached("required"))


def _replay(entry):
    if entry is None:
        raise ForgeUnreadable("not read before")
    ok, value = entry
    if ok:
        return value
    raise ForgeUnreadable(str(value))


def memoized(forge: Forge) -> Memoized:
    cache: dict = {}

    def cached(name: str, read: Callable) -> Callable:
        def call(*args):
            key = (name, args)
            if key not in cache:
                try:
                    cache[key] = (True, read(*args))
                except ForgeUnreadable as error:
                    cache[key] = (False, str(error))
            return _replay(cache[key])
        return call
    return Memoized(cached("pr", forge.read_pr), cached("run", forge.read_run),
                    cached("required", forge.read_required), cache)


def _get(path: str, what: str):
    try:
        return forge_api.api_get(path)
    except forge_api.ForgeError:
        raise ForgeUnreadable(f"{what} could not be read") from None


def _member(mapping, key: str, kind: type, what: str):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise ForgeUnreadable(f"{what} has no readable {key}")
    return value


def read_pr(slug: str, number: int) -> Mapping:
    what = f"pull request {number}"
    pull = _get(f"repos/{slug}/pulls/{number}", what)
    head = _member(pull, "head", dict, what)
    base = _member(pull, "base", dict, what)
    sha = _member(head, "sha", str, what)
    if not _SHA.fullmatch(sha):
        raise ForgeUnreadable(f"{what} has no readable head")
    repo = _member(_member(head, "repo", dict, what), "full_name", str, what)
    return {"branch": _member(head, "ref", str, what), "repo": repo, "head": sha,
            "base": _member(base, "ref", str, what)}


def _pages(path: str, what: str) -> list:
    try:
        return forge_api.api_pages(path)
    except forge_api.ForgeError:
        raise ForgeUnreadable(f"{what} could not be read") from None


def read_run(slug: str, run_id: int) -> Mapping:
    what = f"run {run_id}"
    run = _get(f"repos/{slug}/actions/runs/{run_id}", what)
    pages = _pages(f"repos/{slug}/actions/runs/{run_id}/jobs?per_page=100", what)
    if not pages:
        raise ForgeUnreadable(f"{what} has no readable jobs")
    prs = _member(run, "pull_requests", list, what)
    numbers = [_member(pull, "number", int, what) for pull in prs]
    rerun = []
    for page in pages:
        for job in _member(page, "jobs", list, what):
            name = _member(job, "name", str, what)
            conclusion = job.get("conclusion")
            if conclusion is not None and not isinstance(conclusion, str):
                raise ForgeUnreadable(f"{what} has no readable conclusion")
            if conclusion != "success":
                rerun.append(name)
    return {"event": _member(run, "event", str, what),
            "branch": _member(run, "head_branch", str, what),
            "repo": _member(_member(run, "head_repository", dict, what), "full_name", str, what),
            "head": _member(run, "head_sha", str, what), "prs": numbers, "rerun": rerun}


def read_required(slug: str, base: str) -> frozenset[str]:
    what = f"the required checks of {base}"
    payload = _get(f"repos/{slug}/branches/{base}/protection/required_status_checks", what)
    checks = _member(payload, "checks", list, what)
    contexts = _member(payload, "contexts", list, what)
    found, bound = set(), set()
    for entry in checks:
        context = _member(entry, "context", str, what)
        app = entry.get("app_id")
        if app is not None and (not isinstance(app, int) or isinstance(app, bool)):
            raise ForgeUnreadable(f"{what} has no readable app_id")
        bound.add(context)
        if app in (None, ANY_APP, ACTIONS_APP):
            found.add(context)
    for context in contexts:
        if not isinstance(context, str):
            raise ForgeUnreadable(f"{what} has no readable contexts")
        if context not in bound:
            found.add(context)
    return frozenset(found)


FORGE = Forge(read_pr, read_run, read_required)


def merge_binding(root: str) -> tuple[str | None, bool]:
    try:
        merge = resolve_project.resolve(root)["bindings"]["vcs"]["merge"]
        strategy, delete = merge["strategy"], merge.get("delete_branch")
    except Exception:
        return None, False
    return (strategy, delete is True) if isinstance(strategy, str) else (None, False)


# --- the literal-word grammar ------------------------------------------------------------------------

def words(command: str) -> list[str] | None:
    found: list[str] = []
    i, end = 0, len(command)
    while i < end:
        char = command[i]
        if char in _SEPARATORS:
            i += 1
            continue
        if char in "'\"":
            close = command.find(char, i + 1)
            if close < 0:
                return None
            word = command[i + 1:close]
            if _CONTROL.search(word):
                return None
            if char == '"' and any(bad in word for bad in _DOUBLE_QUOTED_BARRED):
                return None
            i = close + 1
        else:
            match = _PLAIN.match(command, i)
            if match is None or match.group().startswith("="):
                return None
            word, i = match.group(), match.end()
        if i < end and command[i] not in _SEPARATORS:
            return None
        found.append(word)
    return found


_SPLIT = re.compile(r"[\s;|&()<>$`,\[\]{}]+")
_RELEASE_PROGRAMS = ("release", "release.py")
_RELEASE_MODULE = "agent_tools.release.release"
_RELEASE_READS = ("status", "preview")


def _names_release(part: str) -> bool:
    """A word that is the release program, its script or its module, alone, glued to `-m` or assigned (`r=release`)."""
    name = os.path.basename(part.rpartition("=")[2])
    module = part[2:] if part.startswith("-m") else part
    return name in _RELEASE_PROGRAMS or module == _RELEASE_MODULE


def _is_release(command: str, parts: list[str]) -> bool:
    """Fail closed: any spelling that can reach a release run or abandon, however the shell names the program."""
    if any(first == "transaction" and second in ("run", "abandon")
           for first, second in zip(parts, parts[1:])):
        return True
    named = [index for index, part in enumerate(parts) if _names_release(part)]
    if not named:
        return False
    if any(char in command for char in "$`"):
        return True
    after = parts[named[0] + 1:]
    return any(part == "transaction" and following not in _RELEASE_READS
               for part, following in zip(after, after[1:]))


def _verb_of(command: str) -> str | None:
    parts = _SPLIT.split(re.sub(r"['\"\\]", "", command))
    for index, part in enumerate(parts):
        name, rest = os.path.basename(part), parts[index + 1:index + 3]
        if name == "gh" and rest == ["pr", "merge"]:
            return MERGE
        if name == "gh" and rest == ["run", "rerun"]:
            return RERUN
    return RELEASE if _is_release(command, parts) else None


def verb_of(command: str) -> str | None:
    """`merge`, `rerun` or `release` when `mentions(command)`, else None."""
    return _verb_of(command)


def mentions(command: str) -> bool:
    return _verb_of(command) is not None


# --- the judgement ---------------------------------------------------------------------------------------

def _repo_value(parts: list[str]) -> str | None:
    for index, part in enumerate(parts):
        if part in ("--repo", "-R"):
            return parts[index + 1] if index + 1 < len(parts) else ""
        if part.startswith("--repo="):
            return part[len("--repo="):]
    return None


def _merge_shape(parts: list[str], grant: Grant) -> dict | None:
    if grant.slug is None or grant.strategy is None:
        return None
    expected = ["gh", "pr", "merge", None, "--repo", grant.slug, f"--{grant.strategy}",
                "--match-head-commit", None] + (["--delete-branch"] if grant.delete_branch else [])
    if len(parts) != len(expected) or any(
            want is not None and want != part for want, part in zip(expected, parts)):
        return None
    if not _NUMBER.fullmatch(parts[3]) or not _SHA.fullmatch(parts[8]):
        return None
    return {"pr": int(parts[3]), "head": parts[8]}


def merge_target(command: str, grant: Grant) -> dict | None:
    parts = words(command)
    return None if parts is None else _merge_shape(parts, grant)


def _own_issue(grant: Grant, branch: str, refusal: str) -> Verdict | None:
    """The refusal for a branch that is not an own issue's, else None."""
    issue = deliveries.branch_issue(grant.branch_pattern, branch)
    if issue is not None and issue in grant.others:
        return _deny(None, SHARED_ISSUE.format(issue=issue))
    if issue is None or issue not in grant.issues:
        return _deny(None, refusal)
    return None


def _with_verb(verdict: Verdict, verb: str) -> Verdict:
    return Verdict(verdict.decision, verdict.reason, verb, verdict.target)


def _judge_merge(parts: list[str], grant: Grant, forge: Forge) -> Verdict:
    if any(part == "--admin" or part.startswith("--admin=") for part in parts):
        return _deny(MERGE, ADMIN)
    if grant.slug is None or grant.strategy is None:
        return _deny(MERGE, NOT_GRANTED)
    repo = _repo_value(parts)
    if repo is not None and repo != grant.slug:
        return _deny(MERGE, OTHER_REPO)
    target = _merge_shape(parts, grant)
    if target is None:
        return _deny(MERGE, NOT_GRANTED)
    pull = forge.read_pr(grant.slug, target["pr"])
    if pull["repo"] != grant.slug:
        return _deny(MERGE, NOT_OWN_PR.format(pr=target["pr"]))
    refusal = _own_issue(grant, pull["branch"], NOT_OWN_PR.format(pr=target["pr"]))
    if refusal:
        return _with_verb(refusal, MERGE)
    if pull["head"] != target["head"]:
        return _deny(MERGE, STALE_HEAD.format(pr=target["pr"]))
    return _allow(MERGE, target)


def _judge_rerun(parts: list[str], grant: Grant, forge: Forge) -> Verdict:
    repo = _repo_value(parts)
    if grant.slug is not None and repo is not None and repo != grant.slug:
        return _deny(RERUN, OTHER_REPO)
    if (grant.slug is None or len(parts) != 7 or not _NUMBER.fullmatch(parts[3])
            or parts[:3] + parts[4:] != ["gh", "run", "rerun", "--failed", "--repo", grant.slug]):
        return _deny(RERUN, NOT_GRANTED)
    slug, run_id = grant.slug, int(parts[3])
    run = forge.read_run(slug, run_id)
    if run["event"] != "pull_request":
        return _deny(RERUN, DEPLOY_RERUN.format(run=run_id, event=run["event"]))
    not_own = NOT_OWN_RUN.format(run=run_id)
    if run["repo"] != slug:
        return _deny(RERUN, not_own)
    refusal = _own_issue(grant, run["branch"], not_own)
    if refusal:
        return _with_verb(refusal, RERUN)
    for number in run["prs"]:
        pull = forge.read_pr(slug, number)
        if pull["repo"] == slug and pull["branch"] == run["branch"]:
            break
    else:
        return _deny(RERUN, not_own)
    if pull["head"] != run["head"]:
        return _deny(RERUN, STALE_RUN.format(run=run_id))
    if not run["rerun"] or not set(run["rerun"]) <= forge.read_required(slug, pull["base"]):
        return _deny(RERUN, NOT_CHECK_RUN.format(run=run_id))
    return _allow(RERUN, {"run": run_id, "pr": number})


def _release_flags(parts: list[str]) -> dict[str, list[str]] | None:
    """The flag values of a `release transaction run`, None for a flag outside the set, with no value or repeated."""
    flags: dict[str, list[str]] = {}
    rest = parts[3:]
    index = 0
    while index < len(rest):
        flag = rest[index]
        if flag not in _RELEASE_FLAGS or index + 1 >= len(rest) or rest[index + 1].startswith("--"):
            return None
        if flag in flags and flag != "--confirm":
            return None
        flags.setdefault(flag, []).append(rest[index + 1])
        index += 2
    return flags


def _judge_release(parts: list[str], grant: Grant) -> Verdict:
    if parts[2] == "abandon" or any(
            part in ("--dispose", "--reference") or part.startswith(("--dispose=", "--reference="))
            for part in parts):
        return _deny(RELEASE, OWNERS_RELEASE_STEP)
    flags = _release_flags(parts)
    if flags is None:
        return _deny(RELEASE, NOT_GRANTED)
    named = [flag for flag in _CANDIDATE_FLAGS if flag in flags]
    if not named:
        return _deny(RELEASE, RESUME)
    if len(named) != len(_CANDIDATE_FLAGS) or "--repo-root" not in flags:
        return _deny(RELEASE, NOT_GRANTED)
    root = flags["--repo-root"][0]
    if not os.path.isabs(root) or os.path.realpath(root) != os.path.realpath(grant.root):
        return _deny(RELEASE, WRONG_ROOT)
    if "--confirm" not in flags:
        return _deny(RELEASE, NOT_GRANTED)
    commit, version, title = flags["--commit"][0], flags["--version"][0], flags["--title"][0]
    confirmations = frozenset(flags["--confirm"])
    if not any(card.commit == commit and card.version == version and card.title == title
               and card.confirmations == confirmations for card in grant.releases):
        return _deny(RELEASE, NO_CARD.format(commit=commit, version=version))
    return _allow(RELEASE, {"commit": commit, "version": version})


_OPENING = {MERGE: ["gh", "pr", "merge"], RERUN: ["gh", "run", "rerun"]}


def judge(command: str, grant: Grant, forge: Forge) -> Verdict:
    verb = _verb_of(command)
    if verb is None:
        return _no_decision()
    parts = words(command)
    if parts is None:
        return _deny(verb, ALONE)
    try:
        if parts[:3] == _OPENING[MERGE]:
            return _judge_merge(parts, grant, forge)
        if parts[:3] == _OPENING[RERUN]:
            return _judge_rerun(parts, grant, forge)
        if parts[:2] == ["release", "transaction"] and parts[2:3] in (["run"], ["abandon"]):
            return _judge_release(parts, grant)
    except ForgeUnreadable as error:
        return _deny(verb, FORGE_UNREADABLE.format(reason=error))
    return _deny(verb, ALONE)
