"""The `verify` block grammar: parsing a hold comment and checking its structure.

`parse_block` extracts the block from a hold comment (or a bare JSON text) and
`lint_block` walks it, collecting every finding as `{"field", "code",
"message"}`. A finding's `field` is a path into the block
(`checks[0].when.not_before`); an unknown member's path is its own path.
"""

import json
import re
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

RUN_FORMS = ("tool", "command", "script", "ask", "act")
RUN_MEMBERS = {
    "tool": ("tool", "args"),
    "command": ("command",),
    "script": ("script", "at", "args"),
    "ask": ("ask",),
    "act": ("act", "then"),
}
# D5 class 1: a tool that runs code or another program it is handed.
INLINE_CODE_TOOLS = frozenset((
    "sh bash zsh dash ksh fish csh tcsh "
    "awk gawk mawk sed perl ruby php lua tclsh expect node nodejs deno bun npx npm pnpm yarn pip pipx uv uvx "
    "poetry go cargo java osascript Rscript julia "
    "vi vim nvim ex emacs "
    "env xargs eval exec command builtin time timeout gtimeout nice ionice renice stdbuf flock watch caffeinate "
    "nohup setsid disown chroot sudo doas su runuser script unbuffer parallel ssh docker podman kubectl make "
    "devenv nix-shell"
).split())
INTERPRETER = re.compile(r"^(python|pypy|perl|ruby|php|lua|node|tclsh)[0-9.]*$")
EXEC_ARGS = frozenset(("-exec", "-execdir", "-ok", "-okdir"))
# D5 class 3: Nix code-bearing arguments.
NIX_TOOLS = frozenset(("nix", "nix-build", "nix-instantiate", "nix-store", "nix-env"))
NIX_CODE_ARGS = frozenset(("--expr", "-E", "--apply", "--arg", "--run", "--command", "-c", "-p", "--packages"))
NIX_EXEC_SUBCOMMANDS = frozenset(("run", "shell", "develop", "repl", "bundle", "fmt", "env", "profile"))
FLAKE_REF = re.compile(
    r"^(github|gitlab|sourcehut|git\+[a-z]+|hg\+[a-z]+|https?|tarball\+[a-z]+|file\+[a-z]+|path|flake):"
)
# D5 class 4: git configuration that names a command.
GIT_CODE_ARGS = frozenset(("-c", "--config-env", "--exec-path", "--upload-pack", "--receive-pack", "--exec", "-x"))
TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COMMAND_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
APPROVAL_VERB = re.compile(r"\b(approve|approves|approved|approval|sign[- ]?off|lgtm)\b", re.IGNORECASE)
APPROVAL_OBJECT = re.compile(r"\b(design|adr|runbook|path[- ]?list|paths|spec|plan)\b", re.IGNORECASE)


class References(Protocol):
    """What the lint must learn from outside the block (D9); every lookup is tri-state."""

    def tool(self, name: str) -> str:
        """`"present"` or `"absent"`."""

    def command(self, command_id: str) -> str:
        """`"present"`, `"absent"` or `"unknown"`."""

    def script(self, path: str, sha: str) -> tuple[str, str]:
        """`(commit_state, path_state)`; `path_state` is `"unknown"` unless the commit is `"present"`."""


