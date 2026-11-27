"""`lock_bump_forge`: a lock bump's GitHub reads and writes, each one `gh` call.

`open_bumps` lists open pull requests into a base and keeps those whose head is a `lock-bump-<revision>`
branch of the repository itself. `checks` and `verdict` send one GraphQL call; `judge` reads only the
contexts the branch protection requires: red when any failed, green when at least one exists and all
succeeded, else pending. `checks` also needs the forge's merge state to be CLEAN, HAS_HOOKS or UNSTABLE
before it says green and says merged or closed for a pull in those states; `verdict` judges any pull by
its required contexts alone. A second page of contexts, a missing pull request and a head that is not a
full commit are `ForgeError("payload_invalid")`. `open_pull` and `merge` are the adoption's forge calls,
and a merge is pinned to the head that was read, so branch protection always applies. `close` closes the
pull request and deletes its branch. `compare` returns the forge's status of a revision against another.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, NamedTuple

from agent_tools.console import approve
from agent_tools.console.lock_bump_tree import BRANCH, revision_of_branch
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      state headRefOid mergeStateStatus
      commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) {
        pageInfo { hasNextPage }
        nodes { __typename
          ... on CheckRun { name status conclusion isRequired(pullRequestNumber: $number) }
          ... on StatusContext { context state isRequired(pullRequestNumber: $number) } } } } } } }
    }
  }
}"""
FAILED_RUNS = frozenset(("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"))
PASSED_RUNS = frozenset(("SUCCESS", "NEUTRAL", "SKIPPED"))
FAILED_STATUSES = frozenset(("FAILURE", "ERROR"))
MERGEABLE = frozenset(("CLEAN", "HAS_HOOKS", "UNSTABLE"))
COMPARED = frozenset(("ahead", "behind", "identical", "diverged"))


class OpenBump(NamedTuple):
    number: int
    revision: str


class Checks(NamedTuple):
    state: str
    head: str | None
    failing: tuple[str, ...]


def _invalid(detail: str) -> ForgeError:
    return ForgeError("payload_invalid", detail)


def _name(node: dict) -> str:
    return str(node.get("name") if node.get("__typename") == "CheckRun" else node.get("context"))


def _failed(node: dict) -> bool:
    if node.get("__typename") == "CheckRun":
        return node.get("conclusion") in FAILED_RUNS
    return node.get("state") in FAILED_STATUSES


def _passed(node: dict) -> bool:
    if node.get("__typename") == "CheckRun":
        return node.get("status") == "COMPLETED" and node.get("conclusion") in PASSED_RUNS
    return node.get("state") == "SUCCESS"


def judge(nodes: list[dict]) -> tuple[str, tuple[str, ...]]:
    """The state of the required contexts among `nodes` and the sorted names of the failed ones."""
    required = [node for node in nodes if node.get("isRequired") is True]
    failing = tuple(sorted(_name(node) for node in required if _failed(node)))
    if failing:
        return "red", failing
    if required and all(_passed(node) for node in required):
        return "green", ()
    return "pending", ()


