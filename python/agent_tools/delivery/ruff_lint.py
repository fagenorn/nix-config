"""The Ruff enforcers of the never-rise check: Python findings may not rise (#1460).

What is judged. A Python file (`.py` or `.pyi`) at a committed revision is judged
when it sits in or below a directory that holds a tracked `pyproject.toml`, an
empty one included; a Python file outside every such directory is not judged.
Symlinks, submodules and binary files are never judged.

The selection and the pin. The pinned Ruff checks the files with `--isolated`, so
no Ruff configuration of the repository or of any directory above the scratch
directory is read, `--no-cache`, `--exit-zero`, target `py313` and the rules
`SELECTION`: the import, statement and syntax families `E4`, `E7` and `E9`, every
Pyflakes rule `F` and the commented-out-code rule `ERA001`. The package pins Ruff
and exports the directory that holds it as `AGENT_PLATFORM_TOOLS`; the adapter
runs `ruff` by its command name on a `PATH` that is that directory alone, and with
no usable directory it fails closed (`ruff_unavailable`) once a file is judged.

The table. `RULE_OF_CODE` maps a Ruff code to the id of the stack rule it breaks;
the longest key that a code starts with wins, so `F722` is `PY8` and not `PY10`.
A parse error carries the code `invalid-syntax` (or none) and is `PY8`. A code
under the selection that no key covers is a closed failure (`unmapped_code`).

Suppressions. A `# noqa` or `# ruff: noqa` comment passes only when it names the
code of each check it silences and then gives a reason; any other is `PY13` at its
row. Comments are read with `tokenize`, never from raw lines, so text in a string
is no comment; after a tokenize error only the comments read before it count, and
Ruff reports the file itself as `PY8`.

Scratch and batching. The committed bytes of the judged files are written to a
fresh directory below the system temporary directory, never inside the repository
and never over an existing file, and Ruff runs there at most `BATCH` paths at a
time, once per revision (the result is kept for the revisions last judged, so the
eight enforcers share one pass).

Counts. Every enforcer is a count rule: the branch may not hold more violations
of a rule than the merge base, so a rename or a move that keeps the count passes.

Failures. `findings` raises `EnforcerFailed(COMMAND, reason)` with `ruff_unavailable`,
`ruff_failed` (Ruff did not run, ran too long or exited non-zero),
`ruff_output_unreadable`, `unmapped_code`, `unsafe_path` (a path that is absolute
or holds an empty, `.` or `..` part), `path_collision` (two paths that one scratch
file or directory would hold after case and Unicode folding),
`scratch_inside_repository` or `scratch_unwritable`. A failed git read is
`HistoryUnavailable`. The command bounds every child by `--timeout`.

The command `ruff-lint --repo-root <absolute directory> [--revision <rev>]
[--timeout SECONDS]` prints every finding at the revision (default `HEAD`), one
line each on stdout, `<rule> <path>:<line>` as
`agent_tools.delivery.never_rise.Violation.text` defines, in path, line and rule
order. It exits 1 when it printed any and 0 when none. It exits 2 with
`ruff-lint: <reason>` on stderr for a relative or missing root, a root below the
repository's top level, an unresolvable revision, a failed git read, a bad
timeout or a closed failure. That check, not this command's exit, is the gate.
"""

import argparse
import functools
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import (
    Enforcer, EnforcerFailed, HistoryUnavailable, Snapshot, Violation)

COMMAND = "ruff-lint"
TOOLS_ENV = "AGENT_PLATFORM_TOOLS"
RUFF = "ruff"
SELECTION = ("E4", "E7", "E9", "F", "ERA001")
TARGET_VERSION = "py313"
BATCH = 200
SYNTAX_ERROR = "invalid-syntax"
SUPPRESSION_RULE = "PY13"
COMMAND_TIMEOUT_SECONDS = 120.0
RULE_OF_CODE: dict[str, str] = {
    "E4": "PY6", "F4": "PY6", "E7": "PY7", "E9": "PY8", "F722": "PY8", SYNTAX_ERROR: "PY8",
    "F5": "PY9", "F6": "PY10", "F7": "PY10", "F9": "PY10", "F8": "PY11", "ERA001": "PY12"}
