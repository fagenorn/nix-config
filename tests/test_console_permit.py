"""The permit judge: which Bash commands a manager's session may run (#1377, ADR-console-093).

`permit.judge` is pure over a `Grant` and injected forge readers, so every case here fakes the readers
and calls it directly: the three granted shapes, each refusal reason, the literal-word grammar, the
memo the console re-judges with, and the readers' fail-closed parsing.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import permit
from agent_tools.console.permit import (ALLOW, DENY, Forge, ForgeUnreadable, Grant,
                                        ReleaseApproval, judge, memoized, mentions,
                                        merge_target, words)

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
SHA = "b" * 40
HEAD = "c" * 40


class FakeForge:
    """Recording readers with the replies of a sprint's own open pull request and green check run."""

    def __init__(self):
        self.calls = []
        self.pr = {"branch": "issue-12-x", "repo": "o/r", "head": HEAD, "base": "main"}
        self.run = {"event": "pull_request", "branch": "issue-12-x", "repo": "o/r", "head": HEAD,
                    "prs": [7], "jobs": ["Nix Eval"]}
        self.required = frozenset({"Nix Eval"})
        self.pr_error = None

    def read_pr(self, slug, number):
        self.calls.append(("pr", slug, number))
        if self.pr_error is not None:
            raise self.pr_error
        return self.pr

    def read_run(self, slug, run_id):
        self.calls.append(("run", slug, run_id))
        return self.run

    def read_required(self, slug, base):
        self.calls.append(("required", slug, base))
        return self.required

    def forge(self):
        return Forge(self.read_pr, self.read_run, self.read_required)


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, self.root)
        self.approval = ReleaseApproval(
            "a" * 40, "v1.2.0", "v1.2.0 notes",
            frozenset({"publish:0123456789ab", "tag:ba9876543210"}))
        self.grant = Grant(
            slug="o/r", root=self.root, strategy="merge", delete_branch=True,
            branch_pattern="issue-<num>-<slug>", issues=frozenset({12}), others=frozenset({13}),
            releases=frozenset({self.approval}))
        self.fake = FakeForge()
        self.merge = f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA} --delete-branch"
        self.rerun = "gh run rerun 55 --failed --repo o/r"
        self.release = (
            f"release transaction run --repo-root {self.root} --commit {'a' * 40} --version v1.2.0 "
            "--title 'v1.2.0 notes' --notes-file /tmp/n --confirm publish:0123456789ab "
            "--confirm tag:ba9876543210")

    def judge(self, command, grant=None):
        return judge(command, grant or self.grant, self.fake.forge())

    def assertRefused(self, command, reason, grant=None):
        verdict = self.judge(command, grant)
        self.assertEqual((DENY, reason), (verdict.decision, verdict.reason), command)
        return verdict

    def test_the_sprints_own_merge_is_allowed(self):
        verdict = self.judge(self.merge)
        self.assertEqual(ALLOW, verdict.decision)
        self.assertEqual("merge", verdict.verb)
        self.assertEqual({"pr": 7, "head": SHA}, dict(verdict.target))
        self.assertEqual([("pr", "o/r", 7)], self.fake.calls)

    def test_an_admin_merge_is_refused(self):
        self.assertRefused(self.merge + " --admin", permit.ADMIN)
        self.assertEqual([], self.fake.calls)

    def test_a_merge_without_the_head_or_with_another_strategy_is_refused(self):
        cases = {
            "no head": f"gh pr merge 7 --repo o/r --merge --delete-branch",
            "squash": f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA} --delete-branch",
            "keeps the branch": f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA}",
            "short head": f"gh pr merge 7 --repo o/r --merge --match-head-commit {'b' * 39} --delete-branch",
            "extra flag": self.merge + " --subject x",
            "leading zero": self.merge.replace("merge 7", "merge 07"),
        }
        for name, command in cases.items():
            with self.subTest(name):
                self.assertRefused(command, permit.NOT_GRANTED)
        self.assertEqual([], self.fake.calls)

    def test_a_merge_without_a_granted_project_or_strategy_is_refused(self):
        for name, grant in {
            "no slug": Grant(None, self.root, "merge", True, None, frozenset(), frozenset(), frozenset()),
            "no strategy": Grant("o/r", self.root, None, True, None, frozenset(), frozenset(), frozenset()),
        }.items():
            with self.subTest(name):
                self.assertRefused(self.merge, permit.NOT_GRANTED, grant)

    def test_a_merge_that_keeps_no_branch_follows_the_projects_binding(self):
        grant = Grant("o/r", self.root, "squash", False, "issue-<num>-<slug>",
                      frozenset({12}), frozenset(), frozenset())
        command = f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA}"
        self.assertEqual(ALLOW, self.judge(command, grant).decision)
        self.assertRefused(command + " --delete-branch", permit.NOT_GRANTED, grant)

    def test_a_merge_in_another_repository_is_refused(self):
        self.assertRefused(self.merge.replace("--repo o/r", "--repo x/y"), permit.OTHER_REPO)
        self.assertEqual([], self.fake.calls)

    def test_a_merge_of_another_issues_pull_request_is_refused(self):
        cases = (
            ({"branch": "issue-99-x"}, permit.NOT_OWN_PR.format(pr=7)),
            ({"branch": "issue-13-x"}, permit.SHARED_ISSUE.format(issue=13)),
            ({"repo": "fork/r"}, permit.NOT_OWN_PR.format(pr=7)),
            ({"branch": "feature-x"}, permit.NOT_OWN_PR.format(pr=7)),
        )
        for change, reason in cases:
            with self.subTest(change):
                self.fake.pr = {**self.fake.pr, **change}
                self.assertRefused(self.merge, reason)

    def test_a_chained_or_shell_active_command_is_refused(self):
        cases = (
            "true && " + self.merge,
            self.merge + " ; ls",
            self.merge + " | cat",
            self.merge + " > /tmp/x",
            "X=1 " + self.merge,
            "gh pr merge $(echo 7) --repo o/r --merge",
            self.merge + "\nls",
            "bash -c '" + self.merge + "'",
            "/usr/bin/" + self.merge,
        )
        for command in cases:
            with self.subTest(command):
                self.assertRefused(command, permit.ALONE)
        self.assertEqual([], self.fake.calls)

    def test_shell_active_release_arguments_are_refused(self):
        for title in ('"$(id)"', '"a`b`"', "a*", "{a,b}", "x'y'", '"a!b"', "v1 #c"):
            with self.subTest(title):
                self.assertRefused(self.release.replace("'v1.2.0 notes'", title), permit.ALONE)
        self.assertRefused(self.release.replace("/tmp/n", "~/n"), permit.ALONE)

    def test_a_control_character_inside_a_quoted_word_is_refused_not_raised(self):
        for quote in ("'", '"'):
            for bad in ("\x00", "\n", "\x1b", "\x7f"):
                with self.subTest(quote=quote, bad=repr(bad)):
                    value = f"{quote}a{bad}b{quote}"
                    self.assertIsNone(words(f"x {value}"))
                    self.assertRefused(self.release.replace(self.root, value, 1), permit.ALONE)

    def test_quoted_titles_in_the_grammar_pass(self):
        self.assertEqual(["x", "--title", "v1.2.0: fixes (#12)"],
                         words("x --title 'v1.2.0: fixes (#12)'"))
        self.assertEqual(["x", "--title", "v1.2.0 notes"], words('x --title "v1.2.0 notes"'))
        self.assertEqual(["a", "b"], words("a\tb"))
        self.assertIsNone(words("=a"))

    def test_a_rerun_of_the_sprints_check_run_is_allowed(self):
        verdict = self.judge(self.rerun)
        self.assertEqual(ALLOW, verdict.decision)
        self.assertEqual("rerun", verdict.verb)
        self.assertEqual({"run": 55, "pr": 7}, dict(verdict.target))
        self.assertEqual([("run", "o/r", 55), ("pr", "o/r", 7), ("required", "o/r", "main")],
                         self.fake.calls)

    def test_a_deploy_rerun_is_refused(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event):
                self.fake.run = {**self.fake.run, "event": event}
                self.assertRefused(self.rerun, permit.DEPLOY_RERUN.format(run=55, event=event))

    def test_a_pull_request_triggered_deploy_run_is_refused(self):
        self.fake.run = {**self.fake.run, "jobs": ["deploy-preview"]}
        self.assertRefused(self.rerun, permit.NOT_CHECK_RUN.format(run=55))

    def test_a_rerun_of_every_job_or_of_another_pull_request_is_refused(self):
        self.assertRefused("gh run rerun 55 --repo o/r", permit.NOT_GRANTED)
        self.assertRefused(self.rerun.replace("--repo o/r", "--repo x/y"), permit.OTHER_REPO)
        self.fake.run = {**self.fake.run, "branch": "issue-99-x"}
        self.assertRefused(self.rerun, permit.NOT_OWN_RUN.format(run=55))
        self.fake.run = {**self.fake.run, "branch": "issue-13-x"}
        self.assertRefused(self.rerun, permit.SHARED_ISSUE.format(issue=13))
        self.fake.run = {**self.fake.run, "branch": "issue-12-x", "repo": "fork/r"}
        self.assertRefused(self.rerun, permit.NOT_OWN_RUN.format(run=55))
        self.fake.run = {**self.fake.run, "repo": "o/r", "prs": []}
        self.assertRefused(self.rerun, permit.NOT_OWN_RUN.format(run=55))
        self.fake.run = {**self.fake.run, "prs": [7]}
        self.fake.pr = {**self.fake.pr, "branch": "issue-12-other"}
        self.assertRefused(self.rerun, permit.NOT_OWN_RUN.format(run=55))
        self.fake.pr = {**self.fake.pr, "branch": "issue-12-x", "head": "d" * 40}
        self.assertRefused(self.rerun, permit.STALE_RUN.format(run=55))

    def test_an_approved_release_run_is_allowed(self):
        verdict = self.judge(self.release)
        self.assertEqual(ALLOW, verdict.decision)
        self.assertEqual("release", verdict.verb)
        self.assertEqual({"commit": "a" * 40, "version": "v1.2.0"}, dict(verdict.target))
        self.assertEqual([], self.fake.calls)
        swapped = self.release.replace(
            "--confirm publish:0123456789ab --confirm tag:ba9876543210",
            "--confirm tag:ba9876543210 --confirm publish:0123456789ab")
        self.assertEqual(ALLOW, self.judge(swapped).decision)
        self.assertEqual(ALLOW, self.judge(self.release + " --profile p").decision)

    def test_a_release_run_with_no_approved_card_is_refused(self):
        self.assertRefused(self.release.replace("v1.2.0 --title", "v1.3.0 --title"),
                           permit.NO_CARD.format(commit="a" * 40, version="v1.3.0"))
        bare = Grant("o/r", self.root, "merge", True, None, frozenset(), frozenset(), frozenset())
        self.assertRefused(self.release, permit.NO_CARD.format(commit="a" * 40, version="v1.2.0"),
                           bare)

    def test_a_changed_preview_at_the_same_release_is_refused(self):
        cases = (
            self.release.replace("publish:0123456789ab", "publish:ffffffffffff"),
            self.release.replace(" --confirm tag:ba9876543210", ""),
            self.release.replace("--title 'v1.2.0 notes'", "--title other"),
            self.release + " --confirm extra:000000000000",
        )
        for command in cases:
            with self.subTest(command):
                verdict = self.judge(command)
                self.assertEqual((DENY, permit.NO_CARD.format(
                    commit="a" * 40, version="v1.2.0")), (verdict.decision, verdict.reason))

    def test_a_release_resume_abandon_or_dispose_is_refused(self):
        self.assertRefused(f"release transaction run --repo-root {self.root} --confirm t",
                           permit.RESUME)
        self.assertRefused("release transaction abandon", permit.OWNERS_RELEASE_STEP)
        self.assertRefused("release transaction run --dispose no_recovery_path --reference x",
                           permit.OWNERS_RELEASE_STEP)
        self.assertRefused(self.release + " --reference x", permit.OWNERS_RELEASE_STEP)

    def test_a_release_run_elsewhere_or_with_extra_flags_is_refused(self):
        self.assertRefused(self.release.replace(self.root, "/elsewhere"), permit.WRONG_ROOT)
        self.assertRefused(self.release + " --force", permit.NOT_GRANTED)
        self.assertRefused(self.release + f" --commit {'a' * 40}", permit.NOT_GRANTED)
        self.assertRefused(self.release.replace(" --version v1.2.0", ""), permit.NOT_GRANTED)
        self.assertRefused(self.release.replace(" --confirm publish:0123456789ab"
                                                " --confirm tag:ba9876543210", ""), permit.NOT_GRANTED)
        self.assertRefused(self.release + " --profile", permit.NOT_GRANTED)

    def test_a_release_root_is_compared_after_resolving_links(self):
        link = Path(tempfile.mkdtemp()) / "link"
        self.addCleanup(os.rmdir, link.parent)
        link.symlink_to(self.root)
        self.addCleanup(link.unlink)
        self.assertEqual(ALLOW, self.judge(self.release.replace(self.root, str(link))).decision)

    def test_an_unreadable_forge_is_refused(self):
        self.fake.pr_error = ForgeUnreadable("boom")
        self.assertRefused(self.merge, permit.FORGE_UNREADABLE.format(reason="boom"))

    def test_a_command_naming_no_granted_verb_has_no_decision(self):
        for command in ("git status", "gh pr view 7", "release transaction preview --repo-root r",
                        "echo hi"):
            with self.subTest(command):
                verdict = self.judge(command)
                self.assertIsNone(verdict.decision)
                self.assertEqual(("", None, {}), (verdict.reason, verdict.verb, dict(verdict.target)))
        self.assertEqual([], self.fake.calls)

    def test_a_verdict_payload_names_its_four_members(self):
        self.assertEqual(
            {"verb": "merge", "decision": ALLOW, "reason": "", "target": {"pr": 7, "head": SHA}},
            self.judge(self.merge).payload())

    def test_mentions_reads_through_quotes_and_paths(self):
        for command in ("gh 'pr' merge 7", "/usr/bin/gh pr merge 7", "x;gh run rerun 1",
                        "release transaction run", 'rel"ease" transaction abandon'):
            with self.subTest(command):
                self.assertTrue(mentions(command))
        for command in ("gh pr view 7", "gh pr", "release transaction preview", "git status"):
            with self.subTest(command):
                self.assertFalse(mentions(command))

    def test_merge_target_names_only_the_granted_shape(self):
        self.assertEqual({"pr": 7, "head": SHA}, merge_target(self.merge, self.grant))
        self.assertIsNone(merge_target(self.merge + " --admin", self.grant))
        self.assertIsNone(merge_target("git status", self.grant))

    def test_the_granted_merge_lies_inside_the_guards_feature_form(self):
        spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn(
            ("feature", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>] --delete-branch", None),
            module.FORM_TABLE["merge"]["forms"])


