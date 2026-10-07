# Task 5: Controller rules, the acceptance record and sdd's `acceptance_state`

Lane: full (it changes the controller's review, commit and report behavior).
Decisions: per D1, D3, D4, D5, D6, D7, D8, D13 and D15 of the spec's ledger,
and parent D4 and D5. Read the spec's "Controller rules (`final-review.md`)"
and "Acceptance record" sections first.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 4): the prompt placeholder `[ACCEPTANCE_CRITERIA]`. It
  holds the lines `AC<n>: <criterion>` and then
  `Declared verification: <commands>` or `none`. Also from Task 4: the
  prompt's `### Acceptance` table `| AC | Kind | Verdict | Citation |` and
  the citation form `observed <value> at <sha7> vs threshold <literal>`.
- Consumes (Task 1): the `sdd` boundary requires `acceptance_state` and
  pairs it with the state.
- Consumes (Task 3): `AcceptanceGradingContractsTest`, with `read(path)` and
  `assert_ordered(text, *anchors)`.
- Produces: the record path `<plans dir>/<plan stem>.acceptance.md` and its
  header row
  `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`.
  Also the sdd Finish key `acceptance_state`.

**Invariants:**
- `final-review.md` gains no unlabeled fence. The record schema uses a
  ```` ```markdown ```` fence (the dispatch-contract enrolment guard).
- No `agent-dispatch` marker is added (per D4).
- These existing anchors stay in their order: `There is no second fix wave`
  → `## Final verification` → `after the fix wave and its scoped
  re-reviews` → `before you choose the terminal state`. So do the
  `Repair once` anchors through `` `correctness_verdict: findings` ``.
- sdd's `## Finish` still contains neither `verified-tree` nor
  `Final verification: passed`.
- Every shell example is a single plain command, so
  `test_shell_example_contracts.py` stays green.
- No instruction-load profile exceeds its ceiling.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. In `WorkflowSkillContractsTest.test_sdd_report_is_exact_and_mechanically_validated`,
   add `"acceptance_state"` to the field tuple, after `"head_sha"`.
2. Add these tests to `AcceptanceGradingContractsTest`:

```python
    def test_final_review_never_parks_acceptance_findings(self):
        text = self.read(SDD_DIR / "final-review.md")
        self.assert_ordered(
            text, "**Acceptance criteria.**",
            "`<tracker-cli> issue view <num> --repo <repo_slug> --json body`",
            "`## Acceptance criteria` heading", "`AC1`…`ACn`",
            "`Declared verification:`", "`acceptance_state: not_applicable`",
            "stops the final review before either axis is dispatched",
            "Point the conformance dispatch")
        self.assert_ordered(
            text, "**Acceptance verdicts.**",
            "An `evidence` `met` without the observed value or the threshold is "
            "recorded as `unverified`.",
            "A missing table, or a missing row, records every missing `ACn` as "
            "`unverified`.",
            "Every `unmet` or `unverified` row is an acceptance finding.",
            "An acceptance finding is never parked with a ruling",
            "forces the Residuals terminal state",
            "id=sdd-final-review-fixer")
        self.assert_ordered(
            text, "id=sdd-final-conformance-rereview",
            "`observed <value> at <sha7> vs threshold <literal>`; without it, "
            "record `unverified`.",
            "There is no second fix wave", "## Acceptance record",
            "`<plans dir>/<plan stem>.acceptance.md`",
            "| AC | Criterion | Kind | Check or command | Observed | Commit | "
            "Conditions | Verdict |",
            "Commit the acceptance record, then run the **Final verification** step.",
            "`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
            "--worker-id <worker_id> -- <git commit arguments>`",
            "--event returned", "## Final verification",
            "after the acceptance record's commit",
            "`correctness_verdict: findings`",
            "becomes `unmet` in a second record commit")
        raw = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
        self.assertIn("```markdown\n# Acceptance record — issue #<n>", raw)

    def test_sdd_finish_reports_acceptance_state(self):
        finish = self.read(SDD).split("## Finish", 1)[1]
        self.assertIn("`head_sha`, `acceptance_state`, `detail_state`, `report_path`, "
                      "and `notes`", finish)
        self.assert_ordered(
            finish, "`acceptance_state` derives from the final verdicts",
            "`not_applicable` when", "`unmet` when any verdict is `unmet` or `unverified`",
            "`human_pending` when any verdict is `human_pending`", "otherwise `met`",
            "- **Clean** —", "(an acceptance finding never is)")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5`
Expected: FAIL in the two new tests and in
`test_sdd_report_is_exact_and_mechanically_validated`, because
`acceptance_state` is not yet in sdd's Finish.

- [ ] **Step 3: Edit `final-review.md`**

Insert every block below verbatim. Wrap prose at about 80 columns, like the
file. These are the controller's own rules. Each sentence describes what the
controller does, and none restates the prompt's grading rules.

A. Insert this paragraph directly before the paragraph that begins
`Point the conformance dispatch at the ledger's deferred-minor`:

