"""The cleanup issue core of `agent_tools.delivery.cleanup_issue` (#1462).

Measures the selection of the rule with the fewest violations, the whole-file
listing bounded by the batch, the marker as a whole line, the exact issue body
and the three outcomes of a run, over in-memory snapshots and a stub tracker.
"""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import cleanup_issue, never_rise
from agent_tools.delivery.cleanup_issue import (
    RULES, CleanupRule, FixDraft, Issue, Outcome, draft, fix_draft, is_cleanup, is_fix_change,
    listing, run)
from agent_tools.delivery.never_rise import Enforcer, Fix, Snapshot, Violation
from agent_tools.system.forge_api import ForgeError
from tests.test_never_rise import commit_all, fixture_env, git, repo, write
from tests.test_ruff_lint import require_ruff

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = str(REPO_ROOT / "home/common/agent-skills")
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
FIX_MARKER_FX4 = "<!-- agent:cleanup-fix v1 rule=FX4 -->"


def fix_enforcer(rule: str, suffix: str, writes: bool = True) -> Enforcer:
    seen: list[tuple[str, ...]] = []

    def fix(snapshot: Snapshot, paths) -> Fix:
        seen.append(tuple(paths))
        if not writes:
            return Fix({}, 0)
        return Fix({path: f"fixed {path}\n".encode() for path in paths}, len(paths))
    base = suffix_enforcer(rule, suffix)
    enforcer = Enforcer(rule, base.find, fix=fix)
    object.__setattr__(enforcer, "seen", seen)
    return enforcer


R4 = CleanupRule(fix_enforcer("FX4", ".four"), 5, "Fix FX4.")
R5 = CleanupRule(fix_enforcer("FX4", ".four", writes=False), 5, "Fix FX4.")


def snapshot_of(*paths: str) -> Snapshot:
    return Snapshot(REVISION, {path: 1 for path in paths})


class StubTracker:
    def __init__(self, open_issues: list[Issue] | None = None, writer: bool = True,
                 current: bool = True, changes: list[Issue] | None = None, checks: bool = True,
                 taken: bool = False):
        self.open = list(open_issues or [])
        self.writer = writer
        self.is_current = current
        self.changes = list(changes or [])
        self.checks = checks
        self.taken = taken
        self.created: list[tuple[str, str]] = []
        self.opened: list[tuple[str, str, str, str, dict]] = []

    def open_changes(self) -> list[Issue]:
        return list(self.changes)

    def starts_checks(self) -> bool:
        return self.checks

    def open_change(self, branch: str, revision: str, title: str, body: str, files) -> int | None:
        if self.taken:
            return None
        self.opened.append((branch, revision, title, body, dict(files)))
        number = 201 + len(self.opened) - 1
        self.changes.append(Issue(number, body))
        return number

    def trusted_writer(self) -> bool:
        return self.writer

    def current(self, revision: str) -> bool:
        return self.is_current

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

    def test_a_filer_that_would_not_be_trusted_files_nothing(self):
        tracker = StubTracker(writer=False)

        with self.assertRaises(cleanup_issue.Refusal):
            run(tracker, snapshot_of("a.one"), (R1,))
        self.assertEqual(tracker.created, [])
        self.assertEqual(run(tracker, snapshot_of("x.py"), (R1,)), Outcome("clean", None, None))

    def test_a_run_for_a_commit_that_is_no_longer_the_tip_files_nothing(self):
        tracker = StubTracker(current=False)

        self.assertEqual(run(tracker, snapshot_of("a.one"), (R1,)), Outcome("stale", None, None))
        self.assertEqual(tracker.created, [])

    def test_a_path_that_is_not_utf8_is_filed_as_printable_escapes(self):
        name = os.fsdecode(b"big\xff\x80.py")
        tracker = StubTracker()

        outcome = run(tracker, Snapshot(REVISION, {name: 1501, "a\\b.py": 1502}))

        self.assertEqual(outcome, Outcome("filed", 101, "B17"))
        title, body = tracker.created[0]
        self.assertIn("B17 big\\xff\\x80.py:1501", body.splitlines())
        self.assertEqual(body.encode("utf-8").decode("utf-8"), body)
        self.assertEqual(title.encode("utf-8").decode("utf-8"), title)

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

    def test_the_fix_marker_counts_only_as_a_whole_line(self):
        self.assertTrue(is_fix_change("x\n<!-- agent:cleanup-fix v1 rule=PY7 -->\r\n"))
        self.assertFalse(is_fix_change("see <!-- agent:cleanup-fix v1 rule=PY7 --> here"))
        self.assertFalse(is_fix_change("<!-- agent:cleanup-fix v2 rule=PY7 -->"))
        self.assertFalse(is_fix_change("<!-- agent:cleanup v1 rule=PY7 -->"))
        self.assertFalse(is_cleanup("<!-- agent:cleanup-fix v1 rule=PY7 -->"))

    def test_an_extra_field_or_a_repeated_key_is_no_cleanup_marker(self):
        self.assertFalse(is_cleanup("<!-- agent:cleanup v1 rule=B17 extra=1 -->"))
        self.assertFalse(is_cleanup("<!-- agent:cleanup v1 rule=B17 rule=B18 -->"))


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


class FixChangeRunTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"AGENT_PLATFORM_ROOT": PLATFORM_ROOT})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_fixable_ruff_rule_in_a_fixture_repository_opens_one_fix_change_and_files_no_issue(self):
        require_ruff(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "python/pyproject.toml", "[project]\n")
            write(root, "python/m.py", "x = 1;\n")
            commit_all(root)
            snapshot = never_rise.read_snapshot(root, never_rise.resolve_commit(root, "HEAD", 60), 60)
            tracker = StubTracker()

            outcome = run(tracker, snapshot)

        self.assertEqual(outcome, Outcome("opened", 201, "PY7"))
        self.assertEqual(tracker.created, [])
        self.assertEqual(len(tracker.opened), 1)
        branch, revision, _, body, files = tracker.opened[0]
        self.assertEqual(files, {"python/m.py": b"x = 1\n"})
        self.assertEqual(revision, snapshot.revision)
        self.assertEqual(branch, "cleanup-fix-py7-" + snapshot.revision[:12])
        self.assertTrue(is_fix_change(body))
        self.assertIn("- Before: 1", body)
        self.assertIn("- After: 0", body)

    def test_an_open_fix_change_or_cleanup_issue_opens_nothing_and_an_unchanging_autofix_files_an_issue(self):
        snapshot = snapshot_of("a.four")
        R4 = CleanupRule(fix_enforcer("FX4", ".four"), 5, "Fix FX4.")
        with self.subTest("an open fix change"):
            tracker = StubTracker(changes=[Issue(30, "<!-- agent:cleanup-fix v1 rule=FX4 -->")])
            self.assertEqual(run(tracker, snapshot, (R4,)), Outcome("open", 30, None))
            self.assertEqual((tracker.created, tracker.opened), ([], []))
            self.assertEqual(R4.enforcer.seen, [])
        with self.subTest("an open cleanup issue"):
            tracker = StubTracker([Issue(7, MARKER_FX1)])
            self.assertEqual(run(tracker, snapshot, (R4,)), Outcome("open", 7, None))
            self.assertEqual((tracker.created, tracker.opened), ([], []))
            self.assertEqual(R4.enforcer.seen, [])
        with self.subTest("an autofix that changes nothing"):
            tracker = StubTracker()
            self.assertEqual(run(tracker, snapshot, (R5,)), Outcome("filed", 101, "FX4"))
            self.assertEqual(tracker.opened, [])
            self.assertEqual(tracker.created[0][1].splitlines()[0], "<!-- agent:cleanup v1 rule=FX4 -->")

    def test_the_lowest_of_the_open_issues_and_fix_changes_is_named(self):
        tracker = StubTracker([Issue(12, MARKER_FX1)], changes=[Issue(9, FIX_MARKER_FX4)])

        self.assertEqual(run(tracker, snapshot_of("a.four"), (R4,)), Outcome("open", 9, None))

    def test_the_wrong_marker_on_either_side_holds_nothing(self):
        tracker = StubTracker([Issue(5, FIX_MARKER_FX4)], changes=[Issue(6, MARKER_FX1)])

        self.assertEqual(run(tracker, snapshot_of("a.four"), (R4,)).action, "opened")

    def test_a_writer_whose_pull_requests_start_no_checks_defers(self):
        snapshot = snapshot_of("a.four")
        tracker = StubTracker(checks=False)
        self.assertEqual(run(tracker, snapshot, (R4,)), Outcome("deferred", None, "FX4"))
        self.assertEqual((tracker.created, tracker.opened), ([], []))

        tracker = StubTracker(checks=False)
        self.assertEqual(run(tracker, snapshot, (R5,)), Outcome("filed", 101, "FX4"))

    def test_a_ref_another_host_created_answers_taken(self):
        tracker = StubTracker(taken=True)

        self.assertEqual(run(tracker, snapshot_of("a.four"), (R4,)), Outcome("taken", None, "FX4"))
        self.assertEqual(tracker.created, [])

    def test_a_fix_only_run_files_nothing_for_an_unfixable_pick(self):
        snapshot = snapshot_of("a.four", "a.one")
        for rule, expected in ((R5, Outcome("unfixable", None, "FX4")),
                               (R1, Outcome("unfixable", None, "FX1"))):
            with self.subTest(rule=rule.enforcer.rule, fix=rule.enforcer.fix is not None):
                tracker = StubTracker()
                self.assertEqual(run(tracker, snapshot, (rule,), fix_only=True), expected)
                self.assertEqual(tracker.created, [])
        tracker = StubTracker()
        self.assertEqual(run(tracker, snapshot, (R4,), fix_only=True), Outcome("opened", 201, "FX4"))

    def test_the_autofix_sees_only_the_listed_files(self):
        rule = CleanupRule(fix_enforcer("FX4", ".four"), 2, "x")
        tracker = StubTracker()

        run(tracker, snapshot_of("a.four", "b.four", "c.four"), (rule,))

        self.assertEqual(rule.enforcer.seen, [("a.four", "b.four")])
        self.assertEqual(set(tracker.opened[0][4]), {"a.four", "b.four"})

    def test_a_fix_naming_a_file_outside_the_listing_is_refused(self):
        rule = CleanupRule(
            Enforcer("FX4", suffix_enforcer("FX4", ".four").find,
                     fix=lambda snapshot, paths: Fix({"elsewhere.py": b"x"}, 1)), 5, "x")
        tracker = StubTracker()

        with self.assertRaises(ValueError):
            run(tracker, snapshot_of("a.four"), (rule,))
        self.assertEqual((tracker.created, tracker.opened), ([], []))

    def test_an_untrusted_writer_or_a_stale_tip_runs_no_autofix(self):
        snapshot = snapshot_of("a.four")
        R4 = CleanupRule(fix_enforcer("FX4", ".four"), 5, "Fix FX4.")
        with self.assertRaises(cleanup_issue.Refusal):
            run(StubTracker(writer=False), snapshot, (R4,))
        self.assertEqual(run(StubTracker(current=False), snapshot, (R4,)), Outcome("stale", None, None))
        self.assertEqual(R4.enforcer.seen, [])


