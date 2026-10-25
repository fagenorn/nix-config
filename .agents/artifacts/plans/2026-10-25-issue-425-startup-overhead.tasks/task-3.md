# Task 3: The `claude-orchestrate` launcher and its installed tests

Spec § The orchestration launcher and § Test seams 2–3, per D4, D6, D8 and D10. The built Claude package gains a third script, `bin/claude-orchestrate`, beside `claude` and `claude-account`: it exports `ENABLE_CLAUDEAI_MCP_SERVERS=false` unconditionally and execs `claude-account run "$@"`, the command `claude` runs. Plain `claude` does not change. The installed module from Task 2 gains a launcher class fed the built package, and this task runs the whole installed tier that AC2 rests on.

**Files:**
- Modify: `home/common/claude-code/default.nix` (`claudeWithAccounts` and the comment above it)
- Modify: `tests/test_claude_code_installed.py` (module docstring, new constants, new class `ClaudeLaunchersInstalledTest`)
- Modify: `justfile` (recipe `agent-installed-skill-tests` and its comment)
- Modify: `home/common/claude-code/README.md` (section `## Accounts`)

**Interfaces:**
- Consumes (Task 2): `tests/test_claude_code_installed.py` with `INSTALLED_RECIPE`, `SETTINGS_ENV` and `ClaudeSettingsInstalledTest`; the recipe exporting `CLAUDE_SETTINGS_PATH` from the shell variable `$1` after its second discovery, with `installed_home` holding the home-manager-files path.
- Produces: `<the built claude-code-with-accounts package>/bin/claude-orchestrate` (Tasks 4 and 5 run it from the build output); the recipe additionally exporting `CLAUDE_CODE_PACKAGE=<the one store path in ./result's closure matching -claude-code-with-accounts-[^/]*$>`.

**Invariants:**
- `bin/claude-orchestrate` is exactly three lines: `#!${pkgs.runtimeShell}`, `export ENABLE_CLAUDEAI_MCP_SERVERS=false`, `exec ${accountsMod}/bin/claude-account run "$@"` (D4).
- `bin/claude` and `bin/claude-account` are byte-identical to their base content.
- Launched with `ENABLE_CLAUDEAI_MCP_SERVERS=true` inherited, `claude-orchestrate --version` hands the real binary `ENABLE_CLAUDEAI_MCP_SERVERS=false` and the argv `--version`; `claude --version` launched without the variable hands it none.
- Both launchers go through `claude-account run`: the binary sees `CLAUDE_ACCOUNT_LAUNCHER` and the same `CLAUDE_CODE_PLUGIN_DIRS`.
- The recipe fails before any test runs when the closure holds other than exactly one Claude package, with `expected exactly one built Claude Code package; found <n>`.

- [ ] **Step 1: Write the failing tests and wire the recipe**

In `tests/test_claude_code_installed.py`:

1. Replace the module docstring with:

```python
"""Installed seam for the generated Claude Code settings and launchers (issue 425 D6).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
generated settings artifact, found in ./result's closure as
`just show-claude-settings` finds it, as CLAUDE_SETTINGS_PATH, and the built
Claude Code package as CLAUDE_CODE_PACKAGE. Each launcher runs from that
package's bin against a stub binary named by CLAUDE_BIN, with HOME and the
working directory in a temporary directory and the calling session's account
variables removed.
"""
```

2. Extend the imports to `json`, `os`, `subprocess`, `sys`, `tempfile`, `unittest` and `from pathlib import Path`.

3. Add these constants after `EXPECTED_PLUGINS`:

