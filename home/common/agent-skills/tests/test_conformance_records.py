"""Contract tests for how the conformance run treats decision records: an added
record is judged against the size and form rules (B21, B22) and listed in the
never-rise check's facts, a record carried from the merge base is not, and a
migrated one is no addition. Split from test_conformance_checks.py to keep that
file under the size budget (rule B17)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from .conformance_test_support import (
    CLEAN_AREA, CLEAN_MAP, INTEGRATION_REF, ReportAssertions, commit_all, fixture, git,
    make_root, run,
)
from .test_conformance_checks import write_file

TIER = "integration"  # every case commits a real git repository and runs the conformance engine


class RecordNeverRiseTest(ReportAssertions, unittest.TestCase):
    """The never-rise check's treatment of decision records, judged through one
    `ci` run on a committed root whose integration ref the fixture moves."""

    CHECK_ID = "verification.violations.never_rise"

    def ci(self, root: Path) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"],
                check["facts"]]

    REC = "docs/areas/demo/adr/001-demo.md"

    def record_root(self, tmp: Path) -> tuple[Path, str]:
        """A root whose base holds a committed, lint-clean area `demo`; its sha."""
        root = make_root(tmp)
        write_file(root, "docs/CONTEXT-MAP.md",
                   CLEAN_MAP.replace("./fixture-CONTEXT.md", "./areas/demo/CONTEXT.md"))
        (root / "docs/fixture-CONTEXT.md").unlink()
        write_file(root, "docs/areas/demo/CONTEXT.md", CLEAN_AREA)
        commit_all(root, "area")
        return root, self.mark_base(root)

    def mark_base(self, root: Path) -> str:
        git(root, "update-ref", INTEGRATION_REF, "HEAD")
        return git(root, "rev-parse", "HEAD").strip()

    def record(self, root: Path, relative: str, number: int, body: str) -> None:
        write_file(root, relative, f"# ADR-demo-00{number} \u2014 Demo\n\n{body}")
        commit_all(root, f"record {number}")

    def passed_facts(self, root: Path) -> dict:
        code, _, by_id = self.ci(root)
        self.assertEqual(code, 0)
        return by_id[self.CHECK_ID]["facts"]

    def assert_rose(self, root: Path, base: str, rule: str, base_count: int, line: int,
                    rules: list, added: list | None = None) -> None:
        code, report, by_id = self.ci(root)
        self.assertEqual([code, report["outcome"]], [1, {
            "status": "failed", "primary_check_id": self.CHECK_ID}])
        listed = {"added_records": added, "added_record_count": len(added)} if added else {}
        self.assertEqual(self.summary(by_id[self.CHECK_ID]), [
            "failed", "violation_count_rose", "violations.never_rise.reduce",
            {"merge_base": base, "rule": rule, "base_count": base_count, "branch_count": 1,
             "violations": [f"{rule} {(added or [self.REC])[0]}:{line}"], "rules": rules, **listed}])
        self.assert_validates(report)

    def test_an_added_record_over_the_cap_with_a_status_line_turns_ci_red_and_is_listed(self):
        with fixture() as tmp:
            root, base = self.record_root(tmp)
            write_file(root, "notes/plain.txt")
            self.record(root, self.REC, 1, "- **Status:** accepted\n\n" + "x" * 1950 + "\n")
            self.assert_rose(root, base, "B21", 0, 5, ["B21", "B22"], [self.REC])

    def test_an_added_conforming_record_passes_and_is_listed(self):
        with fixture() as tmp:
            root, base = self.record_root(tmp)
            self.record(root, self.REC, 1, "One paragraph naming the rejected alternative.\n")
            self.assertEqual(self.passed_facts(root), {
                "merge_base": base, "added_records": [self.REC], "added_record_count": 1})

    def test_an_over_cap_record_that_grows_turns_ci_red(self):
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            self.record(root, self.REC, 1, "x" * 1574 + "\n")
            base = self.mark_base(root)
            self.record(root, self.REC, 1, "x" * 1575 + "\n")
            self.assert_rose(root, base, "B21", 1, 3, ["B21"])

    def test_a_deleted_breaching_record_does_not_cover_an_added_one(self):
        old, new = "docs/areas/demo/adr/001-old.md", "docs/areas/demo/adr/002-new.md"
        prose = "".join(f"Line {n} of the context about the queue backend.\n" for n in range(8))
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            self.record(root, old, 1, "- **Status:** accepted\n\n## Context\n\n" + prose)
            base = self.mark_base(root)
            git(root, "rm", "-q", old)
            self.record(root, new, 2, f"- **Status:** accepted\n\n{prose}Superseded by the new backend.\n")
            self.assertRegex(git(root, "diff-tree", "-r", "-M", "--diff-filter=R",
                                 "--name-status", base, "HEAD"), rf"R\d+\t{old}\t{new}")
            self.assert_rose(root, base, "B22", 1, 3, ["B22"], [new])

    def test_more_added_records_than_the_list_holds_are_counted(self):
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            paths = [f"docs/areas/demo/adr/00{n}-r{n}.md" for n in range(1, 10)]
            for n, path in enumerate(paths, 1):
                self.record(root, path, n, f"Paragraph {n}.\n")
            facts = self.passed_facts(root)
            self.assertEqual([facts["added_record_count"], facts["added_records"]],
                             [9, paths[:8]])

    ADDED_LINE = "added record "

    def added_lines(self, root: Path) -> list[str]:
        """The records the run's stderr names, one `ADDED_LINE` line each."""
        code, _, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        return [line[len(self.ADDED_LINE):] for line in err.splitlines()
                if line.startswith(self.ADDED_LINE)]

    def test_a_branch_adding_nine_records_names_every_one_in_the_ci_output(self):
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            paths = [f"docs/areas/demo/adr/00{n}-r{n}.md" for n in range(1, 10)]
            for n, path in enumerate(paths, 1):
                self.record(root, path, n, f"Paragraph {n}.\n")
            self.assertEqual(self.added_lines(root), paths)

    def test_two_records_sharing_their_first_200_characters_are_both_named(self):
        stem = "docs/areas/demo/adr/001-" + "a" * 200
        paths = [f"{stem}-{tail}.md" for tail in ("one", "two")]
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            for path in paths:
                self.record(root, path, 1, "One paragraph.\n")
            self.assertEqual(paths[0][:200], paths[1][:200])
            self.assertEqual(self.added_lines(root), paths)

    def test_a_branch_adding_no_record_names_none(self):
        with fixture() as tmp:
            root, _ = self.record_root(tmp)
            write_file(root, "notes/plain.txt")
            commit_all(root, "note")
            self.assertEqual(self.added_lines(root), [])
