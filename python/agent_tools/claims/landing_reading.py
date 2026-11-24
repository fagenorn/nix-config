"""`landing_reading`: the verify scripts that read a host's landings after its deployment.

`python -m agent_tools.claims.landing_reading syncs|ci-runs --repo SLUG --issue N --host H
--landings K` (`ci-runs` also `--baseline-runs R`) reads the forge and prints one JSON line. The
only forge access is `read(path)`, one `forge_api.api_get`-shaped GET returning parsed JSON (the
closing issues of a pull request come from `forge_markers.closing_issues`); nothing is written, and
no commit date or host clock is read: every date is a forge `created_at`, `merged_at` or
`run_started_at`, and a sync is counted by ancestry.

The boundary is the `created_at` of the earliest comment on `--issue` that is a `verify-due`
marker with `host == --host` by a trusted author (`forge_markers.trusted_author`, OWNER or MEMBER):
the forge time at which the host had deployed the check. With none, it prints
`{"status": "not_deployed"}` and exits 75.

A landing is a pull request merged into the default branch after the boundary whose merge commit
is not its own head (the land lock queue measurement's rule: a pull request the forge marks merged because its head
reached the branch inside another landing held no lock cycle), whose closing issue has a `claim`
marker whose `branch` is the pull request's head ref, the latest such claim's `holder` starting
with `<host>/`. Landings are taken oldest merge first; the pull request listing is read at most
10 pages of 100.

`syncs`: a landing counts when its closing issue has a trusted `look` marker with
`answer=approved` and `pr=<n>`. Its first approval is the one with the smallest comment id;
`approvals` is the number of such markers; it is dated by the first approval's `created_at`, which
must be after the boundary. `syncs_after_first_approval` is the number of commits with two or more
parents on the first-parent chain from the merged head back to the first approval's `head` (one
`repos/<slug>/commits/<sha>` read per step, at most 50 steps; a longer chain, or one that never
reaches that head, is `forge_unreadable`). The first K such landings are judged: exit 0 `met` when
each has `approvals == 1` and `syncs_after_first_approval <= 1`, exit 1 `not_met` otherwise, exit
75 `not_yet` with fewer than K. JSON: `{"status", "since", "landings": [{"pr", "approvals",
"syncs_after_first_approval"}]}`.

`ci-runs` reproduces the CI-run count of the land lock queue measurement: the landings are those whose
pull request `created_at` is after the boundary, the first K by merge time, and the runs are the
attempts of the `ci.yaml` workflow on the head branch whose `run_started_at` lies in
`[created_at, merged_at]`, read attempt by attempt (`actions/runs/<id>/attempts/<n>`; the run
object shows only its latest attempt). Exit 0 `met` when their sum is below `--baseline-runs`, exit
1 `not_met` otherwise, exit 75 `not_yet` while fewer than K exist. JSON: `{"status", "since",
"landings": K, "runs", "baseline_runs"}`.

A listing the forge truncated below its `total_count`, or any `ForgeError`, prints
`{"status": "forge_unreadable", "reason"}` and exits 1; `not yet` is always 75, never 1; a usage
error exits 2.
"""

import argparse
import json
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import Any

from agent_tools.claims import forge_markers as fm
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

NOT_YET = 75
TRUSTED = ("OWNER", "MEMBER")
WORKFLOW = "ci.yaml"
PULL_PAGES = 10
PAGE = 100
CHAIN_STEPS = 50
ACTIONS = ("syncs", "ci-runs")

Read = Callable[[str], Any]


class Unreadable(Exception):
    """A forge answer that cannot support a reading: printed as `forge_unreadable`."""


