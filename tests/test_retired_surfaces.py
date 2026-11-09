"""Issue 688: the retired issue pipeline's skills, agents and launcher stay gone.

Each name is spelled in pieces so this file never matches its own search.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("from-" "issue", "ship-" "issue", "issue-" "owner", "claude-" "orchestrate", "skills/" "sdd")
WORD = "mech" "anic"
RETIRED_PATTERN = "|".join(
    [*NAMES[:-1], NAMES[-1] + "([^[:alnum:]_-]|$)", "(^|[^[:alnum:]_])" + WORD + "([^[:alnum:]_]|$)"])
EXCLUDED = (":!.agents/artifacts", ":!.agents/knowledge/archive/path-migrations",
            ":!tests/fixtures/retained-review-evidence")


def retired_hits(root: Path) -> list[str]:
    found = subprocess.run(
        ["git", "-C", str(root), "grep", "-nIE", RETIRED_PATTERN, "--", ".", *EXCLUDED],
        capture_output=True, text=True, check=False)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"git grep failed ({found.returncode}): {found.stderr.strip()}")
    return found.stdout.splitlines()


class RetiredSurfacesTest(unittest.TestCase):
    def scratch(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        return root

    def test_every_retired_name_is_found(self):
        planted = {f"f{i}.md": f"see {name}/x\n" for i, name in enumerate(NAMES)}
        planted["w.md"] = f"the {WORD} agent\n"
        hits = retired_hits(self.scratch(planted))
        self.assertEqual(sorted(h.split(":", 1)[0] for h in hits), sorted(planted))

    def test_near_misses_and_excluded_paths_are_not_found(self):
        root = self.scratch({
            "ok.md": f"{WORD}al {WORD}s .superpowers/sdd/x sdd-gate {NAMES[4]}-gate\n",
            ".agents/artifacts/plans/p.md": f"{NAMES[0]}\n",
            ".agents/knowledge/archive/path-migrations/a.json": f"{NAMES[1]}\n",
            "tests/fixtures/retained-review-evidence/b.json": f"{NAMES[4]}/SKILL.md\n",
        })
        self.assertEqual(retired_hits(root), [])

    def test_the_tree_names_no_retired_surface(self):
        self.assertEqual(retired_hits(ROOT), [])


if __name__ == "__main__":
    unittest.main()
