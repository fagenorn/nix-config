"""Issues 688 and 689: the retired skills, agents, launcher and helper names stay gone.

Each name is spelled in pieces so this file never matches its own search.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("from-" "issue", "ship-" "issue", "issue-" "owner", "claude-" "orchestrate", "skills/" "sdd")
WORD = "mech" "anic"
GATE = "sdd" "-gate"
RETIRED_PATTERN = "|".join(
    [*NAMES[:-1], NAMES[-1] + "([^[:alnum:]_-]|$)", "(^|[^[:alnum:]_])" + WORD + "([^[:alnum:]_]|$)"])
EXCLUDED = (":!.agents/artifacts", ":!.agents/knowledge/archive/path-migrations")

# Issue 689: the retired ledger cluster's command, module and test names, each built from its parts.
_DASHED = (("workflow", "state"), ("sdd", "workspace"), ("task", "brief"),
           ("clear", "library", "bytecode"), ("launch", "scope"), ("launch", "commit"),
           ("sdd", "gate"), ("sdd", "brief"), ("ship", "delivery"), ("acceptance", "record"),
           ("review", "package"), ("review", "range"),
           ("derive", "review", "feasibility", "fixtures"), ("replay", "retained"),
           ("skill", "sections"), ("verification", "observe"), ("agent", "evidence"),
           ("context", "meter"), ("ledger", "archive"), ("ledger", "snapshot"),
           ("worktree", "reconcile"), ("worktree", "mapping"), ("agent", "costs"),
           ("agent", "model", "drift"), ("agent", "retained", "tests"))
_UNDERSCORED = (("workflow", "state"), ("workflow", "delivery"), ("workflow", "delivery", "build"),
                ("workflow", "delivery", "wire"), ("delivery", "model"),
                *(("attempt", s) for s in ("custody", "delivery", "identity", "observations", "store")),
                ("attempt", "delivery", "store"), ("launch", "scope"), ("launch", "commit"),
                ("launch", "processes"), ("sdd", "gate"), ("sdd", "brief"), ("ship", "delivery"),
                ("ship", "delivery", "compile"), ("acceptance", "record"),
                *(("review", s) for s in ("actual", "budget", "derivation", "expansion", "forecast",
                                          "git", "issue100", "issue121", "pack", "package",
                                          "projection", "publish", "range", "record", "replay",
                                          "task7", "witness")),
                ("derive", "review", "feasibility", "fixtures"), ("replay", "retained"),
                ("retained", "root", "copy"), ("skill", "sections"), ("verification", "observe"),
                ("verification", "blocker"), ("agent", "evidence"), ("context", "meter"),
                *(("context", "meter", s) for s in ("commands", "crossing", "transcript")),
                ("phase", "budget"), ("agent", "costs"), ("agent", "cache", "report"),
                ("transcript", "calls"),
                *(("agent", "owner", s) for s in ("report", "replay", "rollup")),
                *(("agent", "boot", s) for s in ("report", "rollup")),
                ("agent", "model", "drift"),
                *(("agent", "model", "drift", s) for s in ("routing", "scheduling", "schema")),
                ("ledger", "archive"), ("ledger", "snapshot"), ("worktree", "reconcile"),
                ("worktree", "mapping"),
                ("owner", "transcripts"), ("", "delivery", "model", "fixtures"),
                *((*p, "test", "support") for p in (("agent", "model", "drift"),
                                                    ("retained", "evidence"),
                                                    ("retained", "review"),
                                                    ("hostile", "git"))))
ISSUE_689_NAMES = tuple(sorted({"-".join(p) for p in _DASHED} | {"_".join(p) for p in _UNDERSCORED}))
ISSUE_689_PATTERN = "(^|[^[:alnum:]])(" + "|".join(ISSUE_689_NAMES) + ")([^[:alnum:]_]|$)"


def retired_hits(root: Path) -> list[str]:
    found = subprocess.run(
        ["git", "-C", str(root), "grep", "-nIE", RETIRED_PATTERN, "--", ".", *EXCLUDED],
        capture_output=True, text=True, check=False)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"git grep failed ({found.returncode}): {found.stderr.strip()}")
    return found.stdout.splitlines()


def issue_689_hits(root: Path) -> list[str]:
    found = subprocess.run(
        ["git", "-C", str(root), "grep", "-nIE", ISSUE_689_PATTERN, "--", ".", *EXCLUDED],
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
            "ok.md": f"{WORD}al {WORD}s .superpowers/sdd/x {GATE} {NAMES[4]}-gate\n",
            ".agents/artifacts/plans/p.md": f"{NAMES[0]}\n",
            ".agents/knowledge/archive/path-migrations/a.json": f"{NAMES[1]}\n",
        })
        self.assertEqual(retired_hits(root), [])

    def test_the_tree_names_no_retired_surface(self):
        self.assertEqual(retired_hits(ROOT), [])

    def test_every_issue_689_name_is_found_in_each_spelling(self):
        planted = {}
        for i, name in enumerate(ISSUE_689_NAMES):
            planted[f"a{i}.md"] = f"run `{name} --help`\n"
            planted[f"b{i}.nix"] = f'".agents/bin/{name}".source = x;\n'
            planted[f"c{i}.py"] = f"from agent_tools import {name}\n"
        hits = issue_689_hits(self.scratch(planted))
        self.assertEqual(sorted(h.split(":", 1)[0] for h in hits), sorted(planted))

    def test_issue_689_near_misses_are_not_found(self):
        root = self.scratch({
            "ok.md": "diff-scope agent-run-profile verify_checks run_profile host_admission "
                     "attempt_budget_minutes review_gate.py artifact-budget per-task member\n",
            "longer.md": "a " + "workflow" "-stateful b " + "review" "-packager c\n",
            ".agents/artifacts/plans/p.md": "workflow" "-state\n",
            ".agents/knowledge/archive/path-migrations/a.json": "agent" "-costs\n",
        })
        self.assertEqual(issue_689_hits(root), [])

    def test_the_tree_names_no_issue_689_surface(self):
        self.assertEqual(issue_689_hits(ROOT), [])


if __name__ == "__main__":
    unittest.main()
