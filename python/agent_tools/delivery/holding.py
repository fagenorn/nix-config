"""`holding`: the pure part of the close-out hold (issue 1541), a port of the program's close-out gates.

A merged issue whose criteria are not all proven at the merge is held: a hold comment carrying one
```verify fence is posted, the issue is labelled `needs-verification` and the runner is run once. This
module decides and words that, from facts the caller has already read: `gate` and `stale` read only their
arguments and call no forge and no subprocess.

The program is `home/common/claude-code/skills/deliver-standard/deliver-standard.js`; the line ranges
below are its. `criteria` reads the acceptance section of an issue body (`console.inbox`); `asks_owner`
(1049), `command_outside` (1038-1042) and `script_run` (1054-1058) are its helpers of those names.

`gate` refuses in this order, the first refusal winning (1170-1231, 1274-1285):

1. `missing-checks`: an open (evidence or human) criterion with no written check, or a human one whose
   check does not ask the owner;
2. `human-checks`: a code or evidence criterion named by a check that asks the owner, written or posted;
3. `unattended`: a written check, or a check of this issue's own posted fence, running a command outside
   the verification ids;
4. `owner-checks`: a human criterion named by a non-owner check of a posted fence, or left in this
   issue's own fence without an owner check;
5. `script-checks` (1203-1224): an evidence criterion held with a committed script that a posted fence
   checks with another invocation, or that this issue's own fence omits;
6. `note-checks`: this issue's own fence checks a note criterion;
7. `missing-checks` again: this issue's own fence omits an open criterion (a human one may sit in a
   fence of another issue for the same merge).

Otherwise `ready`: the human criteria are split into their own checks only when the issue blocks another
(`blocks`), and the rest are the parent `block`. `stale` (1127, 1163) names the posted fences that still
check a criterion the owner's look approval answered and that the hold may not rewrite. Ids compare
ignoring case, as the program's `upId`.

The reads and writes the `closing` hold subcommands make live below `split_body`: `posted_fences` (the issue's own
selected fence and those of its split children for one merge), `blocking`, `pr_facts`, `verification`,
`look_status` and `look_acs`, `lint_all` change nothing; `file_split`, `post_hold`, `deliver_close`,
`label_hold` and `verify_run` write, each idempotent by itself (a second call with the same arguments posts,
files, labels and closes nothing more) and each paired with a read the engine runs as its check. Every one
raises `landing.Failure` for a forge or subprocess fault.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence

from agent_tools.claims import forge_markers
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import inbox
from agent_tools.delivery import landing, look_marker
from agent_tools.delivery.landing import Failure
from agent_tools.system import forge_api
from agent_tools.system.siblings import sibling_argv
from agent_tools.verification import verify_block, verify_issues, verify_pending

LABEL = "needs-verification"
OPEN_KINDS = ("evidence", "human")
KINDS = ("code", "evidence", "human", "note")
LOOK_TIMEOUT = 120
LABEL_COLOR = "1D76DB"
RUN_TIMEOUT = 900


def criteria(body: str) -> list[dict]:
    return [{"id": inbox.ac_id(item), "kind": item.kind, "text": item.text}
            for item in inbox.acceptance_criteria(body)]


def _up(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


def _object(value: object) -> bool:
    return isinstance(value, dict)


def _in(check: object, gone: set) -> bool:
    """Whether the check names a criterion of `gone` (upper-cased ids); a check whose `ac` is no string names none."""
    return _object(check) and isinstance(check.get("ac"), str) and check["ac"].upper() in gone


def _run(check: object) -> dict | None:
    run = check.get("run") if _object(check) else None
    return run if _object(run) else None


def asks_owner(check: object) -> bool:
    if not _object(check):
        return False
    run = _run(check)
    return check.get("kind") == "human" or (run is not None and ("ask" in run or "act" in run))


def command_outside(check: object, verification: Sequence[str]) -> bool:
    run = _run(check)
    if run is None or check.get("kind") != "evidence":
        return False
    then = run.get("then")
    command = run["command"] if isinstance(run.get("command"), str) else (
        then["command"] if _object(then) and isinstance(then.get("command"), str) else None)
    return command is not None and command not in verification


def script_run(check: object, merge: str) -> str | None:
    run = _run(check)
    if run is None or not isinstance(run.get("script"), str):
        return None
    at = run["at"] if isinstance(run.get("at"), str) else merge
    args = run["args"] if isinstance(run.get("args"), list) else []
    return json.dumps([run["script"], at, args])


def parse_written(written: list[dict]) -> list[dict]:
    checks = []
    for entry in written:
        try:
            check = json.loads(entry["check"], object_pairs_hook=reject_duplicate_keys,
                               parse_constant=reject_nonfinite_literal)
        except (TypeError, KeyError, ValueError, RecursionError):
            continue
        if _object(check):
            checks.append(check)
    return checks


def block_of(checks: list, merge: str) -> dict:
    return {"v": 1, "merge": merge, "checks": checks}


def _names(check: object, item: dict) -> bool:
    return _object(check) and _up(check.get("ac")) == _up(item["id"])


def _named(checks: list, item: dict) -> bool:
    return any(_names(check, item) for check in checks)


def _ordered(ids: Sequence[object], every: list[dict]) -> list:
    known = [item["id"] for item in every]
    spelled = {_up(name): name for name in known}
    found = {spelled.get(_up(value), value) for value in ids}
    return [name for name in known if name in found] + sorted(
        (value for value in found if value not in known), key=str)


def _refusal(verdict: str, ids: Sequence[object], every: list[dict], **named: list) -> dict:
    return {"verdict": verdict, "acs": _ordered(ids, every), **named}


def _of_kind(every: list[dict], *kinds: str) -> list[dict]:
    return [item for item in every if item["kind"] in kinds]


def _ids_for(checks: list, items: list[dict], owner: bool) -> list:
    """The items named by a check that asks the owner (`owner`) or one that does not."""
    return [item["id"] for item in items
            if any(_names(check, item) and asks_owner(check) == owner for check in checks)]


def gate(*, criteria: list[dict], posted: list[dict], blocks: list, answered: list[str], written: list[dict],
         merge: str, issue: int, verification: Sequence[str]) -> dict:
    gone = {_up(name) for name in answered}
    acceptance = [item for item in criteria if _up(item["id"]) not in gone]
    open_items = _of_kind(acceptance, *OPEN_KINDS)
    machine = _of_kind(acceptance, "code", "evidence")
    humans = _of_kind(acceptance, "human")
    parsed = parse_written(written)
    authorized = [next((check for check in parsed if _names(check, item)), None) for item in open_items]
    chosen = [check for check in authorized if check is not None]
    own = next((entry for entry in posted if entry["issue"] == issue), None)

    lacking = [item["id"] for item, check in zip(open_items, authorized)
               if check is None or (item["kind"] == "human" and not asks_owner(check))]
    if lacking:
        return _refusal("missing-checks", lacking, criteria)

    given = [*chosen, *(check for entry in posted for check in entry["checks"])]
    asked = _ids_for(given, machine, True)
    if asked:
        holds = [entry["issue"] for entry in posted if _ids_for(entry["checks"], machine, True)]
        return _refusal("human-checks", asked, criteria, posted_holds=holds)

    outside = [check["ac"] for check in [*chosen, *(own["checks"] if own else [])]
               if _object(check) and isinstance(check.get("ac"), str) and command_outside(check, verification)]
    if outside:
        return _refusal("unattended", outside, criteria)

    wrong = [name for entry in posted for name in _ids_for(entry["checks"], humans, False)]
    wrong_holds = [entry["issue"] for entry in posted if _ids_for(entry["checks"], humans, False)]
    unsplit = [item["id"] for item in open_items if own and item["kind"] == "human" and not blocks
               and not any(_names(check, item) and asks_owner(check) for check in own["checks"])]
    if wrong or unsplit:
        return _refusal("owner-checks", [*wrong, *unsplit], criteria,
                        posted_holds=[*wrong_holds, *([issue] if unsplit and issue not in wrong_holds else [])])

    wanted = {_up(item["id"]): script_run(check, merge)
              for item, check in zip(open_items, authorized) if item["kind"] == "evidence"}
    wanted = {name: run for name, run in wanted.items() if run is not None}
    flagged: list[str] = []
    flagged_issues: list[int] = []
    for entry in posted:
        at = entry["merge"] if isinstance(entry.get("merge"), str) else merge
        for check in entry["checks"]:
            item = next((item for item in open_items
                         if _up(item["id"]) in wanted and _names(check, item)), None)
            if item and script_run(check, at) != wanted[_up(item["id"])]:
                flagged.append(item["id"])
                flagged_issues.append(entry["issue"])
        if entry["issue"] == issue:
            for item in open_items:
                if _up(item["id"]) in wanted and not _named(entry["checks"], item):
                    flagged.append(item["id"])
                    flagged_issues.append(entry["issue"])
    if flagged:
        return _refusal("script-checks", flagged, criteria,
                        posted_holds=list(dict.fromkeys(flagged_issues)))

    if own:
        notes = [item["id"] for item in _of_kind(acceptance, "note") if _named(own["checks"], item)]
        if notes:
            return _refusal("note-checks", notes, criteria)
        absent = [item["id"] for item in open_items if not _named(own["checks"], item)
                  and not (item["kind"] == "human" and any(
                      entry["issue"] != issue and entry.get("merge") == merge and _named(entry["checks"], item)
                      for entry in posted))]
        if absent:
            return _refusal("missing-checks", absent, criteria)

    split = []
    remaining = []
    for item, check in zip(open_items, authorized):
        if blocks and item["kind"] == "human":
            split.append({"ac": item["id"], "block": block_of([check], merge)})
        else:
            remaining.append((item, check))
    return {"verdict": "ready", "split": split,
            "block": block_of([check for _, check in remaining], merge) if remaining else None,
            "held": [{"id": item["id"], "kind": item["kind"], "text": item["text"]}
                     for item, _ in remaining]}


def stale(posted: list[dict], answered: list[str], issue: int, criteria: list[dict]) -> list[dict]:
    """The posted fences naming an answered criterion that the hold may not rewrite, with those ids as `acs`."""
    gone = {_up(name) for name in answered}
    no_hold = not any(item["kind"] in OPEN_KINDS and _up(item["id"]) not in gone for item in criteria)
    entries = []
    for entry in posted:
        named = {check["ac"].upper() for check in entry["checks"]
                 if _object(check) and isinstance(check.get("ac"), str)}
        acs = [name for name in answered if _up(name) in named]
        if acs and (entry["issue"] != issue or no_hold or entry["results"] is True):
            entries.append({**entry, "acs": acs})
    return entries


def hold_body(pr: int, merge: str, held: list[dict], block: dict) -> str:
    lines = [f"Held after the merge of PR #{pr} ({merge}); the runner settles the checks below.", ""]
    lines += [f"- {item['id']} [{item['kind']}] {item['text']}" for item in held]
    return "\n".join([*lines, "", "```verify", json.dumps(block, indent=2), "```", ""])


def split_line(issue: int, ac: str, merge: str) -> str:
    return f"Split from #{issue}: {ac} after the merge {merge}."


def split_body(issue: int, pr: int, merge: str, criterion: dict, block: dict) -> tuple[str, str]:
    title = f"Verify {criterion['id']} of #{issue}: {criterion['text']}"
    lines = [split_line(issue, criterion["id"], merge),
             f"This human criterion of #{issue} is held on its own after PR #{pr}: {criterion['text']}"]
    return title, "\n".join([*lines, "", "```verify", json.dumps(block, indent=2), "```", ""])


def _forge(read):
    try:
        return read()
    except forge_api.ForgeError as error:
        raise Failure(error.code, error.detail, error.transient) from None


def _pages(path: str) -> list:
    return _forge(lambda: forge_api.api_pages(path))


def _fence(number: int, ac: str | None, comments: list[verify_issues.Comment]) -> dict | None:
    """The selected fence of one issue as `{issue, ac, merge, checks, comment_id, results, block}`, or None.

    A fence whose JSON is not an object or has no `checks` list is still the selected one: its `checks` is
    empty, its `merge` None and its `block` is what parsed (None for a fence that did not parse)."""
    held = verify_issues.select(comments)
    if held is None:
        return None
    block = held.block if _object(held.block) else None
    checks = block.get("checks") if block else None
    prefix = f"{held.block_id}."
    results = any(marker.fields.get("block", "").startswith(prefix) for marker in held.markers)
    return {"issue": number, "ac": ac, "merge": block.get("merge") if block else None,
            "checks": checks if isinstance(checks, list) else [], "comment_id": held.block_id,
            "results": results, "block": held.block}


def _comments(repo: str, number: int) -> list[verify_issues.Comment]:
    pages = _pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
    return _forge(lambda: verify_issues.comments_from_rest(pages))


def _split_issues(repo: str, issue: int, merge: str, path: str, state: str) -> list[tuple[int, str]]:
    """`(number, ac)` of each `state` issue of the listing `path` whose body starts with the split identity line."""
    identity = re.compile(rf"Split from #{issue}: (\S+) after the merge {re.escape(merge)}\.")
    children = []
    for page in _pages(path):
        for item in page if isinstance(page, list) else []:
            number = item.get("number") if _object(item) else None
            body = item.get("body") if _object(item) else None
            if (not isinstance(number, int) or isinstance(number, bool) or number == issue
                    or "pull_request" in item or item.get("state", "open") != state
                    or not isinstance(body, str)):
                continue
            matched = identity.fullmatch(body.split("\n", 1)[0].removesuffix("\r"))
            if matched:
                children.append((number, matched[1]))
    return sorted(set(children))


def split_children(repo: str, issue: int, merge: str) -> list[tuple[int, str]]:
    """`(number, ac)` of each open `needs-verification` issue split from `issue` for `merge`, ascending."""
    return _split_issues(repo, issue, merge, f"repos/{repo}/issues?labels={LABEL}", "open")


def closed_children(repo: str, issue: int, merge: str) -> list[tuple[int, str]]:
    """`(number, ac)` of each closed issue split from `issue` for `merge`, ascending.

    The runner removes `needs-verification` when it closes a verified issue, so a closed child is found by its
    identity line among the closed issues, not by the label."""
    return _split_issues(repo, issue, merge, f"repos/{repo}/issues?state=closed&per_page=100", "closed")


def fences(repo: str, issue: int, merge: str | None) -> list[dict]:
    """The issue's own selected fence, then each open split child's of `merge` (none when `merge` is None)."""
    found = []
    own = _fence(issue, None, _comments(repo, issue))
    if own is not None:
        found.append(own)
    if merge is None:
        return found
    for number, ac in split_children(repo, issue, merge):
        child = _fence(number, ac, _comments(repo, number))
        if child is not None and child["merge"] == merge:
            found.append(child)
    return found


def posted_fences(repo: str, issue: int, merge: str) -> list[dict]:
    """The posted fences of the issue and its split children for `merge`: `{issue, merge, checks, comment_id, results}`."""
    return [{key: entry[key] for key in ("issue", "merge", "checks", "comment_id", "results")}
            for entry in fences(repo, issue, merge)]


def blocking(repo: str, issue: int) -> list[int]:
    """The numbers of the issues `issue` blocks."""
    found = _forge(lambda: forge_api.gh_json(["api", f"repos/{repo}/issues/{issue}/dependencies/blocking"]))
    if not isinstance(found, list) or not all(_object(item) and isinstance(item.get("number"), int) for item in found):
        raise Failure("payload_invalid", "the blocking list is not an array of issues")
    return [item["number"] for item in found]


def pr_facts(repo: str, pr: int) -> dict:
    """The pull request's `pr_head`, `pr_branch` and the sorted distinct `workflows` of its checks."""
    view = _forge(lambda: forge_api.gh_json(
        ["pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,headRefName,statusCheckRollup"]))
    rollup = view.get("statusCheckRollup") if _object(view) else None
    if (not _object(view) or not isinstance(view.get("headRefOid"), str)
            or not isinstance(view.get("headRefName"), str) or not isinstance(rollup, list)):
        raise Failure("payload_invalid", "the pull request has no head, branch or check rollup")
    names = {item["workflowName"] for item in rollup
             if _object(item) and isinstance(item.get("workflowName"), str) and item["workflowName"]}
    return {"pr_head": view["headRefOid"], "pr_branch": view["headRefName"], "workflows": sorted(names)}


