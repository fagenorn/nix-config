# Task 2: The resume entry reads `SKILL.md` by section

Spec § Solution 2–4, § Decisions "The resume entry", "The clause move" and "Instruction budget", § Test seams 2–4. Rests on D4–D8 and D10. After this task:
- The index's `resume-pack.md` line names short handles that `skill-sections` resolves.
- The Artifact report boundary and the `implementation-plan` projection confirmation form `## Producer reports`, before `## Phase 2 — Brainstorm`.
- `resume-pack.md` runs the helper in its reading rule and points check 2 at it.
- The contract tests pin all of this through the helper.
- The instruction corpus shrinks by 7 bytes.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/resume-pack.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`
- Modify: `home/common/agent-skills/README.md`
- Create: `.agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.acceptance.md`

**Interfaces:**
- Consumes (Task 1): `python -m agent_tools.skill_sections <file> <section>...` from the source `python/`, exit 0 when every name resolves to exactly one `##` heading, else exit 2 with a stderr report. The contract module runs it as a child process and never imports `agent_tools` (D8).
- Produces: the handles `Lifecycle identity`, `Decision ledger`, `Skill-tool`, `Dispatch`, `Terminal return`, `Suspension`, `Producer reports` and `Phase <n>`, and the entry argv `skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside this one'`.

**Invariants:**
- The moved text is byte-identical to its source, except that the 30-byte lead-in `**Artifact report boundary.** ` gives way to the heading line `## Producer reports`. `**Decomposition stop.**` stays in the dispatch section (D6).
- Checks 1–3 of `resume-pack.md` keep their order and precede the reading rule. A failed check still loads the whole skill through the Skill tool. The `AUTO.md`, `delegated-owner.md` and `ship-handoff.md` index lines are unchanged (D4).
- No ceiling is raised: `home/common/agent-skills/instruction-load.json` and every gate file stay as at base (D7).
- Sizes on base `328f08da`: `SKILL.md` exactly 30,513 bytes (base 30,603; the contract cap is 30,611) and `resume-pack.md` exactly 1,868 bytes (base 1,785). Measured from a later merge base, the change is −90 and +83 bytes.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. Add `import sys` between `import subprocess` and `import tempfile`.
2. Insert this function right before `class SlimBootContractsTest(unittest.TestCase):`, followed by two blank lines:

```python
def skill_sections(document, *sections):
    """Run the source tree's `skill-sections` on `document` (issue 505 D8): a child process with
    `PYTHONPATH` set to `python/`, because the installed-mode run has no package on its path."""
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.skill_sections", str(document), *sections],
        capture_output=True, text=True, timeout=60, check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")})
```

3. In `SlimBootContractsTest`, add this class attribute after `ENTRY = "<from-issue-dir>/resume-pack.md"`:

```python
    INDEX_CALL = "skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside this one'"
```

4. In `test_the_entry_runs_its_checks_before_any_skill_section`, replace the last anchor `` "`## Files beside this one`" `` with `` f"`{self.INDEX_CALL}`" ``. Its other anchors stay as they are.
5. Delete the static method `headings` (its only caller is the test rewritten next), and replace `test_every_section_and_file_the_verified_pack_reads_exists` with these three methods. The third method's anchors are headings that only tests and the helper read (agent-helpers rule 6):

