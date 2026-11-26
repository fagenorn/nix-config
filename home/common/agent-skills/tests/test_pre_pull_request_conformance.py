"""The `conformance` recipe runs the same argv as the CI Conformance step, and one run names every broken rule."""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from .conformance_test_support import (
    REPO_ROOT,
    ReportAssertions,
    commit_all,
    fixture,
    make_root,
    run,
)

TIER = "integration"  # commits a real git repository and runs the conformance engine


def recipe_lines(name: str) -> list[str]:
    lines = (REPO_ROOT / "justfile").read_text("utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(name + ":"):
            body: list[str] = []
            for follower in lines[index + 1:]:
                if not follower.startswith((" ", "\t")):
                    break
                body.append(follower.strip())
            return body
    raise AssertionError(f"the justfile has no {name} recipe")


def conformance_tail(command: str) -> list[str]:
    tokens = shlex.split(command)
    if "--command" not in tokens or tokens[tokens.index("--command") + 1:][:1] != ["conformance"]:
        raise AssertionError(f"--command is not followed by conformance in: {command}")
    return tokens[tokens.index("--command") + 2:]


def ci_run_line() -> str:
    lines = (REPO_ROOT / ".github/workflows/conformance.yaml").read_text("utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "- name: Run conformance":
            following = lines[index + 1].strip()
            return following.removeprefix("run: ")
    raise AssertionError("the CI workflow has no Run conformance step")

FLAKE_ARGUMENT = "{{justfile_directory()}}#agent-platform"
QUOTED_FLAKE = '{{quote(justfile_directory() + "#agent-platform")}}'


class PrePullRequestConformanceTest(ReportAssertions, unittest.TestCase):
    def test_the_conformance_command_names_both_broken_rules_in_one_run(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "big.py").write_text("x = 1\n" * 1501, "utf-8")
            (root / "tests").mkdir()
            (root / "tests/test_skipped.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n"
                "    @unittest.skip('x')\n    def test_a(self):\n"
                "        self.assertEqual(1, 1)\n", "utf-8")
            commit_all(root, "two broken rules")
            code, out, err = run(*conformance_tail(recipe_lines("conformance")[0]), cwd=root)
        self.assertEqual(code, 1, err)
        report = json.loads(out)
        check = next(c for c in report["checks"] if c["id"] == "verification.violations.never_rise")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["reason_code"], "violation_count_rose")
        self.assertEqual(check["facts"]["rules"], ["B17", "B23"])
        self.assert_validates(report)

    def test_the_recipe_runs_conformance_as_the_ci_workflow_does(self):
        lines = recipe_lines("conformance")
        ci = shlex.split(ci_run_line())
        expected = [FLAKE_ARGUMENT if t == ".#agent-platform" else t for t in ci]
        self.assertEqual(len(lines), 1)
        self.assertEqual(ci.count(".#agent-platform"), 1)
        self.assertEqual(shlex.split(lines[0].replace(QUOTED_FLAKE, FLAKE_ARGUMENT)), expected)
        self.assertEqual(conformance_tail(lines[0]), ["run", "--purpose", "ci", "--lint-times"])

    def test_a_checkout_path_with_an_apostrophe_still_reaches_nix_as_one_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "Sam's Projects"
            checkout.mkdir()
            (checkout / "justfile").write_text((REPO_ROOT / "justfile").read_text("utf-8"), "utf-8")
            proc = subprocess.run(["just", "--dry-run", "conformance"], cwd=checkout, text=True,
                                  capture_output=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rendered = shlex.split(proc.stderr.strip())
        self.assertEqual(rendered[:3], ["nix", "shell", f"{checkout.resolve()}#agent-platform"])


if __name__ == "__main__":
    unittest.main()