```text
**Acceptance criteria.** Before dispatching the conformance axis, build its `[ACCEPTANCE_CRITERIA]` block (see [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md)). When the caller supplied an issue and the retained `capabilities.tracker` is `available`, read the issue once with `<tracker-cli> issue view <num> --repo <repo_slug> --json body` (from `bindings.tracker`, prefixed as `bindings.tracker.credential_env.unset_before_invocation` requires). Copy the checkbox lines under its `## Acceptance criteria` heading, up to the next heading, verbatim and in issue order, and number them `AC1`…`ACn`. Then add the line `Declared verification:` followed by the command of each retained `bindings.workflow.verification` id, in order, or `none` when the verification capability is authored unsupported. No issue, an intent statement, an `unsupported` tracker, or an issue without such lines is no criterion source: omit the block, write no record, and report `acceptance_state: not_applicable`. A `blocked` tracker capability, or a read that fails, stops the final review before either axis is dispatched, as a generator failure does: report `failed` with `conformance_verdict: not_run` and `acceptance_state: not_applicable`.
```

B. Insert this block directly before the paragraph that begins
`Findings → verify each against the live worktree first`:

```text
**Acceptance verdicts.** When the conformance dispatch carried `[ACCEPTANCE_CRITERIA]`, check its `### Acceptance` table on the first pass and on every conformance re-review, before recording a verdict:

- An `evidence` `met` without the observed value or the threshold is recorded as `unverified`.
- A `code` `met` whose check is not on the Declared verification line, and that has no cited run, is recorded as `unverified`.
- A missing table, or a missing row, records every missing `ACn` as `unverified`. There is no re-dispatch.

Every `unmet` or `unverified` row is an acceptance finding. It joins the fixer's list below as an Important finding labelled `conformance` and its `ACn`. For an `evidence` criterion, the fix is to re-measure and write that row's evidence columns in the acceptance record. An acceptance finding is never parked with a ruling, and the residual adjudication below never turns one into a parked line. One that survives the fix wave is load-bearing: it sets `conformance_verdict: findings` and forces the Residuals terminal state.
```

C. Insert this paragraph directly before the sentence that begins
`Adjudicate residuals like the task-loop breaker.` Start that sentence on
its own new line after the paragraph.

```text
The conformance re-review re-verdicts acceptance findings like any other named finding. Its ADDRESSED on an `evidence` criterion must carry the citation that a first-pass `met` needs, `observed <value> at <sha7> vs threshold <literal>`; without it, record `unverified`.
```

D. Insert this section directly before `## Final verification`:

````text
## Acceptance record

