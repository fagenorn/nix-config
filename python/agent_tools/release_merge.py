"""The released commit of a release candidate, shared by the watch adapters (issue 555 D6; issue 582 P3).

`released_commit` resolves the commit a release published: `candidate.commit`, or, when the
candidate binds a `merge`, the merge commit of that release PR. `gh` is the one bounded `gh`
runner it reads through. Every caller passes its own deadline, so a resolution spends the
caller's one collection budget and never starts a budget of its own.

This module imports only the standard library: the adapters import it, never the reverse.
"""

import json
import re
import subprocess
import time
from typing import Any

DETAIL_LIMIT = 240
CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}")


def _hex40(value: object) -> bool:
    return isinstance(value, str) and CANDIDATE_SHA.fullmatch(value) is not None


def gh(args: list[str], deadline: float) -> tuple[str, Any, str]:
    """Run `gh <args>` within what is left of `deadline`: `(status, payload, detail)`.

    `status` is `"ok"` with the parsed JSON payload, or one of `lookup_failed`,
    `lookup_timeout`, `payload_invalid` and `executable_missing`, with a payload of `None`.
    An argument the operating system cannot pass (`ValueError`) is `lookup_failed`.
    The child inherits the environment unchanged (D10). `detail` is the bounded stderr after
    the child ran, empty on `lookup_timeout`, the operating-system error on
    `executable_missing` and `gh could not be started: <error>` for a `ValueError`.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", None, ""
    argv = ["gh", *args]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=remaining, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", None, ""
    except OSError as error:
        return "executable_missing", None, str(error)
    except ValueError as error:
        return "lookup_failed", None, f"gh could not be started: {error}"
    detail = done.stderr.strip()[:DETAIL_LIMIT]
    if done.returncode != 0:
        return "lookup_failed", None, detail
    try:
        return "ok", json.loads(done.stdout), detail
    except (ValueError, RecursionError):
        return "payload_invalid", None, detail


def _mismatch(detail: str) -> dict[str, str]:
    return {"outcome": "diverged", "reason": "release_merge_mismatch", "detail": detail}


def released_commit(parameters: dict[str, Any], deadline: float
                    ) -> tuple[str | None, dict[str, str] | None, list[str]]:
    """`(commit, failure, references)`: the commit the release published (issue 555 D6).

    Without `candidate.merge` it is `candidate.commit` and nothing is read. With it, the release
    PR is read, then (only when `MERGED`) its merge commit, and the merge commit is the released
    commit when the PR merged into the target branch as `[merge.base_tip, candidate.commit]`.
    `failure` is `{outcome, reason, detail}` for a merge that does not resolve.
    """
    candidate = parameters["candidate"]
    merge = candidate.get("merge")
    if merge is None:
        return candidate["commit"], None, []
    slug, branch = parameters["target"]["repository"], parameters["target"]["branch"]
    references = [f"repos/{slug}/pulls/{merge['pr']}"]

    def unread(status: str, detail: str) -> tuple[None, dict[str, str], list[str]]:
        return None, {"outcome": "unknown", "reason": status, "detail": detail}, references

    status, view, detail = gh(["pr", "view", str(merge["pr"]), "--repo", slug, "--json",
                              "state,baseRefName,mergeCommit"], deadline)
    if status != "ok":
        return unread(status, detail)
    if not isinstance(view, dict) or not isinstance(view.get("state"), str):
        return unread("payload_invalid", "pull request state is not a string")
    if view["state"] == "OPEN":
        return None, {"outcome": "absent", "reason": "release_unmerged",
                      "detail": "the release pull request is open"}, references
    if view["state"] == "CLOSED":
        return None, _mismatch("the release pull request was closed unmerged"), references
    if view["state"] != "MERGED":
        return unread("payload_invalid", f"pull request state {view['state']!r} is unknown")
    if view.get("baseRefName") != branch:
        return None, _mismatch("the release pull request merged into another branch"), references
    merge_commit = view.get("mergeCommit")
    oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    if not _hex40(oid):
        return unread("payload_invalid", "mergeCommit oid is not 40 lowercase hex characters")
    references.append(f"repos/{slug}/git/commits/{oid}")
    status, commit, detail = gh(["api", f"repos/{slug}/git/commits/{oid}"], deadline)
    if status != "ok":
        return unread(status, detail)
    parents = commit.get("parents") if isinstance(commit, dict) else None
    if not (isinstance(parents, list) and all(
            isinstance(parent, dict) and _hex40(parent.get("sha")) for parent in parents)):
        return unread("payload_invalid", "merge commit parents are not a list of shas")
    if [parent["sha"] for parent in parents] != [merge["base_tip"], candidate["commit"]]:
        return (None, _mismatch("the merge commit parents are not the base tip and the head"),
                references)
    return oid, None, references
