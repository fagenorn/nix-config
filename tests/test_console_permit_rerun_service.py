"""A manager's reruns of one head are counted from the event log and a third is refused (ADR-console-106).

Run: just agent-workflow-tests
"""
import unittest

from agent_tools.console import permit

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_manager_service import MERGE, NOW, ROOT, SLUG, PermitCase
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
              "failed": ["Nix Eval"]}
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

    RERUN = f"gh run rerun 55 --failed --repo {SLUG}"

    def landed_row(self, sid, call="t-1"):
        return {"sprint_id": sid, "session_id": "s-1", "tool_use_id": call, "repo": SLUG, "verb": "rerun",
                "target": {"run": 55}}

    def test_a_rerun_the_manager_ran_after_its_allow_is_recorded_as_landed(self):
        svc, sid = self.boot()
        verdict = self.judge(svc, sid, self.RERUN, call="t-1")
        self.assertEqual((verdict.decision, verdict.verb), ("allow", "rerun"))
        self.assertTrue(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", self.RERUN))
        self.assertEqual(self.rows("permit.landed"), [self.landed_row(sid)])
        with self.subTest("prefixed"):
            svc, sid = self.boot()
            prefixed = "env -u GITHUB_TOKEN -u GH_TOKEN " + self.RERUN
            self.assertEqual(self.judge(svc, sid, prefixed, call="t-1").decision, "allow")
            self.assertTrue(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", prefixed))
            self.assertEqual(self.rows("permit.landed")[-1], self.landed_row(sid))

    def test_a_rerun_lands_only_for_its_own_allowed_call_of_the_same_run_within_thirty_minutes(self):
        now = [NOW]
        svc, sid = self.boot(clock=lambda: now[0])
        secret = self.secret(sid)
        with self.subTest("before the allow"):
            self.assertFalse(svc.permit_landed(sid, secret, "s-1", "t-1", self.RERUN))
        self.assertEqual(self.judge(svc, sid, self.RERUN, call="t-1").decision, "allow")
        for name, session, call, command in (
                ("other session", "s-2", "t-1", self.RERUN),
                ("other call", "s-1", "t-9", self.RERUN),
                ("other run", "s-1", "t-1", f"gh run rerun 56 --failed --repo {SLUG}"),
                ("extra flag", "s-1", "t-1", self.RERUN + " --job 9"),
                ("other repository", "s-1", "t-1", "gh run rerun 55 --failed --repo o/other"),
                ("merge text on the rerun's call", "s-1", "t-1", MERGE)):
            with self.subTest(name):
                self.assertFalse(svc.permit_landed(sid, secret, session, call, command))
        self.assertEqual(self.rows("permit.landed"), [])
        self.assertEqual(self.judge(svc, sid, self.RERUN, call="t-2").decision, "allow")
        with self.subTest("denied third rerun"):
            third = self.judge(svc, sid, self.RERUN, call="t-3")
            self.assertEqual(third.decision, "deny")
            self.assertFalse(svc.permit_landed(sid, secret, "s-1", "t-3", self.RERUN))
        with self.subTest("thirty minutes"):
            now[0] = NOW + 30 * 60
            self.assertTrue(svc.permit_landed(sid, secret, "s-1", "t-1", self.RERUN))
            now[0] = NOW + 30 * 60 + 1
            self.assertFalse(svc.permit_landed(sid, secret, "s-1", "t-2", self.RERUN))
        self.assertEqual(self.rows("permit.landed"), [self.landed_row(sid)])

    def test_the_same_landed_notification_delivered_twice_records_one_row(self):
        svc, sid = self.boot()
        self.assertEqual(self.judge(svc, sid, self.RERUN, call="t-1").decision, "allow")
        self.assertTrue(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", self.RERUN))
        self.assertFalse(svc.permit_landed(sid, self.secret(sid), "s-1", "t-1", self.RERUN))
        self.assertEqual(self.rows("permit.landed"), [self.landed_row(sid)])


if __name__ == "__main__":
    unittest.main()