class FixDraftTest(unittest.TestCase):
    def test_the_fix_change_is_the_wire_format(self):
        result = fix_draft(R4, 3, Fix({"b.four": b"x", "a.four": b"y"}, 2), REVISION)

        self.assertEqual(result, FixDraft(
            "FX4", 3, 1, "cleanup-fix-fx4-" + REVISION[:12],
            "Fix 2 of the 3 violations of rule FX4 with its autofix",
            "<!-- agent:cleanup-fix v1 rule=FX4 -->\n"
            f"Rule FX4 has 3 violations at {REVISION}. This change holds only what the rule's"
            " autofix wrote to 2 files.\n"
            "\n"
            "## Count\n"
            "\n"
            "- Before: 3\n"
            "- After: 1\n"
            "\n"
            "## Files\n"
            "\n"
            "```text\n"
            "a.four\n"
            "b.four\n"
            "```\n"))


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_batch_and_guidance(self):
        for rule in RULES:
            self.assertGreaterEqual(rule.batch, 1)
            self.assertTrue(rule.guidance.strip())

    def test_the_rules_are_the_never_rise_enforcers(self):
        from agent_tools.project_contract import conformance_checks

        self.assertEqual([rule.enforcer.rule for rule in RULES],
                         [enforcer.rule for enforcer in
                          conformance_checks.never_rise_enforcers({"bindings": {}})])


NODE_ZEROS = "".join(f"NODE{n} 0\n" for n in range(11, 16))
COUNTS_OF_ONE_FILE = ("B17 1\nB23 0\nB24 0\n" + "".join(f"PY{n} 0\n" for n in range(6, 14))
                      + "".join(f"B{n} 0\n" for n in range(18, 23)) + "B25 0\nB26 0\n" + NODE_ZEROS)
BOT = {"user": {"login": "github-actions[bot]"}, "author_association": "NONE"}
MARK = "<!-- agent:cleanup v1 rule=B17 -->"
LISTING = "repos/octo/widgets/issues?state=open&per_page=100"


def numbered(count: int, prefix: str = "line") -> str:
    return "".join(f"{prefix} {n}\n" for n in range(count))


def marker_issue(number: int) -> dict:
    return {"number": number, "body": MARK, **BOT}


