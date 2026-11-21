"""The console's drafted project contract for a repository that has none (#1067).

Decided in ADR-console-031. The plain words and the main/more split are ADR-console-033. The proposed
commit environment is ADR-console-082. A repository with no `.agents/project.json` is registered with a contract
the console drafts from what the repository says and what the owner answers. This module reads the
repository, drafts the 29 fields of the contract, words the open ones as cards, takes the owner's
answers, and renders the wire-format contract that `adopt-project plan --contract-draft` takes. It
judges only what it must to stay total (the project id's shape, the registry, a command that
`shlex` can read, JSON that parses): every other value is the resolver's to judge (plan D2).

Reading. `read(root)` returns `{"remotes": [(name, url)], "default_branch", "branches", "files",
"texts", "hooks", "environments"}` and never raises and never writes. Every git child has no shell, `stdin` and `stderr` to
`DEVNULL`, `GIT_TIMEOUT` (10 seconds), `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1`; an `OSError`,
a timeout or a non-zero exit reads as empty or None. Remotes are the authored URLs (`config --get-regexp`, before
`insteadOf`), sorted by name, one URL per name. The default branch is asked of the remote only when
there is exactly one (`ls-remote --symref`). Branches are the local heads, files the tracked paths,
texts the tracked build files (`justfile`, `Makefile`, `package.json` and their spellings), at most
65536 bytes each. `hooks` are the `COMMIT_HOOKS` names (`pre-commit`, `prepare-commit-msg`,
`commit-msg`; never `post-commit`, which cannot stop a commit) installed as executable files in the
repository's own hooks directory (the `core.hooksPath` its own configuration sets, else its
`hooks` directory; a global, system or command-line hooks path never counts, and Git's checkout trust
is kept), in `COMMIT_HOOKS` order. A relative `core.hooksPath` is resolved in each checkout, so such a
hook counts only when `HEAD` tracks it as an executable file or as a link inside the tree to one. `environments` are the `ENVIRONMENTS`
file names present in the `HEAD` commit as a regular file (the revision Apply's worktree starts from,
so an untracked, staged-only or directory entry never counts), in `ENVIRONMENTS` order. A set cancel
reads both as empty, as it reads the rest.

`read_hooks(root, cancel, *, search_path=None)` reads the same `hooks` and `environments` and adds
`stranded`, as `{"hooks", "stranded", "environments"}`; it never raises and never writes. `stranded`
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

Fields. `FIELDS` lists the 29 field ids in order; each is a record with exactly the keys
`FIELD_KEYS`: `field`, `label`, `value` (a str or None), `source` (a key of `SOURCES` or None),
`options` (`{"value", "label"}` rows), `text` (a typed value is accepted), `reason` (why its card is
open though it has a value) and `ask` (its card's question, fixed by `draft` so it never changes
with later answers). `draft(root, reading, entries=())` fills each from the remote (the project id,
its name, the default branch, the GitHub tracker), the tracked files (the documentation paths, the
build and test commands) or the console's starting value, and opens the project id's card with
`taken(<id>)` when the id it read is registered for another checkout. A field is open (`open_fields`)
when it has no value and is one of `ASKED` (the project id, the default branch, the tracker, the build
and test commands), or when it has a `reason`; `questions` words each open field as one card; `shown`
gives every other field as one entry that can be changed. `refresh(root, fields)` gives a saved draft today's
label, option labels and card question (ADR-console-033) without touching a value, a source or a reason. `MAIN` lists the seven fields read from the
repository or asked; each of them is one line `<label>: <display> (<source>)`. Every other field has
the flag `more` in `shown`, and while its value is its start value its line is its start sentence
(`REST_WORDS`, plain words with no source), so it reads as a settled default; once it is another value
it reads `<label>: <value> (<source>)`. `more_line` counts those shown `more` entries in one line,
`and <n> more settings at their usual values`, or `and <n> more settings, <k> of them set by you`.
`placeholder` gives a typed field the words its empty box shows (`PLACEHOLDERS`), None for a choice.
Every label is plain words, never a contract term.

Proposed field. `PROPOSED` lists the fields `draft` adds after the 29 only when proposed: today the
`commit-environment` field (`commits run in its development shell`), drafted with the command of the first
`ENVIRONMENTS` file in `reading["environments"]` (source `files`) when `reading["hooks"]` is not empty,
and never otherwise, so a draft without it is exactly the 29 records. It is a main field, a typed
choice with the one option `none`, never open. Its shown line leaves a trailing `--` off the command
(`devenv shell`); the value and the command the contract names keep it. `proposed_lines(fields)` gives
the `shown` line of each `PROPOSED` field present in a draft list, in `PROPOSED` order, `[]` for a
non-list or a draft without one; the ready Apply card shows them first.

A reconcile plan proposes the same field alone (#1333). `reconcile_fields(root, reading)` is `[]`
unless `reading["stranded"]` is not empty and an `ENVIRONMENTS` file is in `reading["environments"]`;
otherwise it is the one `commit-environment` record `draft` would add, built by the same helper.
`amends(fields)` is true for a non-empty list whose every record is a `PROPOSED` field, which no
`draft` list is. `environment(fields)` is that record's value, None when it is None or `none`.
`carried(fields, plan)` keeps `fields` for a plan, except an amendment that names an environment
which the plan's document does not carry, which is None. The drafted path's `_proposal` is unchanged.

Answers. `set_value(fields, field, value, entries=, root=)` returns `(new_fields, None)` or `(None,
text)`, refusing in order with `UNKNOWN_FIELD`, `EMPTY_VALUE`, `NOT_OFFERED` (a choice field), `ID_RULE`
(two names joined by one slash), `taken(<id>)`, `COMMAND_UNREADABLE` (a command `shlex` cannot read) and
`NOT_JSON`, and never mutates its input. `taken_id` is the registry check. `draft_id` is the digest
of the root and the fields, so two different drafts never share a plan.

Contract. `contract(fields)` is total on every list `draft` and `set_value` produced. It has
`schema_version` 2, `project`, `bindings` (`vcs`, `tracker`, `paths`, `commands`, `workflow`),
`capabilities` (each `{"support": "supported" | "unsupported"}`), `projections` and `release`; a
`none` command is left out, `light_lane` is left out when it is `none`, `yes`/`no` are booleans, a
path list splits on commas, and a count that is all digits is an int. It has no `platform` member:
the adoption plan adds it. A `commit-environment` value other than None or `none` adds the command
`bindings.commands["commit-environment"]` and names it in `bindings.vcs.commit.environment`; it never
changes `workflow.verification` or `capabilities`.

Refusals. `refused_field(error)` maps an `adopt.draft.invalid` or `adopt.draft.id_taken` error to the
field its first matching violation names (the longest matching pointer wins) and the one wording `The
plan refused the <label>: <message>`; `mark_refused` opens that field's card with it as the reason.
No text here carries a pointer or a repair id.
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
from agent_tools.project_contract import adopt_planning
from agent_tools.project_contract.adopt_planning import normalize_remote_url

QUESTION_ID = "contract-draft"
GIT_TIMEOUT = 10
TEXT_LIMIT = 65536
FIELD_KEYS = {"field", "label", "value", "source", "options", "text", "reason", "ask"}
SOURCES = {
    "remote": "read from its remote",
    "files": "found in its files",
    "folder": "taken from its folder name",
    "start": "the console's starting value",
    "owner": "set by you",
}
ID_RULE = "a project id is two names joined by one slash, like owner/name, with no spaces"
UNKNOWN_FIELD = "that value is not part of the drafted contract"
EMPTY_VALUE = "type a value"
NOT_OFFERED = "choose one of the offered answers"
COMMAND_UNREADABLE = ("the command could not be read: close every quote and do not end it with a "
                      "backslash")
NOT_JSON = "type it as JSON, or choose one of the offered answers"
NO_DRAFT = "that plan has no drafted contract to change"
REPAIRS = ("adopt.draft.invalid", "adopt.draft.id_taken")
# The hooks whose exit status can stop `git commit` (githooks(5): post-commit cannot).
COMMIT_HOOKS: tuple[str, ...] = ("pre-commit", "prepare-commit-msg", "commit-msg")
MAX_LINKS = 8  # tracked links followed from a relative hooks path before the hook is read as absent
# A root file that marks a development environment, and the command that proposes: in priority order.
ENVIRONMENTS: tuple[tuple[str, str], ...] = (("devenv.nix", "devenv shell --"),)
ENVIRONMENT_FIELD = "commit-environment"
PROPOSED: tuple[str, ...] = (ENVIRONMENT_FIELD,)
ENVIRONMENT_COMMAND = adopt_planning.COMMIT_ENVIRONMENT_ID
ID_PATTERN = re.compile(r"^[^\s/]+/[^\s/]+$")
DIGITS = re.compile(r"^[0-9]+$")


def taken(value: str) -> str:
    return f"{value} is already registered for another checkout"


def _yes_no() -> list[dict]:
    return [{"value": "yes", "label": "yes"}, {"value": "no", "label": "no"}]


def _none(label: str) -> list[dict]:
    return [{"value": "none", "label": label}]


# id, label, pointers (the first is the field's member), options, text.
_TABLE = (
    ("project-id", "project id", ("/project/id", "/bindings/tracker/repo_slug"), [], True),
    ("project-name", "project name", ("/project/name",), [], True),
    ("default-branch", "default branch", ("/bindings/vcs/default_branch",), [], True),
    ("integration-branch", "branch finished work merges into", ("/bindings/vcs/integration_branch",), [], True),
    ("branch-pattern", "work branch names", ("/bindings/vcs/branch_pattern",), [], True),
    ("worktree-root", "folder for work copies",
     ("/bindings/vcs/worktree/root", "/capabilities/worktrees"), [], True),
    ("worktree-prefix", "start of each work copy's name", ("/bindings/vcs/worktree/prefix",), [], True),
    ("commit-signed", "signed commits", ("/bindings/vcs/commit/signed",), _yes_no(), False),
    ("co-authored-by", "co-author lines in commits", ("/bindings/vcs/commit/co_authored_by",),
     _yes_no(), False),
    ("merge-strategy", "how pull requests are merged", ("/bindings/vcs/merge/strategy",), [], True),
    ("delete-branch", "branch deletion after merge", ("/bindings/vcs/merge/delete_branch",),
     _yes_no(), False),
    ("tracker", "issue tracker", ("/bindings/tracker", "/capabilities/tracker"),
     [{"value": "github", "label": "Track its issues on GitHub"},
      {"value": "none", "label": "Track no issues here"}], False),
    ("specs-path", "design specs folder", ("/bindings/paths/artifacts/specs",), [], True),
    ("plans-path", "plans folder", ("/bindings/paths/artifacts/plans",), [], True),
    ("docs-paths", "documentation",
     ("/bindings/paths/architecture", "/capabilities/knowledge.architecture"), [], True),
    ("context-paths", "glossary files",
     ("/bindings/paths/context", "/capabilities/knowledge.context"), [], True),
    ("standards-paths", "coding standards files",
     ("/bindings/paths/standards", "/capabilities/knowledge.standards"), [], True),
    ("hints-paths", "notes that guide agents", ("/bindings/paths/hints", "/capabilities/knowledge.hints"),
     [], True),
    ("operations-paths", "notes on how it is run", ("/bindings/paths/operations",), [], True),
    ("rejections-paths", "records of ruled-out ideas", ("/bindings/paths/rejections",), [], True),
    ("build-command", "build command",
     ("/bindings/commands/build", "/bindings/workflow/verification", "/capabilities/verification"),
     _none("It has no build command"), True),
    ("test-command", "test command", ("/bindings/commands/test",),
     _none("It has no test command"), True),
    ("review-plan-command", "plan review command",
     ("/bindings/commands/review-plan", "/bindings/workflow/review/plan",
      "/capabilities/review.plan"), _none("It has no plan review command"), True),
    ("review-code-command", "code review command",
     ("/bindings/commands/review-code", "/bindings/workflow/review/code",
      "/capabilities/review.code"), _none("It has no code review command"), True),
    ("max-parallel", "deliveries at once",
     ("/bindings/workflow/orchestration/max_parallel",), [], True),
    ("attempt-budget", "minutes per delivery attempt",
     ("/bindings/workflow/orchestration/attempt_budget_minutes",), [], True),
    ("light-lane", "short route for light changes", ("/bindings/workflow/light_lane",),
     _none("Every change takes the full delivery route"), True),
    ("projections", "generated agent files", ("/projections",),
     _none("It generates no agent instruction files"), True),
    ("release", "how it is released", ("/release",),
     [{"value": "unsupported", "label": "It makes no releases"}], True),
)
# Fields `draft` adds only when proposed; they are not among the 29 `FIELDS`.
_PROPOSED_TABLE = (
    (ENVIRONMENT_FIELD, "commits run in its development shell",
     ("/bindings/vcs/commit/environment", "/bindings/commands/commit-environment"),
     _none("Commits run outside a development shell"), True),
)
FIELDS: tuple[str, ...] = tuple(row[0] for row in _TABLE)
ASKED = frozenset({"project-id", "default-branch", "tracker", "build-command", "test-command"})
COMMAND_FIELDS = ("build-command", "test-command", "review-plan-command", "review-code-command",
                  ENVIRONMENT_FIELD)
JSON_FIELDS = ("light-lane", "projections", "release")
LABELS = {row[0]: row[1] for row in (*_TABLE, *_PROPOSED_TABLE)}
POINTERS = {row[0]: row[2] for row in (*_TABLE, *_PROPOSED_TABLE)}
OPTIONS = {row[0]: row[3] for row in (*_TABLE, *_PROPOSED_TABLE)}
TEXT = {row[0]: row[4] for row in (*_TABLE, *_PROPOSED_TABLE)}
# field -> (value, source) the console starts from; the project id, name, default branch, tracker,
# documentation paths and the build and test commands are read, not started.
STARTS = {
    "integration-branch": None,
    "branch-pattern": "issue-<num>-<slug>",
    "worktree-root": ".worktrees",
    "worktree-prefix": "worktree-",
    "commit-signed": "no",
    "co-authored-by": "no",
    "merge-strategy": "merge",
    "delete-branch": "yes",
    "specs-path": ".agents/artifacts/specs",
    "plans-path": ".agents/artifacts/plans",
    "context-paths": "none",
    "standards-paths": "none",
    "hints-paths": "none",
    "operations-paths": "none",
    "rejections-paths": "none",
    "review-plan-command": "none",
    "review-code-command": "none",
    "max-parallel": "1",
    "attempt-budget": "240",
    "light-lane": "none",
    "projections": "none",
    "release": "unsupported",
}
# The more group's start sentences: what a field reads as while it still has its start value.
REST_WORDS = {
    "integration-branch": "finished work merges into the default branch",
    "branch-pattern": "work branches are named after their issue",
    "worktree-root": "each piece of work gets its own copy of the repository in the .worktrees folder",
    "worktree-prefix": "each work copy's folder name starts with worktree-",
    "commit-signed": "commits are not signed",
    "co-authored-by": "commits carry no co-author lines",
    "merge-strategy": "pull requests are merged with a merge commit",
    "delete-branch": "a work branch is deleted once it is merged",
    "specs-path": "design specs are kept in .agents/artifacts/specs",
    "plans-path": "plans are kept in .agents/artifacts/plans",
    "context-paths": "no glossary files are named",
    "standards-paths": "no coding standards files are named",
    "hints-paths": "no notes that guide agents are named",
    "operations-paths": "no notes on how it is run are named",
    "rejections-paths": "no records of ruled-out ideas are named",
    "review-plan-command": "no command reviews its plans",
    "review-code-command": "no command reviews its code",
    "max-parallel": "one delivery runs at a time",
    "attempt-budget": "a delivery attempt may take up to 240 minutes",
    "light-lane": "every change takes the full delivery route",
    "projections": "it generates no agent instruction files",
    "release": "it makes no releases",
}
# The fields whose values are read from the repository or asked: they keep their own line.
MAIN: tuple[str, ...] = ("project-id", "project-name", "default-branch", "tracker", "docs-paths",
                         "build-command", "test-command", ENVIRONMENT_FIELD)
_JSON = "the value as JSON"
PLACEHOLDERS = {
    "project-id": "owner/name",
    "project-name": "the project name",
    "default-branch": "a branch name",
    "integration-branch": "a branch name",
    "branch-pattern": "a branch name pattern",
    "worktree-root": "a folder in the repository",
    "specs-path": "a folder in the repository",
    "plans-path": "a folder in the repository",
    "worktree-prefix": "the start of each folder name",
    "merge-strategy": "the merge method",
    "docs-paths": "paths, separated by commas",
    "context-paths": "paths, separated by commas",
    "standards-paths": "paths, separated by commas",
    "hints-paths": "paths, separated by commas",
    "operations-paths": "paths, separated by commas",
    "rejections-paths": "paths, separated by commas",
    "build-command": "the build command",
    "test-command": "the test command",
    ENVIRONMENT_FIELD: "the development shell command",
    "review-plan-command": "the review command",
    "review-code-command": "the review command",
    "max-parallel": "a number",
    "attempt-budget": "a number of minutes",
    "light-lane": _JSON,
    "projections": _JSON,
    "release": _JSON,
}
DOC_FILES = ("README.md", "README", "README.rst", "ARCHITECTURE.md", "CONTEXT.md")
JUST_FILES = ("justfile", "Justfile", ".justfile")
MAKE_FILES = ("Makefile", "makefile", "GNUmakefile")
TEXT_FILES = (*JUST_FILES, *MAKE_FILES, "package.json")
NPM = {"build": "npm run build", "test": "npm test"}
OTHER_TOOLS = (("Cargo.toml", {"build": "cargo build", "test": "cargo test"}),
               ("go.mod", {"build": "go build ./...", "test": "go test ./..."}))


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


def _hooks(root: str, cancel: threading.Event | None = None) -> list[str]:
    """The `COMMIT_HOOKS` that will run when Apply commits in its fresh worktree of `HEAD`."""
    return [name for name, _ in _hook_sources(root, cancel)]


def _environments(root: str, cancel: threading.Event | None = None) -> list[str]:
    """The `ENVIRONMENTS` files in the `HEAD` commit, the revision Apply's worktree starts from."""
    return [name for name, _ in ENVIRONMENTS
            if _entry(root, name, cancel) in (("100644", "blob"), ("100755", "blob"))]


