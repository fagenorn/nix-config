# Task 3: `from-issue` Phase 0 triage step, docs and final gate

Spec section **`from-issue` Phase 0** and the `CLAUDE.md` obligation; rows D3, D6, D7, D9.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (Phase 0, Phase 2)
- Modify: `home/common/agent-skills/skills/from-issue/investigate.md` (note fields)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (prompt-content bullet)
- Modify: `CLAUDE.md` ("Agent helper package" paragraph)
- Modify: `home/common/agent-skills/instruction-load.json` (only the ceilings this growth breaches)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 2): the command `lane-triage evaluate --repo-root <root> --input -`; its success output `{"hits": [...], "lane": "light"|"full", "mode": ...}`; its refusal codes `invalid_input`, `resolver_refused`, `light_lane_unsupported` (exit 2, one stderr line, empty stdout); signal names `contract_change`, `concurrency_or_persistence`, `open_design_questions`, `criteria_shape`. (Task 1): `agent_tools.resolve_project.resolve`.
- Produces: the skill text below, which the contract tests pin.

**Invariants:**
- The call is named only as the inline span `lane-triage evaluate --repo-root <project.root> --input -`; no shell fence and no heredoc example is added, and `COMMAND_VOCABULARY` and the Claude allowlist are untouched (D9).
- `investigate.md` gains the **Lane triage** field and no `bindings.` reference; its binding declaration stays `bindings.tracker` and `bindings.vcs` (D6).
- The skill text says every attempt runs full, whatever the verdict (D7).
- Each `instruction-load.json` ceiling this task's growth breaches is set to the measured hot bytes, and no other ceiling changes (#276 D9 precedent).
- `.agents/project.json` is not edited (D3).

- [ ] **Step 1: Write the failing tests**

Append this class to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, before the `if __name__ == "__main__":` block (`FROM_ISSUE`, `AUTO`, `INVESTIGATE`, `REPO_ROOT` and `normalized` already exist in the module):

