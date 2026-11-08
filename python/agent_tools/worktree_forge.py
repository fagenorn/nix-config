"""The forge's view of a root's branches, for the C7 worktree-mapping rule (issue 710).

`forge_facts(root)` reads three things for the GitHub repository named by the root's `origin`,
GET only and never a write: the live claims of the open issues labelled `CLAIM_LABEL` (D5, the
winning claim marker of a trusted author names a branch), the open pull requests whose head
branch lives in the PR's own base repository (D6, a fork's PR maps nothing) and the branches of
`DECLARED_BRANCHES` whose declaring issue is still open (D7). A root without a GitHub `origin`
reads no forge and gets empty `ForgeFacts`.

`open_pull_heads(slug)` is the one open-PR reader: C7's `open_pr` reason and
`worktree_reconcile`'s `open_pr` keep reason both call it (D13), so they cannot disagree about
which branches have an open pull request.

Every field a reading consumes is validated, and any deviation raises
`forge_markers.ForgeError("payload_invalid", ...)`: a malformed payload is never a silent skip.
"""
from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from agent_tools import forge_markers, verify_issues
from agent_tools.github_remote import github_slug
from agent_tools.worktree_mapping import ForgeFacts, MappingError

GIT_TIMEOUT = 120
CLAIM_LABEL = "in-progress"
DECLARED_BRANCHES: Mapping[str, Mapping[str, int]] = {
    "fagenorn/nix-config": {"cutover-130-candidate": 130}}


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def root_slug(root: Path) -> str | None:
    """`owner/name` of the root's GitHub `origin`, else None (no origin, or another host)."""
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), "remote", "get-url", "origin"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=GIT_TIMEOUT,
            check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MappingError(f"{root}: git remote get-url failed: {error}") from None
    if done.returncode != 0:
        return None
    return github_slug(done.stdout)


def _base_full_name(number: int, base: object) -> str:
    if not isinstance(base, dict):
        raise _invalid(f"pull request {number} base is not an object")
    repo = base.get("repo")
    if not isinstance(repo, dict):
        raise _invalid(f"pull request {number} base repo is not an object")
    full_name = repo.get("full_name")
    if not isinstance(full_name, str):
        raise _invalid(f"pull request {number} base repo full_name is not a string")
    return full_name


def open_pull_heads(slug: str) -> dict[str, dict]:
    """The open pull requests headed in their own base repository, as `{branch: {number, updated_at}}`.

    Every page is read. A pull request is same-repository when its head repo's `full_name` equals
    its base repo's: the pull request's own payload decides, never the local origin's name, which
    a renamed or transferred repository leaves stale (GitHub redirects the old name). A pull
    request from a fork (or a deleted fork, an explicit `null` head repo; an omitted one is malformed) maps nothing; when several open
    pull requests share a branch the lowest number is kept.
    """
    heads: dict[str, dict] = {}
    for page in forge_markers.api_pages(f"repos/{slug}/pulls?state=open&per_page=100"):
        if not isinstance(page, list):
            raise _invalid("pull request page is not an array")
        for pr in page:
            if not isinstance(pr, dict):
                raise _invalid("pull request is not an object")
            number, updated, head = pr.get("number"), pr.get("updated_at"), pr.get("head")
            if not _is_int(number):
                raise _invalid("pull request number is not an integer")
            if not isinstance(updated, str):
                raise _invalid(f"pull request {number} updated_at is not a string")
            if not isinstance(head, dict):
                raise _invalid(f"pull request {number} head is not an object")
            ref, repo = head.get("ref"), head.get("repo")
            if not isinstance(ref, str):
                raise _invalid(f"pull request {number} head ref is not a string")
            if "repo" not in head:
                raise _invalid(f"pull request {number} head repo is missing")
            base_name = _base_full_name(number, pr.get("base"))
            if repo is None:
                continue
            if not isinstance(repo, dict):
                raise _invalid(f"pull request {number} head repo is not an object")
            full_name = repo.get("full_name")
            if not isinstance(full_name, str):
                raise _invalid(f"pull request {number} head repo full_name is not a string")
            if full_name.lower() != base_name.lower():
                continue
            if ref not in heads or number < heads[ref]["number"]:
                heads[ref] = {"number": number, "updated_at": updated}
    return heads


def _claims(slug: str) -> dict[str, list[dict]]:
    issues = forge_markers.open_issues(slug, CLAIM_LABEL)
    numbers = []
    for issue in issues:
        if not _is_int(issue.get("number")):
            raise _invalid("issue number is not an integer")
        numbers.append(issue["number"])
    claims: dict[str, list[dict]] = {}
    for number in sorted(numbers):
        markers = forge_markers.list_markers(slug, number, associations=verify_issues.TRUSTED)
        held = forge_markers.contest(markers, "claim", {"issue": str(number)})
        branch = held[0].fields.get("branch") if held else None
        if branch:
            claims.setdefault(branch, []).append(
                {"issue": number, "comment_id": held[0].comment_id,
                 "holder": held[0].fields.get("holder")})
    return claims


def _declared(slug: str) -> dict[str, int]:
    declared: dict[str, int] = {}
    for branch, issue in DECLARED_BRANCHES.get(slug, {}).items():
        doc = forge_markers.api_get(f"repos/{slug}/issues/{issue}")
        if not isinstance(doc, dict) or not isinstance(doc.get("state"), str):
            raise _invalid(f"issue {issue} is not an issue document")
        if doc["state"] == "open" and "pull_request" not in doc:
            declared[branch] = issue
    return declared


def forge_facts(root: Path) -> ForgeFacts:
    """What the forge says about the branches of `root`'s repository; read-only.

    Raises `forge_markers.ForgeError` on any forge failure or malformed payload.
    """
    slug = root_slug(root)
    if slug is None:
        return ForgeFacts()
    claims = _claims(slug)
    open_prs = {branch: row["number"] for branch, row in open_pull_heads(slug).items()}
    return ForgeFacts(claims=claims, open_prs=open_prs, declared=_declared(slug))
