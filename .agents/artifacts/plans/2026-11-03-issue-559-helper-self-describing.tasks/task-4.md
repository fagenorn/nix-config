# Task 4: skill-lint L6 and skill text without python-tree pointers

**Files:**
- Modify: `python/agent_tools/skill_lint.py` (new `PYTHON_TREE`, `L6_TEXT`, `_python_tree_violations`; `violations`; two docstrings)
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md` (§ Review feasibility forecast; § Package budget's **Projection gate** paragraph and its exit-2 bullet)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (§ Cumulative delivery gate)
- Modify: `home/common/agent-skills/skills/retro/SKILL.md` (§ Files, the **Helpers** bullet)
- Test: `home/common/agent-skills/tests/test_skill_lint.py` (`RuleTest.test_l6_reports_a_path_into_the_python_tree_in_any_markdown_file`; the existing `LiveTreeTest.test_the_live_tree_lints_clean`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`PROJECTION_MACHINE_TEXT[WRITING_PLANS]`)

**Interfaces:**
- Consumes: Task 2's `review-feasibility forecast --plan <root> --base <base> --spec <spec> --input -`, whose `--help` prints the estimate shape and the sizing rule. From `skill_lint`: `TREE_ROOTS`, `Snapshot.list_files(prefix)`, `read_listed(snapshot, path) -> bytes` and `Violation(key, text)`, which is frozen and ordered.
- Produces: skill-lint rule L6. For every `.md` file that `snapshot.list_files(root)` returns for each of the three `TREE_ROOTS` (with `evals/` and `scripts/` included, unlike L4), it reports each line matching `PYTHON_TREE = re.compile(r"(?<![A-Za-z0-9_.~/-])python/|agent_tools/")` as `Violation(f"L6 {path}:{line_number}", L6_TEXT)`, with 1-based line numbers over `text.splitlines()` of the UTF-8 decode with replacement. `L6_TEXT = "names nix-config's python/ tree, which is not installed"`, so `lint` prints `L6 <path>:<n>: names nix-config's python/ tree, which is not installed` (D8, D13).

**Invariants:**
- `python/` preceded by a path character (`A-Za-z0-9_.~/-`) is legal, so `~/.agents/lib/python/…` and `cpython/` never report. Every `agent_tools/` reports (D8).
- L1–L5 are unchanged, `violations` still returns a sorted list without duplicates, and the CLI's exit codes are unchanged.
- After this task no `.md` file in the three skill trees names `python/README.md` or `agent_tools/`; the live-tree test is the check (AC3).
- `writing-plans/SKILL.md` and `sdd/SKILL.md` stay no larger than at `8d0bbc25`, and `just agent-instruction-budget` passes with no raise (D9). The `from-issue` standards-review and REVIEW-CONTRACT documents are untouched (D10).
- The writing-plans contract keeps the block headings, `git merge-base HEAD origin/<integration-branch>`, the `gate` argv, the `--save-dir` argument and `` `projection` ``. It drops `git-range-ownership/v1` and `authored-cumulative/v1`, which the skill no longer tells anyone to write, and gains the `forecast` argv (agent-helpers rule 6).

- [ ] **Step 1: Write the failing tests**

Add this method to `RuleTest` in `home/common/agent-skills/tests/test_skill_lint.py`, directly after `test_l5_demands_third_person_and_a_trigger_clause`:

```python
    def test_l6_reports_a_path_into_the_python_tree_in_any_markdown_file(self):
        self.files[f"{ALPHA}/GUIDE.md"] = (b"# Guide\nshort guide naming SKILL.md and CONTRACT.md\n"
                                           b"Field semantics: `python/README.md`.\n")
        self.files[f"{ALPHA}/evals/notes.md"] = b"NOT.md is mentioned here\nread python/agent_tools/x.py\n"
        self.files[f"{ALPHA}/scripts/README.md"] = b"script docs\nsee agent_tools/\n"
        self.files[f"{CLAUDE}/beta/SKILL.md"] = skill(
            "beta", body="Installed at ~/.agents/lib/python/review_gate.py; cpython/ is fine.\n")
        self.assertEqual(self.keys(), {f"L6 {ALPHA}/GUIDE.md:3", f"L6 {ALPHA}/evals/notes.md:2",
                                       f"L6 {ALPHA}/scripts/README.md:2"})
        self.assertIn(f"L6 {ALPHA}/GUIDE.md:3: names nix-config's python/ tree, which is not installed",
                      skill_lint.lint(dict_snapshot(self.files)))
```

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, replace the `WRITING_PLANS` entry of `PROJECTION_MACHINE_TEXT` with:

```python
    WRITING_PLANS: (
        "## Review feasibility delivery", "## Review feasibility task",
        "review-feasibility forecast --plan <root> --base <base> --spec <spec> --input -",
        "git merge-base HEAD origin/<integration-branch>",
        "review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0",
        '--save-dir "$(sdd-workspace <root>)"', "`projection`"),
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; rc=0; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py -k test_l6_reports -k test_the_live_tree_lints_clean 2>&1 | tail -4 || rc=1; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_projection_callers_carry_their_machine_text 2>&1 | tail -4 || rc=1; exit $rc'`
Expected: both runs FAIL. The L6 test fails because `keys()` is empty, while the live-tree test still passes because L6 does not exist yet. The contract test fails on the `forecast` argv item.

