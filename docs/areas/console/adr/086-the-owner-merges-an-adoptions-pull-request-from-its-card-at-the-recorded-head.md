# ADR-console-086 — The owner merges an adoption's pull request from its card, at the recorded head

- **Status:** accepted
- **Decided in:** #1338

## Context

ADR-console-030 D10 had the console open an adoption's pull request and leave the merge to the owner on the forge ("the console never merges"). The owner then left the console, merged there, and came back for the registration the console runs once the merge lands (ADR-console-028 D10). The card only linked to the pull request, said nothing about a failed check, a branch that held commits the console did not push, or a pull request someone else opened, and a pull request closed while another registration was shown had no card at all.

## Decision

**D1. Merge is pinned to the recorded head.** `GitHubForge.merge_pull_request(slug, number, head)` is `gh api -X PUT repos/<slug>/pulls/<n>/merge -f sha=<head> -f merge_method=merge`, with the head the console recorded. The forge refuses a moved head (409) and an unmergeable pull request (405), so the forge's branch protection still keeps merge safety. `merge` matches this repository's own lifecycle (`gh pr merge --merge --match-head-commit`). This replaces ADR-console-030 D10 for this one card.

**D2. A failed check is read from the full result.** A pull request is `failing` when it is open, its `mergeable_state` is `blocked` and its head has a failure in the full result: any check run on any page (`gh api --paginate --slurp`) concluded `failure`, `timed_out`, `cancelled` or `action_required`, or the head's combined commit status is `failure` or `error`. A blocked pull request with only pending or passing checks stays `open` and raises no card. The adoption poll reads it again while `failing`, and Apply is refused while it is `failing` as while it is `open` or `ready` (ADR-console-030 D7).

**D3. The card set.** The adoption card is listed for an opened adoption whose pull request is `ready` or `failing`, `open` at a read head other than the recorded commit, or `closed` while a registration of another root is shown (the shown registration's own `Apply it again` card already says it was closed). Merge is offered only when `approve.merge_refusal` is None: the step is `opened`, the pull request is `ready`, the console made it (`created`) and its read head equals the recorded commit. A closed card stays until a registration of that root is shown.

**D4. The route.** `POST /api/adoption-merge` is a page write and owner-only (ADR-console-008). Its body is exactly `{"plan_id", "number", "commit"}`. The route refuses, in order, with `MERGE_UNAVAILABLE`, `register.STOPPING`, `MERGING`, `STALE_CARD` (the folded adoption's number or commit differ from the card's, so a card of a replaced pull request merges nothing), then the `merge_refusal` words. The merge is one forge call bounded by `forge_api.TIMEOUT` and cancelled by the stop event, outside the ingest lock, with a per-plan mark that refuses a second click; `close` waits until no merge is in flight, through recording and dispatch, before it closes the log. On success the service appends the `merged` pull row and dispatches the registration (ADR-console-028 D10).

**D5. The head is unknown until read.** An `opened` step folds `pull_head` None; a pull row sets `pull_head` to its `head`, which is None when the row has none (an earlier release's) or the forge's head was not 40 hex. A replayed legacy row or a malformed reading offers no Merge until a later valid matching reading. The poll appends a row when the state or the head differs.

**D6. Obsolete readings are rejected.** The service keeps a per-plan mark bumped on every pull row it appends; the poll takes the mark before its read and records the reading only while it is unchanged, and nothing is recorded over `merged`. A poll that read `ready` before a click recorded `merged` cannot restore the card.

**D7. Console creation is recorded.** The opened step's `pull_request` gains `created: bool`: true when `open_pull_request` answered, or when a found pull request's title is `approve.title(name)` and its body carries `approve.signature(plan_id)` (the console's own text, so a re-find after a lost create answer still counts); otherwise false. A `pull_request` without `created` (an earlier release's) is not established: no Merge.

**D8. Only what the forge showed is recorded.** After a failed merge call the re-read's head is recorded as read, and the click is acknowledged only when the re-read is `merged` at the recorded commit. `merged` at another head or an unknown head is recorded and refused in plain words (`MERGED_ELSEWHERE`); the merged adoption still registers as an externally merged one does.

## Considered options

- A rule in the lifecycle guard for the console-opened pull request: rejected by the sprint brief; the guard stays unchanged, and the console's `gh` calls are its own subprocesses that the guard never sees.
- Merging on the forge by hand (today): the owner leaves the console and the card cannot say why a pull request is not ready.
- Reading only the first check-run page: rejected; a failure on a later page would hide.

## Consequences

- Amends ADR-console-030 D6 (what the card says and when it is listed), D7 (Apply is refused while the pull request is failing) and D10 (the owner merges from the card).
- The lifecycle guard is unchanged.
- Rollback: a base console reads none of this change's opened steps that carry `created` (its step row wants a `pull_request` of exactly `number` and `url`), skips pull rows whose state is `failing`, and ignores `head`; a resumed approval there finds the open pull request and records it again in the base form.
- Related: ADR-console-008, ADR-console-028, ADR-console-030.
