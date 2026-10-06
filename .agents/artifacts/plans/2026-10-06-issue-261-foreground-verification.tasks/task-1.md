# Task 1: Raise the Bash timeout ceiling

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `settings.env` attrset, currently only `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1";`)
- Modify: `CLAUDE.md` (the `~/.claude/settings.json` bullet of the Claude Code section)
- Test: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the generated `settings.json` carries `env.BASH_MAX_TIMEOUT_MS == "3600000"`. Later tasks' prose relies on an explicit timeout up to 60 minutes being expressible once this is switched in.

**Invariants:**
- `env.BASH_MAX_TIMEOUT_MS` is the string `"3600000"` and is at least 30 minutes (per D2).
- `env.BASH_DEFAULT_TIMEOUT_MS` is absent (per D2).
- `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` stays `"1"`.
- The pin lives in the built-settings test, never in a grep of Nix source (per D7).

- [ ] **Step 1: Write the failing test**

Add to `ClaudePermissionGuardTest`, directly after `test_generated_allow_surface_is_exact_and_ordered`:

```python
    def test_bash_timeout_ceiling_is_raised_and_the_default_left_alone(self):
        # #261 D2: an explicit foreground timeout must be able to cover the
        # longest verification command; the 120 s default stays the host's.
        env = self.settings.get("env", {})
        self.assertEqual(env.get("BASH_MAX_TIMEOUT_MS"), "3600000")
        self.assertGreaterEqual(int(env["BASH_MAX_TIMEOUT_MS"]), 30 * 60 * 1000)
        self.assertNotIn("BASH_DEFAULT_TIMEOUT_MS", env)
        self.assertEqual(env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"), "1")
```

- [ ] **Step 2: Run it and watch it fail**

The live `~/.claude/settings.json` is a copy of the current generated surface and lacks the key, so it serves as the red artifact without a build:

Run: `CLAUDE_SETTINGS_PATH="$HOME/.claude/settings.json" python3 -m unittest tests/test_claude_permission_guard.py -k bash_timeout 2>&1 | tail -5`
Expected: FAIL — `None != '3600000'`.

- [ ] **Step 3: Implement**

In `home/common/claude-code/default.nix`, the `env` attrset becomes exactly:

```nix
    env = {
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1";
      # Ceiling for an explicit Bash timeout (60 min), so a long verification
      # command can run in the foreground; the 120 s default is unchanged (#261).
      BASH_MAX_TIMEOUT_MS = "3600000";
    };
```

In `CLAUDE.md`, append this sentence to the end of the bullet that begins `` - `~/.claude/settings.json` is generated from the `settings` attrset``:

> Its `env` sets `BASH_MAX_TIMEOUT_MS` to `3600000` (60 minutes), the ceiling for an explicit Bash timeout, so an agent can run `just build` or `just agent-workflow-tests` in the foreground under a timeout above its duration (#261); `BASH_DEFAULT_TIMEOUT_MS` is left unset, so a command with no explicit timeout keeps the host's 120 s default.

- [ ] **Step 4: Verify against the built artifact**

`just show-claude-settings` builds first (up to 15 minutes). Run it in the foreground with Bash timeout 1800000 (above the expected duration) when the session runs under the raised `BASH_MAX_TIMEOUT_MS` (per D12), otherwise the pre-#261 host maximum 600000; if the host moves it to the background, wait for the log's `exit=` line within the same turn and never end the turn while it runs:

```bash
s="${TMPDIR:-/tmp}/settings-261.json"; log="${TMPDIR:-/tmp}/settings-261.log"
{ just show-claude-settings > "$s"; echo "exit=$?"; } > "$log" 2>&1; tail -3 "$log"
CLAUDE_SETTINGS_PATH="$s" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
```

Expected: the log ends `exit=0`; the suite reports `OK` with the new test included (it failed in Step 2, so a passing run here could not be a no-op). Then `rm -f "$s" "$log"`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix CLAUDE.md tests/test_claude_permission_guard.py
launch-commit <Lifecycle worker values> -- -m "feat(claude-code): raise the Bash timeout ceiling to 60 minutes (#261)" -m "<trailers>"
```
