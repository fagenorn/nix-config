"""The permit judge: which Bash commands a manager's session may run (#1377, #1401, ADR-console-094).

A manager's session may run exactly three commands, and `judge(command, grant, forge)` decides each
one without touching the network, the clock or a file beyond the injected `Forge` readers and
`os.path.realpath`. Everything it needs about the sprint is in the `Grant`.

The three shapes (D3), judged only over the literal-word grammar of `words`:

1. Merge: `gh pr merge <n> --repo <slug> --<strategy> --match-head-commit <40 lowercase hex>`, then
   `--delete-branch` exactly when `grant.delete_branch` is true. `<n>` is digits with no leading zero.
2. Rerun: `gh run rerun <id> --failed --repo <slug>`.
3. Release: `release transaction run` and then only flag-value pairs, each flag one of `RELEASE_FLAGS`
   spelled exactly (`--confirm` may repeat, every other flag at most once), each value a word that does
   not begin with `-`. This is a grant, not a check: the release command itself refuses a candidate the
   owner has not approved on the console (ADR-release-016), so the permit reads no forge and checks no
   approval (ADR-console-094).

Each of the three shapes may follow one credential-scrub prefix, exactly a spelling of
`SCRUB_PREFIXES`, which equals the lifecycle guard's (#1592, ADR-console-102); `strip_scrub` removes it
once, and only the merge and the rerun are read through it: the release run takes none (ADR-console-094).

`words(command)` is a small scanner, not `shlex` (which accepts expansions and comments the shell
would act on). It splits on spaces and tabs only. A word is a plain run of `[A-Za-z0-9_./:@%+=,-]`
not beginning with `=`, a single-quoted run, or a double-quoted run without `$`, a backtick, a
backslash or `!`; a quote must open and close a whole word, so none is glued to another character.
It returns the words with their quotes removed, or None for anything else (an operator, a
redirection, an expansion, a glob, a comment, a tilde, a brace, a newline outside quotes).

`mentions(command)` is True when, after deleting every quote and backslash and splitting on
whitespace and on `;|&()<>$`, the backtick, `,`, `[`, `]`, `{` and `}`, some word whose basename is `gh` is followed by `pr
merge` or `run rerun`. Only the literal form is ever granted: every other spelling that `mentions` is
`DENY` with `ALONE`, never undecided. The literal plain release run is recognized first, before any
argument text is scanned, so a title or a notes path that spells `gh pr merge` is still a release run.
`release_operation(command)` also reads the release command,
under any program name (a bare `release`, any path whose basename is `release`, `python3 -m
agent_tools.release.release`, behind `env` or inside a chain): `abandon` is `ABANDON` and a `run` with a
`--dispose` or `--dispose=` word is `DISPOSE`, both always `DENY` for a manager (the lead abandons on the
owner's word and disposes on the owner's yes to a token). A literal command is judged on its words, so a
value is never an option: `--notes-file /tmp/a--dispose.md` is an ordinary run. The one word read
as a command line is a shell wrapper's body (the word after a `-c` style flag, or after `eval`): an
abandon or a dispose inside it is `ABANDON` or `DISPOSE`. The plain run is
`RELEASE` only as the literal shape above and only as the first command. A command that runs
`release transaction run` at a command position (the text start, after a chain or pipe operator, or behind
a wrapper the client strips before it matches rules), and that is neither the plain run nor abandon or
dispose (a preview flag, an abbreviated flag, which the release parser refuses, a `--flag=value` word, a
repeated flag, a value beginning with `-`, a chain, an expansion), is `DENY` with `RELEASE_SPELLING`, so
every text the manager's release allow rule matches, which the client matches for each subcommand of a
chain on its own, is decided (#1592, ADR-console-102). Every other release
spelling (a preview, text built at run time and piped to a shell) gets no decision
and falls to the session's classifier, as a merge spelling does; the release command's own approval
check is what makes that safe, and the residual is that an abandon or dispose spelling the scan cannot
see also gets no decision.

`judge` returns a `Verdict`. A command that `mentions` no granted verb gets `Verdict(None, "", None, {})`
and no reader is called. A command that does is `ALLOW` only in a granted shape and `DENY` otherwise,
never None. The checks run in this order, the first that applies deciding:

- Every verb: the words of `strip_scrub(command)` are None, or do not begin with the verb's own words:
  `ALONE`.
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
  skipped dependents of a failed job, but not a skipped job whose own `if` can never hold for a pull
  request event, `read_run`'s business) or one not named by `read_required(slug, base)` is
  `NOT_CHECK_RUN`. A head that `grant.reruns` already counts `MAX_RERUNS` (two) allowed reruns for is
  `RERUN_LIMIT`, which names the two reruns, each by run and failing members (#1712, ADR-console-106). Else `ALLOW` with target `{"run", "pr", "head", "count",
  "members"}`: `count` is the number of allowed reruns of that head with this one, and `members` the
  suite members the run's failed jobs reported as failed.
- Release: the plain run is `ALLOW` with its target; any other leading run is `RELEASE_SPELLING`.
- A reader raising `ForgeUnreadable` is `DENY` with `FORGE_UNREADABLE`.

`ALONE` and `NOT_GRANTED` for a merge or rerun are composed by `spelling_refusal(sentence, verb, grant,
missing)`: the sentence, ` Missing: <flags>.` when `missing` is not empty, and ` Accepted: <form>; <prefix
clause>`, where `accepted_form(verb, grant)` is the granted spelling filled with the grant's slug and
strategy and `PREFIX_CLAUSE` is the optional prefix the guard prints. `_missing` lists, in the form's order,
the flags of the form (`--repo`, the strategy flag, `--match-head-commit` and `--delete-branch` for a
merge; `--failed` and `--repo` for a rerun) that the words lack. `NOT_GRANTED` names them over the words;
`ALONE` names them over the words from the first exact opening when the words parse and hold one, so a
readable merge behind a bad prefix still names its omitted flag, and names none otherwise. Every other
reason keeps its sentence.

`Verdict.payload()` is `{"verb", "decision", "reason", "target"}`; `verb` is `merge`, `rerun`,
`release` (target `{"commit", "version"}`, None for a member the run does not name), `release-abandon`,
`release-dispose` or `action` (target `{"round", "index"}`). `merge_target(command, grant)` is
`{"pr", "head"}` when the command is exactly the granted
merge shape and None otherwise. `NOT_ACTIVE`, `NOT_MANAGER` and `MOVED` are the reasons the console
itself gives (the sprint is not active, the caller is not its manager, the sprint changed between
the first judgement and the second).

Approved actions: `judge_action(digest, questions, now)` is the console's verdict on a command no
granted shape names, by its SHA-256 `command_digest` over the sprint's question cards. A card names a
command when it carries an `action` whose command has that digest and is not withdrawn; none names it:
`Verdict(None, "", None, {})`. The first live card is `ALLOW`, verb `action`, target `{"round", "index"}`.
A card is live when the owner answered it (no guest: `answered_by` None, on an `owner_only` card), picked
exactly the action's `approve` option with no words beside it, no allowed run used it yet
(`action_used_at` None) and the answer is less than `APPROVAL_SECONDS` (60 minutes) old, an `answered_at`
that does not parse or carries no time zone being expired. Otherwise `DENY` with the reason of the last
card, the first that applies: `ACTION_UNANSWERED`, `ACTION_NOT_OWNERS`, `ACTION_NOT_APPROVED`,
`ACTION_USED`, else `ACTION_EXPIRED`. `judge` itself is unchanged: a command naming no granted verb still
gets no decision there, and the console, not `judge`, calls `judge_action` for a signed request.

Proof: the secret never travels on the action path, because another local account may own the loopback
port while the console restarts (ADR-console-100 D9). The command travels only as its SHA-256. The hook's
request carries `auth`, `action_request_auth(secret, signed_bytes(fields))`, an HMAC-SHA256 under the
secret over the request's members but `auth` (sorted compact JSON) behind the tag `permit-action-request`;
the console's judge reply carries `mac`, `action_reply_mac(secret, sprint_id, nonce, digest, decision,
reason)`, which the hook checks before it honours the decision, so whatever else listens on the port
neither learns the secret nor has a decision honoured. A replay of a captured request to the console is
not detected and at worst uses the approval (the manager asks again). The merge, rerun and release path
keeps its secret-bearing body (ADR-console-094, unchanged).

`verb_of(command)` is the verb `mentions` found (`merge`, `rerun` or one of the three release verbs), None
when it found none.

`rerun_record(events, held)` is the allowed reruns of each `(project, head)` that the `permit.judged`
rows say, each a `Rerun` (its run and failing suite members), which the console folds and hands to a
`Grant` as `reruns` (head to its `Rerun`s); `RERUN_LIMIT` names the two reruns from them.

`memoized(forge)` caches each reader's result, or the `ForgeUnreadable` it raised, by its arguments;
its `.frozen()` is a `Forge` over the same cache that raises `ForgeUnreadable("not read before")`
for a call not already cached, so the console judges again without a second forge read.

Readers (`read_pr`, `read_run`, `read_required`) read the forge once and raise `ForgeUnreadable` with
a fixed sentence for a failed read or a missing or malformed member; no raw forge text reaches a
reason. `read_run`'s `rerun` is the names of the jobs a failed-job rerun would run, read across every
page of the run's jobs. A job whose conclusion is `skipped` is left out when the run's workflow file at
the run's head (the run's `path`, read once, only when a job was skipped) gives that job, by name, an
`if` that `never_on_pull_request` proves false for a pull request event: a `&&` chain with a
`github.event_name == '<event>'` term for an event but `pull_request` (or `!= 'pull_request'`), no `||`
and no call but `!cancelled()`, `always()`, `success()` and `failure()`. Anything else, a run with no
`path` or a job the file does not name counts as it did; a workflow file that cannot be read is
`ForgeUnreadable`. `members` is the `suite-runner: failed <member>` lines of the log of each job whose
conclusion is `failure`, in order and once each (at most `MAX_MEMBERS`); a log that cannot be read adds
none, because the members are evidence and gate nothing. `read_required` names only the checks a GitHub Actions job can satisfy: a
check bound to another app is left out, even when the legacy `contexts` list repeats its name. `merge_binding(root)` is the project contract's `bindings.vcs.merge` `strategy` and
`delete_branch`, `(None, False)` on any failure.
"""
import base64
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from agent_tools.console import deliveries
from agent_tools.console.event_log import PERMIT_JUDGED
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api

