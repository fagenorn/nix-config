"""The `verify` block grammar: parsing a hold comment and checking its structure.

`verify-pending` (issue 625, parent 572) gives the pending check of a held issue one strict,
machine-readable form, the verify block, and refuses at hold time the avoidable holds the history
study found. This module is the pure policy (`parse_block`, `lint_block`, `count_since`) and the
one home of the grammar; `agent_tools.verification.verify_pending` is the thin shell that parses argv, reads the
input, builds the real reference lookups and prints the verdict. The lint is read-only: it never
runs a check and never calls `gh`. Its only child processes are the `git` probes below, and only
when `--repo-root` is given.

`parse_block` extracts the block from a hold comment (or a bare JSON text) and
`lint_block` walks it, collecting every finding as `{"field", "code",
"message"}`. A finding's `field` is a path into the block
(`checks[0].when.not_before`); an unknown member's path is its own path.

Where a block lives. A verify block sits in the hold comment, as the one fenced block whose info
string is `verify` (a line of three backticks plus `verify`, closed by a line of three backticks,
either line allowing trailing spaces or tabs, and CRLF line endings read as LF). Only a comment
whose author association is `OWNER` or `MEMBER` carries a block the runner trusts, and a block
trusts only installed or committed code, never code in the comment. That holds by construction:
the run forms are an allowlist (below), so a block can name a contract command, a committed script
or a built-in probe, and nothing else. `lint --input <path|->` reads either a whole hold comment
or a bare JSON block; with no fence the whole input is the block, two or more fences are refused
(`block`, `fence_count`), and JSON that is unparsable or not strict (a repeated key, `NaN`,
nesting too deep to decode, a string holding a lone surrogate) is refused (`block`, `not_json`).

Fields. The top level holds `v` (the integer 1), `merge` (the merge commit, a 40-character
lowercase hex sha) and `checks` (a non-empty list). A check holds `ac` (an acceptance criterion id
such as `AC1`), `kind` (`evidence` or `human`), `host` (a hostname, `any`, or a non-empty list of
distinct hostnames), `when`, `run`, and the optional `expect`, `effects`, `mode`, `on_fail`,
`expires_after_days`, `on_expire` and `reason`. Every object is closed: a member outside the
grammar is refused `unknown_field`, a missing required one `missing_field`, a malformed value
`invalid_value`. The optional fields default as follows, and the defaults are documented, not
enforced by the lint (the runner applies them): `effects: none` (the others are `live` and
`paid`), `mode: assert` (`observe` reports a metric instead of gating), `on_fail: label` (or
`ask`), `expires_after_days: 21` counted from when the check became due (an integer of at least
1), `on_expire: close` (closed as not verified; or `ask`).

`when`. A non-empty object of these members: `deployed_includes` and `released_includes` (a sha),
`ci_run_includes` (`{workflow, branch, sha}`, all three required), `not_before` (an ISO 8601 time
that carries a UTC offset) and `days_after` (`{event, days}` with `event` one of `deployed` or
`released` and `days` an integer of at least 1).

`run`. Exactly one form key, else `run_form` at the run. The system forms are an allowlist of
three; a run of any other shape, such as `{"tool": "git", ...}`, `{"tool": "python3", "args":
["-c", ...]}`, `nix`, `gh`, `curl` or a shell, is refused `run_form`, because the lint does not
try to tell safe arguments of a general tool from code-carrying ones.

- `{"command"}` runs a command id declared in the project contract (`bindings.commands`) with its
  declared argv and nothing else. `args` on a command is `inline_code` at `<run>.args`: a declared
  argv is often a `just` recipe, which pastes its parameters into shell lines unquoted and runs a
  surplus argument as another recipe, so no appended argument is data. A `command` that is not an
  id is `inline_code`.
- `{"script", "at"?, "args"?}` runs a file committed in the repository, executed directly (no
  shell, no interpreter in the block), resolved at `at` or, without `at`, at the block's `merge`.
  `script` is a relative POSIX path with no empty, `.` or `..` segment, no backslash and no NUL
  (else `inline_code`); at the commit it must be a regular file committed with mode `100755` at
  exactly that path, so a missing path, a directory, a non-executable file, a symbolic link (one
  pointing outside the repository included) and a path through a symlinked directory are each
  `not_committed`. `args` is a list of strings, handed to the committed script as data.
- `{"probe", ...parameters}` runs a built-in read-only probe of `verify-pending` by name; its
  parameters are data members of the run object, closed per probe (`unknown_field`,
  `missing_field`, `invalid_value`): `deployed_includes` `{sha}` (the check's host runs a
  deployment that includes `sha`), `released_includes` `{sha}` (the latest release includes `sha`),
  `ci_run_includes` `{workflow, branch, sha}` (a run of that workflow on that branch at that sha
  passed), and `count_since` `{source, since, n, workflow?, branch?}` (at least `n` runs or
  releases strictly after `since`, through `count_since` below; `source` is `runs`, which needs
  `workflow` and takes an optional `branch`, or `releases`, which takes neither). Runs are read
  from that workflow's own run listing, so `workflow` names its file (or id), and a listing the
  forge truncated below its `total_count` is refused as a forge error rather than counted low. An
  unknown probe name is `invalid_value` at `<run>.probe`.

Two owner forms need a person: `{"ask"}` is a non-empty single-line question for the owner, and
`{"act", "then"}` is a non-empty single-line instruction for the owner followed by a system run
(`then` takes no `ask` and no nested `act`, else `run_form` at `<run>.then`). A member outside the
chosen form is `unknown_field`. A system run ends with exit 0 (met), 1 (not met) or 75 (not yet);
these meanings are fixed and not configurable. `expect` is optional and, when present, is
`{"json": [test, ...]}` over the run's JSON output, each test `{"pointer", "equals"}` or
`{"pointer", "min_len"}`, with `pointer` either `""` or starting with `/`.

Kind and run agree. An `ask` or `act` run needs the owner, so it requires `kind: human`; a
`command`, `script` or `probe` run is something the system runs, so it requires `kind: evidence`.
A mismatch is `kind_mismatch` at `checks[i].kind`, which keeps an owner-needing check from dodging
the `reason` rule by calling itself `evidence`. A `human` check needs a `reason` from the set
`senses`, `hands`, `credentials`, `money` and `taste` (else `reason_required`); an `evidence`
check takes none (`reason_not_allowed`). A check whose `effects` is `paid` or `live` must name
exactly one host, so `any` and a list are refused `host_not_concrete`. An `ask` that,
case-insensitively, asks for approval of a document (an approval word together with `design`,
`adr`, `runbook`, `path list`, `paths`, `spec` or `plan`) is refused `approval_ask`.

References must resolve. Checked after the shape rules, and an unconfirmable reference is refused
(fail closed). A `command` needs `--repo-root`: the project contract is resolved in process
through `resolve_project.resolve` and the id must be a member of `bindings.commands` (else
`not_declared` at `<run>.command`; without `--repo-root`, or when resolution is refused,
`unverified_reference`). A `script` needs `--repo-root` too, and is looked up with `git ls-tree`
at its commit: a commit absent from the repository is `unverified_reference` at `<run>.at` (or at
`merge` when the script takes the merge commit), a path that is not an executable committed file
is `not_committed` at `<run>.script`, and no `--repo-root` is `unverified_reference` at
`<run>.script`. A probe references nothing outside the block.

Context options. Three refusals depend on facts only the caller knows. `--code-unmet ID`
(repeatable) refuses the block once, `code_unmet`, because an acceptance criterion that is unmet
in code cannot be held for verification. `--pr-workflow NAME` (repeatable, the pull request's
required workflows) with `--pr-head SHA` or `--pr-branch NAME` refuses `pre_merge_only` at
`checks[i].when` an `evidence` check that awaits only a `ci_run_includes` of one of those
workflows at that head or on that branch, since a run of the pull request cannot be observed after
the merge; the same workflow awaited on another branch at another revision is a post-merge
observation and is accepted, and `--pr-workflow` with neither is a usage error. Three warnings
leave the block accepted: `--blocks ISSUE` (repeatable) warns `ask_blocks_issues` at
`checks[i].run.ask` for each `ask` check, because it holds the issue open and blocks the named
issues; `--repo-root PATH` (which must be a git work tree, else exit 2) with a block whose `merge`
is a valid sha and a check that has `deployed_includes` warns `no_flake_at_merge` at
`checks[i].when.deployed_includes` when the merge commit has no `flake.nix`, or once
`merge_not_found` at `merge` when the repository does not have the commit (the repository cannot
say, so no flake warning).

Verdict. stdout is one line, `json.dumps(verdict, sort_keys=True)`: `{"ok", "errors", "warnings"}`,
each finding `{"field", "code", "message"}`, `field` a path into the block
(`checks[0].when.deployed_includes`, `checks[0].run.command`) and `ok` true exactly when `errors`
is empty. Every finding is collected, in traversal order. The exit status is 0 when the block is
accepted (warnings allowed), 1 when it is refused, and 2 on a usage error, an unreadable input, a
`--repo-root` that is not a git work tree, a `--pr-head` that is not a sha, or `--pr-workflow`
without `--pr-head` or `--pr-branch`. The error codes are closed: `not_json`, `fence_count`,
`unknown_field`, `missing_field`, `invalid_value`, `host_not_concrete`, `reason_required`,
`reason_not_allowed`, `kind_mismatch`, `run_form`, `inline_code`, `not_declared`, `not_committed`,
`unverified_reference`, `approval_ask`, `pre_merge_only` and `code_unmet`; the warning codes are
`ask_blocks_issues`, `no_flake_at_merge` and `merge_not_found`. No other code is emitted.

`count_since(timestamps, since, n)` counts the aware ISO timestamps strictly after `since` and
returns 0 when the count is at least `n`, else 75 ("not yet", never a failure); an `n` below 1, or
a naive or unparsable time, raises `ValueError`. The `count_since` probe uses it, and a check
script answers "at least N runs since T" with `verify-pending count-since --input <path|-> --since
T --n N [--key K]` (the command is in `agent_tools.verification.verify_pending`).

The block below is the host-bound deploy check; `lint` accepts it, and the test file pins that,
and that the same block with an inline `python3 -c` run in place of the probe is refused
`run_form` at `checks[0].run`.

```verify
{
  "v": 1,
  "merge": "0123456789abcdef0123456789abcdef01234567",
  "checks": [
    {
      "ac": "AC1",
      "kind": "evidence",
      "host": "mbp",
      "when": {"deployed_includes": "0123456789abcdef0123456789abcdef01234567"},
      "run": {"probe": "deployed_includes", "sha": "0123456789abcdef0123456789abcdef01234567"}
    }
  ]
}
```
"""

