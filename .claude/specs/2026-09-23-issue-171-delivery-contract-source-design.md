# Delivery contract source and legacy-run continuity — issue 171

Decision for [#171](https://github.com/fagenorn/nix-config/issues/171), 2026-09-23.
Status: delegated (autonomous `--auto`). Builds on the #151 delivery design
(`2026-09-21-issue-151-delivery-reconciliation-design.md`, "SPEC151"), whose
wire tables and D1–D22 still bind except where a row below says it refines or
supersedes one.

## Problem

Interface 2 cannot run a single issue end to end, so neither `/from-issue <n>
--auto` nor `/orchestrate-issues` works:

1. **No contract source.** `direct-owner` and `control` require a
   `delivery-contract/v1` plus its initial `authorization-intent/v1`, but no
   component builds them. Every direct acquisition stops at a
   `delivery_contract` requirement; an all-null control call returns
   `contractless_control`, which reports every issue `queued` and returns
   `finalize` even while an owner is live. Beyond acquisition, owners would
   have to hand-compose sha256-derived ids for every scope and observation, and
   the ship owner's return shape has no defined conversion into
   `ship-summary/v2`.
2. **The PR number cannot be authorized.** A `pr_opened`/`pr_merged`
   observation is admitted only when an intent names that PR literally. The
   number does not exist at acquisition, and checkpoint/summary cannot append
   intents, so no truthful run can observe its own merge.
3. **The 2→3 migration strands v1 owners.** Every mutating call migrates a
   schema-2 ledger, including a v1 owner's own legacy `finish`. After that the
   legacy transport refuses ("read-only for schema 3") and the summary transport
   refuses a contractless issue, so a live v1 owner can only suspend. That is
   how the nodocom run ended with three merged PRs and no recorded results.
4. **Control ignores `forge`.** Control validates the forge map and never
   reads it, so a PR that merged while its attempt was suspended is resumed
   rather than reconciled.
5. **The skills still describe interface 1.** They show v1 requests, the v1
   bootstrap, v1 owner envelopes and the legacy 9-key ship return. The only v2
   text is an appendix that names the pieces without defining them.
6. **Auto mode refuses the lifecycle helper.** The classifier refused
   owners' `finish` calls and a v2 `init-run`.

## Solution

- **Builder.** Add one read-only, deterministic builder verb to `workflow-state`
  (the trusted controller boundary SPEC151 assumes). It derives the contract and
  initial intent from resolved project policy plus invocation facts. It also
  seals every other delivery fact an owner submits, so no agent ever composes a
  digest.
- **PR binding.** Implement SPEC151's declared "slot PR" narrowing, so the
  initial intent covers "the PR opened for the reviewed slot" and no
  successor intent is needed.
- **Contract-last acquisition.** Contractless calls never create a run or
  dispatch. They apply only lifecycle transitions and ask for the contract where
  a dispatch would follow.
- **Legacy continuity.** Legacy `finish` stays usable on migrated contractless
  issues, and control leaves live contractless custody alone.
- **Forge reconciliation.** Control reconciles a merged forge for issues
  without a live owner.
- **Skills and permissions.** Rewrite every lifecycle skill for interface 2
  around one delivery loop, and allow the two lifecycle helpers under auto
  mode.

## Decisions

### 1. The delivery builder (per D3, D4, D5, D6)

`workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind>
--input <absolute-json-path|->` prints the canonical bytes of the sealed object(s)
and exits 0; any refusal exits 2 with nothing on stdout. It takes no lock, reads
no ledger, reads no clock (time is an input), and writes nothing. A new private
build module beside the delivery projection holds all derivation. It loads
lexically under the same fail-closed source/installed rules as the delivery
runtime. Workflow-state only dispatches the verb. Each output passes
`validate_delivery_object` before printing. Inputs are closed objects: unknown,
missing or mistyped keys refuse. The kind set is closed and fails loud:

| Kind | Caller supplies | Builder derives |
|---|---|---|
| `contract` | `issue`, absolute `worktree`, `source_kind`, `source_reference`, `now` | `{contract, initial_intent}` from `resolve-project resolve` at `--repo-root` (the only kind that reads policy) |
| `initial-intent` | `contract` | the contract's initial intent, regenerated and checked against its id and digest |
| `scope` | `contract`, `stage_id` | the stage's actual `scope-tuple/v1` |
| `selected-output` | `contract`, `head`, `tree`, `acceptance_ref`, `review_ref`, `test_ref` | `selected-output/v1` for the contract's reviewed slot |
| `observation` | `contract`, `observation_kind`, the kind's observed facts, `source_kind`, `source_reference`, `observed_at`, `evidence` | `delivery-observation/v1`; every member the contract determines (project, repository ids, branch, base, worktree path, issue) is filled from the contract, and `evidence_digest` is sha256 of the evidence bytes |
| `authority-observation` | `contract`, `scope_id`, `launch_id`, `authority_kind`, `verdict`, `reason_code`, `observed_at`, `evidence` | `authority-observation/v1` |

The observed facts per observation kind are only what a probe returns:

- `branch_published`: the selected head.
- `pr_opened`: PR number, URL and head.
- `pr_merged`: the `pr_opened` facts plus the merge SHA.
- `tracker_closed`: close reason and observation identity.
- The three absence kinds: nothing, because their targets come from the contract.
- `selected_output`: the sealed selection.
- `implementation_delivered`: the selection, the merge SHA, the integrated ref
  and the merge observation id.
- `cleanup_complete`: the absence observation ids, the detail pointer and the
  read evidence.

**Contract derivation from policy (D4).** The contract is derived as follows.

- **Project.** `project_id` is resolve-project's `project.id`. `provider` is
  `bindings.tracker.kind`. `repository_id` and `repository_slug` are both
  `bindings.tracker.repo_slug`. The only supported tracker kind is `github`;
  any other refuses.
- **Branch and base.** The branch is the worktree path's final component. It
  must match `bindings.vcs.branch_pattern` for the issue, with or without the
  worktree prefix, which is the existing AUTO.md `expected_branch` rule. The
  base is `vcs.integration_branch`.
- **Obligations.** All four obligations are `required`.
- **Stages.** The stages form a linear chain whose ids are the stage kind names:
  `select_reviewed_output → publish_branch → open_pr → merge_pr →
  close_tracker → [delete_remote_branch iff vcs.merge.delete_branch] →
  remove_worktree → delete_local_branch`.
  - The first four stages target one commit slot, `reviewed`. Its constraints
    are the project fields plus branch, base, deliverable class `source`, and
    slot-bound data with classification `source` and a named audience of
    `canonical_digest({"repository": <slug>})`, meaning "readers of this
    repository", which is truthful for public and private repositories alike.
  - The cleanup and close stages take literal targets: the issue number,
    the branch, and the worktree.
  - Worktree requirements: `matching_required` through `merge_pr`,
    `not_required` for close and remote deletion, `cleanup_target` for
    worktree and local-branch removal.
  - Every stage is `retryable: true`.
- **Deliverable.** `{id: "issue-<n>", summary: "Deliver <slug>#<n>"}`, which
  carries no issue content, so orchestrate's content boundary holds.
- **Provenance and initial intent.** Provenance is
  `{kind: source_kind, reference: source_reference, digest:
  canonical_digest(policy fields used + issue + worktree + source),
  created_at: now}`.
  - The intent's source is the same kind, reference and digest, with
    `issued_at = now`, `expires_at: null` and revocation key
    `<project_id>#<issue>@<now>`.
  - It declares one scope per stage.
  - Because every intent member is a function of the contract, `initial-intent`
    can regenerate it.

**One scope vocabulary (D5).** Declared scopes and actual scopes come from the
same builder function. They are built from the contract stage and never copied
from an intent object, so exact matching can only disagree when inputs differ.

- **Principal:** `{kind: "issue_owner", stable_id: "<project_id>#<issue>"}`.
  It is stable across attempts, launches and remainders.
- **Risk:** the stage's effect.
- **Endpoint:** `none`, except `remove_worktree`, which uses the literal worktree.
- **Spend:** `none`.
- **Targets:**
  - Slot stages use the slot form for `output_ref`, plus the slot's data
    reference.
  - `pr_ref` is the slot form for `open_pr`/`merge_pr` and `none` for every
    other stage.
  - Literal stages use `output_ref` `none` and data `none`.
- **Selection.** `selected-output` takes its data identity from
  `canonical_digest({"kind":"git-tree","value":<tree>})`.
  - Its evidence ids are `acceptance:<acceptance_ref>@<head>`,
    `review:<review_ref>@<head>` and `test:<test_ref>@<head>`.
  - Its evidence digest covers those refs and the head.
  - The skills fix the refs as follows: the spec root for acceptance, the
    durable review report path (or the literal review state) for review, and
    `checks` for test.
  - A relaunched owner therefore re-derives the identical selection, and a
    differing one is refused by the reducer as a conflicting selection.

**Source kinds (D6).**

- An explicit issue list, or a direct `--auto`, uses `explicit_user`.
  - Direct reference: `invocation:/from-issue <n> --auto`.
  - Orchestrated reference: `invocation:/orchestrate-issues <numbers>`.
- A `--label`/`--milestone` sweep uses `standing_repository`, with reference
  `sweep:<label|milestone>:<value>`. This matches its existing
  `human_directed: false`, and it therefore cannot satisfy D21's
  `human_transient_retry`.
- No initial intent uses `parent_handoff`.

### 2. PR binding through the reviewed slot (per D7)

A scope target's `pr_ref` gains the form `{kind: "slot", slot_id}`. It is valid
only when `output_ref` is the same slot, and it means "the pull request carrying
that slot's reviewed output". Matching stays exact: a declared slot `pr_ref`
admits only the same slot form, and every owner requests the slot form.

PR admission changes in one place. A declared open/merge scope whose `pr_ref` is
the stage's slot admits the PR number of a `pr_opened` observation that matches
the open stage on repository, head (the selected head) and base.

The binding is immutable: a second distinct matching `pr_opened` refuses
through the existing conflicting-stage-observation rule. Merge still requires
a merged observation that matches that opened PR. The existing literal `pr_ref`
path is unchanged.

This implements SPEC151's narrowing table ("slot PR/output"): binding the exact
value narrows the contract and demands no new grant. Ordinary runs therefore
never mint a successor intent.

### 3. Acquisition and the contract lifecycle (per D8, D9, D10)

**The contract binds custody's worktree (D8).** Under a contract, the custody
worktree is the contract's `remove_worktree` literal, and the branch is its
final component. Any spawn, resume, retry or recover whose worktree differs
refuses with no write. The helper selects:

- the recorded path when it is observed `matching_issue_branch` or `absent`
  (the absent path is re-created in place);
- a reserved candidate for a first spawn only, and only when it equals the
  contract path.

A mismatched path refuses; there is no relocation. Callers build the contract
with the issue's recorded worktree when one exists, otherwise with their
reserved candidate.

**Direct acquisition: contract last (D9).** A `direct-owner` request with a null
contract, on an issue with no installed contract, never creates a run and never
dispatches. On an existing contractless run it applies the same lifecycle-only
transitions control does (reap, tracker halt, forge reconcile) and replays
terminals. It returns one of three things:

- the policy's own `observe` requirements (tracker, forge, recorded or candidate
  worktree);