ALLOW = "allow"
DENY = "deny"

ALONE = "This command runs only alone, spelled exactly as the permitted form, with no operator, expansion or wrapper."
NOT_GRANTED = "The permit grants only the exact merge and rerun forms, and this one differs."
NO_ABANDON = "A manager never abandons a release; the lead does, on the owner's word."
NO_DISPOSE = "A manager never disposes of a release; the lead does, on the owner's yes to its token."
RELEASE_SPELLING = ("A release runs only as the plain release transaction run: each flag one of --repo-root, "
                    "--profile, --commit, --version, --title, --notes-file, --confirm, each followed by its "
                    "value as the next word, and only --confirm repeated.")
ADMIN = "An administrator merge is never permitted."
OTHER_REPO = "The command names another repository than this sprint's project."
NOT_OWN_PR = "Pull request {pr} is not this sprint's own pull request."
SHARED_ISSUE = "Issue {issue} belongs to another open sprint."
DEPLOY_RERUN = "Run {run} is a {event} run, not a pull request check run, so it is not rerun."
NOT_OWN_RUN = "Run {run} is not a check run of this sprint's own pull request."
STALE_RUN = "Run {run} is not at the head of its pull request."
NOT_CHECK_RUN = "Run {run} would rerun a job that is not a required check."
RERUN_LIMIT = ("Pull request {pr} has had its head {head} rerun twice, by {reruns}, and a third rerun is "
               "refused: the head must be reported or fixed.")
