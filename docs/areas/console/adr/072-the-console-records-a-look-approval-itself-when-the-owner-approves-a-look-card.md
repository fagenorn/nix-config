# ADR-console-072 — The console records a look approval itself when the owner approves a look card

- **Status:** accepted
- **Decided in:** #1260

## Context

On 17 Nov the owner approved a look card and the approval never reached the issue: the delivery's agent session ran `look-approval post` and the automatic safety check refused that post, so the owner's act was dropped on the way to the tracker. The agent was carrying the owner's own decision, and a refusal of the agent was a refusal of the owner.

## Decision

**D1. The card names its look.** A round question may carry `look` `{issue, pr, head, approve}`: the issue, the pull request, the full 40-hex head its pictures show and the exact text of the one option that approves that head. Only that option, picked as an option and not typed words, records an approval; every other answer to a look card reaches the manager as before.

**D2. Approve only.** The console records `answer=approved`. The other approving answer, approve with one fix, keeps the delivery's agent-written post (`look-approval post --answer fix`), because a round answer is an option or the owner's words, never both, so the card cannot carry a fix with its words yet. That is a known gap against "no agent session writes an approval", tracked by #1261.

**D3. The head is read first.** The console reads the pull request before it posts. When the pull request is not open or its head is not the card's head, it records nothing but the outcome `moved`, answers 409 with the plain reason and leaves the question open with that line on the card.

**D4. One kept record kind, schema 11.** `look.recorded` (outcome `moved`, `posted` or `failed`) joins the kept kinds, so the event log goes to schema 11 with the trigger rebuilt from `KEPT_KINDS` and every row kept.

**D5. The manager hears an approval only once it is recorded.** The answered row of an approving answer carries the look, and its message is held, not unread and not nudged, until a `look.recorded` of outcome `posted` names it. No read or nudge watermark consumes a held approval, so it is delivered exactly once after the post, on replay too.

**D6. A failed post stays with Retry.** A failed post is recorded as `failed` with its reason, the card stays in the owner's open items with that reason and offers Retry. A retry first looks for a trusted marker already posted with that message id and head, so it never posts twice. A post a stopped console left without an outcome reads failed at the next start.

**D7. The delivery reads, never writes, an approve.** The approve resume runs `look-approval status` and lands only on `approved`. The global look-before-merge standard's stop says the owner has not recorded the approval, because it is read in projects with no console; the owner records it wherever they look, never the session.

**D8. Every forge failure is logged first.** The console logs each head-read and post failure, and each retry, with the original error before the plain words reach the card or the answer.

## Consequences

- ADR-guard-010 is unchanged: the marker's format and who is trusted stay as they were, and the console posts the same marker `look-approval post` posts.
- The console's `gh` must be signed in as the owner, because only an owner or member marker counts.
- Each approval costs one pull request read and up to two comment listings.
- The page change was held for the owner's look at 1440 and 480 px.
- Related: ADR-guard-010, ADR-console-019, ADR-console-038, ADR-console-054.
