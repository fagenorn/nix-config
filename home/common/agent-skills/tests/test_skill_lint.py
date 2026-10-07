"""skill_lint: the snapshot seam, frontmatter, reflowed lines and skill classification (#292)."""

from __future__ import annotations

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
SHARED = "home/common/agent-skills/skills"
CLAUDE = "home/common/claude-code/skills"
CODEX = "home/common/codex/skills"
ALPHA = f"{SHARED}/alpha"
MATRIX = {
    "roles": {},
    "dispatch_sites": [
        {"id": "alpha-review", "path": f"{ALPHA}/SKILL.md",
         "call": 'Agent(subagent_type="reviewer", model="opus", effort="high") '
                 'reviews against `CONTRACT.md`.'},
    ],
    "scenarios": {},
}


def skill(name, description="Does things. Use when testing.", body="body\n"):
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}".encode()


def clean_files():
    """A lint-clean three-tree repository: one reference, two payloads, excluded dirs."""
    return {
        "home/common/agent-skills/model-matrix.json": json.dumps(MATRIX).encode(),
        f"{ALPHA}/SKILL.md": skill(
            "alpha", "Alphas things. Use when testing.",
            "Read GUIDE.md first.\nHand alpha-prompt.md and CONTRACT.md to the reviewer.\n"),
        f"{ALPHA}/GUIDE.md": b"# Guide\nshort guide naming SKILL.md and CONTRACT.md\n",
        f"{ALPHA}/alpha-prompt.md": b"Prompt naming GUIDE.md\n",
        f"{ALPHA}/CONTRACT.md": b"contract\n",
        f"{ALPHA}/evals/notes.md": b"NOT.md is mentioned here\n",
        f"{ALPHA}/scripts/README.md": b"script docs\n",
        f"{CLAUDE}/beta/SKILL.md": skill("beta"),
        f"{CODEX}/gamma/SKILL.md": skill("gamma"),
        "home/common/claude-code/agents/reviewer.md": b"reviewer body\n",
        "home/common/agent-guidance/AGENTS.md": b"frame text\n",
        "home/common/agent-skills/skill-lint-debt.json": b'{"debt": []}\n',
    }


def dict_snapshot(files):
    return skill_lint.Snapshot(
        read=files.get,
        list_files=lambda prefix: sorted(p for p in files if p.startswith(prefix + "/")),
    )