```python
PACKAGE_ENV = "CLAUDE_CODE_PACKAGE"
CONNECTORS = "ENABLE_CLAUDEAI_MCP_SERVERS"
# The calling session's account state, removed so it cannot steer a launch.
ACCOUNT_VARIABLES = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_ACCOUNT",
    "CLAUDE_ACCOUNTS_DIR",
    "CLAUDE_CODE_PLUGIN_DIRS",
    "CLAUDE_ACCOUNT_LAUNCHER",
)
TIMEOUT_SECONDS = 60
# Stands in for the real binary through CLAUDE_BIN and records what it was handed.
STUB = (
    "import json, os, sys\n"
    "with open(os.environ['CLAUDE_STUB_RECORD'], 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'argv': sys.argv[1:], 'env': dict(os.environ)}, handle)\n"
)
```

4. Add this class after `ClaudeSettingsInstalledTest`:

```python
class ClaudeLaunchersInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = os.environ.get(PACKAGE_ENV)
        if package is None:
            raise unittest.SkipTest(
                f"{PACKAGE_ENV} is unset; run `{INSTALLED_RECIPE}` to check "
                "the launchers the Nix build installs"
            )
        cls.bin = Path(package) / "bin"

    def launch(self, name, extra_env):
        """Run `<package>/bin/<name> --version` against the stub; return what the stub saw."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        stub = root / "claude"
        stub.write_text(f"#!{sys.executable}\n{STUB}", encoding="utf-8")
        stub.chmod(0o755)
        record = root / "record.json"
        env = {key: value for key, value in os.environ.items()
               if key not in ACCOUNT_VARIABLES and key != CONNECTORS}
        env.update(HOME=str(root), CLAUDE_BIN=str(stub), CLAUDE_STUB_RECORD=str(record))
        env.update(extra_env)
        result = subprocess.run(
            [str(self.bin / name), "--version"], cwd=root, env=env,
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(record.read_text(encoding="utf-8"))

    def test_claude_orchestrate_turns_claude_ai_connectors_off(self):
        seen = self.launch("claude-orchestrate", {CONNECTORS: "true"})
        self.assertEqual(seen["argv"], ["--version"])
        self.assertEqual(seen["env"].get(CONNECTORS), "false")

    def test_plain_claude_leaves_claude_ai_connectors_alone(self):
        seen = self.launch("claude", {})
        self.assertEqual(seen["argv"], ["--version"])
        self.assertNotIn(CONNECTORS, seen["env"])

    def test_claude_orchestrate_launches_through_the_account_run(self):
        orchestrated = self.launch("claude-orchestrate", {})["env"]
        plain = self.launch("claude", {})["env"]
        self.assertIn("CLAUDE_ACCOUNT_LAUNCHER", orchestrated)
        self.assertIn("CLAUDE_CODE_PLUGIN_DIRS", plain)
        self.assertEqual(
            orchestrated.get("CLAUDE_CODE_PLUGIN_DIRS"), plain["CLAUDE_CODE_PLUGIN_DIRS"]
        )
```

In `justfile`, change the recipe's comment line to:

```just
# Check the skill contracts, agent-tool launchers, generated Claude settings and Claude launchers against what the Nix build installs.
```

and replace its line `    AGENT_SKILLS_INSTALLED_HOME="$installed_home" CLAUDE_SETTINGS_PATH="$1" python3 -m unittest -v \` with:

```just
    settings="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-code-with-accounts-[^/]*$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built Claude Code package; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$installed_home" CLAUDE_SETTINGS_PATH="$settings" CLAUDE_CODE_PACKAGE="$1" python3 -m unittest -v \
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the **Installed tier** (Global Constraints; timeout 3600 s).
Expected: exactly two error lines, `ERROR: test_claude_orchestrate_launches_through_the_account_run (…)` and `ERROR: test_claude_orchestrate_turns_claude_ai_connectors_off (…)` (`FileNotFoundError` naming `bin/claude-orchestrate`), then `FAILED (errors=2, skipped=1)`; `test_plain_claude_leaves_claude_ai_connectors_alone` passes.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/claude-code/default.nix`, replace the comment above `claudeWithAccounts` with:

```nix
  # `claude` on PATH starts under the account the current project is bound to,
  # for interactive and non-interactive callers alike. `claude-orchestrate` is the
  # same launch with claude.ai connectors off, for orchestration sessions (issue 425);
  # plain `claude` keeps them. All three entries are scripts, not links: the
  # launcher finds the mod relative to its own real location.
