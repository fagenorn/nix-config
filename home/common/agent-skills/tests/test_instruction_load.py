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

from agent_tools import instruction_load, skill_lint


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
             "conditional_ceiling_bytes": {"claude": 38, "codex": 26},
             "note": "fixture entry"},
            {"id": "demo-reviewer", "launch": ["demo-review"], "hosts": ["claude", "codex"],
             "prompt": "demo/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [],
             "unread": {}, "ceiling_bytes": {"claude": 14, "codex": 0},
             "conditional_ceiling_bytes": {"claude": 0, "codex": 0},
             "note": "fixture reviewer"},
        ],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
        "corpus_ceiling_bytes": 181, "description_ceiling_bytes": 24,
    }


def dict_reader(files):
    return lambda path: files.get(path)


# HEAD_FILES plus a Codex skill with a description, and two files the corpus skips.
CORPUS_FILES = {
    **HEAD_FILES,
    "home/common/codex/skills/stub/SKILL.md":
        b"---\nname: stub\ndescription: Stubs. Use when testing.\n---\nstub body\n",
    "home/common/agent-skills/skills/demo/evals/evals.md": b"not counted\n",
    "home/common/claude-code/agents/notes.txt": b"not markdown\n",
}


def dict_snapshot(files):
    return skill_lint.Snapshot(
        read=files.get,
        list_files=lambda prefix: sorted(p for p in files if p.startswith(prefix + "/")),
    )


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


