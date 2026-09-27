# Roll direct autonomous implementation to a fresh owner

Issue: https://github.com/fagenorn/nix-config/issues/74

This design amends, without replacing, the durable lifecycle and control-plane
contracts accepted for issues 14, 33, 47, 49, and 73.

## Problem

A durable direct autonomous `from-issue` run can now reacquire its complete
lifecycle identity after a restart, but the controller that investigates,
designs, plans, and reviews an issue is still allowed to begin implementation.
That makes the reviewed-plan checkpoint merely advisory. A long design or review
conversation can enter SDD with little or unmeasured context headroom even though
the committed design and reviewed plan already form a complete continuation
seam. The controller then either carries irrelevant history through every
implementation task or hands off according to usage rather than according to the
durable artifact boundary.

The shared phase-action selector cannot simply change order for every run. Its
existing ordering is an accepted interface for dispatcher-owned and explicitly
durable interactive attempts. Module-owned direct autonomous runs need a distinct
artifact-first policy selected from identity the lifecycle module already owns,
not from a new caller assertion.

There is also a restart deadlock before the issue worktree exists. A direct owner
may reserve an absent path, finish Phase 0 with a durable handoff, and exit before
Phase 1 creates the worktree. Reacquisition asks for the recorded path, observes
it is still absent, and asks for it forever because resume currently accepts only
an already-matching issue worktree. Retrying or choosing another path would lose
the reservation and spend lifecycle identity to repair an adapter-state problem.

## Solution

Deepen the existing lifecycle module in two narrow ways.

First, phase progress derives its selection policy from the validated run ID. A
reserved module-owned direct identity uses a complete direct-only precedence in
which a self-contained remainder delegates before usage is considered. Every
other run ID uses the current selector byte-for-byte. The public progress command,
phase-input object, persisted attempt schema, action enum, fixed deadline, and
terminal contracts do not change.

Second, direct acquisition treats an exact absent recorded reservation as a
valid resume fact only for an unexpired handed-off attempt that has not passed
Phase 0. It appends the ordinary resume launch and returns the same owner envelope.
Phase 1, still outside the lifecycle module, creates that exact worktree from the
integration branch. No lifecycle operation performs Git or filesystem mutation.

In the direct autonomous skill, a clean Phase-5 review becomes the mandatory
implementation-owner seam. The current controller commits and validates the
reviewed artifacts, records Phase 5 with a self-contained remainder, receives and
persists `delegate`, then dispatches exactly one fresh issue owner. The fresh
owner receives the unchanged direct-owner envelope, the exact reviewed HEAD,
and only the two bounded artifact roots with current metrics. It reconstructs
from disk, begins at Phase 6, performs the existing SDD and fresh Phase-7
shipping flow, persists the final result, and returns the canonical terminal
JSON. The earlier controller never invokes SDD or edits implementation files.

## Decisions

### Direct-only phase-action policy

Phase-action selection remains inside the durable lifecycle module. The selector
derives whether the attempt is module-owned direct from the already-validated
reserved run identity; the caller cannot pass a mode flag. Persisted phase inputs
remain exactly the current turn count, context count, ceilings, headrooms, and
three booleans. Validation re-derives the action with the ledger's run identity,
so a record cannot transplant direct semantics into another run type.

For a module-owned direct run, evaluate these rules in order:

1. `remainder_self_contained` is true → `delegate`.
2. `artifacts_sufficient` is true and `next_needs_context` is false →
   `fresh_start`.
3. Any available usage measure is at or beyond its ceiling minus headroom →
   `handoff`.
4. `next_needs_context` is false → `handoff`.
5. Otherwise → `continue`.

This is the complete precedence, including mixed observations. A known
near-ceiling measure wins even if the other measure is missing. Missing one or
both measures by itself reaches `continue` only while the next work still needs
the present conversation; the mandatory progress call at the next phase boundary
is the next durable artifact seam. A disposable conversation with sufficient
artifacts chooses `fresh_start` before a usage handoff because neither the old
conversation nor a handoff document is needed. A self-contained remainder always
chooses `delegate`, including when usage is missing, near its ceiling, or the
artifacts would also permit `fresh_start`.

Non-direct identities retain the accepted order exactly: `fresh_start`, missing-
usage `handoff`, near-ceiling `handoff`, `delegate`, no-context `handoff`, then
`continue`. Explicitly durable interactive runs are non-direct even when their
skill invocation is standalone. The attempt deadline is unchanged by every
action, including delegation.

### Mandatory reviewed-plan rollover

The mandatory rollover applies only when all of these facts hold:

- acquisition is direct autonomous and its run ID is module-owned;
- Phase 5 has dispositioned every Blocking and accepted Should-fix finding;
- the reviewed plan and any decision-ledger mutation are committed;
- fresh checker results for both the design root and implementation-plan root
  are `within_budget`, with all four metrics retained; and