- a terminal replay or reconciled terminal, which needs no contract;
- otherwise, exactly the `delivery_contract` requirement where a dispatch would
  follow, with the selected run's id or null.

The acquirer then builds the contract, adds the initial intent as
`authorization_intents`, and repeats the call with every retained fact. This
refines SPEC151's "no contract yields only the contract requirement": no contract
still yields no owner/remainder action and no new run, but legacy observations
come first.

**Null contract means "none supplied" (D10).** This rule applies to both
control and direct:

- **Contracted issue.** For an issue whose ledger already holds a contract, a
  null request contract means the installed contract governs. A supplied
  contract must equal the installed one, or the request refuses (the contract is
  immutable). Facts, scope or a D21 recovery still require the non-null
  installed contract before the lock. A controller takes it from the dispatch
  action it executed.
- **Contractless or absent issue.**
  - With a null contract, the issue runs lifecycle-only policy: reaping,
    tracker halts, forge reconciliation, idle. The would-be dispatch becomes
    idle, and the summary carries the contract requirement.
  - A supplied contract is installed only by the transition that creates or
    relaunches custody for that issue (spawn, resume, retry, recover). Until
    then it is validated context only, never stored.

The `contractless_control` shortcut is removed, and control never fabricates
`queued`/`finalize` for issues with ledger state. Delivery transitions run only
for issues that are contracted or being installed.

