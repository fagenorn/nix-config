# Task 3: Allow `verification-observe` in the Claude permission surface

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `permissions.allow` list and the comment above `permissions`)
- Modify: `home/common/claude-code/README.md` (one clause of the long line that starts `` Use `just show-claude-settings` ``)
- Modify: `tests/test_claude_permission_guard.py` (`EXPECTED_ALLOW` and `test_single_command_lifecycle_calls_pass_the_guard`)

**Interfaces:**
- Consumes: Task 2's command `verification-observe` and its installed launcher `~/.agents/bin/verification-observe`.
- Produces: the built settings' `permissions.allow`, 28 entries, with the two adapter entries right after the `orchestrate-control` pair and before `"Agent"` (D9).

**Invariants:**
- `home/common/claude-code/lifecycle_guard.py`, its base policy, every skill and guidance document and `home/common/agent-skills/tests/test_shell_example_contracts.py` are unchanged (D9; no instruction ceiling moves).
- The guard suite runs only against the built settings and base policy; a failing allow-surface test is fixed in `default.nix`'s order, never in the assertion.

- [ ] **Step 1: Write the failing test changes** in `tests/test_claude_permission_guard.py`

In `EXPECTED_ALLOW`, replace the line

```python
    "Bash(orchestrate-control:*)", "Bash(~/.agents/bin/orchestrate-control:*)", "Agent",
```

with

```python
    "Bash(orchestrate-control:*)", "Bash(~/.agents/bin/orchestrate-control:*)",
    "Bash(verification-observe:*)", "Bash(~/.agents/bin/verification-observe:*)", "Agent",
```

In `test_single_command_lifecycle_calls_pass_the_guard`, add this item after the `orchestrate-control step` item, as the tuple's last:

```python
            "verification-observe observe --repo-root /r --input - <<'JSON'\n"
            '{"kind":"verification","blocker_id":"sha256:' + "0" * 64 + '",'
            '"sources":[{"name":"flake-lock","paths":["flake.lock"]}]}\nJSON',
```

- [ ] **Step 2: Run the guard suite against the build and watch it fail**

Write this script to `<scratch>/i543/guard-suite.sh`, `<scratch>` being the root `launch-scope scratch …` prints, and run it from the worktree root (timeout 3600 s; it builds first): `bash <scratch>/i543/guard-suite.sh <scratch>/i543/logs`.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Full logs stay in the log dir; a failing step prints its whole log, a passing one its tail.
LOG="${1:?usage: guard-suite.sh <log dir>}"; mkdir -p "$LOG"
run_logged() { local name=$1; shift; if ! "$@" >"$LOG/$name.log" 2>&1; then cat "$LOG/$name.log"; echo "$name failed; full log: $LOG/$name.log"; exit 1; fi; }
run_logged build just build
tail -3 "$LOG/build.log"
REQ=$(nix-store --query --requisites ./result)
SETTINGS=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$')
BASE=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$')
test "$(printf '%s\n' "$SETTINGS" | wc -l)" -eq 1
test "$(printf '%s\n' "$BASE" | wc -l)" -eq 1
run_logged guard-suite env CLAUDE_SETTINGS_PATH="$SETTINGS" CLAUDE_GUARD_BASE_POLICY_PATH="$BASE" \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py
tail -4 "$LOG/guard-suite.log"
```

Expected: exit 1, the guard-suite log failing `test_generated_allow_surface_is_exact_and_ordered` (the built list still has 26 entries) while the new `verification-observe` subtest passes.

- [ ] **Step 3: Allow the adapter**

`home/common/claude-code/default.nix`: after `"Bash(~/.agents/bin/orchestrate-control:*)"` add the two entries `"Bash(verification-observe:*)"` and `"Bash(~/.agents/bin/verification-observe:*)"`, in that order and before `"Agent"`. In the comment above `permissions = {`, replace its last line, `    # pipeline segment matches a rule.`, with these two lines:

```nix
    # pipeline segment matches a rule. The verification-observe adapter is allowed the same way:
    # its only write is fetching the integration branch into refs/remotes/origin/<branch>.
```

`home/common/claude-code/README.md`: in the line that starts `` Use `just show-claude-settings` ``, replace `` its 26-entry allow surface allows the lifecycle helpers `workflow-state`, `artifact-budget`, `ship-delivery` and `orchestrate-control` outright `` with `` its 28-entry allow surface allows the lifecycle helpers `workflow-state`, `artifact-budget`, `ship-delivery` and `orchestrate-control`, and the `verification-observe` adapter, outright ``. Nothing else in that line changes.

- [ ] **Step 4: Verify**

Run the Step 2 script again with a fresh log dir: `bash <scratch>/i543/guard-suite.sh <scratch>/i543/logs-green` (timeout 3600 s).
Expected: exit 0, the build's tail, and the guard suite ending `Ran <n> tests` and `OK`.

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3'`
Expected: `Ran 34 tests` and `OK (skipped=1)`, as at base (that suite reads the allow list).

Run: `grep -c '28-entry allow surface' home/common/claude-code/README.md; if git diff --quiet 328f08daca0cd21e71a622f98c91c3f3a7a6728c -- home/common/claude-code/lifecycle_guard.py; then echo unchanged; else exit 1; fi`
Expected: `1` and `unchanged`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix home/common/claude-code/README.md \
  tests/test_claude_permission_guard.py
launch-commit … -- -m "feat(claude-code): allow verification-observe (issue 543)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":1,"record_bytes":6144,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"home/common/claude-code/default.nix"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":32768,"support":{"covers":["r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"home/common/claude-code/README.md"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":1,"record_bytes":8192,"support":{"covers":["r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":3,"owner":3,"path":"tests/test_claude_permission_guard.py"}]}}
```
