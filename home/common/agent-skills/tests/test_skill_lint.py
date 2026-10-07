"""skill_lint: the snapshot seam, frontmatter, reflowed lines and skill classification (#292)."""

from __future__ import annotations

import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
