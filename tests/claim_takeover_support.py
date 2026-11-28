"""What the early-takeover test files share: the ids, git outputs and registry records they read and the process-table helpers."""
from pathlib import Path

from .console_test_support import PROC_PID_DOMAIN

try:
    import agent_tools.claims.claim_takeover as claim_takeover
except ModuleNotFoundError as error:  # the starting commit: only the end-to-end cases run there
    if error.name != "agent_tools.claims.claim_takeover":
        raise
    claim_takeover = None

SLUG = "octo/widgets"
DEAD = "0d0d0d0d-dead"
TAKER_SESSION = "0e0e0e0e-taker"
SPRINT = "0123456789abcdef"
BRANCH = "issue-7-x"
WT = "/srv/repo/.worktrees/issue-7-x"
ORIGIN = ["remote", "get-url", "origin"]
LIST_WT = ["worktree", "list", "--porcelain", "-z"]
STATUS = ["-C", WT, "status", "--porcelain", "-z", "--untracked-files=all"]
LISTING = ("worktree /srv/repo\0HEAD " + "a" * 40 + "\0branch refs/heads/main\0\0worktree " + WT
           + "\0HEAD " + "b" * 40 + "\0branch refs/heads/issue-7-x\0\0")
ORIGIN_URL = "git@github.com:octo/widgets.git\n"
GOOD = {"pid": 2165, "sessionId": DEAD, "cwd": "/x", "procStart": "976", "pidDomain": PROC_PID_DOMAIN}
CALLER = {"pid": 2164, "sessionId": TAKER_SESSION, "cwd": "/x", "procStart": "976",
          "pidDomain": PROC_PID_DOMAIN}


def denied(target):
    """A PermissionError for `target`, as an unreadable path raises it."""
    return PermissionError(13, "Permission denied", str(target))


def running(proc, pid):
    """Make `pid` run in the fake procfs `proc` with the start time 976, as `fake_proc` makes pid 2164 run."""
    stat = Path(proc) / str(pid) / "stat"
    stat.parent.mkdir(parents=True, exist_ok=True)
    stat.write_text(f"{pid} (a) S " + " ".join(["0"] * 18) + " 976 0 0\n")
