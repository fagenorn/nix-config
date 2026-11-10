"""The open pull requests of a repository, for `issue_branch` (issue 748).

`open_pull_heads(slug)` reads the open pull requests whose head branch lives in the pull
request's own base repository, GET only and never a write. Every field a reading consumes is
validated, and any deviation raises `forge_markers.ForgeError("payload_invalid", ...)`: a
malformed payload is never a silent skip. The ledger-backed branch-mapping rule and the
reconcile command that once shared this reader went with the workflow ledger (issue 689).
"""
from __future__ import annotations

from agent_tools import forge_markers


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
