"""The console's verdict on an approved action a manager's session is about to run.

A `POST /api/permit` body with a `nonce` is the signed body of `action_card.ActionPermitRequest`:
`{"sprint_id", "phase", "session_id", "tool_use_id", "command_sha256", "nonce", "auth"}`, which carries no
secret and no command text. `permit_secret(sprint_id, auth, signed)` (the ingest lock; an unknown sprint
is 409, a sprint with no secret file or an `auth` that is not `permit.action_request_auth` of the body's
`signed_bytes` under the secret 403) returns the secret, and `reply` calls `permit_action` (phase `judge`)
or `permit_action_landed` (`landed`) with it. A judge reply is 200 `{"decision", "reason", "mac"}`, `mac`
being `permit.action_reply_mac` for the request's nonce, which the hook checks before it honours the
decision; a landed reply is `{"recorded": <bool>}`.

`permit_action` holds the ingest lock for all of it: the secret and the manager's session as `permit`
checks them (`_permit_refusal`), then `permit.judge_action` over the sprint's questions at the console's
time; a command no card names has no decision and no row, otherwise the decided verdict is appended as a
`permit.judged` row (verb `action`, repo null, target `{"round", "index"}`) before the lock is released,
which folds the card as used, so an allow is never given twice for one approval. An allowed action is also
remembered in memory with the console's clock, and `permit_action_landed` appends one `permit.landed` row
`{"sprint_id", "session_id", "tool_use_id", "repo": null, "verb": "action", "target": {"round", "index"}}`
only for a card whose command has the digest and an allow of that same tool call at most
`service.PERMIT_LANDED_SECONDS` ago; otherwise it is False and appends nothing. Only the signed body decides
an action: `permit` for a command that names no granted verb still has no decision and no row.

`ActionPermit` is the mixin `service.ConsoleService` takes these methods from; it reads the service's
`_ingest`, `_sprints`, `_sprint_secrets`, `_permit_allows`, `_clock`, `_now`, `_apply` and `log`.
"""

import hmac

from agent_tools.console import permit, sprints
from agent_tools.console.action_card import ActionPermitRequest
from agent_tools.console.event_log import PERMIT_LANDED

PERMIT_LANDED_SECONDS = 30 * 60


def reply(console, request: ActionPermitRequest) -> dict:
    """The JSON the permit endpoint answers an action request with."""
    secret = console.permit_secret(request.sprint_id, request.auth, request.signed)
    if request.phase != "judge":
        return {"recorded": console.permit_action_landed(
            request.sprint_id, secret, request.session_id, request.tool_use_id, request.digest)}
    verdict = console.permit_action(
        request.sprint_id, secret, request.session_id, request.tool_use_id, request.digest)
    return {"decision": verdict.decision, "reason": verdict.reason,
            "mac": permit.action_reply_mac(secret, request.sprint_id, request.nonce, request.digest,
                                           verdict.decision, verdict.reason)}


class ActionPermit:
    def permit_secret(self, sprint_id: str, auth: str, signed: bytes) -> str:
        """The sprint's secret, when `auth` is the hook's HMAC under it of `signed` (the secret is never sent)."""
        with self._ingest:
            if sprint_id not in self._sprints:
                raise sprints.Refused(sprints.NOT_OPEN)
            expected = sprints.read_secret(self._sprint_secrets, sprint_id)
            if expected is None or not hmac.compare_digest(
                    permit.action_request_auth(expected, signed).encode(), auth.encode()):
                raise sprints.SecretRefused(sprints.SECRET_REFUSED)
            return expected

    def permit_action(self, sprint_id: str, secret: str, session_id: str, tool_use_id: str,
                      digest: str) -> permit.Verdict:
        """The verdict on a command an owner-only card may have approved, by its digest."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            verdict = permit.judge_action(digest, sprint.questions, self._now())
            if verdict.decision is None:
                return verdict
            verdict = self._permit_refusal(sprint, session_id, permit.ACTION) or verdict
            if verdict.decision == permit.ALLOW:
                self._permit_allows[(sprint_id, session_id, tool_use_id, permit.ACTION,
                                     verdict.target["round"], verdict.target["index"])] = self._clock()
            return self._permit_record(sprint, session_id, tool_use_id, None, verdict)

    def permit_action_landed(self, sprint_id: str, secret: str, session_id: str, tool_use_id: str,
                             digest: str) -> bool:
        """Record an approved action the console allowed and the manager's session ran; False records nothing."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            for question in sprint.questions:
                if question.action is None or permit.command_digest(question.action.command) != digest:
                    continue
                judged = self._permit_allows.get((sprint_id, session_id, tool_use_id, permit.ACTION,
                                                  question.round_id, question.index))
                if judged is None or self._clock() - judged > PERMIT_LANDED_SECONDS:
                    continue
                self._apply(self.log.append([(PERMIT_LANDED, sprint.project_id, {
                    "sprint_id": sprint_id, "session_id": session_id, "tool_use_id": tool_use_id,
                    "repo": None, "verb": permit.ACTION,
                    "target": {"round": question.round_id, "index": question.index}})]))
                return True
            return False