`init-run`'s bootstrap requirements gain nullable `contract_digest`. An adapter
therefore knows at start which recorded issues still need a contract. It
supplies a contract per issue until a summary shows its digest, then sends null.
The contract it builds is process-local request data and is never persisted.
When the builder refuses an issue (for example, a legacy worktree name outside
the branch pattern), the adapter sends null for it and reports the refusal.
That issue then stays lifecycle-only.

### 4. Legacy custody after the 2→3 migration (per D11, D12)

**Legacy custody.** Legacy custody is an issue whose `delivery` is the empty
sentinel. Every v2 custody transition installs its contract (§3), so empty
delivery identifies custody launched before interface 2.

**Legacy transport.**

- Legacy `finish --issue --attempt --result-file` is accepted on schema 1, 2 or
  3 whenever the issue is contractless and has no remainders. It writes only
  `attempts`/`outcome`, and the ledger keeps the helper's single schema-3 write.
- It is refused, with no write, on a contracted issue.
- `progress`, `suspend` and `check-launch` already work on schema 3 and are
  unchanged.

**Migration.** Migration-on-write stays. There is no schema-2 writer and no
bridge, so a v1 owner that meets a ledger another call already migrated simply
continues.

**Control and legacy issues.**

- Control never installs a contract onto live contractless custody that stays
  live in that call: it stays idle.
- A contract lands only on a legacy issue's relaunch.
- Terminal legacy results are never promoted into delivery truth.

**Wire.** A control summary with a null `contract_digest` may carry non-null
legacy custody. It still has no pending stages, exactly the contract
requirement, and no action for that issue. This and the other wire changes are
refinements made in place within interface 2 (D12).

### 5. Control consumes `forge` (per D13, D14)

Control passes each issue's forge observation into both policy passes. A merged
forge reconciles the latest attempt only when two conditions hold:

- Nobody holds live custody: the attempt is not `active` and unexpired,
  unless a current owner-unavailable fact names its launch.
- The attempt is nonterminal or retryable, which is exactly the set direct can
  reach.

Reconciliation writes the existing truthful `merged`/`superseded` closeout
(the detail pointer is preserved and `issue_closed` is false). An owner-verdict
terminal is never overwritten, and a live owner's later `finish` is never raced.

For a contracted issue whose delivery is still pending, reconciliation also
creates remainder 1 when capacity allows. This generalizes direct's
historical path to control. Control returns it as a `delivery_remainder` action.
A contractless issue gets only the lifecycle closeout. The forge triple never
becomes a `pr_merged` observation.

**Remainder minting on finish (D14).** A `terminal_failed` finish mints
remainder 1 only when the contract's selection stage is observed. Before
selection, a failure belongs to the implementation retry lane. Without this
rule, a Phase-0 stop would spawn a delivery remainder that blocks the retry,
because at most one nonterminal custody record may exist. Forge reconciliation
still mints remainder 1 before selection, because a merged PR means delivery is
already in progress.

### 6. Envelopes and the one delivery loop (per D15, D16, D17)

**Owner envelopes (D17).** The v2 owner envelope is one validated
interface-2 `owner` workflow-response object:

- **Direct.** The acquirer adopts the object verbatim.
- **Orchestrated.** The adapter projects a control `spawn|resume|retry` action
  into the object. It renames `id` to `action_id` and `kind` to `launch_kind`,
  and adds `kind: owner`, `interface_version: 2`, `ledger_repo_root` and
  `run_id`. The object travels in the owner prompt as canonical JSON, and the
  owner validates it at the `workflow-response` boundary before use.
- **Remainder.** The remainder envelope is the validated `delivery_remainder`
  object, verbatim.
- **Phase-5 continuation.** AUTO.md's continuation carries the v2 owner object.

**Phase-7 handoff (D17).** Phase 7 uses `ship-handoff/v2`:

- `authorization_intents` is the builder-regenerated initial intent, plus
  the chain digest.
- The historical id arrays and `selected_outputs` are the ones the author
  actually holds (empty at a first ship).
- `requested_scope` is null.
- The handoff carries the full contract and intent, so its `validate-report`
  boundary reads under the `workflow_responses` wire bound, not the phase-report
  bound (D28).

The ship owner's first ledger act is a null-scope `checkpoint-delivery`, which
reports the ledger's current pending stages and requirements. The ledger, not
the handoff, is current truth.

**The delivery loop (D15).**

- **Pre-selection review publication stays as it is.** This covers ship-issue's
  sync, push, PR open for review, review-fix pushes and CI. It is governed by
  the native guard, repository policy and the existing `check-launch` fence
  before every forge write. These effects precede selection, so no stage is
  ready for them.
- **Selection at the pre-merge gate.** Selection is immutable, and a later
  implementation retry cannot deliver a different head under the same contract.
  Selection therefore waits for the final CI-green head. There, the ship owner
  builds the selection and the now-true `selected_output`, `branch_published`
  and `pr_opened` observations. It checkpoints them with the built scope for
  `merge_pr`, the post-fold ready stage. Selection is observation-only, because
  its effect is that checkpoint write.
- **Each post-selection effect** (merge, issue close, worktree removal,
  local-branch deletion) runs one cycle:
  1. The scope proposal is checkpointed.
  2. The owner requires the validated echo to equal the scope.
  3. `current-launch` fence.
  4. The effect runs.
  5. `current-launch` fence again.
  6. The next checkpoint carries the effect's observation, one
     `authority-observation` for the launch that ran it, and the next stage's
     scope.
- **Observation-only stages.** A stage already made true is recorded by
  observation alone, without a proposal: remote deletion by `--delete-branch`,
  and closure by the merge.
- **Denials.** A guard, host or provider denial is checkpointed and becomes the
  reducer's `human_gate` suspension. The owner then prints the re-entry line
  and stops.

**Who writes what (D16).**

- Under implementation custody the ship owner writes only
  `checkpoint-delivery`, never `finish`. This replaces ship-issue's "never
  writes workflow-state".