import json
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

SHA = re.compile(r"^[0-9a-f]{40}$")
HOST = re.compile(r"^[a-z0-9-]+$")
AC = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
REASONS = ("senses", "hands", "credentials", "money", "taste")

FENCE = re.compile(r"(?ms)^```verify[ \t]*\n(.*?)^```[ \t]*$")

TOP_FIELDS = ("v", "merge", "checks")
TOP_REQUIRED = ("v", "merge", "checks")
CHECK_FIELDS = (
    "ac", "kind", "host", "when", "run", "expect", "effects", "mode",
    "on_fail", "expires_after_days", "on_expire", "reason",
)
CHECK_REQUIRED = ("ac", "kind", "host", "when", "run")
WHEN_FIELDS = ("deployed_includes", "released_includes", "ci_run_includes", "not_before", "days_after")
CI_FIELDS = ("workflow", "branch", "sha")
DAYS_AFTER_FIELDS = ("event", "days")
EXPECT_FIELDS = ("json",)
TEST_FIELDS = ("pointer", "equals", "min_len")

KINDS = ("evidence", "human")
EFFECTS = ("none", "live", "paid")
MODES = ("assert", "observe")
ON_FAIL = ("label", "ask")
ON_EXPIRE = ("close", "ask")
EVENTS = ("deployed", "released")

