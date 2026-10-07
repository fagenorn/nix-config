# Task 5: Fit the from-issue text under the ceilings and re-pin AC4

Spec section **Instruction budget**; rows D6, D7, D9, D12, D13, D14 and D16 (D16 reverses part of D14).

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (resolve-once paragraph, deadline-rejected `progress` paragraph, Phase 0, Phase 2)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (the Phase-0 summary bullet)
- Modify: `home/common/agent-skills/skills/from-issue/investigate.md` (step 5's **Lane triage** field)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 4): a head that contains `origin/main`, with `instruction-load.json` equal to main's. Consumes (Task 2): `python/agent_tools/lane_triage.py`'s module-level literal tuples `SIGNALS`, `SIGNAL_MEMBERS` and `TOP_MEMBERS`, and its printed verdict, closed to `hits`, `lane` and `mode` (`tests/test_lane_triage.py` asserts `sorted(value) == ["hits", "lane", "mode"]`). Consumes (Task 1): `python/agent_tools/resolve_project.py`'s `LIGHT_LANE_MODES = ("shadow", "active")`.
- Produces: `LaneTriageRecordKeysTest` with two tests, which the acceptance map uses for AC4, and a from-issue corpus whose summed byte delta against `origin/main` is at most 0.

**Invariants:**
- `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main` exits 0, and `instruction-load.json` is not touched (D12, D15).
- The summed byte delta of `SKILL.md`, `AUTO.md` and `investigate.md` against `origin/main` is ≤ 0.
- These clauses survive verbatim: "only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution", the two helper rejection strings "cannot record progress at or after attempt deadline" and "progress requires an active attempt", and "without a phase advance or a newly recorded progress marker".
- The call stays an inline span. No fence, no `COMMAND_VOCABULARY` entry and no allowlist change (D9).
- The new test file code imports nothing from `agent_tools`, because `just agent-installed-skill-tests` runs this file without `PYTHONPATH` (D16).
- No English phrase pin is added. The deleted tests are exactly `LaneTriageContractsTest` (the whole class) and `WorkflowSkillContractsTest.test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads` and `.test_from_issue_routes_a_deadline_rejected_progress_to_the_suspension_procedure` (D14).

- [ ] **Step 1: Write the new pin and delete the old ones**

Add `import ast` to the module's imports. Delete the three tests named in the invariants. Then append the following before the `if __name__ == "__main__":` block:

```python
LANE_TRIAGE_VERDICT_KEYS = {"hits", "lane", "mode"}  # closed by tests/test_lane_triage.py


def module_constants(path, *names):
    """The literal module-level assignments `names` in `path`, read without importing it."""
    found = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    assert set(found) == set(names), (path, names, sorted(found))
    return found


class LaneTriageRecordKeysTest(unittest.TestCase):
    """#279 (D16): Phase 0 names the JSON keys `lane-triage evaluate` reads and prints."""

    def setUp(self):
        text = normalized(FROM_ISSUE.read_text(encoding="utf-8"))
        start = text.index("## Phase 0 — Investigate")
        phase_zero = text[start:text.index("## Phase 1 — Worktree", start)]
        spans = " ".join(re.findall(r"`([^`]+)`", phase_zero))
        self.span_words = set(re.findall(r"[a-z_]+", spans))

    def test_phase_zero_names_the_triage_record_keys_lane_triage_consumes(self):
        lane = module_constants(REPO_ROOT / "python/agent_tools/lane_triage.py",
                                "SIGNALS", "SIGNAL_MEMBERS", "TOP_MEMBERS")
        expected = set().union(*lane.values())
        self.assertEqual(expected - self.span_words, set())

    def test_phase_zero_names_the_verdict_keys_and_every_light_lane_mode(self):
        modes = module_constants(REPO_ROOT / "python/agent_tools/resolve_project.py",
                                 "LIGHT_LANE_MODES")["LIGHT_LANE_MODES"]
        self.assertEqual((LANE_TRIAGE_VERDICT_KEYS | set(modes)) - self.span_words, set())
```

- [ ] **Step 2: Rewrite the skill text, without the verdict key span yet**

Apply these edits.

**`SKILL.md`, resolve-once paragraph.** Replace the clause "; `lane-triage evaluate` likewise performs its own read-only resolution, only to read `bindings.workflow.light_lane`" with " (and `lane-triage evaluate`, read-only, for `bindings.workflow.light_lane`)".

**`SKILL.md`, deadline paragraph.** Replace the whole paragraph that begins "If `workflow-state progress` is rejected because the" (it runs through "from before the suspension model.") with the text below. Keep the existing quoted line that sits between the first sentence and the rest, "`cannot record progress at or after attempt deadline` …, or", unchanged (D13):

```
If `workflow-state progress` is rejected because the attempt deadline has passed —
<the existing "cannot record progress at or after attempt deadline" line, unchanged>
`progress requires an active attempt` once the lazy reaper demoted the attempt to
`suspended(unknown)` — that is an environmental interruption, not a verdict or a
fault: never retry it and never write a `workflow-state finish` (the helper rejects
one on a non-active attempt). Print the re-entry line and stop. The reaper has
already durably recorded either a resumable suspension or, at the anti-zombie bound
(parked too often in a row without a phase advance or a newly recorded progress marker), a
`stopped(stalled)` terminal; do not assert which, since re-entry resumes the one
or replays the other.
```

**`SKILL.md`, Phase 0.** The opening sentence reads "Investigate per `investigate.md`, run the lane triage below, and post the note." Delete the CHECKPOINT sentence "Interactive mode shows the triage verdict here as information only; there is no lane to choose." Then replace the branch's **Lane triage** paragraph with this single paragraph:

```
**Lane triage.** Before the checkpoint, judge each light-lane signal `no`, `hit` or `doubt`, with one line of evidence: `contract_change` (a contract, schema or public interface changes), `concurrency_or_persistence` (concurrency, locking or persisted state), `open_design_questions` (a design question is open) and `criteria_shape` (`hit`: over four acceptance criteria, or one no deterministic code check verifies). Feed `{"signals": {<name>: {"value": ..., "evidence": ...}}, "paths": [<predicted repo-relative paths>]}` through a quoted heredoc to `lane-triage evaluate --repo-root <project.root> --input -`. Exit 0: record the input, its verdict and `ran: full (shadow)` (`ran: full (active route not yet available)` for `mode: active`) under the note's **Lane triage**; every attempt runs full. `light_lane_unsupported`: record "light lane unsupported". `invalid_input` or `resolver_refused`: fix the record and rerun, or stop; any other exit stops; every stop uses the terminal return procedure.
```

**`SKILL.md`, Phase 2.** The **Lane triage** sentence becomes: `A note's **Lane triage** record and verdict go verbatim into the spec's `## Triage` section.`

**`AUTO.md`.** The bullet becomes: `- the Phase-0 issue summary and scope boundary, with the note's **Lane triage** record and verdict verbatim,`

**`investigate.md`, step 5.** The field becomes: `**Lane triage** (Phase 0's record, verdict and `ran:` line, or "light lane unsupported").`

- [ ] **Step 3: Run the new pin and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k LaneTriageRecordKeysTest 2>&1 | tail -6`
Expected: FAIL in `test_phase_zero_names_the_verdict_keys_and_every_light_lane_mode`, with the missing set `{'hits'}`. `lane` is already present, because the regex splits the `lane-triage` span. The record-keys test passes.

- [ ] **Step 4: Name the verdict keys**

In the Phase-0 paragraph, change "record the input, its verdict and" to "record the input, its `{hits, lane, mode}` verdict and". Re-run Step 3's command. Expected: `OK`, 2 tests.

- [ ] **Step 5: Verify**

Run: `python3 - <<'EOF'
import subprocess, pathlib
d = sum(pathlib.Path(f).stat().st_size - len(subprocess.run(["git", "show", f"origin/main:{f}"], capture_output=True, check=True).stdout)
        for f in [f"home/common/agent-skills/skills/from-issue/{n}" for n in ("SKILL.md", "AUTO.md", "investigate.md")])
print("delta", d); raise SystemExit(d > 0)
EOF`
Expected: `delta` at most 0. The probe estimates about −19. The command exits 1 at this task's base.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main > "${TMPDIR:-/tmp}/il-279.txt" 2>&1; echo "exit=$?"; tail -3 "${TMPDIR:-/tmp}/il-279.txt"`
Expected: `exit=0`. It is non-zero at this task's base, as Task 4 recorded.

Run: `if grep -q 'class LaneTriageContractsTest\|test_expiry_prose_describes\|routes_a_deadline_rejected_progress' home/common/agent-skills/tests/test_workflow_skill_contracts.py; then exit 1; fi`

Run, with a timeout of at least 900 s: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py > "${TMPDIR:-/tmp}/ut5-279.log" 2>&1; echo "exit=$?"; tail -3 "${TMPDIR:-/tmp}/ut5-279.log"`
Expected: `exit=0` and `OK`. Any other failing pin over the rewritten text is a phrase pin. Delete it under rule 6, and report its name. Never re-word it.

- [ ] **Step 6: Commit**

Stage the four files and commit with the message `fix(from-issue): fit #279's lane triage under the instruction ceilings`, signed and with the session trailers.