```

and its `postBuild` with:

```nix
    postBuild = ''
      rm "$out/bin/claude"
      printf '%s\n' '#!${pkgs.runtimeShell}' 'exec ${accountsMod}/bin/claude-account run "$@"' > "$out/bin/claude"
      printf '%s\n' '#!${pkgs.runtimeShell}' 'exec ${accountsMod}/bin/claude-account "$@"' > "$out/bin/claude-account"
      printf '%s\n' '#!${pkgs.runtimeShell}' 'export ENABLE_CLAUDEAI_MCP_SERVERS=false' 'exec ${accountsMod}/bin/claude-account run "$@"' > "$out/bin/claude-orchestrate"
      chmod +x "$out/bin/claude" "$out/bin/claude-account" "$out/bin/claude-orchestrate"
    '';
```

In `home/common/claude-code/README.md`, `## Accounts`, insert this paragraph directly after the paragraph that begins `` `default.nix` builds the folder into one store path (`accountsMod`) `` and before the one that begins `` In a session, `/account` lists ``. In the `` `default.nix` builds the folder `` paragraph itself, replace `and execs the pinned binary.` with `and starts the pinned binary (waiting on it, so the `/account` switch below can relaunch it).`, so it agrees with the switch paragraph and with `run`, which waits on `claude` rather than exec'ing it:

```markdown
`claudeWithAccounts` also puts `claude-orchestrate` on PATH, the command that starts an orchestration session (issue 425): a script that exports `ENABLE_CLAUDEAI_MCP_SERVERS=false`, replacing any inherited value, and execs `claude-account run "$@"`, so the account, the mod and the `/account` switch are `run`'s, and the setting survives a switch because `run` relaunches `claude --resume` from its own process. Claude Code then skips the claude.ai connector fetch for that session, so neither it nor any of its subagents carries claude.ai connector instructions or tools; other MCP servers (palmier-pro, a project's `.mcp.json`) still load, and the claude.ai-synced skills stay governed by `skillOverrides` (`## Settings`). Plain `claude` leaves the variable alone and keeps the connectors. Start an orchestration with `claude-orchestrate`, then run `/orchestrate-issues …` inside it. `tests/test_claude_code_installed.py` runs both built launchers against a stub `CLAUDE_BIN` and checks the arguments and environment each hands it.
```

- [ ] **Step 4: Verify**

Run the **Installed tier**. Expected: no `FAIL:` or `ERROR:` line, `Ran 233 tests …`, `OK (skipped=1)`. This run is AC2's check: the settings test, both launcher tests and the build of mbp.

Run in bash (timeout 600 s), from the worktree root:

```bash
set -e
pkg=$(nix-store --query --requisites ./result | grep -- '-claude-code-with-accounts-[^/]*$')
test "$(wc -l < "$pkg/bin/claude-orchestrate")" -eq 3
grep -qx 'export ENABLE_CLAUDEAI_MCP_SERVERS=false' "$pkg/bin/claude-orchestrate"
if grep -q ENABLE_CLAUDEAI "$pkg/bin/claude" "$pkg/bin/claude-account"; then exit 1; fi
```

Expected: exit 0 — the new script carries the export and the two existing launchers do not.

The anis-desktop evaluation cannot run on mbp (D10); CI's required `Nix Eval` job runs it on the PR.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix tests/test_claude_code_installed.py justfile home/common/claude-code/README.md
launch-commit … -- -m "feat(claude-code): claude-orchestrate starts a session without claude.ai connectors (issue 425)" -m "<session trailers>"
```

Verify: `git status --short -- home tests justfile` prints nothing.
