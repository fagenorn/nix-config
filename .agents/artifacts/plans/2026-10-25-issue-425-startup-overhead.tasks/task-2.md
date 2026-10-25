# Task 2: Hidden skills in the generated settings and the installed settings test

Spec § Hidden skills and § Test seams 2, per D1, D2, D6 and D8. The generated `~/.claude/settings.json` gains a `skillOverrides` map that hides twelve skills from the model's skill listing while `/<name>` still runs each one. A new installed-tier module checks the built settings artifact, the one `just show-claude-settings` prints, and `just agent-installed-skill-tests` finds that artifact and hands it to the module.

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `settings` attrset)
- Create: `tests/test_claude_code_installed.py`
- Modify: `justfile` (recipe `agent-installed-skill-tests` and its comment)
- Modify: `home/common/claude-code/README.md` (section `## Settings`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Task 3 extends both): the module `tests/test_claude_code_installed.py` with constants `INSTALLED_RECIPE = "just agent-installed-skill-tests"` and `SETTINGS_ENV = "CLAUDE_SETTINGS_PATH"` and class `ClaudeSettingsInstalledTest`; the recipe `agent-installed-skill-tests` exporting `CLAUDE_SETTINGS_PATH=<the one store path in ./result's closure ending in -claude-code-settings.json>` to its `python3 -m unittest` run, which lists `tests/test_claude_code_installed.py` last.

**Invariants:**
- `skillOverrides` is exactly the twelve keys below, each `"user-invocable-only"`, and no other key (D1).
- `enabledPlugins` stays `{"skill-creator@claude-plugins-official": true, "codex@nix-codex": true}` (D2).
- No other `settings` key changes: `jq -S 'del(.skillOverrides)'` of the built artifact equals `jq -S .` of the base build's artifact.
- The recipe fails, before running any test, when `./result`'s closure holds other than exactly one settings artifact, with the message `expected exactly one generated Claude settings artifact; found <n>` (the `show-claude-settings` wording).
- The module skips, never fails, when `CLAUDE_SETTINGS_PATH` is unset.

- [ ] **Step 1: Write the failing test and wire the recipe**

Create `tests/test_claude_code_installed.py`:

```python
"""Installed seam for the generated Claude Code settings (issue 425 D6).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
generated settings artifact, found in ./result's closure as
`just show-claude-settings` finds it, as CLAUDE_SETTINGS_PATH.
"""

import json
import os
import unittest
from pathlib import Path

INSTALLED_RECIPE = "just agent-installed-skill-tests"
SETTINGS_ENV = "CLAUDE_SETTINGS_PATH"
# Hidden from the model's skill listing while /<name> still runs it (issue 425 D1).
HIDDEN = "user-invocable-only"
EXPECTED_SKILL_OVERRIDES = {
    "artifact-design": HIDDEN,
    "artifact-diagramming": HIDDEN,
    "artifact-capabilities": HIDDEN,
    "dataviz": HIDDEN,
    "anthropic-skills:docx": HIDDEN,
    "anthropic-skills:pptx": HIDDEN,
    "anthropic-skills:xlsx": HIDDEN,
    "anthropic-skills:pdf": HIDDEN,
    "anthropic-skills:google-workspace": HIDDEN,
    "anthropic-skills:morning": HIDDEN,
    "anthropic-skills:import-memory": HIDDEN,
    "anthropic-skills:skill-creator": HIDDEN,
}
# The plugin's skill-creator is the copy kept listed (issue 425 D2).
EXPECTED_PLUGINS = {
    "skill-creator@claude-plugins-official": True,
    "codex@nix-codex": True,
}


class ClaudeSettingsInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get(SETTINGS_ENV)
        if path is None:
            raise unittest.SkipTest(
                f"{SETTINGS_ENV} is unset; run `{INSTALLED_RECIPE}` to check "
                "the settings the Nix build generates"
            )
        cls.settings = json.loads(Path(path).read_text(encoding="utf-8"))

    def test_skill_overrides_hide_exactly_the_listed_skills(self):
        self.assertEqual(self.settings.get("skillOverrides"), EXPECTED_SKILL_OVERRIDES)

    def test_the_kept_skill_creator_is_the_plugin_copy(self):
        self.assertEqual(self.settings.get("enabledPlugins"), EXPECTED_PLUGINS)


if __name__ == "__main__":
    unittest.main()
```

In `justfile`, replace the comment line above `agent-installed-skill-tests` and the recipe body with exactly this (two-space recipe indentation as today):

