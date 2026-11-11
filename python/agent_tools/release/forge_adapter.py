"""The GitHub forge adapter (#124 D8, D19): `describe`, `inspect` and `invoke`.

These three functions are the adapter's whole public surface, one per half of the adapter
contract (D7): the static descriptor, the read half and the write half.

`describe()` declares which operations the adapter carries, which it refuses, and what a
profile may bind. `pr_merge` is `supported` for `invoke` since issue 554 D4: a `materialize`,
`pointer_cas` operation that binds the candidate's `merge` member, behind a protection floor.
`tag` and `release` are the two publication operations, both `index` mode, both irreversible
and create-if-absent. The descriptor is built fresh on every call, so a caller may mutate what
it receives.

This module imports only the standard library: the registry in `release_adapter` imports
this module, never the reverse (D7).

`inspect(request)` is the read half (D11, D17, D25, spec section 7). It issues only
`gh api` and `gh pr view` reads, by name, with `GITHUB_TOKEN` and `GH_TOKEN` removed from
the child environment so the keyring credential answers. It never mutates, never reads a
Release's `target_commitish`, never calls the guard, and runs every read of one call under
a single `COLLECTION_BUDGET_SECONDS` deadline. Whatever it cannot read it reports as
`unknown`, never raises. It imports no `host_admission` or `launch_*` module (AC9).

`invoke(request)` is the write half (D8, D9, D11, D22, D23, spec section 7). It follows the
spec's ordered steps and stops at the first refusal: request shape, working checkout, same
repository, containment (`tag`), the local annotated tag (`tag`), the rendered command, the
`claude-bash-lifecycle-guard` verdict, and then one mutation. It makes at most one provider
mutation, never retries, never reads the target (`tag.ref`, `tag.object`, `release.view`) and
returns only `accepted`, `rejected` or `unknown`: that a mutation landed is the core's to
observe afterwards (#85, #206). Every child runs with the token variables removed.

`pr_merge` replaces the containment and tag steps with four precondition reads, each a refusal
before the guard and the merge (issue 554 D4, D6, D13): the protection floor, the head
branch's auto-delete setting, the pull request (open, on the target branch, at the candidate
commit) and the base tip bound by `merge`. Any non-zero exit of its one `gh pr merge` is
`unknown`, because the core inspects the pull request afterwards.

With a merge binding, `tag` and `release` judge and tag the release PR's merge commit rather
than `candidate.commit` (issue 554 D8).

Operations. `pr_merge` is `materialize`, `pointer_cas`, with `candidate_members` `["merge"]`
(issue 554 D4); `tag` and `release` are `index` mode, irreversible and create-if-absent.
`inspect` reads a tag from its own ref and object, never from a Release's `target_commitish`.

`invoke` steps. Request shape: an unsupported operation is `unsupported_operation` and bad
parameters are `invalid_input`, with no child process. Working checkout: `git rev-parse
--show-toplevel` (D23). Same repository: `origin` and its one push URL must each be a
`github.com` URL in the `git@github.com:`, `https://github.com/` or `ssh://git@github.com/`
spelling, and they and `gh api repos/<slug> --jq .full_name` must all name
`target.repository`. Containment of the commit in the target branch (`tag`). The local
annotated tag is reused at the same commit, created when absent and refused otherwise (D25).
Then the rendered command and the guard. A failed read before the mutation is `rejected` with
`transient_transport` or `provider_unavailable`, because nothing was mutated.

There are three mutation spellings: `git push origin refs/tags/<tag>`, `gh release create
<tag> --repo <slug> --verify-tag --title "<title>" --notes-file <file>` and `gh pr merge <pr>
--repo <slug> --merge --match-head-commit <commit>`. `--verify-tag` refuses to create a tag,
and the notes file is a mode-0600 temporary removed afterwards. Before the one mutation the
command text is passed to `claude-bash-lifecycle-guard`, by name on `PATH`, as a `{tool_name,
tool_input.command, cwd}` Bash payload; a non-zero exit, timeout or missing guard is
`authorization_denied` (D9). For `tag` and `release`, `already exists` (git) or `HTTP 422` (gh)
is `precondition_failed`. A mutation binary that cannot be spawned is `rejected` with
`provider_unavailable`, because no child ran and nothing was applied (D23); a timeout or any
other non-zero exit is `unknown` with `transient_transport`, which the core resolves by
inspection (D9, D11).

`pr_merge` binds the candidate's `merge` member, `{pr, base_tip}`, beside `version` and
`commit`; its expected head is `candidate.commit`, so `candidate` is exactly `{version, commit,
merge}` for it, while `tag` and `release` take `{version, commit}` or the same with `merge`.
After the same-repository step it makes four precondition reads, and a miss in any of them is
`rejected` with `precondition_failed` before the guard and the merge (issue 554 D6, D13):

1. the protection floor on `target.branch`, which needs a 200 answer with `strict` true,
   non-empty required contexts and enforced admins, else `protection_floor_unmet: <member>`
   naming the first of `unprotected`, `inaccessible`, `strict`, `required_contexts` and
   `enforce_admins`;
2. the repository's `delete_branch_on_merge`, which must print `false`, else
   `head_auto_delete_on`;
3. the pull request, which must be `OPEN` on `target.branch` at `candidate.commit`, else
   `pr_not_open: <STATE>`, `pr_base_mismatch: <base>` or `pr_head_mismatch: <oid>`;
4. the base tip, which must equal `merge.base_tip`, else `base_moved: <tip>`.

A read that fails is `rejected` with `transient_transport` on a timeout and
`provider_unavailable` otherwise. The merge spelling never renders `--admin`, `--auto`,
`--delete-branch`, `--squash`, `--rebase` or a subject (issue 554 D5, D17). Exit 0 is
`accepted` with the pull request URL as its reference; a timeout or any non-zero exit is
`unknown` with `transient_transport`, whatever stderr says (issue 554 D6). Its `inspect` adds
`strict` to `facts.protection` and is `satisfied` only when the merge commit's parents are
exactly `[merge.base_tip, candidate.commit]` (issue 554 D7).

With `candidate.merge`, `tag` and `release` judge an existing tag against the release PR's
merge commit, whose parents must be exactly `[base_tip, commit]`, else `tag_target_mismatch`;
`tag` invoke refuses `release PR not merged as bound`, then checks that merge commit's
containment, fetches `refs/heads/<branch>` and tags it (issue 554 D8, D17).

Post-release sync (issue 845, ADR-release-010). `sync_branch` and `sync_pr` bring the release
merge commit back to the integration branch of a two-branch release. They are requests of
`inspect` and `invoke` that no profile node can bind: `describe()` does not list them, so its
digest, which pins every profile, is what it was, and `release_sync` is their one caller. Both
take `{target, candidate, integration}`, `candidate` carrying `merge` and `integration` a
branch other than `target.branch`. The sync branch is `SYNC_BRANCH`,
`sync-<default>-into-<integration>-after-<version>`.

Both inspections first resolve the released commit as `tag` does (`release_not_merged`,
`diverged`, when the release PR has not merged as bound) and read `repos/<slug>/compare/<merge
commit>...<integration>`: `identical` or `ahead` is `satisfied` with `already_contained`, the
no-op, and nothing else is read. Otherwise `sync_branch` reads the sync branch's ref: 404 is
`absent` (`branch_absent`), a tip at the merge commit or one whose compare against it is
`identical` or `ahead` is `satisfied`, any other is `diverged` (`branch_elsewhere`). `sync_pr`
reads `repos/<slug>/pulls?state=all&base=<integration>&head=<owner>:<branch>&per_page=100`:
exactly one pull request that is open or merged is `satisfied`, with its number as
`observed_subject.pr` and its URL as the first reference; none is `absent` (`pr_absent`) and more
than one `diverged` (`pr_ambiguous`). Every sync observation carries `facts.commands`, the
commands that would finish the sync from that operation on, as plain text for a report.

`sync_branch` invoke resolves the released commit, fetches `refs/heads/<default>`, reuses a local
sync branch at that commit, creates it with `git branch --no-track` when absent and refuses any
other, then pushes it with `git push origin <sync branch>`. `sync_pr` invoke refuses
`sync_branch_absent` unless the remote sync branch exists, then runs `gh pr create --repo <slug>
--base <integration> --head <sync branch> --title "chore: merge <default> into <integration>
after <version>" --body "<version>"`; its accepted reference is the URL `gh` printed. Both
mutations pass the guard like every other, a failed one is `unknown`, and nothing here merges
the pull request.

`tests/fixtures/forge-adapter-spellings.json` is the one list of provider spellings:
`tests/forge_world.py` builds its fake `gh`, `git` and `claude-bash-lifecycle-guard` from it,
and `tests/test_forge_adapter.py` pins the adapter to it, so the world and the adapter cannot
disagree about a spelling (D12, D22). Its `sync` member holds the sync rows; the guard suite
runs both sync mutations against the real guard, per repository class.
"""

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from typing import Any, Callable

