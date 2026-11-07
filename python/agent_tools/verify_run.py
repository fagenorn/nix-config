"""One runner pass over the held verification issues of a repository (issue 630, P1-P18).

`pass_issue` takes one GraphQL issue node and, for the trusted block it holds (P3), decides per
check whether it is this host's and due, runs it through `verify_exec` (never here), records one
result marker per state change (P4), labels failures (P16), files one follow-up issue per observed
miss under a claim (P10) and closes the issue once through a contested `verify-closed` marker
(P9). Every forge call goes through `forge_markers` and every marker write names `TRUSTED`
associations, so a marker by any other author neither wins a contest nor ends one (P3). "Now" is
only `Context.now()`, the forge's clock (P6, P7).

A run of a check holds a lease, a `verify-run` marker it wins and deletes when it is done, so no
two runs of one check overlap whatever their host (a run that died leaves a claim `LEASE` ends),
and it re-reads the markers once it holds it. The issue is finished only if the block it ran is
still the held one.

Every forge write is ordered so that the step that takes the issue out of the listing, or makes the
next pass skip work, comes after the step it would strand; a `ForgeError` ends the pass with a
`forge_error` line and the next pass finishes the work.
"""
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from agent_tools import forge_markers, verify_block, verify_exec, verify_facts, verify_issues, verify_owner
from agent_tools.forge_markers import ForgeError, Marker

NEEDS = "needs-verification"
FAILED = ("verification-failed", "B60205")
FOLLOW_UP = ("verification-follow-up", "FBCA04")
QUERY = (
    'query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) '
    '{ issues(first: 100, states: OPEN, labels: ["needs-verification"], '
    'orderBy: {field: CREATED_AT, direction: ASC}) { nodes { number labels(first: 50) { nodes { name } } '
    'comments(last: 100) { nodes { fullDatabaseId authorAssociation body createdAt updatedAt } } } } } }'
)
FINAL = ("pass", "hit", "miss", "expired")
PENDING_OUTCOMES = ("not_yet", "timeout", "exit_unexpected")
OWNER_GATES = ("owner_check",)
DEFAULT_EXPIRY_DAYS = 21
LEASE = timedelta(minutes=30)
TRUSTED = verify_issues.TRUSTED


@dataclass(frozen=True)
class Project:
    project_id: str
    slug: str
    root: Path
    contract_root: Path
    commit: str
    bindings: Mapping[str, Any]


def list_held(slug: str) -> list[dict]:
    """The open `needs-verification` issue nodes of the repository, with their last comments."""
    owner, name = slug.split("/", 1)
    payload = forge_markers.graphql(QUERY, {"owner": owner, "name": name})
    try:
        nodes = payload["data"]["repository"]["issues"]["nodes"]
    except (KeyError, TypeError):
        raise ForgeError("payload_invalid", "no issues listing") from None
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        raise ForgeError("payload_invalid", "issues are not an array of objects")
    return nodes


def runner_trusted(slug: str) -> bool:
    """Whether the authenticated `gh` account's own comments would count as trusted (`TRUSTED`).

    The runner reads back only trusted markers, so one whose account the forge labels anything
    else (a collaborator, say) cannot see what it wrote: it would repost every marker each pass
    and never expire a check. The association is the forge's, so it is derived the way the forge
    derives it: the owner of a user-owned repository, or an active member of the owning
    organization. A payload without the fields it needs is a `ForgeError`."""
    user = forge_markers.api_get("user")
    login = user.get("login") if isinstance(user, dict) else None
    repository = forge_markers.api_get(f"repos/{slug}")
    owner = repository.get("owner") if isinstance(repository, dict) else None
    owner_login = owner.get("login") if isinstance(owner, dict) else None
    if not (isinstance(login, str) and login and isinstance(owner_login, str) and owner_login):
        raise ForgeError("payload_invalid", "no authenticated login or repository owner")
    if owner.get("type") != "Organization":
        return login.lower() == owner_login.lower()
    membership = forge_markers.api_get(f"user/memberships/orgs/{quote(owner_login, safe='')}", allow=(403, 404))
    return isinstance(membership, dict) and membership.get("state") == "active"