- the remaining Phase 6 and Phase 7 work has no conversational dependency.

At that checkpoint the current controller calls progress for completed Phase 5
with `next_needs_context=false`, `artifacts_sufficient=true`, and
`remainder_self_contained=true`, while reporting available usage truthfully. It
requires the persisted response action to be `delegate`. Only after that durable
write does it dispatch one fresh issue owner at the repository's issue-owner
tier. A commit hook that changed either artifact invalidates its measurement and
must be followed by the established recheck-and-commit sequence before this
gate. The earlier controller does not call SDD, run an
implementation command, edit an implementation file, reacquire through
`direct-owner`, create a new attempt, or dispatch a second replacement issue
owner. A dispatch failure may be terminally persisted by the current controller,
but is never permission to implement locally.

Dispatcher-owned autonomous runs and explicitly durable interactive runs keep
their existing checkpoint behavior and action order. Ledger-free interactive
runs remain outside this durable rollover contract.

### Fresh implementation-owner interface

The delegation prompt is a small continuation interface, not a transcript. Its
standing instructions declare direct autonomous mode and the Phase-6 entry point,
then refer to four closed fields:

1. The canonical direct-owner `owner` object unchanged, including
   `interface_version`, `kind`, `ledger_repo_root`, `run_id`, `issue`, `attempt`,
   `owner`, `action_id`, `launch_kind`, `worktree`, nullable `handoff_path`, and
   `deadline_at`.
2. `reviewed_head_sha`, the full lowercase 40-hex commit reviewed after the
   Phase-5 artifact checks and final clean-worktree gate.
3. `spec_artifact`, with exactly `kind: design-spec`, repository-relative root
   `path`, the four integer metrics, and `budget_status: within_budget`.
4. `plan_artifact`, with exactly `kind: implementation-plan`, repository-relative
   root `path`, the same four metrics, and `budget_status: within_budget`.

The prompt contains no artifact contents, task-member paths, review transcript,
conversation summary, alternate worktree, reconstructed lifecycle field, or
authorization flag. Repository bindings are resolved from the delegated owner's
worktree instead of being copied into a second continuation schema.

Before reading either artifact, the fresh owner verifies that the worktree and
branch match the envelope, that its clean current HEAD equals
`reviewed_head_sha`, and that both roots are tracked at that exact commit. It
independently checks both roots with the artifact budget module and compares all
four metrics with the prompt. It adopts the envelope rather than calling
direct-owner and begins at Phase 6.

After validating SDD, the owner records Phase 6 with a self-contained remainder
and requires `delegate`; that action is fulfilled by the existing fresh Phase-7
ship owner, never another issue owner. After the ship report or any execution
stop, it validates the ship-summary candidate, records Phase 7 with the exact
finish command as a self-contained ledger-only remainder, requires `delegate`,
and sends only that command to the existing bookkeeper route. The bookkeeper
calls `finish` with the same run and attempt and relays canonical stdout; the
fresh issue owner returns those bytes unchanged.

The fixed report contract is therefore the existing closed ship-summary object,
not a new delegation result:

```json
{
  "issue": 74,
  "state": "merged | stopped | failed",
  "pr_url": "<url or null>",
  "merge_sha": "<sha or null>",
  "issue_closed": false,
  "discussion_items": [],
  "detail_state": "none | present | unpublished",
  "report_path": null,
  "notes": "<bounded notes>"
}
```

The field values must satisfy the existing ship-summary validator's state
matrix; the template above describes types, not permission to combine arbitrary
values. Non-empty detail remains behind the single report path. The earlier
controller validates the returned bytes at that boundary, relays the canonical
bytes unchanged, and stops. It never calls `finish` a second time.

### Pre-worktree handoff resume

An unexpired module-owned direct attempt in `handed_off` state may resume when
its completed phase is 0 and the worktree observation contains the exact
ledger-recorded absolute path with state `absent`. The durable handoff file must
still pass its existing validation. The module then performs the same resume
transition used for a matching worktree: it keeps the run, attempt, owner,
worktree reservation, start time, fixed deadline, and handoff path; changes the
attempt back to active; appends one resume launch; persists; and returns the
ordinary complete owner envelope with `launch_kind: resume`.

The absent fact authorizes only reaching the existing Phase-1 materialization
rule. The returning owner creates the exact reserved path from
`origin/<integration-branch>`, adopts no alternate candidate, and then records
Phase-1 progress on the same attempt. An absent path never authorizes an active-
owner takeover, a retry, a new run, a dispatcher-owned resume, or a handoff after
Phase 0. Those paths retain their existing matching-worktree or absent-candidate
requirements.

