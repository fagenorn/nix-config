"""The permit judge: which Bash commands a manager's session may run (#1377, ADR-console-094).

`permit.judge` is pure over a `Grant` and injected forge readers, so every case here fakes the readers
and calls it directly: the two granted shapes, each refusal reason, the literal-word grammar, the
memo the console re-judges with, and the readers' fail-closed parsing.
"""
import base64
import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agent_tools.console import permit, prompt_card, sprint, sprints
from agent_tools.release import release
from agent_tools.console.permit import (ALLOW, DENY, Forge, ForgeUnreadable, Grant, judge,
                                        memoized, mentions, merge_target, words)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
SHA = "b" * 40
HEAD = "c" * 40


class FakeForge:
    """Recording readers with the replies of a sprint's own open pull request and green check run."""

    def __init__(self):
        self.calls = []
        self.pr = {"branch": "issue-12-x", "repo": "o/r", "head": SHA, "base": "main"}
        self.run = {"event": "pull_request", "branch": "issue-12-x", "repo": "o/r", "head": SHA,
                    "prs": [7], "rerun": ["Nix Eval"]}
        self.required = frozenset({"Nix Eval"})
        self.pr_error = None
        self.release_pr = None
        self.release_error = None

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

    def read_release_pr(self, slug, root, branch):
        self.calls.append(("release", slug, root, branch))
        if self.release_error is not None:
            raise self.release_error
        return self.release_pr if self.release_pr is not None and self.release_pr["branch"] == branch else None

    def forge(self, read_pr=None):
        return Forge(read_pr or self.read_pr, self.read_run, self.read_required, self.read_release_pr)


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, self.root)
        self.grant = Grant(
            slug="o/r", root=self.root, strategy="merge", delete_branch=True,
            branch_pattern="issue-<num>-<slug>", issues=frozenset({12}), others=frozenset({13}))
        self.fake = FakeForge()
        self.merge = f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA} --delete-branch"
        self.rerun = "gh run rerun 55 --failed --repo o/r"

    def judge(self, command, grant=None):
        return judge(command, grant or self.grant, self.fake.forge())

    def assertRefused(self, command, reason, grant=None):
        verdict = self.judge(command, grant)
        self.assertEqual((DENY, reason), (verdict.decision, verdict.reason), command)
        return verdict

    def spelling(self, sentence, verb="merge", missing=(), grant=None):
        return permit.spelling_refusal(sentence, verb, grant or self.grant, missing)

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
            "no head": (f"gh pr merge 7 --repo o/r --merge --delete-branch", ("--match-head-commit",)),
            "squash": (f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA} --delete-branch",
                       ("--merge",)),
            "keeps the branch": (f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA}",
                                 ("--delete-branch",)),
            "short head": (f"gh pr merge 7 --repo o/r --merge --match-head-commit {'b' * 39} --delete-branch",
                           ()),
            "extra flag": (self.merge + " --subject x", ()),
            "leading zero": (self.merge.replace("merge 7", "merge 07"), ()),
        }
        for name, (command, missing) in cases.items():
            with self.subTest(name):
                self.assertRefused(command, self.spelling(permit.NOT_GRANTED, missing=missing))
        self.assertEqual([], self.fake.calls)

    def test_a_merge_without_a_granted_project_or_strategy_is_refused(self):
        for name, grant in {
            "no slug": Grant(None, self.root, "merge", True, None, frozenset(), frozenset()),
            "no strategy": Grant("o/r", self.root, None, True, None, frozenset(), frozenset()),
        }.items():
            with self.subTest(name):
                self.assertRefused(self.merge, self.spelling(permit.NOT_GRANTED, grant=grant), grant)

    def test_a_merge_that_keeps_no_branch_follows_the_projects_binding(self):
        grant = Grant("o/r", self.root, "squash", False, "issue-<num>-<slug>",
                      frozenset({12}), frozenset())
        command = f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA}"
        self.assertEqual(ALLOW, self.judge(command, grant).decision)
        self.assertRefused(command + " --delete-branch",
                           self.spelling(permit.NOT_GRANTED, grant=grant), grant)

    def test_a_merge_at_another_head_than_the_pull_requests_is_refused(self):
        self.fake.pr = {**self.fake.pr, "head": HEAD}
        self.assertRefused(self.merge, permit.STALE_HEAD.format(pr=7))
        self.assertEqual([("pr", "o/r", 7)], self.fake.calls)

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
                self.assertRefused(command, self.spelling(permit.ALONE))
        self.assertEqual([], self.fake.calls)

    def test_shell_active_arguments_are_refused(self):
        for word in ('"$(id)"', '"a`b`"', "a*", "{a,b}", "x'y'", '"a!b"', "#c", "~/n"):
            with self.subTest(word):
                self.assertRefused(self.merge + " " + word, self.spelling(permit.ALONE))

    def test_a_control_character_inside_a_quoted_word_is_refused_not_raised(self):
        for quote in ("'", '"'):
            for bad in ("\x00", "\n", "\x1b", "\x7f"):
                with self.subTest(quote=quote, bad=repr(bad)):
                    value = f"{quote}a{bad}b{quote}"
                    self.assertIsNone(words(f"x {value}"))
                    self.assertRefused(self.merge.replace("--repo o/r", f"--repo {value}"),
                                       self.spelling(permit.ALONE))

    def test_quoted_titles_in_the_grammar_pass(self):
        self.assertEqual(["x", "--title", "v1.2.0: fixes (#12)"],
                         words("x --title 'v1.2.0: fixes (#12)'"))
        self.assertEqual(["x", "--title", "v1.2.0 notes"], words('x --title "v1.2.0 notes"'))
        self.assertEqual(["a", "b"], words("a\tb"))
        self.assertIsNone(words("=a"))

    def test_a_merge_or_rerun_behind_a_credential_scrub_prefix_is_judged_as_the_bare_form(self):
        verdict = self.judge("env -u GITHUB_TOKEN -u GH_TOKEN " + self.merge)
        self.assertEqual((ALLOW, "merge", {"pr": 7, "head": SHA}),
                         (verdict.decision, verdict.verb, dict(verdict.target)))
        for prefix in permit.SCRUB_PREFIXES:
            with self.subTest(prefix):
                self.assertEqual(ALLOW, self.judge(prefix + self.merge).decision)
                self.assertEqual(ALLOW, self.judge(prefix + self.rerun).decision)
                self.assertEqual({"pr": 7, "head": SHA}, merge_target(prefix + self.merge, self.grant))

    def test_the_permit_takes_exactly_the_guards_scrub_prefixes(self):
        spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.SCRUB_PREFIXES, permit.SCRUB_PREFIXES)
        self.assertEqual(module.GH_ENV_TOKEN_NAMES, permit.GH_ENV_TOKEN_NAMES)
        self.assertEqual(module.prefix_clause(), permit.PREFIX_CLAUSE)

    def test_a_near_miss_prefix_is_refused_alone_with_the_accepted_form(self):
        reason = ("This command runs only alone, spelled exactly as the permitted form, with no operator, "
                  "expansion or wrapper. Accepted: gh pr merge <n> --repo o/r --merge --match-head-commit "
                  "<sha> --delete-branch; optional prefix: env -u GITHUB_TOKEN -u GH_TOKEN | unset "
                  "GITHUB_TOKEN && | env -u GITHUB_TOKEN")
        for prefix in ("env -u GITHUB_TOKEN  ", "env -u PATH ", "env -u GITHUB_TOKEN -u GITHUB_TOKEN ",
                       "env -uGITHUB_TOKEN ", "unset GITHUB_TOKEN && env -u GH_TOKEN ", "unset PATH && ",
                       "X=1 "):
            with self.subTest(prefix):
                verdict = self.judge(prefix + self.merge)
                self.assertEqual((DENY, reason), (verdict.decision, verdict.reason))
        self.assertEqual([], self.fake.calls)

    def test_a_merge_spelling_refusal_names_the_missing_flag_and_the_accepted_form(self):
        n = "The permit grants only the exact merge and rerun forms, and this one differs."
        a = ("This command runs only alone, spelled exactly as the permitted form, with no operator, "
             "expansion or wrapper.")
        p = "optional prefix: env -u GITHUB_TOKEN -u GH_TOKEN | unset GITHUB_TOKEN && | env -u GITHUB_TOKEN"
        f = "gh pr merge <n> --repo o/r --merge --match-head-commit <sha> --delete-branch"
        keeps = f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA}"
        cases = (
            ("gh pr merge 7 --repo o/r --merge --delete-branch",
             f"{n} Missing: --match-head-commit. Accepted: {f}; {p}"),
            (keeps, f"{n} Missing: --delete-branch. Accepted: {f}; {p}"),
            ("env -u GITHUB_TOKEN -u GH_TOKEN " + keeps,
             f"{n} Missing: --delete-branch. Accepted: {f}; {p}"),
            (f"gh pr merge 7 --repo o/r --squash --match-head-commit {SHA} --delete-branch",
             f"{n} Missing: --merge. Accepted: {f}; {p}"),
            (self.merge + " --subject x", f"{n} Accepted: {f}; {p}"),
            (f"gh pr merge 7 --repo o/r --merg --match-head-commit {SHA} --delete-branch",
             f"{n} Missing: --merge. Accepted: {f}; {p}"),
            ("env -u PATH " + keeps, f"{a} Missing: --delete-branch. Accepted: {f}; {p}"),
            (keeps + " | cat", f"{a} Accepted: {f}; {p}"),
            ("gh run rerun 55 --repo o/r",
             f"{n} Missing: --failed. Accepted: gh run rerun <id> --failed --repo o/r; {p}"),
        )
        for command, reason in cases:
            with self.subTest(command):
                verdict = self.judge(command)
                self.assertEqual((DENY, reason), (verdict.decision, verdict.reason))

    def test_a_release_run_behind_a_scrub_prefix_gets_no_decision(self):
        self.assertIsNone(self.judge("env -u GITHUB_TOKEN release transaction run --commit " + SHA).decision)

    def test_a_rerun_of_the_sprints_check_run_is_allowed(self):
        verdict = self.judge(self.rerun)
        self.assertEqual(ALLOW, verdict.decision)
        self.assertEqual("rerun", verdict.verb)
        self.assertEqual({"run": 55, "pr": 7, "head": SHA, "count": 1, "members": []},
                         dict(verdict.target))
        self.assertEqual([("run", "o/r", 55), ("pr", "o/r", 7), ("required", "o/r", "main")],
                         self.fake.calls)

    def release_run(self, event, **change):
        """A run of the open release pull request (`pull_request`) or of the candidate's push (`push`)."""
        self.fake.release_pr = {"pr": 9, "branch": "develop", "head": SHA, "base": "main"}
        self.fake.run = {"event": event, "branch": "develop", "repo": "o/r", "head": SHA,
                         "prs": [9] if event == "pull_request" else [], "rerun": ["Nix Eval"], **change}
        self.fake.calls = []

    def test_a_rerun_of_the_release_pull_request_run_and_of_the_candidates_push_run_is_allowed(self):
        for event in ("pull_request", "push"):
            with self.subTest(event):
                self.release_run(event)
                verdict = self.judge(self.rerun)
                self.assertEqual((ALLOW, "rerun"), (verdict.decision, verdict.verb))
                self.assertEqual({"run": 55, "pr": 9, "head": SHA, "count": 1, "members": [],
                                  "release": event}, dict(verdict.target))
                self.assertEqual([("run", "o/r", 55), ("release", "o/r", self.root, "develop"),
                                  ("required", "o/r", "main")], self.fake.calls)

    def test_release_reruns_share_the_per_head_cap_and_name_the_release_pull_request(self):
        for event in ("pull_request", "push"):
            with self.subTest(event):
                self.release_run(event)
                one = dataclasses.replace(self.grant, reruns={SHA: (permit.Rerun(53),)})
                verdict = self.judge(self.rerun, one)
                self.assertEqual((ALLOW, 2), (verdict.decision, verdict.target["count"]))
                two = dataclasses.replace(self.grant, reruns={SHA: (permit.Rerun(53), permit.Rerun(54))})
                self.assertRefused(self.rerun, permit.RERUN_LIMIT.format(
                    pr=9, head=SHA, reruns="run 53 (failing: no members reported) and "
                                           "run 54 (failing: no members reported)"), two)

    def test_a_rerun_of_a_run_that_is_no_release_run_of_this_project_is_refused(self):
        deploy = permit.DEPLOY_RERUN.format(run=55, event="push")
        not_own = permit.NOT_OWN_RUN.format(run=55)
        rows = {
            "a": ("push", {}, permit.OTHER_REPO, "no read"),
            "b": ("push", {"release": {"head": "d" * 40}}, deploy, None),
            "c": ("push", {"release": None}, deploy, None),
            "d": ("push", {"branch": "main"}, deploy, "read main"),
            "e": ("workflow_dispatch", {}, permit.DEPLOY_RERUN.format(run=55, event="workflow_dispatch"),
                  "no read"),
            "f": ("push", {"repo": "fork/r"}, deploy, "no read"),
            "g": ("push", {"release_error": ForgeUnreadable("x")},
                  permit.FORGE_UNREADABLE.format(reason="x"), None),
            "h": ("pull_request", {"release": None}, not_own, None),
            "i": ("pull_request", {"prs": [8]}, not_own, None),
            "j": ("pull_request", {"repo": "fork/r"}, not_own, "no read"),
            "k": ("pull_request", {"release": {"head": "d" * 40}}, permit.STALE_RUN.format(run=55), None),
            "l": ("pull_request", {"rerun": ["deploy-preview"]}, permit.NOT_CHECK_RUN.format(run=55), None),
            "m": ("push", {"rerun": ["Nix Eval", "deploy"]}, permit.NOT_CHECK_RUN.format(run=55), None),
            "n": ("pull_request", {"branch": "issue-13-x"}, permit.SHARED_ISSUE.format(issue=13), "no read"),
        }
        for row, (event, change, reason, note) in rows.items():
            with self.subTest(row):
                self.fake = FakeForge()
                change = dict(change)
                release = change.pop("release", ...)
                error = change.pop("release_error", None)
                self.release_run(event, **change)
                if release is None:
                    self.fake.release_pr = None
                elif release is not ...:
                    self.fake.release_pr = {**self.fake.release_pr, **release}
                self.fake.release_error = error
                command = self.rerun.replace("--repo o/r", "--repo x/y") if row == "a" else self.rerun
                self.assertRefused(command, reason)
                if row == "a":
                    self.assertEqual([], self.fake.calls)
                if note == "no read":
                    self.assertFalse([call for call in self.fake.calls if call[0] == "release"])
                if note == "read main":
                    self.assertIn(("release", "o/r", self.root, "main"), self.fake.calls)

    def test_a_release_run_with_a_job_that_has_not_finished_is_refused_and_takes_no_slot(self):
        for event in ("pull_request", "push"):
            with self.subTest(event):
                self.release_run(event, pending=True)
                self.assertRefused(self.rerun, permit.RUN_PENDING.format(run=55))
                self.assertNotIn(("required", "o/r", "main"), self.fake.calls)
                self.release_run(event, pending=False)
                self.assertEqual(ALLOW, self.judge(self.rerun).decision)

    def test_a_rerun_of_the_push_run_at_the_tip_of_a_single_branch_project_is_allowed_within_the_cap(self):
        self.release_run("push", branch="main", prs=[])
        self.fake.release_pr = {"pr": None, "branch": "main", "head": SHA, "base": "main"}
        verdict = self.judge(self.rerun)
        self.assertEqual((ALLOW, "rerun"), (verdict.decision, verdict.verb))
        self.assertEqual({"run": 55, "head": SHA, "count": 1, "members": [], "release": "push"},
                         dict(verdict.target))
        two = dataclasses.replace(self.grant, reruns={SHA: (permit.Rerun(53), permit.Rerun(54))})
        self.assertRefused(self.rerun, permit.RERUN_LIMIT_TIP.format(
            branch="main", head=SHA, reruns="run 53 (failing: no members reported) and "
                                            "run 54 (failing: no members reported)"), two)
        self.fake.release_pr = {**self.fake.release_pr, "head": "d" * 40}
        self.assertRefused(self.rerun, permit.DEPLOY_RERUN.format(run=55, event="push"))
        self.release_run("pull_request", branch="main", prs=[9])
        self.fake.release_pr = {"pr": None, "branch": "main", "head": SHA, "base": "main"}
        self.assertRefused(self.rerun, permit.NOT_OWN_RUN.format(run=55))

    def test_a_sprint_rerun_keeps_its_target_and_reads_no_release_pull_request(self):
        self.fake.release_pr = {"pr": 9, "branch": "issue-12-x", "head": SHA, "base": "main"}
        verdict = self.judge(self.rerun)
        self.assertEqual({"run": 55, "pr": 7, "head": SHA, "count": 1, "members": []}, dict(verdict.target))
        self.assertEqual([("run", "o/r", 55), ("pr", "o/r", 7), ("required", "o/r", "main")],
                         self.fake.calls)

    def test_an_allowed_rerun_names_its_head_its_count_so_far_and_the_failing_suite_members(self):
        self.fake.run = {**self.fake.run, "members": ["tests/test_a.py", "tests/test_b.py"]}
        first = self.judge(self.rerun)
        self.assertEqual({"run": 55, "pr": 7, "head": SHA, "count": 1,
                          "members": ["tests/test_a.py", "tests/test_b.py"]}, dict(first.target))
        second = self.judge(self.rerun, dataclasses.replace(self.grant, reruns={SHA: (permit.Rerun(54),)}))
        self.assertEqual((ALLOW, 2), (second.decision, second.target["count"]))

    def test_a_third_rerun_of_one_head_is_refused_naming_the_two_reruns_and_a_new_head_starts_at_zero(self):
        two = (permit.Rerun(53, ("tests/test_a.py", "tests/test_b.py")), permit.Rerun(54))
        grant = dataclasses.replace(self.grant, reruns={SHA: two, "d" * 40: two})
        verdict = self.assertRefused(self.rerun, permit.RERUN_LIMIT.format(
            pr=7, head=SHA, reruns="run 53 (failing: tests/test_a.py, tests/test_b.py) and "
                                   "run 54 (failing: no members reported)"), grant)
        self.assertIn("twice", verdict.reason)
        self.assertIn("run 53", verdict.reason)
        self.assertIn("tests/test_b.py", verdict.reason)
        self.assertIn("run 54", verdict.reason)
        self.assertIn("reported or fixed", verdict.reason)
        self.fake.pr = {**self.fake.pr, "head": "e" * 40}
        self.fake.run = {**self.fake.run, "head": "e" * 40}
        fresh = self.judge(self.rerun, grant)
        self.assertEqual((ALLOW, 1), (fresh.decision, fresh.target["count"]))

    def test_the_rerun_limit_does_not_hide_an_earlier_refusal(self):
        grant = dataclasses.replace(self.grant, reruns={SHA: (permit.Rerun(53), permit.Rerun(54))})
        self.fake.run = {**self.fake.run, "rerun": ["deploy-preview"]}
        self.assertRefused(self.rerun, permit.NOT_CHECK_RUN.format(run=55), grant)

    def test_a_deploy_rerun_is_refused(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event):
                self.fake.run = {**self.fake.run, "event": event}
                self.assertRefused(self.rerun, permit.DEPLOY_RERUN.format(run=55, event=event))

    def test_a_pull_request_triggered_deploy_run_is_refused(self):
        self.fake.run = {**self.fake.run, "rerun": ["deploy-preview"]}
        self.assertRefused(self.rerun, permit.NOT_CHECK_RUN.format(run=55))

    def test_a_rerun_that_would_also_run_a_job_that_is_no_required_check_is_refused(self):
        self.fake.run = {**self.fake.run, "rerun": ["Nix Eval", "deploy-preview"]}
        self.assertRefused(self.rerun, permit.NOT_CHECK_RUN.format(run=55))
        self.fake.run = {**self.fake.run, "rerun": []}
        self.assertRefused(self.rerun, permit.NOT_CHECK_RUN.format(run=55))
        self.fake.required = frozenset({"Nix Eval", "Budget"})
        self.fake.run = {**self.fake.run, "rerun": ["Nix Eval", "Budget"]}
        self.assertEqual(ALLOW, self.judge(self.rerun).decision)

    def test_a_rerun_of_every_job_or_of_another_pull_request_is_refused(self):
        self.assertRefused("gh run rerun 55 --repo o/r",
                           self.spelling(permit.NOT_GRANTED, "rerun", ("--failed",)))
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

    def run_forms(self):
        root, commit = self.root, "a" * 40
        plain = (f"release transaction run --repo-root {root} --commit {commit} --version v1.2.0 "
                 "--title 'v1.2.0 notes' --notes-file /tmp/n --confirm tag:0123456789ab "
                 "--confirm github-release:0123456789ab")
        target = {"commit": commit, "version": "v1.2.0"}
        return [
            (plain, target),
            (plain.replace("'v1.2.0 notes'", '"v1.2.0 notes"'), target),
            (f"release transaction run --repo-root {root} --commit {commit} --version v1.2.0 "
             "--notes-file /tmp/a--dispose.md --title 'stop --dispose spam' --confirm tag:0123456789ab",
             target),
            (f"release transaction run --repo-root {root} --confirm tag:0123456789ab",
             {"commit": None, "version": None}),
            (f"release transaction run --repo-root {root} --commit {commit} --version v1.2.0 "
             "--title 'gh pr merge and gh run rerun notes' --notes-file /tmp/gh-pr-merge.md "
             "--confirm tag:0123456789ab", target),
        ]

    def test_the_plain_release_run_is_allowed(self):
        for command, target in self.run_forms():
            with self.subTest(command):
                self.assertEqual("release", permit.verb_of(command))
                self.assertTrue(mentions(command))
                verdict = self.judge(command)
                self.assertEqual((ALLOW, "", "release", target),
                                 (verdict.decision, verdict.reason, verdict.verb, dict(verdict.target)))
        self.assertEqual([], self.fake.calls)

    ABANDONS = ("release transaction abandon --repo-root r",
                "/nix/store/x-agent-tools/bin/release transaction abandon --repo-root r",
                "env A=1 release transaction abandon --repo-root r",
                "python3 -m agent_tools.release.release transaction abandon --repo-root r",
                "true && release transaction abandon --repo-root r",
                "bash -c 'release transaction abandon --repo-root r'",
                'sh -lc "true; release transaction abandon --repo-root r"',
                "env X=1 zsh -c '/opt/bin/release transaction abandon'",
                "eval 'release transaction abandon --repo-root r'")
    DISPOSES = ("release transaction run --repo-root r --dispose no_recovery_path --reference x --confirm t",
                "release transaction run --repo-root r --dispose=no_recovery_path --reference=x --confirm t",
                "/opt/bin/release transaction run --repo-root r --confirm t --dispose no_recovery_path "
                "--reference x",
                "bash -c 'release transaction run --repo-root r --dispose no_recovery_path "
                "--reference x --confirm t'")

    def test_a_manager_is_refused_abandon_and_dispose_however_the_program_is_named(self):
        for commands, verb, reason in ((self.ABANDONS, permit.ABANDON, permit.NO_ABANDON),
                                       (self.DISPOSES, permit.DISPOSE, permit.NO_DISPOSE)):
            for command in commands:
                with self.subTest(command):
                    self.assertEqual(verb, permit.verb_of(command))
                    self.assertTrue(mentions(command))
                    verdict = self.judge(command)
                    self.assertEqual((DENY, reason, verb, {}),
                                     (verdict.decision, verdict.reason, verdict.verb, dict(verdict.target)))
        self.assertEqual([], self.fake.calls)
        self.assertEqual("release-abandon", permit.ABANDON)
        self.assertEqual("release-dispose", permit.DISPOSE)

    CHAINED = (
        ("release transaction preview --repo-root r; /opt/bin/release transaction abandon --repo-root r",
         permit.ABANDON),
        ("release transaction run --repo-root r --confirm t; /opt/bin/release transaction abandon --repo-root r",
         permit.ABANDON),
        ("echo release transaction ok; release transaction abandon --repo-root r", permit.ABANDON),
        ("release transaction status --repo-root r && release transaction run --repo-root r "
         "--dispose no_recovery_path --reference x --confirm t", permit.DISPOSE))

    def test_an_earlier_release_mention_does_not_hide_a_later_abandon_or_dispose(self):
        for command, verb in self.CHAINED:
            with self.subTest(command):
                self.assertEqual(verb, permit.verb_of(command))
                self.assertTrue(mentions(command))
                verdict = self.judge(command)
                self.assertEqual((DENY, verb), (verdict.decision, verdict.verb))
        self.assertEqual([], self.fake.calls)

    NO_DECISION = ("release transaction preview --repo-root r",
                   "release transaction preview --repo-root r --dispose no_recovery_path",
                   "env X=1 release transaction run --repo-root r --confirm t",
                   "printf '%s\\n' x | xargs release",
                   "echo 'release transaction abandon'",
                   "bash -c 'release transaction preview --repo-root r'",
                   "r=release; $r transaction run",
                   "git log -1 --format=release%x20transaction%x20run%x20--candidate%x20X | sh")

    def test_a_leading_release_run_the_permit_cannot_read_is_refused(self):
        spelling = ("A release runs only as the plain release transaction run: each flag one of --repo-root, "
                    "--profile, --commit, --version, --title, --notes-file, --confirm, each followed by its "
                    "value as the next word, and only --confirm repeated.")
        for command in ("release transaction run --repo-root r --disp no_recovery_path --reference x --confirm t",
                        "release transaction run --repo-root=r --confirm t",
                        "release transaction run --repo-root r --repo-root s --confirm t",
                        "release transaction run --repo-root r --title -x --confirm t",
                        "release transaction run --repo-root r --confirm t && echo done",
                        f"release transaction run --commit {SHA} --version v1.2.3 --preview",
                        'release transaction run --repo-root r --title "$HOME" --confirm t'):
            with self.subTest(command):
                verdict = self.judge(command)
                self.assertEqual((DENY, permit.RELEASE, spelling),
                                 (verdict.decision, verdict.verb, verdict.reason))
                self.assertTrue(mentions(command))
        self.assertEqual([], self.fake.calls)

    def test_a_release_run_behind_another_command_of_a_chain_is_refused(self):
        """The client matches each subcommand of a chain on its own, so the release allow rule matches
        the segment wherever it stands, and the permit must decide the whole text (#1592)."""
        plain = f"release transaction run --repo-root r --commit {SHA} --version v1.2.3 --confirm t"
        for command in ("git status && release transaction run --help",
                        f"git status && {plain}", f"git status; {plain}", f"git status | {plain}",
                        f"git status\n{plain}", f"(git status; {plain})", f"echo $({plain})",
                        f"timeout 5 {plain}", f"git status && time {plain}",
                        "git status && LANG=C release transaction run --help",
                        "git status && A=x\\ y release transaction run --help",
                        "A=x\\ y release transaction run --help",
                        f'git status && LANG="a b" X=1 {plain}',
                        "if true; then release transaction run --help; fi",
                        "while true; do release transaction run --help; done",
                        "git status && ! release transaction run --help",
                        "git status; if false; then :; else release transaction run --help; fi"):
            with self.subTest(command):
                self.assertTrue(mentions(command))
                verdict = self.judge(command)
                self.assertEqual((DENY, permit.RELEASE, permit.RELEASE_SPELLING),
                                 (verdict.decision, verdict.verb, verdict.reason))
        self.assertEqual([], self.fake.calls)

    def test_a_command_with_a_quoted_assignment_value_is_classified_in_bounded_time(self):
        """A failed search must not backtrack over the many splits of a quoted value: ten JSON pairs took
        40 s, past the hook's timeout, so the client ran the call without the permit's verdict (#1592)."""
        pairs = ",".join(f'"k{i}":"v{i}"' for i in range(10))
        for command in ("DATA='{" + pairs + "}' jq . x", "DATA={" + pairs + "} jq . x",
                        "A=" + '""' * 40 + " jq . x"):
            with self.subTest(command[:30]):
                started = time.monotonic()
                self.assertIsNone(permit.verb_of(command))
                self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(permit.RELEASE, permit.verb_of(
            "DATA='{" + pairs + "}' release transaction run x"))

    def test_a_wrapper_with_many_dash_arguments_is_classified_in_bounded_time(self):
        """Each wrapper argument must parse one way: a dash argument split as `-`+word or word, and a wrapper
        word as a wrapper or an argument, so a failed search doubled with every one (24 took 3.5 s, about 29
        pass the hook's timeout, #1592)."""
        for command in ("timeout" + " -a" * 40 + " x", "timeout " * 40 + "x",
                        "time nix build" + " --show-trace -L -v" * 12 + " x",
                        "xargs" + " -I time" * 30 + " x"):
            with self.subTest(command[:30]):
                started = time.monotonic()
                self.assertIsNone(permit.verb_of(command))
                self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(permit.RELEASE, permit.verb_of(
            "timeout" + " -a" * 40 + " release transaction run x"))
        self.assertEqual(permit.RELEASE, permit.verb_of("nice timeout -k 5 time release transaction run x"))

    def test_every_other_release_spelling_gets_no_decision(self):
        for command in self.NO_DECISION:
            with self.subTest(command):
                self.assertIsNone(permit.verb_of(command))
                self.assertFalse(mentions(command))
                verdict = self.judge(command)
                self.assertEqual((None, "", None, {}),
                                 (verdict.decision, verdict.reason, verdict.verb, dict(verdict.target)))
        self.assertEqual([], self.fake.calls)

    def test_the_permit_agrees_with_the_release_parser_on_abandon_and_dispose(self):
        spellings = [command for command, _ in self.run_forms()] + list(
            self.ABANDONS + self.DISPOSES + self.NO_DECISION) + [
            "release transaction run --repo-root r --disp no_recovery_path --reference x --confirm t"]
        checked = 0
        for command in spellings:
            parts = permit.words(command)
            if parts is None or parts[0] != "release":
                continue
            checked += 1
            with self.subTest(command):
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        parsed = release.build_parser().parse_args(parts[1:])
                except SystemExit:
                    parsed = None
                verb = permit.verb_of(command)
                self.assertEqual(parsed is not None and parsed.action == "abandon", verb == permit.ABANDON)
                self.assertEqual(
                    parsed is not None and parsed.action == "run" and parsed.dispose is not None,
                    verb == permit.DISPOSE)
                if parsed is None:
                    self.assertNotEqual(ALLOW, self.judge(command).decision)
        self.assertGreater(checked, 10)

    def test_an_unreadable_forge_is_refused(self):
        self.fake.pr_error = ForgeUnreadable("boom")
        self.assertRefused(self.merge, permit.FORGE_UNREADABLE.format(reason="boom"))

    EXHAUSTED = ("Post \"https://api.github.com/x\": dial tcp 140.82.112.5:443: "
                 "connect: can't assign requested address")
    PULL_JSON = ('{"head": {"ref": "issue-12-x", "sha": "' + SHA + '", "repo": {"full_name": "o/r"}}, '
                 '"base": {"ref": "main"}}')

    def gh_answering(self, *stderrs, took=0.0, clock=None):
        """The real readers over the `gh` subprocess boundary: each stderr in turn as a failed call, then
        the open pull request. Each call lasts `took` seconds on `clock` when one is given."""
        answers = [*stderrs]
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if clock is not None:
                clock[0] += took
            if answers:
                return mock.Mock(returncode=1, stdout="", stderr=answers.pop(0))
            return mock.Mock(returncode=0, stdout=self.PULL_JSON, stderr="")
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if clock is not None:
                clock[0] += seconds
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(permit.forge_api.subprocess, "run", side_effect=run))
        stack.enter_context(mock.patch("time.sleep", side_effect=sleep))
        if clock is not None:
            stack.enter_context(mock.patch("time.monotonic", side_effect=lambda: clock[0]))
        return stack, calls, sleeps

    def test_a_lookup_that_hits_port_exhaustion_and_then_answers_is_judged_normally(self):
        stack, calls, sleeps = self.gh_answering(self.EXHAUSTED, self.EXHAUSTED)
        with stack:
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual((ALLOW, {"pr": 7, "head": SHA}), (verdict.decision, dict(verdict.target)))
        self.assertEqual(3, len(calls))
        self.assertEqual(2, len(sleeps))
        self.assertTrue(all(0 < pause <= 5 for pause in sleeps), sleeps)

    def test_a_lookup_that_keeps_hitting_port_exhaustion_is_refused_in_plain_words(self):
        stack, calls, sleeps = self.gh_answering(*[self.EXHAUSTED] * 20)
        with stack:
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual(DENY, verdict.decision)
        self.assertEqual(permit.FORGE_UNREADABLE.format(reason=permit.PORTS_EXHAUSTED), verdict.reason)
        self.assertIn("local network ports", verdict.reason)
        self.assertIn("again", verdict.reason)
        self.assertNotIn("dial tcp", verdict.reason)
        self.assertGreater(len(calls), 1)
        self.assertLess(len(calls), 10)
        self.assertEqual(len(calls) - 1, len(sleeps))

    def test_the_retries_and_the_lookup_end_before_the_hooks_request_times_out(self):
        """Three exhausted calls of one second each and their pauses would put a fourth, successful call at
        7 s, past the hook's 10 s once the verdict is delivered: the lookup gives up in its budget instead."""
        clock = [100.0]
        stack, calls, sleeps = self.gh_answering(*[self.EXHAUSTED] * 3, took=1.0, clock=clock)
        with stack:
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual(DENY, verdict.decision)
        self.assertEqual(permit.FORGE_UNREADABLE.format(reason=permit.PORTS_EXHAUSTED), verdict.reason)
        self.assertLessEqual(clock[0] - 100.0, permit.LOOKUP_BUDGET)
        self.assertLess(permit.LOOKUP_BUDGET, sprint.TIMEOUT_SECONDS)

    def test_a_call_running_past_the_lookup_budget_is_cut_short(self):
        clock = [100.0]
        seen = []

        def run(argv, timeout, **kwargs):
            seen.append(timeout)
            raise subprocess.TimeoutExpired(argv, timeout)
        with mock.patch.object(permit.forge_api.subprocess, "run", side_effect=run), \
                mock.patch("time.monotonic", side_effect=lambda: clock[0]):
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual(DENY, verdict.decision)
        self.assertEqual([permit.LOOKUP_BUDGET], seen)

    def test_another_lookup_error_is_not_retried(self):
        stack, calls, sleeps = self.gh_answering("HTTP 502 secret detail")
        with stack:
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual(DENY, verdict.decision)
        self.assertEqual(permit.FORGE_UNREADABLE.format(reason="pull request 7 could not be read"),
                         verdict.reason)
        self.assertEqual((1, []), (len(calls), sleeps))

    def test_a_repository_named_like_the_socket_error_does_not_change_how_another_error_is_handled(self):
        stderr = ('Get "https://api.github.com/repos/o/EADDRNOTAVAIL/pulls/7": dial tcp 1.2.3.4:443: '
                  'connect: connection refused')
        stack, calls, sleeps = self.gh_answering(stderr)
        with stack:
            verdict = judge(self.merge, self.grant, permit.FORGE)
        self.assertEqual(permit.FORGE_UNREADABLE.format(reason="pull request 7 could not be read"),
                         verdict.reason)
        self.assertEqual((1, []), (len(calls), sleeps))

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
                        "(gh pr merge 7)"):
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

    def test_a_frozen_memo_replays_the_release_pull_request_read(self):
        fake = FakeForge()
        fake.release_pr = {"pr": 9, "branch": "develop", "head": SHA, "base": "main"}
        memo = memoized(fake.forge())
        self.assertEqual(memo.read_release_pr("o/r", "/r", "develop"),
                         memo.read_release_pr("o/r", "/r", "develop"))
        self.assertEqual(fake.release_pr, memo.frozen().read_release_pr("o/r", "/r", "develop"))
        self.assertEqual(1, fake.calls.count(("release", "o/r", "/r", "develop")))
        with self.assertRaises(ForgeUnreadable) as caught:
            memo.frozen().read_release_pr("o/r", "/r", "main")
        self.assertEqual("not read before", str(caught.exception))
        none = FakeForge()
        none.release_pr = None
        again = memoized(none.forge())
        self.assertIsNone(again.read_release_pr("o/r", "/r", "develop"))
        self.assertIsNone(again.frozen().read_release_pr("o/r", "/r", "develop"))