def read(root: str, cancel: threading.Event | None = None) -> dict:
    """What the repository says: remotes, default branch, branches, files, texts, hooks, environments.

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
        return {"remotes": remotes, "default_branch": _default_branch(root, remotes, cancel),
                "branches": branches, "files": files, "texts": texts,
                "hooks": _hooks(root, cancel), "environments": _environments(root, cancel)}
    except Exception:  # read never raises: an unreadable repository reads as empty
        return {"remotes": [], "default_branch": None, "branches": [], "files": [], "texts": {},
                "hooks": [], "environments": []}


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


def _host(url: str) -> str | None:
    value = url.strip()
    if value.startswith("git@"):
        host, separator, _ = value[len("git@"):].partition(":")
        return host.lower() if separator and host else None
    if "://" in value:
        authority = value.partition("://")[2].partition("/")[0]
        host = authority.rpartition("@")[2].partition(":")[0]
        return host.lower() or None
    return None


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


def _docs(files: list) -> str:
    found = [name for name in DOC_FILES if name in files]
    if any(str(path).startswith("docs/") for path in files):
        found.append("docs")
    return ", ".join(found) if found else "none"


def _resolved(path: object) -> Path | None:
    try:
        return Path(str(path)).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _held(project_id: str | None, entries: Iterable[Mapping], root: str) -> str | None:
    if project_id is None:
        return None
    here = _resolved(root)
    for entry in entries:
        if entry.get("project_id") == project_id and _resolved(entry.get("root")) != here:
            return taken(project_id)
    return None


def taken_id(fields: Iterable[Mapping], entries: Iterable[Mapping], root: str) -> str | None:
    """`taken(<id>)` when the project id is registered for another checkout, else None."""
    value = next((f["value"] for f in fields if f["field"] == "project-id"), None)
    return _held(value, entries, root)


def _ask(field: str, name: str, remotes: int) -> str:
    if field == "project-id":
        tail = ("It has no remote that names it" if remotes == 0 else
                f"It has {remotes} remotes, so the console cannot tell which one names it"
                if remotes > 1 else "Its remote does not name a project")
        return f"Which project is this repository?\n{tail}: type its id, as owner/name."
    if field == "default-branch":
        tail = ("It has no remote, so the console cannot tell" if remotes == 0 else
                f"It has {remotes} remotes, so the console cannot tell which one to ask"
                if remotes > 1 else "Its remote did not say")
        return (f"Which branch is the default branch of {name}?\n"
                f"{tail}: choose a branch or type its name.")
    if field == "tracker":
        return f"Where are the issues of {name} tracked?"
    if field in ("build-command", "test-command"):
        verb = "builds" if field == "build-command" else "tests"
        return (f"Which command {verb} {name}?\nThe console found none in its files: "
                "type the command, or say it has none.")
    if field == ENVIRONMENT_FIELD:
        return (f"Which command opens the development shell the commits of {name} run in?\n"
                "Its commit hooks need its development shell: type the command, or say they need none.")
    return f"What should the {LABELS[field]} of {name} be?"


def _proposal(reading: Mapping) -> str | None:
    """The command commits run through, when a development environment and a commit hook exist."""
    environments = reading.get("environments") or ()
    if not reading.get("hooks"):
        return None
    return next((command for name, command in ENVIRONMENTS if name in environments), None)


def _environment_record(command: str, name: str, remotes: int) -> dict:
    return {"field": ENVIRONMENT_FIELD, "label": LABELS[ENVIRONMENT_FIELD],
            "value": command, "source": "files",
            "options": copy.deepcopy(OPTIONS[ENVIRONMENT_FIELD]),
            "text": TEXT[ENVIRONMENT_FIELD], "reason": None,
            "ask": _ask(ENVIRONMENT_FIELD, name, remotes)}


def draft(root: str, reading: Mapping, *, entries: Iterable[Mapping] = ()) -> list[dict]:
    """The 29 fields, filled from the reading and the console's starting values."""
    remotes = list(reading.get("remotes") or ())
    name = Path(root).name
    read_id = None
    if len(remotes) == 1:
        read_id = normalize_remote_url(remotes[0][1])
    github = (len(remotes) == 1 and read_id is not None and _host(remotes[0][1]) == "github.com")
    values: dict[str, tuple[str | None, str | None]] = {
        field: (value, "start") for field, value in STARTS.items()}
    values["project-id"] = (read_id, "remote" if read_id else None)
    values["project-name"] = ((read_id.partition("/")[2], "remote") if read_id
                              else (name, "folder"))
    branch = reading.get("default_branch")
    values["default-branch"] = (branch, "remote" if branch else None)
    values["tracker"] = ("github", "remote") if github else (None, None)
    values["docs-paths"] = (_docs(list(reading.get("files") or ())), "files")
    for field, which in (("build-command", "build"), ("test-command", "test")):
        found = _command(reading, which)
        values[field] = (found, "files" if found else None)
    fields = []
    for field in FIELDS:
        options = copy.deepcopy(OPTIONS[field])
        if field == "default-branch":
            options = [{"value": b, "label": b} for b in reading.get("branches") or ()]
        value, source = values[field]
        fields.append({"field": field, "label": LABELS[field], "value": value, "source": source,
                       "options": options, "text": TEXT[field], "reason": None,
                       "ask": _ask(field, name, len(remotes))})
    proposal = _proposal(reading)
    if proposal is not None:
        fields.append(_environment_record(proposal, name, len(remotes)))
    held = taken_id(fields, entries, root)
    if held is not None:
        fields[0]["reason"] = held
    return fields


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
    """The remotes the draft was made from, as the project id's card recorded them."""
    ask = next((f["ask"] for f in fields if f["field"] == "project-id"), "")
    if "has no remote" in ask:
        return 0
    found = re.search(r"It has (\d+) remotes", ask)
    return int(found.group(1)) if found else 1


