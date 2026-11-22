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
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import cleanup_issue
from agent_tools.delivery.cleanup_issue import (
    RULES, CleanupRule, Issue, Outcome, draft, is_cleanup, listing, run)
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Violation
from agent_tools.system.forge_api import ForgeError
from tests.test_never_rise import commit_all, fixture_env, git, repo, write

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
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


BOT = {"user": {"login": "github-actions[bot]"}, "author_association": "NONE"}
MARK = "<!-- agent:cleanup v1 rule=B17 -->"
LISTING = "repos/octo/widgets/issues?state=open&per_page=100"


def numbered(count: int, prefix: str = "line") -> str:
    return "".join(f"{prefix} {n}\n" for n in range(count))


def marker_issue(number: int) -> dict:
    return {"number": number, "body": MARK, **BOT}


class CommandTest(unittest.TestCase):
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

    def call(self, argv, pages=None, created=41):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cleanup_issue.forge_api, "api_pages") as api_pages, \
                mock.patch.object(cleanup_issue.forge_api, "create_issue",
                                  return_value=created) as create_issue, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if isinstance(pages, Exception):
                api_pages.side_effect = pages
            else:
                api_pages.return_value = [[]] if pages is None else pages
            code = cleanup_issue.main(argv)
        return code, out.getvalue(), err.getvalue(), api_pages, create_issue

    def file(self, root, pages=None):
        return self.call(["file", "--repo-root", str(root), "--repo", "octo/widgets"], pages)

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
                 [[{"number": 3, "body": 7, **BOT}]]]
        root = self.world()
        for pages in cases:
            with self.subTest(pages=pages):
                code, out, err, _, create_issue = self.file(root, pages)

                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("cleanup-issue: "), err)
                create_issue.assert_not_called()

    def test_counts_prints_each_rule_and_its_count(self):
        code, out, _, _, _ = self.call(["counts", "--repo-root", str(self.world())])

        self.assertEqual((code, out), (0, "B17 1\n"))

    def test_violations_still_names_a_listed_file_when_the_total_falls(self):
        root = self.world(commit_b=True)
        code, out, _, _, create_issue = self.file(root)
        body = create_issue.call_args.args[2]
        self.assertEqual(code, 0)
        self.assertIn("B17 a.py:1501", body)
        self.assertIn("at most 1 violations", body)
        write(root, "b.py", numbered(10))
        commit_all(root)

        self.assertEqual(self.call(["counts", "--repo-root", str(root)])[:2], (0, "B17 1\n"))
        listed = ["violations", "--repo-root", str(root), "--rule", "B17"]
        self.assertEqual(self.call(listed)[:2], (0, "B17 a.py:1501\n"))
        write(root, "a.py", numbered(1500))
        commit_all(root)
        self.assertEqual(self.call(listed)[:2], (0, ""))

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


STUB_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case " $* " in
  *" POST "*) echo '{"number": 41}' ;;
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