class ForgeWorld:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def world(self, a: int = 1501, b: int = 1600, commit_b: bool = False) -> Path:
        root = repo(self.tmp.name)
        write(root, "a.py", numbered(a))
        if commit_b:
            write(root, "b.py", numbered(b))
        commit_all(root)
        if not commit_b:
            write(root, "b.py", numbered(b))
        return root

    def fixable_world(self) -> Path:
        root = repo(self.tmp.name)
        write(root, "python/pyproject.toml", "[project]\n")
        write(root, "python/m.py", "x = 1;\n")
        commit_all(root)
        return root

    def call(self, argv, pages=None, created=41, reads=None, registry=None):
        out, err = io.StringIO(), io.StringIO()
        answers = {"user": None, **(reads or {})}

        def read(path, allow=()):
            return answers[path]

        with mock.patch.object(cleanup_issue.forge_api, "api_pages") as api_pages, \
                mock.patch.object(cleanup_issue.forge_api, "api_get", side_effect=read) as api_get, \
                mock.patch.object(cleanup_issue.forge_api, "create_issue",
                                  return_value=created) as create_issue, \
                mock.patch.object(cleanup_issue.forge_markers, "create_ref",
                                  return_value=True) as create_ref, \
                mock.patch.object(cleanup_issue.forge_api, "commit_files",
                                  return_value="c" * 40) as commit_files, \
                mock.patch.object(cleanup_issue.forge_api, "create_pull",
                                  return_value=77) as create_pull, \
                mock.patch.object(cleanup_issue.agent_platform, "read_registry",
                                  return_value=registry or []), \
                mock.patch.dict(os.environ, {"AGENT_PLATFORM_ROOT": PLATFORM_ROOT}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if isinstance(pages, Exception):
                api_pages.side_effect = pages
            else:
                api_pages.return_value = [[]] if pages is None else pages
            code = cleanup_issue.main(argv)
        self.forge = types.SimpleNamespace(
            api_get=api_get, create_ref=create_ref, commit_files=commit_files,
            create_pull=create_pull)
        return code, out.getvalue(), err.getvalue(), api_pages, create_issue

    def file(self, root, pages=None, reads=None, *extra):
        return self.call(["file", "--repo-root", str(root), "--repo", "octo/widgets", *extra],
                         pages, reads=reads)

    def assert_no_forge_write(self):
        self.forge.create_ref.assert_not_called()
        self.forge.commit_files.assert_not_called()
        self.forge.create_pull.assert_not_called()


class CommandTest(ForgeWorld, unittest.TestCase):
    def test_file_on_a_committed_tree_files_one_issue_through_the_forge(self):
        root = self.world()

        code, out, _, api_pages, create_issue = self.file(root)

        self.assertEqual(code, 0)
        self.assertEqual(out, '{"action": "filed", "issue": 41, "rule": "B17"}\n')
        api_pages.assert_called_once_with(LISTING)
        create_issue.assert_called_once()
        slug, title, body = create_issue.call_args.args
        self.assertEqual((slug, title), ("octo/widgets", "Clear 1 of the 1 violations of rule B17"))
        self.assertIn("B17 a.py:1501", body)
        self.assertNotIn("b.py", body)

    def test_an_open_cleanup_issue_in_the_listing_files_nothing(self):
        code, out, _, _, create_issue = self.file(self.world(), [[marker_issue(5)]])

        self.assertEqual(code, 0)
        self.assertEqual(out, '{"action": "open", "issue": 5, "rule": null}\n')
        create_issue.assert_not_called()

    def test_a_cleanup_issue_on_the_second_page_files_nothing(self):
        pages = [[{"number": 1, "body": "ordinary", **BOT}, {"number": 2, "body": None, **BOT}],
                 [marker_issue(5)]]

        code, out, _, _, create_issue = self.file(self.world(), pages)

        self.assertEqual(code, 0)
        self.assertEqual(out, '{"action": "open", "issue": 5, "rule": null}\n')
        create_issue.assert_not_called()

    def test_a_marker_issue_by_an_untrusted_author_is_ignored(self):
        untrusted = [[
            {"number": 5, "body": MARK, "user": {"login": "mallory"}, "author_association": "NONE"},
            {"number": 6, "body": MARK, "user": {"login": "mallory"},
             "author_association": "CONTRIBUTOR"},
            {"number": 8, "body": MARK}]]
        root = self.world()

        code, out, _, _, create_issue = self.file(root, untrusted)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "filed")
        create_issue.assert_called_once()
        code, out, _, _, _ = self.call(["open", "--repo", "octo/widgets"], untrusted)
        self.assertEqual((code, out), (1, '{"open": []}\n'))

        owner = [[{"number": 7, "body": MARK, "user": {"login": "octo"},
                   "author_association": "OWNER"}]]
        code, out, _, _, create_issue = self.file(root, owner)
        self.assertEqual(out, '{"action": "open", "issue": 7, "rule": null}\n')
        create_issue.assert_not_called()

    def test_file_with_a_fixable_ruff_rule_opens_one_pull_request_through_the_forge(self):
        require_ruff(self)
        root = self.fixable_world()
        sha = git(root, "rev-parse", "HEAD").strip()
        reads = {"user": {"login": "octo"},
                 "repos/octo/widgets": {"owner": {"login": "octo", "type": "User"}},
                 "repos/octo/widgets/git/ref/heads/main": {"object": {"sha": sha}}}

        code, out, _, _, create_issue = self.file(root, None, reads, "--branch", "main")

        self.assertEqual(code, 0)
        self.assertEqual(out, '{"action": "opened", "issue": 77, "rule": "PY7"}\n')
        create_issue.assert_not_called()
        branch = "cleanup-fix-py7-" + sha[:12]
        self.forge.create_ref.assert_called_once_with("octo/widgets", "refs/heads/" + branch, sha)
        self.forge.commit_files.assert_called_once()
        slug, commit_branch, expected, _, files = self.forge.commit_files.call_args.args
        self.assertEqual((slug, commit_branch, expected, files),
                         ("octo/widgets", branch, sha, {"python/m.py": b"x = 1\n"}))
        self.forge.create_pull.assert_called_once()
        slug, _, body, head, base = self.forge.create_pull.call_args.args
        self.assertEqual((slug, head, base), ("octo/widgets", branch, "main"))
        self.assertEqual(body.splitlines()[0], "<!-- agent:cleanup-fix v1 rule=PY7 -->")

    def test_the_workflow_token_defers_a_fixable_rule(self):
        require_ruff(self)
        root = self.fixable_world()
        repository = {"owner": {"login": "octo", "type": "User"}}
        notice = ("cleanup-issue: rule PY7 needs a fix change; the verify-pending pass opens it "
                  "from a host whose pull requests start checks\n")
        for user in (None, {"login": "github-actions[bot]"}):
            with self.subTest(user=user):
                reads = {"user": user, "repos/octo/widgets": repository}

                code, out, err, _, create_issue = self.file(root, None, reads)

                self.assertEqual((code, out, err), (
                    0, '{"action": "deferred", "issue": null, "rule": "PY7"}\n', notice))
                create_issue.assert_not_called()
                self.assert_no_forge_write()

    def test_an_open_fix_change_in_the_listing_holds_the_slot(self):
        pages = [[{"number": 5, "body": "<!-- agent:cleanup-fix v1 rule=PY7 -->",
                   "pull_request": {}, **BOT}]]

        code, out, _, api_pages, create_issue = self.file(self.world(), pages)

        self.assertEqual((code, out), (0, '{"action": "open", "issue": 5, "rule": null}\n'))
        api_pages.assert_called_once_with(LISTING)
        create_issue.assert_not_called()

    def test_a_fix_marker_by_an_untrusted_author_holds_nothing(self):
        pages = [[{"number": 5, "body": "<!-- agent:cleanup-fix v1 rule=PY7 -->",
                   "pull_request": {}, "user": {"login": "mallory"}, "author_association": "NONE"}]]

        code, out, _, _, _ = self.file(self.world(), pages)

        self.assertEqual((code, json.loads(out)["action"]), (0, "filed"))

    def test_a_fix_change_without_branch_exits_2_before_any_write(self):
        require_ruff(self)
        reads = {"user": {"login": "octo"},
                 "repos/octo/widgets": {"owner": {"login": "octo", "type": "User"}}}

        code, out, err, _, create_issue = self.file(self.fixable_world(), None, reads)

        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("cleanup-issue: "), err)
        create_issue.assert_not_called()
        self.assert_no_forge_write()

    def test_a_pull_request_without_a_body_field_is_a_forge_error(self):
        code, out, err, _, create_issue = self.file(
            self.world(), [[{"number": 4, "pull_request": {}, **BOT}]])

        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("cleanup-issue: "), err)
        create_issue.assert_not_called()

    def test_a_pull_request_in_the_listing_is_not_an_issue(self):
        pages = [[{**marker_issue(5), "pull_request": {}}]]

        code, out, _, _, create_issue = self.file(self.world(), pages)

        self.assertEqual(json.loads(out)["action"], "filed")
        create_issue.assert_called_once()

    def test_a_forge_error_exits_2_and_files_nothing(self):
        cases = [ForgeError("gh_failed", "HTTP 502"),
                 [[{"number": True, "body": "", **BOT}]],
                 [[], "oops"],
                 [[1]],
                 [[{"number": 3, "body": 7, **BOT}]],
                 [[{"number": 3, **BOT}]],
                 [[{"number": 3, "body": "ordinary", **BOT}, {"number": 4, **BOT}]]]
        root = self.world()
        for pages in cases:
            with self.subTest(pages=pages):
                code, out, err, _, create_issue = self.file(root, pages)

                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("cleanup-issue: "), err)
                create_issue.assert_not_called()

    def test_a_filer_that_would_not_be_trusted_exits_2_and_files_nothing(self):
        repository = {"owner": {"login": "octo", "type": "User"}}
        root = self.world()
        for login in ("mallory", "collaborator"):
            with self.subTest(login):
                reads = {"user": {"login": login}, "repos/octo/widgets": repository}

                code, out, err, _, create_issue = self.file(root, None, reads)

                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("cleanup-issue: "), err)
                create_issue.assert_not_called()
        reads = {"user": {"login": "Octo"}, "repos/octo/widgets": repository}
        code, out, _, _, create_issue = self.file(root, None, reads)
        self.assertEqual((code, json.loads(out)["action"]), (0, "filed"))
        create_issue.assert_called_once()

    def test_a_filer_is_trusted_as_the_bot_the_owner_or_an_active_member(self):
        user_repo = {"owner": {"login": "octo", "type": "User"}}
        org_repo = {"owner": {"login": "acme", "type": "Organization"}}
        membership = "user/memberships/orgs/acme"
        cases = [({}, True),
                 ({"user": {"login": "github-actions[bot]"}, "repos/o/w": user_repo}, True),
                 ({"user": {"login": "octo"}, "repos/o/w": user_repo}, True),
                 ({"user": {"login": "other"}, "repos/o/w": user_repo}, False),
                 ({"user": {"login": "amy"}, "repos/o/w": org_repo,
                   membership: {"state": "active"}}, True),
                 ({"user": {"login": "amy"}, "repos/o/w": org_repo,
                   membership: {"state": "pending"}}, False),
                 ({"user": {"login": "amy"}, "repos/o/w": org_repo, membership: None}, False)]
        for reads, want in cases:
            with self.subTest(reads=reads):
                answers = {"user": None, **reads}
                with mock.patch.object(cleanup_issue.forge_api, "api_get",
                                       side_effect=lambda path, allow=(): answers[path]):
                    self.assertIs(cleanup_issue.GitHubTracker("o/w").trusted_writer(), want)
        with mock.patch.object(cleanup_issue.forge_api, "api_get", return_value={"login": "x"}):
            with self.assertRaises(ForgeError):
                cleanup_issue.GitHubTracker("o/w").trusted_writer()

    def test_a_branch_whose_tip_moved_files_nothing(self):
        root = self.world()
        sha = git(root, "rev-parse", "HEAD").strip()
        ref = "repos/octo/widgets/git/ref/heads/main"
        moved = {ref: {"object": {"sha": "b" * 40}}}
        same = {ref: {"object": {"sha": sha}}}

        code, out, _, _, create_issue = self.file(root, None, moved, "--branch", "main")
        self.assertEqual((code, out), (0, '{"action": "stale", "issue": null, "rule": null}\n'))
        create_issue.assert_not_called()
        code, out, _, _, create_issue = self.file(root, None, same, "--branch", "main")
        self.assertEqual((code, json.loads(out)["action"]), (0, "filed"))
        create_issue.assert_called_once()
        code, out, _, _, create_issue = self.file(root, None, {ref: {"object": {}}}, "--branch", "main")
        self.assertEqual((code, out), (2, ""))
        create_issue.assert_not_called()

    def test_counts_prints_each_rule_and_its_count(self):
        code, out, _, _, _ = self.call(["counts", "--repo-root", str(self.world())])

        self.assertEqual((code, out), (0, COUNTS_OF_ONE_FILE))

    def test_violations_still_names_a_listed_file_when_the_total_falls(self):
        root = self.world(commit_b=True)
        code, out, _, _, create_issue = self.file(root)
        body = create_issue.call_args.args[2]
        self.assertEqual(code, 0)
        self.assertIn("B17 a.py:1501", body)
        self.assertIn("at most 1 violations", body)
        write(root, "b.py", numbered(10))
        commit_all(root)

        self.assertEqual(self.call(["counts", "--repo-root", str(root)])[:2], (0, COUNTS_OF_ONE_FILE))
        listed = ["violations", "--repo-root", str(root), "--rule", "B17"]
        self.assertEqual(self.call(listed)[:2], (0, "B17 a.py:1501\n"))
        write(root, "a.py", numbered(1500))
        commit_all(root)
        self.assertEqual(self.call(listed)[:2], (0, ""))

    def test_a_reasoned_suppression_leaves_its_finding_out_of_the_count(self):
        root = repo(self.tmp.name)
        write(root, "a.py", numbered(1500) + "# suppress-standard:B17 generated table\n")
        commit_all(root)

        self.assertEqual(self.call(["counts", "--repo-root", str(root)])[:2],
                         (0, "B17 0\nB23 0\nB24 0\n" + "".join(f"PY{n} 0\n" for n in range(6, 14))
                          + "".join(f"B{n} 0\n" for n in range(18, 23)) + "B25 0\nB26 0\n" + NODE_ZEROS))
        listed = ["violations", "--repo-root", str(root), "--rule", "B17"]
        self.assertEqual(self.call(listed)[:2], (0, ""))

    def test_a_bare_marker_is_counted_beside_the_findings_the_gate_counts(self):
        root = repo(self.tmp.name)
        write(root, "a.py", numbered(4) + "# suppress-standard:B17\n" + numbered(1496))
        commit_all(root)

        listed = ["violations", "--repo-root", str(root), "--rule", "B17"]
        self.assertEqual(self.call(listed)[:2], (0, "B17 a.py:1501\nB17 a.py:5\n"))
        self.assertEqual(self.call(["counts", "--repo-root", str(root)])[1].splitlines()[0],
                         "B17 2")

    def test_an_enforcer_that_cannot_judge_exits_2_and_files_nothing(self):
        root = repo(self.tmp.name)
        write(root, "python/pyproject.toml", "[project]\n")
        write(root, "python/m.py", "import os\n")
        commit_all(root)
        for argv in (["counts"], ["violations", "--rule", "PY6"], ["file", "--repo", "octo/widgets"]):
            with self.subTest(argv[0]), mock.patch.dict(os.environ):
                os.environ.pop("AGENT_PLATFORM_TOOLS", None)

                code, out, err, _, create_issue = self.call(
                    [argv[0], "--repo-root", str(root), *argv[1:]])

                self.assertEqual((code, out, err), (2, "", "cleanup-issue: ruff-lint: ruff_unavailable\n"))
                create_issue.assert_not_called()

    def test_open_exits_0_only_for_exactly_one_cleanup_issue(self):
        plain = {"number": 9, "body": "ordinary", **BOT}
        cases = [([[plain]], 1, '{"open": []}\n'),
                 ([[plain, marker_issue(3)]], 0, '{"open": [3]}\n'),
                 ([[marker_issue(4), plain], [marker_issue(3)]], 1, '{"open": [3, 4]}\n')]
        for pages, want_code, want_out in cases:
            with self.subTest(want_out):
                code, out, _, _, create_issue = self.call(["open", "--repo", "octo/widgets"], pages)

                self.assertEqual((code, out), (want_code, want_out))
                create_issue.assert_not_called()

    def test_a_bad_root_or_repo_exits_2(self):
        root = self.world()
        (root / "sub").mkdir()
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        repo_args = ["--repo", "octo/widgets"]
        cases = [["file", "--repo-root", "relative", *repo_args],
                 ["file", "--repo-root", str(root / "missing"), *repo_args],
                 ["file", "--repo-root", str(root / "sub"), *repo_args],
                 ["file", "--repo-root", str(plain), *repo_args],
                 ["file", "--repo-root", str(root), "--repo", "not a slug"],
                 ["file", "--repo-root", str(root), *repo_args, "--revision", "no-such-ref"],
                 ["counts", "--repo-root", str(root), "--revision", "no-such-ref"],
                 ["violations", "--repo-root", str(root), "--rule", "NOPE"],
                 ["open", "--repo", "not a slug"]]
        for argv in cases:
            with self.subTest(argv):
                code, out, err, api_pages, create_issue = self.call(argv)

                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("cleanup-issue: "), err)
                api_pages.assert_not_called()
                create_issue.assert_not_called()