class CeilingTest(unittest.TestCase):
    def all_ceilings(self, model=None, files=CORPUS_FILES):
        model = model or fixture_model()
        snapshot = dict_snapshot(files)
        return instruction_load.ceilings(model, instruction_load.measure(model, snapshot.read),
                                         instruction_load.measure_corpus(snapshot))

    def test_the_corpus_counts_skill_markdown_agents_and_the_frame(self):
        # 51 + 17 + 9 (demo) + 12 (solo) + 67 (stub) + 14 (reviewer.md) + 11 (frame)
        self.assertEqual(instruction_load.measure_corpus(dict_snapshot(CORPUS_FILES)),
                         {"corpus": 181, "descriptions": 24})

    def test_a_listed_file_that_cannot_be_read_cannot_be_measured(self):
        prompt = "home/common/agent-skills/skills/demo/demo-prompt.md"
        files = {**CORPUS_FILES, prompt: b"payload\n"}
        for path in ("home/common/agent-skills/skills/demo/SKILL.md",
                     "home/common/agent-skills/skills/demo/EXTRA.md", prompt,
                     "home/common/claude-code/agents/reviewer.md"):
            with self.subTest(path=path):
                snapshot = skill_lint.Snapshot(
                    read=lambda p, path=path: None if p == path else files.get(p),
                    list_files=dict_snapshot(files).list_files,
                )
                with self.assertRaisesRegex(ValueError, re.escape(f"cannot read {path}")):
                    instruction_load.measure_corpus(snapshot)

    def test_an_absent_frame_counts_zero_bytes(self):
        # 181 less the frame's 11 bytes: the frame is read by path, not listed.
        files = {p: d for p, d in CORPUS_FILES.items()
                 if p != "home/common/agent-guidance/AGENTS.md"}
        self.assertEqual(instruction_load.measure_corpus(dict_snapshot(files)),
                         {"corpus": 170, "descriptions": 24})

    def test_every_ceiling_is_enumerated_with_its_location(self):
        rows = [(c.label, c.location, c.ceiling, c.measured) for c in self.all_ceilings()]
        self.assertEqual(instruction_load.ceiling_locations(fixture_model()), [r[1] for r in rows])
        self.assertEqual(instruction_load.ceiling_locations(
            {"profiles": [3, {"id": 1}, {"id": "x", "hosts": "claude"}]}),
            [("corpus_ceiling_bytes",), ("description_ceiling_bytes",)])
        hot, conditional = "ceiling_bytes", "conditional_ceiling_bytes"
        self.assertEqual(rows, [
            ("profile demo on claude: hot", ("profiles", "demo", hot, "claude"), 51, 51),
            ("profile demo on claude: conditional",
             ("profiles", "demo", conditional, "claude"), 38, 38),
            ("profile demo on codex: hot", ("profiles", "demo", hot, "codex"), 51, 51),
            ("profile demo on codex: conditional",
             ("profiles", "demo", conditional, "codex"), 26, 26),
            ("profile demo-reviewer on claude: hot",
             ("profiles", "demo-reviewer", hot, "claude"), 14, 14),
            ("profile demo-reviewer on claude: conditional",
             ("profiles", "demo-reviewer", conditional, "claude"), 0, 0),
            ("profile demo-reviewer on codex: hot",
             ("profiles", "demo-reviewer", hot, "codex"), 0, 0),
            ("profile demo-reviewer on codex: conditional",
             ("profiles", "demo-reviewer", conditional, "codex"), 0, 0),
            ("corpus", ("corpus_ceiling_bytes",), 181, 181),
            ("descriptions", ("description_ceiling_bytes",), 24, 24),
        ])

    def test_a_breach_of_each_new_ceiling_is_found_and_over_ceiling_stays_hot_only(self):
        files = dict(CORPUS_FILES)
        files["home/common/agent-skills/skills/demo/EXTRA.md"] += b"x"
        files["home/common/codex/skills/stub/SKILL.md"] = (
            b"---\nname: stub\ndescription: Stubs. Use when testing!!\n---\nstub body\n")
        found = instruction_load.breached(self.all_ceilings(files=files))
        self.assertEqual([c.label for c in found], [
            "profile demo on claude: conditional", "profile demo on codex: conditional",
            "corpus", "descriptions"])
        model = fixture_model()
        self.assertEqual(
            instruction_load.over_ceiling(model, instruction_load.measure(model, files.get)), [])

    def test_the_new_ceilings_are_required_and_typed(self):
        model = fixture_model()
        del model["profiles"][0]["conditional_ceiling_bytes"]
        model["profiles"][1]["conditional_ceiling_bytes"] = {"claude": -1, "codex": True}
        del model["corpus_ceiling_bytes"]
        model["description_ceiling_bytes"] = 1.5
        self.assertEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [
            "model: missing key 'corpus_ceiling_bytes'",
            "model: description_ceiling_bytes must be a non-negative integer",
            "profile demo: missing key 'conditional_ceiling_bytes'",
            "profile demo: conditional_ceiling_bytes must map hosts to byte counts",
            "profile demo-reviewer: conditional_ceiling_bytes claude must be a non-negative integer",
            "profile demo-reviewer: conditional_ceiling_bytes codex must be a non-negative integer",
        ])

    def test_conditional_ceiling_hosts_must_match_the_profile_hosts(self):
        model = fixture_model()
        del model["profiles"][0]["conditional_ceiling_bytes"]["codex"]
        self.assertEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [
            "profile demo: conditional_ceiling_bytes hosts ['claude'] differ from hosts "
            "['claude', 'codex']"])


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

    def test_a_model_from_before_the_gate_still_reports(self):
        model = fixture_model()
        for key in instruction_load.GATE_TOP_LEVEL_KEYS:
            del model[key]
        for profile in model["profiles"]:
            for key in instruction_load.GATE_PROFILE_KEYS:
                del profile[key]
        legacy = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "legacy")
        completed = self.report("--base", self.base, "--head", legacy, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["head"], legacy)
        self.assertNotEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [])

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

        # A member exactly one profile lists, so the copy yields exactly one violation.
        deepening = "home/common/agent-skills/skills/codebase-design/DEEPENING.md"
        cases = (
            ("a matrix site dropped", drop_site, live,
             "matrix site sdd-final-correctness-rereview is in no profile"),
            ("an unknown member", unknown_member, live,
             "profile research: from-issue/NOPE.md resolves to no document"),
            ("an ambiguous member", None, with_copy(deepening),
             "profile architecture-scan-owner: codebase-design/DEEPENING.md resolves to "
             "2 documents"),
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

    def test_the_live_tree_breaches_no_ceiling_of_any_kind(self):
        snapshot = skill_lint.working_tree(REPO_ROOT)
        found = instruction_load.ceilings(self.model, instruction_load.measure(self.model, self.read),
                                          instruction_load.measure_corpus(snapshot))
        self.assertEqual([c.label for c in instruction_load.breached(found)], [])

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


WORKFLOW = ".github/workflows/instruction-budget.yaml"
DEMO = "home/common/agent-skills/skills/demo/SKILL.md"
LOOSE = "home/common/agent-skills/skills/demo/LOOSE.md"
GATE_SITE = {"id": "demo-plugin", "path": DEMO,
             "call": 'Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") '
                     'transports.'}
# A lint-clean three-tree repository carrying the gate workflow; GATE_MODEL's
# ceilings are hand-counted: demo 75, solo 74, stub 74, frame 11; descriptions 31 each.
GATE_TREE = {
    "home/common/agent-skills/model-matrix.json": json.dumps(
        {"roles": {}, "dispatch_sites": [GATE_SITE], "scenarios": {}}).encode(),
    DEMO: b"---\nname: demo\ndescription: Demos things. Use when testing.\n---\nsee `solo`\n",
    "home/common/claude-code/skills/solo/SKILL.md":
        b"---\nname: solo\ndescription: Solos things. Use when testing.\n---\nsolo body\n",
    "home/common/codex/skills/stub/SKILL.md":
        b"---\nname: stub\ndescription: Stubs things. Use when testing.\n---\nstub body\n",
    "home/common/agent-guidance/AGENTS.md": b"frame text\n",
    WORKFLOW: b"name: Instruction Budget\n",
}
TIGHTEN = "run `just agent-instruction-load tighten`"
WAIVER = "revert it, or have a human apply the instruction-budget-raise label"


def gate_model():
    return {
        "frame": "agent-guidance/AGENTS.md",
        "profiles": [{"id": "demo", "entry": "demo", "hosts": ["claude", "codex"],
                      "prompt": None, "hot": ["demo/SKILL.md"], "conditional": ["solo/SKILL.md"],
                      "unread": {}, "ceiling_bytes": {"claude": 75, "codex": 75},
                      "conditional_ceiling_bytes": {"claude": 74, "codex": 0},
                      "note": "gate fixture"}],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
        "corpus_ceiling_bytes": 234,
        "description_ceiling_bytes": 93,
    }


def gate_files(model=None, extra=None, drop=()):
    files = {**GATE_TREE,
             instruction_load.MODEL_PATH: json.dumps(model or gate_model(), indent=2).encode()}
    files.update(extra or {})
    for path in drop:
        files.pop(path)
    return files


class CheckTest(unittest.TestCase):
    def check(self, head, base=None, label=False):
        return instruction_load.run_check(
            dict_snapshot(head), None if base is None else dict_snapshot(base), label)

    def found(self, files, model):
        snapshot = dict_snapshot(files)
        return instruction_load.ceilings(model, instruction_load.measure(model, snapshot.read),
                                         instruction_load.measure_corpus(snapshot))

    def test_the_tight_unchanged_tree_passes(self):
        self.assertEqual(self.check(gate_files(), gate_files()), [])
        self.assertEqual(self.check(gate_files()), [])

    def test_each_raise_fails_unlabelled_and_passes_labelled(self):
        def mutated(change):
            model = gate_model()
            change(model)
            return gate_files(model)

        def move_to_conditional(m):
            profile = m["profiles"][0]
            profile["hot"], profile["conditional"] = [], ["demo/SKILL.md", "solo/SKILL.md"]
            profile["ceiling_bytes"] = {"claude": 0, "codex": 0}
            profile["conditional_ceiling_bytes"] = {"claude": 149, "codex": 75}

        def new_profile(m):
            m["profiles"].append({
                "id": "solo", "entry": "solo", "hosts": ["claude"], "prompt": None,
                "hot": ["solo/SKILL.md"], "conditional": [], "unread": {},
                "ceiling_bytes": {"claude": 74}, "conditional_ceiling_bytes": {"claude": 0},
                "note": "a second profile"})

        model_line = (f"raise: {instruction_load.MODEL_PATH} changes more than lowering a "
                      f"ceiling; {WAIVER}")
        cases = (
            ("raised hot ceiling",
             mutated(lambda m: m["profiles"][0]["ceiling_bytes"].update(claude=76)), model_line),
            ("raised conditional ceiling",
             mutated(lambda m: m["profiles"][0]["conditional_ceiling_bytes"].update(claude=75)),
             model_line),
            ("raised corpus ceiling",
             mutated(lambda m: m.update(corpus_ceiling_bytes=235)), model_line),
            ("raised description ceiling",
             mutated(lambda m: m.update(description_ceiling_bytes=94)), model_line),
            ("hot member moved to conditional", mutated(move_to_conditional), model_line),
            ("new profile", mutated(new_profile), model_line),
            ("excluded_sites edit",
             mutated(lambda m: m["excluded_sites"].update({"demo-plugin": "reworded"})),
             model_line),
            ("gate file edited",
             gate_files(extra={WORKFLOW: b"name: Instruction Budget\n# edited\n"}),
             f"raise: gate file {WORKFLOW} differs from the base; {WAIVER}"),
            ("gate file added",
             gate_files(extra={"python/agent_tools/skill_lint.py": b"# new\n"}),
             f"raise: gate file python/agent_tools/skill_lint.py differs from the base; {WAIVER}"),
        )
        for label, head, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(self.check(head, gate_files()), [expected])
                self.assertEqual(self.check(head, gate_files(), label=True), [])

    def test_a_note_only_change_passes_unlabelled(self):
        model = gate_model()
        model["profiles"][0]["note"] = "gate fixture, reworded"
        self.assertEqual(self.check(gate_files(model), gate_files()), [])

    def test_a_note_change_beside_any_other_change_still_needs_the_label(self):
        def moved(m):
            profile = m["profiles"][0]
            profile["hot"], profile["conditional"] = [], ["demo/SKILL.md", "solo/SKILL.md"]
            profile["ceiling_bytes"] = {"claude": 0, "codex": 0}
            profile["conditional_ceiling_bytes"] = {"claude": 149, "codex": 75}

        model_line = (f"raise: {instruction_load.MODEL_PATH} changes more than lowering a "
                      f"ceiling; {WAIVER}")
        cases = (
            ("membership", moved),
            ("raised ceiling", lambda m: m["profiles"][0]["ceiling_bytes"].update(claude=76)),
            ("excluded_sites", lambda m: m["excluded_sites"].update({"demo-plugin": "reworded"})),
        )
        for label, change in cases:
            with self.subTest(case=label):
                model = gate_model()
                model["profiles"][0]["note"] = "gate fixture, reworded"
                change(model)
                self.assertEqual(self.check(gate_files(model), gate_files()), [model_line])
                self.assertEqual(self.check(gate_files(model), gate_files(), label=True), [])

    def test_a_note_on_a_new_profile_does_not_excuse_it(self):
        model = gate_model()
        renamed = gate_model()["profiles"][0]
        renamed["id"] = "demo-renamed"
        model["profiles"] = [renamed]
        model_line = (f"raise: {instruction_load.MODEL_PATH} changes more than lowering a "
                      f"ceiling; {WAIVER}")
        self.assertEqual(self.check(gate_files(model), gate_files()), [model_line])

    def test_a_lowering_only_change_passes_unlabelled(self):
        base_model = gate_model()
        base_model["profiles"][0]["ceiling_bytes"]["claude"] = 78
        base_model["corpus_ceiling_bytes"] = 240
        self.assertEqual(self.check(gate_files(), gate_files(base_model)), [])

    def test_a_base_without_the_gate_workflow_skips_raise_control(self):
        raised = gate_model()
        raised["profiles"][0]["ceiling_bytes"]["claude"] = 76
        self.assertEqual(self.check(gate_files(raised), gate_files(drop=(WORKFLOW,))), [])

    def test_a_loose_ceiling_fails_and_tighten_fixes_it_without_raising(self):
        within = gate_model()
        within["profiles"][0]["ceiling_bytes"]["claude"] = 78        # 7800 <= 105 * 75
        self.assertEqual(self.check(gate_files(within)), [])
        model = gate_model()
        model["profiles"][0]["ceiling_bytes"]["claude"] = 79         # 7900 > 105 * 75
        model["corpus_ceiling_bytes"] = 250
        self.assertEqual(self.check(gate_files(model)), [
            "tightness: profile demo on claude: hot ceiling 79 is more than 5% above its "
            f"measured 75 bytes; {TIGHTEN}",
            f"tightness: corpus ceiling 250 is more than 5% above its measured 234 bytes; {TIGHTEN}",
        ])
        tight, lowered = instruction_load.tightened(model, self.found(gate_files(model), model))
        self.assertEqual(tight, gate_model())
        self.assertEqual(lowered, ["lowered profile demo on claude: hot: 79 -> 75",
                                   "lowered corpus: 250 -> 234"])
        self.assertEqual(self.check(gate_files(tight)), [])

    def test_a_breach_survives_tighten(self):
        head = gate_files(extra={DEMO: GATE_TREE[DEMO] + b" "})
        expected = [
            "ceiling: profile demo on claude: hot measures 76 bytes, above its ceiling 75",
            "ceiling: profile demo on codex: hot measures 76 bytes, above its ceiling 75",
            "ceiling: corpus measures 235 bytes, above its ceiling 234",
        ]
        self.assertEqual([line.split(";")[0] for line in self.check(head)], expected)
        self.assertEqual(instruction_load.tightened(gate_model(), self.found(head, gate_model())),
                         (gate_model(), []))

    def test_lint_and_invalid_model_lines_carry_their_steps(self):
        self.assertEqual(self.check(gate_files(extra={LOOSE: b""})),
                         [f"lint: L4a {LOOSE}: not named in its SKILL.md"])
        broken = gate_model()
        del broken["excluded_sites"]["demo-plugin"]
        self.assertEqual(self.check(gate_files(broken)),
                         ["ceiling: invalid model: matrix site demo-plugin is in no profile"])

    def test_what_cannot_be_checked_raises(self):
        for head, base in ((gate_files(drop=(instruction_load.MODEL_PATH,)), None),
                           (gate_files(extra={instruction_load.MODEL_PATH: b"{"}), None),
                           (gate_files(), gate_files(drop=(instruction_load.MODEL_PATH,))),
                           (gate_files(), gate_files(extra={instruction_load.MODEL_PATH: b"{"}))):
            with self.subTest(head=sorted(head)[:1], base=base is not None):
                with self.assertRaises(ValueError):
                    self.check(head, base)


class CheckCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.env = git_env()
        for args in (("init", "-q", "-b", "main"), ("config", "commit.gpgsign", "false")):
            subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True)
        self.write(gate_files())
        for args in (("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True)

    def write(self, files):
        for relative, data in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.instruction_load", *args, "--root", str(self.repo)],
            env=self.env, capture_output=True, text=True, check=False)

    def test_check_exit_codes_and_the_label_flag(self):
        clean = self.run_tool("check", "--base", "HEAD")
        self.assertEqual((clean.returncode, clean.stdout), (0, "check: pass\n"), clean.stderr)
        raised = gate_model()
        raised["profiles"][0]["ceiling_bytes"]["claude"] = 76
        self.write({instruction_load.MODEL_PATH: json.dumps(raised, indent=2).encode()})
        unlabelled = self.run_tool("check", "--base", "HEAD")
        self.assertEqual(unlabelled.returncode, 1)
        self.assertTrue(unlabelled.stdout.startswith("raise: "), unlabelled.stdout)
        self.assertEqual(self.run_tool("check", "--base", "HEAD", "--raise-label").returncode, 0)
        for args in (("check", "--base", "no-such-revision"), ("check", "--raise-label")):
            with self.subTest(args=args):
                refused = self.run_tool(*args)
                self.assertEqual((refused.returncode, refused.stdout), (2, ""))
                self.assertEqual(len(refused.stderr.splitlines()), 1, refused.stderr)
                self.assertTrue(refused.stderr.startswith("agent-instruction-load: "))

    def test_tighten_lowers_in_canonical_form_and_fails_on_a_breach(self):
        model = gate_model()
        model["profiles"][0]["ceiling_bytes"]["claude"] = 79
        self.write({instruction_load.MODEL_PATH: json.dumps(model, indent=2).encode()})
        tightened = self.run_tool("tighten")
        self.assertEqual((tightened.returncode, tightened.stdout),
                         (0, "lowered profile demo on claude: hot: 79 -> 75\n"), tightened.stderr)
        self.assertEqual((self.repo / instruction_load.MODEL_PATH).read_text(encoding="utf-8"),
                         json.dumps(gate_model(), indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(self.run_tool("check", "--base", "HEAD").returncode, 0)
        self.write({DEMO: GATE_TREE[DEMO] + b" "})
        breached = self.run_tool("tighten")
        self.assertEqual(breached.returncode, 1)
        self.assertIn("breach profile demo on claude: hot: measures 76 bytes, above its "
                      "ceiling 75", breached.stdout)


class LiveBudgetTest(unittest.TestCase):
    def test_the_live_tree_passes_steps_one_to_three(self):
        self.assertEqual(
            instruction_load.run_check(skill_lint.working_tree(REPO_ROOT), None, False), [])


if __name__ == "__main__":
    unittest.main()
