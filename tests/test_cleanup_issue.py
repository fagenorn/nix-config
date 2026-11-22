"""The cleanup issue core of `agent_tools.delivery.cleanup_issue` (#1462).

Measures the selection of the rule with the fewest violations, the whole-file
listing bounded by the batch, the marker as a whole line, the exact issue body
and the three outcomes of a run, over in-memory snapshots and a stub tracker.
"""

import unittest

from agent_tools.delivery.cleanup_issue import (
    RULES, CleanupRule, Issue, Outcome, draft, is_cleanup, listing, run)
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation

TIER = "integration"

REVISION = "a" * 40
MARKER_FX1 = "<!-- agent:cleanup v1 rule=FX1 -->"


def suffix_enforcer(rule: str, suffix: str) -> Enforcer:
    def find(snapshot: Snapshot) -> list[Violation]:
        return [Violation(rule, path, 1) for path in sorted(snapshot.line_counts)
                if path.endswith(suffix)]
    return Enforcer(rule, find)


R1 = CleanupRule(suffix_enforcer("FX1", ".one"), 5, "Fix FX1.")
R2 = CleanupRule(suffix_enforcer("FX2", ".two"), 5, "Fix FX2.")
R3 = CleanupRule(suffix_enforcer("FX3", ".three"), 5, "Fix FX3.")


def snapshot_of(*paths: str) -> Snapshot:
    return Snapshot(REVISION, {path: 1 for path in paths})


class StubTracker:
    def __init__(self, open_issues: list[Issue] | None = None):
        self.open = list(open_issues or [])
        self.created: list[tuple[str, str]] = []

    def open_issues(self) -> list[Issue]:
        return list(self.open)

    def create(self, title: str, body: str) -> int:
        number = 101 + len(self.created)
        self.created.append((title, body))
        self.open.append(Issue(number, body))
        return number


class CleanupRunTest(unittest.TestCase):
    def test_three_rules_and_no_open_issue_files_the_smallest_count(self):
        tracker = StubTracker()
        snapshot = snapshot_of("a.one", "b.one", "c.one", "a.two", "b.two")

        outcome = run(tracker, snapshot, (R1, R2, R3))

        self.assertEqual(outcome, Outcome("filed", 101, "FX2"))
        self.assertEqual(len(tracker.created), 1)
        title, body = tracker.created[0]
        self.assertEqual(title, "Clear 2 of the 2 violations of rule FX2")
        lines = body.splitlines()
        self.assertEqual(lines[0], "<!-- agent:cleanup v1 rule=FX2 -->")
        self.assertIn("FX2 a.two:1", lines)
        self.assertIn("FX2 b.two:1", lines)
        self.assertNotIn("FX1", body)

    def test_an_open_cleanup_issue_files_nothing(self):
        tracker = StubTracker([Issue(7, f"{MARKER_FX1}\nrenamed")])

        outcome = run(tracker, snapshot_of("a.one", "b.one", "c.one", "a.two", "b.two"), (R1, R2, R3))

        self.assertEqual(outcome, Outcome("open", 7, None))
        self.assertEqual(tracker.created, [])

    def test_the_lowest_open_cleanup_issue_is_named(self):
        tracker = StubTracker([Issue(12, MARKER_FX1), Issue(7, MARKER_FX1)])

        self.assertEqual(run(tracker, snapshot_of("a.one"), (R1,)), Outcome("open", 7, None))

    def test_all_counts_at_zero_file_nothing(self):
        tracker = StubTracker()

        outcome = run(tracker, snapshot_of("x.py"), (R1, R2, R3))

        self.assertEqual(outcome, Outcome("clean", None, None))
        self.assertEqual(tracker.created, [])

    def test_the_next_issue_is_filed_once_the_open_one_is_closed(self):
        tracker = StubTracker([Issue(7, MARKER_FX1)])
        snapshot = snapshot_of("a.one", "b.one", "c.one", "a.two", "b.two")

        self.assertEqual(run(tracker, snapshot, (R1, R2, R3)), Outcome("open", 7, None))
        self.assertEqual(tracker.created, [])
        tracker.open = [issue for issue in tracker.open if issue.number != 7]
        self.assertEqual(run(tracker, snapshot, (R1, R2, R3)), Outcome("filed", 101, "FX2"))
        self.assertEqual(run(tracker, snapshot, (R1, R2, R3)), Outcome("open", 101, None))
        self.assertEqual(len(tracker.created), 1)

    def test_a_hand_filed_issue_without_the_marker_is_not_a_cleanup_issue(self):
        tracker = StubTracker([Issue(9, "Clear 2 of the 2 violations of rule FX2\nhand filed")])

        outcome = run(tracker, snapshot_of("a.one", "b.one", "a.two", "b.two"), (R1, R2))

        self.assertEqual(outcome.action, "filed")
        self.assertEqual(len(tracker.created), 1)

    def test_equal_counts_choose_the_earlier_rule(self):
        tracker = StubTracker()

        outcome = run(tracker, snapshot_of("a.one", "b.one", "a.two", "b.two"), (R1, R2))

        self.assertEqual(outcome.rule, "FX1")

    def test_an_enforcer_emitting_another_rule_is_refused(self):
        tracker = StubTracker()
        rogue = CleanupRule(Enforcer("FX1", lambda snapshot: [Violation("FX9", "a", 1)]), 5, "x")

        with self.assertRaises(ValueError):
            run(tracker, snapshot_of("a"), (rogue,))
        self.assertEqual(tracker.created, [])


