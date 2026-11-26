"""The console's drafted project contract for a repository that has none (#1067).

Decided in ADR-console-031. The plain words and the main/more split are ADR-console-033. The reconcile
proposal of a commit environment is ADR-console-083. A repository with no `.agents/project.json` is registered with
a project-schema-3 contract the console drafts from what the repository says and what the owner answers.
This module reads the repository, drafts the five values schema 3 authors, shows the values the platform
derives as facts, words the open fields as cards, takes the owner's answers, and renders the wire-format
contract that `adopt-project plan --contract-draft` takes. It judges only what it must to stay total (a
command that `shlex` can read, JSON that parses): every other value is the resolver's to judge (plan D2).

Reading. `read(root, cancel=None)` returns `{"remotes": [(name, url)], "default_branch", "branches", "files",
"texts", "platform_version", "tree_platform_version", "protection_after", "pins_platform", "attempt"}` and
never raises and never writes. Every git child has no shell, `stdin` and `stderr` to
`DEVNULL`, `GIT_TIMEOUT` (10 seconds), `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1`; an `OSError`,
a timeout or a non-zero exit reads as empty or None. Remotes are the authored URLs (`config --get-regexp`, before
`insteadOf`), sorted by name, one URL per name. The default branch is asked of the remote only when
there is exactly one (`ls-remote --symref`). Branches are the local heads, files the tracked paths,
texts the tracked build files (`justfile`, `Makefile`, `package.json` and their spellings) and the
tracked `.github/branch-protection.json` and `devenv.lock`, at most 65536 bytes each, read from `HEAD`.
`platform_version` is the running platform manifest's version (None on any error) and
`tree_platform_version` the `platform_version` of a tracked `platform-manifest.json` of the tree at `HEAD`
(None when there is none or it holds no version). The conformance the adoption would plan is read without
writing, with `adopt_conformance.plan_conformance` over `HEAD`: `protection_after` is the text of the
protection file the adoption writes, else the committed one, else None, and `pins_platform` says the
adoption pins the platform in `devenv.lock` (any failure there gives the committed text and False).
`attempt` is `{"minutes", "source"}` of `attempt_history.read` (`history` or `fallback`). A set cancel
reads what git says as empty.

`read_hooks(root, cancel, *, search_path=None)` reads the commit hooks and the environment files a
reconcile plan needs, as `{"hooks", "stranded", "environments"}`; it never raises and never writes. `hooks` are the
`COMMIT_HOOKS` names (`pre-commit`, `prepare-commit-msg`, `commit-msg`; never `post-commit`, which cannot stop
a commit) installed as executable files in the repository's own hooks directory (the `core.hooksPath` its
own configuration sets, else its `hooks` directory; a global, system or command-line hooks path never counts,
and Git's checkout trust is kept), in `COMMIT_HOOKS` order. A relative `core.hooksPath` is resolved in each
checkout, so such a hook counts only when `HEAD` tracks it as an executable file or as a link inside the tree
to one. `environments` are the `ENVIRONMENTS` file names present in the `HEAD` commit as a regular file (the
revision Apply's worktree starts from, so an untracked, staged-only or directory entry never counts), in
`ENVIRONMENTS` order. `stranded`
is the sublist, in `COMMIT_HOOKS` order, of the hooks whose text `hook_stranded(text, search_path)`
judges stranded: a hook that execs a runner found neither at its recorded absolute path nor on the
plain `PATH` (`search_path`, else the console's own), so it fails in the commit Apply runs outside a
development shell (#1333). A hook's text is its file's bytes in the hooks directory, or the `HEAD`
blob a relative `core.hooksPath` resolves to after following links, decoded as UTF-8 with `replace`;
a hook above `TEXT_LIMIT` bytes is never read past that bound and reads as `""`, and so does an
unreadable one. `hook_stranded` judges a hook only when every non-comment line is one of a fixed
allowlist of shapes, and every other hook is unjudged and never stranded, so its plan stays as it is
today (#1333). The shapes are: a blank line; a first-line shebang whose interpreter is `sh`, `bash`,
`dash` or `zsh` (directly or through `env`); `NAME=value` or `NAME="value"` for any `NAME` but `PATH`, `path` (zsh ties it to `PATH`) and `IFS`
(a trailing `#` comment aside; the value is one literal word with no unquoted `;`, `&`, `|`, `<`, `>`,
parenthesis or backtick, or is wholly one balanced `$( )` or backtick substitution, which is never a
runner candidate, so a line holding several commands is never of this shape); `if [ ... ]; then`, `else` and `fi` lines, the test holding no `;`,
`&`, `|`, `<`, `>`, backtick, parenthesis or brace; and exactly one line-leading `exec` of a word or of
`"$NAME"` (`$NAME`, `${NAME}`), outside any `if`, followed by any arguments. A runner variable's
candidates are only its literal assigned values, and it is judged only when a line outside any `if`
assigns it before the `exec` (an assignment only inside an `if`, or only after the `exec`, may leave an inherited value) and, when written without
quotes, only when no assigned value holds a blank or one of `*?[`. A line of any other shape (a `PATH`, `path` or `IFS` assignment, an
`export`, `+=`, an array or nameref, a default expansion, `read`, `for`, `eval`, `source`, a second
`exec`, or a command run on any line but the `exec`) leaves the hook unjudged. A runner is found when it
is absolute and an executable file, or has no `/` and is on `search_path`; a `search_path` with an entry
that is not absolute (relative to a working directory the commit does not share) leaves every hook
unjudged, and so does a set `cancel`. A judged hook is stranded exactly when none of its candidates is found.
A runner that is unassigned, empty, relative, an option, or carries `$`, a backtick or a shell operator is
unjudged too. Reading a hook never fetches a missing blob (`GIT_NO_LAZY_FETCH=1`), and reads a tracked hook by the
blob id it first resolved, so the size bound and the content are one blob.

`hooks_missing(root, cancel=None)` says whether the checkout's devenv git hooks are not installed on this host:
True exactly when `HEAD` tracks `devenv.nix` as a regular file no larger than `hook_install.TEXT_LIMIT` whose
text `hook_install.declares_hooks` judges to declare hooks, and `hook_install.left_alone` finds neither a
`core.hooksPath` of the repository's own configuration nor an executable commit hook in `<git-common-dir>/hooks`
(a global or system hooks path never counts). It is False on any error or a set `cancel`, never raises and never
writes. It is independent of `read_hooks`, whose reconcile proposal it leaves as it was.

Fields. `FIELDS` lists the five authored field ids in order (`integration-branch`, `lint-command`,
`test-command`, `release`, `production`), each pointing only at a member `schema_three.authored` accepts; each is a
record with exactly the keys `FIELD_KEYS`: `field`, `label`, `value` (a str or None), `source` (a key of `SOURCES`
or None), `options` (`{"value", "label"}` rows), `text` (a typed value is accepted), `reason` (why its card is
open though it has a value) and `ask` (its card's question, fixed by `draft` so it never changes
with later answers). `draft(root, reading)` fills each from the remote's default branch, the tracked files
(the lint and test commands) or the console's starting value, and follows them with the facts. A field is open
(`open_fields`) when it has no value and is one of `ASKED` (the integration branch, the lint and test
commands), or when it has a `reason`; `questions` words each open field as one card; `shown` gives every
other record as one entry, with `fact` true for a fact (never `more`, no options, no Change control). `MAIN` lists the fields and facts that keep their own line, each one line
`<label>: <display> (<source>)`; the other two fields have the flag `more` in `shown`, and while their value
is its start value its line is its start sentence (`REST_WORDS`, plain words with no source), so it reads as a
settled default; once it is another value it reads `<label>: <value> (<source>)`. `more_line` counts those
shown `more` entries in one line, `and <n> more settings at their usual values`, or `and <n> more settings,
<k> of them set by you`. `placeholder` gives a typed field the words its empty box shows (`PLACEHOLDERS`),
None for a choice. Every label is plain words, never a contract term.

Facts. `FACTS` lists the values the platform derives and the adoption writes from the repository, as records
with the field keys, `options` `[]`, `text` False, `reason` None and `ask` `""`: the project id and issue
tracker (`project-identity`, the origin remote's slug), the checks a pull request must pass
(`required-checks`, `derived_values.checks_in` of `protection_after`, or `none`), the platform range
(`platform-range`: a tree's own manifest first, else the running manifest's when `pins_platform`), the
minutes per delivery attempt (`attempt-minutes`) and the knowledge files it holds (`knowledge-homes`: the
platform homes that are a tracked path or directory). `FACT_POINTERS` names the pointers each stands for.
A fact is never open, never answered (`UNKNOWN_FIELD`), never a refusal's target; a `source` of None means it
cannot be derived and its value is then the words naming why. `facts(root, reading)` builds them,
`with_facts(fields, reading, root)` appends them, `has_facts(fields)` says a list holds any and
`fact_refused(error)` says an adoption refusal names only facts (or a registered project id), so it is a failed
plan and no field's card reopens.

Earlier drafts. `refresh(root, fields)` gives a saved draft today's label, option labels, card question and
refusal wording (`current_reason`, by `LEGACY_REASONS`).
An amendment (a reconcile proposal) keeps its records. Any other saved draft is carried onto `FIELDS`
(`integration-branch` from its saved value, else the earlier default branch; a test command unless it was
`none`; the release; the production) and the saved facts; every other record of an earlier table
(`RETIRED_FIELDS`) is dropped and the lint command is asked. `retired_in_use(fields)` says a saved draft held
one whose value is not `none`, or a refusal, and `replanned(fields)` opens the integration branch's card with
`PLAN_AGAIN` so an answer plans again, unless a card is already open.

Reconcile proposal. `PROPOSED` lists the one field a reconcile plan proposes alone (#1333), never drafted:
`commit-environment` (`changes are saved in its development shell`), a typed choice with the one option
`none`, never open. `reconcile_fields(root, reading)` is `[]` unless `reading["stranded"]` is not empty and an
`ENVIRONMENTS` file is in `reading["environments"]`; otherwise it is that one record with the command of the first
file (source `files`). `amends(fields)` is true for a non-empty list whose every record is a `PROPOSED` field,
which no `draft` list is. `environment(fields)` is that record's value, None when it is None or `none`.
`carried(fields, plan)` keeps `fields` for a plan, except an amendment that names an environment which the plan's
document does not carry, which is None. `proposed_lines(fields)` gives the `shown` line of each `PROPOSED` field
present in a list, `[]` for a non-list or a draft without one; the ready Apply card shows them first. Its shown
line leaves a trailing `--` off the command.

Answers. `set_value(fields, field, value)` returns `(new_fields, None)` or `(None, text)`, refusing in order
with `UNKNOWN_FIELD`, `EMPTY_VALUE`, `NOT_OFFERED` (a choice field), `none` for a lint or test command (every
project has both), `COMMAND_UNREADABLE` (a command `shlex` cannot read) and `NOT_JSON`, and never mutates its
input. `draft_id` is the digest of the root and the fields, so two different drafts never share a plan.

Contract. `contract(fields)` is total on every list `draft`, `set_value` and `refresh` produced. It has exactly
`schema_version` 3, `bindings` (`vcs.integration_branch` and the commands `lint` and `test`, each only
`argv`: `cwd` and `env` are platform constants), `capabilities` (nine, each `{"support": "supported" |
"unsupported"}`: `knowledge.<x>` is supported exactly when its platform home is in the `knowledge-homes` fact, a
missing fact reading as `none`, and every other one is supported), `projections` `[]`, `release`, and `production`
only when it is not `none`. It has no `project`, `platform` or constant member: the platform derives them.

Refusals. `refused_field(error)` maps an `adopt.draft.invalid` error to the field its first matching violation
names (the longest matching pointer wins) and the one wording `The plan refused the <label>: <message>`;
`mark_refused` opens that field's card with it as the reason. No text here carries a pointer or a repair id.
"""