def verification(repo_root: str) -> list[str]:
    """The resolved contract's verification command ids."""
    found = landing._resolve(repo_root)["bindings"]["workflow"]["verification"]
    if not isinstance(found, list) or not all(isinstance(item, str) for item in found):
        raise Failure("payload_invalid", "the contract's verification is not a list of ids")
    return found


def look_acs(body: str) -> list[str]:
    """The ids of the look-marked criteria of a body, in body order."""
    lines = look_marker.marker_lines(body)
    return [inbox.ac_id(item) for item in inbox.acceptance_criteria(body) if item.line + 1 in lines]


def look_status(*, repo: str, issue: int, pr: int, head: str, merge: str) -> dict:
    """The parsed line of `look-approval status` for the head (`verdict` `unmarked`, `approved` or `needed`)."""
    argv = [*sibling_argv("delivery.look_approval"), "status", "--repo", repo, "--issue", str(issue),
            "--pr", str(pr), "--head", head, "--merge-commit", merge]
    env = {key: value for key, value in os.environ.items() if key not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=LOOK_TIMEOUT, check=False,
                              env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Failure("look_status_failed", "timeout", transient=True) from None
    except OSError as error:
        raise Failure("look_status_failed", str(error)) from None
    lines = done.stdout.splitlines()
    try:
        out = json.loads(lines[-1]) if lines else None
    except ValueError:
        out = None
    if done.returncode != 0 or not _object(out) or not isinstance(out.get("verdict"), str):
        code = out.get("error") if _object(out) and isinstance(out.get("error"), str) else "look_status_failed"
        raise Failure(code, (done.stderr.strip() or done.stdout.strip())[:500])
    return out


def lint(repo_root: str, block: object, *, workflows: Sequence[str], pr_head: str | None,
         pr_branch: str | None, blocks: Sequence) -> dict:
    """`{ok, errors}` of `verify_block.lint_block` for the block."""
    found = verify_block.lint_block(block, refs=verify_pending.CliReferences(repo_root), pr_workflows=workflows,
                                    pr_head=pr_head, pr_branch=pr_branch, blocks=[str(number) for number in blocks])
    return {"ok": found["ok"], "errors": found["errors"]}


def lint_all(*, repo_root: str, repo: str, issue: int, pr_head: str, pr_branch: str, workflows: list,
             blocks: list, answered: list, block: object, split: list[dict]) -> dict:
    """Lint the parent's block (its posted fence less the answered checks, else `block`) and each split's."""
    gone = {_up(name) for name in answered}
    merge = next((entry["block"].get("merge") for entry in [{"block": block}, *split]
                  if _object(entry["block"]) and isinstance(entry["block"].get("merge"), str)), None)
    found = fences(repo, issue, merge)
    context = {"workflows": workflows, "pr_head": pr_head, "pr_branch": pr_branch}
    lints = []
    own = next((entry for entry in found if entry["issue"] == issue), None)
    if own and _object(own["block"]) and isinstance(own["block"].get("checks"), list):
        parent = {**own["block"], "checks": [check for check in own["checks"] if not _in(check, gone)]}
    else:
        parent = own["block"] if own else block
    if own or parent is not None:
        lints.append({"issue": issue, "ac": None, **lint(repo_root, parent, blocks=blocks, **context)})
    for entry in split:
        child = split_child(repo, issue, merge, entry["ac"]) if merge else None
        fence = child["fence"] if child else None
        lints.append({"issue": child["issue"] if child else None, "ac": entry["ac"],
                      **lint(repo_root, fence["block"] if fence else entry["block"], blocks=(), **context)})
    return {"verdict": "valid" if all(item["ok"] for item in lints) else "invalid", "lints": lints}


def split_child(repo: str, issue: int, merge: str, ac: str) -> dict | None:
    """The split child of `issue` for `ac` at `merge` as `{issue, fence}` (`fence` None until it holds one).

    An open child is preferred; a child the runner has closed since still counts, so a continued hold files no second."""
    number = next((found for found, spelled in split_children(repo, issue, merge) if spelled == ac), None)
    if number is None:
        number = next((found for found, spelled in closed_children(repo, issue, merge) if spelled == ac), None)
    if number is None:
        return None
    return {"issue": number, "fence": _fence(number, ac, _comments(repo, number))}


def split_state(repo: str, issue: int, merge: str, split: list[dict]) -> dict:
    """`{verdict, children}`: `none` for no split, `split` when every entry has its child holding a fence."""
    children = []
    for entry in split:
        child = split_child(repo, issue, merge, entry["ac"])
        if child is None or child["fence"] is None:
            return {"verdict": "absent"}
        children.append({"ac": entry["ac"], "issue": child["issue"]})
    return {"verdict": "split" if split else "none", "children": children}


def _own_criterion(repo: str, issue: int, ac: str) -> dict:
    body = read_issue(repo, issue).get("body")
    found = next((item for item in criteria(body if isinstance(body, str) else "") if _up(item["id"]) == _up(ac)),
                 None)
    if found is None:
        raise Failure("payload_invalid", f"issue #{issue} has no criterion {ac}")
    return found


def read_issue(repo: str, number: int) -> dict:
    """The issue as the REST read gives it."""
    found = _forge(lambda: forge_api.gh_json(["api", f"repos/{repo}/issues/{number}"]))
    if not _object(found):
        raise Failure("payload_invalid", "the issue is not an object")
    return found


def file_split(repo: str, issue: int, pr: int, merge: str, split: list[dict]) -> dict:
    """File each split entry's child (when none is open) and post its hold comment (when it has no fence)."""
    children = []
    for entry in split:
        criterion = _own_criterion(repo, issue, entry["ac"])
        child = split_child(repo, issue, merge, entry["ac"])
        if child is None:
            title, body = split_body(issue, pr, merge, criterion, entry["block"])
            _forge(lambda: forge_api.ensure_label(repo, LABEL, LABEL_COLOR))
            number = _forge(lambda: forge_api.create_issue(repo, title, body, labels=[LABEL]))
            child = {"issue": number, "fence": None}
        if child["fence"] is None:
            text = hold_body(pr, merge, [criterion], entry["block"])
            _forge(lambda: forge_markers.post(repo, child["issue"], text))
        children.append({"ac": entry["ac"], "issue": child["issue"]})
    return {"verdict": "split" if split else "none", "children": children}


def _drop_answered(text: str, block: dict, answered: list[str]) -> tuple[str, dict]:
    """The hold comment `text` and its fence `block` without the checks naming an answered criterion."""
    gone = {_up(name) for name in answered}
    kept = [check for check in block["checks"] if not _in(check, gone)]
    reduced = {**block, "checks": kept}
    lines = [line for line in text.replace("\r\n", "\n").split("\n")
             if not any(re.match(rf"- {re.escape(name)}(\s|$)", line, re.IGNORECASE) for name in answered)]
    text = "\n".join(lines)
    fence = verify_block.FENCE.search(text)
    text = text[:fence.start(1)] + json.dumps(reduced, indent=2) + "\n" + text[fence.end(1):]
    return text, reduced


def _answers(block: object, answered: list[str]) -> bool:
    gone = {_up(name) for name in answered}
    checks = block.get("checks") if _object(block) else None
    return isinstance(checks, list) and any(_in(check, gone) for check in checks)


def post_state(repo: str, issue: int, answered: list[str], block: object) -> dict:
    """`posted` with the issue's own fence (none of whose checks name an answered criterion), `closed` when
    `block` is null and the issue is closed, else `absent`."""
    if block is None:
        closed = str(read_issue(repo, issue).get("state", "")).lower() == "closed"
        return {"verdict": "closed", "comment_id": None, "block": None} if closed else {"verdict": "absent"}
    own = _fence(issue, None, _comments(repo, issue))
    if own is None or _answers(own["block"], answered):
        return {"verdict": "absent"}
    return {"verdict": "posted", "comment_id": own["comment_id"], "block": own["block"]}


def post_hold(repo: str, issue: int, pr: int, merge: str, criteria_: list[dict], answered: list[str],
              block: object, children: list[dict]) -> dict:
    """Post the hold comment, edit an answered check out of the one that exists, or close the issue.

    With a null `block` every open criterion was split or answered by the look: post `Delivered by PR #<pr>` once
    and close the issue; with neither a split child nor an open criterion answered there is nothing to close on.
    Otherwise the issue's one fence comment is never posted twice."""
    comments = _comments(repo, issue)
    if block is None:
        gone = {_up(name) for name in answered}
        every_answered = any(item["kind"] in OPEN_KINDS for item in criteria_) and all(
            _up(item["id"]) in gone for item in criteria_ if item["kind"] in OPEN_KINDS)
        if not children and not every_answered:
            raise Failure("nothing_held", "no check is held and no criterion was split, so there is nothing to close on")
        lead = f"Delivered by PR #{pr}"
        if not any(item.body.startswith(lead) for item in comments):
            numbers = ", ".join(f"#{child['issue']}" for child in children)
            held = f"the human checks are held on {numbers}" if children else "the owner's look answered every open criterion"
            _forge(lambda: forge_markers.post(repo, issue, f"{lead}; {held}"))
        _forge(lambda: forge_api.close_issue(repo, issue, "completed"))
        return {"verdict": "closed", "comment_id": None, "block": None}
    own = _fence(issue, None, comments)
    if own is None:
        named = block.get("checks") if _object(block) else None
        held = [item for item in criteria_ if _object(block) and isinstance(named, list) and _named(named, item)]
        comment_id = _forge(lambda: forge_markers.post(repo, issue, hold_body(pr, merge, held, block)))
        return {"verdict": "posted", "comment_id": comment_id, "block": block}
    if _answers(own["block"], answered):
        if own["results"]:
            raise Failure("results_recorded", "the hold comment has a recorded result; editing its checks would "
                                              "invalidate it")
        text = next(item.body for item in comments if item.id == own["comment_id"])
        text, reduced = _drop_answered(text, own["block"], answered)
        _forge(lambda: forge_markers.edit(repo, own["comment_id"], text))
        return {"verdict": "posted", "comment_id": own["comment_id"], "block": reduced}
    return {"verdict": "posted", "comment_id": own["comment_id"], "block": own["block"]}


def label_state(repo: str, issue: int) -> bool:
    """Whether the issue carries the hold label."""
    labels = read_issue(repo, issue).get("labels")
    names = [item.get("name") if _object(item) else item for item in labels] if isinstance(labels, list) else []
    return LABEL in names


def label_hold(repo: str, issue: int) -> None:
    """Add the hold label unless the issue carries it."""
    if not label_state(repo, issue):
        _forge(lambda: forge_api.ensure_label(repo, LABEL, LABEL_COLOR))
        _forge(lambda: forge_api.add_label(repo, issue, LABEL))


def verify_run(host: str, repo: str, number: int) -> int:
    """Run `verify-pending run` for the issue on `host`; its exit status."""
    argv = [*sibling_argv("verification.verify_pending"), "run", "--host", host, "--repo", repo,
            "--issue", str(number)]
    env = {key: value for key, value in os.environ.items() if key not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False, env=env,
                              stdin=subprocess.DEVNULL).returncode
    except subprocess.TimeoutExpired:
        raise Failure("verify_run_failed", "timeout", transient=True) from None
    except OSError as error:
        raise Failure("verify_run_failed", str(error)) from None