def _when(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ForgeError("payload_invalid", f"unreadable timestamp {value!r}") from None


def _objects(payload: Any, what: str) -> list[dict]:
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ForgeError("payload_invalid", f"{what} is not an array of objects")
    return payload


def _object(payload: Any, what: str) -> dict:
    if not isinstance(payload, dict):
        raise ForgeError("payload_invalid", f"{what} is not an object")
    return payload


class Reading:
    """One run's reads: the comments of each issue are fetched once."""

    def __init__(self, read: Read, slug: str) -> None:
        self.read, self.slug = read, slug
        self._comments: dict[int, list[tuple[fm.Marker, dict]]] = {}

    def markers(self, issue: int) -> list[tuple[fm.Marker, dict]]:
        """Every marker of the issue with its comment object, ascending comment id."""
        if issue not in self._comments:
            found = []
            for page in range(1, PULL_PAGES + 1):
                comments = _objects(self.read(
                    f"repos/{self.slug}/issues/{issue}/comments?per_page={PAGE}&page={page}"), "comments")
                found += [(marker, comment) for comment in comments
                          if (marker := fm.parse(comment)) is not None]
                if len(comments) < PAGE:
                    break
            else:
                raise Unreadable(f"the comments of issue {issue} exceed {PULL_PAGES * PAGE}")
            self._comments[issue] = sorted(found, key=lambda pair: pair[0].comment_id)
        return self._comments[issue]

    def trusted(self, issue: int, kind: str) -> list[tuple[fm.Marker, dict]]:
        return [(m, c) for m, c in self.markers(issue)
                if m.kind == kind and fm.trusted_author(c, (), TRUSTED)]

    def boundary(self, issue: int, host: str) -> str | None:
        """The `created_at` of the earliest trusted `verify-due` marker of `host`, or None."""
        due = [c["created_at"] for m, c in self.trusted(issue, "verify-due") if m.fields.get("host") == host]
        return min(due, key=_when) if due else None

    def default_branch(self) -> str:
        branch = _object(self.read(f"repos/{self.slug}"), "repository").get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise ForgeError("payload_invalid", "repository has no default branch")
        return branch

    def merged_pulls(self, since: datetime) -> list[dict]:
        """The pull requests merged after `since` whose merge commit is not their head, oldest merge first."""
        branch, found = self.default_branch(), []
        for page in range(1, PULL_PAGES + 1):
            pulls = _objects(self.read(
                f"repos/{self.slug}/pulls?state=closed&base={branch}&per_page={PAGE}&page={page}"), "pulls")
            found += pulls
            if len(pulls) < PAGE:
                break
        else:
            if min(_when(p.get("created_at")) for p in found) > since:
                raise Unreadable(f"the pull requests exceed {PULL_PAGES * PAGE}")
        landings = [p for p in found if p.get("merged_at") and _when(p["merged_at"]) > since
                    and p.get("merge_commit_sha") != _object(p.get("head"), "head").get("sha")]
        return sorted(landings, key=lambda p: (_when(p["merged_at"]), p["number"]))

    def of_host(self, pull: dict, host: str) -> int | None:
        """The closing issue whose latest claim on the pull request's head ref is `host`'s, or None."""
        for issue in fm.closing_issues(self.slug, pull["number"]):
            claims = [m for m, _ in self.markers(issue)
                      if m.kind == "claim" and m.fields.get("branch") == pull["head"].get("ref")]
            if claims and claims[-1].fields.get("holder", "").startswith(f"{host}/"):
                return issue
        return None

    def landings(self, since: datetime, host: str) -> Iterator[tuple[dict, int]]:
        for pull in self.merged_pulls(since):
            issue = self.of_host(pull, host)
            if issue is not None:
                yield pull, issue

    def syncs_after(self, first: str, head: str) -> int:
        """The merge commits on the first-parent chain from `head` back to `first`."""
        syncs, at = 0, head
        for _ in range(CHAIN_STEPS):
            if at == first:
                return syncs
            commit = _object(self.read(f"repos/{self.slug}/commits/{at}"), "commit")
            parents = [p.get("sha") for p in _objects(commit.get("parents"), "parents")]
            if not parents:
                raise Unreadable(f"the chain from {head} never reaches {first}")
            syncs += len(parents) >= 2
            at = parents[0]
        if at == first:
            return syncs
        raise Unreadable(f"the chain from {head} to {first} exceeds {CHAIN_STEPS} steps")

    def attempts(self, branch: str, start: datetime, end: datetime) -> int:
        """The attempts of the workflow on `branch` that started inside `[start, end]`."""
        runs, total = [], None
        for page in range(1, PULL_PAGES + 1):
            listing = _object(self.read(
                f"repos/{self.slug}/actions/workflows/{WORKFLOW}/runs?branch={branch}&per_page={PAGE}&page={page}"),
                "runs")
            batch, total = _objects(listing.get("workflow_runs"), "workflow_runs"), listing.get("total_count")
            runs += batch
            if len(batch) < PAGE or len(runs) >= total:
                break
        if not isinstance(total, int) or len(runs) < total:
            raise Unreadable(f"the runs of {branch} are truncated below their total_count")
        counted = 0
        for run in runs:
            for attempt in range(1, run["run_attempt"] + 1):
                started = _object(self.read(
                    f"repos/{self.slug}/actions/runs/{run['id']}/attempts/{attempt}"), "attempt")
                counted += start <= _when(started.get("run_started_at")) <= end
        return counted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="landing_reading", description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--repo", required=True, help="the repository slug, owner/name")
    parser.add_argument("--issue", type=int, required=True, help="the issue carrying the verify-due marker")
    parser.add_argument("--host", required=True)
    parser.add_argument("--landings", type=int, required=True, help="how many landings are judged")
    parser.add_argument("--baseline-runs", type=int, default=None, help="ci-runs: the runs to stay below")
    return parser


def _print(document: Mapping) -> None:
    print(json.dumps(document, sort_keys=True))


def _syncs(reading: Reading, args: argparse.Namespace, since: str) -> int:
    rows = []
    for pull, issue in reading.landings(_when(since), args.host):
        approvals = sorted(((m, c) for m, c in reading.trusted(issue, "look")
                            if m.fields.get("answer") == "approved" and m.fields.get("pr") == str(pull["number"])),
                           key=lambda pair: pair[0].comment_id)
        if not approvals or _when(approvals[0][1]["created_at"]) <= _when(since):
            continue
        syncs = reading.syncs_after(approvals[0][0].fields.get("head"), pull["head"]["sha"])
        rows.append({"pr": pull["number"], "approvals": len(approvals), "syncs_after_first_approval": syncs})
        if len(rows) == args.landings:
            break
    if len(rows) < args.landings:
        _print({"status": "not_yet", "since": since, "landings": rows})
        return NOT_YET
    met = all(row["approvals"] == 1 and row["syncs_after_first_approval"] <= 1 for row in rows)
    _print({"status": "met" if met else "not_met", "since": since, "landings": rows})
    return 0 if met else 1


def _ci_runs(reading: Reading, args: argparse.Namespace, since: str) -> int:
    judged = []
    for pull, _ in reading.landings(_when(since), args.host):
        if _when(pull.get("created_at")) > _when(since):
            judged.append(pull)
        if len(judged) == args.landings:
            break
    if len(judged) < args.landings:
        _print({"status": "not_yet", "since": since, "landings": len(judged)})
        return NOT_YET
    runs = sum(reading.attempts(p["head"]["ref"], _when(p["created_at"]), _when(p["merged_at"])) for p in judged)
    met = runs < args.baseline_runs
    _print({"status": "met" if met else "not_met", "since": since, "landings": args.landings,
            "runs": runs, "baseline_runs": args.baseline_runs})
    return 0 if met else 1


def main(argv: list[str] | None = None, *, read: Read = forge_api.api_get) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.action == "ci-runs") != (args.baseline_runs is not None):
        parser.error("--baseline-runs goes with ci-runs and no other action")
    reading = Reading(read, args.repo)
    try:
        since = reading.boundary(args.issue, args.host)
        if since is None:
            _print({"status": "not_deployed"})
            return NOT_YET
        return (_syncs if args.action == "syncs" else _ci_runs)(reading, args, since)
    except (ForgeError, Unreadable) as error:
        _print({"status": "forge_unreadable", "reason": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