class GitHubBumpForge:
    def __init__(self, gh_json: Callable[..., Any] = approve.gh_json, run_gh: Callable[..., Any] = forge_api.run_gh):
        self._gh_json = gh_json
        self._run_gh = run_gh

    def open_bumps(self, slug: str, base: str, cancel: threading.Event | None = None) -> list[OpenBump]:
        pages = self._gh_json(
            ["api", "--paginate", "--slurp", f"repos/{slug}/pulls?state=open&base={base}&per_page=100"], cancel)
        if not isinstance(pages, list) or not all(
                isinstance(page, list) and all(isinstance(pull, dict) for pull in page) for page in pages):
            raise _invalid("the pull request listing is not a list of pages of objects")
        found = []
        for page in pages:
            for pull in page:
                head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
                repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
                revision = revision_of_branch(head.get("ref"))
                number = pull.get("number")
                if (revision is not None and repo.get("full_name") == slug and isinstance(number, int)
                        and not isinstance(number, bool) and number > 0):
                    found.append(OpenBump(number, revision))
        return found

    def _read(self, slug: str, number: int, cancel) -> dict:
        owner, _, name = slug.partition("/")
        answer = self._gh_json(["api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}",
                                "-f", f"name={name}", "-F", f"number={number}"], cancel)
        data = answer.get("data") if isinstance(answer, dict) else None
        repository = data.get("repository") if isinstance(data, dict) else None
        found = repository.get("pullRequest") if isinstance(repository, dict) else None
        if not isinstance(found, dict):
            raise _invalid("the pull request is not in the answer")
        head = found.get("headRefOid")
        if not isinstance(head, str) or approve.COMMIT.fullmatch(head) is None:
            raise _invalid("the pull request head is not a full commit")
        nodes = self._nodes(found)
        return {"state": found.get("state"), "merge": found.get("mergeStateStatus"), "head": head, "nodes": nodes}

    @staticmethod
    def _nodes(found: dict) -> list[dict]:
        commits = found.get("commits")
        last = commits.get("nodes") if isinstance(commits, dict) else None
        commit = last[-1].get("commit") if isinstance(last, list) and last and isinstance(last[-1], dict) else None
        rollup = commit.get("statusCheckRollup") if isinstance(commit, dict) else None
        if rollup is None:
            return []
        contexts = rollup.get("contexts") if isinstance(rollup, dict) else None
        page = contexts.get("pageInfo") if isinstance(contexts, dict) else None
        nodes = contexts.get("nodes") if isinstance(contexts, dict) else None
        if not isinstance(page, dict) or not isinstance(nodes, list):
            raise _invalid("the check contexts are unreadable")
        if page.get("hasNextPage") is not False:
            raise _invalid("the check contexts do not fit one page")
        return [node for node in nodes if isinstance(node, dict)]

    def checks(self, slug: str, number: int, cancel: threading.Event | None = None) -> Checks:
        read = self._read(slug, number, cancel)
        if read["state"] == "MERGED":
            return Checks("merged", read["head"], ())
        if read["state"] == "CLOSED":
            return Checks("closed", read["head"], ())
        state, failing = judge(read["nodes"])
        if state == "green" and read["merge"] not in MERGEABLE:
            state = "pending"
        return Checks(state, read["head"], failing)

    def verdict(self, slug: str, number: int, cancel: threading.Event | None = None) -> Checks:
        read = self._read(slug, number, cancel)
        state, failing = judge(read["nodes"])
        return Checks(state, read["head"], failing)

    def open_pull(self, slug: str, branch: str, base: str, title: str, body: str,
                  cancel: threading.Event | None = None) -> int:
        if BRANCH.fullmatch(branch) is None:
            raise ValueError("a bump pull request opens from a lock bump branch")
        return approve.GitHubForge(self._gh_json).open_pull_request(slug, branch, base, title, body, cancel)["number"]

    def merge(self, slug: str, number: int, head: str, cancel: threading.Event | None = None) -> None:
        approve.GitHubForge(self._gh_json).merge_pull_request(slug, number, head, cancel)

    def close(self, slug: str, number: int, branch: str, cancel: threading.Event | None = None) -> None:
        if BRANCH.fullmatch(branch) is None:
            raise ValueError("only a lock bump branch is deleted")
        self._gh_json(["api", "-X", "PATCH", f"repos/{slug}/pulls/{number}", "-f", "state=closed"], cancel)
        self._run_gh(["api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{branch}"], allow=(404, 422))

    def compare(self, repo: str, base: str, head: str, cancel: threading.Event | None = None) -> str:
        answer = self._gh_json(["api", f"repos/{repo}/compare/{base}...{head}"], cancel)
        status = answer.get("status") if isinstance(answer, dict) else None
        if status not in COMPARED:
            raise _invalid("the comparison has no known status")
        return status
