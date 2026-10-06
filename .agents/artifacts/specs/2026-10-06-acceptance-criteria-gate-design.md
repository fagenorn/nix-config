# Acceptance-criteria gate — an issue closes only when its own criteria are graded met

Design for pipeline improvement **A**, 2026-10-06. Sibling improvement **B**
(a light lane that cuts ceremony) is designed separately. This gate must stay
cheap enough that B never has to remove it. Decisions D1–D11 bind the plan.

## Problem

An issue's acceptance criteria are the contract its author wrote. Nothing in the
pipeline grades them against the delivered work.

[#262](https://github.com/fagenorn/nix-config/issues/262) ("Halve
agent-workflow-tests wall time") is the evidence. Two of its four criteria were
measurements: "completes in at most half its base-commit wall time" and "no
module takes longer than 90 seconds serially". The delivered branch was 39%
faster, and the 90-second limit was never measured. The PR merged and the issue
closed anyway. Each stage that could have caught this had a gap:

- **Conformance review** (sdd's final review, conformance axis) receives the
  issue, the spec and the plan, but it reads only the diff. A measurement is not
  in the diff, so a measured criterion is never graded. Nothing stops an unmet
  criterion from being parked with a ruling, so it does not survive as a
  residual either.
- **The plan** maps tasks to verification lines, not issue criteria to checks.
  A criterion that no task owns is invisible.
- **The delivery contract's `acceptance_ref`** is only a pointer (the spec root,
  or the issue URL in remainder mode). It records where the criteria live, not
  whether they hold.
- **Ship's `close_tracker` stage** closes the issue unconditionally once the
  merge lands.
- **`to-issues`** requires each criterion to be falsifiable, but not to say
  where it is measured. "Measured on mbp, idle machine" looks the same as a
  unit test until someone has to grade it.

For the user, a closed issue does not mean "done as written". Reopening one
needs a human to notice the gap after the fact.

## Solution

Every criterion gets a **kind**, a **place it is measured** and, at the end of
execution, a **verdict**. The issue closes only when every verdict is `met`.
Otherwise the work still merges, if review and CI allow it, and the issue
stays open, labelled `needs-verification` and carrying the verdict table.

1. **Authoring (`to-issues`).** Each criterion line carries its kind and its
   measurement place: `- [ ] [code] … — measured: <test, check or CI job>`. The
   three kinds are:
   - `code`: a check that any reviewer reproduces at the head, such as a test,
     the build or a CI job.
   - `evidence`: a measurement taken outside the gating suite. It names the
     command, the conditions and a literal threshold.
   - `human`: needs a person's judgment or an environment the agent cannot
     control.
2. **Planning (`writing-plans`).** The plan gets an `## Acceptance map`, one
   row per issue criterion: `AC<n>`, the kind, the owning task and the check.
   For `evidence`, the check names the command, the conditions and the record
   row the implementer fills in. The plan review blocks a plan that is missing
   a row.
3. **Execution (`sdd`).** A task that owns an `evidence` criterion writes its
   measurement into the issue's **acceptance record**, a committed Markdown
   file beside the plan. Each row gives the value, the commit measured, the
   command and the conditions. Implementers never write verdicts.
4. **Grading (sdd final review, conformance axis, moved to Opus/high).** The
   axis that already reads the issue grades every criterion and returns a per-criterion verdict:
   `met | unmet | unverified | human_pending`.
   - A `code` criterion is met when its named check exists in the diff or the
     repository and passes in the final verification.
   - An `evidence` criterion is met only when its record row shows a value
     inside the literal threshold, at a commit whose later changes leave the
     measured surface alone. Rounding or "close enough" never counts.
   - An `unmet` or `unverified` verdict is an **acceptance finding**. It enters
     the fix wave like any Important finding, and it can never be parked with a
     ruling.

   After the final review, the sdd controller writes the verdict column into
   the acceptance record and commits it. It also reports one summary field,
   `acceptance_state: met | unmet | human_pending | not_applicable`.
5. **Delivery (`ship-issue`).** `acceptance_state` travels in the ship handoff.
   - `met` (or `not_applicable`): the `close_tracker` stage closes the issue,
     as it does today.
   - Any other value: the stage instead **holds** the issue. Ship adds the
     `needs-verification` label (creating the label if it is absent) and
     comments with the verdict table and a link to the record. That writes a
     new `tracker_held` observation, which satisfies the stage and the tracker
     postcondition. Delivery completes truthfully: the PR merged and the issue
     is held, not closed.

   The PR body always carries the verdict table.

Code-only issues pay almost nothing. Their acceptance map rows are test names,
grading happens inside a review that already runs (only its model tier
rises, from Sonnet to Opus), and no new agent or
measurement step is added (D3, D9).

## Decisions

**Criterion kinds and their place.** There are exactly three kinds, a closed
set, and they are written inline on the criterion line. The issue body stays the
contract (`to-issues`: "the body is the contract"), so the kind lives there, not
in a sidecar. `to-issues` also gains a rule: prefer `code`, then `evidence`, and
use `human` only when no agent can produce the observation. Its existing
falsifiability rule now also requires the `measured:` clause to name an
observation that fails at the base commit. A legacy, untagged criterion is
assigned its kind by the planner in the acceptance map. If no plan exists, the
conformance axis assigns it. A criterion that cannot be classified grades as
`unverified` (D2).

**Acceptance map** (plan section). It has one row per issue criterion, in issue
order, and it is the plan's only acceptance surface. `REVIEW-CONTRACT.md`
gains a blocking check: there is exactly one row per criterion, and every
`evidence` row names its command, its conditions and its threshold. The map is
an input to grading, not a prerequisite for it. A lane with no plan (B's light
lane) still grades, because the conformance axis falls back to the issue's own
tagged lines (D9).

**Acceptance record.** One committed file per issue, beside the plan, in the
existing plans artifacts directory. No new project binding is needed. Its
columns are the criterion, kind, check or command, observed value, commit
measured, conditions and verdict.

- Implementers fill in the evidence columns as part of the task that owns the
  criterion.
- The sdd controller alone fills in the verdict column, after the final review.

The record is the single durable home of the verdicts and the evidence. The PR
body, the hold comment and a later `/from-issue` re-entry (investigate.md's
merged-PR path) all read it (D4).

**Grading seat.** Grading belongs to the existing conformance axis, whose
dispatch moves from Sonnet/high to Opus/high. Its `agent-dispatch` marker and
`final-review.md`'s tier sentence change with it, along with any model-matrix
row that declares that role. It does not get a new auditor. The prompt gains a required `## Acceptance`
table in the verdict. An `evidence` verdict of `met` must cite the observed
value and the threshold. The controller rejects a `met` verdict that lacks
either citation and records the criterion as `unverified`. Unmet and unverified
criteria are acceptance findings, governed by D5 (D3, D5).

**Report fields.** Two additive, closed fields, validated by `artifact-budget
validate-report`:

- The `sdd` boundary gains `acceptance_state`.
  - `complete`/`clean` allows `met`, `human_pending` or `not_applicable`.
  - `residuals` allows any value.
  - `unmet` requires `residuals`, with detail present.
  - `failed` with base and head null requires `not_applicable`.
- The `ship-handoff` boundary carries the same field forward unchanged.

`not_applicable` means the run had no issue, or the issue had no criteria
(D6).

**Hold, not close.** The delivery contract's stages and digests do not change.
The `close_tracker` stage keeps its id and action. The delivery model accepts a
second observation kind for it, `tracker_held`. Its subject is the tracker
repository, the issue, `state: open`, the label, the comment URL, the record
path and the `acceptance_state`. `tracker_held` also satisfies the tracker
postcondition. `workflow-state build-delivery --kind observation` builds it.

Control already derives "delivered" from the observed postconditions (#220), so
a held issue is delivered and is never relaunched. `orchestrate-issues` treats a
held issue as an open blocker for its dependents, because they were written
against criteria that are not yet true. The ledger-free path (Phase 8, step 1)
branches the same way (D1, D7).

**Human criteria.** In an interactive run with the user present, ship asks the
user to attest each `human_pending` criterion before the close stage. The user's
"met" is recorded in the record as `met (attested)`. In `--auto` there is no one
to ask, so the issue is held. The agent never self-attests (D8).

**Evidence freshness.** An evidence row binds the commit it measured. The
grader accepts the row when the commits after it in the range leave the
measured surface alone. Otherwise it grades `unverified`, and the fix wave
re-measures. Ship's delta review applies the same check to its delta. This is
reviewer judgment against a named surface. It is not a new mechanism (D10).

## Test seams

All of these seams already exist (agreed per the `design` skill's seam guard).
`just agent-workflow-tests` runs them all.

1. **`artifact-budget validate-report`** at the `sdd` and `ship-handoff`
   boundaries. This seam covers the `acceptance_state` pairing table, using
   accepted and rejected fixtures in the style of the existing
   `review_state`/`verification_state` cases in `test_artifact_budget.py`.
2. **The delivery model and `workflow-state build-delivery --kind observation`.**
   This seam covers `tracker_held`: it is built, it satisfies `close_tracker`
   and the tracker postcondition, a malformed subject is rejected, and a held
   delivery is projected as delivered to `control`. Prior art is
   `test_delivery_model.py`, `test_workflow_delivery.py` and the #220 cases in
   `test_workflow_state.py`.
3. **Skill-text contract tests** (`test_workflow_skill_contracts.py`). They
   assert these phrases, not the prose around them:
   - the `to-issues` criterion shape (kind tag and `measured:` clause);
   - the `writing-plans` `## Acceptance map` section and its review check;
   - the conformance prompt's required `## Acceptance` table;
   - the rule that acceptance findings can never be parked;
   - ship's close-or-hold branch.

   The dispatch-marker inventory (`test_dispatch_contracts.py`) changes one
   value: the `sdd-final-conformance-review` marker's model moves from `sonnet`
   to `opus`. The marker count stays the same, which proves no new agent was
   added.

No new seam is introduced. In particular there is no parser of the acceptance
record: the gating decision rides on the validated `acceptance_state` field.

## Out of scope

- **A machine evaluator for thresholds.** An evidence verdict remains reviewer
  judgment, constrained by the required citations.
- **Re-running measurements in CI.** CI still does not run on macOS (CLAUDE.md),
  and evidence is measured where the criterion says.
- **Retroactively grading closed issues, including #262.** Reopening #262 is a
  separate tracker action for the user.
- **A new Opus auditor agent or a separate audit phase.**
- **Changing the delivery contract's stage list, its schema version or the
  contract digest.**
- **Checking evidence authenticity** (whether a timing was really measured
  idle) beyond the recorded conditions.
- **Light-lane routing (B).** This design only guarantees that grading works
  without a plan.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Unmet, unverified or human-pending criteria → **the PR may merge and the issue is held open** (`needs-verification` label plus verdict comment), via a new `tracker_held` observation that satisfies `close_tracker`. Accepted by the controller. | Partial work like #262's 39% is a real improvement. Review and CI already gate the merge. #220 derives "delivered" from postconditions. Truthful terminal states (the-bar). | Block the merge and suspend at `human_gate`. This needs no model change, but it strands passing work and turns every evidence miss into a human interrupt. |
| D2 | Three closed kinds (`code`, `evidence`, `human`), written inline on the issue's criterion line with a `measured:` clause. Untagged legacy criteria are classified downstream, and an unclassifiable one grades `unverified`. | The body is the contract (`to-issues`). Fail loud on a closed set (the-bar). | A sidecar metadata block. It would drift from the body, and the body is what later contexts read. |
| D3 | Grading stays inside the existing conformance axis, with required citations for evidence, and that axis moves from Sonnet/high to Opus/high. No dispatch is added. | Prior-session review study: on real historical defects, Sonnet reviewers caught 0/10 and Opus 6/10. On seeded defects, Sonnet caught 10/12 and Opus 12/12, with no false blocks for either. The study flagged the Sonnet final-conformance axis as suspect. Constraint: keep the gate cheap for B (no extra dispatch). | A separate Opus auditor: an extra dispatch on every issue. Keeping the Sonnet axis: 0/10 catch rate on real defects. |
| D4 | The acceptance record is a committed file beside the plan, in the existing plans directory. Implementers write its evidence and the sdd controller writes its verdicts. | The record must outlive the worktree and the sdd workspace (deleted on Clean). It is reviewable in the diff. No new binding is needed. | The PR body only (the PR does not exist at grading time), or the sdd ledger (transient). |
| D5 | Acceptance findings are Important findings that enter the fix wave and can **never** be parked with a ruling, so a residual unmet criterion forces `residuals`. | #262's rationalization path. sdd's Clean state allows "parked-with-ruling". | Allow parking with a ruling. That is the exact hole this design closes. |
| D6 | Add one closed field, `acceptance_state`, to the `sdd` and `ship-handoff` reports. Per-criterion rows never travel inline. | Reports never inline artifact contents (`design`/`artifact-budget` rule). Gating must be mechanical and validated. | Have ship parse the record's Markdown. That puts judgment-bearing parsing at the gate. |
| D7 | A held issue is delivered for control (never relaunched), but it is an open blocker for its dependents. | #220's postcondition-derived custody. `orchestrate-issues` `open_blockers`. | Unblock dependents. They would build on criteria that are not yet true. |
| D8 | `human` criteria are attested by the user in interactive runs and held in `--auto`. The agent never self-attests. | AUTO.md: "never self-answer a request for new authorization"; silence creates no grant. | Have the agent attest from indirect evidence. That is the same rationalization risk as D5. |
| D9 | The acceptance map is an input to grading, not a prerequisite. Grading falls back to the issue's tagged lines when no plan exists. | Constraint from sibling B (light lane). | Make the map mandatory for grading. B would have to remove or bypass the gate. |
| D10 | Evidence freshness is checked by reviewer judgment against the measured surface. A stale row grades `unverified` and is re-measured. | YAGNI (the-bar). The existing delta review already reads the post-review range. | A tree-digest binding for every evidence row. That would need machinery without a demonstrated need. |
| D11 | The label is literally `needs-verification` and ship creates it on demand. It is not a project-policy binding. Accepted by the controller. | The repo already uses fixed label vocabularies (`agent:ready`, `wayfinder:*`). The project contract has no label binding. | Add a `bindings.tracker.labels` member. That is new policy surface for a single constant. |

## Proposed slices

**S1 — Graded acceptance in sdd** (autonomous; blocked by: none)

The conformance axis grades every criterion. The controller writes and commits
the acceptance record, acceptance findings cannot be parked, and the sdd and
ship-handoff reports carry `acceptance_state`.

- An `sdd` report with `review_state: clean` and `acceptance_state: unmet` is
  rejected (exit 2), and `residuals` with `unmet` and detail present is
  accepted. Measured by: `test_artifact_budget.py` under
  `just agent-workflow-tests`.
- A `ship-handoff` report missing `acceptance_state` is rejected. Measured by:
  `test_artifact_budget.py`.
- The `sdd-final-conformance-review` dispatch marker declares `model=opus
  effort=high`, and the marker inventory's count is unchanged. Measured by:
  `test_dispatch_contracts.py`, and the model-matrix tests where the role is
  declared.
- The conformance prompt requires an `## Acceptance` table with
  `met|unmet|unverified|human_pending` verdicts, and an evidence `met` must cite
  the observed value and the threshold. Measured by: an assertion in
  `test_workflow_skill_contracts.py`.
- `final-review.md` states that acceptance findings are never parked with a
  ruling. Measured by: an assertion in `test_workflow_skill_contracts.py`.

**S2 — Hold instead of close** (autonomous once D1 is confirmed; blocked by: S1)

`tracker_held` is added to the delivery model and `build-delivery`, ship's
close-or-hold branch is added (delivery loop and ledger-free Phase 8), and
`orchestrate-issues` reports held issues.

- `build-delivery --kind observation` builds a `tracker_held` observation, and
  the reducer accepts it as satisfying `close_tracker`. A subject with
  `state: closed` is rejected. Measured by: `test_delivery_model.py` and
  `test_workflow_delivery.py`.
- A delivery whose tracker postcondition is `tracker_held` projects no current
  custody, and `control` plans no launch for it. Measured by: a
  `test_workflow_state.py` case modelled on #220's.
- The installed contract digest for an unchanged input is identical before and
  after the change. Measured by: an assertion against a fixture in
  `test_workflow_delivery.py`.
- `ship-issue` names the `needs-verification` hold branch in both the delivery
  loop and Phase 8, and the PR body carries the verdict table. Measured by:
  `test_workflow_skill_contracts.py`.

**S3 — Typed, located criteria at authoring and planning** (autonomous; blocked by: none)

`to-issues` gains the criterion shape, `writing-plans` gains the
`## Acceptance map` section, and `REVIEW-CONTRACT.md` gains the blocking
check.

- The `to-issues` template shows `[code|evidence|human]` and `measured:` on
  every criterion line. Measured by: `test_workflow_skill_contracts.py`.
- `writing-plans` requires `## Acceptance map` with one row per issue criterion,
  and `REVIEW-CONTRACT.md` blocks a missing row. Measured by:
  `test_workflow_skill_contracts.py`.
- The from-issue eval fixture issue `001-well-specified` carries tagged
  criteria, and the eval grading lists a map row for each one. Measured by:
  `test_workflow_skill_contracts.py`'s live-eval grading test.
- No new `agent-dispatch` marker exists. Measured by:
  `test_dispatch_contracts.py`, whose marker count is unchanged.