from __future__ import annotations

import copy
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path

from agent_tools import canonical
from agent_tools.console import manager
from agent_tools.project_contract import (
    adopt_conformance, agent_platform, attempt_history, derived_values, hook_install, schema_three)
from agent_tools.system.semver import parse_semver

QUESTION_ID = "contract-draft"
GIT_TIMEOUT = 10
TEXT_LIMIT = 65536
FIELD_KEYS = {"field", "label", "value", "source", "options", "text", "reason", "ask"}
SOURCES = {
    "remote": "read from its remote",
    "files": "found in its files",
    "lock": "locked in devenv.lock by the adoption",
    "history": "from its recorded deliveries",
    "platform": "the platform's value until enough deliveries are recorded",
    "start": "the console's starting value",
    "owner": "set by you",
}
# The words of a fact's source where the key alone would say less: (fact, source) -> words.
SOURCE_WORDS = {("platform-range", "files"): "from its own platform manifest"}
UNKNOWN_FIELD = "that value is not part of the drafted contract"
EMPTY_VALUE = "type a value"
NOT_OFFERED = "choose one of the offered answers"
COMMAND_UNREADABLE = ("the command could not be read: close every quote and do not end it with a "
                      "backslash")
NOT_JSON = "type it as JSON, or choose one of the offered answers"
NO_DRAFT = "that plan has no drafted contract to change"
REPAIRS = ("adopt.draft.invalid",)
ID_TAKEN = "adopt.draft.id_taken"
# The hooks whose exit status can stop `git commit` (githooks(5): post-commit cannot).
COMMIT_HOOKS: tuple[str, ...] = ("pre-commit", "prepare-commit-msg", "commit-msg")
MAX_LINKS = 8  # tracked links followed from a relative hooks path before the hook is read as absent
# A root file that marks a development environment, and the command that proposes: in priority order.
ENVIRONMENTS: tuple[tuple[str, str], ...] = (("devenv.nix", "devenv shell --"),)
ENVIRONMENT_FIELD = "commit-environment"
PROPOSED: tuple[str, ...] = (ENVIRONMENT_FIELD,)
DIGITS = re.compile(r"^[0-9]+$")


def _none(label: str) -> list[dict]:
    return [{"value": "none", "label": label}]


