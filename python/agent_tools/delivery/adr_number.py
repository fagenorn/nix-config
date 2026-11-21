"""`adr-number`: the number a new decision record takes (issue 1440).

    adr-number next --repo-root <absolute> --dir <absolute> --base <ref>
    adr-number renumber --repo-root <absolute> --record <absolute> --base <ref> [--to NNN]

`next` prints one past the highest record number ever used in `--dir`, zero-padded to
three digits, and a newline (`004`). It writes no file and commits nothing.

A number is used when a file directly in `--dir` named like a record (`NNN-<slug>.md`)
exists in the working tree, or existed in any commit reachable from HEAD or from
`--base`, deleted records included: the history walk is not simplified, so a record
added and deleted on one side of a merge still counts. Files in subdirectories of
`--dir` and in other directories do not count. An empty or absent `--dir` gives `001`.

`--repo-root` and `--dir` must be absolute, `--dir` must be `--repo-root` or inside it,
and `--repo-root` must be the checkout's toplevel.

`renumber` gives the branch's own record a new number: it moves `--record` (a tracked
file `NNN-<slug>.md` in a directory named `adr`, whose first line is the header naming
its own id) with `git mv` to the target number (`--to`, three digits and not `000`, or
else one past the highest number used in the record's directory, as `next` counts it),
and rewrites the old id to the new one in the record's header and in every citation the
branch added. It stages only the rename, commits nothing and adds no `**Formerly:**`
line. A `--to` that is already used is refused.

A citation is branch-added when its line is one the working tree adds relative to the
merge base of HEAD and `--base` (committed, staged or uncommitted edits to tracked
files), or any line of an untracked file that git does not ignore; a file anywhere in
the repository counts, and a line from the base keeps its citation. Files that are not
UTF-8 are left alone. Every check runs before the first change, so a refusal changes
nothing.

`renumber` prints one JSON line on stdout: `from` and `to` (the two ids), `record` (the
new path relative to the root) and `rewritten` (the sorted root-relative paths whose
content changed, the record at its new path).

Exit 0 is done. Exit 1 refuses (`git_failed`, `shallow_history`, `numbers_exhausted`,
`record_missing`, `record_untracked`, `header_mismatch`, `number_used`) and exit 2 is
misuse (`misuse`, `not_a_repository_root`, `base_unknown`, `not_a_record`). Both write
`{"error": {code, detail}}` to stderr and nothing to stdout. A shallow checkout is
refused because its history cannot name every used number.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from agent_tools.delivery.context_map_lint import ADR_FILE_RE, ADR_HEADER_RE

GIT_TIMEOUT = 120
MAX_NUMBER = 999
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
TARGET_RE = re.compile(r"\d{3}")


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


def branch_added_lines(root: Path, merge_base: str) -> dict[Path, set[int]]:
    """Absolute path -> 1-based lines the working tree adds relative to `merge_base`."""
    added: dict[Path, set[int]] = {}
    names = git(root, "diff", "--name-only", "-z", "--no-renames", merge_base, "--")
    for name in filter(None, names.split("\0")):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        diff = git(root, "diff", "-U0", "--no-renames", "--no-ext-diff", "--no-color", merge_base, "--", name)
        lines: set[int] = set()
        for hunk in HUNK_RE.finditer(diff):
            start = int(hunk.group(1))
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            lines.update(range(start, start + count))
        if lines:
            added[path] = lines
    for name in filter(None, git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        added[path] = set(range(1, count + 1))
    return added


def split_lines(text: str) -> list[str]:
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def rewrite(text: str, pattern: re.Pattern[str], new_id: str, lines: set[int]) -> str:
    return "".join(pattern.sub(new_id, line) if number in lines else line
                   for number, line in enumerate(split_lines(text), start=1))


def renumber(root: Path, record: Path, base: str, to: int | None) -> dict:
    if not root.is_absolute() or not record.is_absolute():
        raise NumberRefusal("misuse", "--repo-root and --record must be absolute", 2)
    root, record = root.resolve(), record.resolve()
    if not record.is_relative_to(root):
        raise NumberRefusal("misuse", "--record must be inside --repo-root", 2)
    base_sha = check_repository(root, base)
    rel = record.relative_to(root).as_posix()
    if not record.is_file():
        raise NumberRefusal("record_missing", rel, 1)
    name = ADR_FILE_RE.match(record.name)
    if name is None or record.parent.name != "adr":
        raise NumberRefusal("not_a_record", rel, 2)
    slug, old = record.parent.parent.name, name.group(1)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
                             capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    if tracked.returncode != 0:
        raise NumberRefusal("record_untracked", rel, 1)
    first = record.read_text(encoding="utf-8").split("\n", 1)[0]
    header = ADR_HEADER_RE.match(first)
    if header is None or header.group(1) != slug or header.group(2) != old:
        raise NumberRefusal("header_mismatch", rel, 1)
    used = used_numbers(root, record.parent, base_sha)
    if to is None:
        new = next_number(root, record.parent, base_sha)
    elif to in used:
        raise NumberRefusal("number_used", f"{to:03d}", 1)
    else:
        new = to
    merge_base = git(root, "merge-base", "HEAD", base_sha).strip()
    added = branch_added_lines(root, merge_base)
    added.setdefault(record, set())
    added[record] = added[record] | {1}
    pattern = re.compile(rf"\bADR-{re.escape(slug)}-{old}\b")
    new_id = f"ADR-{slug}-{new:03d}"
    target = record.with_name(f"{new:03d}{record.name[3:]}")
    changes: dict[Path, str] = {}
    for path, lines in added.items():
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        rewritten = rewrite(text, pattern, new_id, lines)
        if rewritten != text:
            changes[target if path == record else path] = rewritten
    git(root, "mv", "--", rel, target.relative_to(root).as_posix())
    for path, content in changes.items():
        path.write_bytes(content.encode("utf-8"))
    return {"from": f"ADR-{slug}-{old}", "to": new_id, "record": target.relative_to(root).as_posix(),
            "rewritten": sorted(path.relative_to(root).as_posix() for path in changes)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adr-number", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    nxt = commands.add_parser("next", help="print the next unused record number")
    nxt.add_argument("--repo-root", required=True)
    nxt.add_argument("--dir", required=True)
    nxt.add_argument("--base", required=True)
    move = commands.add_parser("renumber", help="give the branch's record a new number")
    move.add_argument("--repo-root", required=True)
    move.add_argument("--record", required=True)
    move.add_argument("--base", required=True)
    move.add_argument("--to")
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
        if args.command == "renumber":
            if args.to is not None and (not TARGET_RE.fullmatch(args.to) or args.to == "000"):
                raise NumberRefusal("misuse", "--to must be three digits and not 000", 2)
            done = renumber(Path(args.repo_root), Path(args.record), args.base,
                            None if args.to is None else int(args.to))
            sys.stdout.write(json.dumps(done, sort_keys=True) + "\n")
            return 0
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
