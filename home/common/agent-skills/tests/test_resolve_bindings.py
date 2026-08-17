"""Contract tests for scripts/resolve-bindings.

Runs the resolver as a subprocess against temporary repository roots and parses
its `key=value` lines. Covers the attempt budget (`agentBudgetMinutes`, the
wall-clock allowance for one attempt) and `maxParallel`.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve-bindings"
REPO_ROOT = Path(__file__).resolve().parents[4]


def run(root: Path) -> tuple[int, dict[str, str], str]:
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--repo-root", str(root)],
        capture_output=True, text=True, timeout=30,
    )
    bindings = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    return proc.returncode, bindings, proc.stderr


class ResolveBindingsTest(unittest.TestCase):
    def make_root(self, config: object | None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        if config is not None:
            (root / ".claude").mkdir()
            (root / ".claude" / "skills.config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
        return root

    def test_defaults_apply_without_a_config_file(self):
        code, bindings, err = run(self.make_root(None))
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "90")
        self.assertEqual(bindings["maxParallel"], "2")
        self.assertEqual(err, "")

    def test_configured_orchestration_values_are_emitted(self):
        root = self.make_root(
            {"orchestration": {"agentBudgetMinutes": 240, "maxParallel": 5}}
        )
        code, bindings, err = run(root)
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "240")
        self.assertEqual(bindings["maxParallel"], "5")
        self.assertEqual(err, "")

    def test_invalid_values_fall_back_with_a_diagnostic_and_exit_zero(self):
        for bad in (0, -5, "90", True, 1.5, None):
            with self.subTest(value=bad):
                root = self.make_root({"orchestration": {"agentBudgetMinutes": bad}})
                code, bindings, err = run(root)
                self.assertEqual(code, 0)
                self.assertEqual(bindings["agentBudgetMinutes"], "90")
                if bad is not None:
                    self.assertIn("resolve-bindings:", err)
                    self.assertIn("agentBudgetMinutes", err)
                else:
                    self.assertEqual(err, "")

    def test_adding_the_config_does_not_disturb_the_other_bindings(self):
        plain = self.make_root(None)
        configured = self.make_root(
            {"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}}
        )
        _, a, _ = run(plain)
        _, b, _ = run(configured)
        a.pop("repoRoot"), b.pop("repoRoot")
        a.pop("agentBudgetMinutes"), b.pop("agentBudgetMinutes")
        a.pop("maxParallel"), b.pop("maxParallel")
        self.assertEqual(a, b)

    def test_the_committed_repository_config_sets_the_attempt_budget(self):
        code, bindings, _ = run(REPO_ROOT)
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "180")
        self.assertEqual(bindings["maxParallel"], "2")
        committed = json.loads(
            (REPO_ROOT / ".claude" / "skills.config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(committed), ["orchestration"])
        self.assertEqual(committed["orchestration"]["agentBudgetMinutes"], 180)


if __name__ == "__main__":
    unittest.main()
