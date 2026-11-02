# Keepalive: cap pings after an end_turn reply — issue 502

Design for https://github.com/fagenorn/nix-config/issues/502 (parent
https://github.com/fagenorn/nix-config/issues/432). Base: `4e944cb4`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#423 Dn" cites
`2026-10-25-issue-423-cache-keepalive-design.md` and "#501 Dn" cites
`2026-11-02-issue-501-keepalive-unmarked-side-requests-design.md`.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a new keepalive_end reason value to the documented cache-proxy log contract (python/README.md, END_REASONS)"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "new per-conversation in-memory state written in Keepalive._done under the shared lock, read by the tick thread"}, "open_design_questions": {"value": "doubt", "evidence": "the cap value and the end-reason name are left to the implementer (agent-choose)"}, "criteria_shape": {"value": "hit", "evidence": "the second criterion is 7 days of mbp log evidence after switch, not a deterministic code check"}}, "paths": ["python/agent_tools/cache_keepalive.py", "tests/test_cache_keepalive.py", "python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

`cache-proxy --keepalive` pings an idle subagent conversation every 270 s
while its session stays active, for up to 60 minutes after its last thread
request (#423 D8, D10). #423 D17 accepted that a subagent that has finished
for good is pinged as long as one that waits to be woken, because the proxy
cannot tell the two apart. The bill for that is now known. On mbp over
2026-10-26..11-01 the issue counts $260 of pings. Of that, $191 went to
conversations whose last reply was `end_turn` and that were never resumed,
and $116 of it pinged for the full hour. Only $46 of all pings kept a cache
that was later used.

This spec re-measured the same log (method in D2). Its totals differ from the
issue's because it prices with `model_pricing.usage_cost`, but the shape is
the same. Idle periods that followed an `end_turn` reply held $277.62 of the
$333.73 of pings in ended periods. 456 of them sent 13 pings and were never
resumed. Of the 392 that were resumed, 236 (60%) resumed within two pings. A
conversation pending on `tool_use` is a different case. It is mid-turn, a
tool runs, and its result comes back (#423 D8).

## Solution

A conversation whose *last reply* (D1) ended the turn gets at most
`END_TURN_PINGS` pings, which is 2 (D2), in one idle period. At its next due
time the keepalive ends it with the new reason `end_turn_cap` (D4), and the
candidate and its held headers are cleared. A resume before that due time
still ends the period `resumed`, and a new thread request starts a new count
(D3). A conversation pending on `tool_use` keeps today's full window, and so
does a conversation whose last reply had any other stop reason, or none. The
due time, the window, the outcome set, the proxy seam, every other log field
and the Nix service do not change.

## Acceptance criteria

| AC | Kind | Criterion | Measured by |
|----|------|-----------|-------------|
| AC1 | code | A conversation whose last reply is `end_turn` receives at most the capped number of pings and then ends with its own end reason. A conversation pending on `tool_use` keeps being pinged up to the window | § Test seams in `tests/test_cache_keepalive.py` under `just agent-workflow-tests`. Cases 1, 4, 5 and 6 fail on the current code. Case 2 is the `tool_use` half, and cases 3 and 7 pin D1 and D3 |
| AC2 | evidence | Over 7 days on mbp, no conversation whose last reply was `end_turn` receives more than `END_TURN_PINGS` pings in an idle period | D7's reading of `~/Library/Logs/claude-cache-proxy.log`, no sooner than 7 days after the first `just switch` that includes this change. Post-merge evidence (D7) |

## Decisions

### The last reply (D1)

A conversation's **last reply** is the `stop_reason` of the 2xx, `complete`,
streamed response to its newest thread request. This is the rule that already
decides a pending tool: `_done` records it under the same guard (2xx,
`complete`, track sequence equal to the record's sequence) and in the same
place. `observe` clears it for every thread request, together with the
pending tool. A side request (`no_tail_mark`) never sets or clears it,
because its track has no sequence (#501 D3). A thread request whose response
is not 2xx, or not `complete`, or has no stop reason leaves the conversation
with no last reply.

The cap applies only when the last reply is `end_turn`. `tool_use` (pending a
tool), any other stop reason (`max_tokens`, `stop_sequence`, `pause_turn`,
`refusal`) and no last reply all keep today's behaviour. In the measured week
subagent thread replies were 2,743 `end_turn`, 48,830 `tool_use`, 339 with
no stop reason and none of any other kind. The 28 ended periods with no
recorded last reply held $4.05 of pings.

The state is one more per-conversation field. It is written by `observe` and
`_done` and read by `tick`, all under the keepalive's one lock and with no
I/O held (#423 D2). The record's prune rule does not change, because the
field matters only while the record holds a candidate.

### The cap (D2)

`END_TURN_PINGS = 2` is a module constant next to `DUE_AFTER` and `WINDOW`.
Its comment gives the reason. Two pings keep the reply's cache entry about 14
minutes past the reply's send (2 × 270 s plus the 5-minute lifetime), and the
measured week's best net saving came at 2. The comment cites this decision.

The measurement read the mbp proxy log for 2026-10-26..11-01. The log holds
no lines for 10-28 and 10-29. Each idle period is a `keepalive_end` line. Its
last reply is the `stop_reason` of the conversation's newest thread-request
line before the period's first ping. Each ping is priced with
`model_pricing.usage_cost`. A resume that a cap of N would lose is an
`end_turn` period that ended `resumed` after more than N pings, and it is
valued at its last ping's prefix × (5-minute write − read). The net is the
pings cut minus the resumes lost:

| Cap | Pings cut | Resumes lost | Their saving | Net |
|-----|-----------|--------------|--------------|-----|
| 0 | $277.62 | 390 | $266.67 | $10.94 |
| 1 | $235.50 | 232 | $151.59 | $83.91 |
| **2** | **$201.00** | **154** | **$97.93** | **$103.07** |
| 3 | $171.48 | 110 | $69.81 | $101.67 |
| 4 | $144.64 | 75 | $47.26 | $97.38 |
| 6 | $98.60 | 16 | $10.65 | $87.96 |

2 and 3 are within noise of each other. 2 wins on 10-26..10-27 ($54.32
against $51.60), and 3 wins on 10-30..11-01 ($50.07 against $48.75). 2 is
taken because the issue asks for a small number, and because each further
ping holds the credential for 270 s more for no measured gain.

### Where the cap applies (D3)

At a due time the order is: `ceiling`, then `session_idle`, then the cap,
then the ping. The cap ends the conversation when its last reply is
`end_turn` and its idle period already holds at least `END_TURN_PINGS` pings.
So `end_turn_cap` means exactly "the old rules would have pinged here". A
session that goes idle at the same due time still ends `session_idle`.

The count is the period's existing ping count. It covers every ping built
since the last thread request, including any sent while the reply was still
streaming (#423 D19), and every end resets it, `resumed` included. A
conversation that resumes and ends its turn again therefore gets up to two
pings after each reply.

The end comes at the due time after the last allowed ping, not when that
ping settles. A thread request that arrives after the last allowed ping but
before that due time still ends the period `resumed` with its count. That is
the line #423 D11 uses to tell pings that paid off from pings that were
wasted.

### The end reason (D4)

`end_turn_cap` joins `END_REASONS`, and `_log_end` keeps rejecting any reason
outside the tuple. Its `keepalive_end` line carries today's fields:
`conversation`, `reason`, `pings` and `idle_s`. `pings` equals the cap,
unless pings sent while the reply streamed already went past it (§ Accepted
costs). Like every end except `resumed`, it clears the candidate and the
headers it holds (#423 D24). No other log line or field changes.

### Relation to #423 (D5)

The cap refines #423 D10's stop rules and narrows D17's accepted waste. A
conversation whose turn ended now costs at most two pings, where before it
was pinged as long as its session stayed active, up to 60 minutes. #423 D22
recorded a different lever: ping an ended turn only while one of its own
children is active. That rule stays unbuilt, because the issue asks for a
cap. D22's trigger is not what decided this: in the measured week the
rewrites that resumed periods avoided ($720) still outweighed the $248 of
pings to `end_turn` periods that never resumed. The cap removes most of that
waste and keeps the resumes that come within about 14 minutes (D2).

### Accepted costs

- A conversation whose turn ended and that is woken more than about 14
  minutes after its reply pays a cache rewrite that a ping might have
  avoided. In the measured week that is 154 of 392 resumed `end_turn` periods,
  $97.93 of avoided rewrites given up for $201.00 of pings cut (D2).
- A reply that streams past two due times is pinged while it streams (#423
  D19). If it then ends `end_turn`, its period ends at the next due time
  holding more pings than the cap, and AC2 would report that as a breach. In
  the measured week no `end_turn` reply streamed for longer than 270 s.

### Docs

The `--keepalive` paragraph of `python/README.md` § `cache-proxy` gains three
things: the last-reply definition, next to the pending-tool one; the cap in
the due-time sentence ("with `end_turn_cap` when its last reply was
`end_turn` and its idle period already holds at least two pings"); and
`end_turn_cap` in the list of end reasons.

`home/common/claude-code/README.md` § Cache proxy rewrites its accepted-cost
sentence, which says a finished subagent is pinged for up to 60 minutes. It
will say that a subagent whose turn ended gets at most two pings (about 14
minutes of cache), so one woken later pays a rewrite, while a subagent
pending a tool keeps the 60-minute window. The `keepalive_end` lines measure
both.

CLAUDE.md and AGENTS.md do not change. Neither do the #423 spec and
`docs/spikes/cache-proxy-keepalive.md`, which are point-in-time records.

## Test seams

Every case drives `Keepalive` directly through `KeepaliveCase` in
`tests/test_cache_keepalive.py`, on its fake clock, with `tick` and `send`
against the fake upstream (#423 D12, D25; #501 D4). `busy_main()` keeps the
session active, and `ends()` and the `ping` events are the assertions. No
case reads `_Conversation` fields (D6). Times are seconds after P's tracked
request, which ends `end_turn` unless a case says otherwise.

1. **AC1, the issue's demo.** Fails today. The dues at 270 and 540 each
   ping P, and both pings answer 2xx. At 810 no ping is built, and
   `keepalive_end` reads (P, `end_turn_cap`, 2) with `idle_s` 810.0. A due at
   1080 builds nothing and writes no line. Upstream received two requests.
2. **AC1, `tool_use` keeps the window.** This rewrites the existing
   `test_pings_repeat_while_the_session_is_active_and_stop_at_the_ceiling`,
   whose P ends `end_turn` today and would be capped. P now ends `tool_use`:
   13 pings, then (`ceiling`, 13, 3780.0). It passes today and after.
3. **Other stop reasons are not capped.** A pin. P ends `max_tokens`, and the
   dues at 270, 540 and 810 each ping P, with no `keepalive_end` line.
4. **The count is per idle period.** Fails today. After pings at 270 and
   540, P's next tracked request at 600 ends the period `resumed` with 2. Its
   reply also ends `end_turn`, so P is pinged at 870 and 1140 and ends
   `end_turn_cap` with 2 at 1410.
5. **A side request never lifts the cap.** Fails today. After the ping at
   270, a side request from P (`document(tail_mark=False)`) completes with
   `tool_use` at 279. P is pinged at 540 and ends `end_turn_cap` with 2 at
   810.
6. **Pings while the reply streams count.** Fails today. P's response starts
   2xx and keeps streaming. It is pinged at 270, 540 and 810, then completes
   `end_turn`, and at 1080 it ends `end_turn_cap` with 3. A count already
   past the cap ends the conversation, so the check is "at least", not
   "equal".
7. **`session_idle` comes before the cap.** A pin. The main conversation's
   pending tool is resolved at 300 by its next request ending `end_turn`. P
   is pinged at 270 and 540, the second time active through that request. At
   810 the session is idle, and P ends `session_idle` with 2, not
   `end_turn_cap`.

Every other existing test stays as it is and keeps passing. The resumed
test's two pings, and #501's side-request cases, all stay within the cap or
are pending `tool_use`. No proxy round-trip or command test is added, because
the seam, the request line and the flag do not change.

## Out of scope

- `DUE_AFTER`, `WINDOW`, `MAX_CANDIDATES`, the `tool_use` window and any stop
  reason other than `end_turn` (D1).
- #423 D22's children rule, and any other way of telling a finished subagent
  from a waiting one (D5).
- A `stop_reason` field on `keepalive_end`, or any other log-schema change
  (D4, D7).
- Cost tooling: `agent-costs`, the owner report that #503 extends to price
  `ping` lines (those lines keep their shape), and the owner replay's
  `keepalive=on` model.
- `cache_proxy.py`, the Nix service and the `claude` wrapper.
- The AC2 measurement itself and `just switch`, which are the user's after
  merge.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A conversation's last reply is the `stop_reason` of the 2xx, `complete`, streamed response to its newest thread request, recorded by `_done` under the guard that marks a tool pending and cleared by `observe` for every thread request; side requests never set or clear it; only `end_turn` is capped, and `tool_use`, every other stop reason and no last reply keep today's full window | Issue: "whose last reply ended the turn (`end_turn`)", "Conversations waiting on a tool call (`tool_use`) keep the full window"; #423 D27 and #501 D3 (one home for "newest thread request"); mbp 10-26..11-01: 2,743 `end_turn`, 48,830 `tool_use`, 339 without a stop reason and no other stop reason | Capping every reply that is not `tool_use` (`max_tokens` or `pause_turn` mean the client continues, none was seen, and the issue names only `end_turn`); letting a side request's stop reason count (#501 D3: a side request is not the conversation's turn) |
| D2 | `END_TURN_PINGS = 2`, a module constant whose comment gives its reason: about 14 minutes of cache past the reply (2 × 270 s + 300 s) and the measured week's best net | mbp proxy log 10-26..11-01, pings priced with `model_pricing.usage_cost`: net of pings cut minus resumes lost is $83.91 at 1, $103.07 at 2, $101.67 at 3, $97.38 at 4; 236 of 392 resumed `end_turn` periods resumed within 2 pings; issue: "a small fixed number", "a named constant with its rationale documented beside it" | 1 (gives up 78 more resumes and nets $19 less); 3 (within noise of 2 but one more ping and 270 s more of a held credential per period for no measured gain); a flag or setting (YAGNI: the issue asks for a constant) |
| D3 | The cap is checked at a due time after `ceiling` and `session_idle` and before a ping is built, and ends the conversation once the idle period's existing ping count (every ping since the last thread request, those sent while the reply streamed included) is at least the cap; the end comes at the due time after the last allowed ping, never when that ping settles | #423 D10's order and per-period `pings`; #423 D11: a `resumed` line tells paid-off pings from wasted ones; AC2 counts pings per period whose last reply is `end_turn`; mbp: no `end_turn` reply streamed past 270 s | Ending once the capped ping settles (a resume inside its lifetime would log no `resumed`, hiding pings that paid off); checking the cap before `session_idle` (`end_turn_cap` would then also count ends the old rules made); counting only pings after the reply (a second counter, and a period could then exceed the cap that AC2 checks) |
| D4 | The new reason is `end_turn_cap` in `END_REASONS`; its `keepalive_end` line carries today's fields (`conversation`, `reason`, `pings`, `idle_s`) and, like every end but `resumed`, clears the candidate and its headers; no other log field changes | Issue: "ends the conversation with a distinct end reason"; #423 D11's field set; #423 D24; the bar: fail loud at a closed set (`_log_end` rejects an unknown reason) | `capped` or `finished` (the first does not say which rule fired, and the second claims what the proxy cannot know, #423 D17); a `stop_reason` field on `keepalive_end` (a wider log-contract change that AC2 does not need, D7) |
| D5 | The cap refines #423 D10 and narrows D17: an ended turn costs at most two pings, not the session's activity up to 60 minutes. It is taken over #423 D22's children rule, which stays unbuilt | Issue "What to build" names the cap; #423 D22 recorded the children rule as a lever, not a commitment, and its trigger is not met (mbp week: $720 of rewrites avoided by resumes against $248 of pings to never-resumed `end_turn` periods), so the cap is the issue's own choice; issue 432 measures #501 and #502 together after the first switch that includes both | Building D22's children rule now (it tracks `x-claude-code-parent-agent-id` per conversation, it misses wakes from background-command notifications, and the issue asks for a cap) |
| D6 | AC1 is tested only through `KeepaliveCase` on the fake clock, asserting pings and `keepalive_end` lines and never `_Conversation` fields. Cases 1, 4, 5 and 6 fail today. Case 2 rewrites the existing ceiling test so that its P ends `tool_use`, and cases 3 and 7 pin D1 and D3 | Issue AC1: tests in `tests/test_cache_keepalive.py` that fail on the current code; #501 D4; #423 D12, D25; the bar: assert observable behaviour, fail for one reason | Asserting a private flag or counter (passes even if the pings continue); deleting the ceiling test (it is the only test of the 60-minute ceiling); a proxy round-trip case (the seam and the request line are unchanged) |
| D7 | AC2 is post-merge evidence from mbp's proxy log over the 7 days from the first `listening` line written after the first `just switch` with this change (a restart forgets every conversation, so no period straddles the old code). Each idle period is a `keepalive_end` line, plus a conversation's `ping` lines after its last such line while that period is still open. Its last reply is the `stop_reason` of the conversation's newest thread-request line (`keepalive` neither `untracked` nor `no_tail_mark`) before the period ends, newest by request start (`ts` minus `duration_ms`, as a `request` line is written when its response ends) and none unless that line is 2xx and `complete`, as D1 has it at runtime. Threshold: every `end_turn` period has at most `END_TURN_PINGS` pings | Issue AC2; #501 D5 (post-merge, never claimed by the delivery); CLAUDE.md: switch only when asked; request lines already carry `keepalive`, `conversation` and `stop_reason` | Gating the merge on AC2 (no switched host runs the change before merge); a new log field so that AC2 becomes a grep (D4) |
| D8 | Extends D6: planning adds an eighth AC1 case, a pin like cases 3 and 7. After an `end_turn` reply, a newer thread request answered 529 leaves P with no last reply, so P is pinged at 270, 540 and 810. Planning also moves `SideRequestTest.pinged` into `KeepaliveCase` so both test classes share it; no existing test body changes except case 2's one line | Planning prototype at `4e944cb4`: dropping `observe`'s clear of the last reply passed all seven spec cases and failed only this one; D1 ("a thread request whose response is not 2xx … leaves the conversation with no last reply"); the bar: DRY, one home per helper | Leaving the clear unpinned (a regression would cap a conversation on a stale reply); a second `pinged` in the new class (two homes for one helper) |
| D9 | Extends D7 (Phase-5 standards review): AC2's command is a read-only `python3 -I -c` script in the plan's § AC2 measurement, taking `START`/`END` and printing `end_turn_periods`, `over_cap` and `max_pings`; the threshold is `over_cap` `0`. It printed `over_cap` 1305 of 2017 on the pre-change 10-26..11-01 log, after the PR review had it order last replies by request start and take `max_pings` over every `end_turn` period | Codex plan review: an evidence row needs a concrete command, not a method (from-issue REVIEW-CONTRACT); the script is D7's reading verbatim | A new `just` recipe or `agent-costs` report (out of scope, spec § Out of scope); leaving D7's prose as the command (not executable) |
