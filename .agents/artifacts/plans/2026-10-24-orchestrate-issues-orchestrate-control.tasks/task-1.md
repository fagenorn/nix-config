# Task 1: Whole-allow `orchestrate-control`

Spec § Permission surface and the shell-example contract, per D5 and D14. `orchestrate-control` joins the permission allow list (bare and by its `~/.agents/bin` path) and the shell-example command vocabulary, so a `step` call fed by a quoted heredoc is a sanctioned lifecycle call, the same way `ship-delivery` became one (commit b89c6dbb). The skill does not change in this task.

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `permissions.allow` list and the comment above `permissions`)
- Modify: `home/common/claude-code/README.md` (the allow-surface sentence of `## Allow surface and lifecycle guard`)
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py` (`COMMAND_VOCABULARY`, a new `ORCHESTRATE_STEP_CALL`, one row of `LifecycleHelperCallTest.test_sanctioned_calls_yield_nothing_in_every_region`)
- Test: `tests/test_claude_permission_guard.py` (`EXPECTED_ALLOW`, one row of `test_single_command_lifecycle_calls_pass_the_guard`)

**Interfaces:**
- Consumes: nothing from another task.
- Produces: `orchestrate-control` in `LIFECYCLE_HELPERS` (read from `default.nix` by `whole_allowed_helpers`) and in `COMMAND_VOCABULARY`. Task 2's `step` example in a `text` fence is vetted only with both.

**Invariants:**
- The allow list gains exactly `"Bash(orchestrate-control:*)"` and `"Bash(~/.agents/bin/orchestrate-control:*)"`, in that order, right after `"Bash(~/.agents/bin/ship-delivery:*)"` and before `"Agent"`; no other entry changes, and `ask` and `deny` stay empty.
- `lifecycle_guard.py` is untouched; the guard's adversarial table stays green.
- The settings allow surface is 26 entries.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_shell_example_contracts.py`:

1. In `COMMAND_VOCABULARY`, replace `"mv", "nix", "nixos-rebuild", "node", "npm", "pnpm", "printf", "pytest",` with `"mv", "nix", "nixos-rebuild", "node", "npm", "orchestrate-control", "pnpm", "printf", "pytest",`.
2. Directly above the line `# The same call with its delimiter double-quoted: still sanctioned (per D23, D27).`, insert:

```python
# orchestrate-issues' `step` call: one whole-allowed helper fed by a quoted
# heredoc (#404 D5).
ORCHESTRATE_STEP_CALL = """orchestrate-control step --repo-root <ledger_repo_root> --input - <<'EOF'
{"session": <session>, "first_sweep": <first_sweep>, "owners": <owners>, "contracts_due": <contracts_due>, "refused_contracts": <refused_contracts>}
EOF"""
```

3. In `LifecycleHelperCallTest.test_sanctioned_calls_yield_nothing_in_every_region`, replace the last tuple row `("double-quoted delimiter", DQUOTED_CHECKPOINT_CALL)):` with:

```python
                           ("double-quoted delimiter", DQUOTED_CHECKPOINT_CALL),
                           ("orchestrate step", ORCHESTRATE_STEP_CALL)):
```

In `tests/test_claude_permission_guard.py`:

1. In `EXPECTED_ALLOW`, replace `"Bash(ship-delivery:*)", "Bash(~/.agents/bin/ship-delivery:*)", "Agent",` with:

```python
    "Bash(ship-delivery:*)", "Bash(~/.agents/bin/ship-delivery:*)",
    "Bash(orchestrate-control:*)", "Bash(~/.agents/bin/orchestrate-control:*)", "Agent",
```

2. In `test_single_command_lifecycle_calls_pass_the_guard`, add this command after the `ship-delivery checkpoint` one (inside the same tuple):

```python
            "orchestrate-control step --repo-root /r --input - <<'JSON'\n"
            '{"session":{},"first_sweep":true,"owners":[],"contracts_due":[],'
            '"refused_contracts":[]}\nJSON',
```

- [ ] **Step 2: Run the shell-example test and watch it fail**

Run (timeout 900 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py -k test_sanctioned_calls_yield_nothing_in_every_region`
Expected: FAIL — three subtests, `call='orchestrate step'` in the `bash fence`, `bare fence` and `text fence` regions, each reporting a `heredoc` finding, because `orchestrate-control` is not yet whole-allowed. (The guard suite needs a build; it runs in Step 4.)

- [ ] **Step 3: Allow the helper and say so**

In `home/common/claude-code/default.nix`, insert after the line `        "Bash(~/.agents/bin/ship-delivery:*)"`:

```nix
        "Bash(orchestrate-control:*)"
        "Bash(~/.agents/bin/orchestrate-control:*)"
```

Replace the three comment lines that begin `    # The two lifecycle helpers are allowed whole, bare and by their ~/.agents/bin path:` with:

```nix
    # The lifecycle helpers workflow-state, artifact-budget, ship-delivery and orchestrate-control
    # are allowed whole, bare and by their ~/.agents/bin path: their only writes are validated
    # ledger transitions under .superpowers/workflows/ (orchestrate-control's through its
    # workflow-state children), and every lifecycle call is one heredoc-fed command, so each
    # pipeline segment matches a rule.
```

In `home/common/claude-code/README.md`, replace this text (it occurs once):

```text
its 24-entry allow surface allows the lifecycle helpers `workflow-state`, `artifact-budget` and `ship-delivery` outright,
```

with:

```text
its 26-entry allow surface allows the lifecycle helpers `workflow-state`, `artifact-budget`, `ship-delivery` and `orchestrate-control` outright,
```

Nothing else in that paragraph changes.

- [ ] **Step 4: Verify**

Run (timeout 900 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK (skipped=1)`; no failure names `orchestrate step`.

Write this script to `<scratch>/i404/guard-suite.sh` (scratch from `launch-scope scratch …`) and run it (timeout 3600 s; it builds first): `bash <scratch>/i404/guard-suite.sh <scratch>/i404/logs`.

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

Expected: exit 0, ending in `Ran <n> tests in <t>s` and `OK`. A failure of the allow-tuple test means the built settings' `permissions.allow` differs from `EXPECTED_ALLOW`: fix the `default.nix` entry order, never the assertion.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix home/common/claude-code/README.md \
  home/common/agent-skills/tests/test_shell_example_contracts.py tests/test_claude_permission_guard.py
launch-commit … -- -m "feat(claude-code): whole-allow orchestrate-control (#404)" -m "<session trailers>"
```