class ForgeChangeTest(unittest.TestCase):
    def run_gh(self, graphql_answer):
        self.calls: list[list[str]] = []
        self.requests: list[dict] = []

        def fake(argv, allow=(), cancelled=None, cli="gh"):
            self.calls.append(list(argv))
            if argv[:3] == ["api", "graphql", "--input"]:
                self.requests.append(json.loads(Path(argv[3]).read_text()))
                return 0, graphql_answer
            if argv[3] == "repos/o/w/pulls":
                return 0, '{"number": 77}'
            return 0, ""
        return mock.patch.object(cleanup_issue.forge_api, "run_gh", side_effect=fake)

    def test_open_change_creates_the_ref_then_one_commit_then_the_pull(self):
        answer = '{"data": {"createCommitOnBranch": {"commit": {"oid": "cc"}}}}'
        with self.run_gh(answer):
            number = cleanup_issue.GitHubTracker("o/w", "main").open_change(
                "cleanup-fix-py7-abc", "a" * 40, "T", "B", {"b.py": b"2", "a.py": b"1"})

        self.assertEqual(number, 77)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[1][:3], ["api", "graphql", "--input"])
        self.assertEqual(self.calls[0], ["api", "-X", "POST", "repos/o/w/git/refs", "-f",
                                         "ref=refs/heads/cleanup-fix-py7-abc", "-f", "sha=" + "a" * 40])
        self.assertEqual(self.calls[2], ["api", "-X", "POST", "repos/o/w/pulls", "-f", "title=T",
                                         "-f", "body=B", "-f", "head=cleanup-fix-py7-abc",
                                         "-f", "base=main"])
        self.assertEqual(self.requests, [{
            "query": "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: "
                     "$input) { commit { oid } } }",
            "variables": {"input": {
                "branch": {"repositoryNameWithOwner": "o/w", "branchName": "cleanup-fix-py7-abc"},
                "message": {"headline": "T"},
                "expectedHeadOid": "a" * 40,
                "fileChanges": {"additions": [{"path": "a.py", "contents": "MQ=="},
                                              {"path": "b.py", "contents": "Mg=="}]}}}}])

    def test_a_commit_without_an_oid_opens_no_pull(self):
        with self.run_gh('{"data": {"createCommitOnBranch": {"commit": null}}}'):
            with self.assertRaises(ForgeError) as caught:
                cleanup_issue.GitHubTracker("o/w", "main").open_change(
                    "cleanup-fix-py7-abc", "a" * 40, "T", "B", {"a.py": b"1"})

        self.assertEqual(caught.exception.code, "payload_invalid")
        self.assertNotIn("repos/o/w/pulls", [call[3] for call in self.calls if len(call) > 3])

    def test_a_ref_that_exists_returns_none_and_writes_nothing_more(self):
        with mock.patch.object(cleanup_issue.forge_markers, "create_ref", return_value=False), \
                mock.patch.object(cleanup_issue.forge_api, "commit_files") as commit_files, \
                mock.patch.object(cleanup_issue.forge_api, "create_pull") as create_pull:
            number = cleanup_issue.GitHubTracker("o/w", "main").open_change(
                "cleanup-fix-py7-abc", "a" * 40, "T", "B", {"a.py": b"1"})

        self.assertIsNone(number)
        commit_files.assert_not_called()
        create_pull.assert_not_called()

    def test_starts_checks_is_false_for_the_workflow_token_and_the_bot(self):
        for user, want in ((None, False), ({"login": "github-actions[bot]"}, False),
                           ({"login": "octo"}, True)):
            with self.subTest(user=user), mock.patch.object(
                    cleanup_issue.forge_api, "api_get", return_value=user):
                self.assertIs(cleanup_issue.GitHubTracker("o/w").starts_checks(), want)
        with mock.patch.object(cleanup_issue.forge_api, "api_get", return_value={"login": ""}):
            with self.assertRaises(ForgeError):
                cleanup_issue.GitHubTracker("o/w").starts_checks()


