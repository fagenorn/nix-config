"""The decision-record rules of `agent_tools.delivery.context_map_lint`.

The suite holds `standard:B18` and `standard:B19` by judging the record
enforcers of `agent_tools.delivery.context_map_lint` on records built in memory
and on real git worlds, so the rule index lists this file; the command's own
findings are pinned beside them.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import context_map_lint, never_rise, rule_ids
from agent_tools.delivery.context_map_lint import (
    RECORD_ENFORCERS, RECORD_SIZE_ENFORCER, RECORD_FORM_RULE, RECORD_SIZE_RULE, find_record_form,
    find_record_size, is_record_migration, is_record_path, record_violations)


REPO_ROOT = Path(__file__).parents[1]
LINTER = REPO_ROOT / "python/agent_tools/delivery/context_map_lint.py"
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"

P = "docs/areas/a/adr/001-a.md"
H = "# ADR-a-001 — T\n".encode()
V = never_rise.Violation

MAP = (
    "## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n"
    "| A | [area](areas/a/CONTEXT.md) | x | `docs/CONTEXT-MAP.md` |\n\n"
    "## Terms\n| Term | Area |\n|---|---|\n| Thing | A |\n")
AREA = "---\narea: a\nbudget: 200\n---\n\n**Thing**: a term\n"


class ContextMapLintTest(unittest.TestCase):
    def run_lint(self, root, context_map, *extra):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root), "--context-map", str(context_map), *extra],
            text=True, capture_output=True,
        )

    def test_selected_valid_map_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = root / "CONTEXT-MAP.md"
            area = root / "area.md"
            area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
            context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n")
            (root / "main.py").write_text("")
            self.assertEqual(self.run_lint(root, context_map).returncode, 0)

    def test_relative_and_outside_maps_are_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = subprocess.run([sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root), "--context-map", "CONTEXT-MAP.md"], text=True, capture_output=True)
            self.assertEqual(relative.returncode, 2)
            outside = self.run_lint(root, Path(temp).parent / "outside.md")
            self.assertEqual(outside.returncode, 2)

    def test_missing_context_map_and_malformed_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = subprocess.run([sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root)], text=True, capture_output=True)
            self.assertEqual(missing.returncode, 2)
            context_map = root / "CONTEXT-MAP.md"
            context_map.write_text("not a context map")
            self.assertEqual(self.run_lint(root, context_map).returncode, 1)

    def over_budget_map(self, root):
        """A map the default lint fails on its 150-line budget alone."""
        area = root / "area.md"
        area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
        context_map = root / "CONTEXT-MAP.md"
        context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n" + "\n" * 150)
        (root / "main.py").write_text("")
        return context_map

    def repo_lint(self, root, body):
        script = root / "repo-lint.py"
        script.write_text(body)
        return [sys.executable, str(script)]

    def test_without_a_repo_lint_the_map_budget_still_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_lint(root, self.over_budget_map(root))
            self.assertEqual(result.returncode, 1)
            self.assertIn("budget 150", result.stderr)

    def test_a_map_the_repo_lint_accepts_is_not_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context_map = self.over_budget_map(root)
            command = self.repo_lint(root, "import os, sys\nprint('repo lint in', os.getcwd(), sys.argv[1:])\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command, "--flag", "docs")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"repo lint in {root} ['--flag', 'docs']\n")
            self.assertEqual(result.stderr, "")

    def test_the_repo_lint_findings_and_status_are_the_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            area = root / "area.md"
            area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
            context_map = root / "CONTEXT-MAP.md"
            context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n")
            (root / "main.py").write_text("")
            self.assertEqual(self.run_lint(root, context_map).returncode, 0)
            command = self.repo_lint(root, "import sys\nprint('map over the repo budget', file=sys.stderr)\nsys.exit(1)\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "map over the repo budget\n")

    def test_the_repo_lint_runs_in_its_entry_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context_map = self.over_budget_map(root)
            scripts = root / "scripts"
            scripts.mkdir()
            lint = scripts / "lint.py"
            lint.write_text(f"#!{sys.executable}\nimport os\nprint('repo lint in', os.getcwd())\n")
            lint.chmod(0o755)
            result = self.run_lint(root, context_map, "--repo-lint-cwd", str(scripts), "--repo-lint", "./lint.py")
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f"repo lint in {scripts}\n", ""))
            in_root = self.run_lint(root, context_map, "--repo-lint", "./lint.py")
            self.assertEqual(in_root.returncode, 2)

    def test_the_repo_lint_exit_2_is_passed_through(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            command = self.repo_lint(root, "import sys\nsys.exit(2)\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command)
            self.assertEqual((result.returncode, result.stderr), (2, ""))

    def test_repo_lint_cwd_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            for cwd in ("scripts", str(root / "absent"), str(root.parent), str(context_map)):
                with self.subTest(cwd=cwd):
                    result = self.run_lint(root, context_map, "--repo-lint-cwd", cwd, "--repo-lint", "true")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("--repo-lint-cwd", result.stderr)
            alone = self.run_lint(root, context_map, "--repo-lint-cwd", str(root))
            self.assertEqual(alone.returncode, 2)
            self.assertIn("Usage: context-map-lint --repo-root ", alone.stderr)

    def test_repo_lint_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            empty = self.run_lint(root, context_map, "--repo-lint")
            self.assertEqual(empty.returncode, 2)
            self.assertIn("Usage: context-map-lint --repo-root ", empty.stderr)
            absent = self.run_lint(root, context_map, "--repo-lint", str(root / "no-such-lint"))
            self.assertEqual(absent.returncode, 2)
            self.assertIn("cannot run the repository's lint", absent.stderr)
            outside = self.run_lint(root, root.parent / "outside.md", "--repo-lint", "true")
            self.assertEqual(outside.returncode, 2)
            stray = self.run_lint(root, context_map, "--other", "true")
            self.assertEqual(stray.returncode, 2)

    def record_tree(self, root, records):
        """A docs tree whose map and area are clean, holding `records` (path to bytes)."""
        for relative, content in {
                "docs/CONTEXT-MAP.md": MAP.encode(),
                "docs/areas/a/CONTEXT.md": AREA.encode(), **records}.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return root / "docs/CONTEXT-MAP.md"

    def test_the_command_neither_prints_nor_fails_on_a_form_breach(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            breaching = H + b"\n- **Status:** accepted\n\n## Context\n\n" + b"x" * 2000 + b"\n"
            context_map = self.record_tree(root, {P: breaching})
            result = self.run_lint(root, context_map)
            self.assertEqual(
                (result.returncode, result.stdout, result.stderr),
                (0, f"context-map-lint: {root} OK\n", ""))

    def test_a_duplicate_record_number_stays_a_plain_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context_map = self.record_tree(root, {
                "docs/areas/a/adr/001-a.md": "# ADR-a-001 — A\n\nOne paragraph.\n".encode(),
                "docs/areas/a/adr/001-b.md": "# ADR-a-001 — B\n\nOne paragraph.\n".encode()})
            result = self.run_lint(root, context_map)
            self.assertEqual(result.returncode, 1)
            self.assertIn("number 001 is already", result.stderr)

    def test_source_has_no_policy_discovery(self):
        source = LINTER.read_text(encoding="utf-8")
        for token in ("resolve-project", ".agents/project.json", "find_map(", "docs/CONTEXT-MAP.md"):
            self.assertNotIn(token, source)


class RecordFormTest(unittest.TestCase):
    def test_each_form_breach_yields_a_violation_and_one_paragraph_yields_none(self):
        rows = {
            "one paragraph": (H + b"\nOne paragraph.\n", []),
            "over the cap": (H + b"\n" + b"x" * 1600 + b"\n", [V("B18", P, 3, 1620)]),
            "heading": (H + b"\n## Context\nPara.\n", [V("B19", P, 3, 1)]),
            "status line": (H + b"\n- **Status:** accepted\nPara.\n", [V("B19", P, 3, 1)]),
            "bare status line": (H + b"\n**Status:** accepted\nPara.\n", [V("B19", P, 3, 1)]),
            "heading under carriage returns": (H + b"\n##\r\nPara.\r\n", [V("B19", P, 3, 1)]),
            "second paragraph": (H + b"\nOne.\n\nTwo.\n", [V("B19", P, 5, 1)]),
            "numbered sub-decisions": (
                H + b"\n1. First choice\n2. Second choice\n", [V("B19", P, 3, 2)]),
            "setext heading": (H + b"\nContext\n-------\nPara.\n", [V("B19", P, 4, 1)]),
            "fence": (H + b"\nPara.\n```\ncode\n```\n", [V("B19", P, 4, 2)]),
            "quote": (H + b"\n> Quoted.\n", [V("B19", P, 3, 1)]),
            "Formerly in prose": (
                H + b"\nOne.\n\nSee **Formerly:** ADR-b-001 here.\n", [V("B19", P, 5, 1)]),
            "Formerly after the paragraph": (
                H + b"\nOne.\n\n**Formerly:** ADR-b-001\n", [V("B19", P, 5, 1)]),
            "emphasised status line": (H + b"\n*Status:* accepted\nPara.\n", [V("B19", P, 3, 1)]),
            "adjacent bold sub-decisions": (
                H + b"\n**D1.** First choice.\n**D2.** Second choice.\n", [V("B19", P, 4, 1)]),
            "two Formerly lines": (
                H + b"\n**Formerly:** ADR-b-001\n**Formerly:** ADR-c-001\n\nPara.\n",
                [V("B19", P, 4, 2)]),
            "soft-wrapped prose that starts a line with an ordinal": (
                H + b"\nWe chose protocol version\n2. It supports retries.\n", []),
            "an ordinal opening a block": (
                H + b"\n2. It supports retries.\n", [V("B19", P, 3, 1)]),
        }
        for name, (content, expected) in rows.items():
            with self.subTest(name):
                self.assertEqual(record_violations(P, content), expected)

    def test_the_cap_is_1500_bytes(self):
        self.assertEqual(record_violations(P, H + b"\n" + b"x" * 1480 + b"\n"), [])
        self.assertEqual(
            record_violations(P, H + b"\n" + b"x" * 1481 + b"\n"), [V("B18", P, 3, 1501)])

    def test_a_record_with_no_paragraph_breaches_the_form(self):
        for name, content in {"header alone": H, "empty": b""}.items():
            with self.subTest(name):
                self.assertEqual(record_violations(P, content), [V("B19", P, 1, 1)])

    def test_a_formerly_line_is_not_a_second_paragraph(self):
        self.assertEqual(
            record_violations(P, H + b"\n**Formerly:** ADR-b-001\n\nPara.\n"), [])

    def test_only_records_are_judged(self):
        two_paragraphs = H + b"\n## Context\nOne.\n\nTwo.\n" + b"x" * 2000 + b"\n"
        others = ["docs/areas/a/CONTEXT.md", "docs/areas/a/adr/README.md", "docs/guides/x.md"]
        blobs = {path: two_paragraphs for path in others}
        blobs[P] = H + b"\n- **Status:** accepted\n"
        snapshot = never_rise.Snapshot("a" * 40, {}, blobs)
        self.assertEqual(find_record_size(snapshot), [])
        self.assertEqual(find_record_form(snapshot), [V("B19", P, 3, 1)])
        self.assertTrue(is_record_path(P))
        for path in [*others, "docs/areas/a/adr/sub/001-a.md", P + "/x"]:
            with self.subTest(path):
                self.assertFalse(is_record_path(path))

    def test_an_over_cap_record_may_shrink_or_hold_but_not_grow(self):
        def snapshot(size):
            return never_rise.Snapshot("a" * 40, {}, {P: H + b"\n" + b"x" * size + b"\n"})
        base = snapshot(1580)
        for size, expected in ((1580, ()), (1530, ()), (1581, (
                never_rise.Rise("B18", 1, 1, (V("B18", P, 3, 1601),)),))):
            with self.subTest(size=size):
                self.assertEqual(
                    never_rise.compare(base, snapshot(size), {}, RECORD_ENFORCERS), expected)

    def test_an_added_breach_rises_even_when_another_records_breaches_go(self):
        b = "docs/areas/a/adr/002-b.md"
        moved = "docs/areas/b/adr/001-a.md"
        p_body = b"\n- **Status:** accepted\n\n## Context\n\nPara.\n"
        p_bytes = H + p_body
        base = never_rise.Snapshot("a" * 40, {}, {P: p_bytes})
        b_header = "# ADR-a-002 \u2014 B\n".encode()
        rise = lambda path, line, count: (never_rise.Rise(  # noqa: E731
            "B19", 1, 1, (V("B19", path, line, count),)),)
        rows = {
            "unchanged": ({P: p_bytes}, {}, ()),
            "moved": ({moved: p_bytes}, {moved: P}, ()),
            "migration": ({moved: "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-a-001\n".encode()
                           + p_body}, {moved: P}, ()),
            "supersession paired as a rename": (
                {b: b_header + b"\n- **Status:** accepted\n\n## Context\n\nPara. Superseded.\n"},
                {b: P}, rise(b, 3, 3)),
            "a second status line": (
                {P: H + b"\n- **Status:** accepted\n- **Status:** again\n\n## Context\n\nPara.\n"},
                {}, rise(P, 3, 4)),
            "fixed and another added": (
                {P: H + b"\nOne paragraph.\n", b: b_header + b"\n- **Status:** accepted\nPara.\n"},
                {}, rise(b, 3, 1)),
            "deleted and another added": (
                {b: b_header + b"\n- **Status:** accepted\nPara.\n"}, {}, rise(b, 3, 1)),
        }
        for name, (blobs, renamed, expected) in rows.items():
            with self.subTest(name):
                branch = never_rise.Snapshot("b" * 40, {}, blobs)
                self.assertEqual(
                    never_rise.compare(base, branch, renamed, RECORD_ENFORCERS), expected)

    def test_moving_a_record_over_the_size_cap_is_not_a_rise(self):
        moved = "docs/areas/b/adr/001-a.md"
        header = "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-a-001\n".encode()
        over = b"\n" + b"x" * 1600 + b"\n"
        near_cap = b"\n" + b"x" * 1470 + b"\n"
        rows = {
            "over the cap": (H + over, header + over, ()),
            "under the cap, over it after the move": (H + near_cap, header + near_cap, ()),
            "body amended": (H + over, header + over + b"More.\n", ("B18",)),
            "blank lines appended": (H + over, header + over + b"\n" * 5, ("B18",)),
            "a padded blank line appended": (
                H + over, header + over + b" " * 400 + b"\n", ("B18",)),
            "two Formerly lines": (
                H + over, header + b"**Formerly:** ADR-c-001\n" + over, ("B18",)),
        }
        for name, (old, new, expected) in rows.items():
            with self.subTest(name):
                base = never_rise.Snapshot("a" * 40, {}, {P: old})
                branch = never_rise.Snapshot("b" * 40, {}, {moved: new})
                found = never_rise.compare(base, branch, {moved: P}, (RECORD_SIZE_ENFORCER,))
                self.assertEqual(tuple(rise.rule for rise in found), expected if expected else ())

    def test_a_file_that_was_no_record_is_not_a_migration_whatever_its_size(self):
        guide = "docs/guides/old.md"
        moved = "docs/areas/a/adr/002-b.md"
        body = b"\n" + b"x" * 2000 + b"\n"
        base = never_rise.Snapshot("a" * 40, {}, {guide: b"# Guide\n" + body})
        branch = never_rise.Snapshot(
            "b" * 40, {}, {moved: "# ADR-a-002 \u2014 B\n".encode() + body})
        self.assertEqual(
            never_rise.compare(base, branch, {moved: guide}, RECORD_ENFORCERS),
            (never_rise.Rise("B18", 0, 1, (V("B18", moved, 3, 2020),)),))

    def test_the_record_rules_are_rules_of_the_bar(self):
        rules = rule_ids.sections(BAR.read_text(encoding="utf-8"))
        self.assertIn(RECORD_SIZE_RULE, rules)
        self.assertIn(RECORD_FORM_RULE, rules)

    def test_a_record_migration_is_an_unchanged_body(self):
        old = H + b"\nOne paragraph.\n"
        rows = {
            "renumbered with a Formerly line": (
                "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-a-001\n".encode() + b"\nOne paragraph.\n",
                True),
            "a blank line added": (old + b"\n", True),
            "three blank lines added": (old + b"\n\n\n", False),
            "a padded blank line added": (old + b" " * 400 + b"\n", False),
            "a second Formerly line": (
                "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-a-001\n**Formerly:** ADR-c-001\n"
                .encode() + b"\nOne paragraph.\n", False),
            "a padded header title": (
                "# ADR-b-001 \u2014 T".encode() + b" padded" * 150 + b"\n\n**Formerly:** ADR-a-001\n"
                b"\nOne paragraph.\n", False),
            "a retitled header": (
                "# ADR-b-001 \u2014 U\n\n**Formerly:** ADR-a-001\n\nOne paragraph.\n".encode(), False),
            "a Formerly line with trailing spaces": (
                "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-a-001".encode() + b" " * 3000
                + b"\n\nOne paragraph.\n", False),
            "a Formerly line naming another record": (
                "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-c-009\n\nOne paragraph.\n".encode(), False),
            "a Formerly slug thousands of characters long": (
                "# ADR-b-001 \u2014 T\n\n**Formerly:** ADR-".encode() + b"a" * 3000
                + b"-001\n\nOne paragraph.\n", False),
            "a header slug thousands of characters long": (
                "# ADR-".encode() + b"b" * 3000 + "-001 \u2014 T\n\nOne paragraph.\n".encode(), False),
            "converted to carriage returns": (old.replace(b"\n", b"\r\n"), False),
            "the paragraph amended": (H + b"\nOne paragraph, amended.\n", False),
            "a line added": (H + b"\nOne paragraph.\nMore.\n", False),
        }
        for name, (new, expected) in rows.items():
            with self.subTest(name):
                self.assertEqual(is_record_migration(old, new), expected)


if __name__ == "__main__":
    unittest.main()
