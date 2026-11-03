"""Make a private copy of the retained root, so a commit elsewhere cannot void a retained run (#573, RP11).

The retained tier compares its root's refs and object listing before and after every test. Any session that
commits to the shared checkout moves them. The copy is a `git clone --local --no-checkout` (hard-linked objects,
its own refs and object store) plus the gitignored evidence directory the tests read, which a clone never carries.

Run: python -m agent_tools.retained_root_copy <root> <dest> [evidence-dir]
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_EVIDENCE = ".superpowers/review-evidence/100"


def copy_root(root, dest, evidence=DEFAULT_EVIDENCE) -> Path:
    """Clone `root` into the absent `dest` and copy `root/evidence` into it; return `dest`."""
    root, dest = Path(root).resolve(), Path(dest)
    source = root / evidence
    if not source.is_dir():
        raise FileNotFoundError(f"retained evidence directory missing: {source}")
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    subprocess.run(["git", "clone", "-q", "--local", "--no-checkout", str(root), str(dest)],
                   check=True, env=env)
    shutil.copytree(source, dest / evidence, symlinks=True)
    return dest


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print("usage: retained_root_copy <root> <dest> [evidence-dir]", file=sys.stderr)
        return 2
    try:
        copy_root(*args)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"retained_root_copy: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