class FoundationTest(unittest.TestCase):
    def test_reflowed_lines_count_long_lines_by_the_hundred(self):
        for text, expected in (("", 0), ("a\n", 1), ("\n", 1), ("a\nb", 2),
                               ("x" * 100, 1), ("x" * 101, 2), ("x" * 1229, 13),
                               ("é" * 100 + "\n", 1)):
            with self.subTest(text=text[:12]):
                self.assertEqual(skill_lint.reflowed_lines(text), expected)

    def test_frontmatter_parses_single_line_scalars(self):
        fields, body = skill_lint.parse_frontmatter(
            '---\nname: alpha\ndescription: "Quoted. Use when x."\nflag: true\n'
            "hint: 'single'\nempty:\n---\n# Body\n")
        self.assertEqual(fields, {"name": "alpha", "description": "Quoted. Use when x.",
                                  "flag": "true", "hint": "single", "empty": ""})
        self.assertEqual(body, "# Body\n")

    def test_frontmatter_rejects_every_shape_it_cannot_vouch_for(self):
        for text in ("name: alpha\n---\n",                       # no leading fence
                     "---\nname: alpha\n",                       # never closed
                     "---\nname: a\nname: b\n---\n",             # duplicate key
                     "---\ndescription: >\n  folded\n---\n",     # block scalar
                     "---\ndescription: |\n---\n",               # block scalar
                     "---\nname: a\n  continued\n---\n",         # continuation line
                     "---\nnot a mapping line\n---\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    skill_lint.parse_frontmatter(text)
        for value in ('"Use when testing.', "'Use when testing.", 'Use when testing."',
                      "Use when testing.'", '"Use when testing.\'', "'Use when testing.\"",
                      '"', "'"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,
                                            "frontmatter: description has an unterminated quote"):
                    skill_lint.parse_frontmatter(f"---\ndescription: {value}\n---\n")

    def test_a_listed_file_that_cannot_be_read_cannot_be_linted(self):
        files = clean_files()
        for path in (f"{ALPHA}/SKILL.md", f"{ALPHA}/GUIDE.md"):
            with self.subTest(path=path):
                snapshot = skill_lint.Snapshot(
                    read=lambda p, path=path: None if p == path else files.get(p),
                    list_files=dict_snapshot(files).list_files,
                )
                with self.assertRaisesRegex(ValueError, re.escape(f"cannot read {path}")):
                    skill_lint.violations(snapshot)

    def test_skill_dirs_classify_references_and_payloads(self):
        dirs = skill_lint.skill_dirs(dict_snapshot(clean_files()))
        self.assertEqual([(d.tree, d.name) for d in dirs],
                         [(SHARED, "alpha"), (CLAUDE, "beta"), (CODEX, "gamma")])
        alpha = dirs[0]
        self.assertEqual(alpha.path, ALPHA)
        self.assertEqual(alpha.skill_md, f"{ALPHA}/SKILL.md")
        self.assertEqual(alpha.references, (f"{ALPHA}/GUIDE.md",))
        self.assertEqual(alpha.payloads, (f"{ALPHA}/CONTRACT.md", f"{ALPHA}/alpha-prompt.md"))

    def test_a_skill_directory_without_skill_md_is_still_listed(self):
        files = clean_files()
        files[f"{SHARED}/orphan/NOTES.md"] = b"notes\n"
        orphan = next(d for d in skill_lint.skill_dirs(dict_snapshot(files)) if d.name == "orphan")
        self.assertIsNone(orphan.skill_md)
        self.assertEqual(orphan.references, (f"{SHARED}/orphan/NOTES.md",))

    def test_a_tree_root_without_any_skill_cannot_be_classified(self):
        files = {p: d for p, d in clean_files().items() if not p.startswith(CODEX)}
        with self.assertRaisesRegex(ValueError, CODEX):
            skill_lint.skill_dirs(dict_snapshot(files))

    def test_an_unreadable_matrix_cannot_be_classified(self):
        for raw in (None, b'{"roles": {}, "roles": {}}', b'{"dispatch_sites": 1}'):
            with self.subTest(raw=raw):
                files = clean_files()
                if raw is None:
                    del files["home/common/agent-skills/model-matrix.json"]
                else:
                    files["home/common/agent-skills/model-matrix.json"] = raw
                with self.assertRaises(ValueError):
                    skill_lint.skill_dirs(dict_snapshot(files))

    def test_the_tree_lister_lists_files_recursively_and_sorted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("a/x/SKILL.md", "a/x/sub/deep.md", "a/y.md", "b/z.md"):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(b"x\n")
            os.symlink(root / "b", root / "a/link")
            listing = skill_lint.tree_lister(root)
            self.assertEqual(listing("a"), ["a/x/SKILL.md", "a/x/sub/deep.md", "a/y.md"])
            self.assertEqual(listing("absent"), [])
            snapshot = skill_lint.working_tree(root)
            self.assertEqual(snapshot.read("a/y.md"), b"x\n")
            self.assertEqual(snapshot.list_files("b"), ["b/z.md"])

    def test_instruction_load_uses_the_moved_seam_and_matcher(self):
        self.assertIs(instruction_load.tree_reader, skill_lint.tree_reader)
        self.assertTrue(skill_lint.names("demo/SKILL.md", "see EXTRA.md", "demo/EXTRA.md"))
        self.assertFalse(skill_lint.names("demo/SKILL.md", "see other/EXTRA.md", "demo/EXTRA.md"))
        self.assertTrue(skill_lint.names("x/SKILL.md", "use `demo`", "demo/SKILL.md"))
        self.assertEqual(skill_lint.split_member("demo/EXTRA.md"), ("demo", "EXTRA.md"))
        self.assertIsNone(skill_lint.split_member("demo/sub/EXTRA.md"))


DEBT = "home/common/agent-skills/skill-lint-debt.json"
ALPHA_BODY = "Read GUIDE.md first.\nHand alpha-prompt.md and CONTRACT.md to the reviewer.\n"


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.files = clean_files()

    def keys(self, files=None):
        return {v.key for v in skill_lint.violations(dict_snapshot(files or self.files))}

    def test_the_clean_tree_has_no_violation(self):
        self.assertEqual(skill_lint.violations(dict_snapshot(self.files)), [])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [])

    def test_l1_reports_every_frontmatter_form(self):
        path = f"{ALPHA}/SKILL.md"
        body = ALPHA_BODY.encode()
        cases = {
            "name differs": skill("alphax", body=ALPHA_BODY),
            "missing name": b"---\ndescription: Alphas. Use when testing.\n---\n" + body,
            "missing description": b"---\nname: alpha\n---\n" + body,
            "empty description": b"---\nname: alpha\ndescription:\n---\n" + body,
            "long description": skill("alpha", "Use when testing. " + "x" * 1010, ALPHA_BODY),
            "xml description": skill("alpha", "Alphas <b>things</b>. Use when testing.",
                                     ALPHA_BODY),
            "no fence": body,
            "unclosed fence": b"---\nname: alpha\n" + body,
            "block scalar": b"---\nname: alpha\ndescription: >\n---\n" + body,
            "duplicate key": b"---\nname: alpha\nname: alpha\n"
                             b"description: Alphas. Use when x.\n---\n" + body,
            "unterminated quote": b'---\nname: alpha\ndescription: "Alphas. Use when x.\n---\n'
                                  + body,
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                files = clean_files()
                files[path] = data
                self.assertEqual(self.keys(files), {f"L1 {path}"})

    def test_l1_judges_the_name_itself(self):
        for name in ("a" * 65, "Upper", "claude-helper", "anthropic-x"):
            with self.subTest(name=name):
                files = clean_files()
                path = f"{SHARED}/{name}/SKILL.md"
                files[path] = skill(name)
                self.assertEqual(self.keys(files), {f"L1 {path}"})

    def test_l1_reports_a_skill_directory_without_skill_md(self):
        self.files[f"{SHARED}/orphan/NOTES.md"] = b"notes\n"
        self.assertEqual(self.keys(), {f"L1 {SHARED}/orphan/SKILL.md"})

    def test_l2_counts_reflowed_body_lines(self):
        path = f"{ALPHA}/SKILL.md"
        for body, expected in ((ALPHA_BODY + "x\n" * 498, set()),
                               (ALPHA_BODY + "x\n" * 499, {f"L2 {path}"}),
                               (ALPHA_BODY + "x\n" * 496 + "y" * 201 + "\n", {f"L2 {path}"})):
            with self.subTest(lines=body.count("\n")):
                files = clean_files()
                files[path] = skill("alpha", "Alphas things. Use when testing.", body)
                self.assertEqual(self.keys(files), expected)

    def test_l3_demands_a_contents_list_past_100_reflowed_lines(self):
        guide = f"{ALPHA}/GUIDE.md"
        filler = "line\n"
        cases = (
            ("100 lines, no contents", "# Guide\n" + filler * 99, set()),
            ("101 lines, no contents", "# Guide\n" + filler * 100, {f"L3 {guide}"}),
            ("101 lines with contents",
             "# Guide\n## Contents\n- [A](#a)\n## A\n" + filler * 97, set()),
            ("contents after another heading",
             "# Guide\n## A\n## Contents\n- [A](#a)\n" + filler * 97, {f"L3 {guide}"}),
            ("contents heading without a list",
             "# Guide\n## Contents\nprose\n## A\n" + filler * 97, {f"L3 {guide}"}),
            ("a fenced heading comes first",
             "# Guide\n```\n## Not a heading\n```\n## Contents\n- a\n" + filler * 95, set()),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                files = clean_files()
                files[guide] = text.encode()
                self.assertEqual(self.keys(files), expected)

    def test_l4a_reports_a_reference_its_skill_md_does_not_name(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.assertEqual(self.keys(), {f"L4a {ALPHA}/ORPHAN.md"})

    def test_l4b_reports_a_reference_naming_a_sibling_reference(self):
        self.files[f"{ALPHA}/OTHER.md"] = b"other\n"
        self.files[f"{ALPHA}/SKILL.md"] = skill("alpha", "Alphas things. Use when testing.",
                                                ALPHA_BODY + "See OTHER.md.\n")
        self.files[f"{ALPHA}/GUIDE.md"] = b"# Guide\nsee OTHER.md\n"
        self.assertEqual(self.keys(), {f"L4b {ALPHA}/GUIDE.md names OTHER.md"})

    def test_l4_exempts_payloads_and_naming_skill_md_or_a_payload(self):
        # GUIDE.md names SKILL.md and the payload CONTRACT.md; the payload
        # alpha-prompt.md names the reference GUIDE.md. None of it is a violation.
        self.files[f"{ALPHA}/CONTRACT.md"] = b"contract naming GUIDE.md\n"
        self.assertEqual(self.keys(), set())

    def test_l5_demands_third_person_and_a_trigger_clause(self):
        path = f"{ALPHA}/SKILL.md"
        for description, expected in (("You alpha things. Use when testing.", {f"L5 {path}"}),
                                      ("I alpha things. Use when testing.", {f"L5 {path}"}),
                                      ("Alphas things.", {f"L5 {path}"}),
                                      ("Alphas things. Invoke before planning.", set())):
            with self.subTest(description=description):
                files = clean_files()
                files[path] = skill("alpha", description, ALPHA_BODY)
                self.assertEqual(self.keys(files), expected)


class DebtTest(unittest.TestCase):
    def setUp(self):
        self.files = clean_files()

    def debt(self, keys):
        self.files[DEBT] = json.dumps({"debt": keys}).encode()

    def test_a_listed_violation_is_suppressed(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.debt([f"L4a {ALPHA}/ORPHAN.md"])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [])

    def test_an_unlisted_violation_is_one_failure_line(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)),
                         [f"L4a {ALPHA}/ORPHAN.md: not named in its SKILL.md"])

    def test_a_stale_entry_fails(self):
        self.debt(["L4a gone.md"])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [
            "L4a gone.md: stale debt entry; delete it from "
            "home/common/agent-skills/skill-lint-debt.json"])

    def test_a_malformed_debt_file_cannot_run(self):
        for raw in (b'{"debt": ["b", "a"]}', b'{"debt": ["a", "a"]}', b'{"debt": "a"}',
                    b'{"debt": [], "extra": 1}', b'{"debt": [1]}', b"[]",
                    b'{"debt": [], "debt": []}', b"\xff", None):
            with self.subTest(raw=raw):
                files = clean_files()
                if raw is None:
                    del files[DEBT]
                else:
                    files[DEBT] = raw
                with self.assertRaises(ValueError):
                    skill_lint.lint(dict_snapshot(files))


