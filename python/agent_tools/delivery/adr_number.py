"""`adr-number`: the number a new decision record takes (issue 1440).

    adr-number next --repo-root <absolute> --dir <absolute> --base <ref>

`next` prints one past the highest record number ever used in `--dir`, zero-padded to
three digits, and a newline (`004`). It writes no file and commits nothing.

A number is used when a file directly in `--dir` named like a record (`NNN-<slug>.md`)
exists in the working tree, or existed in any commit reachable from HEAD or from
`--base`, deleted records included: the history walk is not simplified, so a record
added and deleted on one side of a merge still counts. Files in subdirectories of
`--dir` and in other directories do not count. An empty or absent `--dir` gives `001`.

`--repo-root` and `--dir` must be absolute, `--dir` must be `--repo-root` or inside it,
and `--repo-root` must be the checkout's toplevel.

Exit 0 prints the number. Exit 1 refuses (`git_failed`, `shallow_history`,
`numbers_exhausted`) and exit 2 is misuse (`misuse`, `not_a_repository_root`,
`base_unknown`). Both write `{"error": {code, detail}}` to stderr and nothing to stdout.
A shallow checkout is refused because its history cannot name every used number.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

from agent_tools.delivery.context_map_lint import ADR_FILE_RE

GIT_TIMEOUT = 120
MAX_NUMBER = 999


class NumberRefusal(Exception):
    """One refusal: a closed code, its detail and the exit code (1 refuse, 2 misuse)."""

    def __init__(self, code: str, detail: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


def git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise NumberRefusal("git_failed", "timeout", 1) from None
    if done.returncode != 0:
        lines = done.stderr.strip().splitlines()
        raise NumberRefusal("git_failed", lines[-1] if lines else "", 1)
    return done.stdout


def check_repository(root: Path, base: str) -> str:
    """Validate the checkout and return the full commit sha of `base`."""
    try:
        toplevel = git(root, "rev-parse", "--show-toplevel").strip()
    except NumberRefusal as refusal:
        raise NumberRefusal("not_a_repository_root", refusal.detail, 2) from None
    if Path(toplevel).resolve() != root.resolve():
        raise NumberRefusal("not_a_repository_root", str(root), 2)
    if git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise NumberRefusal("shallow_history", str(root), 1)
    try:
        return git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").strip()
    except NumberRefusal:
        raise NumberRefusal("base_unknown", base, 2) from None


def used_numbers(root: Path, directory: Path, base_sha: str) -> set[int]:
    """Every record number a file directly in `directory` has had, in history or on disk."""
    rel = directory.relative_to(root).as_posix()
    log = git(root, "log", "--no-renames", "--full-history", "-m", "--format=", "--name-only", "-z",
              "HEAD", base_sha, "--", rel)
    numbers: set[int] = set()
    for raw in log.split("\0"):
        token = raw.strip("\n")
        if not token:
            continue
        path = PurePosixPath(token)
        match = ADR_FILE_RE.match(path.name)
        if match and path.parent.as_posix() == rel:
            numbers.add(int(match.group(1)))
    if directory.is_dir():
        for entry in directory.iterdir():
            match = ADR_FILE_RE.match(entry.name)
            if match and entry.is_file():
                numbers.add(int(match.group(1)))
    return numbers


def next_number(root: Path, directory: Path, base_sha: str) -> int:
    number = max(used_numbers(root, directory, base_sha), default=0) + 1
    if number > MAX_NUMBER:
        raise NumberRefusal("numbers_exhausted", str(directory), 1)
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adr-number", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    nxt = commands.add_parser("next", help="print the next unused record number")
    nxt.add_argument("--repo-root", required=True)
    nxt.add_argument("--dir", required=True)
    nxt.add_argument("--base", required=True)
    return parser


def resolve_paths(repo_root: str, directory: str) -> tuple[Path, Path]:
    root, target = Path(repo_root), Path(directory)
    if not root.is_absolute() or not target.is_absolute():
        raise NumberRefusal("misuse", "--repo-root and --dir must be absolute", 2)
    root, target = root.resolve(), target.resolve()
    if not target.is_relative_to(root):
        raise NumberRefusal("misuse", "--dir must be inside --repo-root", 2)
    return root, target


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root, directory = resolve_paths(args.repo_root, args.dir)
        base_sha = check_repository(root, args.base)
        number = next_number(root, directory, base_sha)
    except NumberRefusal as refusal:
        sys.stderr.write(json.dumps({"error": {"code": refusal.code, "detail": refusal.detail}}) + "\n")
        return refusal.exit_code
    sys.stdout.write(f"{number:03d}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
