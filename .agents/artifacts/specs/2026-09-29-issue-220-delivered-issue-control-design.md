# Control never launches a delivered issue and never commits a reply the boundary rejects, issue 220

## Problem

An orchestrated run dispatches owners only from the actions `workflow-state
control` returns, and the adapter pipes each owner object through
`artifact-budget validate-report --boundary workflow-response` before it
launches anyone. In run `run-20260927-204-205-206-207-208-209`, issue 207's
attempt 1 went through launches 1 to 4. Delivery remainder `207:r1:1` then
completed delivery and the issue was closed. A later sweep, prompted by issue
209's `unavailable` owner observation, returned two `resume` actions: the
expected `209:1:2` and a stale `207:1:3` for the delivered issue. The boundary
rejected the reply. The ledger had already committed both launches, so the run
now held a custody the adapter could never dispatch and no one would ever
finish. Issue 208's first resume in the same run failed the same way.

The operator sees two faults:

1. **A delivered issue is relaunched.** Delivery is complete, and nothing is
   left to do for issue 207, yet control plans a launch for it.
2. **A rejected reply still mutates the ledger.** Control's contract is "the
   response is the only source of action order", but the ledger records a
   launch that no valid response ever carried.

### Where it comes from

Delivery completion ends custody by derivation, not by rewriting records.
Once every postcondition of an issue's installed contract is observed or not
applicable, the shared custody projection reports no current custody for that
issue. `check-launch`, admission settlement (which releases the claim
`finished`), the live-launch count and the next-deadline computation all read
custody through that projection. The record whose report completed delivery
is left as it was. A remainder stays `active`, since the remainder state set
has no success terminal, and so does an implementation attempt finished with
a null historical result.

Control's lane policies read records directly instead of through the
projection:

- The remainder lane takes the latest remainder whenever it is `active` or
  `suspended`. When the record's deadline passes, the reaper suspends it and
  the resume lane resumes it.
- The implementation lanes take the latest attempt with the same blind spot.
- Recovery's "no current custody" precondition is trivially true on a
  delivered issue.

Once such a launch is planned, response decoration asks the projection for
the issue's custody and gets none. The action therefore keeps the
implementation-shaped id rendered from the remainder facade: the issue, the
source attempt, and the remainder's launch count. For issue 207 that is
`207:1:3`, which names attempt 1's third launch, a launch attempt 1's fourth
launch has already superseded. The action's custody is null. The boundary
rejects the action, but `transact` has already committed the mutation,
because control never validates its own reply.

"Superseded launch" is therefore not a second defect. It is how the delivered
relaunch shows up on the wire. Under the ledger lock every dispatch appends a
launch and renders the newest one, and nothing else can name an older launch
(D3).

## Solution

1. **Delivered issues get no launch lane.** At the start of a sweep, control
   computes the set of requested issues whose persisted ledger state is
   delivery-complete, using the same predicate the custody projection uses.
   For those issues neither the analysis pass nor any dispatch lane runs the
   one-issue policy. Each gets a fixed `terminal` verdict that changes nothing
   and dispatches nothing: no reap, no resume, retry, spawn or recover, no
   remainder, no `expired` delta, and no capacity or slot charge. Delivery
   folding, admission settlement and summary rendering still run for them as
   they do today (D1, D2). A request that carries a recovery proof or a
   candidate worktree for a delivered issue gets the same verdict. The proof is
   not consumed, and no second remainder is allocated (D9).
2. **A delivered issue's summary names a stale custody.** Everything in the
   summary of a delivered issue is unchanged except `custody`. When the ledger
   still holds exactly one nonterminal record for that issue, `custody` names
   that record's current launch. Otherwise it stays null, as today. A delivered
   summary is one with a non-null `contract_digest`, an empty
   `pending_stage_ids`, an empty `requirements` and a null `owner`. It never
   carried a custody before, so a non-null one can only mean a stale custody
   that control will never dispatch. The first two alone do not suffice: live
   custody whose stages are all observed but whose postconditions are pending
   has them too, but it owes postcondition observations and names its owner
   (D13). The wire shape and its vocabulary are unchanged (D4).
