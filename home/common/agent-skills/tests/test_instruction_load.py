"""The instruction-load model: validation, measurement, the corpus and the report command."""

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
         "call": 'Agent(subagent_type="codex:codex-rescue", model="sonnet", effort="medium") transports.'},
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
            {"id": "demo", "entry": "demo", "hosts": ["claude"], "prompt": None,
             "hot": ["demo/SKILL.md"],
             "conditional": ["demo/EXTRA.md", "demo/NEW.md", "solo/SKILL.md"],
             "unread": {}, "note": "fixture entry"},
            {"id": "demo-reviewer", "launch": ["demo-review"], "hosts": ["claude"],
             "prompt": "demo/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [],
             "unread": {}, "note": "fixture reviewer"},
        ],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
    }


def dict_reader(files):
    return lambda path: files.get(path)


# HEAD_FILES plus a shared skill with a description, and two files the corpus skips.
CORPUS_FILES = {
    **HEAD_FILES,
    "home/common/agent-skills/skills/stub/SKILL.md":
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
        self.profile("demo-reviewer")["id"] = "demo"
        self.model["surplus"] = True
        self.assertEqual(self.violations(), [
            "model: unknown key 'surplus'",
            "profile demo: unknown key 'extra'",
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
        self.assertEqual(demo["claude"]["conditional"]["bytes"], 38)
        self.assertEqual(demo["claude"]["conditional"]["words"], 7)
        reviewer = measurement["profiles"]["demo-reviewer"]
        self.assertEqual(reviewer["claude"]["hot"],
                         {"members": ["agents/reviewer.md"], "bytes": 14, "words": 2})
        self.assertEqual(measurement["frame"], {"bytes": 11, "words": 2, "absent": False})

    def test_an_absent_member_measures_zero_and_is_marked(self):
        measurement = instruction_load.measure(self.model, dict_reader(BASE_FILES))
        self.assertEqual(measurement["documents"]["demo/NEW.md"],
                         {"path": None, "tree": None, "bytes": 0, "words": 0, "absent": True})

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


class CorpusTest(unittest.TestCase):
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

GIT_LOCATION_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
)


def git_env():
    """Hermetic git, with no user or system config, so no signing."""
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
        self.assertEqual(demo["hosts"]["claude"]["conditional"]["delta"], {"bytes": 9, "words": 2})
        self.assertNotIn("ceiling_bytes", demo["hosts"]["claude"])
        reviewer = next(p for p in data["profiles"] if p["id"] == "demo-reviewer")
        self.assertEqual(reviewer["hosts"]["claude"]["hot"]["delta"], {"bytes": 0, "words": 0})
        self.assertFalse(reviewer["hosts"]["claude"]["hot"]["affected"])
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
        self.assertIn("| `demo/NEW.md` | claude | absent | 9 | +9 | 0 | 2 | +2 |", lines)

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
        model = fixture_model()   # carries no ceiling, as a model from before the gate did
        legacy = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "legacy")
        completed = self.report("--base", self.base, "--head", legacy, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["head"], legacy)

    def test_a_model_carrying_all_four_ceilings_still_reports_without_them(self):
        model = fixture_model()
        model["corpus_ceiling_bytes"] = 181
        model["description_ceiling_bytes"] = 24
        for profile in model["profiles"]:
            profile["ceiling_bytes"] = {"claude": 51}
            profile["conditional_ceiling_bytes"] = {"claude": 38}
        gated = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "gated")
        completed = self.report("--base", self.base, "--head", gated, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["head"], gated)
        self.assertNotIn("ceiling_bytes", completed.stdout)
        self.assertNotEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [])

    def test_a_model_naming_the_retired_codex_host_still_reports(self):
        model = fixture_model()
        for profile in model["profiles"]:
            profile["hosts"] = ["claude", "codex"]
        historical = self.commit(
            {instruction_load.MODEL_PATH: json.dumps(model).encode()}, "historical")
        completed = self.report("--base", self.base, "--head", historical, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        demo = next(p for p in json.loads(completed.stdout)["profiles"] if p["id"] == "demo")
        self.assertEqual(sorted(demo["hosts"]), ["claude", "codex"])
        self.assertIn(
            "profile demo: hosts must be a non-empty subset of ['claude']",
            instruction_load.validate(model, dict_reader(HEAD_FILES)))

    def test_an_invalid_model_at_head_exits_2(self):
        model = fixture_model()
        del model["excluded_sites"]["demo-plugin"]
        broken = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "broken")
        completed = self.report("--base", self.base, "--head", broken)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("matrix site demo-plugin is in no profile", completed.stderr)


ROSTER = {
    "orchestration-dispatcher": ["claude"],
    "release-owner": ["claude"],
    "researcher": ["claude"],
    "architecture-scan-owner": ["claude"],
    "research": ["claude"],
    "wayfind": ["claude"],
    "to-issues": ["claude"],
    "ship-release": ["claude"],
}


