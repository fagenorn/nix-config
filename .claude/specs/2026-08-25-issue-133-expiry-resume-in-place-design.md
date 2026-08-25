# Expiry suspends and resumes in place — design

Issue: https://github.com/fagenorn/nix-config/issues/133

## Problem

The 2026-08-23 quota-suspension design settled that an environmental
termination "consumes no attempt", and that resuming a suspended attempt
consumes none either and grants a fresh full window (ledger rows D2, D5, D8 of
that spec — the attempt cap stayed at 2 *because* resumes are free).

The lifecycle helper honours that only when the dispatcher happens to be busy.
`_apply_one_issue_policy` computes `expired` (the latest attempt is `active` or
`handed_off` and the deadline has passed) and then folds it into `retryable`
alongside the two genuine terminals. So:

- with **no** free slot the sweep demotes the attempt to `suspended(unknown)`
  and returns idle; the next sweep resumes it in place — the specified
  behaviour;
- with a **free** slot the same expiry lands in the retry lane, which demotes
  attempt 1 and immediately appends attempt 2 on the recorded worktree —
  spending the single retry the cap allows on an interruption the spec says is
  free. A second expiry then hits `retryable and latest["attempt"] >= 2` and is
  stamped `failed`/`refused` with the `retry_refused` delta.

Whether a wall-clock deadline costs an attempt therefore depends on how many
slots were free in the sweep that noticed it. Two of this repository's own
ledgers show the end state: `direct-99-000001` and `orchestrate-21-24-r2`
issue 23 both sit in `retry_refused` after two expiries, having never recorded
a semantic failure. The direct caller is worse than the orchestrated one:
`command_direct_owner` always passes `dispatch_permitted=True`, so a
`/from-issue <n> --auto` re-entry after a crash *always* takes the retry lane
and always spends the retry.

There is a second, quieter consequence. The spec's anti-zombie bound — the
third consecutive suspension at an unchanged phase escalates to a synthetic
`stopped(stalled)` — is defeated on the expiry path today: the retry lane calls
`demote_expired_attempt`, which may stamp that terminal and set the issue
outcome, and then unconditionally appends attempt 2 and clears `outcome`. The
bound writes a record nobody ever reads.

## Solution

Stop treating expiry as a lane of its own. **The reaper runs first, once, on
every touch; everything after it sees an ordinary suspension.**

1. `_apply_one_issue_policy` demotes an expired attempt to `suspended(unknown)`
   immediately after it computes `expired`, before any lane predicate is
   derived. There is exactly one `demote_expired_attempt` call site; the four
   in-lane ones are deleted.
2. `expired` comes out of `retryable`. The retry lane keeps its other two
   entrances untouched — an owner-reported `failed` and a legacy
   `stopped`/`result_source: "expiry"` from before the suspension model — so an
   attempt that genuinely reached a terminal still gets its one fresh retry.
3. A reaped attempt is `suspended(unknown)`, and `unknown` is in
   `AUTO_RESUMABLE_BLOCKED_ON`, so it flows into the **existing** suspension
   lane: the forge ladder, the recorded-worktree ladder with its Phase-0
   carve-out, the `dispatch_permitted` gate, and `resume_attempt` with a fresh
   full `attempt_budget_minutes` window. Expiry gets no capacity policy of its
   own — it inherits the one suspensions already have.
4. When the reap escalates instead (`suspend_attempt` returns `False` at
   `STALL_LIMIT`), the attempt is `stopped(stalled)` with the issue outcome
   set, no lane matches, and the policy returns a `terminal` decision that now
   carries `changed=True` so the escalation is actually persisted and reported.
5. `expired` stays `True` in the projection on every path a reaped attempt can
   reach, so the sweep keeps emitting the `expired` delta and keeps running the
   fallback persistence pass.

The demo in the issue then holds: with `max_parallel: 2` and one issue running,
an expiry with a free slot suspends attempt 1 and dispatches `resume` on it
(action id `<issue>:1:2`), and a second expiry does the same again instead of
refusing.

## Decisions

### The reaper's position in the policy

The policy's opening becomes, in order:

1. derive the issue identity and cross-check the tracker/worktree observations
   (unchanged);
2. compute `expired` and `active_unexpired` — both pure reads of the latest
   attempt and the clock;
