"""Run `git commit` for a registered worker only while its launch is live.

`launch-commit --repo-root R --run-id I --worker-id W -- <git commit args>` asks
`workflow-state check-worker` (by command name on PATH) and runs
`git commit <args>` in the current directory only on a strict `live: true`
reply for exactly that worker, passing git's streams and exit status through.
Any other answer is a refusal: no commit, exit 3, and one line of canonical
JSON on stdout, {"worker_id", "committed": false, "reason"}. A usage error or a
`workflow-state` that cannot be started exits 2.

Residual window: a supersession that lands between the check and the commit is
not caught. The fence narrows that window to one call; it does not claim
atomicity across two processes.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import subprocess
import sys

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

REPLY_KEYS = frozenset({"worker_id", "live", "current_action_id", "reason"})
LIVE = "live"
CHECK_WORKER_FAILED = "check_worker_failed"
MALFORMED_REPLY = "malformed_reply"
REFUSED_EXIT = 3
USAGE_EXIT = 2
SEPARATOR = "--"


class LaunchCommitError(Exception):
    """A helper that cannot be started; main exits 2."""


def check_reply(stdout: bytes, worker_id: str) -> str:
    """The reply's verdict for `worker_id`: "live", its refusal reason, or "malformed_reply"."""
    try:
        reply = json.loads(stdout, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except ValueError:
        return MALFORMED_REPLY
    if not isinstance(reply, dict) or set(reply) != REPLY_KEYS:
        return MALFORMED_REPLY
    live, reason = reply["live"], reply["reason"]
    current = reply["current_action_id"]
    if (type(live) is not bool or reply["worker_id"] != worker_id
            or not isinstance(reason, str)
            or not (current is None or isinstance(current, str))
            or live is not (reason == LIVE)
            or (live and current != worker_id.rpartition(":w")[0])):
        return MALFORMED_REPLY
    return reason


def ask_worker(repo_root: str, run_id: str, worker_id: str) -> str:
    """Ask `workflow-state check-worker` on PATH; a non-zero exit is `check_worker_failed`."""
    try:
        completed = subprocess.run(
            ["workflow-state", "check-worker", "--repo-root", repo_root,
             "--run-id", run_id, "--worker-id", worker_id],
            capture_output=True, check=False)
    except OSError as error:
        raise LaunchCommitError(f"cannot run workflow-state: {error}") from error
    if completed.returncode != 0:
        return CHECK_WORKER_FAILED
    return check_reply(completed.stdout, worker_id)


def fenced_commit(repo_root: str, run_id: str, worker_id: str,
                  git_args: Sequence[str]) -> tuple[int, dict | None]:
    """Commit only on a live verdict: (git's exit, None), or (3, refusal) with no git run."""
    reason = ask_worker(repo_root, run_id, worker_id)
    if reason != LIVE:
        return REFUSED_EXIT, {"worker_id": worker_id, "committed": False, "reason": reason}
    try:
        return subprocess.run(["git", "commit", *git_args], check=False).returncode, None
    except OSError as error:
        raise LaunchCommitError(f"cannot run git: {error}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="launch-commit", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="%(prog)s --repo-root R --run-id I --worker-id W -- <git commit args>")
    parser.add_argument("--repo-root", required=True,
                        help="the ledger repository root")
    parser.add_argument("--run-id", required=True, help="the lifecycle run id")
    parser.add_argument("--worker-id", required=True, help="the registered worker id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    separated = SEPARATOR in argv
    split = argv.index(SEPARATOR) if separated else len(argv)
    args = parser.parse_args(argv[:split])
    if not separated:
        parser.error(f"missing {SEPARATOR} before the git commit arguments")
    try:
        status, refusal = fenced_commit(args.repo_root, args.run_id, args.worker_id,
                                        argv[split + 1:])
    except LaunchCommitError as error:
        print(f"launch-commit: {error}", file=sys.stderr)
        return USAGE_EXIT
    if refusal is not None:
        print(json.dumps(refusal, sort_keys=True, separators=(",", ":")))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
