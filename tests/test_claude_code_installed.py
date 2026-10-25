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