def refresh(root: str, fields: Iterable[Mapping]) -> list[dict]:
    """A saved draft with today's wording: label, option labels and card question, values untouched."""
    fields = [dict(f) for f in fields]
    remotes, name = _remote_count(fields), Path(root).name
    for field in fields:
        known = field["field"]
        if known not in LABELS or not isinstance(field["options"], list):
            continue
        current = {o["value"]: o["label"] for o in OPTIONS[known]}
        field["label"] = LABELS[known]
        field["ask"] = _ask(known, name, remotes)
        field["options"] = [{**o, "label": current.get(o.get("value"), o.get("label"))}
                            if isinstance(o, dict) else o for o in field["options"]]
    return fields


def open_fields(fields: Iterable[Mapping]) -> list[dict]:
    return [dict(f) for f in fields
            if (f["value"] is None and f["field"] in ASKED) or f["reason"] is not None]


def questions(fields: Iterable[Mapping]) -> list[dict]:
    return [{"id": QUESTION_ID, "subject": f["field"], "ask": f["ask"],
             "options": copy.deepcopy(f["options"]), "recommended": None, "why": f["reason"],
             "text": f["text"]} for f in open_fields(fields)]


def _display(field: Mapping, fields: Iterable[Mapping]) -> str:
    value = field["value"]
    if field["field"] == "tracker" and value == "github":
        slug = next(f["value"] for f in fields if f["field"] == "project-id")
        return f"GitHub, as {slug}"
    if field["field"] == "integration-branch" and value is None:
        return "the same as the default branch"
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