STALE_HEAD = "Pull request {pr} is not at the head the merge names."
FORGE_UNREADABLE = "The forge could not be read to judge this command: {reason}"
NOT_ACTIVE = "This sprint is not active."
NOT_MANAGER = "Only the sprint's manager session may run this command."
MOVED = "The sprint changed while the command was judged."
APPROVAL_SECONDS = 60 * 60
ACTION_UNANSWERED = "The owner has not answered this action's card yet; run it after the answer approves it."
ACTION_NOT_OWNERS = "Only the owner's answer on an owner-only card approves an action."
ACTION_NOT_APPROVED = ("The owner's answer did not approve this action: only its approve option, picked "
                       "with no words beside it, approves.")
ACTION_USED = "The owner's approval of this action was used; ask again on a new owner-only card to run it again."
ACTION_EXPIRED = ("The owner's approval of this action expired 60 minutes after the answer; ask again on "
                  "a new owner-only card.")

MERGE, RERUN = "merge", "rerun"
MAX_RERUNS = 2
MAX_MEMBERS = 50
ACTION = "action"
RELEASE, ABANDON, DISPOSE = "release", "release-abandon", "release-dispose"
RELEASE_FLAGS = ("--repo-root", "--profile", "--commit", "--version", "--title", "--notes-file",
                 "--confirm")
