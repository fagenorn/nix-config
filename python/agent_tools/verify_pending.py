"""verify-pending: the commands over a `verify` block.

`verify-pending lint --input <path|->` prints the verdict as one line of
`json.dumps(verdict, sort_keys=True)` and exits 0 when the block is accepted,
1 when it is refused and 2 on a usage error, a `--repo-root` that is not a git
work tree, or an unreadable input path.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from agent_tools.resolve_project import ContractError, resolve
from agent_tools.verify_block import lint_block, parse_block

GIT_TIMEOUT = 60


def git_ok(root: str, *args: str) -> bool:
    """True when `git -C root args` exits 0; raises OSError or SubprocessError when git cannot run."""
    return subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=GIT_TIMEOUT).returncode == 0


def git_object(root: str, sha: str, path: str | None) -> tuple[str, str]:
    """`(commit_state, path_state)` of `sha` (and `path` at it) in the repository at `root`."""
    try:
        if not git_ok(root, "cat-file", "-e", f"{sha}^{{commit}}"):
            return "absent", "unknown"
        if path is None:
            return "present", "unknown"
        return ("present", "present") if git_ok(root, "cat-file", "-e", f"{sha}:{path}") else ("present", "absent")
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown"


class CliReferences:
    """The real D9 lookups: `PATH`, the resolved project contract and git objects."""

    def __init__(self, root: str | None):
        self.root = root
        self.commands: set | None = None
        self.resolved = False

    def tool(self, name: str) -> str:
        return "present" if shutil.which(name) else "absent"

    def command(self, command_id: str) -> str:
        if self.root is None:
            return "unknown"
        if not self.resolved:
            self.resolved = True
            try:
                self.commands = set(resolve(self.root)["bindings"]["commands"])
            except ContractError:
                self.commands = None
        if self.commands is None:
            return "unknown"
        return "present" if command_id in self.commands else "absent"

    def script(self, path: str, sha: str) -> tuple[str, str]:
        if self.root is None:
            return "unknown", "unknown"
        return git_object(self.root, sha, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify-pending")
    commands = parser.add_subparsers(dest="command", required=True)
    lint = commands.add_parser("lint", help="check a verify block")
    lint.add_argument("--input", required=True, help="a hold comment or JSON block; - reads stdin")
    lint.add_argument("--repo-root", help="a git work tree, to check command and script references")
    return parser


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def run_lint(args: argparse.Namespace) -> int:
    root = None
    if args.repo_root is not None:
        root = os.path.abspath(args.repo_root)
        try:
            is_repo = git_ok(root, "rev-parse", "--git-dir")
        except (OSError, subprocess.SubprocessError):
            is_repo = False
        if not is_repo:
            print(f"verify-pending: --repo-root {args.repo_root} is not a git work tree", file=sys.stderr)
            return 2
    try:
        text = read_input(args.input)
    except (OSError, UnicodeDecodeError) as error:
        print(f"verify-pending: cannot read {args.input}: {error}", file=sys.stderr)
        return 2
    block, parse_errors = parse_block(text)
    if parse_errors:
        verdict = {"ok": False, "errors": parse_errors, "warnings": []}
    else:
        verdict = lint_block(block, refs=CliReferences(root))
    print(json.dumps(verdict, sort_keys=True))
    return 0 if verdict["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_lint(args)


if __name__ == "__main__":
    sys.exit(main())
