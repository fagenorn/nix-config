# ADR-console-074 — The console records a look approval itself when the owner approves a look card

- **Status:** accepted; amended by ADR-console-092
- **Decided in:** #1260

## Context

On 17 Nov the owner approved a look card and the approval never reached the issue: the delivery's agent session ran `look-approval post` and the automatic safety check refused that post, so the owner's act was dropped on the way to the tracker. The agent was carrying the owner's own decision, and a refusal of the agent was a refusal of the owner.

## Decision

**D1. The card names its look.** A round question may carry `look` `{issue, pr, head, approve}`: the issue, the pull request, the full 40-hex head its pictures show and the exact text of the one option that approves that head. Only that option, picked as an option with no words of the owner's beside it, records an approval; every other answer to a look card reaches the manager as before. The open card carries the console's own line naming that option, the head and the pull request it approves, so the manager's wording of an option cannot hide that choosing it approves. The approving option is never one of the card's `needs_words`: the option takes no words, so such a card could never be approved and is refused when the manager asks it.

**D2. Approve only.** The console records `answer=approved`. The other approving answer, approve with one fix, keeps the delivery's agent-written post (`look-approval post --answer fix`). A round answer can carry an option and the owner's words together (ADR-console-072), and the owner's words beside the approving option are a fix in the look standard's terms, not an approval of the head as it stands: such an answer is an ordinary answer, records nothing and reaches the manager as it is, and the console never writes `approved` for it. The page also never starts the approving option picked, whatever the manager recommends, so an answer typed in words alone is words alone. That is a known gap against "no agent session writes an approval", tracked by #1261.

**D3. The head is read first.** The console reads the pull request before it posts. When the pull request is not open or its head is not the card's head, it records nothing but the outcome `moved`, answers 409 with the plain reason and leaves the question open with that line on the card. A pull request found closed or moved only after the answer was kept (the head changed between the first read and the post, or before a retry) is recorded as `moved` naming that answer: the fold takes the answer back, the manager never receives it (it receives the stale-card message of D12 instead), and the question is open again in the `moved` state for the manager to replace or withdraw; a retry that finds this is refused with the same plain reason, because no failed state could ever be left.

**D4. One kept record kind, schema 11.** `look.recorded` (outcome `moved`, `posted` or `failed`) joins the kept kinds, so the event log goes to schema 11 with the trigger rebuilt from `KEPT_KINDS` and every row kept.

**D5. The manager hears an approval only once it is recorded.** The answered row of an approving answer carries the look, and its message is held, not unread and not nudged, until a `look.recorded` of outcome `posted` names it. No read or nudge watermark consumes a held approval, so it is delivered exactly once after the post, on replay too. The sprint panel leaves a held approval out, because it was never offered to the manager and is neither sent nor unpicked-up, and a nudge row names the messages it covered, so an approval released while a nudge ran is nudged for on its own.

**D6. A failed post stays with Retry.** A failed post is recorded as `failed` with its reason, the card stays in the owner's open items with that reason and offers Retry. A retry first looks for a trusted marker already posted with that message id and head, so it never posts twice, a marker a trusted end marker withdrew included. Every attempt, an automatic retry too, reads the pull request again before it posts and posts nothing for a head that is not open and the card's, and the answer's row keeps the repository, which the retry posts to whatever the checkout's origin is now. A post a stopped console left without an outcome reads failed at the next start. A retry is refused once the sprint has ended or stopped, and every attempt, an automatic retry after a backoff included, first finds the sprint still taking questions, else it posts nothing and records `failed`.

**D7. The delivery reads, never writes, an approve.** The approve resume runs `look-approval status` and lands only on `approved`. The global look-before-merge standard's stop says the owner has not recorded the approval, because it is read in projects with no console; the owner records it wherever they look, never the session.

**D8. Every forge failure is logged first.** The console logs each head-read and post failure, and each retry, with the original error before the plain words reach the card or the answer.

**D9. The repository is the card's.** The console binds the project's repository when the card is issued (`look_repo` on the round's `questions.asked` row) and reads and posts to that repository only; a checkout whose origin changed afterwards cannot send an approval to another repository that happens to have the same pull request number and head, and a card issued without a known repository records nothing.

**D10. The head is read again after the post.** The tracker cannot make the read of the head and the post of the marker one step, so after the marker is posted the console reads the pull request once more. A pull request found closed, merged or at another head is recorded as `moved` with the answer's id like any other moved finding (D3), and a failed final read is recorded as `failed` with Retry, which finds the marker already posted and reads again. The manager hears the answer only for a head that was still the card's at that last read, and a marker already posted for a head found moved then is ended with a trusted `end` marker before `moved` is recorded, so no later head that keeps the approved changes can pass the merge guard on it; an end that fails is a failed post whose Retry reads the head again and ends it. A push landing after that last read still leaves a marker that names the head the owner looked at, which the merge guard judges against the head it then sees (ADR-guard-010).

**D11. A look card carries its pictures, and a sprint waits for its approval.** A question with a `look` is refused unless it carries a picture marked `before` and one marked `after`, whatever its words say, because the owner approves what the pictures show. A sprint whose manager reported done is not ended while an answered look card has an approval still held or failed, so Retry stays offered until the approval is posted. Such an answered card counts as waiting on the owner, so the sprint reads waiting, not done, with no idle nudge, until it is posted.

**D12. A stale card tells the manager.** Whenever the owner's approval finds the head gone (D3, D10), the sprint gains one `look-moved` message that names the card's round and question, the head it showed and the head now found (or that the pull request is closed or merged), and the manager is nudged, because the open card would otherwise keep an idle manager from ever being woken. The owner's panel does not list it, since the card already says why; a repeat for the same finding adds none while the first is unread.

## Consequences

- ADR-guard-010 is unchanged: the marker's format and who is trusted stay as they were, and the console posts the same marker `look-approval post` posts.
- The console's `gh` must be signed in as the owner, because only an owner or member marker counts.
- Each approval costs one pull request read and up to two comment listings.
- The page change was held for the owner's look at 1440 and 480 px.
- Related: ADR-guard-010, ADR-console-019, ADR-console-038, ADR-console-054.