# The credential names a scrub prefix may drop, and the prefixes the lifecycle guard accepts: the guard's
# own derivation, copied (the package never imports the guard), and a test holds the two equal (#1592).
GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
SCRUB_PREFIXES = tuple(sorted(
    {
        spelling
        for names in [(name,) for name in GH_ENV_TOKEN_NAMES] + [
            (first, second)
            for first in GH_ENV_TOKEN_NAMES for second in GH_ENV_TOKEN_NAMES
            if first != second
        ]
        for spelling in (
            "unset " + " ".join(names) + " && ",
            "env " + " ".join(f"-u {name}" for name in names) + " ",
        )
    },
    key=lambda spelling: (-len(spelling), spelling),
))


def _prefix_clause() -> str:
    """The guard's `prefix_clause()`: the documented two-name `env -u`, the one-name `unset` and the
    one-name `env -u` spelling, in `SCRUB_PREFIXES` order."""
    first, second = GH_ENV_TOKEN_NAMES
    printed = (["env", "-u", first, "-u", second], ["unset", first, "&&"], ["env", "-u", first])
    return "optional prefix: " + " | ".join(
        spelling.rstrip() for spelling in SCRUB_PREFIXES if spelling.split() in printed)


PREFIX_CLAUSE = _prefix_clause()
ACTIONS_APP, ANY_APP = 15368, -1

_PLAIN = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")
_NUMBER = re.compile(r"[1-9][0-9]*")
_SHA = re.compile(r"[0-9a-f]{40}")
_SEPARATORS = " \t"
_DOUBLE_QUOTED_BARRED = "$`\\!"
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


class ForgeUnreadable(Exception):
    """A forge read failed or answered a malformed reply; `str(error)` is the fixed reason."""


@dataclass(frozen=True)
class Rerun:
    """One allowed rerun of a head, as its `permit.judged` row says: the run and the failing suite members."""
    run: object
    members: tuple[str, ...] = ()

    def describe(self) -> str:
        failing = ", ".join(self.members) if self.members else "no members reported"
        return f"run {self.run} (failing: {failing})"


@dataclass(frozen=True)
class Grant:
    slug: str | None
    root: str
    strategy: str | None
    delete_branch: bool
    branch_pattern: str | None
    issues: frozenset[int]
    others: frozenset[int]
    reruns: Mapping[str, Sequence["Rerun"]] = field(default_factory=dict, compare=True)


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


_NEVER_CALLS = re.compile(r"\b(?:cancelled|always|success|failure)\(\)")
_EVENT_IS = re.compile(r"github\.event_name\s*==\s*'([A-Za-z_]+)'", re.IGNORECASE)
_EVENT_IS_NOT = re.compile(r"github\.event_name\s*!=\s*'([A-Za-z_]+)'", re.IGNORECASE)
_EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
_JOB_KEY = re.compile(r"^  [A-Za-z0-9_-]+:\s*$")
_JOB_NAME = re.compile(r"^    name:\s*(\S.*?)\s*$")
_JOB_IF = re.compile(r"^    if:\s*(\S.*?)\s*$")
_FAILED_MEMBER = re.compile(r"^(?:\S+Z )?suite-runner: failed (\S+)\s*$", re.MULTILINE)


def never_on_pull_request(condition: str) -> bool:
    """Whether a job's `if` is provably false for a pull request event (see the module docstring)."""
    found = _EXPRESSION.fullmatch(condition)
    text = (found[1] if found else condition).strip()
    text = _NEVER_CALLS.sub("", text)
    if "||" in text or "(" in text or ")" in text:
        return False
    for term in (term.strip() for term in text.split("&&")):
        for pattern, holds_for in ((_EVENT_IS, lambda event: event.lower() != "pull_request"),
                                   (_EVENT_IS_NOT, lambda event: event.lower() == "pull_request")):
            match = pattern.fullmatch(term)
            if match and holds_for(match[1]):
                return True
    return False