A recorded path mismatch, wrong-branch occupancy, missing recorded observation,
or candidate without the exact recorded reservation remains non-resumable and
leaves lifecycle bytes unchanged. Supplying an extra candidate can never change
the owner response's worktree: only the recorded reservation is authoritative.
Existing handed-off resume with `matching_issue_branch` is unchanged.

### Documentation and compatibility

Implementation appends explicit amendment markers to the accepted issue-33
phase-order statement and the accepted issue-73 acquisition statement in the
same commits that make the direct-only order and Phase-0 absent-reservation
resume true. These are point-in-time decision records, so the markers preserve
their original claims and history rather than making an unshipped design read as
live behavior or silently rewriting it.

No glossary or ADR tree is created. The repository has no governing domain map,
the terms are lifecycle implementation terms already defined by accepted specs,
and this design plus the two explicit amendments are the established decision
home.

## Test seams

- **Progress CLI seam:** drive the public progress command with a reserved direct
  run and assert the full precedence matrix, persisted action, and reopened-state
  validation. Cases cover self-contained with missing and near-ceiling usage;
  self-contained plus fresh-start inputs; fresh-start with missing and
  near-ceiling usage; one missing measure plus the other near ceiling; missing
  usage while context is required; no-context insufficient artifacts; and the
  ordinary measured continue case.
- **Compatibility seam:** replay the existing dispatcher-owned and explicitly
  durable interactive progress fixtures and compare canonical response and
  ledger bytes with their base-revision expectations. Corruption fixtures prove
  that direct and non-direct action derivation cannot be swapped without a loud,
  mutation-free validation failure.
- **Direct-owner CLI seam:** acquire an absent candidate, persist a Phase-0
  handoff, reacquire with the exact recorded path as absent, and assert the same
  run, attempt, owner, deadline, handoff, and worktree plus one resume launch.
  Snapshot tests keep mismatch, wrong-branch, missing-recorded, and alternate-
  candidate cases mutation-free, and retain the existing matching-worktree
  resume fixture.
- **Real-filesystem seam:** use a temporary Git repository with `origin/main` to
  perform the complete absent-candidate acquisition, Phase-0 handoff,
  absent-recorded reacquisition, exact-path `git worktree add`, and Phase-1
  progress sequence. Assert that no second run or attempt appears and never
  fabricate `matching_issue_branch` before Git actually materializes the path.
- **Skill contract seam:** pin the ordered Phase-5 commit/check/progress/delegate/
  dispatch sequence, the complete envelope, reviewed HEAD, and two
  root-plus-metrics blocks; pin the fresh owner's independent checks, Phase-6
  ship delegation, Phase-7 ledger-only delegation, and canonical terminal relay.
  Negative assertions fail if the pre-rollover controller can invoke SDD, edit
  implementation, reacquire, create an attempt, call terminal finish after
  delegation, or continue after the delegated report.
- **Repository gates:** the deterministic agent-workflow suite proves the module
  and skill contracts, and the repository build verifies that the updated helper
  and installed skill documentation are distributed together.

## Out of scope

- General scheduling, queues, polling, daemons, process-liveness detection, or a
  new run type.
- Changing dispatcher-owned, explicitly durable interactive, or ledger-free
  interactive action selection or continuation behavior.
- Changing phase-input fields, action enums, attempt limits, fixed deadlines,
  terminal summaries, direct-owner authorization, or lifecycle schema version.
- Moving Git, tracker, worktree creation, owner dispatch, or artifact reading
  into the lifecycle module.
- Allowing an absent worktree after Phase 0, repairing a deleted worktree,
  substituting a candidate for a recorded reservation, or generalizing worktree
  recovery.
- Redesigning SDD, Phase-7 shipping, artifact budgets, review-detail publication,
  or unrelated artifact policy.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | For module-owned direct runs, use the complete order `delegate` → eligible `fresh_start` → any known near-ceiling `handoff` → no-context `handoff` → `continue`; missing usage alone may continue only when context is required to reach the next durable seam. | Issue 74 requires artifact-first direct selection and names missing and near-ceiling cases; issue 33's accepted order establishes that disposable artifacts beat usage handoff, while the next mandatory progress call bounds the missing-usage continuation. | Put missing/ceiling before delegation, or always hand off on missing usage — the first defeats mandatory rollover and the second can never advance a direct run whose host does not expose usage; put near-ceiling before eligible fresh start — writes a handoff for a conversation already disposable from committed artifacts. |
