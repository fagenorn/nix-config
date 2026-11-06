"""One runner pass over the held verification issues of a repository (issue 630, P1-P18).

`pass_issue` takes one GraphQL issue node and, for the trusted block it holds (P3), decides per
check whether it is this host's and due, runs it through `verify_exec` (never here), records one
result marker per state change (P4), labels failures (P16), files one follow-up issue per observed
miss under a claim (P10) and closes the issue once through a contested `verify-closed` marker
(P9). Every forge call goes through `forge_markers` and every marker write names `TRUSTED`
associations, so a marker by any other author neither wins a contest nor ends one (P3). "Now" is
only `Context.now()`, the forge's clock (P6, P7).

Every forge write is ordered so that the step that takes the issue out of the listing, or makes the
next pass skip work, comes after the step it would strand; a `ForgeError` ends the pass with a
`forge_error` line and the next pass finishes the work.
"""
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from agent_tools import forge_markers, verify_block, verify_exec, verify_facts, verify_issues
from agent_tools.forge_markers import ForgeError, Marker

NEEDS = "needs-verification"
FAILED = ("verification-failed", "B60205")
FOLLOW_UP = ("verification-follow-up", "FBCA04")
QUERY = (
    'query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) '
    '{ issues(first: 100, states: OPEN, labels: ["needs-verification"], '
    'orderBy: {field: CREATED_AT, direction: ASC}) { nodes { number labels(first: 50) { nodes { name } } '
    'comments(last: 100) { nodes { databaseId authorAssociation body createdAt updatedAt } } } } } }'
)
FINAL = ("pass", "hit", "miss", "expired")
PENDING_OUTCOMES = ("not_yet", "timeout", "exit_unexpected")
DEFAULT_EXPIRY_DAYS = 21
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
        self.markers: list[Marker] = []
        self.states: list[str | None] = []
        self.followups: dict[int, str] = {}

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
        held = verify_issues.select(verify_issues.comments_from_graphql(nodes))
        if held is None:
            return self.line(None, None, "skipped", "no_block")
        if held.block is None or not verify_block.lint_block(held.block, refs=self.refs)["ok"]:
            return self.line(None, None, "skipped", "block_invalid")
        self.block, self.block_key, self.markers = held.block, held.key, held.markers
        closed = self.live(verify_issues.CLOSED, {"block": self.block_key})
        if closed is not None and closed.fields.get("outcome") in ("verified", "expired"):
            verified = closed.fields["outcome"] == "verified"
            if not self.report:
                self.finish(verified)
            return self.line(None, None, "closed", "verified" if verified else "not_verified")
        bindings = self.project.bindings
        self.ctx = verify_facts.Context(self.slug, self.project.root, bindings["vcs"]["default_branch"],
                                        bindings["deploy"], bindings["tracker"], self.markers)
        checks = self.block["checks"]
        self.states = [None] * len(checks)
        for index, check in enumerate(checks):
            self.check(index, check)
        if not self.report:
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
        bound = check["host"]
        shared = bound == "any" or isinstance(bound, list)
        if not (bound == self.host or bound == "any" or (isinstance(bound, list) and self.host in bound)):
            return self.line(index, ac, "pending", "not_this_host")
        gate = verify_exec.gate(check, self.project.bindings["workflow"]["verification"])
        if not gate.runnable:
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
        if shared:
            claimed = self.live(verify_issues.RUN, key)
            if claimed is not None:
                if claimed.fields.get("host") != self.host:
                    return self.line(index, ac, "pending", "lost_contest")
            elif not self.write(verify_issues.RUN, {**key, "host": self.host},
                                f"{self.host} runs {ac}.", key).won:
                return self.line(index, ac, "pending", "lost_contest")
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
               command: str, output: str) -> Marker:
        """Post one result marker and note the check's new state."""
        fields = {"block": self.block_key, "check": str(index), "ac": ac, "state": state,
                  "host": self.host}
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
        if found:
            number = min(found)
        else:
            forge_markers.ensure_label(self.slug, *FOLLOW_UP)
            body = forge_markers.render(
                verify_issues.FOLLOWUP_OF, tag_fields,
                f"Follow-up of #{n}: {ac} observed below target on {self.host}.", fenced)
            created = forge_markers.create_issue(
                self.slug, f"Follow-up: {ac} of #{n} observed below target", body, (FOLLOW_UP[0],))
            # The claim names a host, not a run, so another run on this host may have listed none
            # too and filed its own: the lowest number stands and any other is closed, so every
            # run converges on one open follow-up whatever the interleaving (CR-2).
            number = min([*self.filed(claim, tag_fields), created])
            if number != created:
                forge_markers.close_issue(self.slug, created, "not_planned")
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
        self.finish(outcome == "verified")
        self.line(None, None, "closed", "verified" if outcome == "verified" else "not_verified")

    def finish(self, verified: bool) -> None:
        """The idempotent finishing steps: the one that unlists the issue comes last."""
        if verified:
            forge_markers.remove_label(self.slug, self.number, FAILED[0])
            forge_markers.close_issue(self.slug, self.number, "completed")
            forge_markers.remove_label(self.slug, self.number, NEEDS)
        else:
            forge_markers.close_issue(self.slug, self.number, "not_planned")
