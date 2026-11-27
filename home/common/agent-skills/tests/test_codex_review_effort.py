"""The Codex review effort is declared once (`agent_tools.delivery.codex_review_effort.EFFORT`).

Every copy agrees with it, a different declared value reaches every copy, and a copy that
disagrees is named.
"""

from pathlib import Path
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr

from agent_tools.delivery import codex_review_effort, independent_review
from agent_tools.delivery.codex_review_effort import EFFORT, EVALS, PATCH, PLUGINS_NIX, SKILL

TIER = "fast"

REPO_ROOT = Path(__file__).parents[4]
OTHER = "medium" if EFFORT != "medium" else "low"
SKILL_DIR = REPO_ROOT / "home/common/claude-code/skills/codex-collaboration"


def copy_of_the_copies(test: unittest.TestCase) -> Path:
    root = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, root)
    for path in (*codex_review_effort._FILE_RULES, PLUGINS_NIX):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, root / path)
    return root


def patch_revision(root: Path) -> int:
    return int(re.search(r"patchRevision = (\d+);",
                         (root / PLUGINS_NIX).read_text(encoding="utf-8"))[1])


class CodexReviewEffortTest(unittest.TestCase):
    def test_every_copy_agrees_with_the_declared_effort(self):
        self.assertEqual(codex_review_effort.disagreements(REPO_ROOT), [])

    def test_the_independent_review_reads_the_declared_effort(self):
        self.assertIs(independent_review.EFFORT, EFFORT)

    def test_a_different_declared_effort_reaches_every_copy(self):
        root = copy_of_the_copies(self)

        changed = codex_review_effort.write(root, OTHER)

        self.assertEqual(sorted(changed),
                         sorted([*codex_review_effort._FILE_RULES, PLUGINS_NIX]))
        self.assertEqual(codex_review_effort.disagreements(root, OTHER), [])
        self.assertEqual(sorted(codex_review_effort.disagreements(root, EFFORT)),
                         sorted(codex_review_effort._FILE_RULES))
        skill = (root / SKILL).read_text(encoding="utf-8")
        self.assertIn(f"--effort {OTHER} \\\n", skill)
        self.assertIn(f"`runtime.reasoningEffort` `{OTHER}`", skill)
        self.assertNotIn(f"--effort {EFFORT} ", skill)

    def test_a_copy_that_disagrees_is_named(self):
        for path in codex_review_effort._FILE_RULES:
            with self.subTest(path=path):
                root = copy_of_the_copies(self)
                (root / path).write_text(
                    codex_review_effort.render(
                        path, (root / path).read_text(encoding="utf-8"), OTHER),
                    encoding="utf-8")

                self.assertEqual(codex_review_effort.disagreements(root), [path])

    def test_the_patch_rewrite_stays_inside_the_reviewer_detach_test(self):
        root = copy_of_the_copies(self)
        before = (root / PATCH).read_text(encoding="utf-8")

        codex_review_effort.write(root, OTHER)

        after = (root / PATCH).read_text(encoding="utf-8")
        header = codex_review_effort._PATCH_HUNK_HEADER
        self.assertEqual(before.split(header, 1)[0], after.split(header, 1)[0])
        self.assertEqual(before.split(header, 1)[1].split("\ndiff --git ", 1)[1:],
                         after.split(header, 1)[1].split("\ndiff --git ", 1)[1:])

    def test_the_installed_skill_is_rendered_from_the_declaration_alone(self):
        installed = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, installed)
        shutil.copytree(SKILL_DIR, installed / "skill")
        codex_review_effort.render_skill_dir(installed / "skill", OTHER)

        skill = (installed / "skill/SKILL.md").read_text(encoding="utf-8")
        evals = (installed / "skill/evals/evals.json").read_text(encoding="utf-8")
        for text in (skill, evals):
            self.assertIn(f"--effort {OTHER} ", text)
            self.assertRegex(text, rf"reasoningEffort[` ]+{OTHER}\b")
            self.assertNotIn(f"--effort {EFFORT} ", text)
            self.assertNotRegex(text, rf"reasoningEffort[` ]+{EFFORT}\b")

    def test_the_build_installs_the_skill_through_that_rendering(self):
        nix = (REPO_ROOT / "home/common/claude-code/default.nix").read_text(encoding="utf-8")
        self.assertRegex(
            nix, r'\.claude/skills/codex-collaboration" = \{\s*source = pkgs\.runCommand')
        self.assertIn("codex_review_effort.py} --render-skill", nix)

    def test_the_render_skill_command_rewrites_a_skill_directory(self):
        installed = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, installed)
        shutil.copytree(SKILL_DIR, installed / "skill")
        (installed / "skill/SKILL.md").write_text(
            codex_review_effort.render(
                SKILL, (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"), OTHER),
            encoding="utf-8")

        self.assertEqual(codex_review_effort.main(
            ["--render-skill", str(installed / "skill")]), 0)

        self.assertEqual((installed / "skill/SKILL.md").read_text(encoding="utf-8"),
                         (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))

    def test_an_eval_command_with_a_quoted_effort_is_refused_not_skipped(self):
        root = copy_of_the_copies(self)
        evals = (root / EVALS).read_text(encoding="utf-8")
        (root / EVALS).write_text(
            evals.replace(f"--effort {EFFORT} ", f"--effort 'low' ", 1), encoding="utf-8")

        with self.assertRaises(codex_review_effort.CopyError):
            codex_review_effort.disagreements(root)

    def test_each_reviewing_eval_case_is_checked_on_its_own(self):
        root = copy_of_the_copies(self)
        data = json.loads((root / EVALS).read_text(encoding="utf-8"))
        reviewing = [case for case in data["evals"] if "--effort" in case["expected_output"]]
        self.assertGreater(len(reviewing), 1)
        # one case keeps its command but loses its validation phrase; the others still match
        reviewing[0]["expected_output"] = re.sub(
            r"runtime\.reasoningEffort \w+", "runtime.model only", reviewing[0]["expected_output"])
        (root / EVALS).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(codex_review_effort.CopyError):
            codex_review_effort.disagreements(root)

    def test_changing_the_patch_bumps_the_plugin_patch_revision(self):
        root = copy_of_the_copies(self)
        before = patch_revision(root)

        changed = codex_review_effort.write(root, OTHER)

        self.assertIn(PATCH, changed)
        self.assertEqual(patch_revision(root), before + 1)
        # a second write finds nothing to change, so it does not bump again
        self.assertEqual(codex_review_effort.write(root, OTHER), [])
        self.assertEqual(patch_revision(root), before + 1)

    def test_an_unchanged_patch_leaves_the_patch_revision_alone(self):
        root = copy_of_the_copies(self)
        before = patch_revision(root)

        self.assertEqual(codex_review_effort.write(root), [])

        self.assertEqual(patch_revision(root), before)

    def test_a_refused_write_leaves_every_copy_untouched(self):
        root = copy_of_the_copies(self)
        (root / PATCH).write_text(
            (root / PATCH).read_text(encoding="utf-8").replace(
                codex_review_effort._PATCH_HUNK_HEADER, "diff --git a/x b/x\n"),
            encoding="utf-8")
        snapshot = {path: (root / path).read_text(encoding="utf-8")
                    for path in (*codex_review_effort._FILE_RULES, PLUGINS_NIX)}

        with redirect_stderr(io.StringIO()):
            status = codex_review_effort.main(["--write", "--root", str(root)])

        self.assertEqual(status, 2)
        self.assertEqual(snapshot, {path: (root / path).read_text(encoding="utf-8")
                                    for path in snapshot})

    def test_a_copy_missing_its_phrase_is_an_error_not_a_silent_skip(self):
        root = copy_of_the_copies(self)
        (root / SKILL).write_text("no effort here\n", encoding="utf-8")

        with self.assertRaises(codex_review_effort.CopyError):
            codex_review_effort.disagreements(root)


if __name__ == "__main__":
    unittest.main()