3. **Control validates its reply before it commits.** Inside the ledger
   transaction, after the reply is built and before the mutation is returned
   for commit, control renders the reply to the exact bytes it will print. It
   validates those bytes at the `workflow-response` boundary with the same
   `artifact-budget` executable and policy the adapter uses. On rejection the
   transaction raises before `commit_state`. The ledger stays byte-identical,
   the exit status is non-zero, stdout is empty, and stderr carries one line
   naming the `workflow-response` boundary. On acceptance the bytes printed
   after commit are the bytes validated (D5, D6).
4. **The adapter keeps its own validation.** `orchestrate-issues` still pipes
   every owner object through the boundary before a launch. Control's check is
   the inner side of the same trust boundary (D6).

## Decisions

- **Scope of the gate.** The gate lives in `workflow-state control`'s lane
  orchestration: the analysis call and the single `apply_policy` entry that
  every dispatch lane goes through. It does not live in the one-issue policy
  that control shares with `direct-owner`, so `direct-owner`'s behavior is
  unchanged (D1).
- **The predicate.** "Delivered" is the delivery runtime's existing
  `delivery_complete(issue_state)`, evaluated on the ledger as it stands after
  the sweep's opening admission settlement and before planning. No second
  definition of completion is introduced (D1, D2).
- **Custody projection interface.** The projection gains one read that returns
  an issue's single nonterminal record and its custody reference, without the
  delivery mask. `current_custody` becomes the masked view over that read, so
  "which record is nonterminal" and its "more than one nonterminal record"
  refusal keep one home. The summary uses the unmasked read only when the
  issue is delivered (D4).
- **Reply validation hook.** Control reuses `workflow-state`'s existing
  `artifact_budget_validate` subprocess seam, the one the `ship-summary`
  boundary already uses, with boundary `workflow-response` and stdin input. It
  inherits that seam's source-or-installed resolution of the executable and
  the resolved policy. Its refusal text is generalised so it names the
  boundary instead of "terminal result" (D5).
- **Byte identity.** The bytes validated and the bytes printed are one value.
  The canonical output the validator writes is not substituted for control's
  own rendering, so the reply's wire bytes are unchanged (D5).
- **Existing ledgers.** No migration or repair runs. A ledger that already
  holds a stale `active` remainder or attempt for a delivered issue,
  including one whose extra launch a pre-fix sweep committed, is valid under
  today's validator. The gate simply never plans it, and the summary reports
  it (D4, D7).
- **Documentation.** `orchestrate-issues` §5 gains one sentence. A delivered
  summary with a non-null `custody` is reported as stale custody that will
  not be dispatched, never as an active or progressing owner. §4's
  per-object boundary validation stays as it is.

## Test seams

All tests run at the existing CLI seam. They drive `workflow-state` as a
subprocess under the recipe's `PYTHONPATH` and pipe replies through the real
`artifact-budget` validator, in the style of the `test_delivery_workflow.py`
remainder tests and the `test_admission_replay.py` simulated adapter. No
validator or policy function is mocked.

1. **Delivered relaunch regression (acceptance 1).** Two issues run on a
   supported route. Issue A's attempt 1 reaches at least four launches, which
   takes at least three resumed launches. A then fails after selection, which
   mints remainder `r1`, and `r1`'s `finish` reports `delivery_complete`.
   Issue B holds live custody. A later `control` call carries B's
   `unavailable` owner observation and a `now` past `r1`'s deadline, so at the
   base commit the reaper and resume lane relaunch A. A's recorded worktree is
   observed the way the adapter reports it after delivery clean-up. The plan
   pins the exact observation that reproduces the relaunch at the base commit.
   The test asserts that the
   reply passes the `workflow-response` boundary and carries no action for A,
   and that B's resume is still emitted. At the base commit this test fails:
   the boundary rejects the reply (D3). Two variants of that sweep observe A
   only by its candidate worktree, as after an adapter restart, and carry a
   structurally valid recovery proof for A. Each asserts the same reply, no
   `admission.waiting` entry for A, and A's records unchanged (D9, D14).
