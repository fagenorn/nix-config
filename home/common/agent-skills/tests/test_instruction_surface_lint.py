"""The instruction surface enforcer: a surface over its platform budget may not grow (standard:B25).

Each case builds a small repository, commits a base and a branch, and judges them
through the never-rise check or the enforcer's own command. Byte counts are read
back from the old gate's own measuring functions, never from the code under test.
"""

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools import instruction_load
from agent_tools.delivery import instruction_surface_lint, never_rise, rule_ids
from agent_tools.delivery.never_rise import EnforcerFailed, Rise, Violation

from .conformance_test_support import (
    INTEGRATION_REF, REPO_ROOT, ReportAssertions, commit_all, fixture, git, make_root, run,
)
from .test_instruction_load import CORPUS_FILES, dict_snapshot, fixture_model

TIER = "integration"

M = instruction_surface_lint
B = M.BUDGETS
HOT = "home/common/agent-skills/skills/demo/SKILL.md"
EXTRA = "home/common/agent-skills/skills/demo/EXTRA.md"
STUB = "home/common/agent-skills/skills/stub/SKILL.md"
SOLO = "home/common/claude-code/skills/solo/SKILL.md"
PATHS = {
    "always-loaded": "instruction-surface/always-loaded/demo/claude",
    "conditional": "instruction-surface/conditional/demo/claude",
    "corpus": "instruction-surface/corpus",
    "descriptions": "instruction-surface/descriptions",
}
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"
COMMAND_TABLE = REPO_ROOT / "lib/agent-tools.nix"
VERDICTS = REPO_ROOT / "python/agent_tools/delivery/command_verdicts.json"


def padded(raw, size):
    assert size >= len(raw)
    return raw + b"f" * (size - len(raw))


def stub_with_description(n):
    return b"---\nname: stub\ndescription: " + b"d" * n + b"\n---\nstub body\n"


def measured(files, kind):
    if kind in ("always-loaded", "conditional"):
        entry = instruction_load.measure(fixture_model(), files.get)["profiles"]["demo"]["claude"]
        return entry["hot" if kind == "always-loaded" else "conditional"]["bytes"]
    return instruction_load.measure_corpus(dict_snapshot(files))[kind]


def sized(kind, size, files=CORPUS_FILES):
    result = dict(files)
    if kind == "always-loaded":
        result[HOT] = padded(files[HOT], size)
    elif kind == "conditional":
        result[EXTRA] = padded(files[EXTRA], len(files[EXTRA]) + size - measured(files, kind))
    elif kind == "corpus":
        result[STUB] = padded(files[STUB], len(files[STUB]) + size - measured(files, kind))
    else:
        result[STUB] = stub_with_description(size)
    assert measured(result, kind) == size
    return result


def model_bytes(model):
    return json.dumps(model, indent=2).encode()


def write_files(root, files):
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def world(tmp, files, model=fixture_model(), name="repo"):
    root = tmp / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write_files(root, files)
    if model is not None:
        write_files(root, {instruction_load.MODEL_PATH: model_bytes(model)})
    commit_all(root, "base")
    git(root, "update-ref", INTEGRATION_REF, "HEAD")
    return root


def advance(root, files):
    write_files(root, files)
    commit_all(root, "branch")


def rises(root):
    return never_rise.judge(root, "main", [M.ENFORCER], timeout=60).rises


def head_snapshot(root):
    return never_rise.read_snapshot(root, git(root, "rev-parse", "HEAD").strip(), 60, keep=M.reads)


def head_find(root):
    return M.find(head_snapshot(root))


def ceilings(model, value):
    result = copy.deepcopy(model)
    result["corpus_ceiling_bytes"] = value
    result["description_ceiling_bytes"] = value
    for profile in result["profiles"]:
        profile["ceiling_bytes"] = {host: value for host in profile["hosts"]}
        profile["conditional_ceiling_bytes"] = {host: value for host in profile["hosts"]}
    return result