class FixCommandTest(ForgeWorld, unittest.TestCase):
    REPOSITORY = {"owner": {"login": "octo", "type": "User"}}

    def registered_world(self, fixable: bool = True) -> tuple[Path, str]:
        root = self.fixable_world() if fixable else self.world()
        origin = Path(self.tmp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, timeout=60)
        git(root, "remote", "add", "origin", str(origin))
        git(root, "push", "-q", "origin", "main")
        return root, git(root, "rev-parse", "HEAD").strip()

    def fix(self, root, sha):
        reads = {"user": {"login": "octo"}, "repos/octo/widgets": self.REPOSITORY,
                 "repos/octo/widgets/git/ref/heads/main": {"object": {"sha": sha}}}
        return self.call(["fix", "--project", "octo/widgets", "--repo", "octo/widgets",
                          "--branch", "main"], reads=reads,
                         registry=[{"project_id": "octo/widgets", "root": str(root)}])

    def test_fix_reads_the_registered_root_fetches_the_tip_and_opens_the_change(self):
        require_ruff(self)
        root, pushed = self.registered_world()
        write(root, "python/n.py", "y = 2;\n")
        commit_all(root)

        code, out, _, _, create_issue = self.fix(root, pushed)

        self.assertEqual(code, 0)
        self.assertEqual(out, '{"action": "opened", "issue": 77, "rule": "PY7"}\n')
        self.forge.create_ref.assert_called_once_with(
            "octo/widgets", "refs/heads/cleanup-fix-py7-" + pushed[:12], pushed)
        files = self.forge.commit_files.call_args.args[4]
        self.assertEqual(files, {"python/m.py": b"x = 1\n"})
        create_issue.assert_not_called()

    def test_fix_fetches_a_tip_the_root_does_not_hold(self):
        require_ruff(self)
        root, _ = self.registered_world()
        other = Path(self.tmp.name) / "other"
        git(self.tmp.name, "clone", "-q", str(Path(self.tmp.name) / "origin.git"), str(other))
        write(other, "python/n.py", "y = 2;\n")
        commit_all(other)
        git(other, "push", "-q", "origin", "main")
        tip = git(other, "rev-parse", "HEAD").strip()

        code, out, _, _, _ = self.fix(root, tip)

        self.assertEqual((code, json.loads(out)["action"]), (0, "opened"))
        self.assertEqual(self.forge.create_ref.call_args.args[2], tip)

    def test_a_failed_fetch_exits_2_before_any_forge_call(self):
        root = self.fixable_world()

        code, out, err, api_pages, create_issue = self.fix(root, "a" * 40)

        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, f"cleanup-issue: cannot fetch main in {root}\n")
        self.forge.api_get.assert_not_called()
        api_pages.assert_not_called()
        create_issue.assert_not_called()

    def test_an_unregistered_project_exits_2_before_any_forge_call(self):
        code, out, err, api_pages, create_issue = self.call(
            ["fix", "--project", "octo/widgets", "--repo", "octo/widgets", "--branch", "main"])

        self.assertEqual((code, out, err), (2, "", "cleanup-issue: project not registered: octo/widgets\n"))
        self.forge.api_get.assert_not_called()
        api_pages.assert_not_called()
        create_issue.assert_not_called()

    def test_an_unfixable_pick_files_nothing(self):
        root, pushed = self.registered_world(fixable=False)

        code, out, _, _, create_issue = self.fix(root, pushed)

        self.assertEqual((code, out), (0, '{"action": "unfixable", "issue": null, "rule": "B17"}\n'))
        create_issue.assert_not_called()
        self.assert_no_forge_write()