def finding(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def parse_block(text: str) -> tuple[object | None, list[dict]]:
    """Extract and strictly parse the block; on failure `(None, [finding])`."""
    fences = FENCE.findall(text)
    if len(fences) > 1:
        return None, [finding("block", "fence_count", f"{len(fences)} verify fences; exactly one is allowed")]
    body = fences[0] if fences else text
    try:
        block = json.loads(
            body, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal
        )
    except ValueError as error:
        return None, [finding("block", "not_json", f"the block is not strict JSON: {error}")]
    return block, []


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_sha(value: object) -> bool:
    return isinstance(value, str) and SHA.match(value) is not None


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
        valid = host == "any" or HOST.match(host) is not None
    elif isinstance(host, list):
        valid = (
            bool(host)
            and all(isinstance(name, str) and HOST.match(name) for name in host)
            and len(set(host)) == len(host)
        )
    else:
        valid = False
    if not valid:
        invalid(errors, host_path, "must be a hostname, 'any', or a non-empty list of distinct hostnames")
        return
    concrete = isinstance(host, str) and host != "any" and HOST.match(host) is not None
    if check.get("effects") in ("paid", "live") and not concrete:
        errors.append(finding(host_path, "host_not_concrete", "a live or paid check must name exactly one host"))


def is_relative_posix(path: str) -> bool:
    if path == "" or path.startswith("/") or "\\" in path:
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def names_inline_code(name: str) -> bool:
    """A program name that runs code it is handed; lowercased, as the macOS volume is case-insensitive."""
    folded = name.lower()
    return folded in INLINE_CODE_TOOLS or INTERPRETER.match(folded) is not None


def arg_hits_inline_code(arg: str) -> bool:
    """D5 class 2: the arg, its part after `=`, the first word of each, the basename of each."""
    candidates = {arg}
    if "=" in arg:
        candidates.add(arg.split("=", 1)[1])
    candidates |= {word for text in candidates for word in text.split()[:1]}
    candidates |= {text.rsplit("/", 1)[-1] for text in candidates}
    return any(names_inline_code(text) for text in candidates)


def normalised(arg: str) -> str:
    return arg.split("=", 1)[0] if arg.startswith("-") and "=" in arg else arg


def args_carry_code(tool: object, args: list) -> bool:
    texts = [arg for arg in args if isinstance(arg, str)]
    if any(arg in EXEC_ARGS or arg_hits_inline_code(arg) for arg in texts):
        return True
    flags = [normalised(arg) for arg in texts]
    tool = tool.lower() if isinstance(tool, str) else ""
    if tool in NIX_TOOLS:
        if any(flag in NIX_CODE_ARGS for flag in flags):
            return True
        if tool == "nix":
            # Value-taking global options (`--option NAME VALUE`) can precede the subcommand,
            # so any bare word that is an exec subcommand counts.
            if any(arg in NIX_EXEC_SUBCOMMANDS for arg in texts if not arg.startswith("-")):
                return True
        if any(FLAKE_REF.match(arg) or ("=" in arg and FLAKE_REF.match(arg.split("=", 1)[1])) for arg in texts):
            return True
    if tool == "git" and any(flag in GIT_CODE_ARGS for flag in flags):
        return True
    return False


def check_args(run: dict, path: str, errors: list) -> None:
    """Inline code in `args` (checked first), else the argument shape; one finding at most."""
    if "args" not in run:
        return
    args = run["args"]
    args_path = join(path, "args")
    if isinstance(args, list) and args_carry_code(run.get("tool"), args):
        errors.append(finding(args_path, "inline_code", "an argument carries code or names a program to run"))
    elif not (isinstance(args, list) and all(isinstance(arg, str) for arg in args)):
        invalid(errors, args_path, "must be a list of strings")


def check_single_line(value: object, path: str, errors: list) -> bool:
    if not is_text(value) or "\n" in value or "\r" in value:
        invalid(errors, path, "must be a non-empty single-line string")
        return False
    return True


def check_form(run: object, path: str, errors: list, refs: References, allow_interactive: bool) -> None:
    if not isinstance(run, dict):
        invalid(errors, path, "must be an object")
        return
    forms = [form for form in RUN_FORMS if form in run]
    if len(forms) != 1 or (forms[0] in ("ask", "act") and not allow_interactive):
        errors.append(finding(path, "run_form", f"needs exactly one of {', '.join(RUN_FORMS if allow_interactive else RUN_FORMS[:3])}"))
        return
    form = forms[0]
    before = len(errors)
    for name in run:
        if name not in RUN_MEMBERS[form]:
            errors.append(finding(join(path, name), "unknown_field", f"{name!r} is not a member of a {form} run"))
    if form in ("tool", "script"):
        key = form
        name = run[key]
        key_path = join(path, key)
        if form == "tool":
            if not isinstance(name, str):
                invalid(errors, key_path, "must be a string")
            elif not TOOL.match(name) or names_inline_code(name):
                errors.append(finding(key_path, "inline_code", "must be the bare name of an installed program that does not run code it is handed"))
        elif not (isinstance(name, str) and is_relative_posix(name)):
            invalid(errors, key_path, "must be a relative POSIX path inside the repository")
        if form == "script":
            if "at" not in run:
                errors.append(finding(join(path, "at"), "missing_field", "'at' is required"))
            elif not is_sha(run["at"]):
                invalid(errors, join(path, "at"), "must be a 40-character lowercase hex sha")
        check_args(run, path, errors)
    elif form == "command":
        command = run["command"]
        if not isinstance(command, str):
            invalid(errors, join(path, "command"), "must be a string")
        elif not COMMAND_ID.match(command):
            errors.append(finding(join(path, "command"), "inline_code", "must be a contract command id"))
    elif form == "ask":
        if check_single_line(run["ask"], join(path, "ask"), errors) and \
                APPROVAL_VERB.search(run["ask"]) and APPROVAL_OBJECT.search(run["ask"]):
            errors.append(finding(join(path, "ask"), "approval_ask", "approval of a document is not a verification question"))
    else:
        check_single_line(run["act"], join(path, "act"), errors)
        if "then" not in run:
            errors.append(finding(join(path, "then"), "missing_field", "'then' is required"))
        else:
            check_form(run["then"], join(path, "then"), errors, refs, False)
    if len(errors) == before:
        check_references(run, form, path, errors, refs)


def check_references(run: dict, form: str, path: str, errors: list, refs: References) -> None:
    """D9: the reference of a run that passed every other rule must resolve."""
    if form == "tool":
        if refs.tool(run["tool"]) == "absent":
            errors.append(finding(join(path, "tool"), "not_installed", f"{run['tool']!r} is not installed"))
    elif form == "command":
        state = refs.command(run["command"])
        if state == "absent":
            errors.append(finding(join(path, "command"), "not_declared", f"{run['command']!r} is not a contract command"))
        elif state != "present":
            errors.append(finding(join(path, "command"), "unverified_reference", "the contract commands could not be read; pass --repo-root"))
    elif form == "script":
        commit, found = refs.script(run["script"], run["at"])
        if commit == "absent":
            errors.append(finding(join(path, "at"), "unverified_reference", "the commit is not in the repository"))
        elif commit != "present":
            errors.append(finding(join(path, "script"), "unverified_reference", "the script could not be checked; pass --repo-root"))
        elif found == "absent":
            errors.append(finding(join(path, "script"), "not_committed", "the script is not committed at that commit"))
        elif found != "present":
            errors.append(finding(join(path, "script"), "unverified_reference", "the script could not be checked"))


def check_run(run: object, path: str, kind: object, errors: list, refs: References) -> None:
    if not isinstance(run, dict):
        invalid(errors, path, "must be an object")
        return
    forms = [form for form in RUN_FORMS if form in run]
    if len(forms) != 1:
        errors.append(finding(path, "run_form", f"needs exactly one of {', '.join(RUN_FORMS)}"))
        return
    if kind in KINDS:
        needs_owner = forms[0] in ("ask", "act")
        if needs_owner != (kind == "human"):
            wanted = "human" if needs_owner else "evidence"
            errors.append(finding(path.rsplit(".", 1)[0] + ".kind", "kind_mismatch", f"a {forms[0]} run needs kind {wanted}"))
    check_form(run, path, errors, refs, True)


def check_reason(check: dict, path: str, errors: list) -> None:
    kind = check.get("kind")
    reason_path = join(path, "reason")
    if kind == "human":
        if check.get("reason") not in REASONS:
            errors.append(finding(reason_path, "reason_required", f"a human check needs a reason, one of {', '.join(REASONS)}"))
    elif kind == "evidence" and "reason" in check:
        errors.append(finding(reason_path, "reason_not_allowed", "an evidence check takes no reason"))


def check_one(check: object, path: str, errors: list, refs: References) -> None:
    if not closed_object(check, path, CHECK_FIELDS, CHECK_REQUIRED, errors):
        return
    if "ac" in check and not (isinstance(check["ac"], str) and AC.match(check["ac"])):
        invalid(errors, join(path, "ac"), "must match [A-Za-z][A-Za-z0-9_.-]*")
    if "kind" in check:
        check_choice(check["kind"], join(path, "kind"), KINDS, errors)
    if "host" in check:
        check_host(check, path, errors)
    if "when" in check:
        check_when(check["when"], join(path, "when"), errors)
    if "run" in check:
        check_run(check["run"], join(path, "run"), check.get("kind"), errors, refs)
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


def lint_block(block: object, *, refs: References) -> dict:
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
                    check_one(check, f"checks[{index}]", errors, refs)
    return {"ok": not errors, "errors": errors, "warnings": warnings}
