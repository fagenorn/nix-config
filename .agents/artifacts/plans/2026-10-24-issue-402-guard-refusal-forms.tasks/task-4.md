# Task 4: `ship-issue` merges with `--match-head-commit <reviewed HEAD_SHA>`

Spec § Shipping flow, § Shape fixture (first bullet), § Test seams (Shell-example suite, Build); per D11, D12, D15. After this task `ship-issue`'s two merge spellings carry `--match-head-commit <reviewed HEAD_SHA>`, the shape fixture runs that spelling through the guard bare and behind both scrub prefixes, `CI-MERGE.md` routes a merge refused for a moved head to Phase 6's unreviewed-commits stop, and `REMAINDER.md` gives a remainder owner its value, all inside the ship-owner instruction budget with no ceiling change. This is the last task: its guard-suite invocation builds and runs the final tree.

**Files:**
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REMAINDER.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's merge grammar (`[--match-head-commit <sha>]`, both arms); the guard suite's `test_every_guarded_command_shape_gets_its_verdict` (reads `values` and `skill_forms`); the shell-example suite's `guarded_command_findings` (R1 holds a living example to a `skill_forms` template, space for space); `WorkflowSkillContractsTest.test_ship_issue_merge_is_bound_to_the_resolved_repository`.
- Produces: fixture `values["<reviewed HEAD_SHA>"]`; the `merge.subject` and `merge.plain` templates below; the two `SKILL.md` spellings, the `CI-MERGE.md` route and the `REMAINDER.md` value, each in the exact words below.

**Invariants:**
- `<reviewed HEAD_SHA>` is the full `HEAD_SHA` Phase 6 compared: fixed in Phase 5, re-fixed after a review fix or a post-selection sync; for a remainder owner, the current selection's head (D11).
- `SKILL.md` changes only its two merge spellings, each within its current reflowed line count; its body stays at 498 reflowed lines (skill-lint L2 ≤ 500).
- The ship-owner conditional set (`CI-MERGE.md`, `POST-SELECTION-SYNC.md`, `HUMAN-GATE.md`, `REMAINDER.md`) grows by at most 145 bytes: the exact wording below measures +131 (D15). `instruction-load.json` is untouched.
- The new clauses spell no guarded verb as a command, so R1 reads no new living example.

- [ ] **Step 1: Write the failing tests**

1. In `tests/fixtures/guarded-command-shapes.json`, add to `values` after `"<rendered subject>"`:

```json
    "<reviewed HEAD_SHA>": "d4d9acc0505c73305b3e0ced029db43100bc0e8a"
```

and set the two merge templates to:

```json
      "template": "gh pr merge <pr-num> --repo <resolved-repository> --merge --subject \"<rendered subject>\" --match-head-commit <reviewed HEAD_SHA> --delete-branch",
```

(`merge.subject`) and

```json
      "template": "gh pr merge <pr-num> --repo <resolved-repository> --merge --match-head-commit <reviewed HEAD_SHA> --delete-branch",
```

(`merge.plain`). Their verdicts stay `{"exit": 0}` bare, `prefixed` and `env_prefixed`.

2. In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `test_ship_issue_merge_is_bound_to_the_resolved_repository`: insert `--match-head-commit <reviewed HEAD_SHA> ` before `--delete-branch` in both expected strings, so they read `'gh pr merge <pr-num> --repo <resolved-repository> --merge [--subject "<rendered subject>"] --match-head-commit <reviewed HEAD_SHA> --delete-branch'` and `'gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --match-head-commit <reviewed HEAD_SHA> --delete-branch'`.

- [ ] **Step 2: Run the tests and watch them fail**

Run the shell-example run, then `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_ship_issue_merge_is_bound_to_the_resolved_repository 2>&1 | tail -4` (timeout 600 s).
Expected: FAIL — `test_every_guarded_command_is_a_cited_form` reports `ship-issue/SKILL.md` R1 (the old spelling) and R3 (the new template has no site), and the contracts test finds no line holding the new spelling.

- [ ] **Step 3: Write the minimal implementation**

1. `home/common/agent-skills/skills/ship-issue/SKILL.md`, flow diagram (step 7) and Phase 7 fence: insert `--match-head-commit <reviewed HEAD_SHA> ` before `--delete-branch`, giving exactly

```
7. Merge                   → gh pr merge <pr-num> --repo <resolved-repository> --merge [--subject "<rendered subject>"] --match-head-commit <reviewed HEAD_SHA> --delete-branch (true merge commit)
```

and

```
gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --match-head-commit <reviewed HEAD_SHA> --delete-branch
```

Change nothing else in `SKILL.md`.

2. `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`: in the opening paragraph delete the sentence ` Exit-code handling lives in SKILL.md's Phase 6.` (with its leading space), so it ends `exits non-zero.` (D15). At the end of `## Merge exit code in a worktree`, after the line ending ``meaningless until it disagrees with `gh pr view`.``, add one blank line and exactly:

```
Unmerged: re-read `headRefOid`; if it is not the reviewed `HEAD_SHA`, the head
moved; take Phase 6's unreviewed-commits stop.
```

3. `home/common/agent-skills/skills/ship-issue/REMAINDER.md`, `## Entry and start points`: replace `Phase 7's gate and fence still bind, and so` with

```
Phase 7's gate and fence still bind, with the current
selection's head as `<reviewed HEAD_SHA>`, and so
```

(the line break after `current` keeps the paragraph's wrapping).

- [ ] **Step 4: Verify**

1. The shell-example run. Expected: `OK`.
2. `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -4` (timeout 600 s). Expected: `OK`.
3. The Instruction Budget run. Expected: the output ends `check: pass` (no `lint:`, `ceiling:` or `tightness:` line).
4. The full guard-suite invocation (its `just build` is AC5 on the final tree). Expected: `OK`; `test_every_guarded_command_shape_gets_its_verdict` runs `merge.subject` and `merge.plain` with the flag bare, behind `unset GITHUB_TOKEN && ` and behind `env -u GITHUB_TOKEN `, each exit 0.
5. Scope, against the working tree: `git diff --stat <Task 3's commit> -- home/common/agent-skills/skills/ship-issue/` lists exactly `SKILL.md`, `CI-MERGE.md` and `REMAINDER.md`, and `if git diff <Task 3's commit> -- home/common/agent-skills/instruction-load.json | grep -q .; then exit 1; fi`.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/guarded-command-shapes.json home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/REMAINDER.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(ship-issue): merge pins the reviewed head with --match-head-commit (issue 402)" \
  -m "<session trailers>"
```
