"""The integration land lock of a two-branch release (issue 875, ADR-release-011).

A release pull request's head is the integration branch itself, so every landing there moves
the release head and restarts its required checks. The release therefore holds the land lock
of the integration branch (`forge_land_lock`, ADR-claims-009) from the moment its head is
fixed until it has merged. The caller of the driver acquires the lock, with a wait, before the
first preview; the driver only re-checks and releases it, through the two calls here.

`call(action, repository, branch, sha)` runs `forge-claim land <action> --repo <repository>
--branch <branch> --sha <sha>` once in this process, with `--release` on `acquire` and never
`--wait`, and returns `{verdict, lock_sha, detail}`:

- `acquire`: `already_held` (the lock is at `sha`), `acquired` (it was free or stale and is now
  at `sha`), `moved`, `held_by` or `lost_to` (`lock_sha` is the holder's sha, `detail` its pull
  request and holder), or `error`;
- `release`: `released` (the lock is gone, whether or not this call removed it), `not_held`
  (the lock is at another sha, `lock_sha`, and was left alone), or `error`.

`error` covers `no_open_pr` (no open release pull request from `branch` has head `sha`) and
every forge failure; `detail` names it and `lock_sha` is null. `call` never raises: a lock that
cannot be released must not fail a published release, and one left behind is taken over by the
staleness rules of `forge_land_lock` (D3 once the release pull request is merged or closed, D4
after 45 minutes idle).
"""

from types import SimpleNamespace
from typing import Any

from agent_tools.claims import forge_land_lock

ACTIONS = ("acquire", "release")
HELD = "already_held"
DETAIL_LIMIT = 240


def call(action: str, repository: str, branch: str, sha: str) -> dict[str, Any]:
    """One one-shot land lock call as `{verdict, lock_sha, detail}`; never raises."""
    if action not in ACTIONS:
        raise ValueError(f"no land lock action {action!r}")
    args = SimpleNamespace(command="land", action=action, repo=repository, branch=branch,
                           sha=sha, wait=False, release=True)
    try:
        _, result = forge_land_lock.run(args)
    except Exception as error:  # a lock failure must never fail a published release
        return {"verdict": "error", "lock_sha": None,
                "detail": f"{type(error).__name__}: {error}"[:DETAIL_LIMIT]}
    detail = None
    if result["verdict"] == "error":
        detail = f"{result.get('error')}: {result.get('detail')}"[:DETAIL_LIMIT]
    elif result["pr"] is not None and result["verdict"] in ("held_by", "lost_to", "not_held"):
        detail = f"pull request {result['pr']}" + (f", {result['by']}" if result["by"] else "")
    return {"verdict": result["verdict"], "lock_sha": result["lock_sha"], "detail": detail}