class LiveModelTest(unittest.TestCase):
    def setUp(self):
        self.read = instruction_load.tree_reader(REPO_ROOT)
        raw = self.read(instruction_load.MODEL_PATH)
        self.assertIsNotNone(raw, f"{instruction_load.MODEL_PATH} is missing")
        self.model = instruction_load.load_model(raw)

    def profile(self, model, profile_id):
        return next(p for p in model["profiles"] if p["id"] == profile_id)

    def test_the_committed_profiles_are_the_live_ones(self):
        self.assertEqual({p["id"] for p in self.model["profiles"]}, {
            "orchestration-dispatcher", "release-owner", "researcher", "architecture-scan-owner",
            "research", "wayfind", "to-issues", "ship-release", "design-explorer",
            "grill-explorer", "planning-explorer", "grounding-explorer"})

    def test_the_live_model_validates_clean(self):
        self.assertEqual(instruction_load.validate(self.model, self.read), [])

    # orchestrate-issues/SKILL.md, the batch profile's only hot member, measured at d65b64bf (#637).
    BATCH_BASE_HOT_BYTES = 19463

    def test_the_batch_profile_loads_deliver_batch_and_drops_15_kb(self):
        # #637 AC1: the batch profile's hot bytes drop by at least 15 KB.
        profile = self.profile(self.model, "orchestration-dispatcher")
        self.assertEqual(profile["entry"], "deliver-batch")
        self.assertEqual(profile["hot"], ["deliver-batch/SKILL.md"])
        measured = instruction_load.measure(self.model, self.read)
        hot = measured["profiles"]["orchestration-dispatcher"]["claude"]["hot"]["bytes"]
        self.assertLessEqual(hot, self.BATCH_BASE_HOT_BYTES - 15 * 1024)
        self.assertNotIn("orchestrated-" "issue-" "owner", {p["id"] for p in self.model["profiles"]})

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
            m["profiles"].remove(self.profile(m, "researcher"))

        def unknown_member(m):
            self.profile(m, "research")["conditional"].append("missing/NOPE.md")

        def unnamed_member(m):
            self.profile(m, "research")["conditional"].append("to-issues/WIDE-REFACTORS.md")

        def unlisted_sibling(m):
            self.profile(m, "to-issues")["conditional"].remove("to-issues/WIDE-REFACTORS.md")

        def unknown_key(m):
            self.profile(m, "research")["extra"] = 1

        def duplicate_id(m):
            self.profile(m, "to-issues")["id"] = "research"

        def empty_note(m):
            self.profile(m, "research")["note"] = ""

        # A member exactly one profile lists, so the copy yields exactly one violation.
        deepening = "home/common/agent-skills/skills/codebase-design/DEEPENING.md"
        cases = (
            ("a matrix site dropped", drop_site, live,
             "matrix site research-background-researcher is in no profile"),
            ("an unknown member", unknown_member, live,
             "profile research: missing/NOPE.md resolves to no document"),
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
            ("an empty note", empty_note, live, "profile research: empty note"),
        )
        for label, mutate, read, expected in cases:
            with self.subTest(mutation=label):
                model = copy.deepcopy(self.model)
                if mutate is not None:
                    mutate(model)
                self.assertEqual(instruction_load.validate(model, read), [expected])

class RetiredGateTest(unittest.TestCase):
    """Issue 1483: the growth gate is gone; only `report` reads a model that carries ceilings."""

    def test_check_and_tighten_are_gone_and_the_model_holds_no_ceiling(self):
        model = json.loads((REPO_ROOT / instruction_load.MODEL_PATH).read_bytes())
        for command in ("check", "tighten"):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.instruction_load", command],
                    cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")},
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 2, completed.stdout)
                self.assertIn("invalid choice", completed.stderr)
        self.assertEqual(set(model) & {"corpus_ceiling_bytes", "description_ceiling_bytes"}, set())
        for profile in model["profiles"]:
            with self.subTest(profile=profile["id"]):
                self.assertEqual(
                    set(profile) & {"ceiling_bytes", "conditional_ceiling_bytes"}, set())
        self.assertEqual(
            instruction_load.validate(model, instruction_load.tree_reader(REPO_ROOT)), [])

    def test_a_retired_ceiling_key_is_unknown_now_and_tolerated_in_history(self):
        model = fixture_model()
        model["corpus_ceiling_bytes"] = 1
        model["profiles"][0]["ceiling_bytes"] = {"claude": 1}
        now = instruction_load.validate(model, dict_reader(HEAD_FILES))
        old = instruction_load.validate(model, dict_reader(HEAD_FILES), historical=True)
        self.assertIn("model: unknown key 'corpus_ceiling_bytes'", now)
        self.assertIn("profile demo: unknown key 'ceiling_bytes'", now)
        self.assertEqual(old, [])


class ClaudeOnlyHostTest(unittest.TestCase):
    """#687 D1: Codex is a reviewer only, so the budget measures the Claude host alone."""

    def test_the_gate_knows_only_the_claude_host_and_trees(self):
        self.assertEqual(instruction_load.HOSTS, ("claude",))
        self.assertEqual(skill_lint.TREE_ROOTS, (skill_lint.SHARED_TREE, skill_lint.CLAUDE_TREE))
        self.assertFalse(hasattr(skill_lint, "CODEX_TREE"))

    def test_the_live_model_names_no_codex_host(self):
        model = json.loads((REPO_ROOT / instruction_load.MODEL_PATH).read_text(encoding="utf-8"))
        for profile in model["profiles"]:
            with self.subTest(profile=profile["id"]):
                self.assertEqual(profile["hosts"], ["claude"])


if __name__ == "__main__":
    unittest.main()
