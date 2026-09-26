"""The instruction-load model: validation, measurement, ceilings and the report command."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
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


GIT_LOCATION_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
)


def git_env():
    """Hermetic git, as test_sdd_workspace.py: no user or system config, so no signing."""
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test",
    })
    return env


class ReportCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.env = git_env()
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.base = self.commit(BASE_FILES, "base")
        self.head = self.commit({**HEAD_FILES, instruction_load.MODEL_PATH:
                                 json.dumps(fixture_model(), indent=2).encode()}, "head")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files, message):
        for relative, data in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def report(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.instruction_load", "report",
             "--root", str(self.repo), *args],
            env=self.env, capture_output=True, text=True, check=False)

    def json_report(self):
        completed = self.report("--base", self.base, "--head", self.head, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_json_reports_hand_computed_deltas(self):
        data = self.json_report()
        self.assertEqual((data["base"], data["head"]), (self.base, self.head))
        demo = next(p for p in data["profiles"] if p["id"] == "demo")
        self.assertEqual(demo["hosts"]["claude"]["hot"]["base"], {"bytes": 38, "words": 7})
        self.assertEqual(demo["hosts"]["claude"]["hot"]["head"], {"bytes": 51, "words": 9})
        self.assertEqual(demo["hosts"]["claude"]["hot"]["delta"], {"bytes": 13, "words": 2})
        self.assertTrue(demo["hosts"]["claude"]["hot"]["affected"])
        self.assertEqual(demo["hosts"]["codex"]["conditional"]["delta"], {"bytes": 9, "words": 2})
        self.assertEqual(demo["hosts"]["claude"]["conditional"]["delta"], {"bytes": 9, "words": 2})
        self.assertEqual(demo["hosts"]["claude"]["ceiling_bytes"], 51)
        reviewer = next(p for p in data["profiles"] if p["id"] == "demo-reviewer")
        self.assertEqual(reviewer["hosts"]["claude"]["hot"]["delta"], {"bytes": 0, "words": 0})
        self.assertFalse(reviewer["hosts"]["claude"]["hot"]["affected"])
        self.assertEqual(reviewer["hosts"]["codex"]["hot"]["members"], [])
        new = next(d for d in data["documents"] if d["member"] == "demo/NEW.md")
        self.assertEqual(new["base"], {"bytes": 0, "words": 0, "absent": True})
        self.assertEqual(new["head"], {"bytes": 9, "words": 2, "absent": False})
        self.assertEqual(data["frame"]["delta"], {"bytes": 0, "words": 0})

    def test_markdown_file_carries_both_shas_and_the_regeneration_command(self):
        output = Path(self.temporary.name) / "report.md"
        completed = self.report("--base", self.base, "--head", self.head, "--output", str(output))
        self.assertEqual((completed.returncode, completed.stdout), (0, ""), completed.stderr)
        text = output.read_text(encoding="utf-8")
        self.assertIn(f"`{self.base}`", text)
        self.assertIn(f"`{self.head}`", text)
        self.assertIn(f"just agent-instruction-load report --base {self.base} "
                      f"--head {self.head} --output <path>", text)
        self.assertIn("neither is a token count", text)
        for heading in ("## Frame", "## Hot totals", "## Conditional totals", "## Documents",
                        "## Members by profile", "### demo-reviewer"):
            self.assertIn(heading, text)
        lines = text.splitlines()
        self.assertIn("| demo | claude | 38 | 51 | +13 | 7 | 9 | +2 | yes | fixture entry |", lines)
        self.assertIn("| `demo/NEW.md` | claude, codex | absent | 9 | +9 | 0 | 2 | +2 |", lines)

    def test_the_output_is_a_function_of_the_two_shas(self):
        first = self.report("--base", self.base, "--head", self.head)
        (self.repo / "home/common/agent-skills/skills/demo/SKILL.md").write_bytes(b"dirty\n")
        second = self.report("--base", self.base, "--head", self.head)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(first.stdout.startswith("# Instruction load: "), first.stdout[:80])
        self.assertEqual(first.stdout, second.stdout)

    def test_the_model_is_read_at_head_not_from_the_working_tree(self):
        (self.repo / instruction_load.MODEL_PATH).write_text("{", encoding="utf-8")
        self.assertEqual(self.json_report()["head"], self.head)
        completed = self.report("--base", self.base, "--head", self.base)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(len(completed.stderr.splitlines()), 1, completed.stderr)
        self.assertIn(instruction_load.MODEL_PATH, completed.stderr)

    def test_an_unknown_revision_exits_2_and_writes_no_file(self):
        output = Path(self.temporary.name) / "never.md"
        completed = self.report("--base", "no-such-revision", "--head", self.head,
                                "--output", str(output))
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr.count("\n"), 1, completed.stderr)
        self.assertTrue(completed.stderr.startswith("agent-instruction-load: "))
        self.assertFalse(output.exists())

    def test_an_invalid_model_at_head_exits_2(self):
        model = fixture_model()
        del model["excluded_sites"]["demo-plugin"]
        broken = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "broken")
        completed = self.report("--base", self.base, "--head", broken)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("matrix site demo-plugin is in no profile", completed.stderr)


ROSTER = {
    "from-issue-controller": ["claude", "codex"],
    "orchestration-dispatcher": ["claude"],
    "orchestrated-issue-owner": ["claude"],
    "design-and-grill-owner": ["claude", "codex"],
    "planning-owner": ["claude", "codex"],
    "implementation-owner": ["claude", "codex"],
    "ship-owner": ["claude", "codex"],
    "release-owner": ["claude", "codex"],
    "researcher": ["claude", "codex"],
    "architecture-scan-owner": ["claude", "codex"],
    "research": ["claude", "codex"],
    "wayfind": ["claude", "codex"],
    "to-issues": ["claude", "codex"],
    "ship-release": ["claude", "codex"],
}
BREACH = re.compile(r"^profile (\S+) on (\S+): ")


class LiveModelTest(unittest.TestCase):
    def setUp(self):
        self.read = instruction_load.tree_reader(REPO_ROOT)
        raw = self.read(instruction_load.MODEL_PATH)
        self.assertIsNotNone(raw, f"{instruction_load.MODEL_PATH} is missing")
        self.model = instruction_load.load_model(raw)

    def profile(self, model, profile_id):
        return next(p for p in model["profiles"] if p["id"] == profile_id)

    def test_the_live_model_validates_clean(self):
        self.assertEqual(instruction_load.validate(self.model, self.read), [])

    def test_the_roster_profiles_are_modelled_on_their_hosts(self):
        hosts = {p["id"]: p["hosts"] for p in self.model["profiles"]}
        for profile_id, expected in ROSTER.items():
            with self.subTest(profile=profile_id):
                self.assertEqual(hosts.get(profile_id), expected)

    def test_each_live_mutation_yields_exactly_its_violation(self):
        live = self.read

        def with_copy(path):
            return lambda p: live(path) if p == path.replace(
                "agent-skills/skills", "claude-code/skills") else live(p)

        def drop_site(m):
            self.profile(m, "sdd-final-rereviewer")["launch"].remove("sdd-final-correctness-rereview")

        def unknown_member(m):
            self.profile(m, "research")["conditional"].append("from-issue/NOPE.md")

        def unnamed_member(m):
            self.profile(m, "research")["conditional"].append("to-issues/WIDE-REFACTORS.md")

        def unlisted_sibling(m):
            self.profile(m, "to-issues")["conditional"].remove("to-issues/WIDE-REFACTORS.md")

        def unknown_key(m):
            self.profile(m, "research")["extra"] = 1

        def duplicate_id(m):
            self.profile(m, "to-issues")["id"] = "research"

        def ceiling_host(m):
            del self.profile(m, "research")["ceiling_bytes"]["codex"]

        def empty_note(m):
            self.profile(m, "research")["note"] = ""

        sync = "home/common/agent-skills/skills/ship-issue/SYNC.md"
        cases = (
            ("a matrix site dropped", drop_site, live,
             "matrix site sdd-final-correctness-rereview is in no profile"),
            ("an unknown member", unknown_member, live,
             "profile research: from-issue/NOPE.md resolves to no document"),
            ("an ambiguous member", None, with_copy(sync),
             "profile ship-owner: ship-issue/SYNC.md resolves to 2 documents"),
            ("an unnamed member", unnamed_member, live,
             "profile research: to-issues/WIDE-REFACTORS.md is named by neither its "
             "prompt nor another member"),
            ("a named sibling left unlisted", unlisted_sibling, live,
             "profile to-issues: to-issues/SKILL.md names to-issues/WIDE-REFACTORS.md, "
             "which the profile does not list"),
            ("an unknown key", unknown_key, live, "profile research: unknown key 'extra'"),
            ("a duplicate profile id", duplicate_id, live, "profile research: duplicate id"),
            ("a ceiling host missing", ceiling_host, live,
             "profile research: ceiling_bytes hosts ['claude'] differ from hosts "
             "['claude', 'codex']"),
            ("an empty note", empty_note, live, "profile research: empty note"),
        )
        for label, mutate, read, expected in cases:
            with self.subTest(mutation=label):
                model = copy.deepcopy(self.model)
                if mutate is not None:
                    mutate(model)
                self.assertEqual(instruction_load.validate(model, read), [expected])

    def test_the_live_tree_breaches_no_ceiling(self):
        measurement = instruction_load.measure(self.model, self.read)
        self.assertEqual(instruction_load.over_ceiling(self.model, measurement), [])

    def test_growing_a_hot_member_breaches_exactly_the_pairs_that_count_it(self):
        measurement = instruction_load.measure(self.model, self.read)
        for member in ("from-issue/AUTO.md", "agents/reviewer.md"):
            with self.subTest(member=member):
                counting = {
                    (profile["id"], host)
                    for profile in self.model["profiles"] for host in profile["hosts"]
                    if member in measurement["profiles"][profile["id"]][host]["hot"]["members"]
                }
                self.assertTrue(counting)
                slack = max(
                    self.profile(self.model, pid)["ceiling_bytes"][host]
                    - measurement["profiles"][pid][host]["hot"]["bytes"]
                    for pid, host in counting)
                path = measurement["documents"][member]["path"]
                grown = lambda p, path=path, extra=b" " * (slack + 1): (
                    self.read(p) + extra if p == path else self.read(p))
                breaches = instruction_load.over_ceiling(
                    self.model, instruction_load.measure(self.model, grown))
                self.assertEqual({BREACH.match(b).groups() for b in breaches}, counting)


if __name__ == "__main__":
    unittest.main()
