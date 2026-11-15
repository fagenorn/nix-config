"""The console's drafted project contract for a repository that has none (#1067).

Decided in ADR-console-031. The plain words and the main/more split are ADR-console-033. A repository with no `.agents/project.json` is registered with a contract
the console drafts from what the repository says and what the owner answers. This module reads the
repository, drafts the 29 fields of the contract, words the open ones as cards, takes the owner's
answers, and renders the wire-format contract that `adopt-project plan --contract-draft` takes. It
judges only what it must to stay total (the project id's shape, the registry, a command that
`shlex` can read, JSON that parses): every other value is the resolver's to judge (plan D2).

Reading. `read(root)` returns `{"remotes": [(name, url)], "default_branch", "branches", "files",
"texts"}` and never raises and never writes. Every git child has no shell, `stdin` and `stderr` to
`DEVNULL`, `GIT_TIMEOUT` (10 seconds) and `GIT_TERMINAL_PROMPT=0`; an `OSError`, a timeout or a
non-zero exit reads as empty or None. Remotes are the authored URLs (`config --get-regexp`, before
`insteadOf`), sorted by name, one URL per name. The default branch is asked of the remote only when
there is exactly one (`ls-remote --symref`). Branches are the local heads, files the tracked paths,
texts the tracked build files (`justfile`, `Makefile`, `package.json` and their spellings), at most
65536 bytes each.

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
gives every other field as one entry that can be changed. `MAIN` lists the seven fields read from the
repository or asked; each of them is one line `<label>: <display> (<source>)`. Every other field has
the flag `more` in `shown`, and while its value is its start value its line is its start sentence
(`REST_WORDS`, plain words with no source), so it reads as a settled default; once it is another value
it reads `<label>: <value> (<source>)`. `more_line` counts those shown `more` entries in one line,
`and <n> more settings at their usual values`, or `and <n> more settings, <k> of them set by you`.
`placeholder` gives a typed field the words its empty box shows (`PLACEHOLDERS`), None for a choice.
Every label is plain words, never a contract term.

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
the adoption plan adds it.

Refusals. `refused_field(error)` maps an `adopt.draft.invalid` or `adopt.draft.id_taken` error to the
field its first matching violation names (the longest matching pointer wins) and the one wording `The
plan refused the <label>: <message>`; `mark_refused` opens that field's card with it as the reason.
No text here carries a pointer or a repair id.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path

from agent_tools import canonical
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
FIELDS: tuple[str, ...] = tuple(row[0] for row in _TABLE)
ASKED = frozenset({"project-id", "default-branch", "tracker", "build-command", "test-command"})
COMMAND_FIELDS = ("build-command", "test-command", "review-plan-command", "review-code-command")
JSON_FIELDS = ("light-lane", "projections", "release")
LABELS = {row[0]: row[1] for row in _TABLE}
POINTERS = {row[0]: row[2] for row in _TABLE}
OPTIONS = {row[0]: row[3] for row in _TABLE}
TEXT = {row[0]: row[4] for row in _TABLE}
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
                         "build-command", "test-command")
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


def _git(root: str, *arguments: str) -> bytes | None:
    try:
        done = subprocess.run(
            ["git", "-C", root, *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT, shell=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _lines(output: bytes | None) -> list[str]:
    return output.decode("utf-8", "replace").splitlines() if output else []


def _remotes(root: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for line in _lines(_git(root, "config", "--get-regexp", r"^remote\..*\.url$")):
        key, _, url = line.partition(" ")
        if key.startswith("remote.") and key.endswith(".url") and url.strip():
            found.setdefault(key[len("remote."):-len(".url")], url.strip())
    return sorted(found.items())


def _default_branch(root: str, remotes: list[tuple[str, str]]) -> str | None:
    if len(remotes) != 1 or remotes[0][0].startswith("-"):
        return None
    lines = _lines(_git(root, "ls-remote", "--symref", remotes[0][0], "HEAD"))
    match = re.fullmatch(r"ref: refs/heads/(\S.*)\tHEAD", lines[0]) if lines else None
    return match.group(1) if match else None


def read(root: str) -> dict:
    """What the repository says: remotes, default branch, local branches, tracked files and texts."""
    try:
        remotes = _remotes(root)
        branches = _lines(_git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads"))
        listed = _git(root, "ls-files", "-z")
        files = [part for part in listed.decode("utf-8", "replace").split("\0") if part] if listed else []
        texts: dict[str, str] = {}
        for name in TEXT_FILES:
            if name in files:
                body = _git(root, "show", f"HEAD:{name}")
                if body is not None:
                    texts[name] = body[:TEXT_LIMIT].decode("utf-8", "replace")
        return {"remotes": remotes, "default_branch": _default_branch(root, remotes),
                "branches": branches, "files": files, "texts": texts}
    except Exception:  # read never raises: an unreadable repository reads as empty
        return {"remotes": [], "default_branch": None, "branches": [], "files": [], "texts": {}}


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
    return f"What should the {LABELS[field]} of {name} be?"


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
    held = taken_id(fields, entries, root)
    if held is not None:
        fields[0]["reason"] = held
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
    if field not in FIELDS:
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
    github = v["tracker"] == "github"
    default = v["default-branch"]
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
                    "commit": {"co_authored_by": _flag(v["co-authored-by"]),
                               "signed": _flag(v["commit-signed"])},
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
        for field in FIELDS:
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