RULES = ("PY6", "PY7", "PY8", "PY9", "PY10", "PY11", "PY12", "PY13")
PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
MARKER = "pyproject.toml"
MEMO_SIZE = 4
NOQA = re.compile(r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa(?![A-Za-z0-9_])(?P<tail>.*)", re.I)
CODED = re.compile(r"\s*:\s*(?P<codes>[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)(?P<rest>.*)")
TEMPORARY_VARIABLES = ("TMPDIR", "TEMP", "TMP")
TEMPORARY_DIRECTORIES = ("/tmp", "/var/tmp", "/usr/tmp")
REASON_PADDING = re.compile(r"[\s,:;#-]*")
_memo: dict[tuple[str, str, str], tuple[Violation, ...]] = {}


def rule_of(code: str | None) -> str | None:
    """The stack rule a Ruff code breaks: the longest key it starts with, or None."""
    if code is None:
        return RULE_OF_CODE[SYNTAX_ERROR]
    keys = [key for key in RULE_OF_CODE if code.startswith(key)]
    return RULE_OF_CODE[max(keys, key=len)] if keys else None


def covered(files: Iterable[str]) -> list[str]:
    """The Python files at or below a directory that holds a `pyproject.toml`, sorted."""
    paths = list(files)
    roots = {PurePosixPath(path).parent for path in paths if PurePosixPath(path).name == MARKER}
    dot = PurePosixPath(".")
    return sorted(
        path for path in paths
        if PurePosixPath(path).suffix in PYTHON_SUFFIXES
        and (dot in roots or any(parent in roots for parent in PurePosixPath(path).parents)))


def ruff_directory() -> str | None:
    """The pinned tools directory when it is absolute and holds an executable `ruff`."""
    directory = os.environ.get(TOOLS_ENV)
    if directory and os.path.isabs(directory) and shutil.which(RUFF, path=directory):
        return directory
    return None


def suppressions(path: str, source: bytes) -> list[Violation]:
    """A `PY13` violation for each suppression comment without a code and a reason."""
    comments: list[tuple[str, int]] = []
    try:
        for token in tokenize.tokenize(io.BytesIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments.append((token.string, token.start[0]))
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError, LookupError):
        pass
    found = []
    for text, row in comments:
        directive = NOQA.search(text)
        if directive is None:
            continue
        coded = CODED.match(directive["tail"])
        if coded is None or REASON_PADDING.fullmatch(coded["rest"]):
            found.append(Violation(SUPPRESSION_RULE, path, row))
    return found


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _inside(directory: str | Path | None, root: Path | None) -> bool:
    """True when a directory is the repository root or below it."""
    if not directory or root is None:
        return False
    path = Path(directory).resolve()
    return path == root or root in path.parents


def _scratch_parent(root: Path | None) -> Path:
    """The directory the scratch tree is made in, found without writing anything.

    `tempfile.gettempdir()` discovers by creating a probe file in each candidate
    and ends with the current directory, which is the repository under `just
    lint`; so discovery here only inspects: a candidate inside the repository is
    refused, and the current directory is never a candidate.
    """
    if tempfile.tempdir is not None:
        chosen = Path(tempfile.tempdir).resolve()
        if _inside(chosen, root):
            raise EnforcerFailed(COMMAND, "scratch_inside_repository")
        return chosen
    candidates = [os.environ.get(name) for name in TEMPORARY_VARIABLES]
    candidates = [name for name in candidates if name] + list(TEMPORARY_DIRECTORIES)
    if any(_inside(name, root) for name in candidates):
        raise EnforcerFailed(COMMAND, "scratch_inside_repository")
    for name in candidates:
        if os.path.isdir(name) and os.access(name, os.W_OK | os.X_OK):
            return Path(name).resolve()
    raise OSError("no writable scratch directory")


def _check_paths(paths: list[str]) -> None:
    for path in paths:
        if path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
            raise EnforcerFailed(COMMAND, "unsafe_path")
    seen: dict[str, str] = {}
    for path in paths:
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            name = "/".join(parts[:end])
            if seen.setdefault(_fold(name), name) != name:
                raise EnforcerFailed(COMMAND, "path_collision")


def _run_ruff(tools: str, scratch: Path, batch: list[str], timeout: float | None) -> list[Violation]:
    argv = [RUFF, "check", "--isolated", "--no-cache", "--exit-zero", "--target-version",
            TARGET_VERSION, "--select", ",".join(SELECTION), "--output-format", "json",
            "--", *batch]
    try:
        done = subprocess.run(
            argv, cwd=scratch, env={"PATH": tools}, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise EnforcerFailed(COMMAND, "ruff_failed") from None
    if done.returncode != 0:
        raise EnforcerFailed(COMMAND, "ruff_failed")
    names = {}
    for path in batch:
        names[str(scratch / path)] = path
        names[os.path.realpath(scratch / path)] = path
    try:
        items = json.loads(done.stdout)
        if not isinstance(items, list):
            raise ValueError("not a list")
        located = []
        for item in items:
            row = item["location"]["row"]
            if (not isinstance(item, dict) or item["filename"] not in names
                    or not isinstance(row, int) or isinstance(row, bool)):
                raise ValueError("unreadable item")
            located.append((names[item["filename"]], row, item.get("code")))
    except (ValueError, KeyError, TypeError):
        raise EnforcerFailed(COMMAND, "ruff_output_unreadable") from None
    found = []
    for path, row, code in located:
        rule = rule_of(code) if code is None or isinstance(code, str) else None
        if rule is None:
            raise EnforcerFailed(COMMAND, "unmapped_code")
        found.append(Violation(rule, path, row))
    return found


def findings(snapshot: Snapshot) -> tuple[Violation, ...]:
    """Every violation of every rule at the snapshot, sorted by path, line and rule."""
    paths = covered(snapshot.files)
    if not paths:
        return ()
    tools = ruff_directory()
    if tools is None:
        raise EnforcerFailed(COMMAND, "ruff_unavailable")
    key = (str(snapshot.root), snapshot.revision, tools)
    if key in _memo:
        return _memo[key]
    _check_paths(paths)
    contents = never_rise.read_files(snapshot, paths)
    root = snapshot.root.resolve() if snapshot.root is not None else None
    found: list[Violation] = []
    try:
        parent = _scratch_parent(root)
        with tempfile.TemporaryDirectory(prefix="ruff-lint-", dir=parent) as tmp:
            scratch = Path(tmp).resolve()
            for path, data in contents.items():
                target = scratch / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "xb") as handle:
                    handle.write(data)
            for start in range(0, len(paths), BATCH):
                found.extend(_run_ruff(tools, scratch, paths[start:start + BATCH], snapshot.timeout))
    except OSError:
        raise EnforcerFailed(COMMAND, "scratch_unwritable") from None
    for path, data in contents.items():
        found.extend(suppressions(path, data))
    result = tuple(sorted(found, key=lambda v: (v.path, v.line, RULES.index(v.rule))))
    _memo[key] = result
    while len(_memo) > MEMO_SIZE:
        del _memo[next(iter(_memo))]
    return result


def _of_rule(rule: str, snapshot: Snapshot) -> list[Violation]:
    return [violation for violation in findings(snapshot) if violation.rule == rule]


ENFORCERS: tuple[Enforcer, ...] = tuple(
    Enforcer(rule, functools.partial(_of_rule, rule)) for rule in RULES)


def _timeout(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--timeout", default=str(COMMAND_TIMEOUT_SECONDS))
    args = parser.parse_args(argv)
    timeout = _timeout(args.timeout)
    if timeout is None:
        print(f"{COMMAND}: --timeout must be a positive number of seconds", file=sys.stderr)
        return 2
    root = Path(args.repo_root)
    if not root.is_absolute():
        print(f"{COMMAND}: --repo-root must be absolute: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"{COMMAND}: not a directory: {root}", file=sys.stderr)
        return 2
    if never_rise.in_subdirectory(root, timeout=timeout):
        print(f"{COMMAND}: --repo-root is not the repository top level: {root}", file=sys.stderr)
        return 2
    sha = never_rise.resolve_commit(root, args.revision, timeout=timeout)
    snapshot = never_rise.read_snapshot(root, sha, timeout=timeout) if sha else None
    if snapshot is None:
        print(f"{COMMAND}: cannot read {args.revision} in {root}", file=sys.stderr)
        return 2
    try:
        found = findings(snapshot)
    except EnforcerFailed as failure:
        print(f"{COMMAND}: {failure.reason}", file=sys.stderr)
        return 2
    except HistoryUnavailable:
        print(f"{COMMAND}: cannot read {args.revision} in {root}", file=sys.stderr)
        return 2
    for violation in found:
        print(violation.text())
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