- After the last effect, the observations that complete delivery do not go into
  a checkpoint, because `check-launch` reports an attempt inactive once delivery
  is complete. They are the last stage's absence, `implementation_delivered`
  and `cleanup_complete`, and they ride the ship owner's returned
  `ship-summary/v2` (`delivery_complete`, with the legacy `merged` row as
  `historical_owner_result`). Failures return `terminal_failed` with a
  legacy `stopped`/`failed` row and the partial observations.
- from-issue validates that summary, runs `check-launch` and writes
  `finish --summary-file`.
- A remainder owner is ship-issue in remainder mode, entered with the
  `delivery_remainder` envelope. It runs the loop from the ledger's ready stage:
  selection from the PR head when selection is pending, and the merge gate when
  merge is pending. It writes its own `finish --summary-file`, because it
  holds that custody.
- from-issue gains a `delivery_remainder` response branch that launches that
  owner. Orchestrate dispatches the `delivery_remainder` action to it.

### 7. Skill rewrite map

These changes are all prose plus contract-test pins; no skill keeps an
interface-1 request, response or legacy terminal instruction for new runs.

- **orchestrate-issues:**
  - §2: `workflow_bootstrap` with custody, `contract_digest` and a
    per-issue forge observation at the issue-branch prefix.
  - §3: the exact v2 request, with every issue-keyed map and the per-issue
    contract rule of §3.
  - §4: the closed action set plus `delivery_remainder`, the projected owner
    envelope, and a remainder-owner dispatch.
  - §5: reporting from v2 summaries.
  - The trailing appendix is folded in, and evals 1 and 2 are re-expressed.
- **from-issue SKILL.md:**
  - Dispatcher route = the validated owner object.
  - The v2 direct request example and loop of §3.
  - Observe accepts the delivery requirement kinds.
  - The `delivery_remainder` branch.
  - Durable interactive control is v2.
  - The terminal procedure consumes the ship owner's `ship-summary/v2`.
- **AUTO.md:** the v2 continuation object, and a bookkeeper that runs
  `check-launch` then `finish --summary-file`.
- **ship-handoff.md:** a `ship-handoff/v2` prompt and a `ship-summary/v2` return.
- **ship-issue:**
  - The pre-merge selection gate and the post-selection loop.
  - Remainder mode.
  - The D16 writer rule.
  - REVIEW/HUMAN-GATE appendices point at the loop instead of restating it.

Every lifecycle call is one simple command (D22). The request, checkpoint,
summary or builder input goes to the helper on stdin through a heredoc, via a
`-` input path. The command is optionally piped into or out of `artifact-budget
validate-report --input -`. The helper is named by bare name or the
`~/.agents/bin/` form only. This replaces the mktemp/trap request-file pattern
and CLAUDE.md's sentence about it.

### 8. Auto-mode allow rules and single-command calls (per D18, D22)

Four entries are added to the managed `permissions.allow`, taking the list
from 18 to 22:

- `Bash(workflow-state:*)` and `Bash(~/.agents/bin/workflow-state:*)`;
- `Bash(artifact-budget:*)` and `Bash(~/.agents/bin/artifact-budget:*)`.

Both helpers are lifecycle infrastructure. Their only writes are validated
ledger transitions beneath `.superpowers/workflows/`, so neither can alter code
or a remote. Allowing `artifact-budget` covers the mandated
`helper | artifact-budget validate-report` pipeline, whose segments must all
match. Every helper input flag (`--request-file`, `--checkpoint-file`,
`--summary-file`, `--result-file`, `--input`) accepts `-` for stdin. A call
therefore has no mktemp/trap/cat segments that would fall back to the
classifier. The `PreToolUse` guard still adjudicates the four forge verbs
unchanged. The permission-guard test's expected list and CLAUDE.md's entry count
and request-file sentence are updated with it.

## Acceptance criteria

**Part 1: contract source.**

- AC1.1 — `build-delivery --kind contract` over a synthetic resolved project:
  - The output validates, and `initial_intent` has the contract's initial id and
    digest.
  - Identical inputs produce identical bytes.
  - The branch equals the worktree basename.
  - It refuses, with exit 2 and empty stdout: a non-`github` tracker, a basename
    outside the issue's branch pattern, a relative worktree, and an unknown or
    missing input key.
- AC1.2 — Each builder `scope`, proposed through `checkpoint-delivery` when its
  stage is ready, is echoed and covered by the initial intent. The requirement is
  `native_evaluation_required`, never `authorization_intent_required`.
- AC1.3 — A fresh direct acquisition returns, in order, `tracker`, `forge_pr`,
  `candidate_worktree`, then `delivery_contract`, with no run directory or state
  created. Resending with the built contract and intent returns `kind: owner`,
  with the contract installed and `worktree` equal to its literal.
  - A contract naming another worktree refuses without a write.
  - A later null-contract re-entry is governed by the installed contract.
  - A contractless call on a terminal legacy direct run replays it.
  - A contractless call on a suspended legacy direct run whose PR merged
    reconciles it to terminal `merged`.
- AC1.4 — Bootstrap reports `contract_digest`.
  - Control with a built contract for a fresh issue spawns it with that contract.
  - Null for a contracted issue uses the installed one.
  - A different contract refuses without a write.
- AC1.5 — Under a slot-`pr_ref` intent, `pr_opened` then `pr_merged` become
  observed with no successor intent. A second distinct matching `pr_opened`
  refuses without a write. The literal-`pr_ref` model tests stay green.
- AC1.6 — Using only builder outputs, one implementation custody completes the
  §6 loop:
  - selection → merge → close → worktree → local branch, each post-selection
    stage proposed, echoed and observed;
  - then a `delivery_complete` finish.
  - The `ship-summary/v2` carrying the completing observations passes
    `validate-report --boundary ship-summary` within the report wire bound.
- AC1.7 — A `terminal_failed` finish before selection mints no remainder, and
  control then offers the implementation retry. After selection, it mints
  remainder 1.

**Part 2: legacy runs.**

- AC2.1 — Legacy `finish` persists attempt and outcome on a schema-3
  contractless issue, and refuses on a contracted issue with a byte-identical
  ledger.
- AC2.2 — Two concurrent legacy finishes on one schema-2 ledger both succeed and
  persist, which re-pins `concurrent_finish`.
- AC2.3 — Control with a live contractless attempt, with the contract null or
  supplied:
  - leaves the attempt idle and installs nothing;
  - summarizes it with its custody, a null digest and the contract requirement;
  - emits no action for it.