def _line(field: Mapping, fields: list[dict]) -> str:
    if field["field"] not in MAIN and _at_start(field):
        return REST_WORDS[field["field"]]
    return f"{field['label']}: {_display(field, fields)} ({SOURCES.get(field['source'], '')})"


def shown(fields: Iterable[Mapping]) -> list[dict]:
    fields = list(fields)
    still_open = {f["field"] for f in open_fields(fields)}
    return [{"field": f["field"], "line": _line(f, fields), "value": f["value"],
             "options": copy.deepcopy(f["options"]), "text": f["text"],
             "more": f["field"] not in MAIN, "placeholder": placeholder(f["field"])}
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


def set_value(fields: Iterable[Mapping], field: str, value: str, *, entries: Iterable[Mapping],
              root: str) -> tuple[list[dict] | None, str | None]:
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
    if field == "project-id" and not ID_PATTERN.match(value):
        return None, ID_RULE
    new = []
    for record in fields:
        record = copy.deepcopy(dict(record))
        if record["field"] == field:
            record.update(value=value, source="owner", reason=None)
        new.append(record)
    if field == "project-id":
        held = taken_id(new, entries, root)
        if held is not None:
            return None, held
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


def _paths(value: str | None) -> list[str]:
    if value is None or value == "none":
        return []
    return [part.strip() for part in value.split(",")]


def _count(value: str | None):
    return int(value) if value is not None and value.isascii() and DIGITS.match(value) else value


def _flag(value: str | None) -> bool:
    return value == "yes"


def contract(fields: Iterable[Mapping]) -> dict:
    """The drafted contract in the wire format; total on a list `draft` or `set_value` made."""
    v = {f["field"]: f["value"] for f in fields}
    commands = {}
    for field, key in (("build-command", "build"), ("test-command", "test"),
                       ("review-plan-command", "review-plan"),
                       ("review-code-command", "review-code")):
        if v[field] is not None and v[field] != "none":
            commands[key] = {"argv": shlex.split(v[field]), "cwd": ".", "env": []}
    verification = [key for key in ("build", "test") if key in commands]
    environment = v.get(ENVIRONMENT_FIELD)
    if environment is not None and environment != "none":
        commands[ENVIRONMENT_COMMAND] = {"argv": shlex.split(environment), "cwd": ".", "env": []}
    github = v["tracker"] == "github"
    default = v["default-branch"]
    commit = {"co_authored_by": _flag(v["co-authored-by"]), "signed": _flag(v["commit-signed"])}
    if ENVIRONMENT_COMMAND in commands:
        commit["environment"] = ENVIRONMENT_COMMAND
    workflow = {
        "verification": verification,
        "orchestration": {"max_parallel": _count(v["max-parallel"]),
                          "attempt_budget_minutes": _count(v["attempt-budget"])},
        "review": {"plan": "review-plan" if "review-plan" in commands else None,
                   "code": "review-code" if "review-code" in commands else None},
    }
    if v["light-lane"] not in (None, "none"):
        workflow["light_lane"] = _json(v["light-lane"])

    def support(on: bool) -> dict:
        return {"support": "supported" if on else "unsupported"}

    return {
        "schema_version": 2,
        "project": {"id": v["project-id"], "name": v["project-name"]},
        "bindings": {
            "vcs": {"kind": "git", "default_branch": default,
                    "integration_branch": v["integration-branch"] or default,
                    "branch_pattern": v["branch-pattern"],
                    "worktree": {"root": v["worktree-root"], "prefix": v["worktree-prefix"]},
                    "commit": commit,
                    "merge": {"strategy": v["merge-strategy"],
                              "delete_branch": _flag(v["delete-branch"])}},
            "tracker": {"kind": "github" if github else "none", "cli": "gh" if github else "none",
                        "repo_slug": v["project-id"],
                        "credential_env": {"unset_before_invocation": []}},
            "paths": {"artifacts": {"specs": v["specs-path"], "plans": v["plans-path"]},
                      "context": _paths(v["context-paths"]),
                      "standards": _paths(v["standards-paths"]),
                      "architecture": _paths(v["docs-paths"]),
                      "operations": _paths(v["operations-paths"]),
                      "hints": _paths(v["hints-paths"]),
                      "rejections": _paths(v["rejections-paths"])},
            "commands": commands,
            "workflow": workflow,
        },
        "capabilities": {
            "tracker": support(github),
            "worktrees": support(True),
            "knowledge.context": support(bool(_paths(v["context-paths"]))),
            "knowledge.standards": support(bool(_paths(v["standards-paths"]))),
            "knowledge.architecture": support(bool(_paths(v["docs-paths"]))),
            "knowledge.hints": support(bool(_paths(v["hints-paths"]))),
            "verification": support(bool(verification)),
            "review.plan": support("review-plan" in commands),
            "review.code": support("review-code" in commands),
        },
        "projections": [] if v["projections"] in (None, "none") else _json(v["projections"]),
        "release": "unsupported" if v["release"] in (None, "unsupported") else _json(v["release"]),
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
    violations = error.get("violations")
    for violation in violations if isinstance(violations, list) else ():
        pointer = violation.get("pointer") if isinstance(violation, Mapping) else None
        if not isinstance(pointer, str):
            continue
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
