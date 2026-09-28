"""Seam 5: the installed conformance engine reports a promoted leftover (#127 D21).

Run: just agent-installed-skill-tests, which builds first and passes the built
home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Standard library only,
because that recipe sets no PYTHONPATH (D28).
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
REPO_ROOT = Path(__file__).resolve().parents[1]
LEFTOVER = b"Investigate before changing.\n"
CHECK_ID = "repository.residue.promoted_duplicate"


class InstalledPromotedDuplicateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = os.environ.get(INSTALLED_HOME_ENV)
        if home is None:
            raise unittest.SkipTest(f"{INSTALLED_HOME_ENV} is unset; run "
                                    "`just agent-installed-skill-tests`")
        cls.home = Path(home)

    def make_root(self, tmp):
        """Mirrors conformance_test_support.make_root: a root a clean doctor run passes."""
        root = tmp / "project"
        (root / ".agents/instructions").mkdir(parents=True)
        for relative in (".agents/project.json", ".agents/instructions/bootstrap.md",
                         "AGENTS.md", "CLAUDE.md"):
            shutil.copy2(REPO_ROOT / relative, root / relative)
        paths = json.loads((root / ".agents/project.json")
                           .read_text(encoding="utf-8"))["bindings"]["paths"]
        for member in ("context", "standards", "architecture", "operations", "hints",
                       "rejections"):
            for entry in paths[member]:
                if not (root / entry).exists():
                    (root / entry).mkdir(parents=True)
        (root / ".gitignore").write_text(".agents/runtime/\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        return root

    def test_the_installed_engine_fails_an_unchanged_leftover(self):
        with tempfile.TemporaryDirectory() as scratch:
            tmp = Path(scratch).resolve()
            root = self.make_root(tmp)
            # make_root already creates docs/ (a standards knowledge path), so use notes/.
            (root / "notes").mkdir()
            (root / "notes/lesson.md").write_bytes(LEFTOVER)
            candidate = root / ".agents/knowledge/promotions/candidates/c.json"
            candidate.parent.mkdir(parents=True)
            candidate.write_text(json.dumps({
                "kind": "promotion-candidate", "state": "promoted",
                "local_duplicates": [{"repository": "fagenorn/nix-config",
                                      "path": "notes/lesson.md",
                                      "sha256": hashlib.sha256(LEFTOVER).hexdigest(),
                                      "disposition": "remove"}]}), encoding="utf-8")
            proc = subprocess.run(
                [str(self.home / ".agents/bin/conformance"), "run", "--purpose", "doctor",
                 "--offline", "--repo-root", str(root)],
                env={"HOME": str(self.home), "PATH": os.environ["PATH"],
                     "TMPDIR": str(tmp), "LANG": "C"},
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            check = {c["id"]: c for c in json.loads(proc.stdout)["checks"]}[CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"], check["repair_id"],
                              check["facts"]["count"]],
                             ["failed", "promoted_duplicate_present",
                              "promotion.duplicate.remove", 1])