- AC2.4 — An all-null control call on a run with a live owner never reports that
  issue `queued` and never finalizes over a live deadline.
- AC2.5 — **Regression:** a schema-2 run with two live v1 attempts is migrated by
  a v2 `init-run`, a v2 `control` and one owner's `progress`.
  - The other owner's `check-launch` stays `current: true`.
  - Its legacy `finish` persists a `merged` result.
  - The next control summary reports that issue `merged`.

**Part 3: forge.**

- AC3.1 — A suspended attempt with a merged forge becomes `merged`/`superseded`
  with its detail preserved.
- AC3.2 — An active, unexpired attempt with a merged forge stays active, and its
  owner's later finish succeeds.
- AC3.3 — A terminal owner verdict survives a merged forge unchanged.
- AC3.4 — A contracted reconciled issue gets remainder 1 as a
  `delivery_remainder` action within capacity.

**Part 4: skills.**

- AC4.1 — The contract tests pin the §7 anchors: the v2 direct request keys,
  bootstrap `contract_digest`, the action set including `delivery_remainder`,
  the projected owner envelope, `ship-handoff/v2`, the `ship-summary/v2` return,
  ship-issue's writer rule and loop, and AUTO.md's v2 continuation keys.
  - No skill instructs an `interface_version: 1` request or the legacy result
    transport for a new run.
  - The orchestrate evals match.
- AC4.2 — Skill quick-validation passes for from-issue, ship-issue and
  orchestrate-issues.

**Part 5: permissions.**

- AC5.1 — `just show-claude-settings` lists exactly the 22 entries.
- AC5.2 — The guard test pins them, and the guard's adjudication tests are
  unchanged.
- AC5.3 — Each helper input flag accepts `-`. A heredoc-fed `control` and
  `finish --summary-file -`, piped through `artifact-budget validate-report
  --input -`, round-trip identically to the path form. A relative path still
  refuses.

## Test seams

Every seam below is an existing one (per D19):

- **Pure model facade** (`test_delivery_model.py`): slot `pr_ref` grammar,
  admission and conflict.
- **`workflow-state` subprocess round trips over synthetic ledgers and layouts**
  (`test_delivery_workflow.py`, `test_workflow_state.py`): the builder verb
  against a synthetic project root, acquisition, mixed control, legacy finish,
  forge reconciliation, the full loop and the regression. The builder is
  exercised only through its CLI; tests never import the private module.
- **`artifact-budget` CLI** (`test_artifact_budget.py`): the refined summary
  and bootstrap shapes, and the size of the loop's summary.
- **Skill text** (`test_workflow_skill_contracts.py`) and the orchestrate evals.
- **Settings** (`tests/test_claude_permission_guard.py` over the built
  settings).

Re-pins that follow from these decisions:

- `concurrent_finish` users;
- the schema-3 legacy-refusal test, which inverts to contract-keyed refusal;
- contractless-output tests;
- the failure-remainder round trip, which now observes selection first;
- the AUTO.md continuation keys;
- the direct-acquisition anchors.

Verification uses the project's commands, `nix-build` and
`agent-workflow-tests`.

## Out of scope

- **Repairing live ledgers already migrated.** SPEC151 forbids shipped source
  from touching them. Operator note: once the upgraded helper is active, a
  stranded v1 owner's legacy `finish` succeeds again. A suspended attempt whose
  PR merged reconciles on the next ordinary `control` call (or `direct-owner`
  call) that supplies its forge observation. No script and no bridge.
- **Successor-intent minting, revocation tooling and expiring intents.** The
  ordinary path needs none of them (D7).
- **Other deliverables and trackers:** a `tracker.kind` other than `github`,
  record deliverables (`deliver_repository_record`), and local-merge delivery.
- **Reordering ship-issue to review before publishing.** D15 records why.
- **#152 C.**
- **A live auto-mode demonstration.** Whether the classifier labels disappear
  can only be confirmed by a post-merge live run, as the 2026-08-17 design
  also noted.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | #171's own lifecycle runs ledger-free (no `workflow-state` ledger for this issue) | User decision relayed by the orchestrator: acquisition is blocked by this very bug | Acquire a ledger for #171 — impossible until this ships |
