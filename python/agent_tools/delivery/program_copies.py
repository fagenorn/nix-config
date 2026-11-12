"""`program-copies`: a skill's Workflow programs, copied into the checkout (issues 912 and 981, ADR-delivery-008, ADR-delivery-009).

The Workflow tool loads a script by path. A skill directory reached through a store link
stops resolving once an activation replaces it, and is then refused as a script path. So a
lead starts the programs from these copies.

`program-copies --repo-root <checkout> --from <dir>` copies every regular `*.js` file directly
in `<dir>` (not recursive; a symlink, the directory itself or a file, is followed, so a Nix
store link is copied by its content) to `<checkout>/.program-copies/<name>/<set>/<file>`.
`<name>` is the last component of `--from` as given, not resolved: a resolved store path would
name the hash. `<set>` is the first 12 hex digits of a SHA-256 over every program's name and
bytes, so one version of the programs has one directory, a set, and another version another.
A last component that is empty, `.` or `..` (as in `/skills/deliver-standard/sub/..`), or an
existing `.program-copies`, `.program-copies/<name>` or set that is a symlink, is refused
before anything is written: the copies are never placed outside
`<checkout>/.program-copies/<name>`. Directories are created with parents. The printed paths
are built from `--repo-root` as given.

A set is never modified once it exists (issue 981). A running batch read its own program
once, at launch, but the Workflow runtime reads the child program from its path at every
child launch; children launched from a set therefore run the version the batch was launched
with, whatever is placed later. A caller takes every path of one launch from one output.

`--repo-root` must be the top level of a git working tree: `git -C <checkout> rev-parse
--show-toplevel` succeeds and prints a path that resolves to the same directory as
`<checkout>`. That holds for a main checkout and a linked worktree alike, so the copies are
always inside the checkout the lead runs in, never under a git directory (a linked
worktree's git directory and common directory lie outside its working directory, and the
Workflow tool accepts a script path only from the working directory or an added directory).

`<checkout>/.program-copies/.gitignore` holds exactly `*\\n`; git then ignores the whole
directory, the ignore file included, so the copies never show as untracked and `git add -A`
never stages them. A missing or different one is written to a temporary file beside it and
renamed into place.

Placing a set that exists writes no file and prints the same paths; it only sets the set
directory's modification time to now, which records the set's last use. An existing set
whose files are not exactly the programs (a missing, extra, linked or different file) is
refused as `copy_failed` and left as it is. A new set is written to a temporary directory
`.tmp-*` beside it, files mode 0644, and renamed into place, so a reader sees a whole set or
none; when another placement created the same set first, that one is used. On any failure
the temporary directory is removed.

After a placement, every other set (a directory named by 12 hex digits) and every `.tmp-*`
directory under `.program-copies/<name>` whose modification time is more than 24 hours old
is removed; a failure to remove one is ignored. The set just placed is never removed. A
batch runs about four hours and every launch stamps its set, so a set a running batch uses
was stamped less than 24 hours ago, while the sets kept are bounded by the versions placed
within a day. Anything else in that directory is left alone, including the `*.js` files an
earlier version of this command placed directly in it: a batch launched from those keeps
them, and no placement changes them any more.

Success prints one JSON line mapping each copied file name to its absolute copy path.
Refusals write `{"error": {code, detail}}` to stderr. Exit 1: `not_a_checkout` (the git call
fails, prints nothing, or prints another top level, as for a subdirectory or a `.git`
directory; nothing is created), `no_programs` (`--from` is not a directory or holds no
`*.js` file; nothing is created), `unsafe_destination` (the destination rule above; nothing is written), `copy_failed` (an OSError
reading or writing, or an existing set that does not hold the programs). Exit 2:
`relative_path` (`--repo-root` or `--from` is not absolute).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

COPY_DIR = ".program-copies"
IGNORE_NAME = ".gitignore"
IGNORE_BODY = b"*\n"
GIT_TIMEOUT = 120
SET_NAME = re.compile(r"[0-9a-f]{12}\Z")
TEMP_PREFIX = ".tmp-"
KEEP_SECONDS = 24 * 60 * 60


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
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=TEMP_PREFIX)
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


def set_name(contents: list[tuple[str, bytes]]) -> str:
    """The directory name of one version of the programs: 12 hex digits over names and bytes."""
    digest = hashlib.sha256()
    for name, data in contents:
        for part in (name.encode(), data):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()[:12]


def _holds(directory: Path, contents: list[tuple[str, bytes]]) -> bool:
    """Whether `directory` holds exactly `contents` as regular files."""
    if sorted(os.listdir(directory)) != sorted(name for name, _ in contents):
        return False
    return all((directory / name).is_file() and not (directory / name).is_symlink()
               and (directory / name).read_bytes() == data for name, data in contents)


def _place_set(directory: Path, contents: list[tuple[str, bytes]]) -> None:
    """Create `directory` holding `contents`, or confirm it already does; never change one that exists."""
    if not directory.exists():
        temp = Path(tempfile.mkdtemp(dir=directory.parent, prefix=TEMP_PREFIX))
        try:
            for name, data in contents:
                (temp / name).write_bytes(data)
                os.chmod(temp / name, 0o644)
            os.chmod(temp, 0o755)
            try:
                os.rename(temp, directory)
            except OSError:
                if not directory.is_dir():
                    raise
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    if not _holds(directory, contents):
        raise CopyRefusal("copy_failed", f"{directory} exists and does not hold these programs", 1)
    os.utime(directory)


def _prune(target: Path, keep: Path) -> None:
    """Remove the sets and temporary directories under `target` last used over a day ago, never `keep`."""
    cutoff = time.time() - KEEP_SECONDS
    try:
        entries = list(target.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name == keep.name or not (SET_NAME.match(entry.name) or entry.name.startswith(TEMP_PREFIX)):
            continue
        try:
            if entry.is_symlink() or not entry.is_dir() or entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)


def _check_destination(root: Path, base: Path, target: Path, *extra: Path) -> None:
    """Refuse a destination that is not a plain directory chain inside the checkout."""
    if target.name in ("", ".", ".."):
        raise CopyRefusal("unsafe_destination", f"{target.name!r} is not a usable directory name", 1)
    for part in (base, target, *extra):
        if part.is_symlink():
            raise CopyRefusal("unsafe_destination", f"{part} is a symlink", 1)
    if target.resolve().parent.parent != root.resolve():
        raise CopyRefusal("unsafe_destination", f"{target} is not directly under {base}", 1)


def place(repo_root: Path, source: Path) -> dict[str, str]:
    """Copy `source`'s programs under `repo_root`; the file name -> absolute copy path."""
    root = checkout_root(repo_root)
    files = programs(source)
    base = root / COPY_DIR
    target = base / source.name
    try:
        contents = [(f.name, f.read_bytes()) for f in files]
    except OSError as error:
        raise CopyRefusal("copy_failed", str(error), 1) from None
    directory = target / set_name(contents)
    _check_destination(root, base, target, directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
        _sync(base / IGNORE_NAME, IGNORE_BODY)
        _place_set(directory, contents)
    except OSError as error:
        raise CopyRefusal("copy_failed", str(error), 1) from None
    _prune(target, directory)
    return {name: str(directory / name) for name, _ in contents}


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
