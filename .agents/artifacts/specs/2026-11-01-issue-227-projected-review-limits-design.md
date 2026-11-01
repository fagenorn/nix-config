# Enforce projected review limits during planning and execution — issue 227

Issue: https://github.com/fagenorn/nix-config/issues/227, child of
https://github.com/fagenorn/nix-config/issues/152. Its blocker
https://github.com/fagenorn/nix-config/issues/226 delivered the accepted
`review-feasibility project` / `validate-result` interface this design adopts. Designed
autonomously (`from-issue --auto`): every call made without the user is a row in the
Decision ledger.

## Triage

Input: {"signals":{"contract_change":{"value":"hit","evidence":"Changes the producer, plan and SDD transport contracts and sdd-gate/review-feasibility interfaces (AC3, AC5)."},"concurrency_or_persistence":{"value":"doubt","evidence":"sdd-gate appends to the persisted per-plan SDD ledger and stop records must preserve retained work and evidence."},"open_design_questions":{"value":"hit","evidence":"Forecast placement in plan content, stop-summary shape and caller recompute route are open design questions."},"criteria_shape":{"value":"hit","evidence":"Eight acceptance criteria, several (end-to-end replay, child obligations) not verified by one deterministic check."}},"paths":["python/agent_tools/sdd_gate.py","python/agent_tools/review_feasibility.py","python/agent_tools/review_projection.py","home/common/agent-skills/scripts/artifact_budget.py","home/common/agent-skills/skills/writing-plans/SKILL.md","home/common/agent-skills/skills/sdd/SKILL.md","home/common/agent-skills/skills/from-issue/SKILL.md","home/common/agent-skills/skills/from-issue/AUTO.md","tests/test_review_feasibility.py","tests/test_sdd_gate.py","python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

The accepted `review-feasibility project` can say, before the work exists, whether a
delivery's complete review package (its actual changes plus a committed forecast of the
rest) fits the unchanged review-package limits, and which declared smaller boundary would.
No workflow uses it. Plans carry prose estimates, and SDD measures only the actual
cumulative package between tasks. An oversized delivery is found when its actual package
overflows, after the work exists, which is when splitting costs most. The children of
issue 226 ran the projection through hand-written, plan-specific gates.

The transports cannot carry the answer either. A planning producer report knows only
artifact-budget states, so a projected overflow could only be mislabelled as the plan
artifact itself being over budget. The sdd skill says an exit-3 package is "returned" as
`decompose_required`, but the SDD report has no such state. And a receiver has no
deterministic way to check a projection it did not run.

The user wants four outcomes. An oversized plan is refused before its first
implementation task. A plan that fits at first but grows is refused before the next
dispatch, with its complete range identity and a reproducible recommendation for the
smallest declared reviewable descendant. Work and evidence are kept for fresh child
deliveries. The stop authorizes nothing.

## Solution

The accepted `project` and `validate-result` semantics, the v3 forecast format, the
packer and the limits stay as they are. Six parts adopt them in one delivery (D1).

**1. Every plan commits a complete forecast.** writing-plans writes the v3
`## Review feasibility delivery` block in the plan root and a `## Review feasibility task`
block in every task member. These are the closed, single-line canonical JSON blocks the
accepted loader reads, and they count inside the implementation-plan budget. A compact
forecast section inside the skill, with field semantics in `python/README.md` (D14), teaches
the blocks and their conservative bounds:

- process records for the spec, root and members, with growth for the Phase-5 record
  and the per-task recordings;
- one subject bound for each future process commit;
- one record per path in each task's `Files:` block;
- any declared descendant boundaries, each with its own future process package (D7).

`## Delivery estimate and boundaries` keeps only the rationale for each boundary. The
numbers live in the forecast.

**2. Planning gate.** writing-plans pins the delivery base with sdd's merge-base rule
and commits the package. It then runs
`review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0`:

| Exit | Producer report |
|---|---|
| 0 | `complete`, with the summary as `projection` |
| 3 | `decompose_required`: the plan artifact stays `within_budget`, plus the summary |
| 2 | one correction round of the forecast and a rerun, then `failed` |

**3. Per-task recording and reprojection.** After a task's review is clean, the
controller runs `sdd-gate record PLAN_FILE --task N`. It rewrites the forecast's
ownership evidence from the SDD ledger and Git. The controller then commits exactly
those two files as one process-only commit, subject `plan: record task <N> evidence`,
through its existing self-registration and `launch-commit` route.
`sdd-gate next --completed N --task N+1` then:

1. requires that recording;
2. runs the existing complete fixed-base actual gate at it;
3. reprojects with `--completed-through N` at the same head;
4. renders the next brief.

The first `next --task 1` projects with `--completed-through 0` (D2, D8).

Two terms keep this precise:

- The **reviewed head** is the commit a task's clean review accepted.
- The **gate head** is the single recording commit over the reviewed head. The
  issue's "exact accepted head" is the gate head: the actual gate, the projection and
  the `Delivery gate:` ledger line all bind to it.

After SDD entry, the forecast blocks change only through `record` (D12).

**4. One closed stop summary in the existing transports.** `gate` derives a closed,
bounded `review-feasibility-summary` from a validated result. Producer reports carry it
as `projection`. SDD gains a `decompose_required` state whose `stop` tells a projected
overflow from an actual package overage. Invalid input stays `failed` (D3, D5).

**5. Every receiver recomputes.** `review-feasibility confirm --plan <root> --base
<base> --input -` reruns the projection the summary names and requires exact canonical
agreement. It runs before any continuation is chosen: in the sdd controller, at
from-issue's artifact-report boundary (whose confirmation the Phase-5 caller gate
requires) and in from-issue's Phase-6 stop route (D4).