class MemoTest(unittest.TestCase):
    def test_a_frozen_memo_answers_only_cached_reads(self):
        fake = FakeForge()
        memo = memoized(fake.forge())
        self.assertEqual(memo.read_pr("o/r", 7), memo.read_pr("o/r", 7))
        self.assertEqual([("pr", "o/r", 7)], fake.calls)
        frozen = memo.frozen()
        self.assertEqual(fake.pr, frozen.read_pr("o/r", 7))
        with self.assertRaises(ForgeUnreadable):
            frozen.read_pr("o/r", 8)
        self.assertEqual([("pr", "o/r", 7)], fake.calls)

    def test_a_memoized_failure_is_raised_again_without_a_second_read(self):
        fake = FakeForge()
        fake.pr_error = ForgeUnreadable("boom")
        memo = memoized(fake.forge())
        for _ in range(2):
            with self.assertRaises(ForgeUnreadable):
                memo.read_pr("o/r", 7)
        with self.assertRaises(ForgeUnreadable):
            memo.frozen().read_pr("o/r", 7)
        self.assertEqual([("pr", "o/r", 7)], fake.calls)


class ReaderTest(unittest.TestCase):
    PULL = {"head": {"ref": "issue-12-x", "sha": HEAD, "repo": {"full_name": "o/r"}},
            "base": {"ref": "main"}}
    RUN = {"event": "pull_request", "head_branch": "issue-12-x", "head_sha": HEAD,
           "head_repository": {"full_name": "o/r"}, "pull_requests": [{"number": 7}]}
    JOBS = {"jobs": [{"name": "Nix Eval"}, {"name": "Other"}]}
    PROTECTION = {"checks": [{"context": "Nix Eval", "app_id": 1}], "contexts": ["Nix Eval", "Budget"]}

    def reply(self, payloads):
        return mock.patch.object(permit.forge_api, "api_get", side_effect=lambda path, *a: payloads[path])

    def test_readers_raise_on_a_malformed_reply(self):
        with mock.patch.object(permit.forge_api, "api_get", return_value={}):
            for name, args in (("read_pr", ("o/r", 7)), ("read_run", ("o/r", 55)),
                               ("read_required", ("o/r", "main"))):
                with self.subTest(name), self.assertRaises(ForgeUnreadable):
                    getattr(permit, name)(*args)

    def test_readers_raise_when_the_forge_fails(self):
        error = permit.forge_api.ForgeError("gh_failed", "HTTP 502 secret detail")
        with mock.patch.object(permit.forge_api, "api_get", side_effect=error):
            for name, args in (("read_pr", ("o/r", 7)), ("read_run", ("o/r", 55)),
                               ("read_required", ("o/r", "main"))):
                with self.subTest(name), self.assertRaises(ForgeUnreadable) as caught:
                    getattr(permit, name)(*args)
                self.assertNotIn("secret", str(caught.exception))

    def test_a_pull_request_with_a_missing_member_is_unreadable(self):
        for broken in ({**self.PULL, "head": {**self.PULL["head"], "repo": None}},
                       {**self.PULL, "head": {**self.PULL["head"], "sha": 7}},
                       {**self.PULL, "base": {}}):
            with self.subTest(broken), self.reply({"repos/o/r/pulls/7": broken}):
                with self.assertRaises(ForgeUnreadable):
                    permit.read_pr("o/r", 7)

    def test_a_run_with_a_malformed_member_is_unreadable(self):
        for run, jobs in (({**self.RUN, "head_repository": None}, self.JOBS),
                          ({**self.RUN, "pull_requests": [{"number": "7"}]}, self.JOBS),
                          ({**self.RUN, "event": None}, self.JOBS),
                          (self.RUN, {"jobs": [{"name": 3}]}),
                          (self.RUN, {})):
            with self.subTest(run=run, jobs=jobs), self.reply({
                    "repos/o/r/actions/runs/55": run, "repos/o/r/actions/runs/55/jobs": jobs}):
                with self.assertRaises(ForgeUnreadable):
                    permit.read_run("o/r", 55)

    def test_readers_return_the_documented_shapes(self):
        payloads = {
            "repos/o/r/pulls/7": self.PULL,
            "repos/o/r/actions/runs/55": self.RUN,
            "repos/o/r/actions/runs/55/jobs": self.JOBS,
            "repos/o/r/branches/main/protection/required_status_checks": self.PROTECTION,
        }
        with self.reply(payloads):
            self.assertEqual({"branch": "issue-12-x", "repo": "o/r", "head": HEAD, "base": "main"},
                             permit.read_pr("o/r", 7))
            self.assertEqual({"event": "pull_request", "branch": "issue-12-x", "repo": "o/r",
                              "head": HEAD, "prs": [7], "jobs": ["Nix Eval", "Other"]},
                             permit.read_run("o/r", 55))
            self.assertEqual(frozenset({"Nix Eval", "Budget"}), permit.read_required("o/r", "main"))

    def test_a_protection_with_a_malformed_member_is_unreadable(self):
        path = "repos/o/r/branches/main/protection/required_status_checks"
        for broken in ({"checks": [{"app_id": 1}], "contexts": []},
                       {"checks": [], "contexts": [3]},
                       {"checks": "x", "contexts": []},
                       {"contexts": []}):
            with self.subTest(broken), self.reply({path: broken}):
                with self.assertRaises(ForgeUnreadable):
                    permit.read_required("o/r", "main")


class MergeBindingTest(unittest.TestCase):
    def test_the_binding_is_the_contracts_or_none_and_false(self):
        contract = {"bindings": {"vcs": {"merge": {"strategy": "squash", "delete_branch": True}}}}
        with mock.patch.object(permit.resolve_project, "resolve", return_value=contract):
            self.assertEqual(("squash", True), permit.merge_binding("/r"))
        with mock.patch.object(permit.resolve_project, "resolve", side_effect=ValueError("x")):
            self.assertEqual((None, False), permit.merge_binding("/r"))
        with mock.patch.object(permit.resolve_project, "resolve",
                               return_value={"bindings": {"vcs": {"merge": {"strategy": 3}}}}):
            self.assertEqual((None, False), permit.merge_binding("/r"))


if __name__ == "__main__":
    unittest.main()
