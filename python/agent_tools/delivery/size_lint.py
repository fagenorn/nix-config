"""The size enforcer: no source or test file is over 1,500 lines (rule B17, #1455).

A file is judged by its line count at a committed revision, counted as
`git grep -c` counts (`agent_tools.delivery.never_rise.read_snapshot`): the
newline-terminated lines plus an unterminated last line, binary files (a NUL in
the committed bytes, whatever a gitattribute says) and empty files not listed. A file is over the budget when it holds more than `BUDGET`
(1,500) lines; its violation is `Violation(RULE_ID, path, line_count)`, the line
being the file's last line, so a file that grows reports a larger line.

A source file is every tracked text file except documentation, data, lock files,
patches and licence files, named by `NON_SOURCE_SUFFIXES` (the lower-cased
extension) and `NON_SOURCE_NAMES` (the exact file name). A file with no
extension, an executable script or a sourced shell fragment, is therefore judged.

`ENFORCER` is a per-file rule for the never-rise check: a file over the budget
may not grow and a file under it may grow up to it, compared with the same file
on the merge base through git renames. That check, not this command's exit, is
the gate.

The command `size-lint --repo-root <absolute directory> [--revision <rev>]`
prints every over-budget file at the revision (default `HEAD`), one line each on
stdout, `<rule> <path>:<line>` with the path escaped as
`agent_tools.delivery.never_rise.Violation.text` defines. It exits 1 when it
printed any and 0 when none. It exits 2 with `size-lint: <reason>` on stderr for
a relative or missing root, a root below the repository's top level, an
unresolvable revision or a failed git read.
"""

import argparse
from pathlib import Path, PurePosixPath

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation

COMMAND = "size-lint"
RULE_ID = "B17"
BUDGET = 1500
NON_SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".csv", ".tsv", ".xml", ".svg", ".lock", ".sum", ".patch", ".diff"})
NON_SOURCE_NAMES: frozenset[str] = frozenset({"LICENSE", "COPYING", "NOTICE", "AUTHORS", "CODEOWNERS"})


def is_source(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.suffix.lower() not in NON_SOURCE_SUFFIXES and pure.name not in NON_SOURCE_NAMES


def find(snapshot: Snapshot) -> list[Violation]:
    return [Violation(RULE_ID, path, count)
            for path, count in sorted(snapshot.line_counts.items())
            if is_source(path) and count > BUDGET]


ENFORCER = Enforcer(RULE_ID, find, per_file=True)


def resolve(root: Path, revision: str) -> str | None:
    return never_rise.resolve_commit(root, revision, timeout=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args(argv)
    snapshot = never_rise.command_snapshot(COMMAND, args.repo_root, args.revision)
    if snapshot is None:
        return 2
    found = find(snapshot)
    for violation in found:
        print(violation.text())
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