**6. A stop is a recommendation.** A confirmed overflow ends the attempt as `stopped`.
It names the recommended boundary, or says that new design is required. It keeps the
worktree, branch, SDD workspace, ledger and validated result. It acquires no child
lifecycle, files no issue, moves no base and dispatches nothing (D6).

**Demo.** First, an oversized committed plan: the planning gate returns
`decompose_required` with a summary, and `sdd-gate next --task 1` refuses at
`projection` with no dispatch. Second, a fitting plan whose Task 1 outgrows its
forecast: after the recording, `next --completed 1 --task 2` passes the actual gate,
then refuses at `projection` with exit 3. No Task-2 brief or worker exists, and the
summary names the full range, the identities, the four metrics and the smallest fitting
declared descendant holding Task 2.

### This delivery's own gates (AC7)

- **Fixed base.** The immutable delivery base is `8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc`.
  Every gate measures from it; integration advances never move it.
- **Complete forecast.** The plan commits a complete v3 forecast. It charges this spec,
  the plan root, every indexed task, every product path, fix-round allowance and
  sequential shared-path contribution, every recording commit and Phase-5 edit, and
  each declared child boundary's process package.
- **Declared descendants.** The plan declares child boundaries along its dependency
  chain, so that an overflow has a recommendation: summary commands and transport
  validators, then the SDD gate and recording, then callers and the replay.
- **Gates declared in the plan.** The adopting skills and `sdd-gate` are not installed
  while this delivery runs, so the plan declares its gates explicitly, as the issue-235
  plan did (D11):
  - G0 is the accepted projection run twice at identical inputs, both runs agreeing on
    exit and bytes, then `validate-result` with that exit (D21). It runs before Task 1 and
    after each accepted task's recording, and exit 2 or 3 stops.
  - G1 is the installed `sdd-gate` complete fixed-base actual gate, run after every task
    and at the final head.
- **Reviews and verification.** Every implementation task gets a fresh independent
  review. Separate authorship-independent final conformance and correctness reviews
  follow; parent reviews are provenance only. `just agent-workflow-tests` and
  `just build` must pass.

## Decisions

### Stop summary (D3)

A summary is canonical JSON: sorted keys, compact, ASCII-escaped, LF-terminated. That
is the form of the v3 result, and it stays within the report wire bound. Its closed
fields are:

| Field | Value |
|---|---|
| `schema_version` | `1` |
| `kind` | `review-feasibility-summary` |
| `state` | `complete` or `decompose_required`, as the validated result says |
| `plan` | repository-relative POSIX path of the plan root projected |
| `base`, `head` | full commit IDs of the projected range |
| `completed_through` | the projected ordinal |
| `plan_package_sha256`, `forecast_sha256`, `packing_policy_sha256`, `artifact_policy_sha256` | copied from the result |
| `metrics` | the four projected metrics |
| `violations` | the ordered violation codes |
| `recommended_boundary` | `null`, or `{id, tasks, prerequisite_commit, metrics}` copied from the result's recommendation |

A summary is derived only from bytes that passed `validate_result` with their
producer's exit. `complete` holds exactly when there are no violations, the exit is 0
and the recommendation is null. An overflow's recommendation is null when no declared
boundary fits: new design required (D18). Exit 2 yields no summary.

