"""The post-release sync of a two-branch release (issue 845, ADR-release-010).

A release that merges the integration branch into the default branch leaves the default branch
one merge commit ahead, and the next release refuses `release_pr_behind` until that commit is
back on the integration branch. `run` brings it back as far as the core may: it pushes a
disposable sync branch at the release merge commit and opens one pull request from it into the
integration branch. It never merges that pull request; the owner does, once CI is green.

The sync is not part of the release transaction. `binding` says whether a compiled profile has
one: the project's integration branch differs from its default branch and a publication node of
the `github-forge` adapter consumes the candidate's `merge`. The driver calls `run` once every
publication action is `satisfied`, so nothing here can stand between the merge and the tag, and
reports what `run` returns as the `sync` member of its result. Nothing is stored: every call
reads the forge again, so a rerun finishes a sync an earlier call left half done.

`run(adapter, parameters)` drives the forge adapter's `sync_branch` then `sync_pr` with
`{target, candidate, integration}`. Each is inspected; an `absent` one is invoked once and
inspected again; anything but `satisfied` ends the sync as `failed`. An inspection that answers
`unknown` with a reason in `TRANSIENT` (a read that failed or timed out) is made once more after
`RETRY_PAUSE_SECONDS`, before or after the invoke, so one failed lookup does not fail the step
(issue 998); the invoke itself is never repeated. It returns `{status, branch, pr, url, reason,
manual}`:

- `done`: one open or merged sync pull request exists; `pr` is its number and `url` its URL;
- `noop`: the integration branch already holds the release merge commit, and nothing was made;
- `failed`: `reason` is `<operation>: <outcome> <reason>`, then ` (<detail>)` when the
  observation carries `facts.detail` (the provider's error text of an `unknown` read), followed
  after an invoke by ` after <result> <error_class>: <reference>` (` after accepted: <reference>`
  for an accepted one), and `manual` lists the commands that finish the sync by hand, from the
  failed operation on. The next call reads the forge again and goes on from what it finds: a
  pushed branch with no pull request gets its pull request opened, and one opened by hand is
  found and reported `done`.

`run` never raises: an exception from the adapter is `failed` with `<operation>: <type>:
<message>` and no manual commands, because a failed sync must not fail a published release.
"""

import copy
import time
from collections.abc import Mapping
from typing import Any

from agent_tools.release import forge_adapter, release_profile

ADAPTER = "github-forge"
REASON_LIMIT = 400
TRANSIENT = ("lookup_failed", "lookup_timeout")
RETRY_PAUSE_SECONDS = 2.0


def binding(compiled: Mapping[str, Any], project: Any) -> dict[str, Any] | None:
    """`{alias, action, target, integration}` of the profile's sync, or None when it has none;
    `action` is the id of the node that merges."""
    if project.integration_branch == project.default_branch:
        return None
    targets = {unit["name"]: unit["parameters"]["target"]
               for unit in compiled["proof_declaration"]["units"]}
    for node in compiled["publication"]:
        if (release_profile.MERGE_MEMBER in compiled["candidate_members"][node["id"]]
                and compiled["adapters"][node["adapter"]]["adapter"] == ADAPTER):
            return {"alias": node["adapter"], "action": node["id"],
                    "target": release_profile.thaw(targets[node["id"]]),
                    "integration": project.integration_branch}
    return None


def run(adapter: Any, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The sync outcome `{status, branch, pr, url, reason, manual}`; never raises."""
    outcome: dict[str, Any] = {"status": "failed", "branch": None, "pr": None, "url": None,
                               "reason": None, "manual": []}

    def failed(reason: str, manual: list[str]) -> dict[str, Any]:
        return {**outcome, "reason": reason[:REASON_LIMIT], "manual": manual}

    operation = forge_adapter.SYNC_OPERATIONS[0]
    try:
        outcome["branch"] = forge_adapter.SYNC_BRANCH.format(
            default=parameters["target"]["branch"], integration=parameters["integration"],
            version=parameters["candidate"]["version"])
        for operation in forge_adapter.SYNC_OPERATIONS:
            def request() -> dict[str, Any]:
                return {"kind": "effect", "operation": operation,
                        "parameters": copy.deepcopy(dict(parameters))}

            def observe() -> dict[str, Any]:
                seen = adapter.inspect(request())
                if seen["outcome"] == "unknown" and seen["reason"] in TRANSIENT:
                    time.sleep(RETRY_PAUSE_SECONDS)
                    seen = adapter.inspect(request())
                return seen

            observed, after = observe(), ""
            if observed["outcome"] == "absent":
                result = adapter.invoke(request())
                after = (f" after accepted: {result['reference']}" if result["result"] == "accepted"
                         else f" after {result['result']} {result['error_class']}: "
                              f"{result['reference']}")
                observed = observe()
            if observed["outcome"] != "satisfied":
                detail = observed["facts"].get("detail")
                return failed(f"{operation}: {observed['outcome']} {observed['reason']}"
                              f"{f' ({detail})' if detail else ''}{after}",
                              list(observed["facts"].get("commands", [])))
            if observed["reason"] == "already_contained":
                return {**outcome, "status": "noop"}
        references = observed["references"]
        url = references[0] if references and references[0].startswith("http") else None
        return {**outcome, "status": "done", "pr": observed["observed_subject"]["pr"], "url": url}
    except Exception as error:  # a failed sync must never fail the published release
        return failed(f"{operation}: {type(error).__name__}: {error}", [])