from agent_tools.system.github_remote import github_slug

CHILD_TIMEOUT_SECONDS = 30
COLLECTION_BUDGET_SECONDS = 30
DETAIL_LIMIT = 240
TOKEN_VARIABLES = ("GITHUB_TOKEN", "GH_TOKEN")
HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")
TAG_CHAIN_LIMIT = 8
TARGET_MEMBERS = frozenset(("kind", "repository", "branch", "handle"))
TOLERATED = frozenset(("action", "operation", "config"))
SYNC_OPERATIONS = ("sync_branch", "sync_pr")
SYNC_BRANCH = "sync-{default}-into-{integration}-after-{version}"
SYNC_TITLE = "chore: merge {default} into {integration} after {version}"
REQUIRED = {"tag": ("target", "candidate"),
            "release": ("target", "candidate", "title", "notes"),
            "pr_merge": ("target", "candidate"),
            "sync_branch": ("target", "candidate", "integration"),
            "sync_pr": ("target", "candidate", "integration")}
IDENTITY_MEMBERS = frozenset(("version", "commit"))
MERGE_MEMBERS = frozenset(("pr", "base_tip"))
PR_FIELDS = "state,baseRefName,headRefName,headRefOid,mergeCommit,url,statusCheckRollup"


def _publication_operation(candidate_members: list[str]) -> dict[str, Any]:
    return {"mode": "index", "support": "supported", "inspect": "supported", "reason": None,
            "mutability": "create_if_absent", "config_schema_version": 1,
            "config_schema": {"members": {}, "required": []},
            "effects": ["irreversible"], "recovery_capable": False,
            "candidate_members": candidate_members}


def describe() -> dict[str, Any]:
    """The forge descriptor (#124 D8, D19), a fresh plain dict."""
    return {
        "name": "github-forge",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "pr_merge": {"mode": "materialize", "support": "supported", "inspect": "supported",
                         "reason": None, "mutability": "pointer_cas",
                         "config_schema_version": 1,
                         "config_schema": {"members": {}, "required": []},
                         "effects": ["irreversible"], "recovery_capable": False,
                         "candidate_members": ["merge"]},
            "tag": _publication_operation([]),
            "release": _publication_operation(["notes", "title"]),
        },
        "predicates": {
            "publication_visible": {"support": "supported", "reason": None},
            "running_subject_identity": {"support": "unsupported", "reason": "no_activation_mode"},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"github_repository": ["branch", "repository"]},
        "credential_classes": ["gh_keyring"],
        "executables": ["claude-bash-lifecycle-guard", "gh", "git"],
        "host_capacity": "not_required",
    }



class _Unknown(Exception):
    """A read that cannot be judged: the observation is `unknown` with this reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail[:DETAIL_LIMIT]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _observation(outcome: str, reason: str, subject: dict[str, Any], references: list[str],
                 facts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "reason": reason, "observed_subject": subject,
            "references": references, "observed_at": _now_ms(), "facts": facts or {}}


def _unknown(reason: str, detail: str = "", subject: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    return _observation("unknown", reason, subject or {}, [],
                        {"detail": detail[:DETAIL_LIMIT]} if detail else {})


def _gh(argv: list[str], deadline: float) -> tuple[Any, Any, str]:
    """Run `gh <argv>` within what is left of `deadline`: `(status, payload, detail)`.

    `status` is `"ok"` with the parsed JSON payload, or the HTTP status (404, 403) of a
    failed call, or one of `lookup_failed`, `lookup_timeout`, `payload_invalid` and
    `executable_missing`, with a payload of `None`. `detail` is bounded stderr.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "lookup_timeout", None, ""
    env = {name: value for name, value in os.environ.items() if name not in TOKEN_VARIABLES}
    try:
        done = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=remaining,
                              env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "lookup_timeout", None, ""
    except OSError as error:
        return "executable_missing", None, str(error)
    detail = done.stderr.strip()[:DETAIL_LIMIT]
    if done.returncode != 0:
        match = HTTP_STATUS.search(done.stderr)
        status = int(match.group(1)) if match else 0
        return (status if status in (403, 404) else "lookup_failed"), None, detail
    try:
        return "ok", json.loads(done.stdout), detail
    except ValueError:
        return "payload_invalid", None, detail


