"""`program-copies`: a skill's Workflow programs, copied into the checkout (issue 912, ADR-delivery-008).

The Workflow tool loads a script by path. A skill directory reached through a store link
stops resolving once an activation replaces it, and is then refused as a script path. So a
lead starts the programs from these copies.

`program-copies --repo-root <checkout> --from <dir>` copies every regular `*.js` file directly
in `<dir>` (not recursive; a symlink, the directory itself or a file, is followed, so a Nix
store link is copied by its content) to `<checkout>/.program-copies/<name>/<file>`. `<name>` is
the last component of `--from` as given, not resolved: a resolved store path would name the
hash. Directories are created with parents. The printed paths are built from `--repo-root`
as given.

`--repo-root` must be the top level of a git working tree: `git -C <checkout> rev-parse
--show-toplevel` succeeds and prints a path that resolves to the same directory as
`<checkout>`. That holds for a main checkout and a linked worktree alike, so the copies are
always inside the checkout the lead runs in, never under a git directory (a linked
worktree's git directory and common directory lie outside its working directory, and the
Workflow tool accepts a script path only from the working directory or an added directory).

`<checkout>/.program-copies/.gitignore` holds exactly `*\\n`; git then ignores the whole
directory, the ignore file included, so the copies never show as untracked and `git add -A`
never stages them. A missing or different one is written the way a copy is.

A copy is left untouched (no write, same inode and mtime) when it is a regular file, not a
symlink, whose bytes equal the source's. Otherwise the source bytes go to a temporary file
created in the copy directory, mode 0644, which is `os.replace`d onto the copy path: a
reader that already opened the old copy keeps its bytes, a reader opening the path sees the
old or the new file and never a partial one, and a symlink at the copy path becomes a
regular file. On any failure the temporary file is removed. Other files in the copy
directory are left alone.

Success prints one JSON line mapping each copied file name to its absolute copy path.
Refusals write `{"error": {code, detail}}` to stderr. Exit 1: `not_a_checkout` (the git call
fails, prints nothing, or prints another top level, as for a subdirectory or a `.git`
directory; nothing is created), `no_programs` (`--from` is not a directory or holds no
`*.js` file; nothing is created), `copy_failed` (an OSError reading or writing). Exit 2:
`relative_path` (`--repo-root` or `--from` is not absolute).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

COPY_DIR = ".program-copies"
IGNORE_NAME = ".gitignore"
IGNORE_BODY = b"*\n"
GIT_TIMEOUT = 120


class CopyRefusal(Exception):
    """One refusal or failure: a closed code, its detail and the exit code (2 refuse, 1 fail)."""

    def __init__(self, code: str, detail: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


def checkout_root(repo_root: Path) -> Path:
    """`repo_root` when it is the top level of a git working tree, else a `not_a_checkout` refusal."""
    try:
        done = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CopyRefusal("not_a_checkout", f"git failed: {error}", 1) from None
    top = done.stdout.strip()
    if done.returncode != 0 or not top:
        raise CopyRefusal("not_a_checkout", done.stderr.strip() or f"{repo_root} is not in a working tree", 1)
    try:
        same = Path(top).resolve() == repo_root.resolve()
    except OSError as error:
        raise CopyRefusal("not_a_checkout", str(error), 1) from None
    if not same:
        raise CopyRefusal("not_a_checkout", f"{repo_root} is not the top level of its checkout ({top})", 1)
    return repo_root


def programs(source: Path) -> list[Path]:
    """The regular `*.js` files directly in `source` (links followed), sorted by name."""
    try:
        found = sorted(p for p in source.iterdir() if p.name.endswith(".js") and p.is_file())
    except OSError:
        found = []
    if not found:
        raise CopyRefusal("no_programs", f"{source} holds no *.js file", 1)
    return found


def _replace(target: Path, data: bytes) -> None:
    """Write `data` to a temporary file beside `target` and rename it over `target`."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(name, 0o644)
        os.replace(name, target)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def _sync(target: Path, data: bytes) -> None:
    if target.is_file() and not target.is_symlink() and target.read_bytes() == data:
        return
    _replace(target, data)


def place(repo_root: Path, source: Path) -> dict[str, str]:
    """Copy `source`'s programs under `repo_root`; the file name -> absolute copy path."""
    root = checkout_root(repo_root)
    files = programs(source)
    base = root / COPY_DIR
    target = base / source.name
    mapping: dict[str, str] = {}
    try:
        contents = [(f.name, f.read_bytes()) for f in files]
        target.mkdir(parents=True, exist_ok=True)
        _sync(base / IGNORE_NAME, IGNORE_BODY)
        for name, data in contents:
            _sync(target / name, data)
            mapping[name] = str(target / name)
    except OSError as error:
        raise CopyRefusal("copy_failed", str(error), 1) from None
    return mapping


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="program-copies", description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--from", required=True, dest="source")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for path in (args.repo_root, args.source):
            if not os.path.isabs(path):
                raise CopyRefusal("relative_path", f"{path} is not absolute", 2)
        mapping = place(Path(args.repo_root), Path(args.source))
    except CopyRefusal as refusal:
        sys.stderr.write(json.dumps({"error": {"code": refusal.code, "detail": refusal.detail}},
                                    sort_keys=True, separators=(",", ":")) + "\n")
        return refusal.exit_code
    sys.stdout.write(json.dumps(mapping, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
