"""agnostic_lint: the global agent corpus names no hosting-project specifics (#572)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from agent_tools import agnostic_lint, skill_lint


REPO_ROOT = Path(__file__).parents[4]


def dict_snapshot(files):
    return skill_lint.Snapshot(
        read=files.get,
        list_files=lambda prefix: sorted(p for p in files if p.startswith(prefix + "/")),
    )


class AgnosticTest(unittest.TestCase):
    BASE = {
        ".github/branch-protection.json": json.dumps(
            {"required_status_checks": {"checks": [{"context": "Gate One"}]}}).encode(),
        "justfile": b"# c\nbuild host=x:\n    echo\n@ship:\n    echo\nvar := 1\n",
        "home/common/agent-skills/skills/a/SKILL.md": b"clean text just building\n",
        "home/common/claude-code/skills/b/SKILL.md": b"ok\n",
        "home/common/codex/skills/c/SKILL.md": b"ok\n",
        "home/common/claude-code/agents/r.md": b"ok\n",
        "home/common/agent-skills/standards/s.md": b"ok\n",
        "home/common/agent-guidance/AGENTS.md": b"ok\n",
    }

    def test_a_missing_root_is_reported(self):
        files = {p: d for p, d in self.BASE.items() if "standards" not in p}
        self.assertEqual(agnostic_lint.hosting_specifics(dict_snapshot(files)),
                         ["home/common/agent-skills/standards: no files scanned"])

    def hits(self, extra):
        return agnostic_lint.hosting_specifics(dict_snapshot({**self.BASE, **extra}))

    def test_clean_corpus_passes(self):
        self.assertEqual(self.hits({}), [])

    def test_each_token_is_caught_in_each_corpus_root(self):
        tokens = ["fagenorn/nix-config", "nix-config", "Gate One", "just build", "just ship",
                  "origin/main", "--base main", "home/common/x", "python/agent_tools/x"]
        roots = {"home/common/codex/skills/c/SKILL.md", "home/common/claude-code/skills/b/SKILL.md", "home/common/claude-code/agents/r.md",
                 "home/common/agent-skills/standards/s.md", "home/common/agent-guidance/AGENTS.md",
                 "home/common/agent-skills/skills/a/ref.md"}
        for token in tokens:
            for path in roots:
                with self.subTest(token=token, path=path):
                    self.assertTrue(self.hits({path: f"x {token} y\n".encode()}))

    def test_exemptions_are_narrow(self):
        retro = "home/common/agent-skills/skills/retro/SKILL.md"
        self.assertEqual(self.hits({retro: b"nix-config at home/common/ fagenorn/nix-config\n"}), [])
        self.assertTrue(self.hits({retro: b"run just build\n"}))
        self.assertEqual(self.hits({
            "home/common/agent-skills/skills/a/evals/e.md": b"nix-config\n",
            "home/common/agent-skills/skills/a/LICENSE": b"nix-config\n"}), [])
        self.assertTrue(self.hits({"home/common/agent-skills/skills/a/NOTES.md": b"nix-config\n"}))


class LiveTreeTest(unittest.TestCase):
    def test_the_live_global_corpus_names_no_hosting_project_specifics(self):
        self.assertEqual(agnostic_lint.hosting_specifics(skill_lint.working_tree(REPO_ROOT)), [])

    def test_the_command_exits_zero_on_the_live_tree(self):
        done = subprocess.run([sys.executable, "-m", "agent_tools.agnostic_lint", "--root", str(REPO_ROOT)],
                              capture_output=True, text=True, env={"PYTHONPATH": str(REPO_ROOT / "python")})
        self.assertEqual((done.returncode, done.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