class ReaderTest(unittest.TestCase):
    PULL = {"head": {"ref": "issue-12-x", "sha": HEAD, "repo": {"full_name": "o/r"}},
            "base": {"ref": "main"}}
    RUN = {"event": "pull_request", "head_branch": "issue-12-x", "head_sha": HEAD,
           "head_repository": {"full_name": "o/r"}, "pull_requests": [{"number": 7}]}
    JOBS = [{"jobs": [{"name": "Nix Eval", "conclusion": "success"},
                      {"name": "Other", "conclusion": "failure"}]},
            {"jobs": [{"name": "deploy", "conclusion": "skipped"}, {"name": "Late", "conclusion": None}]}]
    JOBS_PATH = "repos/o/r/actions/runs/55/jobs?per_page=100"
    PROTECTION = {"checks": [{"context": "Nix Eval", "app_id": 15368}, {"context": "Budget", "app_id": None},
                             {"context": "Any", "app_id": -1}, {"context": "Bound", "app_id": 1}],
                  "contexts": ["Nix Eval", "Budget", "Any", "Bound", "Legacy"]}

    def reply(self, payloads):
        paged = {path: value for path, value in payloads.items() if path.endswith("per_page=100")}
        plain = {path: value for path, value in payloads.items() if path not in paged}
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(
            permit.forge_api, "api_get", side_effect=lambda path, *a: plain[path]))
        stack.enter_context(mock.patch.object(
            permit.forge_api, "api_pages", side_effect=lambda path: paged[path]))
        return stack

    def test_readers_raise_on_a_malformed_reply(self):
        with mock.patch.object(permit.forge_api, "api_get", return_value={}), \
                mock.patch.object(permit.forge_api, "api_pages", return_value=[{}]):
            for name, args in (("read_pr", ("o/r", 7)), ("read_run", ("o/r", 55)),
                               ("read_required", ("o/r", "main"))):
                with self.subTest(name), self.assertRaises(ForgeUnreadable):
                    getattr(permit, name)(*args)

    def test_readers_raise_when_the_forge_fails(self):
        error = permit.forge_api.ForgeError("gh_failed", "HTTP 502 secret detail")
        with mock.patch.object(permit.forge_api, "api_get", side_effect=error), \
                mock.patch.object(permit.forge_api, "api_pages", side_effect=error):
            for name, args in (("read_pr", ("o/r", 7)), ("read_run", ("o/r", 55)),
                               ("read_required", ("o/r", "main"))):
                with self.subTest(name), self.assertRaises(ForgeUnreadable) as caught:
                    getattr(permit, name)(*args)
                self.assertNotIn("secret", str(caught.exception))

    def test_gh_stderr_showing_address_exhaustion_marks_the_forge_error(self):
        for stderr, exhausted in (
                ("Get \"https://api.github.com/x\": dial tcp 1.2.3.4:443: connect: can't assign requested address",
                 True),
                ("dial tcp 1.2.3.4:443: connect: cannot assign requested address", True),
                ("connect EADDRNOTAVAIL 1.2.3.4:443", True),
                ("Get \"https://api.github.com/repos/o/EADDRNOTAVAIL/pulls/7\": dial tcp 1.2.3.4:443: "
                 "connect: connection refused", False),
                ("HTTP 404: repos/o/cannot assign requested address/pulls/7", False),
                ("dial tcp 1.2.3.4:443: connect: connection refused", False),
                ("HTTP 502 Bad Gateway", False)):
            done = mock.Mock(returncode=1, stdout="", stderr=stderr)
            with self.subTest(stderr), mock.patch.object(permit.forge_api.subprocess, "run",
                                                         return_value=done):
                with self.assertRaises(permit.forge_api.ForgeError) as caught:
                    permit.forge_api.run_gh(["api", "x"])
                self.assertEqual(exhausted, caught.exception.exhausted)

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
                          (self.RUN, [{"jobs": [{"name": 3}]}]),
                          (self.RUN, [{"jobs": [{"name": "x", "conclusion": 3}]}]),
                          (self.RUN, [{}]),
                          (self.RUN, [])):
            with self.subTest(run=run, jobs=jobs), self.reply({
                    "repos/o/r/actions/runs/55": run, self.JOBS_PATH: jobs}):
                with self.assertRaises(ForgeUnreadable):
                    permit.read_run("o/r", 55)

    WORKFLOW = """name: CI
on:
  pull_request:
  push:
jobs:
  suite:
    name: Agent Workflow Tests
    if: github.event_name != 'schedule'
    runs-on: ubuntu-24.04
  baseline:
    name: Suite Timing Baseline
    needs: suite
    if: github.event_name == 'push'
    runs-on: ubuntu-24.04
  timing:
    name: Suite Timing
    needs: suite
    if: ${{ !cancelled() && github.event_name == 'pull_request' }}
    runs-on: ubuntu-24.04
  cased:
    name: Cased Event
    needs: suite
    if: github.event_name == 'Pull_Request'
    runs-on: ubuntu-24.04
  casedpush:
    name: Cased Push
    needs: suite
    if: github.event_name == 'PUSH'
    runs-on: ubuntu-24.04
  either:
    name: Either Or
    if: github.event_name == 'push' || github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
  guarded:
    name: Guarded
    if: ${{ !(github.event_name == 'push' && github.ref == 'x') }}
    runs-on: ubuntu-24.04
  pushed:
    name: Pushed Only
    if: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
    runs-on: ubuntu-24.04
"""
    WORKFLOW_PATH = f"repos/o/r/contents/.github/workflows/ci.yaml?ref={HEAD}"
    LOG = ("2026-11-24T10:00:00.1234567Z suite-runner: end tests/test_a.py failed exit=1 3.0s\n"
           "2026-11-24T10:00:01.0000000Z suite-runner: 3.0s wall 3.0s cpu failed tests/test_a.py\n"
           "2026-11-24T10:00:02.0000000Z suite-runner: failed tests/test_a.py\n"
           "2026-11-24T10:00:02.0000001Z suite-runner: failed tests/test_b.py\n"
           "2026-11-24T10:00:03.0000000Z suite-runner: summary members=9 passed=7 failed=2 jobs=4\n"
           "suite-runner: failed tests/test_a.py\n")

    def run_payloads(self, jobs, path=".github/workflows/ci.yaml", workflow=None):
        """The forge's answers for run 55, its jobs and its workflow file."""
        text = self.WORKFLOW if workflow is None else workflow
        run = {**self.RUN} if path is None else {**self.RUN, "path": path}
        return {"repos/o/r/actions/runs/55": run, self.JOBS_PATH: [{"jobs": jobs}],
                self.WORKFLOW_PATH: {"encoding": "base64",
                                     "content": base64.encodebytes(text.encode()).decode()}}

    def forge_reads(self, payloads, log=None):
        """Patch the GitHub reads with `payloads` and every job log with `log`; returns the context."""
        stack = self.reply(payloads)
        stack.enter_context(mock.patch.object(
            permit.forge_api, "run_gh",
            side_effect=lambda argv, *a, **k: (0, self.LOG if log is None else log)))
        return stack

    def test_a_skipped_job_whose_own_condition_never_holds_on_a_pull_request_is_not_rerun(self):
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                {"id": 901, "name": "Suite Timing Baseline", "conclusion": "skipped"},
                {"id": 902, "name": "Suite Timing", "conclusion": "success"}]
        with self.forge_reads(self.run_payloads(jobs)):
            run = permit.read_run("o/r", 55)
        self.assertEqual(["Agent Workflow Tests"], run["rerun"])

    def test_a_skipped_job_that_could_hold_on_a_pull_request_or_is_not_provable_still_counts(self):
        for name in ("Either Or", "Guarded", "Suite Timing", "No Such Job"):
            with self.subTest(name):
                jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                        {"id": 901, "name": name, "conclusion": "skipped"}]
                with self.forge_reads(self.run_payloads(jobs)):
                    self.assertEqual(["Agent Workflow Tests", name], permit.read_run("o/r", 55)["rerun"])

    def test_the_event_name_in_a_condition_is_compared_without_regard_to_case(self):
        for condition, never in (("github.event_name == 'Pull_Request'", False),
                                 ("github.event_name == 'PULL_REQUEST'", False),
                                 ("github.event_name != 'Pull_Request'", True),
                                 ("github.event_name == 'PUSH'", True),
                                 ("GitHub.Event_Name == 'Push'", True)):
            with self.subTest(condition):
                self.assertIs(never, permit.never_on_pull_request(condition))
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                {"id": 901, "name": "Cased Event", "conclusion": "skipped"},
                {"id": 902, "name": "Cased Push", "conclusion": "skipped"}]
        with self.forge_reads(self.run_payloads(jobs)):
            self.assertEqual(["Agent Workflow Tests", "Cased Event"], permit.read_run("o/r", 55)["rerun"])

    def test_a_failed_job_never_counts_as_skipped_whatever_its_condition(self):
        jobs = [{"id": 900, "name": "Pushed Only", "conclusion": "failure"}]
        with self.forge_reads(self.run_payloads(jobs)):
            self.assertEqual(["Pushed Only"], permit.read_run("o/r", 55)["rerun"])

    def test_a_run_with_no_workflow_path_counts_every_skipped_job(self):
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                {"id": 901, "name": "Suite Timing Baseline", "conclusion": "skipped"}]
        with self.forge_reads(self.run_payloads(jobs, path=None)):
            self.assertEqual(["Agent Workflow Tests", "Suite Timing Baseline"],
                             permit.read_run("o/r", 55)["rerun"])

    def test_an_unreadable_workflow_makes_a_run_with_a_skipped_job_unreadable(self):
        jobs = [{"id": 901, "name": "Suite Timing Baseline", "conclusion": "skipped"}]
        for broken in ({"content": 3}, {}, {"encoding": "base64", "content": "%%%"}):
            with self.subTest(broken):
                payloads = {**self.run_payloads(jobs), self.WORKFLOW_PATH: broken}
                with self.forge_reads(payloads), self.assertRaises(ForgeUnreadable):
                    permit.read_run("o/r", 55)

    def test_the_failing_suite_members_are_read_from_the_failed_jobs_log_once_each(self):
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                {"id": 903, "name": "Other", "conclusion": "failure"}]
        with self.forge_reads(self.run_payloads(jobs)):
            run = permit.read_run("o/r", 55)
            asked = [call.args[0] for call in permit.forge_api.run_gh.call_args_list]
        self.assertEqual(["tests/test_a.py", "tests/test_b.py"], run["members"])
        self.assertEqual([["api", "repos/o/r/actions/jobs/900/logs"],
                          ["api", "repos/o/r/actions/jobs/903/logs"]], asked)

    def test_a_log_that_cannot_be_read_leaves_the_members_empty(self):
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"}]
        with self.forge_reads(self.run_payloads(jobs)) as stack:
            stack.enter_context(mock.patch.object(
                permit.forge_api, "run_gh",
                side_effect=permit.forge_api.ForgeError("gh_failed", "HTTP 410")))
            run = permit.read_run("o/r", 55)
        self.assertEqual((["Agent Workflow Tests"], []), (run["rerun"], run["members"]))

    def test_a_manager_reruns_the_required_failure_of_its_pull_request_twice_and_not_a_third_time(self):
        """The demo end to end (ADR-console-106): the push-only timing job does not block, the members are
        recorded, and the third rerun of one head is refused."""
        jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                {"id": 901, "name": "Suite Timing Baseline", "conclusion": "skipped"}]
        payloads = {**self.run_payloads(jobs), "repos/o/r/pulls/7": self.PULL,
                    "repos/o/r/branches/main/protection/required_status_checks": {
                        "checks": [{"context": "Agent Workflow Tests", "app_id": 15368}], "contexts": []}}
        grant = Grant(slug="o/r", root="/r", strategy="merge", delete_branch=True,
                      branch_pattern="issue-<num>-<slug>", issues=frozenset({12}), others=frozenset())
        forge = Forge(permit.read_pr, permit.read_run, permit.read_required, permit.read_release_pr)
        command = "gh run rerun 55 --failed --repo o/r"
        with self.forge_reads(payloads):
            earlier = (permit.Rerun(53, ("tests/test_a.py",)), permit.Rerun(54, ("tests/test_b.py",)))
            for before in (0, 1):
                verdict = judge(command, dataclasses.replace(grant, reruns={HEAD: earlier[:before]}), forge)
                self.assertEqual((ALLOW, {"run": 55, "pr": 7, "head": HEAD, "count": before + 1,
                                          "members": ["tests/test_a.py", "tests/test_b.py"]}),
                                 (verdict.decision, dict(verdict.target)))
            third = judge(command, dataclasses.replace(grant, reruns={HEAD: earlier}), forge)
            self.assertEqual((DENY, permit.RERUN_LIMIT.format(
                pr=7, head=HEAD, reruns="run 53 (failing: tests/test_a.py) and run 54 (failing: tests/test_b.py)")),
                             (third.decision, third.reason))
        for name, change in (("event", {"event": "push"}), ):
            deploy_payloads = {**payloads, "repos/o/r/actions/runs/55": {
                **payloads["repos/o/r/actions/runs/55"], **change}}
            with self.forge_reads(deploy_payloads):
                deploy = judge(command, grant, forge)
            self.assertEqual((DENY, permit.DEPLOY_RERUN.format(run=55, event="push")),
                             (deploy.decision, deploy.reason))
        cased_on_pull_request = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                                 {"id": 901, "name": "Cased Event", "conclusion": "skipped"}]
        with self.forge_reads({**payloads, **self.run_payloads(cased_on_pull_request)}):
            cased = judge(command, grant, forge)
        self.assertEqual((DENY, permit.NOT_CHECK_RUN.format(run=55)), (cased.decision, cased.reason))
        skipped_on_pull_request = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                           {"id": 901, "name": "Suite Timing", "conclusion": "skipped"}]
        with self.forge_reads({**payloads, **self.run_payloads(skipped_on_pull_request)}):
            refused = judge(command, grant, forge)
        self.assertEqual((DENY, permit.NOT_CHECK_RUN.format(run=55)), (refused.decision, refused.reason))

    def test_the_release_pull_request_is_the_one_open_pull_request_from_integration_into_default(self):
        contract = {"bindings": {"vcs": {"integration_branch": "develop", "default_branch": "main"}},
                    "capabilities": {"release": {"state": "available"}}}
        path = "repos/o/r/pulls?state=open&base=main&head=o:develop&per_page=2"
        entry = {"number": 9, "head": {"ref": "develop", "sha": HEAD, "repo": {"full_name": "o/r"}},
                 "base": {"ref": "main"}}
        with mock.patch.object(permit.resolve_project, "resolve", return_value=contract):
            with self.subTest("one"), self.reply({path: [entry]}):
                self.assertEqual({"pr": 9, "branch": "develop", "head": HEAD, "base": "main"},
                                 permit.read_release_pr("o/r", "/r", "develop"))
            with self.subTest("none"), self.reply({path: []}):
                self.assertIsNone(permit.read_release_pr("o/r", "/r", "develop"))
            broken = ([entry, entry], {}, [{**entry, "number": "9"}],
                      [{**entry, "number": 0}], [{**entry, "number": -3}],
                      [{**entry, "head": {**entry["head"], "sha": "x"}}],
                      [{**entry, "head": {**entry["head"], "ref": "feature"}}],
                      [{**entry, "head": {**entry["head"], "repo": {"full_name": "fork/r"}}}],
                      [{**entry, "base": {"ref": "staging"}}])
            for reply in broken:
                with self.subTest(reply), self.reply({path: reply}):
                    with self.assertRaises(ForgeUnreadable):
                        permit.read_release_pr("o/r", "/r", "develop")
            error = permit.forge_api.ForgeError("gh_failed", "HTTP 502 secret detail")
            with self.subTest("forge error"), mock.patch.object(
                    permit.forge_api, "api_get", side_effect=error):
                with self.assertRaises(ForgeUnreadable) as caught:
                    permit.read_release_pr("o/r", "/r", "develop")
                self.assertNotIn("secret", str(caught.exception))
            with self.subTest("another branch"), mock.patch.object(permit.forge_api, "api_get") as get:
                self.assertIsNone(permit.read_release_pr("o/r", "/r", "feature"))
                get.assert_not_called()
        same = {"bindings": {"vcs": {"integration_branch": "main", "default_branch": "main"}},
                "capabilities": {"release": {"state": "available"}}}
        tip = "repos/o/r/git/ref/heads/main"
        with mock.patch.object(permit.resolve_project, "resolve", return_value=same):
            with self.subTest("equal branches: the candidate is the tip"), self.reply({tip: {"object": {"sha": HEAD}}}):
                self.assertEqual({"pr": None, "branch": "main", "head": HEAD, "base": "main"},
                                 permit.read_release_pr("o/r", "/r", "main"))
            for reply in ({}, {"object": {}}, {"object": {"sha": "x"}}, {"object": {"sha": 7}}, []):
                with self.subTest(reply), self.reply({tip: reply}):
                    with self.assertRaises(ForgeUnreadable):
                        permit.read_release_pr("o/r", "/r", "main")
            with self.subTest("equal branches: another branch"), mock.patch.object(
                    permit.forge_api, "api_get") as get:
                self.assertIsNone(permit.read_release_pr("o/r", "/r", "feature"))
                get.assert_not_called()
        for state in ("unsupported", None, "bogus"):
            for branches in (("develop", "main"), ("main", "main")):
                undeclared = {"bindings": {"vcs": {"integration_branch": branches[0], "default_branch": "main"}},
                              "capabilities": {"release": {"state": state}}}
                with self.subTest(("no release declared", state, branches)), mock.patch.object(
                        permit.resolve_project, "resolve", return_value=undeclared), \
                        mock.patch.object(permit.forge_api, "api_get") as get:
                    self.assertIsNone(permit.read_release_pr("o/r", "/r", branches[0]))
                    get.assert_not_called()
        with self.subTest("no contract"), mock.patch.object(
                permit.resolve_project, "resolve", side_effect=ValueError("x")), \
                mock.patch.object(permit.forge_api, "api_get") as get:
            self.assertIsNone(permit.read_release_pr("o/r", "/r", "develop"))
            get.assert_not_called()

    def test_a_run_is_pending_while_a_job_has_no_conclusion(self):
        for jobs, pending in (([{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"}], False),
                              ([{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                                {"id": 901, "name": "Nix Eval", "conclusion": None}], True),
                              ([{"id": 900, "name": "Nix Eval", "conclusion": None}], True)):
            with self.subTest(jobs), self.forge_reads(self.run_payloads(jobs)):
                self.assertIs(pending, permit.read_run("o/r", 55)["pending"])

    def test_a_skipped_job_whose_condition_never_holds_for_the_runs_own_event_is_not_rerun(self):
        for skipped, expected in (("Suite Timing", ["Agent Workflow Tests"]),
                                  ("Suite Timing Baseline", ["Agent Workflow Tests", "Suite Timing Baseline"])):
            with self.subTest(skipped):
                jobs = [{"id": 900, "name": "Agent Workflow Tests", "conclusion": "failure"},
                        {"id": 901, "name": skipped, "conclusion": "skipped"}]
                payloads = self.run_payloads(jobs)
                payloads["repos/o/r/actions/runs/55"] = {**payloads["repos/o/r/actions/runs/55"],
                                                          "event": "push"}
                with self.forge_reads(payloads):
                    self.assertEqual(expected, permit.read_run("o/r", 55)["rerun"])
        self.assertIs(True, permit.never_on("github.event_name == 'pull_request'", "push"))
        self.assertIs(True, permit.never_on("github.event_name != 'push'", "push"))
        self.assertIs(False, permit.never_on("github.event_name == 'push'", "push"))

    def test_readers_return_the_documented_shapes(self):
        payloads = {
            "repos/o/r/pulls/7": self.PULL,
            "repos/o/r/actions/runs/55": self.RUN,
            self.JOBS_PATH: self.JOBS,
            "repos/o/r/branches/main/protection/required_status_checks": self.PROTECTION,
        }
        with self.reply(payloads):
            self.assertEqual({"branch": "issue-12-x", "repo": "o/r", "head": HEAD, "base": "main"},
                             permit.read_pr("o/r", 7))
            self.assertEqual({"event": "pull_request", "branch": "issue-12-x", "repo": "o/r",
                              "head": HEAD, "prs": [7], "rerun": ["Other", "deploy", "Late"],
                              "members": [], "pending": True},
                             permit.read_run("o/r", 55))
            self.assertEqual(frozenset({"Nix Eval", "Budget", "Any", "Legacy"}),
                             permit.read_required("o/r", "main"))

    def test_a_protection_with_a_malformed_member_is_unreadable(self):
        path = "repos/o/r/branches/main/protection/required_status_checks"
        for broken in ({"checks": [{"app_id": 1}], "contexts": []},
                       {"checks": [{"context": "x", "app_id": "1"}], "contexts": []},
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

    def test_the_release_branches_are_the_contracts_or_none(self):
        def contract(integration, state="available"):
            return {"bindings": {"vcs": {"integration_branch": integration, "default_branch": "main"}},
                    "capabilities": {"release": {"state": state}}}
        for state, expected in (("blocked", ("develop", "main")), ("unsupported", (None, None)),
                                (None, (None, None))):
            with mock.patch.object(permit.resolve_project, "resolve", return_value=contract("develop", state)):
                self.assertEqual(expected, permit.release_branches("/r"), state)
        bare = {"bindings": {"vcs": {"integration_branch": "develop", "default_branch": "main"}}}
        with mock.patch.object(permit.resolve_project, "resolve", return_value=bare):
            self.assertEqual((None, None), permit.release_branches("/r"))
        with mock.patch.object(permit.resolve_project, "resolve", return_value=contract("develop")) as resolve:
            self.assertEqual(("develop", "main"), permit.release_branches("/r"))
            resolve.reset_mock()
            self.assertEqual((None, None), permit.release_branches(None))
            resolve.assert_not_called()
        with mock.patch.object(permit.resolve_project, "resolve", side_effect=ValueError("x")):
            self.assertEqual((None, None), permit.release_branches("/r"))
        for integration in (3, ""):
            with mock.patch.object(permit.resolve_project, "resolve", return_value=contract(integration)):
                self.assertEqual((None, None), permit.release_branches("/r"), integration)


ANSWERED = "2026-11-23T10:00:00.000000+00:00"


class ActionJudgeTest(unittest.TestCase):
    """`permit.judge_action`: an owner-only card's approved command, once, within an hour."""

    CARD = sprints.Question(
        41, 0, "2026-11-23T10:00:00.000000+00:00", False, "May it run?", "the check",
        ("Run it once", "Do not run it"), "Run it once", answer="Run it once", chosen="Run it once",
        answered_at=ANSWERED, owner_only=True, action=sprints.QuestionAction("curl x", "Run it once"))
    DIGEST = permit.command_digest("curl x")

    def now(self, seconds):
        return datetime.fromisoformat(ANSWERED) + timedelta(seconds=seconds)

    def judged(self, *cards, digest=None, seconds=1):
        verdict = permit.judge_action(digest or self.DIGEST, cards, self.now(seconds))
        return verdict.decision, verdict.reason, verdict.verb, dict(verdict.target)

    def test_only_the_owners_own_answer_on_an_owner_only_card_approves(self):
        for changes in ({"answered_by": "colleague-login"}, {"owner_only": False}):
            with self.subTest(changes=changes):
                card = dataclasses.replace(self.CARD, **changes)
                self.assertEqual(self.judged(card)[:2], ("deny", permit.ACTION_NOT_OWNERS))
        self.assertEqual(self.judged(self.CARD),
                         ("allow", "", "action", {"round": 41, "index": 0}))

    def test_the_expiry_boundary_is_sixty_minutes(self):
        self.assertEqual(self.judged(self.CARD, seconds=3599)[0], "allow")
        self.assertEqual(self.judged(self.CARD, seconds=3600)[:2], ("deny", permit.ACTION_EXPIRED))
        for stamp in ("not a time", "2026-11-23T10:00:00"):
            with self.subTest(stamp=stamp):
                card = dataclasses.replace(self.CARD, answered_at=stamp)
                self.assertEqual(self.judged(card)[:2], ("deny", permit.ACTION_EXPIRED))

    def test_a_withdrawn_card_names_nothing_and_a_live_card_wins(self):
        withdrawn = dataclasses.replace(self.CARD, withdrawn_at=ANSWERED)
        self.assertEqual(self.judged(withdrawn), (None, "", None, {}))
        self.assertEqual(self.judged(self.CARD, digest=permit.command_digest("curl y")),
                         (None, "", None, {}))
        used = dataclasses.replace(self.CARD, action_used_at=ANSWERED)
        live = dataclasses.replace(self.CARD, round_id=42)
        self.assertEqual(self.judged(used, live),
                         ("allow", "", "action", {"round": 42, "index": 0}))
        self.assertEqual(self.judged(used, dataclasses.replace(used, round_id=42))[:2],
                         ("deny", permit.ACTION_USED))

    def test_the_proof_binds_each_member_and_is_its_own_domain(self):
        self.assertEqual(permit.command_digest("curl x"), hashlib.sha256(b"curl x").hexdigest())
        base = ("s", "0" * 16, "b" * 32, "d" * 64, "allow", "")
        wanted = permit.action_reply_mac(*base)
        for index, changed in ((1, "1" * 16), (2, "c" * 32), (3, "e" * 64), (4, "deny"), (4, None),
                               (5, "r")):
            with self.subTest(member=index, changed=changed):
                other = list(base)
                other[index] = changed
                self.assertNotEqual(permit.action_reply_mac(*other), wanted)
        self.assertNotEqual(permit.action_request_auth("s", b"x"), prompt_card.request_auth("s", b"x"))
        self.assertEqual(permit.signed_bytes({"b": 1, "a": 2, "auth": "z"}), b'{"a":2,"b":1}')


if __name__ == "__main__":
    unittest.main()