# The allowlist: a run is a contract command, a committed script or a built-in probe (or an owner step).
RUN_FORMS = ("command", "script", "probe", "ask", "act")
SYSTEM_FORMS = ("command", "script", "probe")
RUN_MEMBERS = {
    "command": ("command", "args"),  # `args` is refused with its own finding
    "script": ("script", "at", "args"),
    "ask": ("ask",),
    "act": ("act", "then"),
}
# Built-in read-only probes: each one's parameters are data members of the run, `(required, optional)`.
PROBES = {
    "deployed_includes": (("sha",), ()),
    "released_includes": (("sha",), ()),
    "ci_run_includes": (("workflow", "branch", "sha"), ()),
    "count_since": (("source", "since", "n"), ("workflow", "branch")),
}
COUNT_SOURCES = ("runs", "releases")
COMMAND_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
APPROVAL_VERB = re.compile(r"\b(approve|approves|approved|approval|sign[- ]?off|lgtm)\b", re.IGNORECASE)
APPROVAL_OBJECT = re.compile(r"\b(design|adr|runbook|path[- ]?list|paths|spec|plan)\b", re.IGNORECASE)


class References(Protocol):
    """What the lint must learn from outside the block (D9); every lookup is tri-state."""

    def command(self, command_id: str) -> str:
        """`"present"`, `"absent"` or `"unknown"`."""

    def script(self, path: str, sha: str) -> tuple[str, str]:
        """`(commit_state, path_state)`; `path_state` is `"present"` (an executable file), `"absent"`,
        `"not_executable"` or `"unknown"`, and `"unknown"` unless the commit is `"present"`."""

    def flake(self, merge: str) -> tuple[str, str] | None:
        """`None` when there is no repository to ask, else the `(commit_state, path_state)` of `flake.nix` at `merge`."""