```python
    def test_every_section_and_file_the_verified_pack_reads_exists(self):
        for name, document in (("AUTO.md", AUTO), ("resume-pack.md", FROM_ISSUE),
                               ("delegated-owner.md", DELEGATED_OWNER),
                               ("ship-handoff.md", FROM_ISSUE)):
            sections = []
            for span in re.findall(r"`([^`]+)`", self.bullet(name)):
                if span.endswith(".md"):
                    with self.subTest(bullet=name, span=span):
                        self.assertTrue((FROM_ISSUE_DIR / span).is_file())
                elif not (span.startswith("-") or "<" in span or span in ("sdd", "ship-issue")):
                    sections.append(span.removeprefix("## "))
            with self.subTest(bullet=name, sections=sections):
                self.assertTrue(sections)
                printed = skill_sections(document, *sections)
                self.assertEqual(printed.returncode, 0, printed.stderr)
        for heading in ("`## Checks and Phases 6–7`", "`## Generic delegate`"):
            self.assertIn(heading, self.bullet("delegated-owner.md"))

    def test_the_resume_read_list_names_producer_reports_and_every_phase_resolves(self):
        index = self.bullet("resume-pack.md")
        for span in ("`Producer reports`", "`Phase <n>`"):
            self.assertIn(span, index)
        printed = skill_sections(FROM_ISSUE, *(f"Phase {n}" for n in range(8)))
        self.assertEqual(printed.returncode, 0, printed.stderr)

    def test_producer_report_rules_left_the_always_read_dispatch_section(self):
        text = self.read(FROM_ISSUE)
        dispatch = self.section(text, "## Dispatch, phase-budget and attempt-budget rules",
                                "## Terminal return procedure")
        producer = self.section(text, "## Producer reports", "## Phase 2 — Brainstorm")
        for argv in ("--boundary producer", "review-feasibility confirm"):
            with self.subTest(argv=argv):
                self.assertNotIn(argv, dispatch)
        for argv in ("artifact-budget validate-report --boundary producer --input -",
                     "review-feasibility confirm --plan <root> --base <base> --input -"):
            with self.subTest(argv=argv):
                self.assertIn(argv, producer)
```

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, add `"skill-sections"` to `COMMAND_VOCABULARY` between `"ship-delivery"` and `"sleep"`, so the entry's argv is vetted as one plain command (spec § Test seams 3).

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 300 s): `bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SlimBootContractsTest 2>&1 | grep -E "^(FAIL|ERROR):|^[A-Za-z]*Error|^Ran |^FAILED"'`
Expected: `Ran 7 tests`, `FAILED (failures=2, errors=1)`. The failures are `test_the_entry_runs_its_checks_before_any_skill_section` (anchor `` `skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside this one'` `` not found) and `test_the_resume_read_list_names_producer_reports_and_every_phase_resolves` (`` '`Producer reports`' not found ``). The error is `test_producer_report_rules_left_the_always_read_dispatch_section` (`ValueError: substring not found`). The rewritten span test passes already: today's spans are full headings. Keep this output for the acceptance record.

- [ ] **Step 3: Write the minimal implementation**

Make each replacement below exactly once, byte for byte. Each `old` and `new` is the single line of its fence, and every `old` occurs once in its file.

1. `SKILL.md`, the `resume-pack.md` bullet of `## Files beside this one` (−80 bytes). Old, then new:
   ```text
   `Decision ledger (artifact discipline)`, `Skill-tool invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal return procedure` and `Suspension procedure`, then this file's `## Phase <n>` section,
   ```
   ```text
   `Decision ledger`, `Skill-tool`, `Dispatch`, `Terminal return` and `Suspension`, in Phases 2–4 `Producer reports`, then `Phase <n>`,
   ```
2. `SKILL.md`, the clause move (D6; −10 bytes). Cut the text from the first character of `**Artifact report boundary.** ` up to, but not including, `**Decomposition stop.**`. That is two paragraphs, each followed by its blank line. Remove the leading `**Artifact report boundary.** ` from the cut text, so it begins `At every producer boundary,`. Insert the line `## Producer reports`, and right after it the cut text, immediately before the line `## Phase 2 — Brainstorm`. No blank line follows the heading, as in its neighbours. The new section ends in the blank line that precedes `## Phase 2 — Brainstorm`.
3. `resume-pack.md`, check 2 (+20 bytes). Old, then new:
   ```text
   passes first every check of the delegated-owner file `SKILL.md`'s index names.
   ```
   ```text
   passes first every check of the delegated-owner file `SKILL.md`'s index names (print it as below).
   ```
4. `resume-pack.md`, the reading rule (D5; +63 bytes). Old, then new:
   ```text
   Read `SKILL.md` through `## Files beside this one`, then only the sections that index names for your phase, and start from `next_action`.
   ```
   ```text
   Run `skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside this one'`, then the same without `--opening` for only the sections that index names for your phase, and start from `next_action`.
   ```
5. `home/common/agent-skills/README.md`, the resume-pack paragraph of § Lifecycle helpers. Old, then new:
   ```text
   before reading any of `SKILL.md`, then its index and the current phase's sections, and a failed check
   ```
   ```text
   before reading any of `SKILL.md`, then prints its opening and index and then the current phase's sections through `skill-sections`, and a failed check
   ```

- [ ] **Step 4: Verify**

1. Run the Step 2 command. Expected: `Ran 7 tests`, then `OK` (it prints no `FAILED` line).
2. Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3'`. Expected: `Ran 226 tests`, `OK (skipped=3)`.
3. Show that the span pin can fail: break one handle, run the span test, restore the handle (one `bash` session, timeout 120 s):
   ```bash
   F=home/common/agent-skills/skills/from-issue/SKILL.md
   swap() { python3 -c 'import pathlib, sys; p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8"); assert t.count(sys.argv[2]) == 1; p.write_text(t.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' "$@"; }
   swap "$F" '`Terminal return` and `Suspension`' '`Terminal return` and `Suspended`'
   PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_every_section_and_file 2>&1 | grep "unknown section"
   swap "$F" '`Terminal return` and `Suspended`' '`Terminal return` and `Suspension`'
   ```
   Expected: the `grep` prints a line ending `skill-sections: unknown section "Suspended"`, and item 4 then shows the file restored.
4. Run `wc -c home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/resume-pack.md`. Expected: `30513` and `1868` (on a later merge base, its sizes −90 and +83). Any other number means a replacement drifted; fix the text, not the expectation.
5. Run (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -1'`. Expected: `check: pass`. It must pass with no `--raise-label`. Sync with `origin/main` first if it moved since `328f08da`: at base the corpus has 0 bytes of headroom, so a merge that grew it can fail this gate.
6. Print the ceilings this task moves (timeout 120 s):
   ```bash
   PYTHONPATH="$PWD/python" python3 -c 'from pathlib import Path
   from agent_tools import instruction_load as il, skill_lint as sl
   s = sl.working_tree(Path.cwd()); m = il.load_model(s.read(il.MODEL_PATH))
   for c in il.ceilings(m, il.measure(m, s.read), il.measure_corpus(s)):
       if c.label == "corpus" or c.label.split()[1] in ("from-issue-controller", "orchestrated-issue-owner", "implementation-owner"):
           print(f"{c.label}: {c.measured}/{c.ceiling}")'
   ```
   Expected at base `328f08da` plus this change: `corpus: 403952/403959`; from-issue-controller conditional `46594/46610` (claude) and `36889/36905` (codex), hot `71159/71275`; orchestrated-issue-owner conditional `115706/115802`; implementation-owner conditional `102768/102814` (claude) and `90913/90959` (codex). After a sync, every line must still have measured ≤ ceiling.
7. Run `bash -c 'git diff --quiet "$(git merge-base HEAD origin/main)" -- home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/from-issue/delegated-owner.md'`. Expected: exit 0, so the branch leaves those files alone.

- [ ] **Step 5: Write the acceptance record**

Create `.agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.acceptance.md` with exactly this content. Fill each `<…>` from the runs above. The sdd controller writes the `Verdict` column, so leave it as `—`:

```markdown
# Acceptance record — issue 505

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] The helper prints exactly the named sections, in file order, and fails clearly on an unknown heading. The resume entry names the helper with the section list. `just agent-instruction-budget` (no raise label) and `just build` pass. Measured by: contract tests in the agent workflow test suite. | code | `tests/test_skill_sections.py` and `home/common/agent-skills/tests/test_workflow_skill_contracts.py::SlimBootContractsTest`, run by `just agent-workflow-tests`; `just agent-instruction-budget` (the required check `Instruction Budget`); `just build` | red at each task's start commit: Task 1 Step 2 `<its ModuleNotFoundError line>`, Task 2 Step 2 `<its FAILED line>`; Task 2 Step 4 `just agent-instruction-budget`: `check: pass`, `corpus: 403952/403959`; green in final verification | — | red on the start commits, green under `just agent-workflow-tests` and `just build` on the final head | — |
| AC2 | [evidence] Measured by: `just agent-costs --report boot` on mbp, fresh owners in the 7 days after the first `just switch` that includes this change; threshold: mean from-issue `SKILL.md` tokens per fresh boot (skill bodies + skill files) ≤ 4k (2.2k + 8.1k = 10.3k in phases 6–7, 2026-10-27..11-01). | evidence | `just agent-costs --report boot` on mbp; threshold: mean from-issue `SKILL.md` tokens per fresh boot (skill bodies + skill files) ≤ 4k | not measured — post-deploy (D9, D10) | — | fresh owners in the 7 days after the first `just switch` on mbp that includes the merge, read only once the boot report attributes `skill-sections` output to the file it reads (D9); planning projects 20,032–21,941 bytes of `SKILL.md` per Phase 6–7 resume boot, about 5–6k tokens (D10); evidence pending, never claimed by the delivery | — |
```

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/resume-pack.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/README.md .agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.acceptance.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(from-issue): resume entry reads SKILL.md by section (issue 505)" -m "Co-Authored-By: <session trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":8,"record_bytes":16384,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"home/common/agent-skills/skills/from-issue/SKILL.md"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":4096,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"home/common/agent-skills/skills/from-issue/resume-pack.md"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":16,"record_bytes":12288,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_shell_example_contracts.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":12288,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r2f"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2f","last_task":2,"owner":2,"path":".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.acceptance.md"}]}}
```