class MarkerTest(unittest.TestCase):
    def test_the_marker_counts_only_as_a_whole_line(self):
        self.assertTrue(is_cleanup("x\n<!-- agent:cleanup v1 rule=B17 -->\r\n"))
        self.assertFalse(is_cleanup("see <!-- agent:cleanup v1 rule=B17 --> here"))
        self.assertFalse(is_cleanup("<!-- agent:cleanup v2 rule=B17 -->"))
        self.assertFalse(is_cleanup("<!-- agent:claim v1 issue=3 -->"))


def at(path: str, *lines: int) -> list[Violation]:
    return [Violation("FX1", path, line) for line in lines]


class ListingTest(unittest.TestCase):
    def test_the_listing_takes_whole_files_up_to_the_batch(self):
        violations = at("a.py", 1, 2, 3) + at("b.py", 9) + at("c.py", 4, 5)

        self.assertEqual(listing(violations, 3), tuple(at("b.py", 9) + at("c.py", 4, 5)))

    def test_a_file_over_the_batch_is_listed_whole(self):
        violations = at("a.py", 5, 1, 4, 2, 3) + at("b.py", 1, 2, 3, 4, 5, 6)

        self.assertEqual(listing(violations, 2), tuple(at("a.py", 1, 2, 3, 4, 5)))

    def test_a_size_rule_lists_the_smallest_file_first(self):
        snapshot = Snapshot(REVISION, {"big.py": 2000, "small.py": 1512, "mid.py": 1600, "doc.md": 9000})
        tracker = StubTracker()

        run(tracker, snapshot)

        title, body = tracker.created[0]
        self.assertEqual(title, "Clear 1 of the 3 violations of rule B17")
        self.assertIn("B17 small.py:1512", body)
        self.assertNotIn("big.py", body)
        self.assertNotIn("mid.py", body)


class DraftTest(unittest.TestCase):
    def test_the_body_is_the_wire_format(self):
        rule = CleanupRule(R1.enforcer, 1, R1.guidance)

        result = draft(rule, [Violation("FX1", "a.one", 1), Violation("FX1", "b.one", 1)], REVISION)

        self.assertEqual(result.title, "Clear 1 of the 2 violations of rule FX1")
        self.assertEqual(result.body, (
            "<!-- agent:cleanup v1 rule=FX1 -->\n"
            f"Rule FX1 has 2 violations at {REVISION}. This issue clears 1 of them.\n"
            "\n"
            "## What to change\n"
            "\n"
            "Fix FX1.\n"
            "\n"
            "## Violations\n"
            "\n"
            "```text\n"
            "FX1 a.one:1\n"
            "```\n"
            "\n"
            "## Acceptance criteria\n"
            "\n"
            "- [ ] [code] Rule FX1 has at most 1 violations and none in the listed files"
            " — measured: `cleanup-issue violations --repo-root <checkout> --rule FX1`"
            " at the merge commit prints at most 1 lines and no line naming a listed file\n"))
        self.assertEqual((result.rule, result.count), ("FX1", 2))
        self.assertEqual(result.listed, (Violation("FX1", "a.one", 1),))


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_batch_and_guidance(self):
        for rule in RULES:
            self.assertGreaterEqual(rule.batch, 1)
            self.assertTrue(rule.guidance.strip())

    def test_the_rules_are_the_never_rise_enforcers(self):
        from agent_tools.project_contract import conformance_checks

        self.assertEqual([rule.enforcer for rule in RULES],
                         list(conformance_checks.NEVER_RISE_ENFORCERS))


if __name__ == "__main__":
    unittest.main()
