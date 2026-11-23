"""The Node enforcers: Workflow programs parse and pass ESLint's recommended set (#1467).

Rules NODE11 (parses), NODE12 (no unused binding), NODE13 (names declared once and
used as their kind), NODE14 (no likely bug) and NODE15 (a suppression names its rule
and a reason) are count rules of the never-rise check
(`agent_tools.delivery.never_rise`): a branch may not hold more violations of one
than its merge base, compared by line count through git renames.

Coverage. A file is a Workflow program when its path ends `.js` and one of its lines
starts `export const meta` (`is_program`). The skill loads a program by path, not by
that line, so a revision that breaks the line would otherwise stop being judged:
`enforcers(..., also=)` names revisions whose programs every judged revision keeps
covering, and a revision judges the programs selected at it or at any of them that it
still holds. A revision with no covered program starts no tool and resolves no record.

The wrapper. The runtime replaces the `export const meta` line with `const meta` and
runs the text as the body of an async function whose parameters are
`PROGRAM_PARAMETERS`. A program is judged the same way: `wrap` writes the text as the
body of an anonymous async function expression on the first line (no newline before
the program, so lines keep their numbers, and a directive prologue stays one), and
the file is read as a CommonJS script. The wrapper declares no binding of its own;
the findings it would add (an unused runtime parameter, the unused `meta` binding the
runtime's caller reads) are dropped by position.

The rules. `node --check` and ESLint's fatal parse errors are NODE11, one violation
per distinct line. Every rule of ESLint's recommended set is mapped by
`ESLINT_RULES` to NODE12, NODE13 or NODE14, one violation per finding, with no
globals configured (the runtime names are parameters).

Suppression. ESLint honours an inline disable, so a finding it hides is not counted;
a second run with `noInlineConfig` turns every inline configuration comment into a
warning that quotes the comment, and `directive_violation` decides whether the comment
is NODE15: a disable naming no rule or giving no reason holding a letter or digit, and
every configuring comment, is. An enable comment is not.

Tools. The package pins `node` and `eslint` beside Ruff and every launcher exports
their directory as `AGENT_PLATFORM_TOOLS`; the adapter runs each by its command name on a
`PATH` that is that directory alone, never the inherited one, with `HOME` a temporary
directory and `LANG` `C` besides, so no inherited setting changes what they read. Every
line either tool reports is clamped into the source before anything is combined. Once a
program is judged, a tools directory that is unset, relative or without an executable
`node` and `eslint` is `tools_unavailable`; a tool that cannot start, runs too long or
exits unexpectedly is `node_failed` or `eslint_failed`; output that is incomplete or
malformed is `node_output_unreadable` or `eslint_output_unreadable`; a scratch directory
that cannot be written is `scratch_unwritable`. Each raises
`agent_tools.delivery.never_rise.EnforcerFailed(COMMAND, reason)`. A failed git read
raises `HistoryUnavailable`.

The command `node-lint --repo-root <absolute directory> [--revision <rev>]` prints
the counted violations at the revision (default `HEAD`: `never_rise.counted` of each
enforcer, kept plus marked), one line each on stdout as
`agent_tools.delivery.never_rise.Violation.text` defines, sorted by path then line. It
exits 1 when it printed any and 0 when none. It exits 2 with `node-lint: <reason>` on
stderr for a relative or missing root, a root below the repository's top level, an
unresolvable revision, a failed git read, or a closed failure.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import (
    Enforcer, EnforcerFailed, HistoryUnavailable, Snapshot, Violation)

COMMAND = "node-lint"
TOOLS_ENV = "AGENT_PLATFORM_TOOLS"
NODE = "node"
ESLINT = "eslint"
PARSE_RULE = "NODE11"
UNUSED_RULE = "NODE12"
NAMES_RULE = "NODE13"
LIKELY_BUG_RULE = "NODE14"
DIRECTIVE_RULE = "NODE15"
RULES = (PARSE_RULE, UNUSED_RULE, NAMES_RULE, LIKELY_BUG_RULE, DIRECTIVE_RULE)

# ESLint's recommended set, by the rule of the Node shard each finding is.
ESLINT_RULES: Mapping[str, str] = {
    # NODE12
    "no-unused-vars": "NODE12", "no-unused-labels": "NODE12",
    "no-unused-private-class-members": "NODE12",
    # NODE13
    "no-undef": "NODE13", "no-redeclare": "NODE13", "no-global-assign": "NODE13",
    "no-const-assign": "NODE13", "no-func-assign": "NODE13", "no-class-assign": "NODE13",
    "no-import-assign": "NODE13", "no-ex-assign": "NODE13", "no-delete-var": "NODE13",
    "no-shadow-restricted-names": "NODE13", "no-dupe-args": "NODE13",
    "no-dupe-class-members": "NODE13", "no-dupe-keys": "NODE13", "no-case-declarations": "NODE13",
    "no-with": "NODE13",
    # NODE14
    "constructor-super": "NODE14", "for-direction": "NODE14", "getter-return": "NODE14",
    "no-async-promise-executor": "NODE14", "no-compare-neg-zero": "NODE14",
    "no-cond-assign": "NODE14", "no-constant-binary-expression": "NODE14",
    "no-constant-condition": "NODE14", "no-control-regex": "NODE14", "no-debugger": "NODE14",
    "no-dupe-else-if": "NODE14", "no-duplicate-case": "NODE14", "no-empty": "NODE14",
    "no-empty-character-class": "NODE14", "no-empty-pattern": "NODE14",
    "no-empty-static-block": "NODE14", "no-extra-boolean-cast": "NODE14",
    "no-fallthrough": "NODE14", "no-invalid-regexp": "NODE14",
    "no-irregular-whitespace": "NODE14", "no-loss-of-precision": "NODE14",
    "no-misleading-character-class": "NODE14", "no-new-native-nonconstructor": "NODE14",
    "no-nonoctal-decimal-escape": "NODE14", "no-obj-calls": "NODE14", "no-octal": "NODE14",
    "no-prototype-builtins": "NODE14", "no-regex-spaces": "NODE14", "no-self-assign": "NODE14",
    "no-setter-return": "NODE14", "no-sparse-arrays": "NODE14", "no-this-before-super": "NODE14",
    "no-unexpected-multiline": "NODE14", "no-unreachable": "NODE14",
    "no-unsafe-finally": "NODE14", "no-unsafe-negation": "NODE14",
    "no-unsafe-optional-chaining": "NODE14", "no-useless-backreference": "NODE14",
    "no-useless-catch": "NODE14", "no-useless-escape": "NODE14", "require-yield": "NODE14",
    "use-isnan": "NODE14", "valid-typeof": "NODE14",
}

PROGRAM_PARAMETERS = ("agent", "parallel", "pipeline", "phase", "log", "args", "budget", "workflow")
META = re.compile(r"^export const meta\b", re.MULTILINE)
PREFIX = "void async function (" + ", ".join(PROGRAM_PARAMETERS) + ") {"
SUFFIX = "\n}\n"
CJS = "p{}.cjs"
CONFIG = "eslint.config.mjs"
INLINE_CONFIG = "eslint.inline.mjs"
NODE_ERROR_LINE = re.compile(r"p\d+\.cjs:(\d+)\s*$")
NO_EFFECT = "' has no effect because you have 'noInlineConfig' setting in "
JUSTIFICATION = re.compile(r"\s-{2,}\s")
DIRECTIVE_LABEL = re.compile(
    r"^(eslint(?:-env|-enable|-disable(?:(?:-next)?-line)?)?|exported|globals?)(?:\s|$)")

class Wrapped(NamedTuple):
    text: str
    meta_at: tuple[int, int] | None


def is_program(path: str, text: str) -> bool:
    return path.endswith(".js") and META.search(text) is not None


def wrap(text: str) -> Wrapped:
    match = META.search(text)
    if match is None:
        return Wrapped(PREFIX + text + SUFFIX, None)
    body = text[:match.start()] + "const meta" + text[match.end():]
    line = text.count("\n", 0, match.start()) + 1
    column = len("const ") + 1 + (len(PREFIX) if line == 1 else 0)
    return Wrapped(PREFIX + body + SUFFIX, (line, column))


def source_lines(text: str) -> int:
    return text.count("\n") + (0 if not text or text.endswith("\n") else 1)


def directive_violation(comment: str) -> bool:
    """Whether a comment that configures ESLint inline is itself a violation (NODE15)."""
    body = comment[2:-2] if comment.startswith("/*") else comment[2:]
    split = JUSTIFICATION.search(body)
    directive, reason = ((body[:split.start()], body[split.end():]) if split else (body, ""))
    directive, reason = directive.strip(), reason.strip()
    label = DIRECTIVE_LABEL.match(directive)
    if label is None:
        return True
    name = label.group(1)
    if name == "eslint-enable":
        return False
    if name in ("eslint-disable", "eslint-disable-line", "eslint-disable-next-line"):
        named = [part.strip() for part in directive[label.end(1):].split(",") if part.strip()]
        return not named or not any(c.isalnum() for c in reason)
    return True


def _failure(reason: str) -> EnforcerFailed:
    return EnforcerFailed(COMMAND, reason)


def tools_directory() -> str:
    """The pinned tools directory when it is absolute and holds an executable `node` and `eslint`."""
    directory = os.environ.get(TOOLS_ENV)
    if (directory and os.path.isabs(directory)
            and all(shutil.which(name, path=directory) for name in (NODE, ESLINT))):
        return directory
    raise _failure("tools_unavailable")


def _run(tool: str, argv: list[str], tools: str, tmp: Path,
         timeout: float | None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, cwd=tmp, env={"PATH": tools, "HOME": str(tmp), "LANG": "C"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise _failure(f"{tool}_failed") from None


def _syntax_line(proc: subprocess.CompletedProcess) -> int:
    lines = proc.stderr.splitlines()
    located = next((m for m in map(NODE_ERROR_LINE.search, lines) if m), None)
    if located is None or not any(line.startswith("SyntaxError: ") for line in lines):
        raise _failure("node_output_unreadable")
    return int(located.group(1))


def _is_line(value: object) -> bool:
    return type(value) is int and value >= 1


def _messages(proc: subprocess.CompletedProcess, names: Sequence[str]) -> dict[str, list[dict]]:
    """The validated messages of an ESLint run, keyed by the requested file name."""
    if proc.returncode not in (0, 1):
        raise _failure("eslint_failed")
    try:
        results = json.loads(proc.stdout)
    except ValueError:
        raise _failure("eslint_output_unreadable") from None
    unreadable = _failure("eslint_output_unreadable")
    if not isinstance(results, list):
        raise unreadable
    by_name: dict[str, list[dict]] = {}
    for result in results:
        if (not isinstance(result, dict) or not isinstance(result.get("filePath"), str)
                or not isinstance(result.get("messages"), list)):
            raise unreadable
        name = Path(result["filePath"]).name
        if name not in names or name in by_name:
            raise unreadable
        for message in result["messages"]:
            if (not isinstance(message, dict) or not _is_line(message.get("line"))
                    or not _is_line(message.get("column"))
                    or not (message.get("ruleId") is None or isinstance(message.get("ruleId"), str))
                    or not isinstance(message.get("message"), str)):
                raise unreadable
        by_name[name] = result["messages"]
    if set(by_name) != set(names):
        raise unreadable
    return by_name


def _config(linter_options: dict, rules: dict) -> str:
    config = [{"files": ["**/*.cjs"],
               "languageOptions": {"ecmaVersion": "latest", "sourceType": "script"},
               "linterOptions": linter_options, "rules": rules}]
    return "export default " + json.dumps(config) + ";\n"


def lint_files(files: Mapping[str, str], timeout: float | None) -> list[Violation]:
    """The violations of Workflow programs, `files` mapping each path to its text."""
    if not files:
        return []
    tools = tools_directory()
    paths = sorted(files)
    names = [CJS.format(i) for i in range(len(paths))]
    wrapped = [wrap(files[path]) for path in paths]
    limits = [max(1, source_lines(files[path])) for path in paths]

    def clamp(index: int, line: int) -> int:
        return max(1, min(line, limits[index]))

    found: list[Violation] = []
    parse_lines: set[tuple[int, int]] = set()
    try:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for name, program in zip(names, wrapped):
                (tmp / name).write_text(program.text, encoding="utf-8")
            for index, name in enumerate(names):
                proc = _run(NODE, [NODE, "--check", name], tools, tmp, timeout)
                if proc.returncode == 1:
                    parse_lines.add((index, clamp(index, _syntax_line(proc))))
                elif proc.returncode != 0:
                    raise _failure("node_failed")
            (tmp / CONFIG).write_text(
                _config({"reportUnusedDisableDirectives": "off"},
                        {name: "error" for name in ESLINT_RULES}), encoding="utf-8")
            (tmp / INLINE_CONFIG).write_text(
                _config({"reportUnusedDisableDirectives": "off", "noInlineConfig": True}, {}),
                encoding="utf-8")
            flags = ["--format", "json", "--no-warn-ignored"]
            checked = _messages(
                _run(ESLINT, [ESLINT, "--config", CONFIG, *flags, *names], tools, tmp, timeout), names)
            inline = _messages(
                _run(ESLINT, [ESLINT, "--config", INLINE_CONFIG, *flags, *names], tools, tmp, timeout),
                names)
    except OSError:
        raise _failure("scratch_unwritable") from None
    for index, name in enumerate(names):
        path = paths[index]
        for message in checked[name]:
            line = clamp(index, message["line"])
            if message.get("fatal"):
                parse_lines.add((index, line))
                continue
            rule = ESLINT_RULES.get(message["ruleId"] or "")
            if rule is None:
                continue
            at = (message["line"], message["column"])
            if message["line"] == 1 and message["column"] <= len(PREFIX):
                continue
            if message["ruleId"] == "no-unused-vars" and at == wrapped[index].meta_at:
                continue
            found.append(Violation(rule, path, line))
        for message in inline[name]:
            text = message["message"]
            if message["ruleId"] is not None or NO_EFFECT not in text or not text.startswith("'"):
                continue
            if directive_violation(text[1:text.rindex(NO_EFFECT)]):
                found.append(Violation(DIRECTIVE_RULE, path, clamp(index, message["line"])))
    found.extend(Violation(PARSE_RULE, paths[index], line) for index, line in parse_lines)
    return sorted(found, key=lambda v: (v.path, v.line, v.rule))


def enforcers(also: Sequence[str] = ()) -> tuple[Enforcer, ...]:
    """One count enforcer per rule, all sharing one tool run per revision.

    A revision is judged on the programs it holds that are programs at it or at any
    revision of `also`.
    """
    programs: dict[tuple[str, str], set[str]] = {}
    results: dict[tuple[str, str], list[Violation]] = {}

    def texts_of(snapshot: Snapshot) -> dict[str, str]:
        return {path: snapshot.contents[path].decode("utf-8", errors="replace")
                for path in snapshot.files if path.endswith(".js") and path in snapshot.contents}

    def programs_at(snapshot: Snapshot) -> set[str]:
        return {path for path, text in texts_of(snapshot).items() if is_program(path, text)}

    def programs_of(root: Path | None, revision: str, timeout: float | None) -> set[str]:
        key = (str(root), revision)
        if key not in programs:
            if root is None:
                raise ValueError("the snapshot was not read from a repository")
            other = never_rise.read_snapshot(root, revision, timeout)
            if other is None:
                raise HistoryUnavailable()
            programs[key] = programs_at(other)
        return programs[key]

    def violations(snapshot: Snapshot) -> list[Violation]:
        key = (str(snapshot.root), snapshot.revision)
        if key not in results:
            here = texts_of(snapshot)
            chosen = programs_at(snapshot).union(
                *(programs_of(snapshot.root, other, snapshot.timeout) for other in also))
            covered = chosen & here.keys()
            results[key] = (lint_files({path: here[path] for path in covered}, snapshot.timeout)
                            if covered else [])
        return results[key]

    def finder(rule: str) -> Callable[[Snapshot], list[Violation]]:
        return lambda snapshot: [v for v in violations(snapshot) if v.rule == rule]

    return tuple(Enforcer(rule, finder(rule)) for rule in RULES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args(argv)
    snapshot = never_rise.command_snapshot(COMMAND, args.repo_root, args.revision)
    if snapshot is None:
        return 2
    found: list[Violation] = []
    try:
        for enforcer in enforcers():
            kept, marked = never_rise.counted(enforcer, snapshot)
            found.extend(kept + marked)
    except EnforcerFailed as failure:
        print(f"{COMMAND}: {failure.reason}", file=sys.stderr)
        return 2
    except HistoryUnavailable:
        print(f"{COMMAND}: cannot read {args.revision} in {args.repo_root}", file=sys.stderr)
        return 2
    found.sort(key=lambda v: (v.path, v.line))
    for violation in found:
        print(violation.text())
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
