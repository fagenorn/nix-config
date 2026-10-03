# Durable in-phase progress resets the anti-zombie stall bound, issue 250

## Problem

The lifecycle stops an attempt as `stopped(stalled)` on its fourth consecutive
suspension at one recorded phase. The only progress it recognises is a change
of the phase number. The host cuts an issue owner off after about an hour, so a
Phase 6 (SDD execution) that runs for several hours must suspend and resume
several times at phase 6. Issue #248's attempt 1 was stopped this way although
two tasks had been implemented, reviewed and committed and a third implemented
between its suspensions. The bound measured phase changes, not progress, and
discarded a healthy attempt.

## Solution

An active attempt's current launch can record a **progress marker**: the commit
its recorded worktree has checked out, read by the helper itself. The ledger
keeps the last marker on the attempt. A recording whose commit strictly
descends from the stored marker is new progress and starts a fresh stall count,
exactly as a phase advance does. Anything else leaves the count alone. The
suspension arithmetic, its threshold, and every suspension path (owner, delivery
checkpoint, expiry reaper, host-capacity refusal) are untouched, so a parked
owner that records nothing new still stops at the existing boundary.

This follows the delivery remainder's bound: there the helper derives a
`progress_token` from ledger content and a changed token on a non-blocking
checkpoint resets the counter at record time. Here the helper derives the
token from the worktree's history instead of from a caller's claim.

## Decisions

Three existing names sit close to this one and stay distinct. The `progress`
verb is the phase gate and `last_progress_at` is its clock; neither is
changed. The remainder's `progress_token` is a digest of delivery content. The
**progress marker** is a commit ID on an implementation attempt, written only
by `mark-progress`.

### Ledger schema v6: `progress_marker`

Each attempt gains one field, `progress_marker`: `null`, or a full lowercase
hexadecimal commit ID (40 or 64 characters). A new attempt starts with `null`.
The strict attempt validator requires the field and refuses any other value.
The delivery remainder record is unchanged.

The v5→v6 step joins the delivery runtime's `migrate` chain: it adds
`progress_marker: null` to every attempt and changes nothing else, so
`suspend_phase` and `stalled_resumes` carry over as stored. A v5 document that
already has the field on any attempt is a hybrid and is refused. The unlocked
reader migrates v5 on a detached copy as it does v1–v4, so `check-launch`
keeps working on a run in flight at rollout; the first locked write persists
v6 (per D4). As with every earlier schema step, a helper older than this
change refuses a v6 ledger, so a rollback fails closed on runs written after
it.

### New verb: `workflow-state mark-progress`

```
workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>
```

The caller names only its launch; it supplies no marker (per D1, D2). Steps:

1. Read the ledger unlocked. Refuse unless the launch verdict for
   `--action-id` is `current` — the same test `register-worker` applies. That
   refuses an unknown issue or attempt, a superseded attempt or launch, and an
   attempt that is suspended, handed off or terminal. A remainder action ID is
   refused: remainders keep their own bound.
2. Probe the attempt's recorded worktree, read-only, with the existing
   worktree-git reader (git by name, timeout, no lock): the path must be the
   top level of a git worktree with a branch checked out, and `HEAD` must
   resolve to a commit. When the stored marker is not null and differs from
   `HEAD`, ask git whether the marker is an ancestor of `HEAD`. Any probe
   failure, including a stored marker git no longer knows, is a refusal.
3. In one locked transaction, re-check the launch verdict, and that the
   attempt's worktree and stored marker still equal what step 2 used; a
   difference is a refusal. `--now` must not precede the run's `updated_at`.
   Then apply the outcome below.

| Stored marker | `HEAD` | `outcome` | Ledger write |
|---|---|---|---|
| `null` | any commit | `baseline` | marker := `HEAD`; stall fields untouched |
| M | M | `unchanged` | none |
| M | strict descendant of M | `advanced` | marker := `HEAD`; `stalled_resumes` := 0; `suspend_phase` := `null` |
| M | not a descendant of M | `diverged` | none |

A refusal exits non-zero with a `mark-progress refused: <reason>` line and
writes nothing. The four outcomes exit zero and print
`{"action_id": <id>, "outcome": <outcome>, "marker": <stored marker after the call>}`,
a plain object like `register-worker`'s, not a `workflow-response` kind. A
write is committed through the one state write boundary before the reply is
printed.

The rule that decides the outcome and mutates the attempt is one importable
function beside `suspend_attempt`, taking the attempt, the probed commit and
the ancestry answer; the command is the shell that probes and transacts
(agent-helpers rule 2).

### Why this cannot be forged by repetition

- **Replay.** Recording the same commit is `unchanged`. Because the marker
  only moves forward along ancestry, every earlier marker is an ancestor of
  the stored one, so an earlier commit can never be `advanced` again and no
  set of seen markers is needed (per D3).