def _read(argv: list[str], deadline: float, allow: tuple[int, ...] = ()) -> tuple[Any, Any]:
    """`(status, payload)` of one read; any status but `ok` and `allow` ends the inspection."""
    status, payload, detail = _gh(argv, deadline)
    if status != "ok" and status not in allow:
        raise _Unknown(status if isinstance(status, str) else "lookup_failed", detail)
    return status, payload


def _field(value: Any, *path: str, kind: type = str) -> Any:
    for step in path:
        if not isinstance(value, dict) or step not in value:
            raise _Unknown("payload_invalid", f"missing {'.'.join(path)}")
        value = value[step]
    if type(value) is not kind:
        raise _Unknown("payload_invalid", f"{'.'.join(path)} is not a {kind.__name__}")
    return value


def _sha(value: str, where: str) -> str:
    if SHA.fullmatch(value) is None:
        raise _Unknown("payload_invalid", f"{where} is not a 40-character commit id")
    return value


def _tag_state(slug: str, tag: str, released: Callable[[], str | None], deadline: float
               ) -> tuple[str, str, str | None, list[str]]:
    """`(outcome, reason, peeled commit, references)` of the tag, read from its own objects.

    A tag object whose target is another tag object is peeled in turn, as local
    `refs/tags/<tag>^{commit}` peels it, up to `TAG_CHAIN_LIMIT` objects. `released` names the
    commit the tag must peel to and is called only once an annotated tag has peeled, so a
    missing or lightweight tag costs no pull request read; `None` matches no tag.
    """
    ref_path = f"repos/{slug}/git/ref/tags/{tag}"
    references = [ref_path]
    status, ref = _read(["api", ref_path], deadline, allow=(404,))
    if status == 404:
        return "absent", "tag_absent", None, references
    sha = _sha(_field(ref, "object", "sha"), "tag ref object")
    kind = _field(ref, "object", "type")
    if kind == "commit":
        return "diverged", "tag_not_annotated", sha, references
    if kind != "tag":
        raise _Unknown("payload_invalid", f"tag ref object type {kind!r}")
    for _ in range(TAG_CHAIN_LIMIT):
        object_path = f"repos/{slug}/git/tags/{sha}"
        references.append(object_path)
        _, annotated = _read(["api", object_path], deadline)
        sha = _sha(_field(annotated, "object", "sha"), "tag object target")
        if _field(annotated, "object", "type") != "tag":
            break
    else:
        raise _Unknown("payload_invalid", f"tag chain deeper than {TAG_CHAIN_LIMIT} objects")
    peeled = sha
    if peeled == released():
        return "satisfied", "observed", peeled, references
    return "diverged", "tag_target_mismatch", peeled, references


def _released(parameters: dict[str, Any], read: Callable[[list[str]], Any]) -> str | None:
    """The commit `tag` and `release` publish, or None when the release PR has not landed as bound.

    Without `candidate.merge` it is `candidate.commit` and nothing is read. With it, it is the
    pull request's merge commit, and only when `_merge_outcome` is `satisfied`, so the judgment
    here and `pr_merge`'s inspect cannot disagree (issue 554 D8). `read` takes a `gh` argv
    without `gh` and returns the parsed JSON.
    """
    candidate = parameters["candidate"]
    if "merge" not in candidate:
        return candidate["commit"]
    slug = parameters["target"]["repository"]
    view = read(["pr", "view", str(candidate["merge"]["pr"]), "--repo", slug, "--json", PR_FIELDS])
    state, base = _field(view, "state"), _field(view, "baseRefName")
    oid, parents = None, None
    if state == "MERGED":
        oid = _sha(_field(view, "mergeCommit", "oid"), "mergeCommit.oid")
        parents = _parents(read(["api", f"repos/{slug}/git/commits/{oid}"]))
    try:
        outcome, _ = _merge_outcome(state, base, parents, parameters)
    except ValueError as error:
        raise _Unknown("payload_invalid", str(error))
    return oid if outcome == "satisfied" else None


def _inspect_released(parameters: dict[str, Any], deadline: float
                      ) -> Callable[[], str | None]:
    return lambda: _released(parameters, lambda argv: _read(argv, deadline)[1])