Write the record after the scoped re-reviews, or right after the first pass when neither axis had findings, and before the **Final verification** step. That step's verified tree then already holds the record, so ship's `verified-tree check` still matches (#263). Skip this section when the conformance dispatch carried no `[ACCEPTANCE_CRITERIA]`.

The record is one committed file per plan, beside the plan: `<plans dir>/<plan stem>.acceptance.md`. It sits outside `<plan stem>.tasks/`, so the plan's metrics do not change. Its schema:

```markdown
# Acceptance record — issue #<n>

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
```

- One row per `ACn`, in order. `Criterion` is the issue line verbatim, without its checkbox.
- Whoever measured writes the evidence columns (`Observed`, `Commit`, `Conditions`): an implementer whose task brief names the measurement, or the final-review fixer. For a `code` row, `Observed` is `in final verification` or the cited run. For a `human` row the evidence columns hold `—`.
- Only you, the controller, write `Verdict`, using the four grading tokens `met`, `unmet`, `unverified` and `human_pending`. No code parses the record: the gate is the report's `acceptance_state`.

Write each row's final verdict into `Verdict`. When the record has no rows yet, write the whole record. Commit the acceptance record, then run the **Final verification** step. Under a lifecycle identity, register yourself for that commit as SKILL.md's `### Lifecycle workers` describes: run `workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`, commit with `launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`, then run `workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --worker-id <worker_id> --event returned`. A `launch fence refused: <reason>` takes that section's refusal route. Without a lifecycle identity, commit with plain `git`.
````

E. In `## Final verification`, in its first paragraph, replace
`when neither axis had findings, and before you choose the terminal state.`
with
`when neither axis had findings, after the acceptance record's commit (when there is one), and before you choose the terminal state.`

F. At the end of step 4 (**Repair once.**), after
`` `correctness_verdict: findings`. ``, append:

```text
When there is an acceptance record, every `code` row whose check failed becomes `unmet` in a second record commit, made the same way, and each one is an acceptance finding as above.
```

- [ ] **Step 4: Edit sdd `SKILL.md`'s `## Finish`**

1. In the sentence `Build one exact SDD JSON object with only …`, insert
   `` `acceptance_state`, `` after `` `head_sha`, ``. The list then reads
   `` … `base_sha`, `head_sha`, `acceptance_state`, `detail_state`, `report_path`, and `notes` ``.
2. Directly after the sentence that ends `… when that step's repair round did
   not pass.`, insert:

```text
`acceptance_state` derives from the final verdicts final-review.md recorded: `not_applicable` when there was no criterion source or the run failed before the conformance axis graded; otherwise `unmet` when any verdict is `unmet` or `unverified`; otherwise `human_pending` when any verdict is `human_pending`; otherwise `met`. `artifact-budget validate-report --boundary sdd` rejects `unmet` under `clean`.
```

3. In the **Clean** terminal state, replace
   `or every remaining finding parked-with-ruling,` with
   `or every remaining finding parked-with-ruling (an acceptance finding never is),`.

- [ ] **Step 5: Raise the instruction-load ceilings**

Measure with:

```bash
PYTHONPATH="$PWD/python" python3 - <<'PY'
from pathlib import Path
from agent_tools import instruction_load as il
root = Path(".").resolve()
model = il.load_model((root / il.MODEL_PATH).read_bytes())
measured = il.measure(model, il.tree_reader(root))
for profile in model["profiles"]:
    for host in profile["hosts"]:
        used = measured["profiles"][profile["id"]][host]["hot"]["bytes"]
        if used > profile["ceiling_bytes"][host]:
            print(profile["id"], host, profile["ceiling_bytes"][host], "->", used)
PY
```

For every `(profile, host)` line it prints, set that profile's
`ceiling_bytes.<host>` in `home/common/agent-skills/instruction-load.json` to
the printed measured value, with no slack. Append this sentence to that
profile's `note`:
`Ceiling raised for #272: final-review.md checks acceptance verdicts and commits the acceptance record, and sdd's Finish reports acceptance_state (#155 D10).`
Re-run the script: it must print nothing.

- [ ] **Step 6: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK`. That includes `CheckpointVerificationContractsTest`,
`LaunchFencedWorkerContractsTest` and the enrolment guard.

Run: `if ! grep -q 'An acceptance finding is never parked with a ruling' home/common/agent-skills/skills/sdd/final-review.md; then exit 1; fi`
Expected: exit 0. At the base commit this exits 1.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(sdd): never park acceptance findings and commit the acceptance record (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`.