| D2 | All four parts plus the regression test ship in one PR | User decision ("All of #171 in one PR") | Split into contract-source / legacy / forge / skills issues — rejected by the user |
| D3 | The contract source is one read-only `workflow-state build-delivery` verb backed by a new private build module. It covers contract, initial intent, scope, selection, observation and authority kinds. | SPEC151:32-36 assumes a trusted controller that no code implements; the-bar DRY (one home per convention) and token economy (one CLI, one allow rule); the investigator's prior that LLM-composed canonical digests are the weakest boundary | Skill-composed JSON (hand-made sha256); the helper defaulting a null contract (bootstrap "no project policy is defaulted", SPEC151:34-35); a `resolve-project` projection (lacks invocation facts); a separate executable (second tool and allow rule for the same boundary); contract-only scope (owners still hand-seal every checkpoint, so end-to-end fails at finish) |
| D4 | The contract is derived from resolved policy: `repository_id` = the tracker slug; only `github` is supported; all four obligations required; a linear stage chain with remote deletion iff `delete_branch`; every stage retryable; the summary carries no issue content | bootstrap.md policy-only rule; the-bar YAGNI; SPEC151:21-22 (missing evidence never creates `not_applicable`) | Provider node id via `gh repo view` (a network read and a value policy does not carry); supporting `tracker.kind none` or record deliverables now (no caller) |
| D5 | One scope/evidence vocabulary lives only in the builder: per-issue `issue_owner` principal, risk = effect, a named repository audience, endpoint only for worktree removal, tree-based data identity, and head-keyed evidence ids fixed by skill-defined refs, so re-derivation is identical | Exact matching (SPEC151 narrowing table); the-bar DRY; a relaunched owner must re-derive selection without ledger reads | A per-attempt principal (breaks exact match across retries/remainders); `private`/`public` audience (visibility is not in policy and would lie for one of them) |
| D6 | Source kinds: explicit numbers, direct `--auto` and an explicit durable interactive request → `explicit_user`; label/milestone sweeps → `standing_repository`; `parent_handoff` unused by initial intents | Existing `human_directed` semantics; D21 `human_transient_retry` requires `explicit_user` | `explicit_user` for sweeps (claims per-issue authorization nobody gave); `parent_handoff` for orchestrated owners (describes transport, not authority) |
| D7 | A slot `pr_ref` binds the PR through the unique matching `pr_opened` observation, with no successor intent. This implements SPEC151's "slot PR" narrowing and answers "who mints the PR intent" with "nobody". | SPEC151:26-31 and the narrowing-table row "slot PR/output"; `subject_kind` already includes `pull_request`; checkpoint/summary cannot carry intents (SPEC151, the reducer) | A successor intent after `open_pr` (no mid-flight controller transport exists: `direct-owner` refuses a live owner, and the orchestrator sees no PR number without a human round trip); a checkpoint intent carve-out (contradicts SPEC151's trusted-source rule) |
| D8 | The contract binds the custody worktree and branch. A mismatched transition refuses without a write; an absent recorded path is re-created in place; no relocation. | Cleanup stages require literal targets (SPEC151 cleanup rules; "never permits relocation or candidate discovery"); the AUTO.md `expected_branch` rule | Letting the helper switch to a fresh candidate under a contract (the immutable contract would then name a dead path) |
| D9 | A contractless `direct-owner` call never creates a run or dispatches. It applies lifecycle-only transitions (reap, tracker halt, forge reconcile) to an existing contractless run, as control does (D10), replays terminals, and asks for the contract last, after legacy observations. Refines SPEC151:533-534. | Fixes finding 6 (terminal replay unreachable); the worktree must be known before the contract (D8); the grill found that a write-free variant would strand the repo's suspended legacy direct runs whose PRs merged | Contract first (the acquirer cannot know the recorded path of a run it may not know exists); fully read-only (legacy merged direct runs could never reconcile without inventing a contract) |
| D10 | A null contract means "none supplied": an installed contract governs; contractless issues run lifecycle-only; a supplied contract installs only at a custody-creating/relaunching transition; the bootstrap exposes `contract_digest`; `contractless_control` is removed | SPEC151 "contracts are context, not inferred authority"; a restarted adapter cannot reproduce a contract built at an earlier `now` | Always re-send the contract (restart breaks immutability); null ⇒ refuse (strands legacy issues); discover contract need from a first control call (a premature `finalize` ends the run) |
| D11 | Legacy `finish` is accepted on any schema for a contractless issue without remainders, and refused on a contracted one. Migration-on-write stays, with no legacy writer and no bridge. Supersedes 151 task-2's "legacy v1 summaries are read-only" and re-pins `concurrent_finish` to "both succeed". | Issue fix option 2; SPEC151:445-453 (legacy results remain historical claims, no truth promoted); SPEC151:494-497 (no bridge) | Do not migrate while legacy attempts are live (needs a schema-2 writer; misses finish, init-run and control; useless for already-migrated runs); ship the bridge (forbidden by SPEC151) |
| D12 | Refine interface 2 in place, with no version bump: a null-digest control summary may carry legacy custody; the bootstrap gains `contract_digest`; `pr_ref` gains the slot form | No v2 run has ever completed (acquisition was impossible); every refinement is additive to persisted grammar, so existing ledgers stay valid, including any run that installed contracts (#169's `orch-1635-1642`); SPEC151 "all callers cut over together" | Interface/schema version bumps (a second migration and compatibility surface for zero consumers) |
| D13 | Control reconciles a merged forge only without live custody, and only for a nonterminal or retryable latest attempt (never over an owner verdict). Contracted issues get remainder 1 as a `delivery_remainder`; contractless issues get the lifecycle closeout only. | SPEC151:366-371; direct's live-owner guard precedes its reconcile; the investigator's E5b (control resumed a merged suspended attempt) | Reconcile active attempts (races every owner between merge and finish); reconcile without minting a remainder (leaves contracted delivery pending forever); document "direct only" (orchestrated runs could never reconcile) |
| D14 | A `terminal_failed` finish mints remainder 1 only after selection is observed; forge reconciliation mints it regardless. Refines SPEC151's remainder-creation rule. | Otherwise a Phase-0 stop mints a delivery remainder that blocks the implementation retry (one nonterminal custody); the-bar truthful terminal states | `select_reviewed_output` non-retryable (overloads `retryable` and also blocks reconciled remainders) |
| D15 | Pre-selection review publication (push, PR for review, fix pushes, CI) stays under the guard and `check-launch`. Selection happens at the pre-merge gate on the final head; each post-selection effect is proposed via checkpoint; already-true stages are observation-only. | SPEC151's model requires selection before publication/merge, while ship-issue publishes in order to be reviewed; observations fold independently of readiness (the reducer) | Reorder ship-issue to review before publishing (drops PR review); select after sdd (the head moves in sync and fixes, so a merge could never match the selection) |
| D16 | The ship owner writes only checkpoints under implementation custody; completing observations ride its returned `ship-summary/v2`; from-issue writes `finish`. A remainder owner (ship-issue remainder mode) writes its own `finish`. | `check-launch` reports inactive once delivery completes, so a completing checkpoint would make the parent's fence refuse; the existing completion test puts `implementation_delivered` in the summary; "the custody owner writes the terminal" | Change `check-launch` semantics (reopens #151's fence decision); the parent converting a legacy 9-key return (the ship owner owns the facts and proposals) |
| D17 | The owner envelope is the validated v2 `owner` object (the adapter projects control actions into it); the remainder envelope is the `delivery_remainder` object; Phase 7 uses `ship-handoff/v2` with the builder-regenerated intent and the historical arrays the author holds; the ledger is synchronized by a null-scope checkpoint | One validated shape for both routes; artifact-budget already validates it; truthful handoff arrays | key=value envelope lines (cannot carry the contract); a new read-only delivery-view verb (a wider wire surface than a null checkpoint); `ship-handoff/v2` for remainders (it requires spec/plan fields a remainder does not have) |
| D18 | Allow `workflow-state` and `artifact-budget` in both bare and `~/.agents/bin/` forms (18 → 22), as whole-helper prefixes | 2026-08-17 lifecycle-permissions design (Bash rules precede the classifier; literal prefixes; compound segments must all match); the issue's evidence of refused `finish`/`init-run`; D11 removes the stranding the refused `init-run` could have caused; the classifier sees only the command line, never the request body, so it never guarded an `owner_unavailable` takeover (that stays the skills' explicit-instruction rule plus the helper's active-owner refusal) | Leave the list alone (the lifecycle stalls at the classifier: "[Auto-Mode Bypass]"); per-subcommand rules excluding `direct-owner` (a 20-rule surface protecting nothing the classifier could see; they would also block every acquisition); `Bash(python*)`-style rules (dropped in auto mode, far broader) |
| D19 | Tests use only existing public seams: CLI subprocess round trips, the model facade, the artifact-budget CLI, skill contract tests/evals and the settings guard test. The builder is tested through its verb. | design skill "prefer existing, highest seams"; the-bar "tests that can fail" | Importing the private build module in tests (pins internals, misses the loader) |
| D20 | No ledger repair ships; the operator note relies on the upgraded helper's ordinary lifecycle | SPEC151:494-497; the brief's scope boundary | A migration script for stranded ledgers (the forbidden bridge) |
| D21 | No ADR or context doc. The CLAUDE.md edits (allow count, the stdin request pattern replacing the mktemp sentence, the builder in the Claude Code section) ship with the code that makes them true. | The repo has no context map or ADR home (the 153 D13 precedent; grill-with-docs "don't impose the standard tree mid-flight"); the-bar "moves keep their history" (living docs change with the code) | Found `docs/areas/system/adr/` for this issue (imposes the tree mid-flight); edit CLAUDE.md now (it would lie until the code lands) |
| D22 | Every helper input flag accepts `-` for stdin, so each lifecycle call is one heredoc-fed simple command, optionally piped through `artifact-budget validate-report --input -`, with no temp request files | D18 only works when every segment matches, and the existing mktemp/trap/cat pattern is compound; CLAUDE.md records that the guard treats a heredoc body as non-command; the-bar token economy | Keep temp files (compound commands reach the classifier and D18 is moot); Write-tool files (need read-before-write on an mktemp path plus cleanup) |
| D23 | One stdin-aware reader serves every helper input flag (`--request-file`, `--checkpoint-file`, `--summary-file`, `--result-file`, `--input`): `-` reads all of stdin, and any other value must be an absolute path. This extends the request-file rule to the three report flags, which today hand a relative path to artifact-budget's cwd-relative read. | AC5.3 ("a relative path still refuses"); D22; the-bar DRY (one home per convention); every skill already prescribes an absolute path | Keep relative report paths (two rules for one input class, and AC5.3 would hold for only two of the five flags) |
| D24 | The lifecycle-only transitions (reap, stall terminal, tracker halt, forge reconcile and the third-attempt `refuse`) run with or without a contract and never install one. Only custody-creating transitions install a supplied contract: spawn, resume, retry, recover, and direct's existing historical remainder. | D10's install list names only custody-creating transitions; `refuse` creates no custody and records a lifecycle verdict | Demand a contract before `refuse` (forces a contract build only to record a terminal the contract never governs) |
| D25 | D8's worktree binding applies exactly when the effective contract declares a `remove_worktree` stage, which every builder contract does. Under it, resume keeps its existing recorded-worktree requirement; retry and a direct `new_run` spawn re-create an absent recorded path in place instead of taking a candidate; a first spawn takes the candidate only when it equals the literal; any other path refuses with no write. Without that stage (hand-built contracts, contractless calls) today's selection stands, and the orchestrate adapter reports a candidate only for issues without a bootstrap requirement. | D8; SPEC151's literal cleanup target; the helper already refuses an unused candidate for a recorded issue; fixture contracts without cleanup stages keep their relocation tests | Universal no-relocation (changes contractless and fixture behavior no caller needs and re-pins every relocation test); letting resume accept an absent path (a resumed owner would silently lose uncommitted phase work) |
| D26 | Remainder owners reuse the existing dispatch sites. Orchestrate's one owner dispatch carries either the projected `owner` object or the `delivery_remainder` object into `from-issue <n> --auto`. from-issue's dispatcher route and its direct `delivery_remainder` branch both launch ship-issue remainder mode through the existing `from-issue-ship-owner` site, with a remainder prompt in `ship-handoff.md` that carries the object verbatim. No new `agent-dispatch` marker is added. | D16 and D17 (the remainder owner is ship-issue remainder mode; its envelope is the `delivery_remainder` object); `agent-model-matrix` and `test_dispatch_contracts` register every marker | A second orchestrate dispatch site for remainder owners (another marker, matrix row and dispatch-contract carrier for the same role and tier) |
| D27 | `workflow-state build-delivery` runs `resolve-project resolve --repo-root` itself (the source sibling under the running interpreter, else the installed `resolve-project` beside the script, else `~/.agents/bin/resolve-project`) and hands the snapshot to the build module, which does no I/O. A resolver refusal is a builder refusal. The build module reads the stage action, effect and observation vocabulary from a new read-only `STAGE_ACTIONS` export of the model facade instead of restating it. | The projection module's "no I/O" precedent; `artifact_budget_paths()` resolves its sibling helper the same way; the-bar single responsibility and DRY (the model owns the stage vocabulary) | The build module spawning the resolver (puts I/O inside the pure derivation seam); a second copy of the stage table in the builder (two homes for one vocabulary) |
| D28 | `validate-report --boundary ship-handoff` reads its input under `workflow_responses.wire_max_bytes`, as `workflow-response` does; no policy key is added, and `ship-checkpoint` and `ship-summary` keep the phase-report bound | Phase-5 review (B1): a v2 handoff carries the full contract and initial intent; the 4-stage fixture handoff is already 5318 canonical bytes, and a builder contract of 7–8 stages with one intent scope per stage exceeds `phase_reports.wire_max_bytes` (8192). Task 3's loop test validates a real handoff | A dedicated handoff wire key (a third bound for the same class of delivery objects); dropping the contract from the handoff (a wire-shape change D17 does not make; the ship owner builds scopes from it) |
| D29 | Under lifecycle identity ship-issue's post-merge exemption is retired: merge, remote branch deletion, issue close, `git branch -d` and `git worktree remove` each run as a `## Delivery loop` cycle, and `ship-summary/v2` is validated only after the last cycle. The ledger-free guard skip stays, and the 9-key legacy summary stays as the ledger-free return and as the `historical_owner_result`. ship-issue's own interface-2 appendix folds into `## Delivery loop` | Phase-5 review (B2): D15's one loop covers every post-selection stage, which the exemption and the Phase-7/8 prose contradicted; §6 and D16 keep the legacy row as `historical_owner_result` | Deleting the 9-key row, as the reviewer proposed (drops the ledger-free return and the historical result D16 keeps); keeping the exemption beside the loop (two rules for one stage) |
| D30 | Control writes each reconciliation into `state["issues"]` before re-planning, and keys the reconciled-remainder re-plan on persisted state (installed contract, incomplete delivery, no remainder, a latest attempt in the historical terminal set, a merged forge), not on the sweep's analysis result, so a sweep after a capacity-0 sweep still mints remainder 1. The runtime wrapper is renamed `historical_requested` with no alias, and the policy's forge docstring and comments describe the live-custody guard for both callers | Phase-5 review (S1–S3): D13's guard makes a later sweep's policy answer `terminal` for a reconciled attempt; `apply_policy` deep-copies pre-sweep state; the wrapper, a pre-selection remainder test and "only the direct owner reads forge" comments were missed | Keying on the analysis result (never fires on a later sweep, and re-reconciles within one); keeping a `historical_direct_requested` shim (two names for one predicate) |
| D31 | Refines D10: a null-digest control summary carries `delivery_contract_required` only when policy's operation is `"contract"` (a would-be spawn, resume or retry); live custody left idle, terminal and lifecycle-only verdicts carry none. The orchestrate adapter sends a built contract for a null-digest issue on the first sweep that lists it, then only while its latest summary carries the requirement | Phase-5 review (Dsc2): bootstrap lists every issue that is not delivery-complete and the wire forced the requirement onto every null-digest summary, so a terminal legacy issue was asked for a contract forever; D24 makes a contract supplied for a terminal issue harmless | Dropping terminal contractless issues from the bootstrap (a projection change beyond D10); keeping the rule (endless rebuilds and "contract required" on merged issues) |
| D32 | Every builder refusal names its rule on stderr with a fixed fragment that the refusal tests assert, and the contract check is stated at its real reach: a contract whose intent-bearing fields differ from the builder's derivation is refused; its other fields are model-validated, not re-derived | Phase-5 review (S4, Dsc1): `(2, b"")` alone lets a builder that refuses every input pass; intent regeneration only covers fields that reach a scope or the intent's source | Full re-derivation of every contract field (larger, and D25 keeps hand-built fixture contracts legal in the helper); exit-code-only refusal tests |
| D33 | Execution corrects two plan-text defects without editing the budget-bound plan: Task 2's commit also stages `T/test_resolve_project.py` (and any other file the task edits), and Task 7's stdin-flag contract test strips backticks and trailing `.,;` together before asserting the value is `-` | sdd's initial package scan (C1, C2): Task 2's `git add` omits the resolver test the task edits and imports; `strip("`").rstrip(".,;")` leaves `-`` for `--input -`;` and fails on unchanged from-issue text | Editing the plan package (at 130,747 of 131,072 bytes); following the plan text verbatim (a commit that cannot import its helper, a test red on untouched prose) |
| D34 | Refines D25 and the contractless retry lane: with no installed contract, a retry or `new_run` whose recorded worktree observation is `matching_issue_branch` or `absent` answers `"contract"` without first demanding a `candidate_worktree`, so the contract re-creates the recorded path in place; only a `mismatch` falls through to today's selection. A control sweep that reaches that answer without a supplied contract reports `delivery_contract_required` rather than refusing the sweep | Task 4 review (I1, plan-mandated): demanding a candidate the D25-bound contract can never use made every later control sweep exit 2 for a legacy run holding a failed attempt whose worktree was cleaned up, stranding the whole run (and made direct raise a custody mismatch) | Amending D25/D31 so the adapter keeps resending a contract for every null-digest issue with a failed retryable attempt (wider adapter rule, leaves the policy's unusable candidate demand in place); keeping the brief's selection verbatim (strands runs — the defect #171 exists to fix) |
| D35 | Supersedes D2's one-PR delivery: #171 ships as two PRs. PR 1 is Tasks 1–4 (slot PR binding, the builder verb, contract-last acquisition and null-contract semantics) at `6e084737c6be181649d9cf9e6b42c51eadd63796`, on branch `worktree-issue-171-contract-builder`; PR 2 is Tasks 5–8 (legacy finish continuity, forge reconciliation, lifecycle skills, auto-mode allow rules), built on top of PR 1. PR 1's final review and Finish are scoped to Tasks 1–4; Tasks 5–8's criteria (AC1.7, AC2.1, AC2.2, AC2.5, AC3.1–AC3.4, AC4.1, AC4.2, AC5.1, AC5.2) are PR 2's | User decision after sdd's cumulative delivery gate returned `decompose_required` for `58eca39..4992a48` (the `-U10` diff of `T/test_delivery_workflow.py` exceeds the 65,536-byte member bound, which v3 remediation never covers), while `58eca39..6e08473` passed the same gate | One PR with the branch's new tests moved into a new module so no single file diff exceeds the member bound (outside the reviewed plan; the user chose the split) |
| D36 | PR 1 keeps D25/D34's contractless `mismatch` fall-through unchanged: with no contract, a retry or `new_run` whose recorded worktree is `mismatch` still takes today's selection (a reported candidate, then `"contract"`), and the builder contract that answers it refuses with no write under D8. The finding is parked, not fixed, in PR 1, and carried to PR 2 as an open acceptance item that Task 6's written steps do not yet cover: PR 2 either closes I1 in the retry/`new_run` recorded-path rule with a test pinning the contractless `mismatch` outcome, or rules it final in a ledger row of its own | PR 1 final review (correctness I1): the `"contract"` answer on a `mismatch` is one wasted round trip before the D8 refusal, and a contractless control sweep with a reported candidate refuses at the candidate guard instead. Both end in the refusal D8 specifies for a mismatched custody worktree, which needs human repair either way. D25 and D34 state this selection explicitly, and PR 2's Task 6 owns the retry/`new_run` recorded-path rule in the same function. PR 1's ship review (conformance) found Task 6's text silent on I1, so the carry is stated here rather than implied | Refusing a contractless `mismatch` immediately in PR 1 (contradicts D25/D34's stated contractless selection, needs a new refusal message, and conflicts with PR 2's concurrent edits to the same policy) |
