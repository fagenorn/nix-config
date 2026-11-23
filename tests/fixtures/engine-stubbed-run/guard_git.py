"""The `git_bin` of the stubbed world's real guard (issue 1530).

Run as `python guard_git.py <fixture root> <github url> <real git> <args...>`. The guard reads a
checkout's origin as `git -C <dir> remote get-url origin` and its push urls as `git -C <dir> remote
get-url --push --all origin`; when `<dir>` is the fixture root or inside it, both print
`<github url>`, so the guard sees the fixture's GitHub origin while the checkout pushes to a local
bare repository. Every other call runs the real git. `insteadOf` is not used: git expands it in
`get-url` and the guard would read the rewritten path.
"""

import os
import sys

ROOT, URL, GIT = sys.argv[1:4]
ARGV = sys.argv[4:]
URL_LOOKUPS = (["remote", "get-url", "origin"], ["remote", "get-url", "--push", "--all", "origin"])


def inside(directory: str) -> bool:
    here = os.path.realpath(directory)
    root = os.path.realpath(ROOT)
    return here == root or here.startswith(root + os.sep)


if len(ARGV) > 2 and ARGV[0] == "-C" and ARGV[2:] in URL_LOOKUPS and inside(ARGV[1]):
    print(URL)
else:
    os.execv(GIT, [GIT, *ARGV])