class CommandTest(unittest.TestCase):
    def run_lint(self, files):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, data in files.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(data)
            return subprocess.run(
                [sys.executable, "-m", "agent_tools.skill_lint", "check", "--root", str(root)],
                capture_output=True, text=True, check=False)

    def test_exit_codes(self):
        clean = self.run_lint(clean_files())
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, "", ""))
        orphaned = self.run_lint({**clean_files(), f"{ALPHA}/ORPHAN.md": b"orphan\n"})
        self.assertEqual((orphaned.returncode, orphaned.stdout),
                         (1, f"L4a {ALPHA}/ORPHAN.md: not named in its SKILL.md\n"))
        no_codex = {p: d for p, d in clean_files().items() if not p.startswith(CODEX)}
        for files in ({**clean_files(), DEBT: b"{"}, no_codex):
            broken = self.run_lint(files)
            self.assertEqual((broken.returncode, broken.stdout), (2, ""))
            self.assertEqual(len(broken.stderr.splitlines()), 1, broken.stderr)
            self.assertTrue(broken.stderr.startswith("skill-lint: "))


class LiveTreeTest(unittest.TestCase):
    def test_the_live_tree_lints_clean_against_its_debt_file(self):
        self.assertEqual(skill_lint.lint(skill_lint.working_tree(REPO_ROOT)), [])

    def test_every_live_debt_key_names_a_known_rule(self):
        raw = (REPO_ROOT / DEBT).read_bytes()
        for key in skill_lint.load_debt(raw):
            with self.subTest(key=key):
                self.assertIn(key.split(" ", 1)[0], {"L1", "L2", "L3", "L4a", "L4b", "L5"})


if __name__ == "__main__":
    unittest.main()