# id, label, pointers (the first is the field's member), options, text.
_TABLE = (
    ("integration-branch", "main version finished work merges into", ("/bindings/vcs/integration_branch",),
     [], True),
    ("lint-command", "house-rule checks command", ("/bindings/commands/lint",), [], True),
    ("test-command", "test command", ("/bindings/commands/test",), [], True),
    ("release", "how it is released", ("/release",),
     [{"value": "unsupported", "label": "It makes no releases"}], True),
    ("production", "production rules", ("/production",),
     _none("It declares no production rules"), True),
)
# An earlier console's field ids that are no longer drafted: `refresh` drops their saved records.
RETIRED_FIELDS: tuple[str, ...] = (
    "project-id", "project-name", "default-branch", "branch-pattern", "worktree-root",
    "worktree-prefix", "commit-signed", "merge-strategy", "delete-branch", "tracker", "specs-path",
    "plans-path", "docs-paths", "context-paths", "standards-paths", "hints-paths", "operations-paths",
    "rejections-paths", "build-command", "review-plan-command", "review-code-command", "max-parallel",
    "attempt-budget", "projections", "light-lane")
PLAN_AGAIN = ("The console now drafts fewer settings, so the plan is made again: choose the main "
              "version finished work merges into to go on.")
# The field a reconcile plan proposes alone; `draft` never adds it.
_PROPOSED_TABLE = (
    (ENVIRONMENT_FIELD, "changes are saved in its development shell",
     ("/bindings/vcs/commit/environment", "/bindings/commands/commit-environment"),
     _none("Changes are saved outside a development shell"), True),
)
# id, label, the pointers the platform derives for it.
_FACT_TABLE = (
    ("project-identity", "project id and issue tracker",
     ("/project/id", "/bindings/tracker/repo_slug")),
    ("required-checks", "checks a proposed change must pass", ("/bindings/vcs/merge/required_checks",)),
    ("platform-range", "platform versions it runs on", ("/platform",)),
    ("attempt-minutes", "minutes per delivery attempt",
     ("/bindings/workflow/orchestration/attempt_budget_minutes",)),
    ("knowledge-homes", "agent knowledge files it holds", ("/capabilities",)),
)
FIELDS: tuple[str, ...] = tuple(row[0] for row in _TABLE)
FACTS: tuple[str, ...] = tuple(row[0] for row in _FACT_TABLE)
FACT_POINTERS = {row[0]: row[2] for row in _FACT_TABLE}
ASKED = frozenset({"integration-branch", "lint-command", "test-command"})
COMMAND_FIELDS = ("lint-command", "test-command", ENVIRONMENT_FIELD)
JSON_FIELDS = ("release", "production")
LABELS = {**{row[0]: row[1] for row in (*_TABLE, *_PROPOSED_TABLE)},
          **{row[0]: row[1] for row in _FACT_TABLE}}
POINTERS = {row[0]: row[2] for row in (*_TABLE, *_PROPOSED_TABLE)}
OPTIONS = {**{row[0]: row[3] for row in (*_TABLE, *_PROPOSED_TABLE)}, **{f: [] for f in FACTS}}
TEXT = {**{row[0]: row[4] for row in (*_TABLE, *_PROPOSED_TABLE)}, **{f: False for f in FACTS}}
# field -> the value the console starts from; the integration branch and the commands are read, not started.
STARTS = {"release": "unsupported", "production": "none"}
# The more group's start sentences: what a field reads as while it still has its start value.
REST_WORDS = {
    "release": "it makes no releases",
    "production": "it declares no production rules",
}
# The fields and facts that keep their own line.
MAIN: tuple[str, ...] = ("integration-branch", "lint-command", "test-command", *FACTS, ENVIRONMENT_FIELD)
_JSON = "the value as JSON"
PLACEHOLDERS = {
    "integration-branch": "a branch name",
    "lint-command": "the house-rule checks command",
    "test-command": "the test command",
    ENVIRONMENT_FIELD: "the development shell command",
    "release": _JSON,
    "production": _JSON,
}
# The platform home of each knowledge capability a draft declares, by the pointer that names the home.
KNOWLEDGE = (("knowledge.context", "/bindings/paths/context"),
             ("knowledge.standards", "/bindings/paths/standards"),
             ("knowledge.architecture", "/bindings/paths/architecture"),
             ("knowledge.hints", "/bindings/paths/hints"))
JUST_FILES = ("justfile", "Justfile", ".justfile")
MAKE_FILES = ("Makefile", "makefile", "GNUmakefile")
TEXT_FILES = (*JUST_FILES, *MAKE_FILES, "package.json", derived_values.PROTECTION_SOURCE,
              derived_values.LOCK_SOURCE)
NPM = {"lint": "npm run lint", "test": "npm test"}
OTHER_TOOLS = (("Cargo.toml", {"lint": "cargo clippy", "test": "cargo test"}),
               ("go.mod", {"lint": "go vet ./...", "test": "go test ./..."}))