3. the `current_owner_unavailable and not active_unexpired` refusal
   (unchanged — an expired attempt already failed `active_unexpired`);
4. **the forge-merged reconciliation**, hoisted here from below the
   terminal check;
5. **the reaper**: `if expired: demote_expired_attempt(ledger_issue, latest, now=now)`;
6. `handed_off`, `suspended` and `retryable`, all derived from the *post-reap*
   attempt;
7. everything else, unchanged in order.

Step 4 must precede step 5 or the anti-zombie escalation can mask a merged pull
request: the escalation writes a terminal, no lane then matches, and the policy
would return before reaching reconciliation. The 2026-08-23 spec's D3 says
reconciliation precedes ownership, and the existing code comment at that branch
says exactly that; hoisting makes the claim true for every state rather than
for the subset that survives the terminal check. The hoist is inert for both
live callers today — `control` never supplies a forge observation, and
`direct-owner` short-circuits a terminal latest into replay before the policy
runs, so the branch it now jumps ahead of is unreachable there.

After step 6 the post-reap predicates are exhaustive in a useful way: a reaped
attempt is either `suspended` (always, since `unknown` is auto-resumable, so it
never needs `human_directed`) or `stopped(stalled)`.

**The reaper's trigger does not move.** The 2026-08-23 spec calls it a lazy
reaper, "the existing next-touch stamping mechanism, unchanged in trigger", and
that stays exactly true: it still fires only when `control` or `direct-owner`
touches the ledger, still never from `progress`, `suspend`, `finish` or #132's
clockless `check-launch`. What moves is its position *within* one touch —
before the lanes instead of inside four of them.

A reap whose decision does not persist (`changed=False` — the two `observe`
rounds a direct owner takes while it still owes the forge or worktree
observation) is discarded with the rest of the mutation, and the next call
re-derives it from the same stored attempt. `stalled_resumes` therefore cannot
inflate across observation rounds; it advances once per completed
suspend-resume-expire cycle, because a *parked* suspension is not `expired`
(that predicate requires `active` or `handed_off`) and so is never reaped twice.

### Where a reaped attempt goes, lane by lane

| Post-reap situation | Decision | `changed` | `expired` |
|---|---|---|---|
| stall escalation (`stopped(stalled)`) | `terminal`, no `tracker_reason` | `True` | `True` |
| tracker says closed/blocked | `terminal` with `tracker_reason` (the suspension branch, not the retry-lane one) | `True` | `True` |
| no dispatch slot | `idle`, `desired="resume"` | `True` | `True` |
| forge observation still owed (direct only) | `observe`, `desired="resume"` | `False` | `True` |
| recorded worktree unobserved or unusable | `observe`, `desired="resume"` | `False` | `True` |
| dispatchable | `resume` with a fresh full window | `True` | `True` |

Every branch in this region hard-codes `expired=False` today and now propagates
the real value; two of them additionally gain `changed=expired` — the early
terminal check (true only for the escalation) and the suspension tracker-halt
branch. Without the `changed` the reap would be computed and thrown away; without
the `expired` the sweep would neither report it nor run the pass that persists it.

Below the suspension lane, `expired` is provably `False` — the reap makes an
expired attempt non-`retryable`, and nothing reaches the retry/spawn region
except `latest is None or retryable`. Those returns therefore pass
`expired=False` outright, guarded by one `assert not expired` at the top of the
region so a future edit that reopens the path fails loudly rather than
silently re-emitting an `expired` delta from the wrong lane.

### Same sweep or next sweep

**Same sweep when the suspension lane can already dispatch; the next sweep
otherwise — and this is not a new rule.** The issue leaves the choice open and
requires it recorded (D2). The choice made is to give expiry no timing rule of
its own: the suspension lane has decided exactly this question since the
2026-08-23 design, and expiry is now just another way into that lane.

Concretely, in `command_control`:

- the dry-run analysis pass reaps its deepcopy, so `analysis[issue]["desired"]`
  is `"resume"` and `analysis[issue]["attempt"]["state"]` is `"suspended"`;
- the resume pass takes the issue when capacity is free **and** the caller has
  already reported the recorded worktree; it dispatches `resume` in this sweep;
- when the caller reported nothing about that worktree, the existing "round
  still owed" guard skips it — the sweep persists the suspension and the next
  sweep resumes. That guard tests `attempt["state"] == "suspended"`, which a
  reaped attempt now satisfies, so it covers expiry with no edit;
