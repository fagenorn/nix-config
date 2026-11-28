"""`lock_bump_forge`: a lock bump's GitHub reads and writes, each one `gh` call.

`open_bumps` lists open pull requests into a base and keeps those whose head is a `lock-bump-<revision>`
branch of the repository itself. `checks` and `verdict` send one GraphQL call per page of contexts, up to
`MAX_PAGES`, following the cursor; `judge` reads only the contexts the branch protection requires: red
when any failed, green when at least one exists, all succeeded and every context the protection rule names
reported, else pending. `checks` also needs the forge's merge state to be CLEAN, HAS_HOOKS or UNSTABLE
before it says green and says merged or closed for a pull in those states; `verdict` judges any pull by
its required contexts alone. An unreadable or repeated cursor, a head that moves between pages, a missing
pull request and a head that is not a full commit are `ForgeError("payload_invalid")`. `pinned` returns
the revision the lock pins at a commit. `open_pull` and `merge` are the adoption's forge calls,
and a merge is pinned to the head that was read, so branch protection always applies. `close` closes the
pull request and deletes its branch. `compare` returns the forge's status of a revision against another.
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable, Collection
from typing import Any, NamedTuple

from agent_tools.console import approve
from agent_tools.project_contract.adopt_conformance import LOCK_FILE
from agent_tools.project_contract.lock_bump_tree import BRANCH, BumpRefused, pinned_revision, revision_of_branch
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

QUERY = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      state headRefOid mergeStateStatus
      baseRef { branchProtectionRule { requiredStatusChecks { context } } }
      commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
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
MAX_PAGES = 50


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


def judge(nodes: list[dict], protected: Collection[str] = ()) -> tuple[str, tuple[str, ...]]:
    """The state of the required contexts among `nodes` and the sorted names of the failed ones.

    A context the branch protection names that no node reports is never green."""
    required = [node for node in nodes if node.get("isRequired") is True or _name(node) in protected]
    failing = tuple(sorted(_name(node) for node in required if _failed(node)))
    if failing:
        return "red", failing
    missing = set(protected) - {_name(node) for node in nodes}
    if required and not missing and all(_passed(node) for node in required):
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
        """The pull request's state and every page of its contexts, each read of one head."""
        owner, _, name = slug.partition("/")
        nodes: list[dict] = []
        cursor, first = None, None
        for _ in range(MAX_PAGES):
            argv = ["api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"name={name}",
                    "-F", f"number={number}"]
            answer = self._gh_json(argv + (["-f", f"after={cursor}"] if cursor else []), cancel)
            data = answer.get("data") if isinstance(answer, dict) else None
            repository = data.get("repository") if isinstance(data, dict) else None
            found = repository.get("pullRequest") if isinstance(repository, dict) else None
            if not isinstance(found, dict):
                raise _invalid("the pull request is not in the answer")
            head = found.get("headRefOid")
            if not isinstance(head, str) or approve.COMMIT.fullmatch(head) is None:
                raise _invalid("the pull request head is not a full commit")
            if first is None:
                first = {"state": found.get("state"), "merge": found.get("mergeStateStatus"), "head": head,
                         "protected": self._protected(found)}
            elif head != first["head"]:
                raise _invalid("the pull request head moved while its contexts were read")
            page, after = self._nodes(found, cursor)
            nodes += page
            if after is None:
                return {**first, "nodes": nodes}
            cursor = after
        raise _invalid("the check contexts do not fit the pages read")

    @staticmethod
    def _protected(found: dict) -> frozenset[str]:
        base = found.get("baseRef")
        rule = base.get("branchProtectionRule") if isinstance(base, dict) else None
        listed = rule.get("requiredStatusChecks") if isinstance(rule, dict) else None
        return frozenset(entry["context"] for entry in listed or []
                         if isinstance(entry, dict) and isinstance(entry.get("context"), str))

    @staticmethod
    def _nodes(found: dict, cursor: str | None) -> tuple[list[dict], str | None]:
        """The context nodes of one page and the cursor of the next page, None on the last."""
        commits = found.get("commits")
        last = commits.get("nodes") if isinstance(commits, dict) else None
        commit = last[-1].get("commit") if isinstance(last, list) and last and isinstance(last[-1], dict) else None
        rollup = commit.get("statusCheckRollup") if isinstance(commit, dict) else None
        if rollup is None:
            return [], None
        contexts = rollup.get("contexts") if isinstance(rollup, dict) else None
        page = contexts.get("pageInfo") if isinstance(contexts, dict) else None
        nodes = contexts.get("nodes") if isinstance(contexts, dict) else None
        if not isinstance(page, dict) or not isinstance(nodes, list):
            raise _invalid("the check contexts are unreadable")
        kept = [node for node in nodes if isinstance(node, dict)]
        if page.get("hasNextPage") is False:
            return kept, None
        after = page.get("endCursor")
        if page.get("hasNextPage") is not True or not isinstance(after, str) or not after or after == cursor:
            raise _invalid("the check contexts' next page is unreadable")
        return kept, after

    def checks(self, slug: str, number: int, cancel: threading.Event | None = None) -> Checks:
        read = self._read(slug, number, cancel)
        if read["state"] == "MERGED":
            return Checks("merged", read["head"], ())
        if read["state"] == "CLOSED":
            return Checks("closed", read["head"], ())
        state, failing = judge(read["nodes"], read["protected"])
        if state == "green" and read["merge"] not in MERGEABLE:
            state = "pending"
        return Checks(state, read["head"], failing)

    def verdict(self, slug: str, number: int, cancel: threading.Event | None = None) -> Checks:
        read = self._read(slug, number, cancel)
        state, failing = judge(read["nodes"], read["protected"])
        return Checks(state, read["head"], failing)

    def pinned(self, repo: str, sha: str, cancel: threading.Event | None = None) -> str | None:
        """The revision the lock of `repo` pins at commit `sha`, None when that lock cannot be bumped."""
        answer = self._gh_json(["api", f"repos/{repo}/contents/{LOCK_FILE}?ref={sha}"], cancel)
        content = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(answer, dict) or answer.get("encoding") != "base64" or not isinstance(content, str):
            raise _invalid("the lock at the commit is not readable")
        try:
            return pinned_revision(base64.b64decode(content))
        except (ValueError, BumpRefused):
            return None

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
