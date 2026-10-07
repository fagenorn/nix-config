# Task 5: Give the Phase-5 gates one home; cut standards-review.md, REVIEW-CONTRACT.md and decision-ledger.md

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/from-issue/standards-review.md`, `skills/from-issue/REVIEW-CONTRACT.md`, `skills/from-issue/decision-ledger.md`
- Modify: `skills/from-issue/SKILL.md` (`## Phase 5 — Standards review` only)
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 4's tree.
- Produces:
  - `standards-review.md`, the only home of the caller input gate and the accepted-edit remeasurement. Its sections are `## Caller input gate`, `## Dispositioning findings` and `## Accepted-edit remeasurement`.
  - `REVIEW-CONTRACT.md`, holding only reviewer-facing sections: an opening paragraph, `## Reviewer instructions`, `## Acceptance map check`, `## Common-miss checklist` and `## Output`.

**Invariants:**
- The `from-issue-plan-review` marker and its call line stay in `standards-review.md` byte for byte (per D3).
- The caller gate keeps its order, which `workflow-state` and `artifact-budget` enforce:
  1. `validate-report --boundary producer --input -` over the received bytes;
  2. then `state: complete`, an `implementation-plan` artifact and `within_budget`;
  3. then `artifact-budget check --kind implementation-plan --root <reported-root> --format json`, with the root and four metrics compared;
  4. then the route choice. Any failure stops before reviewer dispatch, on both the Codex and the native route.
- The route choice keeps its closed set and order: **Blocked** stops with `reason_code` and `repair_id`; available + `codex-collaboration` → `plan-review`; authored unsupported or the completed non-capacity runtime/output failure → the native reviewer. The contract travels by absolute path.
- The remeasurement keeps:
  - its order: the last plan or ledger write, then `artifact-budget check --kind implementation-plan`, then `--kind design-spec` when the spec or its ledger changed, then the owning producer's remediation once;
  - `decompose_required` with no SDD dispatch when over budget;
  - only `within_budget` advances.
- `REVIEW-CONTRACT.md`:
  - keeps the D14 clause, every reviewer instruction, the six Blocking items and the Should-fix rule of `## Acceptance map check`, the common-miss categories and the three output buckets;
  - loses `## Caller pre-dispatch boundary` and `## Accepted-edit remeasurement`, and the caller-facing half of its opening paragraph;
  - names no from-issue file.
- `decision-ledger.md` keeps its fenced table block and the three rules byte for byte. Its last sentence names no file: "A subagent prompt that needs the format pastes this table block and the three rules verbatim."
- Byte targets: `standards-review.md` 3,200, `REVIEW-CONTRACT.md` 6,800, `decision-ledger.md` 950.

- [ ] **Step 1: Re-point the remeasurement test (it fails until Step 3)**

Replace `WorkflowSkillContractsTest.test_phase_five_remeasures_every_artifact_it_mutates` with:

```python
    def test_phase_five_remeasures_every_artifact_it_mutates(self):
        remeasure = normalized(self.standards_review.split("## Accepted-edit remeasurement", 1)[1])
        self.assert_ordered(remeasure, "artifact-budget check --kind implementation-plan",
                            "artifact-budget check --kind design-spec", "decompose_required")
        for heading in ("## Accepted-edit remeasurement", "## Caller pre-dispatch boundary"):
            with self.subTest(heading=heading):
                self.assertNotIn(heading, self.phase_5_review_contract)
```

Add `"## Acceptance map check"`, `"## Common-miss checklist"` and `"## Output"` as ordered heading anchors to `AcceptanceMapContractsTest.test_review_contract_blocks_a_missing_or_duplicated_row`. Keep its closed kind set (`code`, `evidence`, `human`), and delete its English-phrase assertions (per D11).

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k remeasures_every_artifact` (timeout 300 s)
Expected: FAIL. `REVIEW-CONTRACT.md` still holds `## Accepted-edit remeasurement`. The ordered argv check may also fail, because the current text splits `--kind` across a line break before normalisation: "`artifact-budget check --kind\nimplementation-plan`".

- [ ] **Step 3: Cut**

1. `standards-review.md`:
   - Delete the opening "A plan reviewed only by its author risks blind spots, and you are the author." rationale. Keep "Unless Phase 0 marked the issue `mechanical-only`:".
   - Write the caller gate once, in the order above. Cut "neither may trust the producer's validation" and the repeated "before any state access or reviewer dispatch".
   - Cut "**The contract travels by path, never inlined** — pasting reviewer text here costs…" to "Pass the contract by path; never inline it."
   - Make the remeasurement one paragraph with the `--kind implementation-plan` and `--kind design-spec` argv on single lines, and drop the "(D5, D14)" trail.
2. `REVIEW-CONTRACT.md`:
   - Delete `## Caller pre-dispatch boundary` and `## Accepted-edit remeasurement`.
   - Reduce the opening paragraph to: what the reviewer receives (the plan root path and its four checker metrics, the spec path, the issue number, `bindings.tracker`, `bindings.paths` and the review capability), the D14 clause, and "never inline this file".
   - Cut rationale tails in `## Reviewer instructions` and `## Common-miss checklist`, such as "— they have repeatedly slipped past plan review…" and "Duplicate helpers fixed only at PR review are a recurring waste". Keep each category's rule and its required finding shape.
3. `decision-ledger.md`: replace the last sentence (Invariants).
4. `SKILL.md` § Phase 5: replace the "Both routes consume the planning producer's received stdout bytes…" paragraph with one sentence: "`standards-review.md`'s caller input gate runs first, on every route."

- [ ] **Step 4: Delete the prose pins on the cut text**

Apply D11 to these `WorkflowSkillContractsTest` methods:
- `test_both_plan_review_routes_revalidate_received_reports_in_the_caller`. Keep only `validate-report --boundary producer --input -` in `standards_review`.
- `test_standards_review_stops_a_blocked_plan_review_capability`. Keep the ordered `capabilities.review.plan`, `reason_code`, `repair_id`.
- `test_fixture_producer_states_supplement_behavioral_cli_cases`, for its `phase_5_review_contract` parts.

Then grep the test file for `phase_5_review_contract`, `self.standards_review`, `decision-ledger.md` and `REVIEW_CONTRACT`, and apply D11 to every other hit.

- [ ] **Step 5: Models**

- `skill-lint-debt.json`: delete `"L4b home/common/agent-skills/skills/from-issue/decision-ledger.md names AUTO.md"` (per D12).
- Run `just agent-instruction-load tighten` (timeout 300 s). `plan-reviewer` and `planning-owner` lower with `REVIEW-CONTRACT.md`.

- [ ] **Step 6: Verify**

Run the focused suite. Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
python3 - <<'EOF'
from pathlib import Path
F = Path("home/common/agent-skills/skills/from-issue")
for name, cap in {"standards-review.md": 3200, "REVIEW-CONTRACT.md": 6800, "decision-ledger.md": 950}.items():
    size = len((F / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
contract = (F / "REVIEW-CONTRACT.md").read_text(encoding="utf-8")
assert "## Caller pre-dispatch boundary" not in contract
assert "never resolve or infer policy" in contract, "D14 clause missing"
assert "AUTO.md" not in (F / "decision-ledger.md").read_text(encoding="utf-8")
EOF
if grep -q 'decision-ledger.md names' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 4's head it fails at `## Caller pre-dispatch boundary`.

- [ ] **Step 7: Commit**

Commit as `refactor(from-issue): give the Phase-5 gates one home and cut the review contract to its reviewer (#295)`.
