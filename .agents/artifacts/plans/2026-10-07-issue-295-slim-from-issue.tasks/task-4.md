# Task 4: Move Phase-0 inspection and Phase-7 report handling; cut investigate.md and ship-handoff.md

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/from-issue/SKILL.md` (`## Phase 0 — Investigate`, `## Phase 7 — Ship`, and the index bullets for the two files)
- Modify: `skills/from-issue/investigate.md`, `skills/from-issue/ship-handoff.md`
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 3's tree.
- Produces:
  - `investigate.md` with `## PR pre-flight queries`, a new `## Worktree pre-flight` and `## Investigate`.
  - `ship-handoff.md` with `## Ship-owner subagent prompt`, a new `## Ship report handling`, a new `## Dispatch-gap fallback`, `## Inline fallback (no ship-issue skill)` and `## Remainder owner prompt`, in that order. If the file is over 100 reflowed lines, a `## Contents` list comes first.
  - Test constant `SHIP_HANDOFF_DOC = FROM_ISSUE_DIR / "ship-handoff.md"`.

**Invariants:**
- `SKILL.md` § Phase 7 keeps the `from-issue-ship-owner` marker and its call line byte for byte (per D3). It also keeps one sentence each for: the prompt and its inline fallback (named by file), the remainder launch at the same site, and "from-issue owns the terminal durable write; handle the ship report as `ship-handoff.md` § Ship report handling says".
- `SKILL.md` § Phase 0 keeps:
  - the `investigate.md` pointers;
  - the stop rules (bundled issues → `to-issues`, question or duplicate → stop), and the rule that every Phase-0 early stop uses the terminal return procedure;
  - the mandatory open-questions rule;
  - the mechanical-only shortcut;
  - the CHECKPOINT.
- The four-signal inspection and the "provably disposable" deletion rule move intact to `investigate.md` § Worktree pre-flight, with their argv byte for byte: `git worktree list`, `git log origin/<integration-branch>..<branch> --oneline`, and `git worktree remove` + `git branch -D`. Their branching stays: none, one, one with uncommitted work, several. The Phase-0 race rationale is cut.
- `## Ship report handling` keeps the closed order of cases:
  1. the re-entry-only line, which is relayed;
  2. `capability_gap: agent_dispatch`, compared byte for byte and never decoded, which leads to the dispatch-gap fallback;
  3. `delivery_stalled`, which is relayed;
  4. `validate-report --boundary ship-summary` and then `report_path` handling (including `unpublished`);
  5. the `check-launch` fence (argv byte for byte);
  6. `workflow-state finish --summary-file -`, through `SKILL.md`'s terminal return procedure.
- `## Dispatch-gap fallback` keeps its closed behaviour. With lifecycle identity it runs the fence first, and ledger-free it skips the fence. It runs `ship-issue` inline through the Skill tool with the same validated bytes. A second `capability_gap` line suspends with `agent_dispatch` under lifecycle identity, or reports and stops when ledger-free. A `delivery_remainder` launch never takes this fallback.
- `ship-handoff.md` keeps:
  - exactly one unlabeled fence, the ship-owner prompt, holding the three leaf-agent clauses once;
  - the remainder prompt's ```` ```text ```` fence and its placeholder line `<the three leaf-agent clauses of the ship-owner prompt above, verbatim>`;
  - the `from-issue-inline-ship-review` marker and its call line;
  - the `ship-handoff/v2` and legacy JSON lines, the `ship-summary/v2` and legacy key lists, and every `build-delivery` argv, all byte for byte;
  - the `Lifecycle worker:` line and its two sentences in both prompts.
- Neither file names a sibling. "the terminal return procedure" and "`SKILL.md`" are allowed. "rollover" and "delegated owner" name routes, not files.
- Byte targets: `investigate.md` 3,800, `ship-handoff.md` 11,000.

- [ ] **Step 1: Re-point the machine-read test (it fails until Step 3)**

Add `SHIP_HANDOFF_DOC = FROM_ISSUE_DIR / "ship-handoff.md"` after `FROM_ISSUE_DIR`. Then replace `WorkflowSkillContractsTest.test_from_issue_revalidates_its_launch_before_the_terminal_finish` with:

```python
    def test_from_issue_revalidates_its_launch_before_the_terminal_finish(self):
        handling = normalized(self.section(
            SHIP_HANDOFF_DOC.read_text(encoding="utf-8"),
            "## Ship report handling", "## Dispatch-gap fallback"))
        self.assert_ordered(
            handling,
            "validate-report --boundary ship-summary --input -",
            "~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <issue:attempt:launch>",
            "/from-issue <num> --auto",
            "workflow-state finish --summary-file -",
        )
        fallback = normalized(self.section(
            SHIP_HANDOFF_DOC.read_text(encoding="utf-8"),
            "## Dispatch-gap fallback", "## Inline fallback (no ship-issue skill)"))
        self.assert_ordered(fallback, "check-launch", "`ship-issue`",
                            f"`{CAPABILITY_GAP_LINE}`", "`agent_dispatch`")
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k revalidates_its_launch` (timeout 300 s)
Expected: ERROR, `ValueError: substring not found` for `## Ship report handling`.