def pass_repo(project: Project, host: str, refs: verify_block.References, *,
              issue: int | None = None, report: bool = False) -> list[dict]:
    """One pass over every listed issue (only `issue` when given); a listing failure propagates.

    A pass that writes first checks the runner's own account is trusted and otherwise ends with
    one `runner_untrusted` line, before any write or run; a report writes nothing and skips the check."""
    if not report and not runner_trusted(project.slug):
        return [{"repo": project.slug, "issue": None, "check": None, "ac": None,
                 "state": "skipped", "reason": "runner_untrusted"}]
    lines: list[dict] = []
    for node in list_held(project.slug):
        if issue is None or node.get("number") == issue:
            lines.extend(pass_issue(project, host, node, refs, report=report))
    return lines


def pass_issue(project: Project, host: str, node: dict, refs: verify_block.References, *,
               report: bool = False) -> list[dict]:
    """The report lines of one issue's pass; a forge failure ends it with one `forge_error` line."""
    run = _Pass(project, host, node, refs, report)
    try:
        run.execute()
    except ForgeError:
        run.line(None, None, "skipped", "forge_error")
    return run.lines


def _fence(text: str) -> str:
    """`text` inside a fence of backticks one longer than its longest backtick run (at least three)."""
    longest = max((len(found) for found in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}\n{text}\n{ticks}"


def _fenced_of(body: str) -> str:
    """The fenced output a result marker carries, or an empty string."""
    lines = body.split("\n")
    for index, text in enumerate(lines):
        if text.startswith("```"):
            return "\n".join(lines[index:])
    return ""


class _Pass:
    def __init__(self, project: Project, host: str, node: dict, refs: verify_block.References,
                 report: bool) -> None:
        self.project, self.host, self.refs, self.report = project, host, refs, report
        self.slug = project.slug
        self.number = node["number"]
        self.node = node
        self.lines: list[dict] = []
        self.block: dict = {}
        self.block_key = ""
        self.block_id = 0
        self.markers: list[Marker] = []
        self.states: list[str | None] = []
        self.followups: dict[int, str] = {}
        self.owner_posted = False
        self.prompted: set[int] = set()
        labels = (node.get("labels") or {}).get("nodes")
        self.labels: set[str] = {n["name"] for n in labels if isinstance(n, dict)
                                 and isinstance(n.get("name"), str)} if isinstance(labels, list) else set()
        self.trusted: list[Marker] = []

    def line(self, check: int | None, ac: str | None, state: str, reason: str) -> None:
        self.lines.append({"repo": self.slug, "issue": self.number, "check": check, "ac": ac,
                           "state": state, "reason": reason})

    def write(self, kind: str, fields: Mapping[str, str], sentence: str, match: Mapping[str, str],
              extra: str = "") -> forge_markers.WriteResult:
        return forge_markers.write(self.slug, self.number, kind, fields, sentence, match, extra,
                                   associations=verify_issues.TRUSTED)

    def live(self, kind: str, match: Mapping[str, str]) -> Marker | None:
        return verify_issues.live_one(self.markers, kind, match)

    # --- the pass ------------------------------------------------------------

    def execute(self) -> None:
        nodes = (self.node.get("comments") or {}).get("nodes")
        if not isinstance(nodes, list):
            raise ForgeError("payload_invalid", "issue node has no comments")
        comments = verify_issues.comments_from_graphql(nodes)
        held = verify_issues.select(comments)
        if held is None:
            return self.line(None, None, "skipped", "no_block")
        if held.block is None or not verify_block.lint_block(held.block, refs=self.refs)["ok"]:
            return self.line(None, None, "skipped", "block_invalid")
        self.block, self.block_key, self.markers = held.block, held.key, held.markers
        self.block_id = held.block_id
        parsed = [forge_markers.parse({"id": c.id, "body": c.body, "updated_at": c.created_at})
                  for c in comments if c.association in TRUSTED]
        self.trusted = [m for m in parsed if m is not None]
        closed = self.live(verify_issues.CLOSED, {"block": self.block_key})
        if closed is not None and closed.fields.get("outcome") in ("verified", "expired"):
            verified = closed.fields["outcome"] == "verified"
            if not self.report:
                self.owner_sweep()
                if not self.conclude(verified):
                    return
            return self.line(None, None, "closed", "verified" if verified else "not_verified")
        bindings = self.project.bindings
        self.ctx = verify_facts.Context(self.slug, self.project.root, bindings["vcs"]["default_branch"],
                                        bindings["deploy"], bindings["tracker"], self.markers)
        checks = self.block["checks"]
        self.states = [None] * len(checks)
        for index, check in enumerate(checks):
            self.check(index, check)
        if not self.report:
            self.owner_sweep()
            self.close()

    def check(self, index: int, check: Mapping) -> None:
        ac = check["ac"]
        key = {"block": self.block_key, "check": str(index)}
        previous = verify_issues.latest_result(self.markers, self.block_key, index)
        prev = previous.fields.get("state") if previous is not None else None
        self.states[index] = prev
        if prev in FINAL:
            self.line(index, ac, prev, "resolved")
            if prev == "miss":
                if "followup" in previous.fields:
                    self.followups[index] = previous.fields["followup"]
                elif not self.report:
                    self.follow_up(index, ac, key, previous, _fenced_of(previous.body))
            return
        if not self.report and self.answer(index, check, ac, key, previous):
            return
        bound = check["host"]
        if not (bound == self.host or bound == "any" or (isinstance(bound, list) and self.host in bound)):
            return self.line(index, ac, "pending", "not_this_host")
        gate = verify_exec.gate(check, self.project.bindings["workflow"]["verification"])
        if not gate.runnable and (self.report or gate.reason not in OWNER_GATES):
            return self.line(index, ac, "pending", gate.reason)
        merge = self.block["merge"]
        due = verify_facts.evaluate_when(check["when"], merge, self.ctx)
        if not due.due:
            if due.open_window is not None and not self.report:
                event = due.open_window
                self.write(verify_issues.WINDOW, {"event": event, "merge": merge, "host": self.host},
                           f"The {event} window opened, seen on {self.host}.",
                           {"event": event, "merge": merge})
            return self.line(index, ac, "pending", due.reason)
        if self.report:
            return self.line(index, ac, "due", "due")
        if not gate.runnable:
            return self.owner_form(index, check, ac, key, previous, prev, due, gate.reason)
        lease = self.take_lease(ac, key)
        if lease is None:
            return self.line(index, ac, "pending", "lost_contest")
        try:
            if not self.unchanged_since(index, previous):
                return self.line(index, ac, "pending", "lost_contest")
            self.settle(index, check, ac, key, prev, due)
        finally:
            forge_markers.delete(self.slug, lease)

    def take_lease(self, ac: str, key: Mapping[str, str]) -> int | None:
        """The comment id of this run's lease on the check, or None when another run holds it.

        A claim older than `LEASE` is a run that died: it is ended (append-only) and does not
        count. The lease is won by the smallest live `verify-run` comment, this host's own
        earlier run included, so two runs of one host never overlap either."""
        now = self.ctx.now()
        held = False
        for claim in forge_markers.contest(self.markers, verify_issues.RUN, key):
            if now >= claim.updated_at + LEASE:
                forge_markers.end(self.slug, self.number, claim.comment_id, "stale")
            else:
                held = True
        if held:
            return None
        won = self.write(verify_issues.RUN, {**key, "host": self.host}, f"{self.host} runs {ac}.", key)
        return won.own_id if won.won else None

    def unchanged_since(self, index: int, previous: Marker | None) -> bool:
        """Re-read the markers under the lease: False when a run that held it before recorded a
        result this one has not seen (it then waits for the next pass). Later reads use the fresh markers."""
        self.markers = verify_issues.visible(
            forge_markers.list_markers(self.slug, self.number, TRUSTED), self.block_id)
        latest = verify_issues.latest_result(self.markers, self.block_key, index)
        return (latest.comment_id if latest else None) == (previous.comment_id if previous else None)

    def settle(self, index: int, check: Mapping, ac: str, key: Mapping[str, str], prev: str | None,
               due: verify_facts.Due) -> None:
        """Run the check and record what changed, under its lease."""
        waiting = self.live(verify_issues.DUE, key)
        days = check.get("expires_after_days") or DEFAULT_EXPIRY_DAYS
        if (waiting is not None and check.get("on_expire", "close") == "close"
                and self.ctx.now() >= waiting.updated_at + timedelta(days=days)):
            self.record(index, ac, "expired", None, {}, "", "")
            return self.line(index, ac, "expired", "changed")
        outcome, code, output, command, facts = self.run(check)
        if outcome in PENDING_OUTCOMES:
            if waiting is None:
                self.write(verify_issues.DUE, {**key, "host": self.host},
                           f"{ac} is not yet resolved on {self.host}.", key)
            return self.line(index, ac, "pending", outcome)
        assertion = check.get("mode", "assert") == "assert"
        state = ("pass" if outcome == "met" else "fail") if assertion else (
            "hit" if outcome == "met" else "miss")
        if state == prev:
            return self.line(index, ac, state, "unchanged")
        facts = {**due.facts, **facts}
        if state == "fail" and check.get("on_fail", "label") == "ask":
            self.record(index, ac, state, code, facts, command, output)
            return self.line(index, ac, state, "fail_ask")
        if state == "fail":
            forge_markers.ensure_label(self.slug, *FAILED)
            forge_markers.add_label(self.slug, self.number, FAILED[0])
        posted = self.record(index, ac, state, code, facts, command, output)
        self.line(index, ac, state, "changed")
        if state == "miss":
            self.follow_up(index, ac, key, posted, _fenced_of(posted.body))

    # --- running ---------------------------------------------------------------

    def run(self, check: Mapping) -> tuple[str, int | None, str, str, dict[str, str]]:
        """The outcome, exit, trimmed output, command line and facts of one run."""
        run, expect = check["run"], check.get("expect")
        if "probe" in run:
            probe = verify_facts.run_probe(run, self.ctx)
            outcome = verify_exec.classify(verify_exec.Result(probe.exit, probe.output, "", False), expect)
            return outcome, probe.exit, verify_exec.trim(probe.output), f"probe {run['probe']}", probe.facts
        commit = self.project.commit if "command" in run else (run.get("at") or self.block["merge"])
        try:
            with verify_exec.workspace(self.project.root, commit) as wt:
                argv, cwd = verify_exec.run_argv(run, self.project.bindings, self.project.contract_root, wt)
                result = verify_exec.execute(argv, cwd)
        except verify_exec.WorkspaceError:
            return "exit_unexpected", None, "", "", {}
        output = verify_exec.trim(result.stdout + result.stderr)
        return verify_exec.classify(result, expect), result.exit, output, json.dumps(argv), {}

    def record(self, index: int, ac: str, state: str, code: int | None, facts: Mapping[str, str],
               command: str, output: str, **extra: str) -> Marker:
        """Post one result marker and note the check's new state; `extra` fields follow the host."""
        fields = {"block": self.block_key, "check": str(index), "ac": ac, "state": state,
                  "host": self.host, **extra}
        if code is not None:
            fields["exit"] = str(code)
        for name in ("rev", "tag"):
            value = facts.get(name)
            if isinstance(value, str) and re.fullmatch(forge_markers.VALUE, value):
                fields[name] = value
        extra = f"Command: {command}\n\n{_fence(output)}" if command else ""
        body = forge_markers.render(verify_issues.RESULT, fields, f"{ac} {state} on {self.host}.", extra)
        comment_id = forge_markers.post(self.slug, self.number, body)
        self.states[index] = state
        return forge_markers.parse({"id": comment_id, "body": body, "updated_at": self.ctx.now().isoformat()})

    # --- follow-up (P10) -----------------------------------------------------

    def follow_up(self, index: int, ac: str, key: Mapping[str, str], result: Marker, fenced: str) -> None:
        n = self.number
        claim = self.live(verify_issues.FOLLOWUP, key)
        if claim is not None:
            if claim.fields.get("host") != self.host:
                return
        else:
            won = self.write(verify_issues.FOLLOWUP, {**key, "host": self.host},
                             f"Filing the follow-up of {ac}.", key)
            if not won.won:
                return
            claim = won.winner
        tag_fields = {"issue": str(n), "block": self.block_key, "check": str(index)}
        found = self.filed(claim, tag_fields)
        if not found:
            forge_markers.ensure_label(self.slug, *FOLLOW_UP)
            body = forge_markers.render(
                verify_issues.FOLLOWUP_OF, tag_fields,
                f"Follow-up of #{n}: {ac} observed below target on {self.host}.", fenced)
            created = forge_markers.create_issue(
                self.slug, f"Follow-up: {ac} of #{n} observed below target", body, (FOLLOW_UP[0],))
            # The claim names a host, not a run, so another run on this host may have listed none
            # too and filed its own: the lowest number stands (CR-2).
            found = [*self.filed(claim, tag_fields), created]
        number = min(found)
        # Every other follow-up is closed here, not only the one this run created: a run that
        # stopped before closing its own duplicate leaves it for the next run to close (COR-003).
        # Closing a closed issue is a no-op, and the result is edited only after, so the follow-up
        # is never recorded while a duplicate is open.
        for extra in sorted(set(found) - {number}):
            forge_markers.close_issue(self.slug, extra, "not_planned")
        forge_markers.edit(self.slug, result.comment_id, forge_markers.with_fields(result, followup=str(number)))
        self.followups[index] = str(number)

    def filed(self, claim: Marker, tag_fields: Mapping[str, str]) -> list[int]:
        """The numbers of the trusted follow-up issues tagged with `tag_fields`, closed ones included."""
        found = []
        for issue in forge_markers.list_issues(self.slug, FOLLOW_UP[0], claim.updated_at):
            if issue.get("author_association") not in TRUSTED or isinstance(issue.get("number"), bool) \
                    or not isinstance(issue.get("number"), int):
                continue
            tag = forge_markers.parse({"id": issue["number"], "body": issue.get("body"),
                                       "updated_at": issue.get("updated_at")})
            if tag is not None and tag.kind == verify_issues.FOLLOWUP_OF and tag.fields == tag_fields:
                found.append(issue["number"])
        return found

    # --- owner prompts (issue 631) ---------------------------------------------

    def prompt(self, reason: str, index: int, fields: Mapping[str, str], sentence: str, extra: str,
               match_keys: Sequence[str] = ()) -> bool:
        """Post one prompt unless one of its identity was ever posted, ended ones included.

        The prompt is posted first and the comments re-read after; the smallest comment of the
        identity wins and a loser deletes its own, so racing runners and a pass holding an old
        listing leave exactly one prompt. `forge_markers.write` would not do: its contest ignores
        ended markers, so it would post again once the first prompt was answered and ended."""
        all_fields = {"reason": reason, "block": self.block_key, "check": str(index), **fields}
        match = {k: all_fields[k] for k in ("reason", "block", "check", *match_keys)}
        body = forge_markers.render(verify_owner.KIND, all_fields, sentence, extra)
        own = forge_markers.post(self.slug, self.number, body)
        reread = forge_markers.list_markers(self.slug, self.number, TRUSTED)
        first = min([m.comment_id for m in verify_owner.same_identity(reread, match)] + [own])
        if first != own:
            forge_markers.delete(self.slug, own)
            return False
        self.owner_posted = True
        self.prompted.add(index)
        return True

    def owner_form(self, index: int, check: Mapping, ac: str, key: Mapping[str, str], previous: Marker | None,
                   prev: str | None, due: verify_facts.Due, gate_reason: str) -> None:
        """What a due check only the owner can answer does this pass: ask once, then wait."""
        if "ask" in check["run"]:
            if verify_owner.prompts(self.markers, verify_owner.ASK, self.block_key, index):
                return self.line(index, ac, "pending", "owner_waiting")
            won = self.prompt(verify_owner.ASK, index, {"host": self.host}, f"{ac}: the owner's answer is needed.",
                              f"{check['run']['ask']}\n\n{verify_owner.box(verify_owner.ACCEPT)}\n"
                              f"{verify_owner.box(verify_owner.REJECT)}")
            return self.line(index, ac, "pending", "owner_asked" if won else "owner_waiting")
        self.line(index, ac, "pending", gate_reason)

    def answer(self, index: int, check: Mapping, ac: str, key: Mapping[str, str], previous: Marker | None) -> bool:
        """Record the owner's answer to a live ask prompt of this check; True when it added the check's line."""
        found = verify_owner.live_prompts(self.markers, (verify_owner.ASK,), self.block_key, index)
        prompt = next((p for p in found if verify_owner.answer(p, verify_owner.ACCEPT, verify_owner.REJECT)), None)
        if prompt is None:
            return False
        verdict = verify_owner.answer(prompt, verify_owner.ACCEPT, verify_owner.REJECT)
        if verdict == "ambiguous":
            self.line(index, ac, "pending", "owner_ambiguous")
            return True
        met = verdict == "yes"
        if check.get("mode", "assert") == "assert":
            state = "pass" if met else "fail"
        else:
            state = "hit" if met else "miss"
        lease = self.take_lease(ac, key)
        if lease is None:
            self.line(index, ac, "pending", "lost_contest")
            return True
        try:
            if not self.unchanged_since(index, previous):
                self.line(index, ac, "pending", "lost_contest")
                return True
            again = verify_owner.live_prompts(self.markers, (verify_owner.ASK,), self.block_key, index)
            if not any(p.comment_id == prompt.comment_id and verify_owner.answer(
                    p, verify_owner.ACCEPT, verify_owner.REJECT) == verdict for p in again):
                self.line(index, ac, "pending", "owner_waiting")
                return True
            if state == "fail" and check.get("on_fail", "label") == "label":
                forge_markers.ensure_label(self.slug, *FAILED)
                forge_markers.add_label(self.slug, self.number, FAILED[0])
            posted = self.record(index, ac, state, None, {}, "", "", owner=str(prompt.comment_id))
            forge_markers.end(self.slug, self.number, prompt.comment_id, "answered")
            self.line(index, ac, state, "owner_answered")
            if state == "miss":
                self.follow_up(index, ac, key, posted, "")
        finally:
            forge_markers.delete(self.slug, lease)
        return True

    def owner_sweep(self, closing: bool = False) -> None:
        """End the prompts that are settled and keep the `owner-action` label in step with the live ones.

        Settlement is judged against the block held now, never the one this pass ran: a pass
        that ran an older version must not end a prompt of the version now held. When the issue
        is closing, or is no longer listed because another run closed it, no question on it can
        be answered any more: every live prompt ends as `closed` and the label goes, so a closed
        issue never keeps an owner-action that no later pass will sweep."""
        if not (self.owner_posted or verify_owner.LABEL[0] in self.labels
                or any(m.kind == verify_owner.KIND for m in self.trusted)):
            return
        held_key, labels = self.fresh_held()
        closing = closing or labels is None
        labels = self.labels if labels is None else labels
        fresh = forge_markers.list_markers(self.slug, self.number, TRUSTED)
        gone: set[int] = set()
        for m in fresh:
            if m.kind != verify_owner.KIND or not forge_markers.is_live(m, fresh) \
                    or m.fields.get("reason") not in verify_owner.REASONS:
                continue
            why = verify_owner.settle_reason(m, fresh, held_key, FINAL) or ("closed" if closing else None)
            if why is not None:
                forge_markers.end(self.slug, self.number, m.comment_id, why)
                gone.add(m.comment_id)
        remaining = [m for m in fresh if m.kind == verify_owner.KIND and forge_markers.is_live(m, fresh)
                     and m.comment_id not in gone]
        name = verify_owner.LABEL[0]
        if remaining and name not in labels:
            forge_markers.ensure_label(self.slug, *verify_owner.LABEL)
            forge_markers.add_label(self.slug, self.number, name)
        elif not remaining and name in labels:
            forge_markers.remove_label(self.slug, self.number, name)

    # --- closing (P9) ----------------------------------------------------------

    def close(self) -> None:
        checks, states = self.block["checks"], self.states
        acs = [check["ac"] for check in checks]
        expired = list(dict.fromkeys(ac for ac, state in zip(acs, states) if state == "expired"))
        if expired:
            outcome, sentence = "expired", f"Not verified: {', '.join(expired)} expired."
        elif all(state in ("pass", "hit", "miss") for state in states) and all(
                index in self.followups for index, state in enumerate(states) if state == "miss"):
            verified = [ac for ac in dict.fromkeys(acs)
                        if all(state in ("pass", "hit") for a, state in zip(acs, states) if a == ac)]
            outcome = "verified"
            sentence = f"Verified: {', '.join(verified) if verified else 'none'}." + "".join(
                f" Observed below target: {acs[i]} (follow-up #{self.followups[i]})."
                for i, state in enumerate(states) if state == "miss")
        else:
            return
        block = {"block": self.block_key}
        if not self.write(verify_issues.CLOSED, {**block, "outcome": outcome}, sentence, block).won:
            return
        if self.conclude(outcome == "verified"):
            self.line(None, None, "closed", "verified" if outcome == "verified" else "not_verified")

    def fresh_held(self) -> tuple[str | None, set[str] | None]:
        """This issue's held block key and label names from a fresh listing, `(None, None)` when
        the issue is no longer listed."""
        for node in list_held(self.slug):
            if node.get("number") == self.number:
                nodes = (node.get("comments") or {}).get("nodes")
                if not isinstance(nodes, list):
                    raise ForgeError("payload_invalid", "issue node has no comments")
                held = verify_issues.select(verify_issues.comments_from_graphql(nodes))
                labels = (node.get("labels") or {}).get("nodes")
                names = {n["name"] for n in labels if isinstance(n, dict) and isinstance(n.get("name"), str)} \
                    if isinstance(labels, list) else set()
                return (held.key if held is not None else None), names
        return None, None

    def current(self) -> bool:
        """Whether the block this pass ran is still the issue's held block, read afresh."""
        return self.fresh_held()[0] == self.block_key

    def conclude(self, verified: bool) -> bool:
        """Finish the issue only if its held block is still the one this pass ran: an owner who
        replaced or edited the block while a check ran has checks nobody has run yet (COR-002)."""
        if not self.current():
            self.line(None, None, "skipped", "block_changed")
            return False
        if not self.report:
            self.owner_sweep(closing=True)
        self.finish(verified)
        return True

    def finish(self, verified: bool) -> None:
        """The idempotent finishing steps: the one that unlists the issue comes last."""
        if verified:
            forge_markers.remove_label(self.slug, self.number, FAILED[0])
            forge_markers.close_issue(self.slug, self.number, "completed")
            forge_markers.remove_label(self.slug, self.number, NEEDS)
        else:
            forge_markers.close_issue(self.slug, self.number, "not_planned")