2. **Atomic refusal (acceptance 2).** The test copies the source `scripts`
   tree beside a copy of the artifact-budget policy whose
   `workflow_responses.wire_max_bytes` is too small for any control reply,
   following the `ArtifactBudgetPolicyResolutionTest` layout precedent. It
   initialises a run, then issues a `control` call that would spawn and
   therefore commit a change. The run's state file is byte-identical before
   and after, the exit status is non-zero, stdout is empty, and the call is
   refused by the real boundary. The rejection is real, not simulated (D8).
3. **Stale custody reported, not dispatched (acceptance 3).** The ledger is
   the one test 1 leaves, where delivery is complete and `r1` is still
   `active`. The test then appends one resume launch to `r1` in the stored
   ledger, the shape a pre-fix sweep committed, and checks that the ledger
   still loads. A control sweep emits no action or delta for the delivered
   issue. Its summary names `r1`'s current launch in `custody`, keeps the delivered state and an
   empty `pending_stage_ids`, and the ledger's records for that issue are
   unchanged (D4, D7).
4. **`just agent-workflow-tests`** stays green (acceptance 4).

## Out of scope

- Terminalising or repairing a stale record, whether at delivery
  completion in `finish` or `checkpoint-delivery`, or during a sweep. That
  would require a success terminal for remainders and a result for them, which
  is a ledger schema change (D7).
- `direct-owner`'s handling of a delivered issue. Its remainder re-entry path
  reads the latest remainder the same way, so it may share the defect. That
  belongs in its own issue (D1).
- A `launch_refused` owner observation naming a delivered issue's stale
  custody. The masked projection reports no custody, so it refuses the whole
  sweep with `launch_refused is not applicable`. It is believed unreachable:
  the only such custody is one a pre-fix sweep committed, and its reply failed
  the adapter's own boundary check, so no owner was ever launched on it.
- `direct-owner`'s terminal blocker order (D10).
- An issue whose delivery is completed by this same sweep's delivery-
  observation fold after a lane has already planned its launch. Guarantee 2
  refuses such a sweep atomically, and it is not otherwise special-cased (D2).