def _home(pointer: str) -> str:
    return schema_three.CONSTANTS[pointer][0]


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def _git(root: str, *arguments: str, extra_env: Mapping[str, str] | None = None,
         cancel: threading.Event | None = None) -> bytes | None:
    """One read-only git child in its own group, so a timeout or a set `cancel` ends its transport children too."""
    if cancel is not None and cancel.is_set():
        return None
    try:
        done = manager.run_in_own_group(
            ["git", "-C", root, *arguments], timeout=GIT_TIMEOUT, cancel=cancel,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", **(extra_env or {})},
            start_new_session=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _lines(output: bytes | None) -> list[str]:
    return output.decode("utf-8", "replace").splitlines() if output else []


def _remotes(root: str, cancel: threading.Event | None = None) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for line in _lines(_git(root, "config", "--get-regexp", r"^remote\..*\.url$", cancel=cancel)):
        key, _, url = line.partition(" ")
        if key.startswith("remote.") and key.endswith(".url") and url.strip():
            found.setdefault(key[len("remote."):-len(".url")], url.strip())
    return sorted(found.items())


def _default_branch(root: str, remotes: list[tuple[str, str]],
                    cancel: threading.Event | None = None) -> str | None:
    if len(remotes) != 1 or remotes[0][0].startswith("-"):
        return None
    lines = _lines(_git(root, "ls-remote", "--symref", remotes[0][0], "HEAD", cancel=cancel))
    match = re.fullmatch(r"ref: refs/heads/(\S.*)\tHEAD", lines[0]) if lines else None
    return match.group(1) if match else None


def _entry(root: str, path: str, cancel: threading.Event | None = None) -> tuple[str, str] | None:
    """The (mode, type) of `path` in the `HEAD` commit, None when it is not there."""
    listed = _git(root, "ls-tree", "--full-tree", "-z", "HEAD", "--", path,
                  extra_env={"GIT_LITERAL_PATHSPECS": "1"}, cancel=cancel)
    if not listed:
        return None
    meta, _, name = listed.split(b"\0")[0].partition(b"\t")
    fields = meta.decode("utf-8", "replace").split()
    if len(fields) < 2 or name.decode("utf-8", "replace") != path:
        return None
    return fields[0], fields[1]


def _repository_hooks_path(root: str, cancel: threading.Event | None = None) -> str | None:
    """The `core.hooksPath` the repository's own config sets (the last one wins).

    Only the `local` scope counts: the fresh linked worktree Apply creates inherits that file, not the
    registration checkout's `config.worktree`, and never a global, system or command-line setting.
    """
    value = None
    for line in _lines(_git(root, "config", "--type=path", "--show-scope", "--get-all", "core.hooksPath",
                            cancel=cancel)):
        scope, _, setting = line.partition("\t")
        if scope == "local":
            value = setting
    return value


def _tracked_target(root: str, path: str, cancel: threading.Event | None = None) -> str | None:
    """The in-tree path of the executable file `HEAD` tracks at `path`, None when it is not one.

    Tracked links are followed on every component.

    Each component is looked up in the `HEAD` tree, as the checkout's filesystem would resolve it: a
    link, whether it ends the path or sits on a directory component, is read and its target spliced in
    (at most `MAX_LINKS` of them); a link that is absolute, empty or leaves the tree reads as absent.
    """
    pending = path.split("/")
    current = ""
    links = 0
    entry: tuple[str, str] | None = None
    target: str | None = None
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not current:
                return None
            current, entry = posixpath.dirname(current), ("040000", "tree")
            continue
        candidate = posixpath.join(current, part)
        entry = _entry(root, candidate, cancel)
        target = candidate
        if entry is None:
            return None
        if entry == ("120000", "blob"):
            links += 1
            if links > MAX_LINKS:
                return None
            linked = _git(root, "cat-file", "blob", f"HEAD:{candidate}", cancel=cancel)
            text = linked.decode("utf-8", "replace") if linked else ""
            if not text or posixpath.isabs(text):
                return None
            pending[:0] = text.split("/")
        elif entry[1] == "tree":
            current = candidate
        elif pending:
            return None
    return target if entry == ("100755", "blob") else None


def _hook_sources(root: str, cancel: threading.Event | None = None) -> list[tuple[str, Path | str]]:
    """The name and source of each `COMMIT_HOOKS` hook that will run when Apply commits in its fresh worktree.

    A source is the hook's `Path` in the hooks directory, or the in-tree path `HEAD` tracks it at.

    The hooks directory is the repository's own: a global, system or command-line `core.hooksPath`
    never counts, while Git's checkout trust (`safe.directory`) is kept. A relative `core.hooksPath`
    is resolved in each checkout, so its hook counts only when `HEAD` tracks it as an executable file
    (or as a link, inside the tree, to one); a path that cannot be verified against `HEAD` has no hooks.
    """
    setting = _repository_hooks_path(root, cancel)
    if setting is not None and not posixpath.isabs(setting):
        tracked = [(name, _tracked_target(root, f"{setting}/{name}", cancel)) for name in COMMIT_HOOKS]
        return [(name, target) for name, target in tracked if target is not None]
    if setting is None:
        printed = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", cancel=cancel)
        if not printed:
            return []
        directory = Path(printed.decode("utf-8", "replace").rstrip("\n")) / "hooks"
    else:
        directory = Path(setting)
    if cancel is not None and cancel.is_set():
        return []
    return [(name, directory / name) for name in COMMIT_HOOKS
            if (directory / name).is_file() and os.access(directory / name, os.X_OK)]


def _environments(root: str, cancel: threading.Event | None = None) -> list[str]:
    """The `ENVIRONMENTS` files in the `HEAD` commit, the revision Apply's worktree starts from."""
    return [name for name, _ in ENVIRONMENTS
            if _entry(root, name, cancel) in (("100644", "blob"), ("100755", "blob"))]


def _tree_platform_version(root: str, files: list[str], cancel: threading.Event | None) -> str | None:
    """The `platform_version` of the manifest the tree tracks at `HEAD`, None when there is none."""
    if derived_values.TREE_MANIFEST not in files:
        return None
    body = _git(root, "show", f"HEAD:{derived_values.TREE_MANIFEST}", cancel=cancel)
    try:
        document = json.loads(body[:TEXT_LIMIT]) if body is not None else None
    except (ValueError, RecursionError):
        return None
    version = document.get("platform_version") if isinstance(document, dict) else None
    return version if isinstance(version, str) and parse_semver(version) is not None else None


def _platform_version() -> str | None:
    try:
        version = agent_platform.load_manifest()[0].get("platform_version")
    except Exception:  # an unreadable manifest is a platform range that cannot be derived
        return None
    return version if isinstance(version, str) else None


def _conformance(root: str, branch: str | None, committed: str | None,
                 cancel: threading.Event | None) -> tuple[str | None, bool]:
    """`(protection_after, pins_platform)`: what adopting `root` writes of the protection file, and whether it pins."""
    try:
        head = _git(root, "rev-parse", "--verify", "HEAD^{commit}", cancel=cancel)
        if head is None or (cancel is not None and cancel.is_set()):
            return committed, False
        plan = adopt_conformance.plan_conformance(
            Path(root), head.decode("ascii").strip(),
            {"schema_version": 3, "bindings": {"vcs": {"integration_branch": branch or "main"}}}, {})
        written = plan.contents.get(adopt_conformance.PROTECTION_FILE)
        return (written.decode("utf-8", "replace") if written is not None else committed,
                plan.member is not None)
    except Exception:  # a conformance that cannot be planned changes nothing the draft shows
        return committed, False


def _origin_slug(remotes: list[tuple[str, str]]) -> str | None:
    url = dict(remotes).get("origin")
    return derived_values.normalize_remote_url(url) if url else None


def read(root: str, cancel: threading.Event | None = None) -> dict:
    """What the repository says: remotes, default branch, branches, files, texts and what adoption derives.

    A set `cancel` ends the running git child's whole group and reads the rest as empty.
    """
    try:
        remotes = _remotes(root, cancel)
        branches = _lines(_git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads",
                               cancel=cancel))
        listed = _git(root, "ls-files", "-z", cancel=cancel)
        files = [part for part in listed.decode("utf-8", "replace").split("\0") if part] if listed else []
        texts: dict[str, str] = {}
        for name in TEXT_FILES:
            if name in files:
                body = _git(root, "show", f"HEAD:{name}", cancel=cancel)
                if body is not None:
                    texts[name] = body[:TEXT_LIMIT].decode("utf-8", "replace")
        default = _default_branch(root, remotes, cancel)
        after, pins = _conformance(root, default, texts.get(derived_values.PROTECTION_SOURCE), cancel)
        budget = attempt_history.read(Path(root), _origin_slug(remotes))
        return {"remotes": remotes, "default_branch": default, "branches": branches, "files": files,
                "texts": texts, "platform_version": _platform_version(),
                "tree_platform_version": _tree_platform_version(root, files, cancel),
                "protection_after": after, "pins_platform": pins,
                "attempt": {"minutes": budget.minutes,
                            "source": "history" if budget.basis.get("source") == "history" else "fallback"}}
    except Exception:  # read never raises: an unreadable repository reads as empty
        return {"remotes": [], "default_branch": None, "branches": [], "files": [], "texts": {},
                "platform_version": None, "tree_platform_version": None, "protection_after": None,
                "pins_platform": False,
                "attempt": {"minutes": attempt_history.FALLBACK_MINUTES, "source": "fallback"}}


_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_EXEC = re.compile(r"^exec\s+(.*)$")
_IF = re.compile(r"^if \[ [^;&|<>`(){}]* \]; then$")
_VARIABLE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
_SHELL_SYNTAX = set("$`;&|<>()")
_SHELLS = ("sh", "bash", "dash", "zsh")


def _runner_found(candidate: str, search_path: str) -> bool:
    if candidate.startswith("/"):
        return os.path.isfile(candidate) and os.access(candidate, os.X_OK)
    return shutil.which(candidate, path=search_path) is not None


def _shell_shebang(line: str) -> bool:
    words = line[2:].split()
    if words and posixpath.basename(words[0]) == "env":
        words = words[1:]
    return bool(words) and posixpath.basename(words[0]) in _SHELLS