STUB_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case " $* " in
  *" POST "*) echo '{"number": 41}' ;;
  *" api user "*) echo "gh: Resource not accessible by integration (HTTP 403)" >&2; exit 1 ;;
  *) cat "$GH_PAGES" ;;
esac
"""


class EntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(STUB_GH)
        gh.chmod(0o755)
        self.pages = Path(self.tmp.name) / "pages.json"
        self.log = Path(self.tmp.name) / "gh.log"
        self.env = fixture_env({
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(REPO_ROOT / "python"),
            "AGENT_PLATFORM_ROOT": PLATFORM_ROOT,
            "GH_PAGES": str(self.pages), "GH_LOG": str(self.log)})

    def program(self, *argv):
        return subprocess.run(
            [sys.executable, "-B", "-m", "agent_tools.delivery.cleanup_issue", *argv],
            cwd=REPO_ROOT, env=self.env, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=60)

    def test_the_module_runs_as_a_program_against_a_stub_gh(self):
        plain = {"number": 9, "body": "ordinary", **BOT}
        cases = [([[plain]], 1, '{"open": []}\n'),
                 ([[plain, marker_issue(3)]], 0, '{"open": [3]}\n'),
                 ([[marker_issue(3)], [marker_issue(4)]], 1, '{"open": [3, 4]}\n')]
        for pages, want_code, want_out in cases:
            with self.subTest(want_out):
                self.pages.write_text(json.dumps(pages))

                done = self.program("open", "--repo", "octo/widgets")

                self.assertEqual((done.returncode, done.stdout), (want_code, want_out), done.stderr)

        root = repo(self.tmp.name)
        write(root, "a.py", numbered(1501))
        commit_all(root)
        self.pages.write_text("[[]]")
        self.log.write_text("")

        done = self.program("file", "--repo-root", str(root), "--repo", "octo/widgets")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"action": "filed", "issue": 41, "rule": "B17"}\n')
        self.assertEqual(self.log.read_text().count("-X POST repos/octo/widgets/issues"), 1)

    def test_the_command_is_a_row_of_the_command_table(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()

        self.assertIn('"cleanup-issue" = "delivery.cleanup_issue";', table)


if __name__ == "__main__":
    unittest.main()
