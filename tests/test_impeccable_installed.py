"""Installed-layout seam for the Impeccable skill (#238 D3, D4, D6, D7, D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Codex gets the
derived tree as one directory link, Claude as a recursive copy of links, and
both launchers must answer `engine-probe` from the tree's own sibling engine
without touching ~/.impeccable/bin.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
SKILL = "impeccable"
OPT_IN_SKILLS = ("sdd", "from-issue")
RETIRED_SKILLS = ("ui-ux-pro-max",)
SKILL_ROOTS = (".agents/skills", ".claude/skills")
SLOTS = {("Darwin", "arm64"): "darwin-arm64", ("Linux", "x86_64"): "linux-x64"}
TIMEOUT_SECONDS = 60


def path_without_engines(path):
    """`path` minus every directory holding an `impeccable` executable.

    The launcher falls back to `impeccable` on PATH when its sibling engine is
    missing, so a probe that kept e.g. ~/.agents/bin would pass on a global
    wrapper instead of the tree under test. The other directories stay so the
    launcher's own utilities (`uname`, `tr`) still resolve.
    """
    kept = [d for d in path.split(os.pathsep) if d and shutil.which(SKILL, path=d) is None]
    return os.pathsep.join(kept)


class ImpeccableInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the Impeccable skill the Nix build installs"
            )
        cls.root = Path(root)

    def setUp(self):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        self.codex = self.root / ".agents/skills" / SKILL
        self.claude = self.root / ".claude/skills" / SKILL

    def slot(self):
        key = (platform.system(), platform.machine())
        if key not in SLOTS:
            self.fail(f"no pinned Impeccable engine slot for {key}")
        return SLOTS[key]

    def version(self):
        return (self.codex / "scripts/VERSION").read_text(encoding="utf-8").strip()

    def probe(self, executable):
        """Run `<executable> engine-probe` isolated from ~/.impeccable and PATH engines."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        home = Path(scratch.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("IMPECCABLE_")}
        env.update(HOME=str(home), IMPECCABLE_NO_UPDATE_CHECK="1", DO_NOT_TRACK="1")
        env["PATH"] = path_without_engines(env.get("PATH", os.defpath))
        self.assertIsNone(shutil.which(SKILL, path=env["PATH"]), env["PATH"])
        result = subprocess.run(
            [str(executable), "engine-probe"], env=env, capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            (home / ".impeccable/bin").exists(),
            f"{executable} installed an engine instead of using the sibling slot",
        )
        return result.stdout.strip()

    def test_codex_view_is_a_whole_directory_link(self):
        self.assertTrue(self.codex.is_symlink(), f"{self.codex} is not a link")
        self.assertTrue(self.codex.is_dir())
        skill_md = self.codex / "SKILL.md"
        self.assertTrue(skill_md.is_file() and not skill_md.is_symlink())

    def test_claude_view_has_skill_md(self):
        self.assertTrue((self.claude / "SKILL.md").is_file())

    def test_sibling_engine_answers_tree_version(self):
        engine = self.codex / "scripts/bin" / self.slot() / SKILL
        self.assertTrue(os.access(engine, os.X_OK), f"{engine} is not executable")
        self.assertEqual(self.probe(engine), f"impeccable-engine {self.version()}")

    def test_launchers_answer_tree_version(self):
        expected = f"impeccable-engine {self.version()}"
        for launcher in (
            self.root / ".agents/bin" / SKILL,
            self.claude / "scripts" / SKILL,
        ):
            with self.subTest(launcher=str(launcher)):
                self.assertEqual(self.probe(launcher), expected)

    def test_workflow_skills_do_not_name_impeccable(self):
        for skills_dir in SKILL_ROOTS:
            for name in OPT_IN_SKILLS:
                tree = self.root / skills_dir / name
                with self.subTest(tree=str(tree)):
                    self.assertTrue((tree / "SKILL.md").is_file(), f"{tree} missing")
                    for dirpath, _, files in os.walk(tree, followlinks=True):
                        for file_name in files:
                            path = Path(dirpath) / file_name
                            self.assertNotIn(
                                b"impeccable", path.read_bytes().lower(), str(path)
                            )

    def test_retired_skills_are_not_installed(self):
        for skills_dir in SKILL_ROOTS:
            for name in RETIRED_SKILLS:
                path = self.root / skills_dir / name
                with self.subTest(path=str(path)):
                    self.assertFalse(os.path.lexists(path), f"{path} still installed")


if __name__ == "__main__":
    unittest.main()