def _closing(text: str, index: int, quote: bool) -> int | None:
    """The index after the `)` (or, when `quote`, the `"`) that ends what `text[index:]` opens, else `None`.

    Reads one balanced `$( )` quote-aware, so a quoted or nested parenthesis never ends it; a backtick
    inside, a lone `'`, a `#` that starts a word outside quotes (after a blank or one of `;&|<>()`: a shell
    comment, which would hide the real end) or an unclosed form is `None`.
    """
    start = index
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == "#" and not quote and (
                index == start or text[index - 1].isspace() or text[index - 1] in ";&|<>()"):
            return None
        elif char == "'" and not quote:
            index = text.find("'", index + 1) + 1 or len(text) + 1
        elif char == "`":
            return None
        elif text.startswith("$(", index):
            index = _closing(text, index + 2, False)
            if index is None:
                return None
        elif char == '"':
            if quote:
                return index + 1
            index = _closing(text, index + 1, True)
            if index is None:
                return None
        elif char == "(" and not quote:
            index = _closing(text, index + 1, False)
            if index is None:
                return None
        elif char == ")" and not quote:
            return index + 1
        else:
            index += 1
    return None


def _comment_only(rest: str) -> bool:
    return not rest.strip() or (rest[0].isspace() and rest.lstrip().startswith("#"))


def _assigned_word(value: str) -> tuple[bool, str | None]:
    """`(True, word)` for an assignment of exactly one literal word, `(True, None)` for one substitution.

    The value is one literal word (an unquoted `;`, `&`, `|`, `<`, `>`, parenthesis or backtick, or a `$(`
    or backtick inside double quotes, makes it `(False, None)`), or wholly one balanced `$( )` or backtick
    substitution, quoted or not. Only blanks then a `#` comment may follow; a `#` that starts a word after
    blanks begins a comment, dropped unread, so an apostrophe in it cannot spoil the read, and a `#` inside
    a word is not a comment and the value is not judged.
    """
    for opener, quote in (('"$(', True), ("$(", False)):
        if value.startswith(opener):
            end = _closing(value, len(opener), False)
            if end is not None and quote:
                end = end + 1 if value[end:end + 1] == '"' else None
            return (True, None) if end is not None and _comment_only(value[end:]) else (False, None)
    if value.startswith("`"):
        end = value.find("`", 1) + 1
        return (True, None) if end and "\\" not in value[:end] and _comment_only(value[end:]) \
            else (False, None)
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
            elif quote == '"' and (char == "`" or value.startswith("$(", index)):
                return False, None
        elif char in "'\"":
            quote = char
        elif char in ";&|<>()`" or value.startswith("$(", index):
            return False, None
        elif char == "#":
            if index == 0 or not value[index - 1].isspace():
                return False, None
            value = value[:index]
            break
    try:
        words = shlex.split(value)
    except ValueError:
        return False, None
    return (True, words[0]) if len(words) == 1 and words[0] else (False, None)


def hook_stranded(text: str, search_path: str, cancel: threading.Event | None = None) -> bool:
    """Whether a hook execs a runner that is found neither at its recorded path nor on `search_path`.

    A hook is judged only when every non-comment line has one of the allowlisted shapes (blank; a shell
    shebang; `NAME=value` as above, `PATH`, `path` and `IFS` aside; `if [ ... ]; then`, `else`, `fi`; exactly one line-leading `exec`
    of a word or `"$NAME"` outside any `if`) and each candidate runner is a literal; a runner variable is
    judged only when some line outside any `if` assigns it, and an unquoted one only when no value holds a
    blank or a glob character (the shell would split or expand it). An assignment after the `exec` line
    never runs and is not counted. The module docstring states the allowlist.
    Every other hook is unjudged and never stranded, and so is one read under a set `cancel` or with a
    `search_path` entry that is not absolute.
    """
    if any(not os.path.isabs(entry) for entry in search_path.split(os.pathsep)):
        return False
    assigned: dict[str, dict[str | None, None]] = {}
    fixed: set[str] = set()
    runner = None
    quoted = False
    depth = 0
    for number, raw in enumerate(text.splitlines()):
        if cancel is not None and cancel.is_set():
            return False
        line = raw.strip()
        if number == 0 and raw.startswith("#!"):
            if not _shell_shebang(raw):
                return False
        elif not line or line.startswith("#"):
            pass
        elif _IF.match(line):
            depth += 1
        elif line == "else" and depth:
            pass
        elif line == "fi" and depth:
            depth -= 1
        elif _ASSIGNMENT.match(line):
            name, value = _ASSIGNMENT.match(line).groups()
            known, word = _assigned_word(value)
            if name in ("PATH", "path", "IFS") or not known:
                return False
            if runner is None:  # a line after the `exec` never runs, so it sets no value
                assigned.setdefault(name, {})[word] = None
                if depth == 0:
                    fixed.add(name)
        elif _EXEC.match(line) and runner is None and depth == 0:
            try:
                words = shlex.split(_EXEC.match(line).group(1), comments=True)
            except ValueError:
                return False
            if not words or words[0].startswith("-"):
                return False
            runner = words[0]
            quoted = _EXEC.match(line).group(1).startswith('"')
        else:
            return False
    if runner is None or depth:
        return False
    variable = _VARIABLE.match(runner)
    if variable:
        values = assigned.get(variable.group(1))
        if not values or None in values or variable.group(1) not in fixed:
            return False
        candidates = list(values)
        if not quoted and any(char.isspace() or char in "*?[" for value in candidates for char in value):
            return False
    else:
        candidates = [runner]
    for candidate in candidates:
        if _SHELL_SYNTAX & set(candidate) or ("/" in candidate and not candidate.startswith("/")):
            return False
    return not any(_runner_found(candidate, search_path) for candidate in candidates)


def _hook_text(root: str, source: Path | str, cancel: threading.Event | None = None) -> str:
    """A hook's text, `""` when it is unreadable or above `TEXT_LIMIT` bytes (never a truncated prefix)."""
    if isinstance(source, Path):
        try:
            with source.open("rb") as stream:
                body = stream.read(TEXT_LIMIT + 1)
        except OSError:
            return ""
    else:
        printed = _git(root, "rev-parse", "--verify", f"HEAD:{source}", cancel=cancel)
        blob_id = printed.decode("ascii", "replace").strip() if printed else ""
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", blob_id):
            return ""
        size = _git(root, "cat-file", "-s", blob_id, cancel=cancel)
        if size is None or not re.fullmatch(r"[0-9]+", size.decode("ascii", "replace").strip()) \
                or int(size.decode("ascii").strip()) > TEXT_LIMIT:
            return ""
        blob = _git(root, "cat-file", "blob", blob_id, cancel=cancel)
        body = blob if blob is not None else b""
    return "" if len(body) > TEXT_LIMIT else body.decode("utf-8", "replace")


def read_hooks(root: str, cancel: threading.Event | None = None, *,
               search_path: str | None = None) -> dict:
    """The commit hooks, which of them are stranded, and the environment files: `{hooks, stranded, environments}`.

    Never raises and never writes. `search_path` defaults to the console's own `PATH`.
    """
    path = os.environ.get("PATH", os.defpath) if search_path is None else search_path
    try:
        sources = _hook_sources(root, cancel)
        stranded = [name for name, source in sources
                    if hook_stranded(_hook_text(root, source, cancel), path, cancel)]
        return {"hooks": [name for name, _ in sources], "stranded": stranded,
                "environments": _environments(root, cancel)}
    except Exception:  # read_hooks never raises: an unreadable repository reads as empty
        return {"hooks": [], "stranded": [], "environments": []}


