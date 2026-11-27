"""The forge side of a lock bump: reads, the required-check verdict, and the writes.

Run: just agent-workflow-tests
"""
import base64
import unittest

from agent_tools.console.lock_bump_forge import Checks, GitHubBumpForge, OpenBump, QUERY
from agent_tools.system.forge_api import ForgeError
from tests.accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from tests.test_console_lock_bump_tree import dumped, document

TIER = "fast"

H = "d" * 40
REV_A = "a" * 40
REV_B = "b" * 40
SLUG = "octo/fixture"


class Scripted:
    """A `gh` stand-in: records each call and answers from a queue."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, argv, cancel=None):
        self.calls.append((argv, cancel))
        return self.answers.pop(0)


class Deleter:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, allow=(), cancelled=None):
        self.calls.append((argv, tuple(allow)))
        return 0, ""


def run(name, conclusion="SUCCESS", required=True, status="COMPLETED"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion,
            "isRequired": required}


def context(name, state="SUCCESS", required=True):
    return {"__typename": "StatusContext", "context": name, "state": state, "isRequired": required}


def reading(nodes, state="OPEN", merge_state="CLEAN", head=H, next_page=False, cursor="c1", protected=None):
    rule = None if protected is None else {"requiredStatusChecks": [{"context": name} for name in protected]}
    return {"data": {"repository": {"pullRequest": {
        "state": state, "headRefOid": head, "mergeStateStatus": merge_state,
        "baseRef": {"branchProtectionRule": rule},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {
            "pageInfo": {"hasNextPage": next_page, "endCursor": cursor}, "nodes": nodes}}}}]}}}}}


def graphql_argv(number=7):
    return ["api", "graphql", "-f", f"query={QUERY}", "-f", "owner=octo", "-f", "name=fixture",
            "-F", f"number={number}"]


def pull(number, ref, repo=SLUG):
    return {"number": number, "head": {"ref": ref, "repo": {"full_name": repo}}}


class ChecksTest(unittest.TestCase):
    def checks(self, answer):
        return GitHubBumpForge(gh_json=Scripted(answer)).checks(SLUG, 7)

    def test_every_required_check_green_with_a_clean_merge_state_reads_green(self):
        gh = Scripted(reading([run("Tests"), context("Conformance"), run("Lint", "FAILURE", required=False)]))
        self.assertEqual(GitHubBumpForge(gh_json=gh).checks(SLUG, 7), Checks("green", H, ()))
        self.assertEqual([argv for argv, _ in gh.calls], [graphql_argv()])

    def test_a_failed_required_check_reads_red_naming_it(self):
        answer = reading([run("Tests", "FAILURE"), context("Conformance", "ERROR")])
        self.assertEqual(self.checks(answer), Checks("red", H, ("Conformance", "Tests")))

    def test_a_required_check_in_progress_reads_pending(self):
        self.assertEqual(self.checks(reading([run("Tests", None, status="IN_PROGRESS")])).state, "pending")

    def test_a_blocked_merge_state_reads_pending_though_reported_checks_passed(self):
        self.assertEqual(self.checks(reading([run("Tests")], merge_state="BLOCKED")).state, "pending")

    def test_no_required_context_reads_pending(self):
        self.assertEqual(self.checks(reading([run("Lint", required=False)])).state, "pending")

    def test_a_merged_pull_reads_merged(self):
        self.assertEqual(self.checks(reading([], state="MERGED")), Checks("merged", H, ()))

    def test_every_page_of_contexts_is_read_through_its_cursor(self):
        gh = Scripted(reading([run("Tests")], next_page=True, cursor="c1"),
                      reading([run("Conformance", "FAILURE")], cursor="c2"))
        self.assertEqual(GitHubBumpForge(gh_json=gh).checks(SLUG, 7), Checks("red", H, ("Conformance",)))
        self.assertEqual([argv for argv, _ in gh.calls], [graphql_argv(), graphql_argv() + ["-f", "after=c1"]])

    def test_a_next_page_without_a_new_cursor_is_unreadable(self):
        for cursor in (None, "", "c1"):
            gh = Scripted(reading([run("Tests")], next_page=True, cursor="c1"),
                          reading([run("Tests")], next_page=True, cursor=cursor))
            with self.subTest(cursor=cursor), self.assertRaises(ForgeError):
                GitHubBumpForge(gh_json=gh).checks(SLUG, 7)

    def test_a_head_that_moves_between_pages_is_unreadable(self):
        gh = Scripted(reading([run("Tests")], next_page=True), reading([run("Tests")], head="e" * 40))
        with self.assertRaises(ForgeError):
            GitHubBumpForge(gh_json=gh).checks(SLUG, 7)

    def test_a_protected_context_that_never_reported_keeps_the_verdict_from_green(self):
        answer = reading([run("Tests")], state="MERGED", protected=["Tests", "Conformance"])
        self.assertEqual(GitHubBumpForge(gh_json=Scripted(answer)).verdict(SLUG, 7), Checks("pending", H, ()))

    def test_every_protected_context_reported_green_reads_green(self):
        answer = reading([run("Tests", required=False), context("Conformance")], state="MERGED",
                         protected=["Tests", "Conformance"])
        self.assertEqual(GitHubBumpForge(gh_json=Scripted(answer)).verdict(SLUG, 7), Checks("green", H, ()))

    def test_the_lock_pinned_at_a_commit_is_read_from_the_forge(self):
        text = base64.encodebytes(dumped(document())).decode()
        gh = Scripted({"encoding": "base64", "content": text}, {"encoding": "none", "content": ""})
        forge = GitHubBumpForge(gh_json=gh)
        self.assertEqual(forge.pinned(SLUG, H), REV_A)
        self.assertEqual(gh.calls[0][0], ["api", f"repos/{SLUG}/contents/devenv.lock?ref={H}"])
        with self.assertRaises(ForgeError):
            forge.pinned(SLUG, H)

    def test_the_verdict_of_a_merged_pull_judges_only_its_required_contexts(self):
        gh = Scripted(reading([run("Tests"), context("Conformance"), run("Lint", "FAILURE", required=False)],
                              state="MERGED", merge_state="UNKNOWN"))
        self.assertEqual(GitHubBumpForge(gh_json=gh).verdict(SLUG, 7), Checks("green", H, ()))
        self.assertEqual([argv for argv, _ in gh.calls], [graphql_argv()])

    def test_the_verdict_of_a_merged_pull_with_a_failed_required_status_is_red(self):
        answer = reading([context("Conformance", "FAILURE"), run("Tests")], state="MERGED")
        self.assertEqual(GitHubBumpForge(gh_json=Scripted(answer)).verdict(SLUG, 7),
                         Checks("red", H, ("Conformance",)))


class ListingTest(unittest.TestCase):
    def test_open_bumps_keeps_only_this_repositorys_bump_branches(self):
        pages = [[pull(3, f"lock-bump-{REV_A}"), pull(4, f"lock-bump-{REV_B}", "fork/fixture")],
                 [pull(5, "adopt-0123456789ab"), pull(6, "lock-bump-xyz")]]
        gh = Scripted(pages)
        self.assertEqual(GitHubBumpForge(gh_json=gh).open_bumps(SLUG, "main"), [OpenBump(3, REV_A)])
        self.assertEqual([argv for argv, _ in gh.calls],
                         [["api", "--paginate", "--slurp", f"repos/{SLUG}/pulls?state=open&base=main&per_page=100"]])

    def test_compare_returns_the_forges_status(self):
        gh = Scripted({"status": "ahead"}, {"status": "odd"})
        forge = GitHubBumpForge(gh_json=gh)
        self.assertEqual(forge.compare("octo/platform", REV_A, REV_B), "ahead")
        self.assertEqual(gh.calls[0][0], ["api", f"repos/octo/platform/compare/{REV_A}...{REV_B}"])
        with self.assertRaises(ForgeError):
            forge.compare("octo/platform", REV_A, REV_B)


class WriteTest(unittest.TestCase):
    def test_close_refuses_a_foreign_branch_before_any_call(self):
        gh, deleter = Scripted(), Deleter()
        with self.assertRaises(ValueError):
            GitHubBumpForge(gh_json=gh, run_gh=deleter).close(SLUG, 7, "main")
        self.assertEqual((gh.calls, deleter.calls), ([], []))

    def test_open_pull_refuses_a_foreign_branch_before_any_call(self):
        gh = Scripted()
        with self.assertRaises(ValueError):
            GitHubBumpForge(gh_json=gh).open_pull(SLUG, "adopt-0123456789ab", "main", "t", "b")
        self.assertEqual(gh.calls, [])

    def test_close_closes_the_pull_then_deletes_its_branch(self):
        gh, deleter = Scripted({}), Deleter()
        GitHubBumpForge(gh_json=gh, run_gh=deleter).close(SLUG, 7, f"lock-bump-{REV_A}")
        self.assertEqual([argv for argv, _ in gh.calls],
                         [["api", "-X", "PATCH", f"repos/{SLUG}/pulls/7", "-f", "state=closed"]])
        self.assertEqual(deleter.calls,
                         [(["api", "-X", "DELETE", f"repos/{SLUG}/git/refs/heads/lock-bump-{REV_A}"], (404, 422))])


if __name__ == "__main__":
    unittest.main()
