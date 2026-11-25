"""A manager's reruns of one head are counted from the event log and a third is refused (ADR-console-106).

Run: just agent-workflow-tests
"""
import unittest

from agent_tools.console import permit

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_manager_service import ROOT, SLUG, PermitCase
from .test_console_permit import HEAD, SHA

TIER = "fast"  # a local service on a free port and the standard library


class PermitRerunServiceTest(PermitCase):
    def test_a_manager_reruns_one_head_twice_each_recorded_and_a_third_is_refused(self):
        svc, sid = self.boot()
        self.fake.run = {**self.fake.run, "members": ["tests/test_a.py"]}
        rerun = f"gh run rerun 55 --failed --repo {SLUG}"
        for call, count in (("t-1", 1), ("t-2", 2)):
            verdict = self.judge(svc, sid, rerun, call=call)
            self.assertEqual((verdict.decision, verdict.verb), ("allow", "rerun"))
            self.assertEqual({"run": 55, "pr": 7, "head": SHA, "count": count,
                              "members": ["tests/test_a.py"]},
                             self.rows("permit.judged")[-1]["target"])
        third = self.judge(svc, sid, rerun, call="t-3")
        self.assertEqual((third.decision, third.reason), ("deny", permit.RERUN_LIMIT.format(
            pr=7, head=SHA, reruns="run 55 (failing: tests/test_a.py) and run 55 (failing: tests/test_a.py)")))
        self.assertEqual([("allow", "allow", "deny")], [tuple(
            row["decision"] for row in self.rows("permit.judged"))])
        self.fake.pr = {**self.fake.pr, "head": HEAD}
        self.fake.run = {**self.fake.run, "head": HEAD}
        fresh = self.judge(svc, sid, rerun, call="t-4")
        self.assertEqual((fresh.decision, fresh.target["count"]), ("allow", 1))

    PR_RUN = {"event": "pull_request", "branch": "develop", "repo": SLUG, "head": SHA, "prs": [9],
              "rerun": ["Nix Eval"]}
    PUSH_RUN = {**PR_RUN, "event": "push", "prs": []}

    @staticmethod
    def rerun_of(number, repo=SLUG):
        return f"gh run rerun {number} --failed --repo {repo}"

    def release_boot(self):
        svc, sid = self.boot()
        svc._slug_of = lambda root: SLUG if root == ROOT else "o/other"
        self.fake.release_pr = {"pr": 9, "branch": "develop", "head": SHA, "base": "main"}
        return svc, sid

    def test_a_projects_manager_reruns_its_release_runs_and_another_projects_manager_is_refused(self):
        svc, sid = self.release_boot()
        self.fake.run = self.PR_RUN
        first = self.judge(svc, sid, self.rerun_of(55), call="t-1")
        self.assertEqual((first.decision, first.verb), ("allow", "rerun"))
        self.assertEqual({"run": 55, "pr": 9, "head": SHA, "count": 1, "members": [],
                          "release": "pull_request"}, self.rows("permit.judged")[-1]["target"])
        self.fake.run = self.PUSH_RUN
        second = self.judge(svc, sid, self.rerun_of(56), call="t-2")
        self.assertEqual((second.decision, second.verb), ("allow", "rerun"))
        self.assertEqual({"run": 56, "pr": 9, "head": SHA, "count": 2, "members": [], "release": "push"},
                         self.rows("permit.judged")[-1]["target"])
        other = self.sprint(svc, "make the exporter resumable", project="owner/p00")
        self.seen(svc, other, "s-2", project="owner/p00")
        for call, run, command, reason in (
                ("o-1", self.PR_RUN, self.rerun_of(55), permit.OTHER_REPO),
                ("o-2", self.PR_RUN, self.rerun_of(55, "o/other"), permit.NOT_OWN_RUN.format(run=55)),
                ("o-3", self.PUSH_RUN, self.rerun_of(56), permit.OTHER_REPO),
                ("o-4", self.PUSH_RUN, self.rerun_of(56, "o/other"),
                 permit.DEPLOY_RERUN.format(run=56, event="push"))):
            with self.subTest(call):
                self.fake.run = run
                verdict = svc.permit(other, self.secret(other), "s-2", call, command)
                self.assertEqual((verdict.decision, verdict.reason), ("deny", reason))
        self.fake.run = self.PUSH_RUN
        third = self.judge(svc, sid, self.rerun_of(56), call="t-3")
        self.assertEqual((third.decision, third.reason), ("deny", permit.RERUN_LIMIT.format(
            pr=9, head=SHA, reruns="run 55 (failing: no members reported) and "
                                   "run 56 (failing: no members reported)")))
        self.assertEqual(["allow", "allow", "deny", "deny", "deny", "deny", "deny"],
                         [row["decision"] for row in self.rows("permit.judged")])

    def test_release_rerun_counts_survive_a_restart(self):
        svc, sid = self.release_boot()
        self.fake.run = self.PR_RUN
        self.judge(svc, sid, self.rerun_of(55), call="t-1")
        self.fake.run = self.PUSH_RUN
        self.judge(svc, sid, self.rerun_of(56), call="t-2")
        again = self.start(
            launcher=support.Launches(), session_poll_seconds=3600, slug_of=lambda root: SLUG,
            merge_binding_of=lambda root: ("merge", True),
            branch_pattern_of=lambda root: "issue-<num>-<slug>", permit_forge=self.fake.forge())
        verdict = again.permit(sid, self.secret(sid), "s-1", "t-3", self.rerun_of(56))
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.RERUN_LIMIT.format(
            pr=9, head=SHA, reruns="run 55 (failing: no members reported) and "
                                   "run 56 (failing: no members reported)")))

    def test_the_count_of_reruns_of_a_head_survives_a_restart(self):
        svc, sid = self.boot()
        rerun = f"gh run rerun 55 --failed --repo {SLUG}"
        self.judge(svc, sid, rerun, call="t-1")
        self.judge(svc, sid, rerun, call="t-2")
        again = self.start(
            launcher=support.Launches(), session_poll_seconds=3600, slug_of=lambda root: SLUG,
            merge_binding_of=lambda root: ("merge", True),
            branch_pattern_of=lambda root: "issue-<num>-<slug>", permit_forge=self.fake.forge())
        verdict = again.permit(sid, self.secret(sid), "s-1", "t-3", rerun)
        self.assertEqual((verdict.decision, verdict.reason), ("deny", permit.RERUN_LIMIT.format(
            pr=7, head=SHA, reruns="run 55 (failing: no members reported) and run 55 (failing: no members reported)")))


if __name__ == "__main__":
    unittest.main()