- **Rewind and re-advance.** Checking out an older or unrelated commit is
  `diverged` and does not move the marker, so stepping back and forward again
  yields `unchanged`, never a second reset.
- **Nothing durable.** A reset needs a commit object in the attempt's own
  worktree that descends from the last one the helper itself observed. The
  first recording has nothing to compare with, so it only sets the baseline.
- **Not active.** Only the current launch of an active attempt may record.

An owner that manufactures empty commits could still reset the count. That is
outside the bound's threat model: the bound exists to stop an owner that keeps
parking without moving, and the phase number it already trusts is an unverified
caller claim. The marker is strictly harder to fake than that.

The recording at session start credits commits an interrupted task left
behind before the owner was cut off, although that task has no `complete`
line yet (per D11). That is intended: #248's third task was implemented but
unreviewed when its attempt was stopped. A task that never converges is
bounded by sdd's fix-loop cap, not by this bound.

### Where the count resets

At record time, on `advanced` only, by clearing `suspend_phase` and zeroing
`stalled_resumes` (per D5). The next suspension then sees a phase that differs
from `suspend_phase` and counts from 0, which is the path a phase advance
already takes. `suspend_attempt`, `resume_attempt`, the expiry reaper and the
host-capacity refusal are not edited: they read no git state and no marker,
so host-caused suspensions behave identically to owner ones, and the bound
remains the only limit on resuming an expired attempt in place (#133).
`STALL_LIMIT`, the `stalled` result source (quota spec D11) and the stop
reason text are unchanged. Quota spec D8 holds as written: escalation on the
third consecutive resume without progress, where progress is now a phase
advance or an `advanced` marker.

`mark-progress` does not touch `phase`, `last_progress_at`, the phase action
or the deadline, has no deadline rule, and returns no phase-gate action: it is
not a phase boundary. It does not pass the owner-exit fence, because it ends
no launch.

### Skill prose

- **sdd, `### Lifecycle workers` and step 5.** Under a lifecycle identity the
  controller runs the `mark-progress` command once before dispatching the
  first task it will execute in this session, and again immediately after
  each task's `Task <N>: complete` ledger line. The reply's `outcome` is
  informational. A refusal changes nothing, is not a suspension cause and is
  never a reason to stop the task loop: the next `workflow-state progress` or
  `check-launch` remains the authority on the attempt's state. Without a
  lifecycle identity none of this applies.
- **from-issue, Phase 6.** The sentence that hands sdd its lifecycle identity
  also says sdd records a progress marker after each completed task, and the
  mechanical route's owner runs the same command once before dispatching the
  mechanic and once after its change is committed.
- **Descriptions of the bound.** from-issue's and orchestrate-issues'
  sentences that describe the bound as "parked at the same phase too many
  times" are reworded to "without a phase advance or a newly recorded
  progress marker".

The architecture document's lifecycle paragraph gains the verb, the schema
field and the reset rule in the implementation change, not in this design
commit: until the code lands that text would describe behaviour that does not
exist.

## Test seams

All behaviour is tested through the public commands and the persisted ledger,
with the existing `test_workflow_state.py` harness (`spawn`, `suspend`,
`resume`, control-driven expiry and launch refusal) plus a real git repository
created in the test's temporary directory as the attempt worktree, following
the `build-delivery` live-branch tests.

- **Demo.** Four suspend/resume cycles at phase 6 with a new commit and
  `mark-progress` between each pair: the attempt is still resumable and
  `stalled_resumes` is 0 after each suspension.
- **No marker, and each non-reset case.** With no recording, with the same
  commit re-recorded (`unchanged`), with a rewind and re-advance, with only a
  `baseline`, and with a recording attempted while suspended (refused), the
  fourth suspension is `stopped(stalled)` with the same terminal envelope as
  today. Each refusal and each no-write outcome leaves the state file
  byte-identical.
- **Host-caused suspensions.** Expiry demotion and host-capacity refusal: an
  `advanced` marker between them resets the count; without one the fourth is
  terminal.
- **Refusals.** Superseded launch, unknown identity, remainder action ID,
  absent or non-git worktree, detached `HEAD`, a stored marker git does not
  know.
- **Persistence.** After an `advanced` reply the stored state carries the
  marker and validates; it survives suspend and resume unchanged.
- **Schema.** A stored v5 ledger with non-zero `stalled_resumes` loads, keeps
  its counts, and is written back as v6 with null markers; a v5 hybrid and a
  malformed marker are refused; the unlocked reader accepts v5.
- **Skill contract.** `test_workflow_skill_contracts.py` pins the exact
  command line as a constant and asserts, in order within sdd's text, the
  lifecycle-workers heading, the command, and the step-5 `complete` sentence
  followed by the command; within from-issue's Phase 6, the lifecycle
  identity sentence followed by `mark-progress` before the Phase 7 heading.

`just agent-workflow-tests` and `just build` are the completion gates.

## Out of scope

- Worker hand-back routing and `external` / `agent_dispatch` suspension
  bursts; they explain why same-phase suspensions cluster but are separate
  defects.
- The delivery remainder's stall bound and its `progress_token`.
- `STALL_LIMIT`, the `stalled` result source, the stop reason text, and any
  change to which suspension causes are auto-resumable.
- Verifying that a commit represents useful work (non-empty tree change, task
  identity, review evidence). The marker proves durable forward movement of
  the worktree, not its quality.
- Markers for phases other than Phase 6 in the skills. The verb is
  phase-agnostic, but only Phase 6 is instructed to use it.
- Moving `workflow-state` into the `agent_tools` package.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A new verb `mark-progress` addressed by `--action-id`, not a flag on `progress` | `progress` is the phase gate: it demands three context booleans and returns an action the owner must obey; sdd already holds exactly root, run and `action_id`, and `register-worker` gates on the same launch verdict | A `--marker` flag on `progress`: a mid-phase call could return `handoff` or `fresh_start`, and `--issue/--attempt` cannot refuse a superseded launch |
| D2 | The helper derives the marker from the recorded worktree's `HEAD`; the caller supplies none | Issue: follow the remainder's content-derived token and make markers non-forgeable; the bar's token economy (fewer parameters) | A caller-supplied commit or task number: one more failure site, and a claim the helper would have to verify against `HEAD` anyway |
| D3 | "Strictly new" means a strict descendant of the stored marker; one stored marker, no history list; a non-descendant is `diverged` and never becomes the new marker | Ancestry is a strict order, so monotone advance makes every prior marker unreachable as new; issue: "strictly new compared with the last one recorded" | A set of seen markers (unbounded ledger growth); re-baselining on divergence (rewind then re-advance would reset without new work) |
| D4 | Schema v6 with a required nullable field and a v5→v6 migration step | #222 D10 precedent: a field joins by a schema step in the runtime's `migrate` chain, hybrids are refused, the unlocked reader migrates in memory; issue: a pre-change ledger loads with counts intact | An optional key inside v5: the attempt validator is exact-key by design, and tolerance would make two valid shapes of one version |
| D5 | Reset at record time by clearing `suspend_phase` and zeroing the count; `suspend_attempt` is not edited | The remainder resets at checkpoint time the same way; the reaper and host-capacity paths call the pure `suspend_attempt` and must read no git state (#133 D12) | Comparing a second stored "marker at last suspension" inside `suspend_attempt`: two fields and an edit to the arithmetic #133 guarantees |
| D6 | The first recording is a `baseline` that resets nothing | Issue: a marker with nothing durable behind it must not reset; with no prior observation the helper cannot prove movement, and the attempt records no base commit | Treating the first recording as progress (one free reset for an owner that did nothing); deriving a base from the integration branch (needs project policy inside a ledger write) |
| D7 | `unchanged` and `diverged` exit zero with no write; only identity, state and probe failures are refusals | from-issue routes a rejected lifecycle write into the suspension procedure; a benign replay after a resume must not look like one. The ledger stays byte-identical, so the marker is still not accepted | A non-zero exit for replay: correct in isolation, but it turns a routine re-recording into a stop signal for the owner |
| D8 | The git probe runs before the lock and the transaction re-checks the worktree and stored marker it used | The existing worktree-git reader is documented read-only and lock-free; a 60-second git timeout must not be held under the run lock | Probing inside the transaction (blocks every other ledger writer on git); a caller-submitted observation (forgeable, against D2) |
| D9 | The stop reason text "suspension stalled without phase progress" and D8/D11 of the quota spec stay as written | Issue: the no-progress case must stop "exactly as it does today"; the text is still true of an attempt that neither advanced phase nor marker | Rewording the reason: churns terminal envelopes and tests for no behavioural gain |
| D10 | The new rule lands in the legacy `workflow-state` script, as a pure function plus a thin command | agent-helpers: a legacy flat script meets the package rules when its cluster moves; rule 2 still shapes the split | A new `agent_tools` module and command row: it would need the ledger transaction and validator that live in the legacy script |
| D11 | The marker credits any committed forward movement, including an unfinished task's commits picked up by the session-start recording; task completion is where sdd is told to record, not a condition the helper checks | Issue: the bound must measure progress, and #248's implemented-but-unreviewed task was real work; the helper cannot see sdd's git-ignored task ledger | Requiring a task number or review evidence: a caller claim the helper cannot verify (against D2), and it would discard long single tasks |
