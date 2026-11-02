# Task 6: `ship-release` opens the release PR within the budget

Per D1, D9 and D18; spec §7. Read the plan root's Global Constraints first. This task has a human gate. If no offset keeps the skill's meaning within the unchanged ceilings, stop with `blocked_on: human_gate` (the user's `instruction-budget-raise` label), and do not commit a raised ceiling or a skill over budget.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md` (Phase 3, plus offsets elsewhere in the file)
- Modify: `home/common/agent-skills/tests/test_ship_release_contracts.py` (`test_skill_names_no_legacy_state`; new `test_a_missing_release_pr_is_opened_with_the_guard_form`)

**Interfaces:**
- Consumes: Task 4's `release_pr_missing` preview refusal; the guard's pr-create form `gh pr create --repo <slug> --base <base> --head <branch> --title "<title>" --body "<body>"` (`lifecycle_guard.FORM_TABLE["pr-create"]`, unchanged).
- Produces: one Phase 3 sentence. On `release_pr_missing`, open the release PR once with `gh pr create --repo <slug> --base <default> --head <integration> --title "<title>" --body "<version>"`, where `<slug>` is `bindings.tracker.repo_slug`, then re-run the same preview.

**Invariants:**
- `instruction_load check --base origin/main` passes with every `ceiling_bytes` in `home/common/agent-skills/instruction-load.json` unchanged. The `ship-release` and `release-owner` hot bytes (`SKILL.md` plus `CHANGELOG.md`) stay at or below 16,997.
- The `gh pr create` text is an inline code span in prose, not a fenced line, so the count of lines starting `release transaction ` stays 6 and no new living shell example appears.
- `CHANGELOG.md`, the evals, the description and the front matter are unchanged. Only `gh pr create` leaves the legacy list; `gh pr merge`, `gh release create`, `git tag -a` and `--auto` stay forbidden (D18).
- Every assertion of `test_ship_release_contracts.py` that is not named here passes unedited. That includes the pinned phrases "tokens from an earlier yes are never reused", "a confirmation is never carried across one" and the checkout-then-ff sentence.

- [ ] **Step 1: Write the failing test**

In `test_skill_names_no_legacy_state`, remove `"gh pr create"` from the tuple and add "(issue 554 D18: the release PR call is reinstated)" to its docstring or a comment. Add:

```python
    def test_a_missing_release_pr_is_opened_with_the_guard_form(self):
        """Issue 554 D1, D9: Phase 3 opens the release PR once, in the guard's pr-create form."""
        phase3 = self.skill.split("## Phase 3", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`release_pr_missing`", phase3)
        self.assertIn('`gh pr create --repo <slug> --base <default> --head <integration> '
                      '--title "<title>" --body "<version>"`', phase3)
        self.assertIn("bindings.tracker.repo_slug", phase3)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_ship_release_contracts.py 2>&1 | tail -4'`
Expected: FAIL in `test_a_missing_release_pr_is_opened_with_the_guard_form`.

- [ ] **Step 3: Write the minimal implementation**

Insert the sentence in Phase 3, right after the `legacy_release_in_flight` sentence and before "On `verification_pending`". Then offset its bytes by tightening existing `SKILL.md` prose without changing meaning. These three edits were measured at base to total +135 bytes:

1. Authorization: "Each irreversible action (for nix-config, `tag` and `github-release`) needs its own confirmation token." becomes "Each irreversible action needs its own confirmation token." A two-branch project adds `merge`, so the nix-config parenthesis no longer lists every action.
2. Phase 3: "The document names `candidate`, `verification`, `actions`, `confirmations` (each `{action, operation, version, commit, token}`), `runnable` and `refusal`. Exit 3 with `runnable: false` still prints it." becomes "The document names `candidate`, `verification`, `actions`, `confirmations`, `runnable` and `refusal`; exit 3 with `runnable: false` still prints it."
3. The new sentence itself.

Find at least 135 more bytes the same way: shorter wording of the same instruction, never a dropped rule. Candidates are the `legacy_release_in_flight` sentence ("Report `legacy_release_in_flight` with its detail; the user decides about the old file, which the driver never removes.") and redundant connectives in Phases 0 and 4. Measure after every edit:

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main`
Expected: `check: pass`. If no meaning-preserving offset reaches it, restore the file, stop, and report `blocked_on: human_gate` with the measured overage.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main`
Expected: `check: pass`.

Run: `if git diff --name-only e692c968 -- home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/ship-release/CHANGELOG.md | grep -q .; then exit 1; fi`
Expected: exit 0.

Run (timeout 3600 s): `just build`
Expected: exit 0 (the skill tree is installed by the build).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/tests/test_ship_release_contracts.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T6): open the release PR from ship-release" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":6,"records":[{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":10,"record_bytes":12288,"support":{"covers":["r6a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6a","last_task":6,"owner":6,"path":"home/common/agent-skills/skills/ship-release/SKILL.md"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":2,"record_bytes":3072,"support":{"covers":["r6b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6b","last_task":6,"owner":6,"path":"home/common/agent-skills/tests/test_ship_release_contracts.py"}]}}
```