def finding(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def parse_block(text: str) -> tuple[object | None, list[dict]]:
    """Extract and strictly parse the block; on failure `(None, [finding])`."""
    text = text.replace("\r\n", "\n")  # GitHub keeps a comment edited in the web UI with CRLF endings
    fences = FENCE.findall(text)
    if len(fences) > 1:
        return None, [finding("block", "fence_count", f"{len(fences)} verify fences; exactly one is allowed")]
    body = fences[0] if fences else text
    try:
        block = json.loads(
            body, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal
        )
        # A lone surrogate (`"\udc80"`) decodes but names no path or argument any program can be handed.
        json.dumps(block, ensure_ascii=False).encode("utf-8")
    except (ValueError, RecursionError) as error:
        return None, [finding("block", "not_json", f"the block is not strict JSON: {error}")]
    return block, []


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def is_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def closed_object(value: object, path: str, fields: tuple, required: tuple, errors: list) -> bool:
    """Check `value` is an object with only `fields` and all `required`; True when it is an object."""
    where = path or "block"
    if not isinstance(value, dict):
        errors.append(finding(where, "invalid_value", "must be an object"))
        return False
    for name in value:
        if name not in fields:
            errors.append(finding(join(path, name), "unknown_field", f"{name!r} is not a member of this object"))
    for name in required:
        if name not in value:
            errors.append(finding(join(path, name), "missing_field", f"{name!r} is required"))
    return True


def invalid(errors: list, path: str, message: str) -> None:
    errors.append(finding(path, "invalid_value", message))


def check_iso(value: object, path: str, errors: list) -> None:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        moment = None
    if moment is None:
        invalid(errors, path, "must be an ISO 8601 time")
    elif moment.utcoffset() is None:
        invalid(errors, path, "must carry a UTC offset")


def check_choice(value: object, path: str, choices: tuple, errors: list) -> None:
    if not isinstance(value, str) or value not in choices:
        invalid(errors, path, f"must be one of {', '.join(choices)}")


def check_when(when: object, path: str, errors: list) -> None:
    if not closed_object(when, path, WHEN_FIELDS, (), errors):
        return
    if not when:
        invalid(errors, path, "must not be empty")
        return
    for name in ("deployed_includes", "released_includes"):
        if name in when and not is_sha(when[name]):
            invalid(errors, join(path, name), "must be a 40-character lowercase hex sha")
    if "ci_run_includes" in when:
        ci_path = join(path, "ci_run_includes")
        ci = when["ci_run_includes"]
        if closed_object(ci, ci_path, CI_FIELDS, CI_FIELDS, errors):
            for name in ("workflow", "branch"):
                if name in ci and not is_text(ci[name]):
                    invalid(errors, join(ci_path, name), "must be a non-empty string")
            if "sha" in ci and not is_sha(ci["sha"]):
                invalid(errors, join(ci_path, "sha"), "must be a 40-character lowercase hex sha")
    if "not_before" in when:
        check_iso(when["not_before"], join(path, "not_before"), errors)
    if "days_after" in when:
        days_path = join(path, "days_after")
        days_after = when["days_after"]
        if closed_object(days_after, days_path, DAYS_AFTER_FIELDS, DAYS_AFTER_FIELDS, errors):
            if "event" in days_after:
                check_choice(days_after["event"], join(days_path, "event"), EVENTS, errors)
            if "days" in days_after and not (is_int(days_after["days"]) and days_after["days"] >= 1):
                invalid(errors, join(days_path, "days"), "must be an integer of at least 1")


def check_expect(expect: object, path: str, errors: list) -> None:
    if not closed_object(expect, path, EXPECT_FIELDS, ("json",), errors):
        return
    if "json" not in expect:
        return
    tests_path = join(path, "json")
    tests = expect["json"]
    if not isinstance(tests, list) or not tests:
        invalid(errors, tests_path, "must be a non-empty list of tests")
        return
    for index, test in enumerate(tests):
        test_path = f"{tests_path}[{index}]"
        if not closed_object(test, test_path, TEST_FIELDS, ("pointer",), errors):
            continue
        pointer = test.get("pointer")
        if "pointer" in test and not (isinstance(pointer, str) and (pointer == "" or pointer.startswith("/"))):
            invalid(errors, join(test_path, "pointer"), 'must be "" or start with "/"')
        if ("equals" in test) == ("min_len" in test):
            invalid(errors, test_path, "needs exactly one of equals and min_len")
        elif "min_len" in test and not (is_int(test["min_len"]) and test["min_len"] >= 0):
            invalid(errors, join(test_path, "min_len"), "must be an integer of at least 0")


def check_host(check: dict, path: str, errors: list) -> None:
    host = check["host"]
    host_path = join(path, "host")
    if isinstance(host, str):
        valid = host == "any" or HOST.fullmatch(host) is not None
    elif isinstance(host, list):
        valid = (
            bool(host)
            and all(isinstance(name, str) and HOST.fullmatch(name) for name in host)
            and len(set(host)) == len(host)
        )
    else:
        valid = False
    if not valid:
        invalid(errors, host_path, "must be a hostname, 'any', or a non-empty list of distinct hostnames")
        return
    concrete = isinstance(host, str) and host != "any" and HOST.fullmatch(host) is not None
    if check.get("effects") in ("paid", "live") and not concrete:
        errors.append(finding(host_path, "host_not_concrete", "a live or paid check must name exactly one host"))


def is_relative_posix(path: str) -> bool:
    if path == "" or path.startswith("/") or "\\" in path or "\0" in path:
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def check_args(run: dict, path: str, errors: list) -> None:
    """A script's `args` are data handed to the committed script: a list of strings."""
    if "args" not in run:
        return
    args = run["args"]
    if not (isinstance(args, list) and all(isinstance(arg, str) and "\0" not in arg for arg in args)):
        invalid(errors, join(path, "args"), "must be a list of strings")


def check_single_line(value: object, path: str, errors: list) -> bool:
    if not is_text(value) or "\n" in value or "\r" in value:
        invalid(errors, path, "must be a non-empty single-line string")
        return False
    return True


def check_probe(run: dict, path: str, errors: list) -> None:
    name = run["probe"]
    if not isinstance(name, str) or name not in PROBES:
        invalid(errors, join(path, "probe"), f"must be one of {', '.join(PROBES)}")
        return
    required, optional = PROBES[name]
    for member in run:
        if member != "probe" and member not in required + optional:
            errors.append(finding(join(path, member), "unknown_field", f"{member!r} is not a parameter of the {name} probe"))
    for member in required:
        if member not in run:
            errors.append(finding(join(path, member), "missing_field", f"{member!r} is required"))
    for member in ("workflow", "branch"):
        if member in run and not is_text(run[member]):
            invalid(errors, join(path, member), "must be a non-empty string")
    if "sha" in run and not is_sha(run["sha"]):
        invalid(errors, join(path, "sha"), "must be a 40-character lowercase hex sha")
    if name == "count_since":
        if "source" in run:
            check_choice(run["source"], join(path, "source"), COUNT_SOURCES, errors)
        if "since" in run:
            check_iso(run["since"], join(path, "since"), errors)
        if "n" in run and not (is_int(run["n"]) and run["n"] >= 1):
            invalid(errors, join(path, "n"), "must be an integer of at least 1")
        if run.get("source") == "runs" and "workflow" not in run:
            errors.append(finding(join(path, "workflow"), "missing_field", "counting runs needs 'workflow'"))
        if run.get("source") == "releases":
            for member in ("workflow", "branch"):
                if member in run:
                    errors.append(finding(join(path, member), "unknown_field", "counting releases takes no workflow or branch"))


def check_form(run: object, path: str, merge: object, errors: list, refs: References, allow_interactive: bool) -> None:
    if not isinstance(run, dict):
        invalid(errors, path, "must be an object")
        return
    allowed = RUN_FORMS if allow_interactive else SYSTEM_FORMS
    forms = [form for form in RUN_FORMS if form in run]
    if len(forms) != 1 or forms[0] not in allowed:
        errors.append(finding(path, "run_form", f"needs exactly one of {', '.join(allowed)}; nothing else runs"))
        return
    form = forms[0]
    before = len(errors)
    if form == "probe":
        check_probe(run, path, errors)
        return
    for name in run:
        if name not in RUN_MEMBERS[form]:
            errors.append(finding(join(path, name), "unknown_field", f"{name!r} is not a member of a {form} run"))
    if form == "script":
        script = run["script"]
        if not (isinstance(script, str) and is_relative_posix(script)):
            errors.append(finding(join(path, "script"), "inline_code", "must be a relative path to a file committed in the repository"))
        if "at" in run and not is_sha(run["at"]):
            invalid(errors, join(path, "at"), "must be a 40-character lowercase hex sha")
        check_args(run, path, errors)
    elif form == "command":
        command = run["command"]
        if not isinstance(command, str) or not COMMAND_ID.fullmatch(command):
            errors.append(finding(join(path, "command"), "inline_code", "must be a contract command id"))
        if "args" in run:
            # A declared argv is the whole command: a `just` recipe pastes its parameters into shell
            # lines unquoted and runs a surplus argument as another recipe, so no argument is data.
            errors.append(finding(join(path, "args"), "inline_code", "a contract command runs with its declared argv only"))
    elif form == "ask":
        if check_single_line(run["ask"], join(path, "ask"), errors) and \
                APPROVAL_VERB.search(run["ask"]) and APPROVAL_OBJECT.search(run["ask"]):
            errors.append(finding(join(path, "ask"), "approval_ask", "approval of a document is not a verification question"))
    else:
        check_single_line(run["act"], join(path, "act"), errors)
        if "then" not in run:
            errors.append(finding(join(path, "then"), "missing_field", "'then' is required"))
        else:
            check_form(run["then"], join(path, "then"), merge, errors, refs, False)
    if len(errors) == before:
        check_references(run, form, path, merge, errors, refs)


SCRIPT_STATES = {
    "absent": "the script is not a file committed at that commit (a directory or symbolic link is not one)",
    "not_executable": "the script is committed without the executable bit; it runs directly, with no interpreter",
}


def check_references(run: dict, form: str, path: str, merge: object, errors: list, refs: References) -> None:
    """D9: the reference of a run that passed every other rule must resolve."""
    if form == "command":
        state = refs.command(run["command"])
        if state == "absent":
            errors.append(finding(join(path, "command"), "not_declared", f"{run['command']!r} is not a contract command"))
        elif state != "present":
            errors.append(finding(join(path, "command"), "unverified_reference", "the contract commands could not be read; pass --repo-root"))
    elif form == "script":
        at = run.get("at", merge)
        if not is_sha(at):
            return  # the block's `merge` is invalid and already refused
        at_path = join(path, "at") if "at" in run else "merge"
        commit, found = refs.script(run["script"], at)
        if commit == "absent":
            errors.append(finding(at_path, "unverified_reference", "the commit is not in the repository"))
        elif commit != "present":
            errors.append(finding(join(path, "script"), "unverified_reference", "the script could not be checked; pass --repo-root"))
        elif found in SCRIPT_STATES:
            errors.append(finding(join(path, "script"), "not_committed", SCRIPT_STATES[found]))
        elif found != "present":
            errors.append(finding(join(path, "script"), "unverified_reference", "the script could not be checked"))


def check_run(run: object, path: str, kind: object, merge: object, errors: list, refs: References) -> None:
    if not isinstance(run, dict):
        invalid(errors, path, "must be an object")
        return
    forms = [form for form in RUN_FORMS if form in run]
    if len(forms) != 1:
        errors.append(finding(path, "run_form", f"needs exactly one of {', '.join(RUN_FORMS)}; nothing else runs"))
        return
    if kind in KINDS:
        needs_owner = forms[0] in ("ask", "act")
        if needs_owner != (kind == "human"):
            wanted = "human" if needs_owner else "evidence"
            errors.append(finding(path.rsplit(".", 1)[0] + ".kind", "kind_mismatch", f"a {forms[0]} run needs kind {wanted}"))
    check_form(run, path, merge, errors, refs, True)


def check_reason(check: dict, path: str, errors: list) -> None:
    kind = check.get("kind")
    reason_path = join(path, "reason")
    if kind == "human":
        if check.get("reason") not in REASONS:
            errors.append(finding(reason_path, "reason_required", f"a human check needs a reason, one of {', '.join(REASONS)}"))
    elif kind == "evidence" and "reason" in check:
        errors.append(finding(reason_path, "reason_not_allowed", "an evidence check takes no reason"))


def check_one(check: object, path: str, merge: object, errors: list, refs: References) -> None:
    if not closed_object(check, path, CHECK_FIELDS, CHECK_REQUIRED, errors):
        return
    if "ac" in check and not (isinstance(check["ac"], str) and AC.fullmatch(check["ac"])):
        invalid(errors, join(path, "ac"), "must match [A-Za-z][A-Za-z0-9_.-]*")
    if "kind" in check:
        check_choice(check["kind"], join(path, "kind"), KINDS, errors)
    if "host" in check:
        check_host(check, path, errors)
    if "when" in check:
        check_when(check["when"], join(path, "when"), errors)
    if "run" in check:
        check_run(check["run"], join(path, "run"), check.get("kind"), merge, errors, refs)
    if "expect" in check:
        check_expect(check["expect"], join(path, "expect"), errors)
    for name, choices in (("effects", EFFECTS), ("mode", MODES), ("on_fail", ON_FAIL), ("on_expire", ON_EXPIRE)):
        if name in check:
            check_choice(check[name], join(path, name), choices, errors)
    if "expires_after_days" in check:
        days = check["expires_after_days"]
        if not (is_int(days) and days >= 1):
            invalid(errors, join(path, "expires_after_days"), "must be an integer of at least 1")
    check_reason(check, path, errors)


def valid_checks(block: dict) -> list[tuple[int, dict]]:
    """The `(index, check)` pairs of a block whose checks are objects."""
    checks = block.get("checks")
    if not isinstance(checks, list):
        return []
    return [(index, check) for index, check in enumerate(checks) if isinstance(check, dict)]


def check_pre_merge(block: dict, errors: list, pr_workflows: Sequence[str], pr_head: str | None, pr_branch: str | None) -> None:
    """A check that awaits a CI run of the pull request itself cannot be held after the merge."""
    for index, check in valid_checks(block):
        when = check.get("when")
        if check.get("kind") != "evidence" or not isinstance(when, dict) or set(when) != {"ci_run_includes"}:
            continue
        ci = when["ci_run_includes"]
        if not isinstance(ci, dict) or ci.get("workflow") not in pr_workflows:
            continue
        if (pr_head is not None and ci.get("sha") == pr_head) or (pr_branch is not None and ci.get("branch") == pr_branch):
            errors.append(finding(f"checks[{index}].when", "pre_merge_only", "this run belongs to the pull request, not to the merge commit"))


def check_context(
    block: dict, errors: list, warnings: list, refs: References, code_unmet: Sequence[str],
    pr_workflows: Sequence[str], pr_head: str | None, pr_branch: str | None, blocks: Sequence[str],
) -> None:
    if code_unmet:
        errors.append(finding("code_unmet", "code_unmet", f"acceptance criteria unmet in code: {', '.join(code_unmet)}"))
    if pr_workflows:
        check_pre_merge(block, errors, pr_workflows, pr_head, pr_branch)
    checks = valid_checks(block)
    if blocks:
        for index, check in checks:
            run = check.get("run")
            if isinstance(run, dict) and "ask" in run:
                warnings.append(finding(f"checks[{index}].run.ask", "ask_blocks_issues", f"a human ask holds the issue open and blocks {', '.join(blocks)}"))
    deploys = [index for index, check in checks if isinstance(check.get("when"), dict) and "deployed_includes" in check["when"]]
    if deploys and is_sha(block.get("merge")):
        probe = refs.flake(block["merge"])
        if probe is None:
            return
        commit, found = probe
        if commit != "present":
            warnings.append(finding("merge", "merge_not_found", "the merge commit could not be found in the repository"))
        elif found == "absent":
            for index in deploys:
                warnings.append(finding(f"checks[{index}].when.deployed_includes", "no_flake_at_merge", "the merge commit has no flake.nix to deploy"))


def lint_block(
    block: object,
    *,
    refs: References,
    code_unmet: Sequence[str] = (),
    pr_workflows: Sequence[str] = (),
    pr_head: str | None = None,
    pr_branch: str | None = None,
    blocks: Sequence[str] = (),
) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    if closed_object(block, "", TOP_FIELDS, TOP_REQUIRED, errors):
        if "v" in block and not (is_int(block["v"]) and block["v"] == 1):
            invalid(errors, "v", "must be the integer 1")
        if "merge" in block and not is_sha(block["merge"]):
            invalid(errors, "merge", "must be a 40-character lowercase hex sha")
        if "checks" in block:
            checks = block["checks"]
            if not isinstance(checks, list) or not checks:
                invalid(errors, "checks", "must be a non-empty list of checks")
            else:
                for index, check in enumerate(checks):
                    check_one(check, f"checks[{index}]", block.get("merge"), errors, refs)
        check_context(block, errors, warnings, refs, code_unmet, pr_workflows, pr_head, pr_branch, blocks)
    elif code_unmet:
        check_context({}, errors, warnings, refs, code_unmet, (), None, None, ())
    return {"ok": not errors, "errors": errors, "warnings": warnings}


NOT_YET = 75


def parse_time(value: object) -> datetime:
    """An ISO 8601 time with a UTC offset (`Z` accepted) as an aware datetime; ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError(f"not a time string: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"time has no UTC offset: {value!r}")
    return parsed


def count_after(timestamps: Iterable[str], since: str) -> int:
    """How many of `timestamps` fall strictly after `since`; ValueError on an unusable time."""
    start = parse_time(since)
    return sum(1 for stamp in map(parse_time, timestamps) if stamp > start)


def count_since(timestamps: Iterable[str], since: str, n: int) -> int:
    """0 when at least `n` of `timestamps` are strictly after `since`, else 75 (not yet)."""
    if not is_int(n) or n < 1:
        raise ValueError(f"n must be an integer of at least 1, got {n!r}")
    return 0 if count_after(timestamps, since) >= n else NOT_YET
