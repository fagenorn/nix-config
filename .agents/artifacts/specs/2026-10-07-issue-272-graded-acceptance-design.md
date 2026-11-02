# Issue 272: graded acceptance in sdd

Slice S1 of the [acceptance-criteria gate](2026-10-06-acceptance-criteria-gate-design.md)
(the "parent"). The parent's decisions D1 to D11 bind this slice and are cited
as "parent D<n>". They are not restated here. This document pins the S1
interfaces concretely. Its own decisions are D1 to D10 in the ledger below.

## Problem

sdd's final review grades the diff and nothing else. An issue's acceptance
criteria (above all its measurements) are never graded, and nothing stops an
unmet criterion from being parked with a ruling. sdd then reports `clean`, and
ship closes the issue. That is #262's path (parent, Problem).

S1 closes the grading half. Every criterion gets a verdict inside the review
that already runs. An unmet criterion cannot leave sdd as `clean`. The verdict
summary travels to ship as one validated field. What ship does with that field
(hold instead of close) is S2 (#273).

## Solution

1. **The conformance axis grades.** The existing final conformance dispatch
   moves from Sonnet/high to Opus/high (parent D3). It gets the issue's
   criterion lines and returns a required `### Acceptance` table with one
   verdict per criterion: `met`, `unmet`, `unverified` or `human_pending`.
2. **Acceptance findings.** Every `unmet` or `unverified` row is an acceptance
   finding. It enters the single fix wave as an Important conformance finding,
   and it is never parked with a ruling (parent D5).
3. **The controller finalizes and commits the record.** After the scoped
   re-reviews, the sdd controller applies its citation checks. It then writes
   the acceptance record (verdict column included) and commits it, before the
   Final verification step runs.
4. **One closed field on two reports.** The sdd report and the ship handoff (in
   both its legacy and version-2 shapes) carry a required `acceptance_state`.
   Its values are `met`, `unmet`, `human_pending` and `not_applicable`.
   `artifact-budget validate-report` checks it against a pairing table
   (parent D6).

## Decisions

### Criterion source and kinds

When the sdd caller supplies an issue, the controller copies that issue's
acceptance-criteria checkbox lines verbatim, in issue order. It numbers them
`AC1`…`ACn`. That numbering is shared with S3's acceptance map and with the
record. The lines go into the conformance dispatch as one new placeholder,
`[ACCEPTANCE_CRITERIA]`.

There is no criterion source when sdd has no issue (a standalone plan, or an
intent-statement `[ISSUE_REF]`), or when the issue has no such lines. Then the
placeholder and the `### Acceptance` section are both omitted, no record is
written, and the run reports `not_applicable`.

The grader takes each criterion's kind (`code`, `evidence` or `human`) from the
plan's `## Acceptance map` when the plan has one (S3). Otherwise it takes the
kind from the criterion's inline tag. An untagged legacy line is classified by
the grader, and a line it cannot classify grades `unverified` (parent D2, D9;
D1). S1 does not require an acceptance map.

### Grading rules (conformance prompt)

- **`code`.** The criterion is `met` when its named check exists at the head and
  is part of the declared verification, which the Final verification step then
  runs. A named check outside the declared verification (for example a CI job's
  command) is `met` only when the grader ran it at the graded head and cites the
  command and its pass. Otherwise the criterion is `unverified`. A named check
  that is absent, or that the grader ran and saw fail, is `unmet` (D2).
- **`evidence`.** The criterion is `met` only when its record row shows a value
  inside the criterion's literal threshold, and the commits after the measured
  commit leave the measured surface alone (parent D10). The citation must give
  the observed value and the literal threshold. Rounding or "close enough" never
  counts. A missing row is `unverified`, a stale row is `unverified`, and a value
  outside the threshold is `unmet`.
- **`human`.** Always `human_pending`. The grader never attests (parent D8).

### Conformance output shape

The prompt's Output Format gains one required section, placed after
`### Coverage`:

```
### Acceptance
| AC | Kind | Verdict | Citation |
```

There is one row per `ACn`, in order. `Verdict` takes exactly one of the four
tokens. `Citation` holds whatever the rule above requires. For a `code`
criterion that is the check name and either `in final verification` or the
command the grader ran with its result. For an `evidence` criterion it is
`observed <value> at <sha7> vs threshold <literal>`. For an `unverified` or
`unmet` row it names what is missing or failing.

The first-line axis verdict is `Findings` whenever any row is `unmet` or
`unverified`. The table is outside the existing ≤400-word budget, so a long
criterion list cannot crowd out findings (D3). The section is omitted exactly
when `[ACCEPTANCE_CRITERIA]` is omitted.

### Controller rules (`final-review.md`)

1. **Citation check, on the first pass and on every re-review.** An `evidence`
   `met` that lacks the observed value or the threshold is recorded as
   `unverified`. A `code` `met` whose check is outside the declared verification
   and has no cited run is recorded as `unverified`. When the table is missing,
   or a row is missing, every missing row is recorded as `unverified`, so a
   verdict that omits a criterion can only fail toward an acceptance finding
   (D3).
2. **Fix wave.** Each `unmet` or `unverified` row joins the fixer's list as an
   Important finding labelled `conformance` and `ACn`. For an `evidence`
   criterion, the fix is to re-measure and write the row's evidence columns.
   The existing scoped conformance re-review (reviewer-lite) re-verdicts those
   findings. Its `ADDRESSED` verdict on an `evidence` criterion must carry the
   same citation as a first-pass `met`. Without that citation the controller
   records `unverified`. No dispatch is added (D4).
3. **Never parked.** An acceptance finding is never parked with a ruling, and
   the residual adjudication never turns it into a parked line. An acceptance
   finding that survives the fix wave is load-bearing. It sets
   `conformance_verdict: findings` and forces the Residuals terminal state.
4. **Record, then verify.** After the re-reviews, the controller writes the
   verdict column into the acceptance record. When the record has no rows yet,
   the controller writes the whole record. It commits the record, and then runs
   the Final verification step. That verified tree therefore already contains
   the record, so ship's `verified-tree check` still matches (#263). If the
   Final verification repair round does not pass, every `code` row whose check
   failed becomes `unmet` in a second record commit, and that is an acceptance
   finding as in step 3. The run is Residuals with `verification_state:
   failed` either way (D5).
5. **Commit fence.** Under a lifecycle identity, the controller registers itself
   as a worker of its launch for the record commit and commits through
   `launch-commit`, then releases with `--event returned`, exactly like any
   other writer (#222). It uses plain `git` without a lifecycle identity (D6).
6. **Derive `acceptance_state`.**
   - No criterion source, or a failure before the conformance axis graded:
     `not_applicable`.
   - Any final verdict `unmet` or `unverified`: `unmet`.
   - Otherwise, any `human_pending`: `human_pending`.
   - Otherwise: `met`.

### Acceptance record

The record is one committed file per plan, beside the plan:
`<plans dir>/<plan stem>.acceptance.md`. It sits outside `<plan stem>.tasks/`,
so the plan artifact's members and metrics do not change (parent D4; D7). The
schema has one home, `final-review.md`:

```
# Acceptance record — issue #<n>

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
```

- Rows follow `ACn` order. `Criterion` is the issue line verbatim, without its
  checkbox.
- The evidence columns (`Observed`, `Commit`, `Conditions`) are written by
  whoever measured: an implementer whose task brief names the measurement, or
  the final-review fixer. For `code` rows, `Observed` is `in final verification`
  or the cited run. For `human` rows the evidence columns hold `—`.
- Only the sdd controller writes `Verdict`, and `Verdict` uses the four grading
  tokens (S2 adds `met (attested)`).
- No code parses the record (parent, Test seams). The gate is
  `acceptance_state`.

### `acceptance_state` pairing (artifact-budget)

The field is required on every report shape listed below, so a report without
it is rejected. Its value is drawn from a closed set: `met`, `unmet`,
`human_pending` or `not_applicable`. The sets of values allowed in each state:

| Report | State | Allowed `acceptance_state` |
|---|---|---|
| sdd | `complete` / `clean` | `met`, `human_pending`, `not_applicable` |
| sdd | `residuals` / `residuals` | any. `unmet` additionally requires `conformance_verdict: findings` |
| sdd | `failed` / `unknown`, SHAs null | `not_applicable` |
| sdd | `failed` / `unknown`, SHAs set, conformance `not_run` | `not_applicable` |
| sdd | `failed` / `unknown`, SHAs set, conformance graded | any |
| ship-handoff (legacy and v2) | `review_state: clean` | `met`, `human_pending`, `not_applicable` |
| ship-handoff (legacy and v2) | `review_state: residuals` | any |
| ship-handoff (legacy and v2) | `review_state: unknown` | `not_applicable` |

The existing `residuals` rule already requires `detail_state: present`, so
`unmet` with detail is accepted, and `unmet` under `clean` exits 2.
`not_applicable` covers the parent's meaning (no issue, or no criteria). It
also covers "nothing was graded", which the parent's own failed-with-null-SHAs
row already uses (D8).

The closed set and the pairing have one home, in artifact-budget. The delivery
model's version-2 handoff validator admits `acceptance_state` into its exact
key set as a string, which is how it already treats `review_state`. Then
artifact-budget applies the shared pairing rule to the validated version-2
value, following the existing precedent of the ship-summary legacy-slot rule
(D9). The handoff key is not part of the delivery contract, so the contract
and its digest do not change.

`from-issue`'s ship-handoff templates (both shapes) copy the sdd report's
value unchanged. `ship-issue` validates the field and carries it, but S1 does
not change its close stage.

### Tier change ripple

- The `conformance-reviewer` role is kept, and its tier moves to `opus`/`high`
  everywhere the tier is declared:
  - the model matrix's role, its dispatch row and its sdd event;
  - the matrix module's and the matrix test's expected-tier tables;
  - the prompt's marker, its `Agent(...)` call and its subagent line.

  The role's distinct value is its eligibility (conformance only, with
  correctness review prohibited), not its tier (D10).
- In `final-review.md`, the conformance-axis bullet's sentence giving the
  Sonnet tier and its "checklist-shaped work" reason is replaced. The new
  sentence names Opus/high, citing parent D3.
- The marker inventory count is unchanged.
- The instruction-load ceilings of the profiles that load a grown file are
  re-measured and raised, each with a "Ceiling raised for #272" note (#155
  D10). The grown files are `conformance-reviewer-prompt.md`,
  `final-review.md`, sdd `SKILL.md` and `ship-handoff.md`.

## Test seams

These are existing seams only (parent, Test seams 1 and 3), all run by `just
agent-workflow-tests`:

1. **`artifact-budget validate-report`, sdd and ship-handoff boundaries**
   (`test_artifact_budget.py`). The pairing table is tested with accepted and
   rejected fixtures, in the style of the existing
   `review_state`/`verification_state` cases. At minimum it covers:
   - `clean` with `unmet` exits 2;
   - `residuals` with `unmet` and detail is accepted;
   - `residuals` with `unmet` and a clean conformance axis exits 2;
   - a missing field exits 2 for the sdd report, the legacy handoff and the v2
     handoff;
   - an out-of-set value exits 2.

   The delivery model's own suite (`test_delivery_model.py`) and the shared
   handoff fixture gain the key.
2. **Dispatch and matrix inventories** (`test_dispatch_contracts.py`,
   `test_agent_model_matrix.py`). These cover the marker value and the role
   tier, with the marker count unchanged.
3. **Skill-text contracts** (`test_workflow_skill_contracts.py`). These assert
   phrases, not prose:
   - the conformance prompt's `### Acceptance` table header, the four verdict
     tokens and the evidence citation rule;
   - `final-review.md`'s never-parked sentence and its record-before-verification
     order;
   - the record path pattern;
   - `acceptance_state` in sdd's Finish key list and in both ship-handoff
     templates.

## Out of scope

- S2 (#273): `tracker_held`, the hold instead of close, `needs-verification`,
  and the verdict table in the PR body. Ship still closes as it does today.
  Until S2 lands, a `clean` run that reports `human_pending` still closes its
  issue. That is a known gap in the interim, and S2 closes it.
- S3 (#274): `to-issues`' criterion shape, `writing-plans`' acceptance map and
  its review check. This also covers the implementer-prompt wording that gives
  a task ownership of an evidence row.
- Implementer model routing (#270) and the light lane (#284).
- Any record parser, and any machine threshold evaluator (parent, Out of scope).
- Changing the delivery contract, its stages or its digest.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The controller passes the issue's criterion lines verbatim as `AC1..n` in one `[ACCEPTANCE_CRITERIA]` placeholder. Kinds come from the plan's acceptance map when present, else from the inline tags, else the grader classifies. No source gives `not_applicable`. | Parent D2 and D9 (grading must work without a map). the-bar Token economy (short stable handles). | Let the reviewer fetch the issue itself: the numbering could drift from the record, and every run pays a tracker read. |
| D2 | A `code` check that is not in the declared verification is `met` only with a cited grader run at the graded head. Otherwise it is `unverified`. | Parent: "a check that any reviewer reproduces at the head". Truthful terminal states. | Treat a CI-only check as met because ship's CI wait gates the merge: sdd would be grading something it never observed. |
| D3 | The `### Acceptance` table sits at the prompt's existing heading level, is outside the ≤400-word budget, and forces a first-line `Findings` when any row is unmet or unverified. A missing table or row records `unverified`, with no re-dispatch. | It is consistent with the sibling `### Coverage` and `### Issues` sections, and the parent's `## Acceptance` names the section. A word cap must not crowd out criteria. | Count the table inside the 400 words: a long criterion list would silently truncate findings. |
| D4 | Acceptance findings re-verdict through the existing reviewer-lite conformance re-review, with the same citation rule enforced by the controller. No dispatch is added. | Parent D3 (no new agent, marker count unchanged). Reviewer-lite eligibility covers "named prior findings". | An Opus re-grade dispatch: it adds an agent, and the citation check already removes the risk of a judgment shortcut. |
| D5 | The record is written and committed before Final verification. A failed repair round flips the affected `code` rows to `unmet` in a second commit. | #263: ship skips its rerun only for the identical verified tree. Parent D4 (the record must be committed). | Commit after verification: every issue with criteria would force ship to rerun the full verification. |
| D6 | The controller's record commit goes through `launch-commit` under a self-registered worker id, and through plain `git` without a lifecycle identity. | #222: every writer on a shared checkout is launch-fenced. | An unfenced controller commit: a superseded predecessor could still write to the successor's branch. |
| D7 | The record path is `<plans dir>/<plan stem>.acceptance.md`, outside `.tasks/`. | Parent D4 (beside the plan, no new binding). The plan's budgeted member set counts `.tasks/` members. | A file inside `.tasks/`: it would change the plan artifact's metrics after they were reported. |
| D8 | `acceptance_state` is required on every shape. `not_applicable` also means "nothing graded" (failed before grading, or a handoff with `review_state: unknown`). Residuals with `unmet` requires `conformance_verdict: findings`. | Parent D6 pairing, whose failed-with-null-SHAs row already uses `not_applicable` this way. Fail loud on a closed set. | Make the field optional for back-compatibility: a missing field would read as no gate at all (the issue's criterion 2 rejects it). |
| D9 | The closed set and pairing live once, in artifact-budget, and apply to the sdd report, the legacy handoff and the v2 handoff. The v2 wire validator only admits the key. | the-bar DRY (one home). Precedent: the post-model ship-summary legacy-slot rule. The v2 `review_state` is already string-only in the model. | Duplicate the pairing in the delivery model: two homes that must change together. |
| D10 | Keep the `conformance-reviewer` role and move its tier to opus/high. | Smallest change. Historical telemetry keeps the role spelling (agent costs). The role still differs from `reviewer` by its prohibitions. | Re-point the dispatch to `reviewer` and retire the role: old cost logs would turn role-ambiguous and the prohibition would be lost. |
| D11 | The pairing is extended in place in the legacy flat `scripts/artifact_budget.py`. It rejects every (`review_state`, `acceptance_state`) pair outside the table, so it also closes the v2 handoff's `review_state` to `clean`, `residuals` or `unknown`. | `docs/standards/agent-helpers.md`: a legacy script meets the package rules when its cluster moves, and this is not that move. Fail loud on a closed set. | Move artifact-budget into `agent_tools` now: that is a cluster move outside S1. Let an unknown v2 `review_state` pass the pairing: the pairing would then need a default row. |
| D12 | The marker inventory is the number of `<!-- agent-dispatch:` lines across both skill source trees. `test_dispatch_contracts.py` pins it as the literal 37, and it pins the exact conformance marker line. | Issue criterion 3 names `test_dispatch_contracts.py`, which holds no count today. Parent S3 measures "unchanged" with the same test. | Per-file marker-id sets: these do not measure an inventory. Deriving the count from `model-matrix.json`: that compares two artifacts, and both could grow together. |
| D13 | The controller reads the criteria once, with `<tracker-cli> issue view <n> --repo <slug> --json body`. It takes the checkbox lines under the body's `## Acceptance criteria` heading, up to the next heading. An `unsupported` tracker counts as no source (`not_applicable`). A `blocked` tracker, or a failed read, stops the final review as `failed` before dispatch, with conformance `not_run`. | D1 (the controller numbers the lines). The issue template's `## Acceptance criteria` section. A blocked capability stops. | Have from-issue pass the lines into sdd: that widens the Phase 6 contract. Fall back to `not_applicable` on a failed read: the gate would silently vanish. |
| D14 | ship-issue's full two-axis review reuses the conformance prompt without `[ACCEPTANCE_CRITERIA]`, so ship grades nothing in S1. `ship-issue/REVIEW.md` says so. | The spec's Out of scope (ship's close stage is unchanged). sdd is the only grader. | Grade at ship as well: two graders could disagree, and S2 owns ship's acceptance behavior. |
| D15 | `[ACCEPTANCE_CRITERIA]` ends with one line, `Declared verification: <each declared verification command, in order>` (or `none`), which the controller writes. That line is what a `code` check is graded against. The reviewer finds the record from the plan path (`<plan stem>.acceptance.md` beside `[PLAN_FILE]`). | D2 needs the declared verification, but the prompt names no binding beyond `bindings.workflow.review.code`. D7 fixes the record path. | Add `[DECLARED_VERIFICATION]` and `[ACCEPTANCE_RECORD]` placeholders: two more substitution sites for values the controller already writes into one block. |
| D16 | On `ship-handoff/v2`, artifact-budget rejects `acceptance_state: unmet` with a null `report_path`, so an unmet criterion always travels with durable detail; the accepted residual fixtures carry that path. | Phase-5 Codex plan review (PR272-03): the v2 model only type-checks `report_path`, while parent "unmet requires residuals, with detail present" and ship-handoff.md require the durable path for a residual report. | Enforce `residuals` → path for every v2 value: wider than S1 needs, and it changes v2 behavior beyond the acceptance field. |
| D17 | The controller's acceptance checks are first-pass checks. A scoped conformance re-review re-verdicts only the named acceptance findings and every other `ACn` keeps its first-pass verdict. Before the record is written, and again after a verification repair, an `evidence` `met` row whose measured surface a later commit touches becomes `unverified`; the controller's ≤400-word cap excludes the `### Acceptance` table. | Phase-5 Codex plan review (PR272-01, PR272-02, PR272-04): the re-review contract returns only ADDRESSED / NOT ADDRESSED for named findings, a correctness-only fix or a verification repair can change a measured surface unseen by conformance, and parent D10 requires stale evidence to grade `unverified`. | Demand a full table on every re-review (false Residuals from a compliant scoped reply), or a second conformance pass after every fix (an extra dispatch, against parent D3's cost constraint). |
