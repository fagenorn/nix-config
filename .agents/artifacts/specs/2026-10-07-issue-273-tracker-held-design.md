# Hold an issue open as needs-verification instead of closing it

Design for [#273](https://github.com/fagenorn/nix-config/issues/273), slice S2
of the [acceptance-criteria gate](./2026-10-06-acceptance-criteria-gate-design.md)
(the "parent"). The parent's D1, D7, D8 and D11 bind this work. S1
([#272](./2026-10-07-issue-272-graded-acceptance-design.md)) already carries
`acceptance_state` (`met | unmet | human_pending | not_applicable`) from sdd
into both ship handoffs. Rows D1–D15 below are this issue's own decisions.

## Problem

sdd now grades every criterion, but ship still ignores the grade. Its
`close_tracker` stage closes the issue once the merge lands, and the PR body's
`Closes #<num>` trailer closes it on a default-branch merge even before that
stage runs. So an issue whose criteria are `unmet`, or still `human_pending`,
closes as if it were done, which is exactly the #262 failure. The delivery model
also cannot express any outcome but "closed": `close_tracker` and the
`tracker_closed` postcondition accept one observation kind, with
`state: "closed"`.

## Solution

Ship fixes one **effective acceptance state** at the end of Phase 0. With `met`
or `not_applicable` it closes the issue as it does today. With `unmet` or
`human_pending` it **holds** the issue: the PR still merges, if review and CI
allow it, but the PR carries no closing keyword. After the merge, ship labels
the issue `needs-verification`, creating the label when it is missing, and
posts a comment with the verdict table and a link to the acceptance record.
Under lifecycle identity, that hold is recorded as a new `tracker_held`
delivery observation. The observation satisfies the unchanged `close_tracker`
stage and the unchanged `tracker_closed` postcondition, so the delivery
completes and the contract and its digest stay as they are. Control already
treats a delivery-complete issue as delivered (#220), so it never relaunches a
held issue. Control's summary names the issue `held`. The issue stays open on
the tracker, so it stays an open blocker for its dependents.

## Decisions

### The `tracker_held` observation (delivery model)

- **Subject.** Exactly these members:
  - `tracker_repository_id`: a string;
  - `issue`: an integer of at least 1;
  - `state`: the literal `"open"`;
  - `label`: the literal `"needs-verification"`;
  - `comment_url`: a non-empty string;
  - `record_path`: a non-empty, relative POSIX path with no `..` component;
  - `acceptance_state`: `unmet` or `human_pending`;
  - `observation_identity`: a non-empty string, as for `tracker_closed`.

  Any other member set, `state` value, label or acceptance value is rejected.
  A hold never carries `met` or `not_applicable`, because those values close the
  issue (D2, D3).
- **One home for "what satisfies what".** The stage table keeps its 3-tuple, and
  `tracker_closed` stays the primary kind of `close_tracker`. The model gains one
  mapping, owned in the objects module, from each stage kind to the observation
  kinds that satisfy it, and another from each postcondition to the kinds that
  satisfy it. Both are derived from the stage table and `_POSTCONDITIONS`, and
  `close_tracker` and `tracker_closed` each add `tracker_held`. These five checks
  read the mappings instead of comparing against a single kind:
  - the observation-kind admission;
  - the reducer's stage matching;
  - the reducer's postcondition matching;
  - the wire validator's stage-fact check;
  - the wire validator's postcondition check.

  The mappings are exported as the model's observable set (`OBSERVATION_KINDS`).
  The builder derives its kinds from that set instead of from the tuple's third
  element (D1).
- **Matching.** `close_tracker` and the `tracker_closed` postcondition match a
  `tracker_held` subject whose repository is the contract's repository, whose
  issue is the contract's issue and whose state is `open`. A `tracker_closed`
  subject still needs `closed`. The existing rule, "more than one distinct
  matching subject is a rejection", now spans both kinds. A delivery therefore
  records exactly one tracker outcome: closed or held, never both (D4).
- **Contract unchanged.** A contract stage carries only `action`/`effect`
  (`close_issue`/`tracker_write`) and never the observation kind. The
  obligation key `tracker_closed` stays. The stage list, schema version, scope
  tuples and digests therefore cannot move, and the hold runs under the
  `close_tracker` stage's existing scope (D5).

### `build-delivery --kind observation`

`tracker_held` takes the facts `comment_url`, `record_path`, `acceptance_state`
and `observation_identity`. The builder supplies `tracker_repository_id` and
`issue` from the contract context, and the literals `state: "open"` and
`label: "needs-verification"`. The builder checks the closed acceptance set and
the relative path, so a bad fact fails fast with its reason. The model checks
both again (defense in depth). Source kind is `tracker`.

### Ship summary and finish

- A held run's legacy row is `state: merged`, `issue_closed: false`, and its
  notes name the hold and the comment URL. The owner-report rule in
  `artifact-budget` admits `issue_closed: false` beside `merged`. A `merged` row
  still needs a PR URL and a full SHA, and every other cell of the rule is
  unchanged. This amends #191 D3: the `merged`/`issue_closed: false` shape is
  no longer, by itself, the reconciliation signature on the wire. A reconciled
  issue's control summary reads `merged`, and a held one reads `held` (D7).
  The ledger keeps telling them apart by `result_source`.
- The inner check is in finish's `delivery_complete` path. When the tracker
  postcondition is observed, the historical row's `issue_closed` must be `true`
  exactly when that observation is `tracker_closed`, and `false` exactly when it
  is `tracker_held`. On a mismatch the summary is refused (D6).

### Control projection

- **Delivered.** A held issue is delivered because its postconditions are all
  observed, so control plans nothing for it and projects no current custody.
  This needs no change (#220).
- **The `held` state.** `control_summary` reports `held` for a delivered issue
  when two things are true: its `tracker_closed` postcondition is observed by a
  `tracker_held` observation, and the tracker reads `open`. The tracker
  reading `closed` still gives `closed`, which is the case after a human
  verifies and closes the issue.
- **The closed state set.** `held` joins the control summary state set in both
  of its homes: workflow-state's constant and the wire validator (D7).
- **No contract.** An issue that runs lifecycle-only, with no contract, has no
  observation to read. It reports `merged`, and its notes name the hold (D15).

### Blockers and orchestrate-issues

Dependents need no code. A held issue is open on the tracker, so the
adapter's normalized `open_blockers` for a dependent includes it, and control
plans that dependent as `blocked` (parent D7). `orchestrate-issues` §5 gains two
sentences:

- A `held` summary is reported as held: merged, open with `needs-verification`,
  and waiting for a human to verify it. It is never reported as queued,
  progressing or closed, and it has no relaunch line.
- A held issue stays in its dependents' `open_blockers` like any open issue,
  even though its summary is delivered.

### ship-issue

- **Effective acceptance state (end of Phase 0).** It starts from the handoff's
  `acceptance_state`. A standalone run with `review_state: unknown` is
  `not_applicable` and closes, as S1 defined.
  - `human_pending` with `auto: false`: ask the user to attest each
    `human_pending` row of the acceptance record. Attesting is always a
    grounded question.
    - If every row is attested, rewrite those Verdict cells to `met (attested)`,
      commit under `### Local commits` and continue with `met`. The new commit
      means Phase 2 cannot skip its rerun.
    - Otherwise keep `human_pending`.
  - `--auto` never asks and never self-attests (parent D8). The value is fixed
    for the rest of the run, and ship grades nothing (#272 D14).
- **PR body (Phase 4).** The body gains an `## Acceptance` section:
  - `Acceptance state: <effective value>`;
  - `Acceptance record: <record path | none>`;
  - when there is a record, a three-column table, `| AC | Kind | Verdict |`.

  The table copies the record's closed tokens, which is copying, not gating
  (parent D6). The `Closes #<num>` trailer appears only on the close branch. A
  hold body contains no closing keyword. The body stays inside the guard's
  character rules (D8, D9).
- **Close or hold (Phase 8 step 1 and the `close_tracker` cycle).**
  - The close branch is unchanged.
  - The hold branch runs these steps in order:
    1. View the issue's state.
    2. If it is `CLOSED`, which a commit's closing keyword can cause, reopen
       it.
    3. If `gh label list --search` shows no exact `needs-verification`, create
       the label (D10).
    4. `gh issue edit --add-label needs-verification`.
    5. Post the hold comment with `gh issue comment`. Its stdout is the
       comment URL.
       - The comment's first line is `Held for verification: <PR URL>`. The
         rest gives the effective state, the verdict table and the record's
         link at the merge SHA.
       - A relaunched owner first looks in `gh issue view --json comments` for
         a comment with that first line. If one exists, it reuses that comment's
         URL instead of posting again (D14).
    6. View the issue again to confirm it is open and labelled.
  - Under lifecycle identity, the cycle's observation is `tracker_held`, with
    `observation_identity` set to `github:issue:<num>:held`. Its scope and
    fences are exactly those of the close cycle.
  - "Observation-only when the merge already closed it" applies only to the
    close branch (D8).
- **Remainder mode.** A remainder has no handoff. It reads the PR body with
  `gh pr view --json body` and takes three things from it: its one
  `Acceptance state:` line, its one `Acceptance record:` line and its table.
  - `met` or `not_applicable` closes, and `unmet` or `human_pending` holds.
  - A missing or duplicated line, or a value outside the set, stops before the
    `close_tracker` effect with `terminal_failed`, and the notes name the line.
    It never defaults (D11).
- **Summary.** Phase 8 step 4 builds `issue_closed: true` on close and `false`
  on hold.
- **Unsupported tracker.** With an unsupported tracker capability, there is
  nothing to close or hold, as today.
- **from-issue.** `ship-handoff.md`'s "its close stage does not read it" becomes
  the close-or-hold rule. Its inline fallback also holds rather than closes.

## Test seams

All of these seams exist, and `just agent-workflow-tests` runs them. The
issue's file names are honored literally (D12).

1. **Reducer and object grammar (`test_delivery_model.py`).** These cases use
   prior art from the existing `tracker_closed` cases:
   - A `tracker_held` observation folds `close_tracker` to `observed` and the
     `tracker_closed` postcondition to `observed`.
   - A held subject with `state: "closed"`, a foreign issue, a label other
     than `needs-verification`, `acceptance_state` `met`/`not_applicable`, or an
     extra or missing member is rejected.
   - A held observation and a closed observation in the same delivery reject.
2. **Builder and digest (`test_workflow_delivery.py`).** These cases go through
   the `DeliveryRuntime.build_delivery` facade that `build-delivery` calls:
   - The builder builds `tracker_held`.
   - It refuses `acceptance_state: met` and an absolute `record_path`.
   - A `--kind contract` build of one fixed input against `resolved_snapshot`
     asserts the contract digest and the initial intent digest as literals.
     Both literals are captured at the base commit, 8a2e2631, before any model
     edit (criterion 3).
3. **Control (`test_workflow_state.py`).** The case is modelled on #220's
   `DeliveredControlTest`:
   - The issue's delivery completes through `tracker_held`, and its tracker is
     observed `open`.
   - Past the remainder deadline, control plans no action or delta for it.
   - Its summary is `held`, with null owner and empty pending stages.
   - A dependent whose `open_blockers` names it is `blocked`.

   The #220 driver helpers move into a plain mixin in `test_delivered_control.py`,
   which both test classes use. Importing the `TestCase` itself would run its
   tests twice.
4. **Owner-report rule (`test_artifact_budget.py`).** The `merged` row with
   `issue_closed: false` is now accepted. #191's
   `test_only_response_result_slots_accept_the_reconciliation_record` changes
   on purpose:
   - Its `bare` record is now accepted at `ship-summary`.
   - Its uncited `present` and `unpublished` records are still refused there.

   The finish cross-check's mismatch is refused, in `test_delivery_workflow.py`,
   which is the finish-path prior art.
5. **Skill text (`test_workflow_skill_contracts.py`).** These are phrase
   assertions:
   - The delivery loop names `tracker_held` and `needs-verification`.
   - Phase 8 names the hold branch and the label creation.
   - The PR template carries `## Acceptance` and `Acceptance state:`.
   - The trailer is conditional.
   - `orchestrate-issues` names `held`.

   The existing `Closes #<num>` assertion and the guard-parse example in
   `test_shell_example_contracts.py` stay green against the new template. If
   the text grows past an entry's `instruction-load.json` ceiling, that ceiling
   is raised and its note is rewritten in the same commit (#155 D10).

## Out of scope

- The parent's own out-of-scope list: no threshold evaluator, no CI
  re-measurement, no retroactive grading, no new auditor, and no change to the
  contract's stages, schema or digest.
- S3 (#274): criterion tags and the acceptance map.
- What a `/from-issue` re-entry does on a held issue, beyond the existing
  merged-PR path.
- Removing the label or closing the issue after a human verifies it. That is
  a manual tracker action.
- Lifecycle-guard or permission-surface changes. The hold's `gh issue`/`gh label`
  verbs are unguarded, as `gh issue close` is today.
- Moving `artifact_budget.py` or the delivery scripts into `agent_tools`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Stage→kinds and postcondition→kinds mappings, derived in the objects module and exported as `OBSERVATION_KINDS`. They are the single home that the five checks and the builder read. | the-bar DRY. Today the five checks each hard-code "one kind". | Widen the `STAGE_ACTIONS` tuple, which breaks every unpacking caller, or special-case `close_tracker` at each check (five copies). |
| D2 | Subject = parent's members plus `observation_identity`. `label` is the literal constant, and `record_path` is required. | Parent "Hold, not close". Parent D11 makes the label a constant. A hold only follows grading, and S1 D5 then always commits a record. | A nullable `record_path`. No hold exists without a record. |
| D3 | A hold's `acceptance_state` is `unmet` or `human_pending`. `met`/`not_applicable` are rejected in the builder and in the model. | Parent: met/not_applicable close. Fail loud on a closed set. | Accept any S1 value: a "held but met" record would be untruthful. |
| D4 | One tracker outcome per delivery. The conflicting-subject rejection spans `tracker_closed` and `tracker_held`. | The existing reducer rule. Truthful terminal states. | Let the latest observation win, which hides a held-then-closed contradiction inside one delivery. |
| D5 | The hold runs under `close_tracker`'s existing scope (`close_issue`/`tracker_write` on that issue), with no new scope or intent. | Issue: "without a contract change". Parent D1, accepted by the controller. The hold is a weaker write to the same target. | A `hold_issue` scope, which changes intents and digests (criterion 3). |
| D6 | The legacy owner rule admits `merged` with `issue_closed: false`. Finish refuses an `issue_closed` that disagrees with the observed tracker kind. | The row has to say truthfully that the issue is not closed. Defense in depth puts the inner check where the reduction is. | A new `held` legacy state or key: it widens the 9-key row and every ledger result reader. |
| D7 | Control summaries gain the state `held` (delivered, held observation, tracker open). | Issue: "reports it as held". Today the summary would read `queued`. | Let the skill infer it from a delivered summary that is not `closed`: that is judgment at the reporting surface, and fragile. |
| D8 | The PR body omits `Closes #<num>` when held. A post-merge `CLOSED` state (a commit keyword) is reopened in the hold branch. | GitHub closes on a default-branch merge with a keyword (ship-issue Phase 4). The hold must leave the issue open. | Keep the trailer and reopen every time, which emits close/reopen noise on every hold. Fail on `CLOSED`, which strands a merged delivery. |
| D9 | The PR and comment tables have three columns, `AC`, `Kind` and `Verdict`, all closed tokens, and link to the record for the rest. | Guard body rules (no `"` `$` backtick backslash). the-bar Token economy. | Copy all eight record columns, whose free text breaks the guard's body form. |
| D10 | The label is created only when `gh label list --search` lacks an exact match. It is never `--force`d. | Parent D11: "creates it on demand". | `gh label create --force`, which overwrites a user's color or description. |
| D11 | A remainder reads the state and the record from its PR body's `## Acceptance` lines. Anything malformed fails before the effect. | A remainder has no handoff. The PR body is the forge-durable record ship wrote. Fail loud. | Close by default, which bypasses the gate. Add the state to the ledger or remainder wire, which widens schemas for one field. |
| D12 | Test files are as the criteria name them. The #220 helpers move into a mixin that `test_workflow_state.py` reuses. The digest literals are pinned at base 8a2e2631. | The criteria name the files, and the grader checks that the named check exists (#272 D2). | Put the control case in `test_delivered_control.py`: the grader would find no case in the named file. |
| D13 | Interactive attestation happens at the end of Phase 0. It writes `met (attested)` into the record and commits before Phase 2. | Parent D8. The record is the single home of verdicts (parent D4). | Attest after the merge: the record could no longer be committed on the branch. |
| D14 | The hold comment's first line is `Held for verification: <PR URL>`. A relaunch reuses an existing comment with that line, so a repeated cycle builds an identical subject. | A cycle can repeat after a relaunch. D4 rejects two different held subjects, and the close branch is already idempotent (view before close). | Post a fresh comment on every cycle: a duplicate comment, and a second subject that D4 rejects. |
| D15 | `held` is projected only from a `tracker_held` observation. A lifecycle-only run reports `merged`, and its notes name the hold. | That run has no observation to read. D7 bases the projection on evidence. | Infer `held` from `issue_closed: false`, which collides with the reconciliation shape (#191 D3). |