- [ ] **Step 3: Move and cut**

1. Move `SKILL.md` § Phase 0's worktree bullets ("Then run `git worktree list` …" through "several → stop and ask…") into `investigate.md` § Worktree pre-flight. In `investigate.md`, replace "The stop rules and worktree-safety inspection live in `SKILL.md`; this file carries the working detail." with "The stop rules live in `SKILL.md` § Phase 0." Cut the Phase-0 race sentence and the C4 rationale in the size-gate paragraph. Keep its rule: a Phase-0 estimate covers the product change alone, and `diff-scope` is the accounting authority once a range exists, with one `--artifact-path` per file this run wrote.
2. Move `SKILL.md` § Phase 7 from "After receiving the ship report" through the end of `**Dispatch-gap fallback.**` into the two new `ship-handoff.md` sections. Keep `SKILL.md`'s Phase-7 lines (Invariants). Cut while moving:
   - the restated "never inline" clauses (one remains);
   - "prefix its phases `ship-Phase-N`…";
   - the shared-launch-identity rationale behind the fence, keeping its rule.
3. Cut `ship-handoff.md` outside the two fences by the spec's content-class table:
   - the field-derivation paragraphs become one sentence each that names the builder command;
   - "The handoff records historical custody…" and "A v2 handoff carries the full contract…" rationale are cut;
   - the `action_id` paragraph shrinks to its rule (verbatim `custody.action_id`, never recomputed);
   - the closing sentence after the remainder fence, "The placeholder line stands for…", becomes one clause.

   Inside the ship-owner prompt fence, cut only sentences the received prompt restates, such as the second "never inline" sentence. Leave the leaf-agent paragraph and every task-list step.
4. Add a `## Contents` list when `ship-handoff.md` is over 100 reflowed lines.

- [ ] **Step 4: Delete the prose pins on the moved and cut text**

Apply D11 and D13 to these methods:
- `WorkflowSkillContractsTest`: `test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt` (keep its key-set and argv anchors), `test_ship_issue_writer_rule_delivery_loop_and_remainder_mode` (from-issue parts only), `test_ship_handoff_returns_the_gap_line_before_either_loop_exit`, `test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap`, `test_handoff_head_sha_is_the_sdd_report_head_sha`, `test_durable_review_detail_precedes_every_removable_cleanup`, `test_preflight_worktree_deletion_requires_proof_of_disposability`, `test_phase0_size_note_delegates_counting_to_diff_scope`.
- `LaunchFencedWorkerContractsTest.test_the_ship_prompt_carries_the_worker_line_outside_the_handoff` and `test_the_remainder_prompt_releases_itself_before_its_finish`. Keep the `Lifecycle worker:` line and the `release-worker` argv order.
- `AcceptanceGradingContractsTest.test_both_handoff_templates_carry_acceptance_state`. Keep the key presence in both JSON lines.
- `HeldReportContractsTest.test_the_handoff_and_its_inline_fallback_close_or_hold`.
- `LaunchScopeWiringContractsTest.test_the_worker_sentence_follows_every_composed_worker_line`, for its two `handoff` orderings. Keep the line and sentence constants, and drop English anchors such as "never inside the handoff".

Leave the `ship-issue/HUMAN-GATE.md` pins at L3509/L3517 unchanged (per D9).

- [ ] **Step 5: Models**

- `skill-lint-debt.json`: delete `"L3 home/common/agent-skills/skills/from-issue/ship-handoff.md"` (per D12).
- Run `just agent-instruction-load tighten` (timeout 300 s). Then run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. If `from-issue-controller`'s conditional ceiling is breached because `ship-handoff.md` absorbed Phase-7 text, set it to the measure and add a `raise:` body line (per D12).

- [ ] **Step 6: Verify**

Run the focused suite. Expected: OK. `test_dispatch_contracts` stays green unchanged, which shows the fence carrier and the enrolment guard hold.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
python3 - <<'EOF'
from pathlib import Path
F = Path("home/common/agent-skills/skills/from-issue")
for name, cap in {"investigate.md": 3800, "ship-handoff.md": 11000}.items():
    size = len((F / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
skill = (F / "SKILL.md").read_text(encoding="utf-8")
phase0 = skill[skill.index("## Phase 0"):skill.index("## Phase 1")]
phase7 = skill[skill.index("## Phase 7"):]
assert "provably disposable" not in phase0, "inspection still in SKILL.md"
assert "**Dispatch-gap fallback.**" not in phase7, "fallback still in SKILL.md"
assert "## Worktree pre-flight" in (F / "investigate.md").read_text(encoding="utf-8")
handoff = (F / "ship-handoff.md").read_text(encoding="utf-8")
heads = [handoff.index(h) for h in ("## Ship-owner subagent prompt", "## Ship report handling",
         "## Dispatch-gap fallback", "## Inline fallback (no ship-issue skill)", "## Remainder owner prompt")]
assert heads == sorted(heads), "ship-handoff.md section order"
EOF
if grep -q 'from-issue/ship-handoff.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 3's head it fails at `provably disposable`.

- [ ] **Step 7: Commit**

Commit as `refactor(from-issue): move Phase-0 inspection and Phase-7 report handling into their phase files (#295)`.
