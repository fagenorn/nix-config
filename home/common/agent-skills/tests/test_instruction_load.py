"""The instruction-load model: validation, measurement, ceilings and the report command."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_tools import instruction_load


REPO_ROOT = Path(__file__).parents[4]

# A two-profile model over a small tree, read through a dict reader. Byte and
# word counts in the assertions are hand-computed from these literals.
FIXTURE_MATRIX = {
    "roles": {},
    "dispatch_sites": [
        {"id": "demo-review",
         "call": 'Agent(subagent_type="reviewer", model="opus", effort="high") reviews the demo.'},
        {"id": "demo-plugin",
         "call": 'Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports.'},
    ],
    "scenarios": {},
}
BASE_FILES = {
    "home/common/agent-skills/model-matrix.json": json.dumps(FIXTURE_MATRIX).encode(),
    "home/common/agent-skills/skills/demo/SKILL.md": b"one two three\nsee EXTRA.md and `solo`\n",
    "home/common/agent-skills/skills/demo/EXTRA.md": b"extra words here\n",
    "home/common/claude-code/skills/solo/SKILL.md": b"claude only\n",
    "home/common/claude-code/agents/reviewer.md": b"reviewer body\n",
    "home/common/agent-guidance/AGENTS.md": b"frame text\n",
}
HEAD_FILES = {
    **BASE_FILES,
    "home/common/agent-skills/skills/demo/SKILL.md":
        b"one two three four\nsee EXTRA.md, NEW.md and `solo`\n",
    "home/common/agent-skills/skills/demo/NEW.md": b"new file\n",
}


def fixture_model():
    return {
        "frame": "agent-guidance/AGENTS.md",
        "profiles": [
            {"id": "demo", "entry": "demo", "hosts": ["claude", "codex"], "prompt": None,
             "hot": ["demo/SKILL.md"],
             "conditional": ["demo/EXTRA.md", "demo/NEW.md", "solo/SKILL.md"],
             "unread": {}, "ceiling_bytes": {"claude": 51, "codex": 51},
             "note": "fixture entry"},
            {"id": "demo-reviewer", "launch": ["demo-review"], "hosts": ["claude", "codex"],
             "prompt": "demo/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [],
             "unread": {}, "ceiling_bytes": {"claude": 14, "codex": 0},
             "note": "fixture reviewer"},
        ],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
    }


def dict_reader(files):
    return lambda path: files.get(path)


class ModelCoreTest(unittest.TestCase):
    def setUp(self):
        self.model = fixture_model()
        self.files = dict(HEAD_FILES)

    def violations(self):
        return instruction_load.validate(self.model, dict_reader(self.files))

    def profile(self, profile_id):
        return next(p for p in self.model["profiles"] if p["id"] == profile_id)

    def test_the_fixture_validates_clean(self):
        self.assertEqual(self.violations(), [])

    def test_a_dropped_site_is_reported(self):
        del self.model["excluded_sites"]["demo-plugin"]
        self.assertEqual(self.violations(), ["matrix site demo-plugin is in no profile"])

    def test_a_site_claimed_twice_and_an_unknown_site_are_reported(self):
        self.model["excluded_sites"]["demo-review"] = "also excluded"
        self.model["excluded_sites"]["ghost-site"] = "not in the matrix"
        self.assertEqual(self.violations(), [
            "matrix site demo-review is claimed 2 times",
            "unknown matrix site ghost-site",
        ])

    def test_an_unknown_member_is_reported(self):
        self.profile("demo")["conditional"].append("demo/NOPE.md")
        self.assertEqual(self.violations(), ["profile demo: demo/NOPE.md resolves to no document"])

    def test_an_ambiguous_member_is_reported(self):
        self.files["home/common/claude-code/skills/demo/EXTRA.md"] = b"a second copy\n"
        self.assertEqual(self.violations(),
                         ["profile demo: demo/EXTRA.md resolves to 2 documents"])

    def test_an_unnamed_member_is_reported(self):
        self.files["home/common/agent-skills/skills/demo/LONE.md"] = b"nobody names me\n"
        self.profile("demo")["conditional"].append("demo/LONE.md")
        self.assertEqual(self.violations(), [
            "profile demo: demo/LONE.md is named by neither its prompt nor another member"])

    def test_an_agent_definition_needs_a_launch_site_of_its_type(self):
        self.profile("demo")["hot"].append("agents/reviewer.md")
        self.assertEqual(self.violations(), [
            "profile demo: agents/reviewer.md is not the subagent_type of any of its sites"])

    def test_a_named_sibling_left_unlisted_is_reported(self):
        self.profile("demo")["conditional"].remove("demo/EXTRA.md")
        self.assertEqual(self.violations(), [
            "profile demo: demo/SKILL.md names demo/EXTRA.md, which the profile does not list"])

    def test_an_unread_sibling_satisfies_closure_but_names_nothing(self):
        profile = self.profile("demo")
        profile["conditional"].remove("demo/EXTRA.md")
        profile["unread"]["demo/EXTRA.md"] = "read only on a branch this fixture never takes"
        self.assertEqual(self.violations(), [])

    def test_schema_violations_are_reported(self):
        demo = self.profile("demo")
        demo["extra"] = 1
        demo["note"] = " "
        del demo["ceiling_bytes"]["codex"]
        self.profile("demo-reviewer")["id"] = "demo"
        self.model["surplus"] = True
        self.assertEqual(self.violations(), [
            "model: unknown key 'surplus'",
            "profile demo: unknown key 'extra'",
            "profile demo: ceiling_bytes hosts ['claude'] differ from hosts ['claude', 'codex']",
            "profile demo: empty note",
            "profile demo: duplicate id",
        ])

    def test_a_member_listed_twice_is_reported(self):
        self.profile("demo")["unread"]["demo/EXTRA.md"] = "also unread"
        self.assertEqual(self.violations(), ["profile demo: demo/EXTRA.md listed more than once"])

    def test_entry_and_launch_are_exclusive_and_set_the_prompt_rule(self):
        self.profile("demo")["prompt"] = "demo/SKILL.md"
        self.profile("demo-reviewer")["prompt"] = None
        self.assertEqual(self.violations(), [
            "profile demo: an entry has no prompt",
            "profile demo-reviewer: a launch needs a prompt",
        ])

    def test_the_frame_must_resolve(self):
        del self.files["home/common/agent-guidance/AGENTS.md"]
        self.assertEqual(self.violations(),
                         ["model: frame agent-guidance/AGENTS.md resolves to no document"])

    def test_a_matrix_with_a_duplicate_key_is_reported(self):
        self.files["home/common/agent-skills/model-matrix.json"] = b'{"roles": {}, "roles": {}}'
        violations = self.violations()
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0].startswith("matrix: cannot load "), violations)

    def test_load_model_is_strict(self):
        for raw in (b'{"frame": 1, "frame": 2}', b'{"profiles": NaN}', b"[]", b"\xff"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    instruction_load.load_model(raw)

    def test_measure_counts_bytes_and_words_per_host(self):
        measurement = instruction_load.measure(self.model, dict_reader(self.files))
        demo = measurement["profiles"]["demo"]
        self.assertEqual(demo["claude"]["hot"], {"members": ["demo/SKILL.md"], "bytes": 51, "words": 9})
        self.assertEqual(demo["codex"]["hot"], {"members": ["demo/SKILL.md"], "bytes": 51, "words": 9})
        self.assertEqual(demo["claude"]["conditional"]["bytes"], 38)
        self.assertEqual(demo["claude"]["conditional"]["words"], 7)
        self.assertEqual(demo["codex"]["conditional"],
                         {"members": ["demo/EXTRA.md", "demo/NEW.md"], "bytes": 26, "words": 5})
        reviewer = measurement["profiles"]["demo-reviewer"]
        self.assertEqual(reviewer["claude"]["hot"],
                         {"members": ["agents/reviewer.md"], "bytes": 14, "words": 2})
        self.assertEqual(reviewer["codex"]["hot"], {"members": [], "bytes": 0, "words": 0})
        self.assertEqual(measurement["frame"], {"bytes": 11, "words": 2, "absent": False})

    def test_an_absent_member_measures_zero_and_is_marked(self):
        measurement = instruction_load.measure(self.model, dict_reader(BASE_FILES))
        self.assertEqual(measurement["documents"]["demo/NEW.md"],
                         {"path": None, "tree": None, "bytes": 0, "words": 0, "absent": True})

    def test_ceilings_hold_at_the_measured_values_and_break_one_byte_past(self):
        read = dict_reader(self.files)
        self.assertEqual(
            instruction_load.over_ceiling(self.model, instruction_load.measure(self.model, read)), [])
        self.files["home/common/agent-skills/skills/demo/SKILL.md"] += b" "
        grown = instruction_load.measure(self.model, dict_reader(self.files))
        self.assertEqual(instruction_load.over_ceiling(self.model, grown), [
            "profile demo on claude: hot 52 bytes exceed ceiling 51 (demo/SKILL.md 52)",
            "profile demo on codex: hot 52 bytes exceed ceiling 51 (demo/SKILL.md 52)",
        ])

    def test_the_tree_reader_matches_names_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills/demo").mkdir(parents=True)
            (root / "skills/demo/SKILL.md").write_bytes(b"body\n")
            read = instruction_load.tree_reader(root)
            self.assertEqual(read("skills/demo/SKILL.md"), b"body\n")
            self.assertIsNone(read("skills/demo/skill.md"))
            self.assertIsNone(read("skills/Demo/SKILL.md"))
            self.assertIsNone(read("skills/demo"))
            self.assertIsNone(read("skills/demo/ABSENT.md"))


if __name__ == "__main__":
    unittest.main()