def binds_environment(root: str) -> bool:
    """Whether the contract at `root`, as the resolver fills it, binds `vcs.commit.environment`.

    A schema-3 contract always does (the platform constant `commit-environment`, ADR-project-contract-013 D1-D2);
    any other only when it authors the member.
    """
    try:
        path = Path(root, ".agents/project.json")
        if path.stat().st_size > hook_install.TEXT_LIMIT:
            return False
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if schema_three.declares(document):
        return True
    bindings = document.get("bindings") if isinstance(document, dict) else None
    vcs = bindings.get("vcs") if isinstance(bindings, dict) else None
    commit = vcs.get("commit") if isinstance(vcs, dict) else None
    return isinstance(commit, dict) and "environment" in commit


def hooks_missing(root: str, cancel: threading.Event | None = None) -> bool:
    """Whether `HEAD` tracks a `devenv.nix` declaring git hooks that this host has not installed."""
    try:
        if cancel is not None and cancel.is_set():
            return False
        if _entry(root, "devenv.nix", cancel) not in (("100644", "blob"), ("100755", "blob")):
            return False
        size = _git(root, "cat-file", "-s", "HEAD:devenv.nix", cancel=cancel)
        if size is None or not size.strip().isdigit() or int(size.strip()) > hook_install.TEXT_LIMIT:
            return False
        text = _git(root, "cat-file", "blob", "HEAD:devenv.nix", cancel=cancel)
        if text is None or not hook_install.declares_hooks(text.decode("utf-8", "replace")):
            return False
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", cancel=cancel)
        printed = common.decode("utf-8", "replace").strip() if common else ""
        if not printed:
            return False
        return not hook_install.left_alone(_repository_hooks_path(root, cancel), Path(printed) / "hooks")
    except Exception:  # hooks_missing never raises: an unreadable repository reads as not missing
        return False


# --------------------------------------------------------------------------
# Drafting
# --------------------------------------------------------------------------


_JUST_PARAMETER = r"""[+*$]?[A-Za-z_][\w-]*(?:=(?:'[^']*'|"[^"]*"|`[^`]*`|[^\s:]+))?"""
_JUST_PARAMETERS = re.compile(_JUST_PARAMETER)


def _just_recipe(which: str, text: str) -> bool:
    """True when `text` defines the recipe `which` and `just <which>` runs it with no argument."""
    header = re.compile(rf"^{which}((?:[ \t]+{_JUST_PARAMETER})*)[ \t]*:(?!=)", re.M)
    for found in header.finditer(text):
        if all(item.startswith("*") or "=" in item
               for item in _JUST_PARAMETERS.findall(found.group(1))):
            return True
    return False


def _command(reading: Mapping, which: str) -> str | None:
    files = set(reading.get("files") or ())
    texts = reading.get("texts") or {}
    for name in JUST_FILES:
        if name in files and _just_recipe(which, texts.get(name, "")):
            return f"just {which}"
    for name in MAKE_FILES:
        if name in files and re.search(rf"^{which}:(?!=)", texts.get(name, ""), re.M):
            return f"make {which}"
    if "package.json" in files:
        try:
            scripts = json.loads(texts.get("package.json", "")).get("scripts")
        except (ValueError, RecursionError, AttributeError):
            scripts = None
        if isinstance(scripts, dict) and which in scripts:
            return NPM[which]
    for name, commands in OTHER_TOOLS:
        if name in files:
            return commands[which]
    return None


def _ask(field: str, name: str, remotes: int) -> str:
    if field == "integration-branch":
        tail = ("It has no remote, so the console cannot tell" if remotes == 0 else
                f"It has {remotes} remotes, so the console cannot tell which one to ask"
                if remotes > 1 else "Its remote did not say")
        return (f"Which branch does finished work of {name} merge into?\n"
                f"{tail}: choose a branch or type its name.")
    if field in ("lint-command", "test-command"):
        verb = "runs the house-rule checks of" if field == "lint-command" else "tests"
        return (f"Which command {verb} {name}?\nThe console found none in its files: "
                "type the command that runs it.")
    if field == ENVIRONMENT_FIELD:
        return (f"Which command opens the development shell the changes of {name} are saved in?\n"
                "Its git hooks need its development shell: type the command, or say they need none.")
    if field in FACTS:
        return ""
    return f"What should the {LABELS[field]} of {name} be?"


def _record(field: str, value: str | None, source: str | None, name: str, remotes: int, *,
            options: list | None = None, reason: str | None = None) -> dict:
    return {"field": field, "label": LABELS[field], "value": value, "source": source,
            "options": copy.deepcopy(OPTIONS[field] if options is None else options),
            "text": TEXT[field], "reason": reason, "ask": _ask(field, name, remotes)}


def _environment_record(command: str, name: str, remotes: int) -> dict:
    return _record(ENVIRONMENT_FIELD, command, "files", name, remotes)


def _cannot(words: str) -> tuple[str, None]:
    return words, None


def _identity(reading: Mapping) -> tuple[str, str | None]:
    slug = _origin_slug(list(reading.get("remotes") or ()))
    return (slug, "remote") if slug else _cannot(
        "cannot be derived until its origin remote names a GitHub repository")


def _checks(reading: Mapping) -> tuple[str, str | None]:
    text = reading.get("protection_after")
    if text is None:
        return _cannot(
            f"cannot be derived until {derived_values.PROTECTION_SOURCE} is in the repository")
    try:
        found = derived_values.checks_in(text)
    except derived_values.Underivable as error:
        return _cannot(error.message)
    return (", ".join(found) or "none"), "files"


def _range_words(version: str) -> str:
    interval = derived_values.platform_range(version)
    return f"{interval['min_inclusive']} up to {interval['max_exclusive']}"


def _platform(reading: Mapping) -> tuple[str, str | None]:
    tree, running = reading.get("tree_platform_version"), reading.get("platform_version")
    try:
        if tree:
            return _range_words(tree), "files"
        if reading.get("pins_platform") and running:
            return _range_words(running), "lock"
    except derived_values.Underivable as error:
        return _cannot(error.message)
    if derived_values.LOCK_SOURCE in (reading.get("files") or ()):
        return _cannot(
            f"cannot be derived until {derived_values.LOCK_SOURCE} can pin the agent platform")
    return _cannot(f"cannot be derived until {derived_values.LOCK_SOURCE} is in the repository")


def _attempt(reading: Mapping) -> tuple[str, str | None]:
    found = reading.get("attempt") or {}
    minutes = found.get("minutes", attempt_history.FALLBACK_MINUTES)
    return str(minutes), "history" if found.get("source") == "history" else "platform"


def _homes(reading: Mapping) -> tuple[str, str | None]:
    files = list(reading.get("files") or ())
    held = [home for _, pointer in KNOWLEDGE
            for home in (_home(pointer),)
            if any(path == home or path.startswith(home + "/") for path in files)]
    return (", ".join(held) or "none"), "files"