```just
# Check the skill contracts, agent-tool launchers and generated Claude settings against what the Nix build installs.
agent-installed-skill-tests: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    installed_home="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-code-settings\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one generated Claude settings artifact; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$installed_home" CLAUDE_SETTINGS_PATH="$1" python3 -m unittest -v \
      home/common/agent-skills/tests/test_dispatch_contracts.py \
      home/common/agent-skills/tests/test_shell_example_contracts.py \
      home/common/agent-skills/tests/test_workflow_skill_contracts.py \
      tests/test_agent_tools_launchers.py \
      tests/test_promotion_installed.py \
      tests/test_impeccable_installed.py \
      tests/test_claude_code_installed.py
```

- [ ] **Step 2: Run the tests and watch one fail**

Run the **Installed tier** (Global Constraints; timeout 3600 s).
Expected: exactly one failure line, `FAIL: test_skill_overrides_hide_exactly_the_listed_skills (…ClaudeSettingsInstalledTest…)`, then `FAILED (failures=1, skipped=1)`. `test_the_kept_skill_creator_is_the_plugin_copy` passes: it pins today's plugins.

Also run (timeout 600 s): `bash -c 'set -o pipefail; env -u CLAUDE_SETTINGS_PATH python3 -m unittest tests/test_claude_code_installed.py 2>&1 | tail -1'`. Expected: `OK (skipped=…)`.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/claude-code/default.nix`, inside `settings`, directly above the comment `# Plugins + their marketplaces, declared so the setup is portable to a fresh machine.`, add:

```nix
    # Hidden from the model's skill listing, each still runnable as /<name> (issue 425):
    # skills synced from claude.ai by their full `anthropic-skills:` name, which Claude
    # Code matches before the bare one, bundled skills by their bare name. A plugin's
    # skills ignore this map, so the skill-creator kept listed is the plugin's (below).
    skillOverrides = lib.genAttrs [
      "artifact-design"
      "artifact-diagramming"
      "artifact-capabilities"
      "dataviz"
      "anthropic-skills:docx"
      "anthropic-skills:pptx"
      "anthropic-skills:xlsx"
      "anthropic-skills:pdf"
      "anthropic-skills:google-workspace"
      "anthropic-skills:morning"
      "anthropic-skills:import-memory"
      "anthropic-skills:skill-creator"
    ] (_: "user-invocable-only");
```

`lib` is already a module argument of that file.

In `home/common/claude-code/README.md`, add this paragraph to `## Settings`, after its existing paragraph (the one about `BASH_MAX_TIMEOUT_MS`) and before `## Allow surface and lifecycle guard`:

```markdown
`skillOverrides` hides twelve skills from the model's skill listing, each set to `user-invocable-only`, so `/<name>` still runs it (issue 425): the bundled `artifact-design`, `artifact-diagramming`, `artifact-capabilities` and `dataviz`, keyed by their bare names, and the claude.ai-synced `docx`, `pptx`, `xlsx`, `pdf`, `google-workspace`, `morning`, `import-memory` and `skill-creator`, keyed by their full `anthropic-skills:<name>` names. Claude Code matches a synced skill's full name before its bare one, so a user or project skill that shares a bare name stays listed. A plugin's skills ignore user-level overrides and leave the listing only when their plugin is disabled, so the skill-creator kept listed is the plugin's `skill-creator:skill-creator` and the hidden one is the claude.ai copy. The three Artifact skills are registered only in sessions that have the Artifact tool, so their entries take effect only there. `tests/test_claude_code_installed.py`, run by `just agent-installed-skill-tests`, checks the map and `enabledPlugins` in the built settings.
```

- [ ] **Step 4: Verify**

Run the **Installed tier**. Expected: no `FAIL:` or `ERROR:` line, `Ran 230 tests …`, `OK (skipped=1)`.

Run in bash (timeout 600 s), from the worktree root, with `BASE_SETTINGS` set to the settings path the Step 2 build discovered (record it before Step 3 with `nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$'`; at base it is `/nix/store/ccl01gcf03cl47s8g2ymxvvcyjldp0yz-claude-code-settings.json`, and Task 1 does not change it):

```bash
set -e
new=$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')
test "$(jq -c '.skillOverrides | length' "$new")" = 12
diff <(jq -S 'del(.skillOverrides)' "$new") <(jq -S . "$BASE_SETTINGS")
```

Expected: exit 0 and no `diff` output — the map holds twelve entries and nothing else in the settings changed.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix tests/test_claude_code_installed.py justfile home/common/claude-code/README.md
launch-commit … -- -m "feat(claude-code): hide twelve skills from the model's listing (issue 425)" -m "<session trailers>"
```

Verify: `git status --short -- home tests justfile` prints nothing.