def malformed_ceilings(model):
    result = copy.deepcopy(model)
    result["corpus_ceiling_bytes"] = "x"
    result["description_ceiling_bytes"] = -1
    for profile in result["profiles"]:
        profile["ceiling_bytes"] = {"codex": "x"}
        profile["conditional_ceiling_bytes"] = []
    return result


def one(kind, size, base=0):
    return (Rise("B25", base, 1, (Violation("B25", PATHS[kind], size),)),)


class SurfaceRuleTest(unittest.TestCase):
    def test_an_over_budget_surface_that_grows_fails(self):
        files = sized("always-loaded", B["always-loaded"] + 100)
        with fixture() as tmp:
            root = world(tmp, files)
            advance(root, {HOT: padded(files[HOT], B["always-loaded"] + 101)})

            found = rises(root)

        self.assertEqual(found, one("always-loaded", B["always-loaded"] + 101, base=1))

    def test_an_over_budget_surface_that_holds_or_shrinks_passes(self):
        files = sized("always-loaded", B["always-loaded"] + 100)
        rows = {"unchanged": {"README": b"x\n"},
                "shrinks": {HOT: files[HOT][:B["always-loaded"] + 50]}}
        for name, change in rows.items():
            with self.subTest(name), fixture() as tmp:
                root = world(tmp, files)
                advance(root, change)

                found = rises(root)

                self.assertEqual(found, ())

    def test_an_under_budget_surface_may_grow_to_its_budget(self):
        files = sized("always-loaded", B["always-loaded"] - 100)
        with fixture() as tmp:
            root = world(tmp, files)
            advance(root, {HOT: padded(files[HOT], B["always-loaded"])})

            found = rises(root)

        self.assertEqual(found, ())

    def test_an_under_budget_surface_that_grows_past_its_budget_fails(self):
        files = sized("always-loaded", B["always-loaded"] - 100)
        with fixture() as tmp:
            root = world(tmp, files)
            advance(root, {HOT: padded(files[HOT], B["always-loaded"] + 1)})

            found = rises(root)

        self.assertEqual(found, one("always-loaded", B["always-loaded"] + 1))

    def test_every_kind_is_judged_against_its_own_budget(self):
        for kind in PATHS:
            with self.subTest(kind=kind), fixture() as tmp:
                over, at = sized(kind, B[kind] + 1), sized(kind, B[kind])
                root = world(tmp, CORPUS_FILES)
                advance(root, {p: v for p, v in over.items() if CORPUS_FILES.get(p) != v})
                held = world(tmp, CORPUS_FILES, name="held")
                advance(held, {p: v for p, v in at.items() if CORPUS_FILES.get(p) != v})

                found, kept = rises(root), rises(held)

                self.assertEqual((found, kept), (one(kind, B[kind] + 1), ()))

    def test_the_budgets_are_the_platform_constants(self):
        self.assertEqual(dict(B), {
            "always-loaded": 20480, "conditional": 32768, "corpus": 163840, "descriptions": 3072})
        with self.assertRaises(TypeError):
            B["corpus"] = 1

    def test_a_project_ceiling_file_changes_no_budget(self):
        files = sized("descriptions", B["descriptions"] + 10)
        files[HOT] = padded(files[HOT], B["always-loaded"] - 10)
        models = {"low": ceilings(fixture_model(), 1), "high": ceilings(fixture_model(), 10**9),
                  "absent": fixture_model(),   # fixture_model() carries no ceiling since issue 1483
                  "malformed": malformed_ceilings(fixture_model())}
        with fixture() as tmp:
            reference = M.surfaces(head_snapshot(world(tmp, files, models["low"], name="low")))
            for name, model in models.items():
                with self.subTest(name):
                    root = world(tmp, files, model, name=f"ceilings-{name}")

                    self.assertEqual(head_find(root), [
                        Violation("B25", PATHS["descriptions"], B["descriptions"] + 10)])
                    self.assertEqual(M.surfaces(head_snapshot(root)), reference)

    def test_raising_a_project_ceiling_admits_no_growth(self):
        with fixture() as tmp:
            root = world(tmp, sized("descriptions", B["descriptions"] + 10))
            advance(root, {instruction_load.MODEL_PATH: model_bytes(ceilings(fixture_model(), 10**9)),
                           STUB: stub_with_description(B["descriptions"] + 11)})

            found = rises(root)

        self.assertEqual(found, one("descriptions", B["descriptions"] + 11, base=1))

    def test_a_file_moved_onto_a_surface_path_changes_no_verdict(self):
        moved = "".join(f"line {n}\n" for n in range(40)).encode()
        with fixture() as tmp:
            root = world(tmp, sized("descriptions", B["descriptions"] + 10) | {"notes/moved.txt": moved})
            (root / "instruction-surface").mkdir()
            git(root, "mv", "notes/moved.txt", PATHS["descriptions"])
            commit_all(root, "branch")

            verdict = never_rise.judge(root, "main", [M.ENFORCER], timeout=60)

        self.assertEqual((dict(verdict.renamed), verdict.rises),
                         ({PATHS["descriptions"]: "notes/moved.txt"}, ()))

    def test_a_repository_without_a_model_or_skill_trees_measures_nothing(self):
        with fixture() as tmp:
            root = world(tmp, {"src/app.py": b"x = 1\n"}, model=None)

            found = M.surfaces(head_snapshot(root))

        self.assertEqual(found, ((), ()))

    def test_without_a_model_the_corpus_is_still_judged(self):
        with fixture() as tmp:
            root = world(tmp, sized("descriptions", B["descriptions"] + 1), model=None)

            found = head_find(root)

        self.assertEqual(found, [Violation("B25", PATHS["descriptions"], B["descriptions"] + 1)])

    def test_a_model_broken_on_the_branch_rises(self):
        ghost = fixture_model()
        ghost["profiles"][0]["hot"].append("ghost/SKILL.md")
        for name, content in {"unparsable": b"{", "dangling member": model_bytes(ghost)}.items():
            with self.subTest(name), fixture() as tmp:
                root = world(tmp, CORPUS_FILES)
                advance(root, {instruction_load.MODEL_PATH: content})

                found = rises(root)

                self.assertEqual(found, (
                    Rise("B25", 0, 1, (Violation("B25", M.UNMEASURABLE_PROFILES, 1),)),))

    def test_a_model_broken_on_both_sides_passes(self):
        with fixture() as tmp:
            root = world(tmp, CORPUS_FILES)
            broken_base(root)
            advance(root, {"README": b"x\n"})

            found = rises(root)

        self.assertEqual(found, ())

    def test_a_held_unmeasurable_part_does_not_hide_a_new_one(self):
        with fixture() as tmp:
            root = world(tmp, CORPUS_FILES)
            broken_base(root)
            git(root, "mv", SOLO, SOLO.replace("SKILL.md", "OTHER.md"))
            commit_all(root, "branch")

            found = rises(root)

        self.assertEqual(found, (Rise("B25", 1, 2, (Violation("B25", M.UNMEASURABLE_CORPUS, 1),)),))

    def test_the_enforcer_keeps_every_path_it_measures(self):
        for path in (instruction_load.MODEL_PATH, instruction_load.FRAME_PATH,
                     "home/common/agent-skills/model-matrix.json", HOT, SOLO,
                     "home/common/claude-code/agents/reviewer.md"):
            self.assertTrue(M.reads(path), path)
        self.assertFalse(M.reads("README.md"))
        with fixture() as tmp:
            root = world(tmp, CORPUS_FILES)
            unkept = never_rise.read_snapshot(
                root, git(root, "rev-parse", "HEAD").strip(), 60, keep=lambda path: False)

            with self.assertRaises(EnforcerFailed):
                M.find(unkept)