| D2 | Derive the direct-only selector from the reserved run ID inside the lifecycle module, keep public progress inputs and persisted schema unchanged, and re-derive persisted actions with that same identity. | Issue 73 makes module-owned direct identity authoritative; issue 47 defines `workflow-state` as the deep lifecycle module and The Bar gives policy one home. | Add a caller-supplied mode flag or duplicate selection in skill prose — introduces forgeable authority or a second policy implementation and changes dispatcher bytes. |
| D3 | Make committed, freshly validated Phase-5 artifacts the mandatory direct-autonomous rollover: persist `delegate`, dispatch exactly one fresh issue owner, and forbid the earlier controller from SDD, implementation edits, reacquisition, retries, or a second terminal write. | Issue 74 fixes Phase 5 as the earliest self-contained implementation seam; issue 49 makes validated artifact roots the producer/consumer seam and excludes transcripts. | Roll on usage only, delegate before review/commit, or let the parent implement as fallback — transfers incomplete state or preserves the exhausted-controller failure mode. |
| D4 | Give the fresh owner the unchanged complete direct-owner object plus only current design/plan root-and-metrics objects; it revalidates from disk, executes Phases 6–7, persists `finish`, and returns the existing canonical ship-summary for byte-for-byte relay. | Issue 74 requires the same lifecycle envelope and validated artifact roots; existing SDD and ship-owner contracts already use root-plus-metrics inputs and a fixed ship-summary terminal seam. | Invent a transcript handoff, partial identity, task-member list, or new implementation-result schema — expands the interface, can reconstruct the wrong owner, and duplicates established bounded contracts. |
| D5 | Resume an exact absent recorded reservation only for an unexpired handed-off module-owned direct attempt at Phase 0, preserving every identity/deadline/path field and leaving Phase 1 as the sole materializer. | Issue 74 identifies the pre-worktree handoff deadlock and explicitly preserves exact-path Phase-1 creation; issue 73 keeps lifecycle code free of Git and makes the recorded path authoritative. | Treat absence as retry/new-run input, accept it for later phases or active takeover, or adopt an alternate candidate — spends lifecycle allowance, can resume after retained work vanished, or breaks reservation identity. |
| D6 | Test through the progress/direct-owner CLI, reopened durable bytes, one real Git worktree sequence, and installed skill contracts; add no glossary or ADR tree. | Issues 14/47 and The Bar require observable restart-safe behavior; issue 73 D9 records `.claude/specs` as this repository's decision home in the absence of a domain-doc tree. | Test private selector branches only or bootstrap new documentation architecture — misses the public persistence seam or creates unrelated structure. |
| D7 | Split the installed rollover contract test into mandatory-transfer, fresh-owner, and earlier-controller-stop seams; assert the exact three-block nested field sets and reject any affirmative post-delegation permission outside validate, relay, and stop. | Native Phase-5 finding B1 showed that mixed presence/order anchors could pass with extra transfer fields or prose authorizing forbidden parent actions; D3–D4 define closed interfaces and The Bar requires fail-loud tests that can fail. | Keep one mixed substring test — it cannot distinguish the delegated owner from the earlier controller or prove the continuation is closed. |
| D8 | Test an exact recorded `absent` reservation together with an alternate absent candidate and require ordinary resume to preserve the recorded owner/worktree; keep candidate-only and mismatched observations non-resumable and mutation-free. | Native Phase-5 finding S2 exposed the missing mixed-observation case; D5 and the issue criteria make the recorded reservation authoritative even when an extra candidate is supplied. | Test only exact-recorded success and candidate-only/mismatch failures separately — leaves candidate precedence unproved when both facts arrive together. |
| D9 | Include mechanical-only module-owned direct autonomous runs in the mandatory Phase-5 rollover; the fresh owner uses the existing mechanical Phase-6 mechanic/reviewer route, while mechanical ordering and ownership stay unchanged only for other acquisition routes. | Native Phase-5 discussion D1 resolved the design's identity-and-checkpoint rule consistently with D3: every qualifying direct-auto run rolls before implementation, regardless of implementation lane. | Exempt mechanical direct-auto work or redesign its Phase-6 route — the first weakens the mandatory ownership seam and the second changes behavior the issue does not target. |
| D10 | Reverse D4's three-field-only continuation: add the exact reviewed full HEAD SHA and require equality before artifact reads, while retaining the unchanged owner and two root-and-metrics objects. | Ship correctness finding COR-002 showed that cleanliness plus artifact size metrics cannot identify reviewed content; The Bar requires evidence to bind the state it authorizes. | Trust any clean HEAD or use artifact metrics as content identity — both can admit equal-size or unrelated clean changes that Phase 5 never reviewed. |
| D11 | At the delegated owner's Phase-6 gate, fulfill persisted `delegate` with the existing fresh ship owner; at Phase 7, make the exact finish command the self-contained ledger-only remainder and fulfill `delegate` with the existing bookkeeper. | Ship correctness finding COR-001 exposed the collision between the mandatory every-phase gate and the generic issue-owner delegate route; the existing ship-owner and ledger-only routes already match the two remaining responsibilities. | Skip progress, report false booleans, or dispatch a second issue owner — violates durable phase accounting, falsifies state, or reintroduces the ownership churn this issue removes. |