def facts(root: str, reading: Mapping) -> list[dict]:
    """One fact record per `FACTS`, each from what the adoption would write (never a tracked file alone)."""
    derived = {"project-identity": _identity, "required-checks": _checks, "platform-range": _platform,
               "attempt-minutes": _attempt, "knowledge-homes": _homes}
    return [_record(field, *derived[field](reading), Path(root).name, 0) for field in FACTS]


def with_facts(fields: Iterable[Mapping], reading: Mapping, root: str) -> list[dict]:
    """`fields` followed by the facts of `reading`."""
    return [*(dict(f) for f in fields), *facts(root, reading)]


def has_facts(fields: Iterable[Mapping]) -> bool:
    return any(f["field"] in FACTS for f in fields)


def _violations(error: Mapping) -> list[Mapping]:
    found = error.get("violations")
    return [v for v in found if isinstance(v, Mapping) and isinstance(v.get("pointer"), str)
            ] if isinstance(found, list) else []


def fact_refused(error: Mapping) -> bool:
    """Whether an adoption refusal is about the project id it derived or only about derived values."""
    if error.get("repair_id") == ID_TAKEN:
        return True
    members = [member for pointers in FACT_POINTERS.values() for member in pointers]
    violations = _violations(error)
    return (error.get("repair_id") == "adopt.draft.invalid" and bool(violations)
            and len(violations) == len(error["violations"])
            and all(any(_matches(v["pointer"], member) for member in members) for v in violations))


def draft(root: str, reading: Mapping) -> list[dict]:
    """The five fields, filled from the reading and the console's starting values, then the facts."""
    remotes = len(reading.get("remotes") or ())
    name = Path(root).name
    branch = reading.get("default_branch")
    values: dict[str, tuple[str | None, str | None]] = {
        field: (value, "start") for field, value in STARTS.items()}
    values["integration-branch"] = (branch, "remote" if branch else None)
    for field, which in (("lint-command", "lint"), ("test-command", "test")):
        found = _command(reading, which)
        values[field] = (found, "files" if found else None)
    fields = []
    for field in FIELDS:
        options = None
        if field == "integration-branch":
            options = [{"value": b, "label": b} for b in reading.get("branches") or ()]
        fields.append(_record(field, *values[field], name, remotes, options=options))
    return [*fields, *facts(root, reading)]


def reconcile_fields(root: str, reading: Mapping) -> list[dict]:
    """The one `commit-environment` record a reconcile plan proposes, `[]` when no stranded hook needs it."""
    environments = reading.get("environments") or ()
    if not reading.get("stranded"):
        return []
    command = next((command for name, command in ENVIRONMENTS if name in environments), None)
    return [] if command is None else [_environment_record(command, Path(root).name, 1)]


def amends(fields: object) -> bool:
    """Whether `fields` is an amendment: a non-empty list of only `PROPOSED` records."""
    return (isinstance(fields, list) and bool(fields)
            and all(isinstance(f, Mapping) and f.get("field") in PROPOSED for f in fields))


def environment(fields: Iterable[Mapping]) -> str | None:
    """The command the `commit-environment` record names, None when it has none or says `none`."""
    value = next((f["value"] for f in fields if f["field"] == ENVIRONMENT_FIELD), None)
    return None if value is None or value == "none" else value


def carried(fields: list[dict] | None, plan: Mapping) -> list[dict] | None:
    """`fields`, or None when an amendment's environment is missing from a plan that carries no error."""
    if (fields is not None and amends(fields) and environment(fields) is not None
            and "error" not in plan and "commit_environment" not in (plan.get("plan") or {})):
        return None
    return fields


def _remote_count(fields: list[Mapping]) -> int:
    """The remotes the draft was made from, as an earlier card recorded them."""
    for field in fields:
        if field["field"] in ("integration-branch", "default-branch", "project-id"):
            if "has no remote" in field["ask"]:
                return 0
            found = re.search(r"It has (\d+) remotes", field["ask"])
            if found:
                return int(found.group(1))
    return 1


def _carry(fields: list[dict], name: str, remotes: int) -> list[dict]:
    """A saved draft of an earlier table on today's: its values where they still mean the same."""
    saved = {f["field"]: f for f in fields}
    branch = saved.get("integration-branch")
    earlier = saved.get("default-branch")
    if branch is not None and isinstance(branch["value"], str) and branch["value"]:
        kept = _record("integration-branch", branch["value"], branch["source"], name, remotes,
                       options=branch["options"], reason=branch["reason"])
    else:
        source = earlier or branch or {"value": None, "source": None, "options": []}
        kept = _record("integration-branch", source["value"], source["source"], name, remotes,
                       options=source["options"],
                       reason=branch["reason"] if branch is not None else None)
    carried_over = [kept]
    for field in ("lint-command", "test-command", "release", "production"):
        found = saved.get(field)
        if found is None or (field == "test-command" and found["value"] in (None, "none")):
            value, source = (None, None) if field in ASKED else (STARTS[field], "start")
            carried_over.append(_record(field, value, source, name, remotes))
        else:
            carried_over.append(_record(field, found["value"], found["source"], name, remotes,
                                        reason=found["reason"]))
    return [*carried_over, *(_record(f["field"], f["value"], f["source"], name, remotes)
                             for f in fields if f["field"] in FACTS)]


# Refusals and the replan sentence an earlier console saved in a draft, by the words it used then.
LEGACY_REASONS = (
    ("The plan refused the lint command:", f"The plan refused the {LABELS['lint-command']}:"),
    ("The plan refused the commits run in its development shell:",
     f"The plan refused the {LABELS[ENVIRONMENT_FIELD]}:"),
    ("choose the branch finished work merges into to go on.", PLAN_AGAIN.split(": ", 1)[1]),
    ("The plan refused the branch finished work merges into:",
     f"The plan refused the {LABELS['integration-branch']}:"),
)


def current_reason(reason: object) -> object:
    """A saved refusal in the words of today."""
    if not isinstance(reason, str):
        return reason
    for old, new in LEGACY_REASONS:
        reason = reason.replace(old, new)
    return reason


def refresh(root: str, fields: Iterable[Mapping]) -> list[dict]:
    """A saved draft with today's wording and fields: labels, option labels, card questions and refusals.

    An amendment keeps its records. Any other draft is carried onto `FIELDS` and its saved facts.
    """
    return [{**f, "reason": current_reason(f["reason"])} for f in _refreshed(root, fields)]


def _refreshed(root: str, fields: Iterable[Mapping]) -> list[dict]:
    fields = [dict(f) for f in fields]
    remotes, name = _remote_count(fields), Path(root).name
    if not amends(fields):
        return _carry(fields, name, remotes)
    fields = [f for f in fields if f["field"] in LABELS]
    for field in fields:
        known = field["field"]
        if not isinstance(field["options"], list):
            continue
        current = {o["value"]: o["label"] for o in OPTIONS[known]}
        field["label"] = LABELS[known]
        field["ask"] = _ask(known, name, remotes)
        field["options"] = [{**o, "label": current.get(o.get("value"), o.get("label"))}
                            if isinstance(o, dict) else o for o in field["options"]]
    return fields


def retired_in_use(fields: Iterable[Mapping]) -> bool:
    """Whether a saved draft holds an earlier field whose value or refusal a stored plan may rest on."""
    return any(f["field"] in RETIRED_FIELDS and (f["value"] not in (None, "none")
                                                 or f["reason"] is not None) for f in fields)