- The transaction-core cutover (#125) and any `agent_tools.transaction_*`
  module.
- Moving `workflow-state` or `artifact_budget` into the `agent_tools` package,
  and CI or branch-protection changes.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Gate delivered issues out of every launch lane in `control`'s orchestration (analysis call and the one `apply_policy` entry), not inside the shared one-issue policy | Issue scope: IN is control's lane selection, OUT is other subcommands' behavior; custody projection already masks delivered issues everywhere except the lane policies | Gate in the shared policy: silently changes `direct-owner` behavior outside the issue's scope |
| D2 | "Delivered" is the existing `delivery_complete` predicate on the persisted ledger after the opening settle; same-sweep completion by the delivery fold is left to guarantee 2's atomic refusal | The Bar: DRY (one completion predicate), YAGNI; fold runs after planning today | Preview the fold on a copy before planning: reorders a stateful fold for an edge no run has shown |
| D3 | No separate "superseded launch" detector; the observed superseded id is the delivered remainder's facade rendering, removed by D1 and backstopped by D5 | Under the ledger lock every dispatch appends and renders its newest launch; The Bar "tests that can fail" rejects guards no test can turn red | A post-mutation custody-equals-current assertion: redundant with the wire's custody/id check and untestable once D1 lands |
| D4 | Report stale custody by filling only the delivered summary's existing `custody` field from an unmasked projection read; no new wire vocabulary | Brief: prefer existing closed vocabulary; delivered summaries never carried custody, so non-null is unambiguous; #194 precedent keeps per-issue facts in the summary | New requirement kind or reason code: requirements mean "what the caller owes", and it widens the closed wire set; state `active`: untruthful for a delivered issue |
| D5 | Validate the exact printed reply bytes in-transaction through the existing `artifact_budget_validate` subprocess seam at `workflow-response`, raising before commit | Brief: reuse the validator workflow-state already calls; `ship-summary` precedent; standards rule 3 forbids new import machinery; same executable and policy as the adapter | In-process import of `artifact_budget`: needs new file-path loading in a legacy script, and could diverge from the adapter's executable and wire bound |
| D6 | Keep the adapter's boundary validation; control's check is the inner side | The Bar: defense in depth, both sides of every trust boundary | Drop the adapter pipe now that control validates: removes the outer check |
| D7 | No migration or repair of existing ledgers; stale records stay as written | Stale records already pass `validate_state`; remainder states have no success terminal; issue asks for reporting, not healing | Terminalise on delivery or during a sweep: a schema and result-semantics change outside scope |
| D8 | Acceptance 2 forces a real boundary rejection with a copied script tree and a too-small `workflow_responses.wire_max_bytes` policy | The Bar: assert observable behavior, no mock of the validator; `ArtifactBudgetPolicyResolutionTest` copies the tree the same way | Mock `artifact_budget_validate` to raise: tests the mock, not the boundary; seed a bad ledger: no post-fix ledger yields an invalid reply |
| D9 | A recovery proof or other launch input for a delivered issue gets the terminal verdict: it is not consumed and nothing is refused | #194's lesson that one issue's input must not take down the sweep; delivery completion leaves nothing for a recovery to do | Refuse the sweep (fail loud on a protocol input): one issue's stale proof would then block every other issue's dispatch |
| D10 | Control sorts each summary's blockers by `(kind, issue)`, the wire's closed order; `control_blockers` and the direct-owner terminal it feeds stay unchanged | D5's in-transaction validation exposed it: a tracker with both open and decision blockers made control emit `issue` before `decision`, a reply the boundary always rejected; D1 keeps `direct-owner` out of scope. Known out-of-scope defect for a follow-up: the direct-owner terminal still gets `control_blockers`' issue-then-decision order, which the wire's terminal `blockers` check rejects | Relax the wire's blocker order: widens a closed public contract; sort inside `control_blockers`: silently changes `direct-owner`'s terminal output |
| D11 | The acceptance-1 fixture is pinned: 207 runs alone through launches 1–4 (minutes 0, 31, 62, 93), fails after selection at 94 (r1 deadline 274), delivers through r1 at 95; 209 spawns at 250; the sweep at 275 carries 209's `unavailable` owner and observes 207 `closed` with its recorded worktree `absent` | Spec test seam 1 asks the plan to pin the base-reproducing observation; run at base, this exact sequence yields the rejected `207:1:2` resume with null custody | Spawn both issues at minute 0: 209's own fourth expiry trips the stall bound and stops it, so no live custody remains past r1's deadline |
| D12 | Delivered issues also skip the remainder-1 lane before its slot check and the candidate-worktree replay check | D1's "no capacity or slot charge" and D9's "candidate worktree gets the terminal verdict"; the verdict carries no `custody_kind`, so the replay check would otherwise raise for a delivered remainder issue observed with a candidate | Rely on the verdict alone: the replay loop raises `current control action requires a recorded worktree observation` and the remainder lane can add the issue to `waiting` |
| D13 | Amends D4: a delivered summary is recognised by non-null `contract_digest`, empty `pending_stage_ids`, empty `requirements` and null `owner`; the Task 2 test pins the last two | Plan review SF-1: live custody with every stage observed and postconditions pending also has a digest, no pending stages and a custody, but carries `postcondition_observation_required` requirements and its record's owner; `control_summary` takes no latest record for a delivered issue | Digest and pending stages alone: misreports that live custody as delivered with stale custody |
| D14 | Amends D12: no remainder-1-lane guard, since its existing `historical_requested` filter is already False under `delivery_complete`; the replay-loop skip stays, pinned by a candidate-only post-restart regression, and D9 gets a recovery-proof regression | Plan review SF-2, SF-3 and Codex PR220-01: the guard was dead code; without the skip, a delivered issue observed only by candidate raises the replay error; at base `recovery_policy` refuses a proof against the active r1 | Keep the dead guard; leave the replay skip and D9 untested |
| D15 | Amends D5: `print_json` writes `render_json`, so the wire rendering has one home, and control's inner function returns `tuple[bytes, bool]` | Plan review SF-4: two renderings could drift apart, and a validated reply must match every printed one | Keep `print_json`'s own `json.dump` beside `render_json` |