def _inspect_tag(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    subject = {"tag": tag, "commit": None}
    try:
        outcome, reason, peeled, references = _tag_state(
            slug, tag, _inspect_released(parameters, deadline), deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    return _observation(outcome, reason, {"tag": tag, "commit": peeled}, references)


def _inspect_release(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    subject = {"tag": tag, "commit": None}
    path = f"repos/{slug}/releases/tags/{tag}"
    try:
        status, release = _read(["api", path], deadline, allow=(404,))
        if status == 404:
            return _observation("absent", "release_absent", subject, [path])
        draft, name = _field(release, "draft", kind=bool), _field(release, "tag_name")
        url = release.get("html_url")
        references = [path] if not isinstance(url, str) else [url, path]
        if draft:
            return _observation("diverged", "release_draft", subject, references)
        if name != tag:
            return _observation("diverged", "release_tag_mismatch", subject, references)
        outcome, reason, peeled, tag_references = _tag_state(
            slug, tag, _inspect_released(parameters, deadline), deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    return _observation(outcome, reason, {"tag": tag, "commit": peeled},
                        references + tag_references)


def _protection_facts(status: Any, payload: Any) -> dict[str, Any]:
    """The protection facts of one branch-protection answer (issue 554 D4).

    `status` is `"ok"` with the parsed payload, or the HTTP status 404 (`unprotected`) or 403
    (`inaccessible`). Inspect's `protection` fact and invoke's floor read both come from here.
    """
    if status == 404 or status == 403:
        return {"status": "unprotected" if status == 404 else "inaccessible", "strict": False,
                "required_contexts": [], "enforce_admins": False}
    if status != "ok":
        raise ValueError(f"no protection facts for status {status!r}")
    checks = payload.get("required_status_checks") if isinstance(payload, dict) else None
    contexts = checks.get("contexts") if isinstance(checks, dict) else None
    admins = payload.get("enforce_admins") if isinstance(payload, dict) else None
    return {"status": "protected",
            "strict": isinstance(checks, dict) and checks.get("strict") is True,
            "required_contexts": sorted(contexts) if isinstance(contexts, list) else [],
            "enforce_admins": isinstance(admins, dict) and admins.get("enabled") is True}


def _floor_problem(facts: dict[str, Any]) -> str | None:
    """The first member of the `pr_merge` protection floor that `facts` leave unmet (D4)."""
    if facts["status"] != "protected":
        return facts["status"]
    for member in ("strict", "required_contexts", "enforce_admins"):
        if not facts[member]:
            return member
    return None


def _protection_path(slug: str, branch: str) -> str:
    return f"repos/{slug}/branches/{branch}/protection"


def _protection(slug: str, base: str, deadline: float) -> dict[str, Any]:
    status, payload, detail = _gh(["api", _protection_path(slug, base)], deadline)
    if status not in ("ok", 404, 403):
        raise _Unknown(status, detail)
    return _protection_facts(status, payload)


def _merge_outcome(state: str, base: str, parents: list[str] | None,
                   parameters: dict[str, Any]) -> tuple[str, str]:
    """`(outcome, reason)` of a release pull request (issue 554 D7, spec section 4).

    It is the one home of the rule: inspect reports it and the released-commit resolution
    reads it, so the two cannot disagree.
    """
    candidate = parameters["candidate"]
    if base != parameters["target"]["branch"]:
        return "diverged", "base_mismatch"
    if state == "OPEN":
        return "absent", "pr_open"
    if state == "CLOSED":
        return "diverged", "pr_closed"
    if state != "MERGED":
        raise ValueError(f"unknown pull request state {state!r}")
    if parents == [candidate["merge"]["base_tip"], candidate["commit"]]:
        return "satisfied", "observed"
    return "diverged", "merge_parents_mismatch"


def _parents(commit: Any) -> list[str]:
    """The parent commit ids of one `git/commits` answer."""
    listed = commit.get("parents") if isinstance(commit, dict) else None
    if not isinstance(listed, list):
        raise _Unknown("payload_invalid", "parents is not a list")
    return [_sha(_field(parent, "sha"), "parent") for parent in listed]


def _inspect_pr_merge(parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    slug, number = parameters["target"]["repository"], parameters["candidate"]["merge"]["pr"]
    subject = {"pr": number, "merge_commit": None}
    try:
        _, view = _read(["pr", "view", str(number), "--repo", slug, "--json", PR_FIELDS], deadline)
        state = _field(view, "state")
        if state not in ("OPEN", "MERGED", "CLOSED"):
            raise _Unknown("payload_invalid", f"PR state {state!r}")
        base, head = _field(view, "baseRefName"), _field(view, "headRefName")
        head_oid = _sha(_field(view, "headRefOid"), "headRefOid")
        if BRANCH.fullmatch(base) is None or ".." in base:
            raise _Unknown("payload_invalid", "baseRefName is not a branch name")
        base_path = f"repos/{slug}/git/ref/heads/{base}"
        _, base_ref = _read(["api", base_path], deadline)
        base_tip = _sha(_field(base_ref, "object", "sha"), "base ref")
        references = [view["url"]] if isinstance(view.get("url"), str) else []
        references.append(base_path)
        parents = None
        if state == "MERGED":
            merge = view.get("mergeCommit")
            oid = _sha(_field(merge, "oid"), "mergeCommit.oid")
            subject["merge_commit"] = oid
            commit_path = f"repos/{slug}/git/commits/{oid}"
            references.append(commit_path)
            _, commit = _read(["api", commit_path], deadline)
            parents = _parents(commit)
        protection = _protection(slug, base, deadline)
    except _Unknown as error:
        return _unknown(error.reason, error.detail, subject)
    facts = {"state": state, "base": base, "head": head, "head_oid": head_oid,
             "base_tip": base_tip, "protection": protection}
    outcome, reason = _merge_outcome(state, base, parents, parameters)
    return _observation(outcome, reason, subject, references, facts)


def _sync_names(parameters: dict[str, Any]) -> dict[str, str]:
    """The names one sync works with: the slug, both branches, the version and the sync branch."""
    names = {"slug": parameters["target"]["repository"], "default": parameters["target"]["branch"],
             "integration": parameters["integration"], "version": parameters["candidate"]["version"]}
    return {**names, "branch": SYNC_BRANCH.format(**names), "title": SYNC_TITLE.format(**names)}


def _sync_create(names: dict[str, str]) -> tuple[list[str], str]:
    """The argv and the raw text of the one `gh pr create` that opens the sync pull request."""
    argv = ["gh", "pr", "create", "--repo", names["slug"], "--base", names["integration"],
            "--head", names["branch"], "--title", names["title"], "--body", names["version"]]
    raw = (f'gh pr create --repo {names["slug"]} --base {names["integration"]} '
           f'--head {names["branch"]} --title "{names["title"]}" --body "{names["version"]}"')
    return argv, raw


def _sync_commands(operation: str, names: dict[str, str], released: str | None) -> list[str]:
    """The commands that finish the sync from `operation` on, as text for a report."""
    branch = names["branch"]
    commands = [f"git branch --no-track {branch} {released or '<release merge commit>'}",
                f"git push origin {branch}", _sync_create(names)[1]]
    return commands if operation == "sync_branch" else commands[2:]


def _contains(slug: str, commit: str, branch: str, deadline: float) -> tuple[bool, str]:
    """Whether `branch` holds `commit`, and the compare path that says so."""
    path = f"repos/{slug}/compare/{commit}...{branch}"
    _, compare = _read(["api", path], deadline)
    return _field(compare, "status") in ("identical", "ahead"), path


def _sync_branch_state(names: dict[str, str], released: str, deadline: float
                       ) -> tuple[str, str, list[str]]:
    path = f"repos/{names['slug']}/git/ref/heads/{names['branch']}"
    status, ref = _read(["api", path], deadline, allow=(404,))
    if status == 404:
        return "absent", "branch_absent", [path]
    if _sha(_field(ref, "object", "sha"), "sync branch ref") == released:
        return "satisfied", "observed", [path]
    held, compare_path = _contains(names["slug"], released, names["branch"], deadline)
    return ("satisfied", "observed", [path, compare_path]) if held else (
        "diverged", "branch_elsewhere", [path, compare_path])


def _sync_pr_state(names: dict[str, str], deadline: float
                   ) -> tuple[str, str, list[str], int | None]:
    owner = names["slug"].split("/")[0]
    path = (f"repos/{names['slug']}/pulls?state=all&base={names['integration']}"
            f"&head={owner}:{names['branch']}&per_page=100")
    _, listed = _read(["api", path], deadline)
    if not isinstance(listed, list):
        raise _Unknown("payload_invalid", "the pull request listing is not a list")
    live = [entry for entry in listed if isinstance(entry, dict)
            and (entry.get("state") == "open" or entry.get("merged_at"))]
    if not live:
        return "absent", "pr_absent", [path], None
    if len(live) > 1:
        return "diverged", "pr_ambiguous", [path], None
    number = _field(live[0], "number", kind=int)
    url = live[0].get("html_url")
    return "satisfied", "observed", ([url, path] if isinstance(url, str) else [path]), number


def _inspect_sync(operation: str, parameters: dict[str, Any], deadline: float) -> dict[str, Any]:
    """The observation of `sync_branch` or `sync_pr` (issue 845)."""
    names = _sync_names(parameters)
    subject: dict[str, Any] = ({"branch": names["branch"], "commit": None}
                               if operation == "sync_branch" else {"pr": None})
    released = None

    def facts() -> dict[str, Any]:
        return {"commands": _sync_commands(operation, names, released)}

    try:
        released = _inspect_released(parameters, deadline)()
        if released is None:
            return _observation("diverged", "release_not_merged", subject, [], facts())
        if "commit" in subject:
            subject["commit"] = released
        held, path = _contains(names["slug"], released, names["integration"], deadline)
        if held:
            return _observation("satisfied", "already_contained", subject, [path], facts())
        if operation == "sync_branch":
            outcome, reason, references = _sync_branch_state(names, released, deadline)
        else:
            outcome, reason, references, subject["pr"] = _sync_pr_state(names, deadline)
    except _Unknown as error:
        return _observation("unknown", error.reason, subject, [],
                            {**facts(), **({"detail": error.detail} if error.detail else {})})
    return _observation(outcome, reason, subject, references, facts())


def _target_problem(target: Any) -> str | None:
    if not isinstance(target, dict) or not set(target) <= TARGET_MEMBERS:
        return "target is not a github_repository object"
    if target.get("kind") != "github_repository":
        return "target kind is not github_repository"
    slug, branch = target.get("repository"), target.get("branch")
    if not isinstance(slug, str) or SLUG.fullmatch(slug) is None or ".." in slug:
        return "target repository is not an owner/name slug"
    if not isinstance(branch, str) or BRANCH.fullmatch(branch) is None or ".." in branch:
        return "target branch is not a branch name"
    return None


def _merge_problem(merge: Any) -> str | None:
    if not (isinstance(merge, dict) and set(merge) == MERGE_MEMBERS):
        return "merge is not {pr, base_tip}"
    if type(merge["pr"]) is not int or merge["pr"] < 1:
        return "merge pr is not a positive integer"
    if not isinstance(merge["base_tip"], str) or SHA.fullmatch(merge["base_tip"]) is None:
        return "merge base_tip is not a 40-character commit id"
    return None


def _candidate_problem(operation: str, candidate: Any) -> str | None:
    """Why `candidate` is not the shape `operation` takes (issue 554 D2, D4), or None.

    `pr_merge` and the sync operations take `{version, commit, merge}`; `tag` and `release`
    take `{version, commit}`, or the same with `merge` when their profile binds it.
    """
    with_merge = IDENTITY_MEMBERS | {"merge"}
    needs_merge = operation == "pr_merge" or operation in SYNC_OPERATIONS
    shapes = (with_merge,) if needs_merge else (IDENTITY_MEMBERS, with_merge)
    if not (isinstance(candidate, dict) and set(candidate) in shapes
            and isinstance(candidate["version"], str) and VERSION.fullmatch(candidate["version"])
            and isinstance(candidate["commit"], str) and SHA.fullmatch(candidate["commit"])):
        return ("candidate is not {version vMAJOR.MINOR.PATCH, commit 40-hex, merge}"
                if needs_merge
                else "candidate is not {version vMAJOR.MINOR.PATCH, commit 40-hex[, merge]}")
    return _merge_problem(candidate["merge"]) if "merge" in candidate else None


def _parameters_problem(operation: str, parameters: Any) -> str | None:
    """Why `parameters` are not the closed set for `operation`, or None."""
    required = REQUIRED[operation]
    if not isinstance(parameters, dict):
        return "parameters are not an object"
    missing = [name for name in required if name not in parameters]
    unknown = sorted(set(parameters) - set(required) - TOLERATED)
    if missing or unknown:
        return "parameters " + "; ".join(
            part for part in (f"miss {', '.join(missing)}" if missing else "",
                              f"have unknown {', '.join(unknown)}" if unknown else "") if part)
    problem = _target_problem(parameters["target"])
    if problem is not None:
        return problem
    problem = _candidate_problem(operation, parameters["candidate"])
    if problem is not None:
        return problem
    if operation == "release" and not (isinstance(parameters["title"], str)
                                       and isinstance(parameters["notes"], str)):
        return "title and notes are not strings"
    if operation in SYNC_OPERATIONS:
        integration = parameters["integration"]
        if (not isinstance(integration, str) or BRANCH.fullmatch(integration) is None
                or ".." in integration or integration == parameters["target"]["branch"]):
            return "integration is not a branch name other than the target branch"
    return None


def _effect(operation: str, parameters: Any, deadline: float) -> dict[str, Any]:
    if operation not in REQUIRED:
        return _unknown("parameters_invalid", f"unknown operation {operation!r}")
    problem = _parameters_problem(operation, parameters)
    if problem is not None:
        return _unknown("parameters_invalid", problem)
    if operation in SYNC_OPERATIONS:
        return _inspect_sync(operation, parameters, deadline)
    reader = {"tag": _inspect_tag, "release": _inspect_release, "pr_merge": _inspect_pr_merge}
    return reader[operation](parameters, deadline)


def _predicate(request: dict[str, Any], deadline: float) -> dict[str, Any]:
    def result(outcome: str, reason: str, references: list[str] | None = None) -> dict[str, Any]:
        return {"outcome": outcome, "reason": reason, "references": references or [],
                "observed_at": _now_ms()}

    if request.get("predicate") != "publication_visible":
        return result("unknown", "store_unreachable")
    observed = _effect(request.get("operation"), request.get("parameters"), deadline) \
        if isinstance(request.get("operation"), str) else _unknown("parameters_invalid")
    references = observed["references"]
    if observed["outcome"] == "satisfied":
        return result("satisfied", "observed", references)
    if observed["outcome"] == "absent":
        return result("unsatisfied", "ref_absent", references)
    if observed["outcome"] == "diverged":
        if observed["reason"] == "tag_not_annotated":
            return result("unsatisfied", "ref_not_immutable", references)
        return result("unsatisfied", "subject_mismatch", references)
    return result("unknown", "store_unreachable", references)


def inspect(request: Any) -> dict[str, Any]:
    """The effect or predicate `Observation` for one adapter request (#124 D7, D11, D25).

    Never raises and never mutates: a request outside the closed shape, or a read that cannot
    be judged, is `unknown`.
    """
    deadline = time.monotonic() + COLLECTION_BUDGET_SECONDS
    kind = request.get("kind") if isinstance(request, dict) else None
    if kind == "predicate" and set(request) == {"kind", "predicate", "operation", "parameters"}:
        return _predicate(request, deadline)
    if kind == "effect" and set(request) == {"kind", "operation", "parameters"}:
        operation = request["operation"]
        return _effect(operation if isinstance(operation, str) else "", request["parameters"],
                       deadline)
    if kind == "predicate":
        return {"outcome": "unknown", "reason": "store_unreachable", "references": [],
                "observed_at": _now_ms()}
    return _unknown("parameters_invalid", "request is not a closed effect or predicate request")


class _Refusal(Exception):
    """An `invoke` that ends here: the closed `InvokeResult` to return."""

    def __init__(self, result: str, error_class: str, reference: str) -> None:
        super().__init__(reference)
        self.answer = {"result": result, "error_class": error_class,
                       "reference": reference[:DETAIL_LIMIT] or "refused"}


FORBIDDEN_TITLE = frozenset('"$`\\\x00\r\n')


def _run_child(argv: list[str], cwd: str | None, stdin: str | None = None
               ) -> tuple[str, subprocess.CompletedProcess | None, str]:
    """Run `argv` by name within `CHILD_TIMEOUT_SECONDS`: `(status, process, detail)`.

    `status` is `ok` (the process finished, whatever its exit), `timeout` or `missing`.
    """
    env = {name: value for name, value in os.environ.items() if name not in TOKEN_VARIABLES}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=CHILD_TIMEOUT_SECONDS, env=env, cwd=cwd, input=stdin,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "timeout", None, "timed out"
    except OSError as error:
        return "missing", None, str(error)
    return "ok", done, done.stderr.strip()[:DETAIL_LIMIT]


def _precondition_read(argv: list[str], cwd: str | None) -> str:
    """Stdout of one precondition read; nothing was mutated, so a failed read is a refusal."""
    status, done, detail = _run_child(argv, cwd)
    name = " ".join(argv[:2])
    if status == "timeout":
        raise _Refusal("rejected", "transient_transport", f"{name}: timed out")
    if status == "missing" or done.returncode != 0:
        raise _Refusal("rejected", "provider_unavailable", f"{name}: {detail or 'failed'}")
    return done.stdout


def _invoke_shape(request: Any) -> tuple[str, dict[str, Any]]:
    """The operation and parameters of a request that is a supported, valid effect."""
    if not (isinstance(request, dict) and set(request) == {"kind", "operation", "parameters"}
            and request["kind"] == "effect" and isinstance(request["operation"], str)):
        raise _Refusal("rejected", "invalid_input", "request is not a closed effect request")
    operation, parameters = request["operation"], request["parameters"]
    entry = describe()["operations"].get(operation)
    if operation in SYNC_OPERATIONS:
        entry = {"support": "supported"}
    if entry is None or entry["support"] != "supported":
        reason = "unknown_operation" if entry is None else entry["reason"]
        raise _Refusal("rejected", "unsupported_operation", f"{operation}: {reason}")
    problem = _parameters_problem(operation, parameters)
    if problem is None and operation == "release":
        if any(char in FORBIDDEN_TITLE for char in parameters["title"]):
            problem = "title has a character that cannot be quoted"
        else:
            try:
                parameters["notes"].encode("utf-8")
            except UnicodeEncodeError:
                problem = "notes are not UTF-8 text"
    if problem is not None:
        raise _Refusal("rejected", "invalid_input", problem)
    return operation, parameters


def _same_repository(slug: str, checkout: str) -> None:
    origin = _precondition_read(["git", "remote", "get-url", "origin"], checkout)
    pushes = [line for line in _precondition_read(
        ["git", "remote", "get-url", "--push", "--all", "origin"], checkout).splitlines()
        if line.strip()]
    named = _precondition_read(
        ["gh", "api", f"repos/{slug}", "--jq", ".full_name"], checkout).strip()
    if len(pushes) != 1:
        raise _Refusal("rejected", "precondition_failed", f"origin has {len(pushes)} push urls")
    for what, url in (("origin", origin), ("push url", pushes[0])):
        if github_slug(url) is None:
            raise _Refusal("rejected", "precondition_failed",
                           f"{what} is not a github.com repository url")
    for what, found in (("origin", github_slug(origin)),
                        ("push url", github_slug(pushes[0])), ("repository", named)):
        if found != slug:
            raise _Refusal("rejected", "precondition_failed",
                           f"{what} is {found}, not {slug}")


def _contained(parameters: dict[str, Any], commit: str, checkout: str) -> None:
    slug, branch = parameters["target"]["repository"], parameters["target"]["branch"]
    status = _precondition_read(
        ["gh", "api", f"repos/{slug}/compare/{commit}...{branch}", "--jq", ".status"],
        checkout).strip()
    if not status:
        raise _Refusal("rejected", "provider_unavailable", "compare returned no status")
    if status not in ("identical", "ahead"):
        raise _Refusal("rejected", "precondition_failed", f"{commit} is {status} of {branch}")


def _local_tag(tag: str, commit: str, checkout: str) -> None:
    """Reuse an annotated local tag at `commit`, create it when absent, else refuse (D25)."""
    kind = _precondition_read(
        ["git", "for-each-ref", "--format=%(objecttype)", f"refs/tags/{tag}"], checkout).strip()
    if not kind:
        _precondition_read(["git", "tag", "-a", tag, commit, "-m", f"release: {tag}"], checkout)
        return
    peeled = _precondition_read(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"],
                                checkout).strip() if kind == "tag" else None
    if peeled is not None and SHA.fullmatch(peeled) is None:
        raise _Refusal("rejected", "provider_unavailable", "rev-parse did not return a commit id")
    if peeled != commit:
        raise _Refusal("rejected", "precondition_failed",
                       f"local tag {tag} is not an annotated tag at {commit}")


def _guard(raw: str, checkout: str) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": raw}, "cwd": checkout})
    status, done, detail = _run_child(["claude-bash-lifecycle-guard"], checkout, payload)
    if status == "ok" and done.returncode == 0:
        return
    if status == "ok" and not detail:
        detail = f"exit {done.returncode}"
    raise _Refusal("rejected", "authorization_denied", f"guard: {detail}")


def _mutate(argv: list[str], raw: str, checkout: str, operation: str, reference: str
            ) -> dict[str, Any]:
    """The guarded one mutation: `reference` names what an accepted call made.

    A `release` or `sync_pr` prefers the URL its `gh` printed. Only `tag` and `release` read their refusal
    text (`already exists`, `HTTP 422`): a failed `pr_merge` is `unknown` whatever it says,
    and the core inspects the pull request (issue 554 D6).
    """
    _guard(raw, checkout)
    status, done, detail = _run_child(argv, checkout)
    name = " ".join(argv[:2])
    if status == "timeout":
        return {"result": "unknown", "error_class": "transient_transport",
                "reference": f"{name}: timed out"}
    if status == "missing":
        # the spawn failed before any child ran, so nothing was applied
        return {"result": "rejected", "error_class": "provider_unavailable",
                "reference": f"{name}: {detail}"[:DETAIL_LIMIT]}
    if done.returncode == 0:
        url = done.stdout.strip().splitlines()[:1]
        if operation in ("release", "sync_pr") and url and url[0].startswith("http"):
            reference = url[0].strip()
        return {"result": "accepted", "error_class": None, "reference": reference}
    marker = {"tag": "already exists", "release": "HTTP 422"}.get(operation)
    if marker is not None and marker in done.stderr:
        return {"result": "rejected", "error_class": "precondition_failed",
                "reference": f"{name}: {marker}"}
    return {"result": "unknown", "error_class": "transient_transport",
            "reference": f"{name}: {detail or 'exit ' + str(done.returncode)}"[:DETAIL_LIMIT]}


def _precondition_json(argv: list[str], checkout: str) -> Any:
    """The parsed JSON of one precondition read; unparsable output is a refusal."""
    try:
        return json.loads(_precondition_read(argv, checkout))
    except ValueError:
        raise _Refusal("rejected", "provider_unavailable", f"{' '.join(argv[:2])}: output is not JSON")


def _precondition_field(value: Any, *path: str) -> str:
    """A string field of a precondition read; a missing or mistyped one is a refusal."""
    try:
        return _field(value, *path)
    except _Unknown as error:
        raise _Refusal("rejected", "provider_unavailable", f"{error.reason}: {error.detail}")


def _protection_floor(slug: str, branch: str) -> None:
    """Refuse unless the target branch's protection holds the floor (issue 554 D4, D13)."""
    status, payload, detail = _gh(["api", _protection_path(slug, branch)],
                                  time.monotonic() + CHILD_TIMEOUT_SECONDS)
    if status == "lookup_timeout":
        raise _Refusal("rejected", "transient_transport", "protection read: timed out")
    if status not in ("ok", 404, 403):
        raise _Refusal("rejected", "provider_unavailable",
                       f"protection read: {status}: {detail}")
    unmet = _floor_problem(_protection_facts(status, payload))
    if unmet is not None:
        raise _Refusal("rejected", "precondition_failed", f"protection_floor_unmet: {unmet}")


def _merge_preconditions(parameters: dict[str, Any], checkout: str) -> None:
    """The reads between the floor and the render, each a refusal on a miss (issue 554 D6)."""
    slug, branch = parameters["target"]["repository"], parameters["target"]["branch"]
    candidate = parameters["candidate"]
    _protection_floor(slug, branch)
    deletes = _precondition_read(
        ["gh", "api", f"repos/{slug}", "--jq", ".delete_branch_on_merge"], checkout).strip()
    if deletes != "false":
        raise _Refusal("rejected", "precondition_failed", "head_auto_delete_on")
    view = _precondition_json(["gh", "pr", "view", str(candidate["merge"]["pr"]), "--repo", slug,
                               "--json", PR_FIELDS], checkout)
    state, base = _precondition_field(view, "state"), _precondition_field(view, "baseRefName")
    head = _precondition_field(view, "headRefOid")
    if state != "OPEN":
        raise _Refusal("rejected", "precondition_failed", f"pr_not_open: {state}")
    if base != branch:
        raise _Refusal("rejected", "precondition_failed", f"pr_base_mismatch: {base}")
    if head != candidate["commit"]:
        raise _Refusal("rejected", "precondition_failed", f"pr_head_mismatch: {head}")
    tip = _precondition_field(_precondition_json(
        ["gh", "api", f"repos/{slug}/git/ref/heads/{branch}"], checkout), "object", "sha")
    if tip != candidate["merge"]["base_tip"]:
        raise _Refusal("rejected", "precondition_failed", f"base_moved: {tip}")


def _invoke_pr_merge(parameters: dict[str, Any], checkout: str) -> dict[str, Any]:
    """Merge the release pull request once, behind its preconditions (issue 554 D4, D6, D13)."""
    slug, commit = parameters["target"]["repository"], parameters["candidate"]["commit"]
    number = parameters["candidate"]["merge"]["pr"]
    _merge_preconditions(parameters, checkout)
    argv = ["gh", "pr", "merge", str(number), "--repo", slug, "--merge",
            "--match-head-commit", commit]
    raw = " ".join(argv)
    if shlex.split(raw) != argv:
        raise _Refusal("rejected", "invalid_input", "rendered command does not match its argv")
    return _mutate(argv, raw, checkout, "pr_merge", f"https://github.com/{slug}/pull/{number}")


def _released_for_invoke(parameters: dict[str, Any], checkout: str) -> str:
    """The commit `tag` publishes, or a refusal when the release PR has not landed as bound."""

    def read(argv: list[str]) -> Any:
        try:
            return json.loads(_precondition_read(["gh", *argv], checkout))
        except ValueError:
            raise _Refusal("rejected", "provider_unavailable", f"gh {argv[0]}: output is not JSON")

    try:
        released = _released(parameters, read)
    except _Unknown as error:
        raise _Refusal("rejected", "provider_unavailable", f"{error.reason}: {error.detail}")
    if released is None:
        raise _Refusal("rejected", "precondition_failed", "release PR not merged as bound")
    return released


def _invoke_tag(parameters: dict[str, Any], checkout: str) -> dict[str, Any]:
    """Tag and push the released commit; a merge binding also fetches the branch holding it (D8)."""
    tag, branch = parameters["candidate"]["version"], parameters["target"]["branch"]
    released = _released_for_invoke(parameters, checkout)
    _contained(parameters, released, checkout)
    if "merge" in parameters["candidate"]:
        _precondition_read(["git", "fetch", "--no-tags", "origin", f"refs/heads/{branch}"], checkout)
    _local_tag(tag, released, checkout)
    argv, raw = ["git", "push", "origin", f"refs/tags/{tag}"], f"git push origin refs/tags/{tag}"
    return _mutate(argv, raw, checkout, "tag", f"refs/tags/{tag}")


def _local_branch(branch: str, commit: str, checkout: str) -> None:
    """Reuse a local `branch` at `commit`, create it when absent, else refuse (issue 845)."""
    found = _precondition_read(
        ["git", "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}"], checkout).strip()
    if not found:
        _precondition_read(["git", "branch", "--no-track", branch, commit], checkout)
    elif found != commit:
        raise _Refusal("rejected", "precondition_failed",
                       f"local branch {branch} is not at {commit}")


def _invoke_sync_branch(parameters: dict[str, Any], checkout: str) -> dict[str, Any]:
    """Push the sync branch at the release merge commit (issue 845)."""
    names = _sync_names(parameters)
    released = _released_for_invoke(parameters, checkout)
    _precondition_read(["git", "fetch", "--no-tags", "origin", f"refs/heads/{names['default']}"],
                       checkout)
    _local_branch(names["branch"], released, checkout)
    argv = ["git", "push", "origin", names["branch"]]
    return _mutate(argv, " ".join(argv), checkout, "sync_branch", f"refs/heads/{names['branch']}")


def _invoke_sync_pr(parameters: dict[str, Any], checkout: str) -> dict[str, Any]:
    """Open the sync pull request from the pushed sync branch (issue 845)."""
    names = _sync_names(parameters)
    status, _, detail = _gh(["api", f"repos/{names['slug']}/git/ref/heads/{names['branch']}"],
                            time.monotonic() + CHILD_TIMEOUT_SECONDS)
    if status == 404:
        raise _Refusal("rejected", "precondition_failed", "sync_branch_absent")
    if status != "ok":
        raise _Refusal("rejected", "transient_transport" if status == "lookup_timeout"
                       else "provider_unavailable", f"sync branch read: {status}: {detail}")
    argv, raw = _sync_create(names)
    if shlex.split(raw) != argv:
        raise _Refusal("rejected", "invalid_input", "rendered command does not match its argv")
    return _mutate(argv, raw, checkout, "sync_pr", f"pr:{names['branch']}")


def _invoke(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
    slug, tag = parameters["target"]["repository"], parameters["candidate"]["version"]
    toplevel = _precondition_read(["git", "rev-parse", "--show-toplevel"], None).strip()
    if not os.path.isabs(toplevel):
        raise _Refusal("rejected", "provider_unavailable", "rev-parse did not return a directory")
    _same_repository(slug, toplevel)
    if operation == "pr_merge":
        return _invoke_pr_merge(parameters, toplevel)
    if operation == "tag":
        return _invoke_tag(parameters, toplevel)
    if operation in SYNC_OPERATIONS:
        sync = _invoke_sync_branch if operation == "sync_branch" else _invoke_sync_pr
        return sync(parameters, toplevel)
    descriptor, path = tempfile.mkstemp(prefix="forge-release-notes-", suffix=".md")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(parameters["notes"])
        argv = ["gh", "release", "create", tag, "--repo", slug, "--verify-tag", "--title",
                parameters["title"], "--notes-file", path]
        raw = (f'gh release create {tag} --repo {slug} --verify-tag '
               f'--title "{parameters["title"]}" --notes-file {shlex.quote(path)}')
        if shlex.split(raw) != argv:
            raise _Refusal("rejected", "invalid_input", "rendered command does not match its argv")
        return _mutate(argv, raw, toplevel, operation, f"release:{tag}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def invoke(request: Any) -> dict[str, Any]:
    """The `InvokeResult` of one effect request: `{result, error_class, reference}` (#124 D8, D9).

    A refusal at any step returns before the mutation, which is made at most once and never
    retried. Whether it landed is the core's to observe afterwards (#85, #206).
    """
    try:
        operation, parameters = _invoke_shape(request)
        return _invoke(operation, parameters)
    except _Refusal as refusal:
        return refusal.answer