def _unquoted(value: str) -> str:
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"" else value


def _job_conditions(workflow: str) -> dict[str, str]:
    """Each job's display name, its `name:` else its key, mapped to its job-level `if:` (only jobs with one)."""
    conditions: dict[str, str] = {}
    key = name = condition = None
    inside = False

    def close():
        if key is not None and condition is not None:
            conditions[key if name is None else name] = condition

    for line in workflow.splitlines():
        if line.startswith("jobs:"):
            inside = True
        elif inside and re.match(r"^[A-Za-z]", line):
            inside = False
        if not inside:
            continue
        if _JOB_KEY.match(line):
            close()
            key, name, condition = line.strip()[:-1].strip(), None, None
        elif (match := _JOB_NAME.match(line)):
            name = _unquoted(match[1])
        elif (match := _JOB_IF.match(line)):
            condition = _unquoted(match[1])
    close()
    return conditions


def _workflow_conditions(slug: str, run: Mapping, what: str) -> dict[str, str]:
    """The job `if:` conditions of the run's workflow file at the run's head; none when the run has no path."""
    path = run.get("path")
    if not isinstance(path, str) or not path:
        return {}
    head = _member(run, "head_sha", str, what)
    reply = _get(f"repos/{slug}/contents/{path.partition('@')[0]}?ref={head}", f"the workflow of {what}")
    content = reply.get("content") if isinstance(reply, dict) else None
    if not isinstance(content, str):
        raise ForgeUnreadable(f"the workflow of {what} has no readable content")
    try:
        return _job_conditions(base64.b64decode("".join(content.split()), validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ForgeUnreadable(f"the workflow of {what} has no readable content") from None


def _failed_members(slug: str, job_ids: Sequence[int]) -> list[str]:
    """The suite members the logs of the jobs report as failed, in order and once each."""
    found: list[str] = []
    for job_id in job_ids:
        try:
            _, text = forge_api.run_gh(["api", f"repos/{slug}/actions/jobs/{job_id}/logs"])
        except forge_api.ForgeError:
            continue
        for member in _FAILED_MEMBER.findall(text):
            if member not in found:
                found.append(member)
    return found[:MAX_MEMBERS]


def read_run(slug: str, run_id: int) -> Mapping:
    what = f"run {run_id}"
    run = _get(f"repos/{slug}/actions/runs/{run_id}", what)
    pages = _pages(f"repos/{slug}/actions/runs/{run_id}/jobs?per_page=100", what)
    if not pages:
        raise ForgeUnreadable(f"{what} has no readable jobs")
    prs = _member(run, "pull_requests", list, what)
    numbers = [_member(pull, "number", int, what) for pull in prs]
    jobs = []
    for page in pages:
        for job in _member(page, "jobs", list, what):
            name = _member(job, "name", str, what)
            conclusion = job.get("conclusion")
            if conclusion is not None and not isinstance(conclusion, str):
                raise ForgeUnreadable(f"{what} has no readable conclusion")
            jobs.append((name, conclusion, job.get("id")))
    conditions = (_workflow_conditions(slug, run, what)
                  if any(conclusion == "skipped" for _, conclusion, _ in jobs) else {})
    rerun = [name for name, conclusion, _ in jobs
             if conclusion != "success" and not (
                 conclusion == "skipped" and never_on_pull_request(conditions.get(name, "")))]
    failed = [job_id for _, conclusion, job_id in jobs
              if conclusion == "failure" and isinstance(job_id, int) and not isinstance(job_id, bool)]
    return {"event": _member(run, "event", str, what),
            "branch": _member(run, "head_branch", str, what),
            "repo": _member(_member(run, "head_repository", dict, what), "full_name", str, what),
            "head": _member(run, "head_sha", str, what), "prs": numbers, "rerun": rerun,
            "members": _failed_members(slug, failed)}


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


def rerun_record(events: Sequence, held: Mapping[tuple[str | None, str], tuple[Rerun, ...]] | None = None
                 ) -> dict[tuple[str | None, str], tuple[Rerun, ...]]:
    """`held` plus, for each `permit.judged` row of an allowed rerun, its `Rerun` for its `(project, head)`."""
    record = dict(held or {})
    for event in events:
        payload = event.payload
        target = payload.get("target") if isinstance(payload, dict) else None
        head = target.get("head") if isinstance(target, dict) else None
        if (event.kind == PERMIT_JUDGED and payload.get("verb") == RERUN
                and payload.get("decision") == ALLOW and isinstance(head, str)):
            members = target.get("members")
            rerun = Rerun(target.get("run"), tuple(m for m in members if isinstance(m, str))
                          if isinstance(members, list) else ())
            record[(event.project, head)] = record.get((event.project, head), ()) + (rerun,)
    return record


def reruns_of(record: Mapping[tuple[str | None, str], tuple[Rerun, ...]], project: str) -> dict[str, tuple[Rerun, ...]]:
    """The allowed reruns of each head in one project, from `rerun_record`'s `(project, head)` keys."""
    return {head: reruns for (owner, head), reruns in record.items() if owner == project}


def reads(root: str | None, slug_of, branch_pattern_of, merge_binding_of
          ) -> tuple[str | None, str | None, str | None, bool]:
    """The project's slug, branch pattern, merge strategy and whether a merge deletes its branch; `root` None or a
    reader that raises reads as unknown (None, and False for the branch deletion)."""
    if root is None:
        return None, None, None, False

    def read(source, default):
        try:
            return source(root)
        except Exception:
            return default
    strategy, delete_branch = read(merge_binding_of, (None, False))
    return read(slug_of, None), read(branch_pattern_of, None), strategy, delete_branch


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
_SHELL_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
# A release run at a command position: the text start or after an operator, past leading `NAME=value`
# assignments, shell keywords and `!`, and after the wrappers the client strips before it matches rules (the
# guard refuses the detaching one). The client matches each subcommand of a chain on its own, so the
# manager's release allow rule matches such a segment wherever it stands (#1592). Whether the client also
# strips assignments or splits keyword bodies is unconfirmed, so the permit decides them all. A value's
# unquoted character excludes quotes and backslashes, so each value parses one way: with `\S` there it split
# a quoted value many ways and a failed search backtracked exponentially on every Bash call.
# Likewise a wrapper's argument is a run of `[\w=.,:-]` that is no wrapper word (a wrapper word starts the
# next wrapper instead), so each token parses one way here too.
_RELEASE_RUN_TEXT = re.compile(
    r"(?:\A|[;&|\n(){`]|\$\()\s*"
    r"(?:(?:(?:then|do|else|elif|if|while|until|!)|[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\\.|[^\s\"'\\])*)\s+)*"
    r"(?:(?:timeout|time|nice|stdbuf|command|builtin|noglob|xargs)"
    r"(?:\s+(?!(?:timeout|time|nice|stdbuf|command|builtin|noglob|xargs)\s)[\w=.,:-]+)*?\s+)*"
    r"release\s+transaction\s+run(?:\s|\Z)")


def release_target(command: str) -> dict | None:
    """`{"commit", "version"}` when the command is exactly the plain release run, else None."""
    parts = words(command)
    if parts is None or parts[:3] != ["release", "transaction", "run"]:
        return None
    rest, seen, target = parts[3:], set(), {"commit": None, "version": None}
    if len(rest) % 2:
        return None
    for flag, value in zip(rest[::2], rest[1::2]):
        if flag not in RELEASE_FLAGS or value.startswith("-"):
            return None
        if flag != "--confirm" and flag in seen:
            return None
        seen.add(flag)
        if flag in ("--commit", "--version"):
            target[flag[2:]] = value
    return target


def _release_verb(parts: list[str], literal: bool, command: str) -> str | None:
    """The release verb the word list `parts` runs; `RELEASE` only for a literal command's first words."""
    for index, part in enumerate(parts):
        if (os.path.basename(part) != "release" and part != "agent_tools.release.release"
                or parts[index + 1:index + 2] != ["transaction"] or len(parts) <= index + 2):
            continue
        verb = parts[index + 2]
        if verb == "abandon":
            return ABANDON
        if verb == "run" and any(
                word == "--dispose" or word.startswith("--dispose=") for word in parts[index + 3:]):
            return DISPOSE
        if literal and index == 0 and verb == "run" and release_target(command) is not None:
            return RELEASE
    return None


def _wrapper_bodies(literal: list[str]) -> list[str]:
    """The words a shell would run as a command line: the word after a `-c` style flag or `eval`."""
    return [word for before, word in zip(literal, literal[1:])
            if _SHELL_FLAG.fullmatch(before) or os.path.basename(before) == "eval"]


def release_operation(command: str) -> str | None:
    """`RELEASE`, `ABANDON` or `DISPOSE` when the command runs the release command that way, else None."""
    literal = words(command)
    if literal is None:
        return _release_verb(_SPLIT.split(re.sub(r"['\"\\]", "", command)), False, command)
    found = _release_verb(literal, True, command)
    if found is not None:
        return found
    for body in _wrapper_bodies(literal):
        inner = _release_verb(_SPLIT.split(re.sub(r"['\"\\]", "", body)), False, body)
        if inner in (ABANDON, DISPOSE):
            return inner
    return None


def _verb_of(command: str) -> str | None:
    if release_target(command) is not None:
        return RELEASE
    parts = _SPLIT.split(re.sub(r"['\"\\]", "", command))
    for index, part in enumerate(parts):
        name, rest = os.path.basename(part), parts[index + 1:index + 3]
        if name == "gh" and rest == ["pr", "merge"]:
            return MERGE
        if name == "gh" and rest == ["run", "rerun"]:
            return RERUN
    found = release_operation(command)
    if found is None and _RELEASE_RUN_TEXT.search(command):
        return RELEASE
    return found


def verb_of(command: str) -> str | None:
    """`merge`, `rerun` or a release verb when `mentions(command)`, else None."""
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


def strip_scrub(command: str) -> str:
    """The rest after the first `SCRUB_PREFIXES` spelling `command` starts with, when that rest is
    non-empty and does not begin with whitespace; else `command` unchanged. Stripped at most once."""
    for prefix in SCRUB_PREFIXES:
        if command.startswith(prefix):
            rest = command[len(prefix):]
            return rest if rest and not rest[0].isspace() else command
    return command


def accepted_form(verb: str, grant: Grant) -> str:
    """The granted spelling of `verb`, filled with the grant's slug and strategy where it has them."""
    slug = grant.slug or "<slug>"
    if verb == RERUN:
        return f"gh run rerun <id> --failed --repo {slug}"
    form = f"gh pr merge <n> --repo {slug} --{grant.strategy or '<strategy>'} --match-head-commit <sha>"
    return form + (" --delete-branch" if grant.delete_branch else "")


def spelling_refusal(sentence: str, verb: str, grant: Grant, missing: Sequence[str] = ()) -> str:
    """`sentence`, the flags the command omits, the accepted form and the optional prefix clause."""
    named = f" Missing: {', '.join(missing)}." if missing else ""
    return f"{sentence}{named} Accepted: {accepted_form(verb, grant)}; {PREFIX_CLAUSE}"


def _missing(verb: str, parts: list[str], grant: Grant) -> tuple[str, ...]:
    """The flags of the granted form that `parts` lacks, in the form's order."""
    if verb == RERUN:
        wanted = ["--failed", "--repo"]
    else:
        wanted = ["--repo"] + ([f"--{grant.strategy}"] if grant.strategy is not None else [])
        wanted += ["--match-head-commit"] + (["--delete-branch"] if grant.delete_branch else [])
    return tuple(flag for flag in wanted if flag not in parts)


def merge_target(command: str, grant: Grant) -> dict | None:
    parts = words(strip_scrub(command))
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
    refusal = spelling_refusal(NOT_GRANTED, MERGE, grant, _missing(MERGE, parts, grant))
    if grant.slug is None or grant.strategy is None:
        return _deny(MERGE, refusal)
    repo = _repo_value(parts)
    if repo is not None and repo != grant.slug:
        return _deny(MERGE, OTHER_REPO)
    target = _merge_shape(parts, grant)
    if target is None:
        return _deny(MERGE, refusal)
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
        return _deny(RERUN, spelling_refusal(NOT_GRANTED, RERUN, grant, _missing(RERUN, parts, grant)))
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
    done = grant.reruns.get(run["head"], ())
    if len(done) >= MAX_RERUNS:
        return _deny(RERUN, RERUN_LIMIT.format(
            pr=number, head=run["head"], reruns=" and ".join(rerun.describe() for rerun in done)))
    return _allow(RERUN, {"run": run_id, "pr": number, "head": run["head"], "count": len(done) + 1,
                          "members": list(run.get("members", []))})


_OPENING = {MERGE: ["gh", "pr", "merge"], RERUN: ["gh", "run", "rerun"]}


def judge(command: str, grant: Grant, forge: Forge) -> Verdict:
    verb = _verb_of(command)
    if verb is None:
        return _no_decision()
    if verb == RELEASE:
        target = release_target(command)
        return _allow(RELEASE, target) if target is not None else _deny(RELEASE, RELEASE_SPELLING)
    if verb == ABANDON:
        return _deny(ABANDON, NO_ABANDON)
    if verb == DISPOSE:
        return _deny(DISPOSE, NO_DISPOSE)
    parts = words(strip_scrub(command))
    if parts is None:
        return _deny(verb, spelling_refusal(ALONE, verb, grant))
    try:
        if parts[:3] == _OPENING[MERGE]:
            return _judge_merge(parts, grant, forge)
        if parts[:3] == _OPENING[RERUN]:
            return _judge_rerun(parts, grant, forge)
    except ForgeUnreadable as error:
        return _deny(verb, FORGE_UNREADABLE.format(reason=error))
    opening = _OPENING[verb]
    start = next((i for i in range(len(parts)) if parts[i:i + 3] == opening), None)
    missing = () if start is None else _missing(verb, parts[start:], grant)
    return _deny(verb, spelling_refusal(ALONE, verb, grant, missing))


# --- approved actions ---------------------------------------------------------------------

def command_digest(command: str) -> str:
    """The SHA-256 of a command, the only form in which an action's command travels."""
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def signed_bytes(fields: Mapping[str, object]) -> bytes:
    """The bytes a request's `auth` covers: its members but `auth`, as sorted compact JSON."""
    return json.dumps({k: v for k, v in fields.items() if k != "auth"}, sort_keys=True,
                      separators=(",", ":")).encode()


def action_request_auth(secret: str, signed: bytes) -> str:
    """The hook's `auth` of an action request whose `signed_bytes` are given (see the module docstring)."""
    return hmac.new(secret.encode(), b"permit-action-request\0" + signed, hashlib.sha256).hexdigest()


def action_reply_mac(secret: str, sprint_id: str, nonce: str, digest: str, decision: str | None,
                     reason: str) -> str:
    """The `mac` of a judge reply to the request that carried `nonce` (see the module docstring)."""
    return hmac.new(
        secret.encode(),
        f"permit-action-reply\0{sprint_id}\0{nonce}\0{digest}\0{decision or ''}\0{reason}".encode(),
        hashlib.sha256).hexdigest()


def _approval_live(card, now: datetime) -> bool:
    if (card.answer is None or not card.owner_only or card.answered_by is not None
            or card.chosen != card.action.approve or card.words is not None
            or card.action_used_at is not None):
        return False
    try:
        answered = datetime.fromisoformat(card.answered_at)
    except (TypeError, ValueError):
        return False
    return answered.tzinfo is not None and now < answered + timedelta(seconds=APPROVAL_SECONDS)


def _action_refusal(card) -> str:
    if card.answer is None:
        return ACTION_UNANSWERED
    if not card.owner_only or card.answered_by is not None:
        return ACTION_NOT_OWNERS
    if card.chosen != card.action.approve or card.words is not None:
        return ACTION_NOT_APPROVED
    if card.action_used_at is not None:
        return ACTION_USED
    return ACTION_EXPIRED


def judge_action(digest: str, questions: Sequence, now: datetime) -> Verdict:
    """The verdict on a command by its digest over the sprint's question cards (see the module docstring)."""
    cards = [card for card in questions
             if card.action is not None and card.withdrawn_at is None
             and command_digest(card.action.command) == digest]
    if not cards:
        return _no_decision()
    for card in cards:
        if _approval_live(card, now):
            return _allow(ACTION, {"round": card.round_id, "index": card.index})
    return _deny(ACTION, _action_refusal(cards[-1]))
