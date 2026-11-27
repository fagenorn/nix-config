"""Run a verification command's members, every one, and name each that failed (issue 1446).

Usage: `python -m agent_tools.delivery.verification_command {lint|test}`

`just lint` and `just test` run this module (it has no command-table row, after
`agent_tools.delivery.suite_runner`). It reads no project policy: the root is the current
directory, which `just` sets to the justfile's directory. Each member runs from the root
with this process's stdin, stdout, stderr and environment.

Members, in order:

- `lint`: `agnostic-lint` (`agent_tools.delivery.agnostic_lint --root <root>`),
  `context-map-lint` (`agent_tools.delivery.context_map_lint` with the root and
  `docs/CONTEXT-MAP.md`), `skill-lint` (`agent_tools.skill_lint check --root <root>`) and
  `dotnet-format` (`agent_tools.delivery.dotnet_format_lint --root <root>`).
  No lint member builds a host configuration.
- `test`: `nix-build` (`just build`) then `agent-workflow-tests` (`just agent-workflow-tests`),
  which runs with `WORKFLOW_POLICY_SURFACE=source` added to its environment, the way CI runs
  it: before activation the suite checks the skills from source only (issue 1580). The
  comparison of the host's activated skills with the source is kept in
  `just agent-activated-skill-tests`, which is for after activation.

Every member runs even after an earlier one failed. Output, each line flushed before the
next member starts:

- before a member, on stderr: `<command>: run <member>`
- a member that exits non-zero, on stderr: `<command>: <member> failed (exit <code>)`
- a member that cannot start, on stderr:
  `<command>: <member> failed (cannot start: <error>)`
- at the end, when none failed, on stdout: `<command>: passed: <id>, <id>, ...`; exit 0
- at the end, when some failed, on stderr: `<command>: failed: <id>, ...`; exit 1
- a missing or unknown command is a usage error; exit 2
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from agent_tools.system.siblings import sibling_argv


class Member(NamedTuple):
    id: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


COMMANDS: tuple[str, ...] = ("lint", "test")


def members(command: str, root: Path) -> tuple[Member, ...]:
    if command == "lint":
        return (
            Member("agnostic-lint", (*sibling_argv("delivery.agnostic_lint"), "--root", str(root))),
            Member("context-map-lint", (
                *sibling_argv("delivery.context_map_lint"), "--repo-root", str(root),
                "--context-map", str(root / "docs" / "CONTEXT-MAP.md"))),
            Member("skill-lint",
                   (*sibling_argv("skill_lint"), "check", "--root", str(root))),
            Member("dotnet-format",
                   (*sibling_argv("delivery.dotnet_format_lint"), "--root", str(root))),
        )
    if command == "test":
        return (
            Member("nix-build", ("just", "build")),
            Member("agent-workflow-tests", ("just", "agent-workflow-tests"),
                   (("WORKFLOW_POLICY_SURFACE", "source"),)),
        )
    raise ValueError(f"unknown verification command {command!r}")


def _say(stream, line: str) -> None:
    print(line, file=stream, flush=True)


def run(command: str, root: Path) -> list[str]:
    failed: list[str] = []
    for member in members(command, root):
        _say(sys.stderr, f"{command}: run {member.id}")
        sys.stdout.flush()
        try:
            code = subprocess.run(
                list(member.argv), cwd=root, env={**os.environ, **dict(member.env)}).returncode
        except OSError as error:
            _say(sys.stderr, f"{command}: {member.id} failed (cannot start: {error})")
            failed.append(member.id)
            continue
        if code != 0:
            _say(sys.stderr, f"{command}: {member.id} failed (exit {code})")
            failed.append(member.id)
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verification-command")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    failed = run(args.command, root)
    if failed:
        _say(sys.stderr, f"{args.command}: failed: {', '.join(failed)}")
        return 1
    ids = ", ".join(m.id for m in members(args.command, root))
    _say(sys.stdout, f"{args.command}: passed: {ids}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