- [ ] **Step 3: Write the minimal implementation**

**`python/agent_tools/skill_lint.py`.** Add `PYTHON_TREE` and `L6_TEXT` beside the other module constants, and add `_python_tree_violations(snapshot: Snapshot) -> list[Violation]` implementing the Produces rule. `violations` extends its list with that function's result after the per-directory loop, keeping `sorted(set(found))`. Change "rules L1–L5" in the module docstring to "rules L1–L6", and "Every L1-L5 violation" in `violations`' docstring to "Every L1-L6 violation".

Now run the Step 2 command again. The L6 test passes, and the live-tree test fails with exactly three lines: `L6 home/common/agent-skills/skills/retro/SKILL.md:60`, `L6 home/common/agent-skills/skills/sdd/SKILL.md:49` and `L6 home/common/agent-skills/skills/writing-plans/SKILL.md:170`.

**`home/common/agent-skills/skills/writing-plans/SKILL.md`.** Replace everything from the line `## Review feasibility forecast` up to, but not including, the line `## Package budget` with this text, which ends in one blank line:

```markdown
## Review feasibility forecast

Once the content is final, pin `<base>` with `git merge-base HEAD origin/<integration-branch>` and run `review-feasibility forecast --plan <root> --base <base> --spec <spec> --input -`. From an estimate on stdin, one entry per task in order listing its `Files:` paths, it writes the root's `## Review feasibility delivery` and each member's `## Review feasibility task` block; `--help` gives the shape and sizing rule:

`{"tasks":[{"files":[{"path":"a.py","change":"modify","added_lines":30,"deleted_lines":10}]}]}`

Rerun it after any edit that changes a task's files. A refusal names the failing field.

```

In the **Projection gate** paragraph, replace the first text below with the second:

```text
and a `within_budget` check, pin `<base>` with `git merge-base HEAD origin/<integration-branch>`, commit, then run
```

```text
and a `within_budget` check, commit, then run
```

In the bullet below that paragraph, replace the first text below with the second:

```text
- Exit 2: one forecast correction round (commit, rerun), then
```

```text
- Exit 2: one forecast correction round (fix the estimate or the plan, rerun `forecast`, commit, rerun), then
```

The file shrinks from 12682 to 12286 bytes.

**`home/common/agent-skills/skills/sdd/SKILL.md`.** In § Cumulative delivery gate, delete ` (steps and ledger lines: nix-config's `python/README.md` § `sdd-gate`)`, so that the sentence reads "`sdd-gate next` gates every dispatch on the cumulative package, then the projection of the remaining tasks." The refusal already names its `step` and `detail` (D9).

**`home/common/agent-skills/skills/retro/SKILL.md`.** Replace the **Helpers** bullet with:

```markdown
- **Helpers**: the `~/.agents/bin` commands are built from nix-config's command table, `lib/agent-tools.nix`, and its `home/common/agent-skills/scripts/`.
```

- [ ] **Step 4: Verify**

1. Focused tests, green (timeout 600 s): the Step 2 command.
   Expected: both runs `OK`.
2. Both modules, which cover the no-growth tests and the rest of the lint suite (timeout 1800 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -4'`
   Expected: `OK`. A failure in `test_edited_planning_documents_do_not_grow` or `test_edited_execution_documents_do_not_grow` means a skill file grew past its `8d0bbc25` size.
3. No python-tree pointer is left in any skill tree (instant): `if rg -n --pcre2 '(?<![A-Za-z0-9_.~/-])python/|agent_tools/' -g '*.md' home/common/agent-skills/skills home/common/claude-code/skills home/common/codex/skills; then exit 1; fi`
   Expected: exit 0 with no output. Exit 1 lists the remaining pointer.
4. Instruction Budget (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- just agent-instruction-budget`
   Expected: exit 0, with no raise requested.
5. Build (timeout 3600 s). The build imports every `agent_tools` module and installs the skills, and it sees only tracked content, so stage first: `git add python/agent_tools/skill_lint.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/retro/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py`, then `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; just build 2>&1 | tail -3'`
   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/skill_lint.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/retro/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-559): add skill-lint L6, drop python-tree pointers" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | wc -l | tr -d ' ')" = 6 && git show --name-only --format= HEAD | grep -qx home/common/agent-skills/skills/writing-plans/SKILL.md`
Expected: exit 0. A non-zero exit means the commit touched another file or missed the skill edit.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":4,"records":[{"bounds":[{"added_lines":25,"boundary":"all","deleted_lines":3,"record_bytes":8192,"support":{"covers":["r4-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-1","last_task":4,"owner":4,"path":"python/agent_tools/skill_lint.py"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r4-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-2","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_skill_lint.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":8,"record_bytes":8192,"support":{"covers":["r4-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-3","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/writing-plans/SKILL.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":8192,"support":{"covers":["r4-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-4","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/sdd/SKILL.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":4096,"support":{"covers":["r4-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-5","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/retro/SKILL.md"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["r4-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4-6","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