The full validated result is kept wherever a stop is recorded, as
`projection-<head7>-<N>.json` through one shared writer: `gate --save-dir` at planning
(writing-plans passes the plan's `sdd-workspace`), sdd-gate's `projection` step in SDD
(D20). It is a cache, not the provenance. The immutable provenance is the committed plan and history, and `confirm`
reproduces the summary from them at any later time.

### `review-feasibility gate` and `confirm` (D4)

A new package module owns three importable operations: bounded capture, summary
derivation and confirmation. `review-feasibility` stays a thin shell, and sdd-gate
imports the same functions. The command table is unchanged.

- **Capture.** It takes the child argv as a parameter; production passes the packaged
  sibling `review-feasibility project` with the caller's four arguments. It reads at most
  the authority's report wire bound plus one byte of stdout (more is invalid) and drains
  stderr to a bounded tail without blocking. The exit must be 0, 2 or 3. On 0 or 3 the
  bytes must pass `validate_result` with that exit under the same
  `describe("review-package")` authority. On 2 the result is the child's one-line reason.
- **`gate --plan P --base B --head H --completed-through N [--save-dir DIR]`.** It prints
  the canonical summary, after saving the validated result into DIR, and exits 0 or 3. Any other outcome exits 2 with one stderr line,
  `review-feasibility: <reason>`, and empty stdout.
- **`confirm --plan P --base B --input FILE|-`.** It reads at most wire bound plus one
  byte, with no symlink following for a file, as `validate-result` does. It parses
  strictly: no duplicate keys, no non-finite numbers, the closed summary key set. It
  requires `plan` to equal P relative to the checkout's top level and `base` to equal B.
  It then reruns the capture with the summary's `base`, `head` and `completed_through`;
  the accepted loader itself requires `head` to be the checkout's `HEAD`. The canonical
  re-encoding of the input must equal the recomputed summary byte for byte, and the
  recomputed exit must be the input state's exit. On agreement it prints the summary and
  exits 0 or 3. Otherwise it exits 2 with one stderr line naming the first disagreeing
  top-level field in sorted order, or the capture's reason.
- **Ordinal binding.** Receivers bind `completed_through` only at planning, where the
  producer boundary requires 0. In SDD, a forged ordinal must still
  reproduce against the plan's recorded ownership, or the recomputation refuses.

### Ownership recording (D2)

A new package module rewrites the forecast blocks, and `sdd-gate record PLAN_FILE --task N`
is its ledger-aware shell. The reviewed head `H` is the checkout's `HEAD`, or the head an
existing `Task N: recorded (head H)` line names. `B` is task N's
`Task N: dispatched (base B)`.

- **`ledger`.** The ledger is this plan's. Tasks 1 to N−1 are complete, and task N is
  dispatched and not complete. An earlier recorded head for N must equal `H`.
- **`worktree`.** No tracked change lies outside the plan root and task N's member. `B`
  is a strict ancestor of `H`, and the previous evidence checkpoint `C` (the forecast's
  current `actual_evidence.head`) is an ancestor of `B`.
- **`record`.** The committed blocks at `H` must equal those at `B`: no task commit may
  edit the forecast. It reads those blocks and makes four changes:
  - task N's `actual_ranges` gains `{base: B, head: H}`;
  - when `B ≠ C`, `actual_evidence.process_ranges` gains
    `{base: C, head: B, boundaries: [<proposed boundary>]}`;
  - `actual_evidence.head` and `tree` become `H` and `H`'s tree;
  - every `completed-tasks` prerequisite whose highest task is N gets commit `H` and
    `H`'s tree.

  It writes only the two block lines, atomically, and appends
  `Task N: recorded (head <H>)`.

`record` is repeat-safe. It reports `changed: false` and writes nothing when both files
already hold those bytes, or when `HEAD` is a single-parent commit over `H` that changes
only those two files and whose committed blocks equal them. Its ready object is
`{"command":"record","outcome":"ready","task":N,"head_sha":H,"paths":[root,member],"changed":bool}`.
A refusal uses sdd-gate's existing refusal object with `gate: null` and exit 2. The
projection, not `record`, is the authority on whether the evidence is valid.

### `sdd-gate next` (D8)

The steps run in this order:

1. `ledger`
2. `evidence`
3. `ledger-complete`
4. `mark-progress`
5. `review-package`
6. `validate-report`
7. `budget-check`
8. `metrics-match`
9. `projection`
10. `task-brief`
11. `prepare-brief`
12. `register-worker`
13. `write-brief`

- **`ledger`.** With `--completed N` it also requires `Task N: recorded (head H)`. With
  `--task M` the complete tasks, counting this call's `--completed`, must be exactly 1
  to M−1.
- **`ledger-complete`.** It writes `Task N: complete (commits <B7>..<H7>, …)` using the
  recorded `H`.
- **`evidence`** (task N with `--completed N`, else task M−1 for a fresh `--task M`,
  M > 1). `HEAD` has exactly one parent, that parent is that task's recorded `H`, `HEAD`
  changes only the plan root and that task's member, and both files equal the
  bytes `record` computes from `H`. A recording commit therefore cannot carry any other
  forecast edit, and a `complete` line never vouches for an unverified `HEAD` (D19). Any
  refusal carries gate `failed`.
- **`projection`** (only with `--task M`, when M has no dispatched line). It captures at
  `HEAD` with `--completed-through M−1`:
  - exit 0 saves the validated result to the workspace as
    `projection-<head7>-<M−1>.json` and appends
    `Projection gate: <base40>..<head40> through <M−1> root_bytes=<n> total_bytes=<n> file_count=<n> largest_member_bytes=<n>`;
  - exit 3 saves the result and refuses with gate `decompose_required`, the summary as
    `report`, and exit 3;
  - exit 2 or an invalid capture refuses with gate `failed`, a null `report`, the reason
    as `detail`, and exit 2.

  A re-dispatch of M runs no projection. It requires the `Projection gate:` line through
  M−1 whose head is M's recorded dispatch base.

The actual gate always runs before the projection, and its refusal ends the call. A
projection therefore never runs over, or suppresses, an actual failure. The ready object
gains `projection`: `{completed_through, head_sha, metrics}`, or `null` without `--task`.
`next --completed N` alone, after the last task, runs no projection.

### Transport validation (D5)

`artifact-budget validate-report` validates the summary structurally, in one function
that both boundaries share. It checks:

- the closed keys, the schema version and the kind;
- the SHA, digest and relative-path shapes;
- `artifact_policy_sha256` equals the checker's own policy identity;
- the metrics are valid and the `violations` equal those the review-package limits give
  for them, in checker order;
- `state` agrees with the violations;
- the recommendation is null when `complete`; otherwise it is null or holds a
  well-formed id, sorted unique tasks containing `completed_through + 1`, a full commit
  and within-budget metrics.

`packing_policy_sha256` is checked for shape only; `confirm` establishes it.

- **Producer, `implementation-plan`.**
  - `complete` has exactly `state`, `artifact`, `projection` and `notes`. The
    projection's state is `complete`, its `completed_through` is 0, and its `plan`
    equals the artifact path.
  - `decompose_required` is either the existing over-budget artifact without
    `projection` (an actual artifact overage), or a `within_budget` artifact plus a
    projection whose state is `decompose_required`, with the same ordinal and plan
    bindings.
  - `failed` carries no projection. That includes an exit 2 whose reason begins
    `projection_unavailable`: an unprovable recommendation is never relabelled as an
    overflow, and the notes keep the tool's reason.
  - Every other artifact kind refuses `projection`.
- **SDD.** A new `decompose_required` state has the eleven existing keys plus `stop`:
  - `review_state` is `unknown`; both verdicts and `verification_state` are `not_run`;
  - `base_sha` and `head_sha` are the refused gate's range;
  - `acceptance_state` is `not_applicable`, `detail_state` is `none`, and `report_path`
    is null;
  - `stop` is either `{"kind":"projected_overflow","projection":<summary>}` (state
    `decompose_required`, its `base` and `head` equal to `base_sha` and `head_sha`) or
    `{"kind":"actual_overage","artifact":<over_budget review-package artifact>}`.

  Other states keep their keys and refuse `stop`.

### Callers (D6)

- **writing-plans.** It runs parts 1 and 2 after its final mutation. A mechanical-only
  self-grade's edits come before it. Its producer report adds `projection`, as above.
- **sdd.** After a clean review, Step 5 runs `record`, the commit and `next`. On
  refusals:
  - `projection` with `decompose_required` → `confirm` must exit 3 → SDD
    `decompose_required` with `projected_overflow`.
  - `validate-report` with `decompose_required` → run `artifact-budget check` on the
    report's root, which must agree on the four metrics and the violations → SDD
    `decompose_required` with `actual_overage`.
  - `failed`, or any disagreement → SDD `failed`.

  No later dispatch follows a stop. The workspace, ledger and worktree are kept. A plan
  without forecast blocks fails at the first projection (D9).
- **from-issue.** Every receiver computes the base it passes to `confirm` itself, by
  sdd's merge-base rule; it never copies the base from the report it is checking (D13).
  - Its artifact-report boundary confirms an implementation-plan report's `projection`,
    and the confirm exit must match the state. A confirmed `decompose_required` ends the
    attempt. The Phase-5 caller gate requires that confirmation.
  - The Phase-5 plan review grades the forecast's completeness: a missing `Files:` path,
    a missing process artifact or recording subject, or a bound below the task's stated
    scope is Blocking.
  - In Phase 6, an SDD `decompose_required` is verified by `confirm` or by the
    independent artifact check, then ends through the terminal return procedure with a
    `stopped` historical row. A disagreement is `failed`. The delegated owner takes this
    route in place of progress or delegate.
  - The stop's bounded notes lead with the class, the gate head, the ordinal, and the
    recommendation's id and tasks or "new design required", because the lifecycle
    ledger trims the tail of the notes to retain the worktree path.
  - AUTO.md's exact plan reports gain `projection`.
- **The decomposition-stop text in from-issue.** It is the one home of the
  reconciliation rule. A recommendation authorizes nothing. Each derived delivery needs
  a new issue, spec, plan, base, forecast, package and reviews. The stopped issue stays
  open. Closing it, or its parent, requires a reconciliation record that maps each
  original criterion and operational effect to an accepted child's immutable
  identities, actual package, review and operational evidence. A closed checkbox is not
  evidence.

## Test seams

All tests run source commands under the recipe's `PYTHONPATH` in real temporary Git
repositories (D10). No fake `review-feasibility` sits on `PATH` (siblings run by module), and
no projection result is mocked.

| Contract | Seam and prior art | Evidence |
|---|---|---|
| Capture, summary, `confirm` | `python -m agent_tools.review_feasibility gate/confirm` in a repository built by the existing source-projection fixture. The capture function's argv parameter supplies producer output no real producer emits. | Summaries equal their result fields, both null and non-null recommendations, an overflow with a null one included, at `gate`, `confirm` and both transports; `--save-dir` keeps the exact validated bytes. Capture refuses malformed, non-canonical, oversized, unknown-exit and exit-disagreeing output. `confirm` refuses each of: an extra or missing key; each of the four metrics plus one; each of the four identity digests altered; a stale head after a new commit; a base or plan mismatch; a state/exit swap. Each refusal names its field or the capture's reason. |
| Transport validators | The existing `artifact_budget` boundary tests | Every producer and SDD shape above, accepted and refused, including a projection on another kind, in `failed`, with a nonzero ordinal, a foreign plan, a foreign policy, a state/violation disagreement, or an over-budget artifact beside a projection. Every summary `gate` emits validates at both boundaries. |
| Ownership recording | `sdd-gate record` with the existing sdd-gate lifecycle harness | The recorded plan projects; prerequisites are filled; a repeat is a no-op; refusals for an undispatched task, a task with no commits, a changed reviewed head, an extra dirty path, and a task commit that edited a forecast block. A recording commit that carries any other forecast edit is refused at `evidence`. |
| SDD ordering | `sdd-gate next` in the same harness | The initial projection runs before Task 1. Steps run in the order above. A projected overflow and an invalid projection each leave no dispatched line, brief or worker. An actual overflow despite a fitting projection refuses at `validate-report` and the projection never runs. A re-dispatch reuses the projection line. A missing or extra recording commit refuses at `ledger` or `evidence`, writing no `complete` line; a later `--task` over a lowered bound refuses at `evidence`. |
| End-to-end replay | A new source test: a scratch repository shaped like the retained issue-121 delivery, with eight tasks and declared children for tasks 1–3, 4–6 and 7–8, and no historical fixture used as acceptance | Detailed after this table. |
| Installed parity | The existing launcher-layout test | The built `gate` and `confirm` print the source bytes. |
| Skill contracts | The existing skill-contract tests, machine-consumed text only | The exact producer and SDD report key sets in skill text. |

The end-to-end replay must show seven things:

- An oversized plan is refused by both the planning gate and the SDD entry gate.
- A growing plan stops before Task 2 with a recommendation.
- The accepted commits, the branch, the ledger and the saved result are unchanged.
- The parent summary still confirms after the child exists.
- A child branched from the recommendation's `prerequisite_commit` projects `complete`.
  It has its own base, a new process package and recovered commits, and its plan cites
  the parent summary.
- The child's ledger starts empty.
- Under a lifecycle identity, the stop registers no worker and acquires nothing.

## Out of scope

- Shared verification-blocker identity and resume, which belong to
  https://github.com/fagenorn/nix-config/issues/228.
- Any change to `project` or `validate-result` semantics, the v3 forecast format,
  reconstruction proofs, the packer, the limits or the policy file.
- Generating forecasts automatically.
- Child issue creation, child lifecycle acquisition, base repinning, and reuse of parent
  reviews as acceptance.
- Projecting after the last task or over final-review fixes; the actual gate and the
  final reviews govern those. The ship-time sync range is ship-issue's.
- Moving `artifact-budget` into the package, which is
  https://github.com/fagenorn/nix-config/issues/178.
- The retained issue-121 evidence and its replay, which stay unchanged.
- The light lane's active route.
- A parent audit of issue 152.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Adopt the accepted interface unchanged through four parts: a shared planning gate in writing-plans, an sdd-gate projection step with per-task ownership recording, one closed summary in the producer and SDD transports, and recomputation by every receiver. This is one delivery. | Issue 227: "This child alone adopts the accepted tooling interface in planning, SDD, ownership callers and result transport". The issue-235 plan's G0/G1 precedent. | Per-plan, hand-written G0 gates: the contract stays in each planner's prose, unshared and untested. Splitting it up: the transports, callers and gates must change together. |
| D2 | After each accepted task, `sdd-gate record` rewrites the task range, process ranges, checkpoint and newly due prerequisite identities from the ledger and Git. The controller commits exactly those two files as one process-only commit through self-registration and `launch-commit`. `next` requires that commit, and both gates run at it. | The accepted loader refuses product commits after the evidence checkpoint, and refuses due prerequisites with null identities. The issue-235 recording commits. final-review.md's acceptance-record commit route. | Hand-edited canonical JSON per task is error-prone, with exact SHAs. sdd-gate committing would need a commit trailer and authority it does not hold. Reading ownership from the ledger would change the accepted interface. |
| D3 | The summary is a closed v1 object: state, plan, full range, ordinal, the four identities, the four metrics, the violations, and a recommendation trimmed to id, tasks, prerequisite commit and metrics. The full result is saved where the stop is recorded. | AC3's field list. The 8192-byte report wire bound. The CORE spec: consumers compare every identity and metric. | Embedding the whole v3 result costs bytes and carries reconstruction internals no receiver uses. Carrying only identities lets one-metric drift pass. |
| D4 | One package module provides capture (a bounded sibling stdout read, then `validate_result` with its exit), summary derivation and confirmation. They are exposed as `review-feasibility gate` and `confirm --plan --base` and imported by sdd-gate. `confirm` binds the plan and base it is given, the head through `HEAD`, and requires exact canonical equality and an agreeing exit. | agent-helpers rules 1 to 4 (package module, thin shell, sibling runner, one canonical home). The bar's token economy: few parameters. | A new top-level command would add a second launcher for the same domain. Receivers comparing fields in prose or with `cmp` is non-deterministic, and a byte-exact transcription is fragile. |
| D5 | The planning `complete` report requires a `projection`. A projected overflow is `decompose_required` with a `within_budget` artifact and the summary; an artifact overage is unchanged. SDD gains `decompose_required` with a `stop` union of `projected_overflow` and `actual_overage`, and invalid input stays `failed`. `artifact-budget` validates the summary structurally, including its own policy identity, and `confirm` establishes it semantically. | Issue 227: artifact metrics stay separate from projection metrics, and projected overflow, invalid input and artifact overage stay distinct. The bar's defense in depth. Every report field is strictly validated. | An opaque `projection` slot leaves the transport unchecked. Having `artifact-budget` call `review-feasibility` creates a process cycle. A new failure state is redundant, because `failed` already carries the tool's reason in its notes. |
| D6 | A confirmed overflow or artifact overage ends the attempt as `stopped`, never `failed`. It names its class and recommendation, or "new design required". The worktree, branch, workspace, ledger and saved result are kept. Nothing acquires, files, repins or dispatches. A reconciliation record, not a checkbox, closes the stopped issue or its parent. | Issue 227's Decisions: a stop is a recommendation, and parent closure needs explicit reconciliation. The bar's truthful terminal states. The existing terminal return procedure. | Auto-filing child issues would need a new authorization. Reporting `failed` for a valid overflow is untruthful. Restoring a retired result transport is forbidden. |
| D7 | Planning pins the base with sdd's merge-base rule. The planning-time checkpoint is the delivery base with no process ranges, unless an earlier commit changes a path outside the package; that commit goes in a task's `actual_ranges`. The forecast reference lives beside writing-plans. Exit 2 gets one correction round; exit 3 is final. | load_plan's tail rule. The writing-plans budget remediation, compact once and then stop. Issue 226: never lower an honest forecast. | Unlimited retries invite forecast gaming. No retry means one JSON typo fails the attempt. A separate base rule could disagree with SDD's pinned base. |
| D8 | Projection runs at SDD entry, which covers Phase-5 edits, and before each task's first dispatch, always after the actual gate. A re-dispatch reuses the recorded `Projection gate:` line. After the last task there is no projection. | AC2: reproject "before another dispatch". A projection cannot suppress an actual failure. | Reprojecting on re-dispatch would see partial product commits and refuse. Projecting after the last task repeats the actual-only parity. |
| D9 | A plan without a forecast, whether in flight or hand-written, is invalid input at SDD entry and fails. There is no grandfathering. | Issue 227: no guessed success. The loader refuses a missing section. | Skipping the gate when the blocks are absent would be guessed success. |
| D10 | Tests run source commands in real temporary Git repositories, with an argv seam for producer outputs that cannot occur and a scratch replay shaped like the retained issue-121 delivery: eight tasks, children 1–3, 4–6 and 7–8. One installed-parity case. | agent-helpers rule 5. The bar's tests that can fail. The CORE test seams. The parent issue 152 demo. | A fake command on `PATH` cannot work, because siblings run by module. Mocked results prove no parity. Replaying the real retained evidence only shows `projection_unavailable`. |
| D11 | This delivery runs its gates as plan-declared steps. G0 is the accepted projection: the installed command or a scratch checkout of the base, never the in-flight worktree source, with hand recordings that G0 validates. G1 is the installed sdd-gate actual gate. | AC7. The installed skills are not updated until merge and switch. The issue-235 plan precedent. | Using unreviewed in-flight source as its own gate. Waiting for installation, which would leave this delivery ungated. |
| D12 | Forecast blocks change only through `record`. A task commit may not edit them, and a recording commit must be byte-equal to `record`'s output. The Phase-5 plan review grades the forecast's completeness as Blocking. | Issue 226/227: never lower an honest forecast. The loader's tail rule admits any edit to a process path, so a mid-run edit could otherwise lower future bounds unseen. The bar's defense in depth. | Trusting tail process edits allows silent forecast lowering mid-run. A mechanical completeness checker adds little: the projection already counts unforecast actual paths, and whether a bound is honest needs judgment. |
| D13 | Each receiver derives the base it passes to `confirm` by sdd's merge-base rule, never from the report under check. The stop's notes lead with the class, the gate head, the ordinal and the recommendation. | The bar's defense in depth: the expectation is independent. The delegated owner's continuation carries no base. workflow-state trims the tail of the notes to retain the worktree path. | Copying the report's `base_sha` makes the binding circular. The Phase-1 note is unavailable to a delegated owner. |
| D14 | The instruction budget stays neutral: no raise label, no `instruction-load.json` edit, and every edited instruction document ends no larger in bytes than at the delivery base, its additions funded by cuts in the same document. The forecast reference is a compact `## Review feasibility forecast` section inside writing-plans `SKILL.md`, with full field semantics in `python/README.md`. Reverses D7's "beside writing-plans". | The required Instruction Budget check. CLAUDE.md: only the user applies the raise label. Base headroom: planning-owner hot 18 B and conditional 0 B, from-issue-controller hot 3 B, implementation-owner hot 79 B, plan-reviewer hot 1 B. A new skill member needs a model change the gate refuses without the label. The issue 448, 477 and 478 plans. D9 makes every planning run read it, so it is hot. | A labelled ceiling raise needs an authorization this autonomous run cannot self-answer, and leaves the PR unmergeable. An unmeasured installed reference directory evades the gate's intent. |
| D15 | `tests/test_sdd_gate.py` gains `ForecastCase(GateCase)`, which writes the v3 forecast at setUp over the fixture's plan commit as delivery base. The committed fixture files and golden briefs stay unchanged, and every dispatching `NextTest` case is re-based on it. | D9: every dispatch now projects. The loader binds `delivery_base` to a runtime commit, so committed fixture blocks cannot name it. Spec § Test seams' existing sdd-gate harness. | Committed fixture blocks with a fixed SHA cannot load. A separate harness would duplicate the lifecycle shims. |
| D16 | This delivery's G0 runs between two installed `sdd-gate next` calls: `--completed N` (closing N and running G1), G0 at N, then `--task N+1`. Recordings are hand commits of D2's four changes, validated by G0. Each `Files:` list is exhaustive. The root's headroom covers the five recordings, so a Phase-5 root edit stays under 300 B or goes to this spec. | D11. The installed `sdd-gate next` has no projection step. The loader refuses a completed record with no owned effect. `load_plan` and `sdd-gate` check the root budget at every gate. | One `next --completed N --task N+1` call dispatches before a projection can run. Using the in-flight `record` before its review lets unreviewed code shape its own gate's input. |
| D17 | The first planning G0 over a seven-task package (exit 3: `root_bytes` 19,187 of 16,384, total 486,131, recommendation `c1`) gets the installed writing-plans' one compaction round: seven tasks fold into five (recording with the `next` steps, planning with execution callers), cutting future commits from 40 to 30 at unchanged bounds of four subjects per task. | The packing policy reserves 6 JSON bytes per forecast subject byte, so the commit count drives the review root. writing-plans allows one compaction before `decompose_required`, and this plan predates D7's gate. Record and `next` share `sdd_gate.py` and its tests; both caller halves share from-issue `SKILL.md` and the contracts test. | Lowering per-task subject counts after a refusal is forecast gaming (D7, issue 226). Returning `decompose_required` at once would split a delivery whose fix lowers no bound. |
| D18 | An overflow may carry a null recommendation, meaning new design required; only `complete` requires null. Task 1 tests it through `gate` and `confirm`, Task 2 at both transports. | Phase-5 review (Codex): Task 1 made null equivalent to success, failing AC4's "new design required" case. `_recommend` returns None when no declared boundary fits; `validate_result` accepts it. | Requiring a recommendation on every overflow would turn a valid stop into `failed`. |
| D19 | `next` runs `evidence` before `ledger-complete`, and also for task M−1 before a fresh `--task M` without `--completed`. Amends D8's order. | Phase-5 review (Codex): a refused recording left a `complete` line, so a later `next --task N+1` could project over a tampered recording; the loader admits tail edits to process paths. D12. | Trusting the `complete` line lets an unverified forecast edit lower future bounds. A separate verified-marker line duplicates `evidence`. |
| D20 | `gate --save-dir DIR` and sdd-gate's `projection` step keep the validated result through one `save_result` as `projection-<head7>-<N>.json`; writing-plans passes `sdd-workspace <root>`. | Phase-5 review (Codex): D3 keeps the full result wherever a stop is recorded, and planning had no writer. `sdd-workspace` ensures the per-plan directory D6 keeps. | Embedding the result in the report breaks the 8192-byte wire bound (D3). Relying on `confirm` alone drops the required cache. |
| D21 | G0 keeps the producer's real exit, runs the projection twice at identical inputs, requires equal exits and bytes, then `validate-result` with that exit; any refusal fails closed. Amends D11 and D16; the provenance and G0 edits take the root past D16's 300 B, within the measured headroom of its 16,384 B forecast after five recordings. | Phase-5 review (Codex): `--producer-exit 0` rejected every valid exit 3, and `cmp` against `validate-result`'s echo of its input reproduced nothing. | Keeping the echo comparison proves only validity. Moving provenance to the spec breaks the provenance contract. |
| D22 | New skill-text pins cover only machine-consumed text: helper argv, the forecast headings and kinds the loader reads, report JSON. English phrases are not pinned, and a phrase pin on cut text is deleted. Amends D14's "keep every pinned string". | Phase-5 review (Codex). agent-helpers rule 6. | Pinning `reconciliation record` or the stop heading freezes prose the standard leaves free. |
| D23 | The replay derives process horizons from its task count and snapshots every workspace file's bytes. | Phase-5 review (Codex): the loader refuses a horizon above the task count, so the three-task child could not load, and a filename snapshot misses an overwritten result. | Reviewer's call accepted as-is. |

The design and grill frontier is closed within the approved scope. The retained project bindings give no context-map or ADR write route, so this ledger is the issue's decision store.
