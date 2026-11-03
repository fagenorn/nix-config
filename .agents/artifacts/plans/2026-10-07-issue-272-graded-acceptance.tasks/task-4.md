# Task 4: The conformance prompt grades every criterion

Lane: full (it changes the instructions that drive the final review).
Decisions: per D1, D2, D3, D14 and D15 of the spec's ledger, and parent D2,
D5, D8 and D10. Read the spec's "Grading rules (conformance prompt)" and
"Conformance output shape" sections first.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 3): the test class `AcceptanceGradingContractsTest`, with
  `read(path)` (normalized text) and `assert_ordered(text, *anchors)`. Also
  the module constants `SDD_DIR` and `SHIP_ISSUE_REVIEW`.
- Produces (Task 5's controller text relies on these exact names): the
  placeholder `[ACCEPTANCE_CRITERIA]`. It holds one line
  `AC<n>: <the issue's criterion line verbatim, without its checkbox>` per
  criterion, then one line `Declared verification: <commands>` or
  `Declared verification: none`. Also produced: the prompt section heading
  `## Acceptance criteria`, the output section `### Acceptance`, its header
  row `| AC | Kind | Verdict | Citation |`, and the evidence citation form
  `observed <value> at <sha7> vs threshold <literal>`.

**Invariants:**
- The prompt keeps exactly one unlabeled fence, and every new prompt line is
  inside it, indented four spaces like its neighbours. The
  `test_dispatch_contracts.py` fence carrier and enrolment guard stay green.
- The marker, the `Agent(...)` call and the subagent line that Task 3 set are
  unchanged.
- The output section order is `### Coverage`, `### Acceptance`, `### Issues`,
  then `### Ledger Triage`.
- The ≤400-word budget excludes the `### Acceptance` table (per D3).
- The prompt names no `bindings.` key other than
  `bindings.workflow.review.code` (the retained-support contract).
- No instruction-load profile exceeds its ceiling.

- [ ] **Step 1: Write the failing test**

Add to `AcceptanceGradingContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

```python
    def test_the_conformance_prompt_grades_every_criterion(self):
        prompt = self.read(SDD_DIR / "conformance-reviewer-prompt.md")
        fence = prompt[prompt.index("```"):prompt.rindex("```")]
        for fragment in (
            "## Acceptance criteria [ACCEPTANCE_CRITERIA]",
            "`AC1`…`ACn` in order, as exactly one of `met`, `unmet`, `unverified` or `human_pending`",
            "part of the Declared verification line",
            "`<plan stem>.acceptance.md`",
            "An evidence `met` must cite the observed value and the threshold;",
            'rounding or "close enough" never counts',
            "A missing row is `unverified`, a stale row is `unverified`",
            "`human`: always `human_pending`",
            "An acceptance finding is never parked with a ruling.",
            "≤400 words total, not counting the `### Acceptance` table.",
            "It is `Findings` whenever any Acceptance row is `unmet` or `unverified`.",
            "| AC | Kind | Verdict | Citation |",
            "`observed <value> at <sha7> vs threshold <literal>`",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, fence)
        self.assert_ordered(fence, "### Coverage", "### Acceptance (omit this section",
                            "### Issues", "### Ledger Triage")
        placeholders = prompt[prompt.index("**Placeholders:**"):]
        self.assert_ordered(placeholders, "`[ACCEPTANCE_CRITERIA]`",
                            "`AC<n>: <the issue's criterion line verbatim, without its checkbox>`",
                            "`Declared verification: <each declared verification command, in order>`",
                            "ship-issue's full review",
                            "`### Acceptance` output section")
        self.assertIn("omit the ledger-triage placeholder and `[ACCEPTANCE_CRITERIA]`",
                      self.read(SHIP_ISSUE_REVIEW))
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_the_conformance_prompt_grades_every_criterion 2>&1 | tail -5`
Expected: FAIL on the first fragment, `## Acceptance criteria [ACCEPTANCE_CRITERIA]`.

- [ ] **Step 3: Edit the prompt and REVIEW.md**

All text below goes inside the fence, indented four spaces. Insert it
verbatim.

1. In `## Requirements`, after the `Plan: [PLAN_FILE]` line, add a blank
   line and then:

```text
    ## Acceptance criteria

    [ACCEPTANCE_CRITERIA]
```

2. In `## What to Check`, insert this bullet between **Message-format
   parity** and **Ledger triage**:

```text
    - **Acceptance criteria:** grade every criterion in the Acceptance
      criteria section, `AC1`…`ACn` in order, as exactly one of `met`,
      `unmet`, `unverified` or `human_pending`. Take each criterion's kind
      (`code`, `evidence` or `human`) from the plan's `## Acceptance map`
      when the plan has one, else from the criterion's inline tag. Classify
      an untagged line yourself; a line you cannot classify is `unverified`.
      - `code`: `met` when its named check exists at HEAD and is part of the
        Declared verification line, which the final verification runs. A
        named check outside that line is `met` only when you ran it at HEAD
        and cite the command and its pass; otherwise it is `unverified`. A
        named check that is absent, or that you ran and saw fail, is `unmet`.
      - `evidence`: `met` only when its row in the acceptance record
        (`<plan stem>.acceptance.md`, beside the plan) shows a value inside
        the criterion's literal threshold, and the commits after the
        measured commit leave the measured surface alone. An evidence `met`
        must cite the observed value and the threshold; rounding or "close
        enough" never counts. A missing row is `unverified`, a stale row is
        `unverified`, and a value outside the threshold is `unmet`.
      - `human`: always `human_pending`. Never attest a human criterion.
      Every `unmet` or `unverified` row is an acceptance finding: list it
      under Important, labelled `conformance` and its `ACn`. An acceptance
      finding is never parked with a ruling.
```

3. In `## Output Format`, replace the first four lines of the section,
   from `≤400 words total. Your FIRST line is the axis verdict:` through
   `file:line, or a check you ran; no preamble, no closing summary.`, with:

```text
    ≤400 words total, not counting the `### Acceptance` table. Your FIRST
    line is the axis verdict:
    `**Conformance:** Clean | Findings — 1–2 sentence assessment.`
    It is `Findings` whenever any Acceptance row is `unmet` or `unverified`.
    Then the sections below — every line a verdict, a finding with
    file:line, or a check you ran; no preamble, no closing summary.
```

4. Between the `### Coverage` section (its heading and its one line) and
   `### Issues`, insert:

```text
    ### Acceptance (omit this section when the dispatch supplied no acceptance criteria)
    | AC | Kind | Verdict | Citation |
    One row per `ACn`, in order. `Verdict` is exactly one of `met`, `unmet`,
    `unverified` or `human_pending`. `Citation` for a `code` row is the
    check name and either `in final verification` or the command you ran
    with its result; for an `evidence` row it is
    `observed <value> at <sha7> vs threshold <literal>`; for an `unmet` or
    `unverified` row it names what is missing or failing.
```

5. In the `**Placeholders:**` paragraph after the fence, insert this entry
   before `[DEFERRED_AND_PARKED_LINES]`, as plain prose (not in a fence):

   `[ACCEPTANCE_CRITERIA]` (written by sdd's controller per final-review.md:
   one line `AC<n>: <the issue's criterion line verbatim, without its checkbox>`
   per criterion, in issue order, then one line
   `Declared verification: <each declared verification command, in order>`,
   or `Declared verification: none`. When the dispatch has no criterion
   source, which means no issue, an intent-statement `[ISSUE_REF]`, an issue
   without acceptance-criteria lines, or ship-issue's full review, omit the
   `## Acceptance criteria` heading, this placeholder AND the
   `### Acceptance` output section),

6. In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, section
   `## Full two-axis review — templates`, replace this sentence:

```text
omit the ledger-triage placeholder and let each reviewer fetch the range per its template's fallback.
```

   with this one, keeping the surrounding paragraph's line wrapping:

```text
omit the ledger-triage placeholder and `[ACCEPTANCE_CRITERIA]` (acceptance criteria are graded only in sdd's final review), and let each reviewer fetch the range per its template's fallback.
```

7. Instruction-load ceilings. Measure with:

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
   `ceiling_bytes.<host>` in `home/common/agent-skills/instruction-load.json`
   to the printed measured value, with no slack. Append this sentence to that
   profile's `note`:
   `Ceiling raised for #272: the conformance prompt grades every acceptance criterion and ship's full review omits them (#155 D10).`
   Re-run the script: it must print nothing.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK`. That includes the fence carrier and enrolment guard tests, and
`test_the_live_tree_breaches_no_ceiling`.

Run: `if [ "$(grep -c '^```' home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md)" != 2 ]; then exit 1; fi`
Expected: exit 0, because the prompt still has exactly one fence.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(sdd): grade every acceptance criterion on the conformance axis (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`.
