# Task 8: Auto-mode allow rules for the lifecycle helpers

Decisions: D18, D21, D22. Spec §8.

**Files:**
- Modify: `home/common/claude-code/default.nix` (`permissions.allow`, its comment)
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `CLAUDE.md` (the allow-surface sentence)

**Interfaces:**
- Consumes: Task 7's single-command lifecycle calls (heredoc on stdin, optional
  `| artifact-budget validate-report --input -`).
- Produces: the generated `permissions.allow`, 22 entries in this order: the 17
  existing `Bash(...)` rules, then `Bash(workflow-state:*)`,
  `Bash(~/.agents/bin/workflow-state:*)`, `Bash(artifact-budget:*)`,
  `Bash(~/.agents/bin/artifact-budget:*)`, then `Agent` last.

**Invariants:**
- The `PreToolUse` lifecycle guard is untouched; every existing adjudication test
  passes unchanged (AC5.2).
- `defaultMode` stays `auto`; `ask` and `deny` stay empty.
- A heredoc-fed helper call piped through `artifact-budget` is not a guarded verb:
  the guard passes it (exit 0), so only the allow rules decide it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_claude_permission_guard.py`, replace the tail of `EXPECTED_ALLOW`:

```python
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)",
    "Bash(workflow-state:*)", "Bash(~/.agents/bin/workflow-state:*)",
    "Bash(artifact-budget:*)", "Bash(~/.agents/bin/artifact-budget:*)", "Agent",
]
```

and add beside `test_unrelated_bash_and_exact_branch_delete_pass`:

```python
    def test_single_command_lifecycle_calls_pass_the_guard(self):
        for command in (
            "workflow-state control --repo-root /r --run-id run --request-file - <<'JSON' "
            "| artifact-budget validate-report --boundary workflow-response --input -\n"
            '{"interface_version": 2}\nJSON',
            "artifact-budget validate-report --boundary ship-summary --input - <<'JSON' "
            "| ~/.agents/bin/workflow-state finish --repo-root /r --run-id run "
            "--now 2026-09-24T00:00:00Z --summary-file -\n{}\nJSON",
        ):
            with self.subTest(command=command.split()[0]):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run:
```bash
SETTINGS_JSON="${TMPDIR:-/tmp}/issue171-settings.json"
just show-claude-settings > "$SETTINGS_JSON"
CLAUDE_SETTINGS_PATH="$SETTINGS_JSON" python3 tests/test_claude_permission_guard.py 2>&1 | tail -5
```
Expected: FAIL in `test_generated_allow_surface_is_exact_and_ordered` (18 entries
generated, 22 expected); the new pass-through test already passes, which pins the
guard's existing heredoc handling rather than adding behavior.

- [ ] **Step 3: Implement**

In `home/common/claude-code/default.nix`, insert the four entries after
`"Bash(gh pr merge:*)"` and before `"Agent"`, and extend the comment above
`permissions` with: "The two lifecycle helpers are allowed whole, bare and by
their ~/.agents/bin path: their only writes are validated ledger transitions under
.superpowers/workflows/, and every lifecycle call is one heredoc-fed command, so
each pipeline segment matches a rule." In `CLAUDE.md`, change "its 18-entry allow
surface hands four lifecycle verbs to a fail-closed `PreToolUse` hook." to "its
22-entry allow surface allows the two lifecycle helpers `workflow-state` and
`artifact-budget` outright, bare and as `~/.agents/bin/…`, and hands four
lifecycle verbs to a fail-closed `PreToolUse` hook."

- [ ] **Step 4: Verify**

Run: `just build 2>&1 | tail -3` → exit 0.
Run (fresh settings): the three Step-2 commands → all tests pass, no failures.
Run: `just show-claude-settings | jq -e '(.permissions.allow | length) == 22 and .permissions.defaultMode == "auto" and (.permissions.ask | length) == 0 and (.permissions.deny | length) == 0'` → `true`.
Run: `if grep -q "18-entry allow surface" CLAUDE.md; then exit 1; fi` → exit 0.
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`. Remove the scratch settings file.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix tests/test_claude_permission_guard.py CLAUDE.md
git commit -m "feat(claude-code): allow the lifecycle helpers under auto mode"
```