```python
class LaneTriageContractsTest(unittest.TestCase):
    """#279: from-issue Phase 0 records a shadow lane-triage verdict."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def section(text, heading, next_heading):
        start = text.index(heading)
        return text[start:text.index(next_heading, start + len(heading))]

    def setUp(self):
        self.from_issue = normalized(FROM_ISSUE.read_text(encoding="utf-8"))
        self.auto = normalized(AUTO.read_text(encoding="utf-8"))
        self.investigate = normalized(INVESTIGATE.read_text(encoding="utf-8"))

    def test_phase_zero_runs_lane_triage_in_shadow(self):
        phase_zero = self.section(self.from_issue, "## Phase 0 — Investigate",
                                  "## Phase 1 — Worktree")
        self.assert_ordered(
            phase_zero,
            "run the lane triage below, and post the note",
            "**Lane triage.**", "`contract_change`", "`concurrency_or_persistence`",
            "`open_design_questions`", "`criteria_shape`", "The triage record is",
            "`lane-triage evaluate --repo-root <project.root> --input -`",
            "quoted heredoc", "no input file is written",
            "`ran: full (shadow)`", "`ran: full (active route not yet available)`",
            "every attempt runs full", "`light_lane_unsupported`",
            "light lane unsupported", "terminal return procedure",
            "**CHECKPOINT**", "triage verdict here as information only")

    def test_phase_two_commits_the_record_as_the_spec_triage_section(self):
        phase_two = self.section(self.from_issue, "## Phase 2 — Brainstorm",
                                 "## Phase 3 — Grill")
        self.assert_ordered(phase_two, "**Lane triage** record", "verbatim",
                            "`## Triage` section")
        self.assert_ordered(self.auto, "the Phase-0 issue summary and scope boundary",
                            "**Lane triage** record and verdict verbatim",
                            "`## Triage` section")

    def test_the_note_names_the_lane_triage_field_without_a_binding(self):
        self.assertIn("**Lane triage** (the triage record", self.investigate)
        self.assertNotIn("bindings.workflow", self.investigate)

    def test_claude_md_names_the_command_and_its_seam(self):
        text = normalized((REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assert_ordered(
            text, "`launch-scope scratch` (#277)",
            "`lane-triage evaluate --repo-root <root> --input -` (#279)",
            "`agent_tools.resolve_project.resolve`", "`light_lane_unsupported`",
            "every attempt still runs full", "The remaining Python helpers")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaneTriageContractsTest 2>&1 | tail -4`
Expected: FAILED (failures=4) — `run the lane triage below, and post the note`, `**Lane triage** record`, `**Lane triage** (the triage record` and the `lane-triage evaluate …` CLAUDE.md anchor are not found.

- [ ] **Step 3: Write the text**

Edit exactly as follows; the quoted sentences go in verbatim (hard-wrap at about 80 columns like the surrounding text; the tests normalize whitespace).

1. `SKILL.md`, Phase 0: replace "Investigate per `investigate.md` and post the note." with "Investigate per `investigate.md`, run the lane triage below, and post the note."
2. `SKILL.md`, Phase 0: insert this paragraph after the **Mechanical-only shortcut** paragraph and before **CHECKPOINT**:

   > **Lane triage.** After investigating and before the checkpoint, judge each light-lane signal as `no`, `hit` or `doubt`, with one line of evidence each: `contract_change` (a contract, schema or public interface changes), `concurrency_or_persistence` (concurrency, locking or persisted state is touched), `open_design_questions` (a design question is still open), and `criteria_shape` (`hit` for more than four acceptance criteria or for any criterion that no deterministic code check verifies, `doubt` for one you cannot classify). List the repository-relative paths the change is predicted to touch. The triage record is the JSON object `{"signals": {<name>: {"value": ..., "evidence": ...}, ...}, "paths": [...]}`. Feed it to `lane-triage evaluate --repo-root <project.root> --input -` on stdin through a quoted heredoc; no input file is written. Exit 0 prints the verdict `{"hits": [...], "lane": ..., "mode": ...}`: record the triage record, the verdict and `ran: full (shadow)` under the note's **Lane triage** field, or `ran: full (active route not yet available)` when `mode` is `active`. The verdict is observed, never acted on: every attempt runs full, whatever `lane` says. The `light_lane_unsupported` refusal means the project has no light lane: skip triage and record "light lane unsupported". Any other refusal (`invalid_input` or `resolver_refused`, exit 2 with one stderr line) is an input or resolver error: fix the record and rerun, or stop through the terminal return procedure.

3. `SKILL.md`, Phase 0 **CHECKPOINT** paragraph: append "Interactive mode shows the triage verdict here as information only; there is no lane to choose."
4. `SKILL.md`, Phase 2: append to its first paragraph "When the investigation note carries a **Lane triage** record, the design copies the record and the verdict verbatim into the spec as a `## Triage` section; that commit is what makes them durable."
5. `investigate.md`, Investigate step 5: replace "whether the mechanical-only shortcut applies)." with "whether the mechanical-only shortcut applies); **Lane triage** (the triage record, the `lane-triage` verdict and its `ran:` line, or "light lane unsupported"; `SKILL.md` Phase 0 runs the step)."
6. `AUTO.md`: replace the bullet "- the Phase-0 issue summary and scope boundary," with "- the Phase-0 issue summary and scope boundary, with the investigation note's **Lane triage** record and verdict verbatim, which the design subagent copies into the spec's `## Triage` section,".
7. `CLAUDE.md`, "Agent helper package" paragraph: after the sentence that begins "`launch-scope scratch` (#277)" and ends "deleting none of them.", insert:

   > `lane-triage evaluate --repo-root <root> --input -` (#279) reads an owner's triage record on stdin, reads `bindings.workflow.light_lane` (an optional `resolve-project` member; absent or `null` means unsupported) through `agent_tools.resolve_project.resolve`, the one public function that composes exactly what `resolve-project resolve` prints, and prints the verdict `{hits, lane, mode}` without writing anything: `lane` is `light` only when no signal is `hit` or `doubt` and no predicted path matches a `risk_paths` glob, an absent or `null` member exits 2 with `light_lane_unsupported`, and `from-issue` Phase 0 records the verdict while every attempt still runs full.

8. `instruction-load.json`: run `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "exceed ceiling|^(OK|FAILED)"`. For each `profile <id> on <host>: hot <N> bytes exceed ceiling` line, set that profile's `ceiling_bytes[<host>]` to `<N>`, and append to that profile's `note`: " Ceiling raised for #279: from-issue Phase 0 runs lane-triage and records its shadow verdict (#155 D10)." Rerun until it prints `OK`. Raise only the profiles the test names.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 1200 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `OK`; the four `LaneTriageContractsTest` cases pass, no ceiling is breached and no shell-example refusal appears.

Run: `if git diff --quiet HEAD -- .agents/project.json home/common/claude-code/default.nix home/common/agent-skills/tests/test_shell_example_contracts.py; then echo unchanged; else echo CHANGED; exit 1; fi`
Expected: `unchanged` (D3, D9).

- [ ] **Step 5: Final gate (whole plan)**

Stage everything this task changed (`git add` the six files above) so the Git-backed build sees it, then run each in the foreground with an explicit timeout of at least 2400 s (3600 s recommended):

Run: `timeout 3600 just build 2>&1 | tail -5`
Expected: the build succeeds.

Run: `timeout 3600 just agent-workflow-tests 2>&1 | tail -5`
Expected: `OK` (skips allowed only where the suite already skips); 0 failures, 0 errors. `tests/test_lane_triage.py` appears in the run.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/investigate.md home/common/agent-skills/skills/from-issue/AUTO.md CLAUDE.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "feat(from-issue): shadow lane triage at Phase 0 (#279)" -m "<trailers>"
```
Use the launch-commit identity and commit trailers from your dispatch brief.

## Phase-5 review amendments (per D10)

- **R-SF1:** `SKILL.md` line 8 says `workflow-state build-delivery` is "The only sanctioned exception" to resolving once. Keep that pinned substring intact and add right after it a clause stating that `lane-triage evaluate` likewise performs its own read-only resolution to read `bindings.workflow.light_lane` (reword the sentence so it stays true; e.g. "…; `lane-triage evaluate` likewise performs its own read-only resolution, only to read `bindings.workflow.light_lane`"). Add an anchor for that clause in `LaneTriageContractsTest`.
- **R-SF2:** The Lane triage paragraph must cover every exit: after the exit-0, `light_lane_unsupported` and other-refusal (exit 2) cases, add that any other non-zero exit (a traceback's exit 1, a missing command's 127) stops the attempt through the terminal return procedure. Anchor it in the contract test.
- **R-D1:** In the final gate, after `just build`, also run `just agent-installed-skill-tests` (timeout ≥ 2400 s); it exercises the Task-2 `LAUNCHER_FLOOR` row.
