"""Installed seam for the generated Claude Code settings and launchers (issue 425 D6).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
generated settings artifact, found in ./result's closure as
`just show-claude-settings` finds it, as CLAUDE_SETTINGS_PATH, and the built
Claude Code package as CLAUDE_CODE_PACKAGE. Each launcher runs from that
package's bin against a stub binary named by CLAUDE_BIN, with HOME and the
working directory in a temporary directory and the calling session's account
variables removed.
"""

import json
import os
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