def replanned(fields: Iterable[Mapping]) -> list[dict]:
    """The fields with the integration branch's card open to plan again, unless a card is already open."""
    fields = list(fields)
    return fields if open_fields(fields) else mark_refused(fields, "integration-branch", PLAN_AGAIN)


def open_fields(fields: Iterable[Mapping]) -> list[dict]:
    return [dict(f) for f in fields
            if (f["value"] is None and f["field"] in ASKED) or f["reason"] is not None]


def questions(fields: Iterable[Mapping]) -> list[dict]:
    return [{"id": QUESTION_ID, "subject": f["field"], "ask": f["ask"],
             "options": copy.deepcopy(f["options"]), "recommended": None, "why": f["reason"],
             "text": f["text"]} for f in open_fields(fields)]


def _display(field: Mapping) -> str:
    value = field["value"]
    if field["field"] == "project-identity" and field["source"] is not None:
        return f"GitHub, as {value}"
    if field["field"] == ENVIRONMENT_FIELD and isinstance(value, str):
        return value.removesuffix(" --")
    return str(value)


def placeholder(field: str) -> str | None:
    """The words a typed card's empty box shows, None for a field that is not typed."""
    return PLACEHOLDERS[field] if TEXT[field] else None


def _more(fields: list[dict]) -> list[dict]:
    still_open = {f["field"] for f in open_fields(fields)}
    return [f for f in fields if f["field"] not in still_open and f["field"] not in MAIN]


def _at_start(field: Mapping) -> bool:
    return field["value"] == STARTS.get(field["field"])


def _line(field: Mapping) -> str:
    if field["field"] not in MAIN and _at_start(field):
        return REST_WORDS[field["field"]]
    words = SOURCE_WORDS.get((field["field"], field["source"]), SOURCES.get(field["source"], ""))
    return f"{field['label']}: {_display(field)}" + (f" ({words})" if words else "")


def shown(fields: Iterable[Mapping]) -> list[dict]:
    fields = list(fields)
    still_open = {f["field"] for f in open_fields(fields)}
    return [{"field": f["field"], "line": _line(f), "value": f["value"],
             "options": copy.deepcopy(f["options"]), "text": f["text"],
             "more": f["field"] not in MAIN, "fact": f["field"] in FACTS,
             "placeholder": placeholder(f["field"])}
            for f in fields if f["field"] not in still_open]


def proposed_lines(fields: object) -> list[str]:
    """The shown line of each proposed field a draft holds, in `PROPOSED` order."""
    if not isinstance(fields, list):
        return []
    lines = {entry["field"]: entry["line"] for entry in shown(fields)}
    return [lines[field] for field in PROPOSED if field in lines]


def more_line(fields: Iterable[Mapping]) -> str | None:
    """The counted line for the shown settings outside `MAIN`, None when there are none."""
    more = _more(list(fields))
    count, set_by_you = len(more), sum(1 for f in more if f["source"] != "start")
    if not count:
        return None
    if set_by_you == 0:
        return ("and 1 more setting at its usual value" if count == 1
                else f"and {count} more settings at their usual values")
    return ("and 1 more setting, set by you" if count == 1
            else f"and {count} more settings, {set_by_you} of them set by you")


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------


def _parses(value: str) -> bool:
    try:
        json.loads(value, object_pairs_hook=canonical.reject_duplicate_keys,
                   parse_constant=canonical.reject_nonfinite_literal)
    except (ValueError, RecursionError):
        return False
    return True


def set_value(fields: Iterable[Mapping], field: str, value: str) -> tuple[list[dict] | None, str | None]:
    """The fields with `field` set by the owner, or `(None, text)` saying why not."""
    fields = list(fields)
    if (field not in FIELDS and field not in PROPOSED) or not any(
            record["field"] == field for record in fields):
        return None, UNKNOWN_FIELD
    value = value.strip()
    if not value:
        return None, EMPTY_VALUE
    offered = [option["value"] for option in OPTIONS[field]]
    if not TEXT[field] and value not in offered:
        return None, NOT_OFFERED
    if field in ("lint-command", "test-command") and value.lower() == "none":
        what = "the house-rule checks" if field == "lint-command" else "the tests"
        return None, f"Every project has a command that runs {what}: type that command."
    new = []
    for record in fields:
        record = copy.deepcopy(dict(record))
        if record["field"] == field:
            record.update(value=value, source="owner", reason=None)
        new.append(record)
    if field in COMMAND_FIELDS and value != "none":
        try:
            shlex.split(value)
        except ValueError:
            return None, COMMAND_UNREADABLE
    if field in JSON_FIELDS and value not in offered and not _parses(value):
        return None, NOT_JSON
    return new, None


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def _json(value: str):
    return json.loads(value, object_pairs_hook=canonical.reject_duplicate_keys,
                      parse_constant=canonical.reject_nonfinite_literal)


def contract(fields: Iterable[Mapping]) -> dict:
    """The drafted contract in the wire format; total on a list `draft`, `set_value` or `refresh` made."""
    v = {f["field"]: f["value"] for f in fields}
    commands = {}
    for field, key in (("lint-command", "lint"), ("test-command", "test")):
        if v.get(field) not in (None, "none"):
            commands[key] = {"argv": shlex.split(v[field])}
    homes = {home.strip() for home in (v.get("knowledge-homes") or "none").split(",")}

    def support(on: bool) -> dict:
        return {"support": "supported" if on else "unsupported"}

    release = v.get("release", STARTS["release"])
    production = v.get("production", STARTS["production"])
    return {
        "schema_version": schema_three.SCHEMA_VERSION,
        "bindings": {"vcs": {"integration_branch": v.get("integration-branch")}, "commands": commands},
        "capabilities": {
            "tracker": support(True),
            "worktrees": support(True),
            **{name: support(_home(pointer) in homes) for name, pointer in KNOWLEDGE},
            "verification": support(True),
            "review.plan": support(True),
            "review.code": support(True),
        },
        "projections": [],
        "release": "unsupported" if release in (None, "unsupported") else _json(release),
        **({} if production in (None, "none") else {"production": _json(production)}),
    }


# --------------------------------------------------------------------------
# Refusals and identity
# --------------------------------------------------------------------------


def _matches(pointer: str, candidate: str) -> bool:
    return pointer == candidate or pointer.startswith(candidate + "/")


def refused_field(error: Mapping) -> tuple[str, str] | None:
    """The field an adoption refusal names, and the plain words saying so, else None."""
    if error.get("repair_id") not in REPAIRS:
        return None
    for violation in _violations(error):
        pointer = violation["pointer"]
        best, size = None, -1
        for field in (*FIELDS, *PROPOSED):
            for candidate in POINTERS[field]:
                if _matches(pointer, candidate) and len(candidate) > size:
                    best, size = field, len(candidate)
        if best is not None:
            message = " ".join(str(violation.get("message", "")).split())
            return best, f"The plan refused the {LABELS[best]}: {message}"
    return None


def mark_refused(fields: Iterable[Mapping], field: str, reason: str) -> list[dict]:
    marked = []
    for record in fields:
        record = copy.deepcopy(dict(record))
        if record["field"] == field:
            record["reason"] = reason
        marked.append(record)
    return marked


def draft_id(root: str, fields: Iterable[Mapping]) -> str:
    return "draft:" + canonical.telemetry_digest({"root": root, "fields": list(fields)})