- when capacity is zero the issue never enters the resume pass at all and the
  fallback persistence pass parks it as a suspension.

For `command_direct_owner` there is no next sweep — the acquiring owner *is*
the sweep, `dispatch_permitted` is always `True`, and it observes its own
worktree — so a direct expiry always resumes in the same call. That asymmetry
is the reason a "always demote, always return idle, let the next sweep resume"
rule is not viable: `idle` from the direct caller raises
`"direct run has an active owner"`, which would make every post-crash
`/from-issue <n> --auto` re-entry fail outright.

Same-sweep is the *normal* outcome rather than the lucky one, because
`bootstrap_response` already emits a `recorded_worktree` requirement for every
issue that has attempts, whatever their state, and the dispatcher prose already
tells the orchestrator to inspect every such requirement and report it. A sweep
that observes an expiring attempt has, by contract, already been asked for that
attempt's worktree. "Round still owed" is the exception — the caller that
answered nothing — and it costs one sweep, not an attempt.

The next sweep is the one the orchestrator's own wait arms, or, when a parked
suspension is all that is left, the human's single re-invocation: with no
`active`/`handed_off` attempt anywhere, `control` arms no deadline and returns
`finalize` rather than parking on a wake that will never come, and
re-invocation sweeps and auto-resumes (that spec's D9, D12). This is the
existing behaviour for every parked suspension; expiry does not change it.

### The escalation's decision shape

`suspend_attempt`'s `STALL_LIMIT` escalation was previously reachable from the
expiry path only to be immediately overwritten. It now terminates for real, and
both callers must handle a `terminal` decision that carries no `tracker_reason`:

- **`control`** needs nothing new. `desired` is `"terminal"`, so the issue is
  never appended to `proposal_order` and never reaches the
  `{spawn, resume, retry}` delta map; the fallback persistence pass writes it,
  and the `expired` delta reports `state: "stopped"`.
- **`direct-owner`** gains one branch, placed after the existing
  `terminal`-with-`tracker_reason` branch and mirroring the `reconcile` branch:
  persist when `policy["changed"]`, then return `direct_terminal` with
  `source="lifecycle"`, `reason` = the attempt's terminal result state
  (`"stopped"`), `blockers=[]`, and `result` = the issue outcome. That envelope
  is byte-identical to the one the *next* direct call produces from terminal
  replay, because `direct_run_is_terminal` classifies `stopped(stalled)` as
  terminal and the replay builds the same fields.

The `"invalid one-issue policy operation"` fall-through stays as the closed-set
default (the-bar, *Fail loud*).

The bound's arithmetic is unchanged and worth stating exactly, because the
issue's prose ("the third consecutive resume … escalates") is looser than the
code: `stalled_resumes` counts 0, 1, 2 across suspensions at an unchanged
phase, and the suspension that would be the fourth escalates. So one attempt
gets three expiry-driven resumes, and the fourth expiry at the same phase
terminates it. Two consecutive expiries yielding two resumes (the issue's AC2)
sits comfortably inside that.

### Expired handoffs, and the handoff path

An expired `handed_off` attempt takes the same route: the reaper demotes it to
`suspended(unknown)` and the suspension lane resumes it in place. That is
strictly better than today, where it enters the retry lane and opens an
attempt 2 whose `handoff_path` is `null` — the handoff document is silently
abandoned. A resumed handoff keeps the same attempt, the same document, and the
same worktree; `control`'s dispatch action and `direct_owner_response` already
carry `handoff_path`, and the orchestrator prose already says to pass it
through on a `resume`.

The resume lane validates the handoff document only while the state is still
`handed_off`, so a demoted handoff would skip validation and hand out a path
nobody checked. The guard changes from the attempt's *state* to the attempt's
*data*: validate whenever `handoff_path` is not `null`. That is the honest
invariant — verify the path exactly when the response is about to publish it —
and it also closes a pre-existing gap, since `handoff_path` survives
`resume_attempt` and is never cleared, so an attempt resumed once from a
handoff already hands the path out unvalidated on every later resume.

### The sweep's fallback persistence pass

`command_control`'s second pass ends with
`elif analysis[issue]["expired"]: apply_policy(issue, False)`, which exists to
persist a demotion when no dispatch happened. Today it cannot collide with the
resume pass, because the resume lane always reported `expired=False`. Once it
reports the truth, an issue the resume pass already dispatched would be
re-planned with `dispatch_permitted=False`, silently replacing the resume with
a suspension while the issue stayed in `proposal_order` — and the delta map
would then `KeyError` on `"idle"`. The fallback is therefore guarded to run
only for issues no earlier pass has planned.

The `desired == "retry"` branch's inner `elif analysis[issue]["expired"]` is
deleted rather than guarded: `retryable` and `expired` are now mutually
exclusive by construction, so it is unreachable (the-bar, *Production-grade by
default*).

One pre-existing sweep contract becomes newly relevant and is worth pinning in
the fixtures rather than changing: supplying a `candidate` worktree observation
for an issue that already has attempts raises unless the plan actually consumes
that candidate. A reaped-and-resumed issue does not consume one, so the sweep
request for an expiring issue must carry only the `recorded` observation. That
is already true today for the expiry-then-retry case whenever the recorded
worktree matched.

### What the deltas and summaries now say

`CONTROL_DELTA_KINDS` and `CONTROL_DISPATCH_KINDS` are unchanged closed sets;
no new action kind, no new delta kind. What changes is which of them an expiry
produces and what state the `expired` delta reports — always the attempt's real
post-policy state, read from the persisted ledger:

- resumed in this sweep → `expired`/`active`, followed by `resumed`/`active`
  and a `resume` action whose id is `<issue>:<attempt>:<launch>` on the *same*
  attempt;
- parked for the next sweep, or parked by a tracker halt → `expired`/`suspended`;
- escalated → `expired`/`stopped`.

`retried` and `retry_refused` are no longer reachable from an expiry at all.
Summaries need no change: `control_summary` already reports the latest
attempt's state and `blocked_on` verbatim, so a parked expiry shows
`state: "suspended"`, `blocked_on: "unknown"` and its worktree.

No persisted field changes shape, so `schema_version` does not move and live
ledgers in three repositories stay loadable (that spec's D15). The resumed
attempt still validates: `resume_attempt` re-bases `deadline_at` to
`now + attempt_budget_minutes` *and* `last_progress_at` to `now`, which is what
keeps `validate_attempt`'s `started_at <= last_progress_at <= deadline_at`
ordering and its "every launch event at or before the deadline" rule satisfied
for the newly appended launch.

**Interaction with #132's launch guard.** A same-sweep resume makes the dead
owner's `<issue>:1:1` answer `superseded_launch` with `current_action_id`
`<issue>:1:2`, where today's expiry-driven retry made it `superseded_attempt`
pointing at `<issue>:2:1`. Both are `current: false`, both are shapes
`check-launch` already classifies, and the parked case is unchanged
(`inactive_attempt`, `current_action_id: null`). #132's spec also states that an
attempt past its deadline that no sweep has visited still answers `current`
because no successor launch exists yet; that stays true — this change moves
where the reaper runs inside a touch, never when a touch happens.

### Prose

Three homes state what expiry costs, and all three are corrected:

- **`from-issue`'s deadline-rejected-`progress` paragraph** already routes the
  owner to the suspension procedure. It gains the accounting fact it is missing:
  the reaper's suspension consumes no attempt and re-entry resumes the *same*
  attempt with a fresh window, so a deadline never opens a second attempt and
  never exhausts the one fresh retry, which stays reserved for an attempt that
  reported a terminal.
- **`orchestrate-issues`' final-report section**, where the dispatcher renders
  what happened: an `expired` delta is an interruption, not a consumed attempt;
  it is followed by a `resumed` on the same attempt or by a `suspended` summary
  the next sweep resumes, and never by `retried` or `retry_refused`.
- **The helper's own docstrings** — `demote_expired_attempt` (now the single
  reaper call, no longer "only when there is no slot"), `_apply_one_issue_policy`
  (the reap-first ordering and why reconciliation precedes it), `resume_attempt`
  (a reaped expiry is one of the suspensions that takes the fresh window), and
  `stop_attempt`'s existing note that no writer passes `expiry` any more.

The `stopped`/`expiry` shape itself is untouched: it stays a legacy record from
before the suspension model, it stays a retry-lane entrance, and its validation
rule (an expiry finish must not precede the deadline) stays.

## Test seams

This is lifecycle behaviour, not a mechanical edit — the full risk lane applies
to every task that touches the policy. Existing seams only; no new ones.

**Seam 1 — the `workflow-state` CLI via subprocess**
(`test_workflow_state.py`, `WorkflowStateLifecycleTest`), using the existing
`init_run`/`spawn`/`control`/`suspend`/`resume`/`finish`/`acquire_direct`/
`direct_owner` wrappers. The suite's `expire()` helper drives a tracker-closed
sweep, so it exercises the tracker-halt branch; the new capacity cases need
sweeps built from `control(...)` directly with an open tracker.

New cases:

- **Expiry with a free slot** — one issue, `max_parallel: 2`, recorded worktree
  observed as matching. Assert deltas `expired`/`active` then `resumed`/`active`,
  one `resume` action on the same attempt with the next launch ordinal and a
  deadline of `now + attempt_budget_minutes`, and a persisted ledger with
  exactly one attempt whose `launches` has grown by one.
- **Expiry with no free slot** — a second issue occupying the only slot. Assert
  the `expired`/`suspended` delta, no dispatch action for the expired issue, a
  persisted `suspended(unknown)`, and that the following sweep resumes it.
- **Expiry with the worktree unobserved** — the "round still owed" path: the
  sweep parks it even though capacity is free, and the next sweep with the
  observation resumes it.
- **Double expiry** — expire, resume, expire again at the same phase. Assert two
  `resume` launches on attempt 1, `stalled_resumes` advancing 0 → 1, no
  `retried` and no `retry_refused` delta anywhere, and one attempt in the ledger.
- **Expiry exhausting the anti-zombie bound** — three expiry-driven resumes at
  an unchanged phase, then a fourth expiry: assert `expired`/`stopped`,
  `result_source: "stalled"`, the issue `outcome` set, and no successor attempt.
- **Expired handoff** — a handoff `progress` call, then expiry. Assert the
  resume keeps the attempt, keeps `handoff_path`, and that the dispatch action
  carries it.
- **Direct-run expiry** — `acquire_direct`, let the deadline pass, re-acquire.
  Assert a `resume` owner envelope on attempt 1 with a fresh deadline, not a
  `retry` on attempt 2.
- **Direct-run escalation** — drive the same direct run to the bound and assert
  the `terminal` envelope, then assert the next direct call returns a
  byte-identical envelope from terminal replay.

Rewritten, not deleted — each currently asserts expiry → a fresh attempt 2 or a
refusal, and each is re-pointed at the new contract while keeping its original
scenario:

- the composite expiry/retry/spawn sweep and the "expires, retries and fills
  unrelated capacity" demo (both assert `["expired", "retried", "spawned"]`,
  which becomes `["expired", "resumed", "spawned"]`);
- the reversed-request-order expiry-delta test;
- `test_control_attempt_two_deadline_emits_only_retry_refused` — attempt 2 there
  is reached by an owner-reported failure and then expires, so the fix makes its
  expiry suspend instead of refuse; the owner-failure retry that opens attempt 2
  must stay asserted;
- `test_direct_expiry_retries_on_absent_candidate_then_refuses_attempt_two` —
  the absent-recorded-worktree case, which now returns the `recorded_worktree`
  observe requirement and leaves one suspended attempt (see Out of scope).

Must stay green untouched, and are the guard on AC3: every retry-lane test
driven by `fail_owner` (an owner-reported `failed`), every `legacy_expiry_record`
test (the `stopped`/`expiry` entrance), the `retry_refused` test driven by two
owner-reported failures, `test_third_stalled_suspension_escalates_to_synthetic_stop`,
and #132's `check-launch` retry-shape and resume-shape tests — the first of
which carries a comment forbidding its re-pointing at an expiry fixture.

**Seam 2 — skill prose** (`test_workflow_skill_contracts.py`,
`WorkflowSkillContractsTest`) via the existing `self.section(...)`,
`normalized(...)` and `self.assert_ordered(...)` helpers, extending the existing
`test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads` rather
than opening a parallel one, plus one assertion in the orchestrate-issues
final-report section. Every new assertion must anchor on wording that is absent
at base, so it can actually fail.

**Seam 3 — `just build`.** The Nix evaluation check; there is no unit-test suite
for the Nix configs. The generated Claude settings artifact is unaffected —
`workflow-state` is not on the allow surface and no verb is added — so
`tests/test_claude_permission_guard.py` is a gate here, not a target.

Verification: `just agent-workflow-tests` (455 tests green at base),
`just build`, and `python3 tests/test_claude_permission_guard.py` against the
built settings.

## Out of scope

- **A suspension whose recorded worktree is gone.** A reaped attempt observed as
  `absent` or `mismatch` at a phase past zero now behaves exactly as any other
  suspension in that position: `control` refuses the sweep loudly, and
  `direct-owner` re-asks for the recorded worktree. That dead end predates this
  issue — it is reachable today by suspending at phase 3 and deleting the
  worktree — and expiry merely adds an entrance to it. Closing it needs either a
  resume that relocates an attempt to a candidate worktree (a new capability
  that breaks `resume_attempt`'s in-place contract and the one-worktree-per-issue
  reservation #132 relies on) or a synthetic terminal for a lost worktree.
  → **new issue** ("A suspended attempt whose recorded worktree is gone has no
  exit"), following this repository's convention that an out-of-scope entry
  proposes the filing rather than performing it. Not fixed here; the rewritten
  direct-run test pins the inherited behaviour so it is visible rather than
  silent.
- **#125 — epoch-fenced leases.** This change is #125's regression floor. None of
  it is attempted here. One consequence is worth stating plainly rather than
  discovering in review: a resumed attempt is `active` again under its *own*
  number, and `progress` authorizes on attempt state, not launch identity, so a
  predecessor that is somehow still alive can write progress against it. That is
  true of every resume today and #132's spec already assigns it to #125 — but
  today's expiry-driven retry *incidentally* fenced that predecessor by leaving
  attempt 1 suspended, and this change gives up that incidental fencing in
  exchange for correct accounting. The forge-write half stays closed by #132's
  `check-launch`.
- **The `owner_unavailable` refusal on an expired attempt.** An orchestrator
  that reports an owner unavailable for an attempt whose deadline has also
  passed still gets `"owner_unavailable is not applicable"`, exactly as today —
  the refusal keys on `active_unexpired`, which expiry already falsified. The
  condition, the message and the outcome are untouched; the new fixtures must
  not accidentally combine the two facts.
- **The attempt cap, `new_run`, and the `refuse` lane.** The cap stays 2 (that
  spec's D5 kept it there precisely because resumes are free), `new_run` keeps
  its existing guards including the refusal to fan out over a resumable
  suspension, and `refuse` keeps closing out a genuinely terminal attempt 2.
  `new_run`'s *code* is untouched; the message a post-expiry `new_run` receives
  becomes the more specific `"new_run is not applicable: suspended attempt is
  resumable"` simply because the persisted state is now a suspension, which is
  the truthful answer and the one the escape hatch already gives every other
  suspension.
- **`CLAUDE.md`.** Its only claim in this area — that two attempts on one issue
  share a checkout because the lifecycle hands a retry the predecessor's
  worktree and branch — stays true: retries still exist, for the two terminal
  entrances this change does not touch. Nothing there needs correcting, and the
  contract suite reads that file only as a gitignore-shape fixture.
- **The retry lane's other two entrances.** Owner-reported `failed` and legacy
  `stopped`/`expiry` are untouched in predicate, behaviour and tests.
- **Migrating ledgers already parked in `retry_refused`.** The issue calls them
  historical; no migration, no `schema_version` bump — no persisted field
  changes shape.
- **`check-launch` and the ship-time launch guard.** #132's verb takes no clock
  and cannot run the reaper; nothing here changes that.
- **A `docs/` tree, a context map, or an ADR file.** This repository has none;
  its binding documents are `CLAUDE.md` and the standards file, and every
  decision here lands as a row below.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The reaper runs first and unconditionally inside `_apply_one_issue_policy`, at a single call site; every lane predicate is derived from the post-reap attempt, and `expired` leaves `retryable`. | Issue AC1 and the 2026-08-23 spec's D2 ("the reaper demotes an expired active attempt to `suspended(unknown)`") — a reaper that fires only when the dispatcher is busy is not a reaper. the-bar *DRY*: one policy home, one demotion site. | Widening the resume lane's entry predicate to include `expired` and demoting at the point of resume — keeps a second expiry route through the retry lane alive and leaves the four in-lane demotions in place. |
| D2 | Same-sweep resume when the existing suspension lane can dispatch (free capacity **and** an observed matching recorded worktree), next sweep otherwise; the direct caller always resumes in the same call. **This is the ledger row the issue requires.** | The suspension lane already decides this for every other `blocked_on`, including the "round still owed" skip (that spec's D9); expiry inheriting it adds no policy. `command_direct_owner` raises on `idle`, so a next-sweep-always rule would break every post-crash `/from-issue --auto` re-entry. | "Always demote and return idle, resume next sweep" — uniform on paper, but it needs a direct-caller special case, which is a second policy in a deliberately shared function. |
| D3 | The forge-merged reconciliation is hoisted above the reaper, to run immediately after the owner-unavailable refusal. | That spec's D3, "reconciliation precedes ownership", which the branch's own comment already asserts; without the hoist a stall escalation returns a terminal before reconciliation is ever considered, masking a merged pull request. Inert for both live callers today. | Leaving reconciliation where it is and making the reap conditional on "not about to reconcile" — a special case hiding a wrong ordering (the-bar, *Root causes*). |
| D4 | The stall escalation surfaces as a `terminal` decision with `changed=True` and no `tracker_reason`; `direct-owner` gains one branch mirroring `reconcile`, returning a lifecycle terminal whose envelope equals the next call's replay. `control` needs no change because `desired="terminal"` never reaches `proposal_order`. | The bound is currently written and then discarded by the retry lane, so it has never terminated anything. `direct-owner`'s existing chain has no branch for it and would raise `"invalid one-issue policy operation"`. the-bar *Truthful terminal states*. | A new operation name for the escalation — grows a closed set that `CONTROL_DISPATCH_KINDS`, the delta map, the skill prose and the evals all mirror, for one internal transition. |
| D5 | Expired `handed_off` attempts take the same suspend-and-resume-in-place path, and the resume lane validates `handoff_path` whenever it is non-null rather than when the state is `handed_off`. | `expired` already covers `handed_off`; today such an attempt retries into an attempt 2 with `handoff_path: null`, abandoning the document. Validate exactly when the response publishes the path (the-bar, *Defense in depth*) — which also covers the pre-existing case of an attempt resumed twice from one handoff. | Excluding handoffs from the new routing — two expiry policies, and the worse one for the case that carries the most context. Keeping the state-keyed guard — hands out an unvalidated path on exactly the new path. |
| D6 | `expired` stays `True` in the projection on every branch a reaped attempt can reach, and the branches that mutate carry `changed`; below the suspension lane `expired` is passed as `False` behind one `assert not expired`. | The sweep's `expired` delta and its fallback persistence pass both key off the projection, so a `False` there silently drops both. the-bar *Fail loud*: the assertion makes the unreachability a checked claim rather than a comment. | Recomputing `expired` from the post-reap state — it would be `False` everywhere and the delta would vanish entirely. |
| D7 | The sweep's fallback persistence pass runs only for issues no earlier pass planned; the `desired == "retry"` branch's inner expiry fallback is deleted as unreachable. | Once the resume lane reports `expired=True`, the unguarded fallback would overwrite a dispatched resume with a suspension and then `KeyError` in the `{spawn, resume, retry}` delta map. `retryable` and `expired` are now mutually exclusive, so the retry-branch fallback is dead (the-bar, *Production-grade by default*). | Guarding the retry-branch fallback instead of deleting it — keeps a branch that cannot execute, in the function whose control flow this issue exists to make legible. |
| D8 | The `expired` delta reports the attempt's real post-policy state — `active` alongside a `resumed` delta for a same-sweep resume, `suspended` when parked, `stopped` on escalation. No delta kind, action kind, summary field or persisted field changes shape. | the-bar *Truthful terminal states*; `CONTROL_DELTA_KINDS`/`CONTROL_DISPATCH_KINDS` are closed sets mirrored in the orchestrator prose and its graded evals, and `control_summary` already reports `state`/`blocked_on` verbatim. No shape change means no `schema_version` bump and no ledger migration. | Introducing a distinct delta kind for a reaped expiry — ripples through the closed set, the dispatcher prose and two eval files for information the `state` field already carries. |
| D9 | A reaped attempt whose recorded worktree is observed `absent`/`mismatch` inherits the suspension lane's refusal; the pre-existing dead end there is filed as a follow-up issue rather than fixed, and the rewritten direct-run test pins the inherited behaviour. | Issue: "an expired attempt is … never opens a successor attempt", and AC1's falsification note names `retryable` including `expired` as the defect — a worktree-conditional retry door would keep expiry inside `retryable` in spirit and would make the accounting depend on whether a directory happened to exist, the same complaint as the capacity dependence. The dead end is reachable today from any suspension. | Letting a resume relocate the attempt onto a candidate worktree — a new capability contradicting `resume_attempt`'s in-place contract and the one-worktree-per-issue reservation, and not a field write either: `validate_launch_event` pins every recorded launch to the attempt's own worktree, so the whole launch history would have to move with it. Keeping a worktree-conditional retry entrance — re-creates environment-dependent accounting. |
| D10 | Corrections land in three prose homes — from-issue's deadline-rejected-`progress` paragraph, orchestrate-issues' final-report section, and the helper docstrings — with the two skill homes guarded by assertions in `test_workflow_skill_contracts.py` that anchor on wording absent at base. | Issue AC5. Those are the only two skill-prose homes that describe expiry to an owner and to the dispatcher, and the contract suite already reads both files. the-bar *DRY*: one authoritative home per statement. | A new documentation section or file — this repo has no `docs/` tree, and the facts belong beside the sentences they complete. Section-wide `assertIn` checks that already pass at base — permanently green. |
| D11 | The change deliberately gives up the incidental fencing that expiry-driven retry provided — a resumed attempt is `active` under its own number, so a surviving predecessor's `progress` is authorized again — and records it as #125's, rather than adding a launch check to `progress` here. | #132's spec already scopes "ledger writes by a stale launch outside the one path guarded here" to #125, and every existing resume has this property, so fixing it for expiry alone would leave the model inconsistent and duplicate the fencing #125 owns. the-bar *Production-grade by default*: known limitations belong in docs, not in a half-wired guard. | Adding a launch-identity check to `command_progress` — a second, narrower fencing mechanism racing the one #125 is designed to introduce, in a verb this issue otherwise never touches. |
| D12 | The grill's verification pass is recorded as part of the design rather than deferred: the reaper's *trigger* is unchanged (still next-touch, still only `control`/`direct-owner`), a non-persisting reap is discarded and re-derived so `stalled_resumes` cannot inflate across observation rounds, and `bootstrap_response` already requires the recorded worktree for every issue with attempts, which is what makes same-sweep the normal outcome under D2. | Each is a claim a reviewer would otherwise have to re-derive from the helper, and each is load-bearing for D1, D2 and the anti-zombie arithmetic; the 2026-08-23 spec's D2 explicitly promised the trigger would not move. | Leaving them implicit — the "reaper runs first" phrasing reads as a trigger change against that spec's own wording, and the counter question is exactly the one an expiry-heavy ledger provokes. |
| D13 | The rewritten direct-run expiry test pins a resume **in place on the recorded worktree** and pins the inherited dead end with a `mismatch` observation, rather than expecting the `recorded_worktree` observe requirement from an `absent` one (refines this spec's Test seams sentence). | A reaped attempt that never advanced past Phase 0 satisfies `absent_phase_zero_pause` — `new_control_attempt` writes `"phase": 0`, and the resume lane treats an `absent` recorded worktree at phase 0 as the reservation intact (that spec's D7). An `absent` observation there therefore resumes; only a `mismatch` (or an `absent` past phase 0) reaches the dead end D9 leaves open. | Asserting an observe requirement for the `absent` case — the test would fail against correct code, and the Out-of-scope behaviour it is meant to pin would go unpinned. |
| D14 | Re-pointing `test_control_attempt_two_deadline_emits_only_retry_refused` at the new contract keeps its owner-reported retry into attempt 2 asserted and changes only the expiry half; the `retry_refused` delta keeps live coverage through the owner-reported entrance. | Issue AC3 requires the owner-reported retry to keep working and AC4 requires rewriting rather than deleting; `test_only_one_fresh_retry_and_refusal_links_prior_attempts` and `test_refused_third_attempt_result_is_not_supersedable` already reach `refuse` without a clock, so the delta kind loses no coverage when expiry stops producing it. | Deleting the test as obsolete — AC4 forbids it, and the attempt-2 retry it sets up is exactly the guarantee AC3 asks to be kept. |