def broken_base(root):
    write_files(root, {instruction_load.MODEL_PATH: b"{"})
    commit_all(root, "broken model")
    git(root, "update-ref", INTEGRATION_REF, "HEAD")


class SurfaceLintCommandTest(unittest.TestCase):
    def run_command(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.instruction_surface_lint", *args],
            capture_output=True, text=True, timeout=60, cwd=cwd,
            env=dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python")))

    def test_the_command_prints_each_breach_as_rule_surface_and_bytes(self):
        files = sized("descriptions", B["descriptions"] + 3)
        files[HOT] = padded(files[HOT], B["always-loaded"] + 5)
        with fixture() as tmp:
            over = self.run_command("--repo-root", str(world(tmp, files)))
            clean = self.run_command("--repo-root", str(world(tmp, CORPUS_FILES, name="clean")))

        self.assertEqual((over.returncode, over.stdout, clean.returncode, clean.stdout), (
            1, f"B25 {PATHS['always-loaded']}:{B['always-loaded'] + 5}\n"
               f"B25 {PATHS['descriptions']}:{B['descriptions'] + 3}\n", 0, ""))

    def test_a_relative_or_subdirectory_root_exits_2(self):
        with fixture() as tmp:
            root = world(tmp, CORPUS_FILES)
            for args, cwd in ((("--repo-root", "."), root), (("--repo-root", str(root / "home")), None)):
                with self.subTest(args):
                    done = self.run_command(*args, cwd=cwd)

                    self.assertEqual((done.returncode, done.stdout), (2, ""))
                    self.assertTrue(done.stderr.startswith("instruction-surface-lint: "), done.stderr)

    def test_the_rule_id_is_a_rule_of_the_bar_and_cited_by_its_enforcer(self):
        module = Path(instruction_surface_lint.__file__).read_text(encoding="utf-8")

        self.assertIn("B25", rule_ids.sections(BAR.read_text(encoding="utf-8")))
        self.assertIn("B25", {c.token for c in rule_ids.citations(module) if c.well_formed})

    def test_the_command_is_a_row_of_the_command_table(self):
        self.assertIn('"instruction-surface-lint" = "delivery.instruction_surface_lint";',
                      COMMAND_TABLE.read_text(encoding="utf-8"))
        self.assertIsNone(json.loads(VERDICTS.read_text(encoding="utf-8"))["instruction-surface-lint"])


class NeverRiseRegistrationTest(ReportAssertions, unittest.TestCase):
    CHECK_ID = "verification.violations.never_rise"

    def ci(self, root):
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check):
        return [check["status"], check["reason_code"], check["repair_id"], check["facts"]]

    def instruction_base(self, root, files):
        write_files(root, files)
        write_files(root, {instruction_load.MODEL_PATH: model_bytes(fixture_model())})
        commit_all(root, "instructions")
        git(root, "update-ref", INTEGRATION_REF, "HEAD")
        return git(root, "rev-parse", "HEAD").strip()

    def test_a_grown_over_budget_surface_turns_ci_red_and_names_it(self):
        size = B["always-loaded"] + 101
        with fixture() as tmp:
            root = make_root(tmp)
            base = self.instruction_base(root, sized("always-loaded", B["always-loaded"] + 100))
            write_files(root, {HOT: padded(CORPUS_FILES[HOT], size)})
            commit_all(root, "grow")

            code, report, by_id = self.ci(root)

            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {"status": "failed", "primary_check_id": self.CHECK_ID})
            self.assertEqual([c["id"] for c in report["checks"] if c["status"] == "failed"],
                             [self.CHECK_ID])
            self.assertEqual(self.summary(by_id[self.CHECK_ID]), [
                "failed", "violation_count_rose", "violations.never_rise.reduce",
                {"merge_base": base, "rule": "B25", "base_count": 1, "branch_count": 1,
                 "violations": [f"B25 {PATHS['always-loaded']}:{size}"], "rules": ["B25"]}])
            self.assert_validates(report)

    def test_a_level_instruction_tree_passes_ci(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = self.instruction_base(root, sized("always-loaded", B["always-loaded"] + 100))

            code, _, by_id = self.ci(root)

            self.assertEqual(code, 0)
            self.assertEqual(self.summary(by_id[self.CHECK_ID]),
                             ["passed", None, None, {"merge_base": base}])


if __name__ == "__main__":
    unittest.main()
