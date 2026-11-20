"""A manager posts, lists and withdraws notices for its project (#1117).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json

from agent_tools.console import sprints, service

from . import console_test_support as support
from .test_console_messages import GOAL_TEXT, PARTS
from .test_console_reports import CLOSING
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

BRIEF = "/api/brief"
APPROVE = "/api/approve"
NOTICE = "/api/notice"
NOTICES = "/api/notices"
WITHDRAW_NOTICE = "/api/withdraw-notice"
OWNER_NOTICE = "/api/owner-notice"
OWNER_WITHDRAW = "/api/owner-notice-withdraw"
JSON = {"Content-Type": "application/json"}
CLAIM = {"kind": "claim", "text": " the page fold ", "what": "python/agent_tools/console/page.html",
         "until": "the board fold lands", "issue": 7}
HEADS_UP = {"kind": "heads-up", "text": "sprint ask gains a dry run"}
HAND_OFF = {"kind": "hand-off", "text": "the importer needs a retry", "to": "owner"}
OTHER_GOAL = "make the exporter resumable"


class NoticeRouteTest(Case):
    def open(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        return self.start(**kwargs)

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def approved(self, svc, project_id):
        sid = svc.state_goal(project_id, GOAL_TEXT)
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "brief": PARTS}).encode()
        self.assertEqual(support.post_page(svc.address, BRIEF, JSON, body)[0], 200)
        body = json.dumps({"project_id": project_id, "sprint_id": sid, "version": 1}).encode()
        self.assertEqual(
            support.post_page(svc.address, APPROVE, self.own(svc, **JSON), body)[0], 204)
        return sid

    def post(self, svc, path, body, **headers):
        return support.post_page(svc.address, path, {**JSON, **headers},
                                 json.dumps(body).encode())

    def notice(self, svc, sid, notice, secret=None, **headers):
        return self.post(svc, NOTICE, {"sprint_id": sid, "secret": secret or self.secret(sid),
                                       "notice": notice}, **headers)

    def listed(self, svc, sid, secret=None):
        status, _, body = self.post(svc, NOTICES, {"sprint_id": sid,
                                                   "secret": secret or self.secret(sid)})
        self.assertEqual(status, 200, body)
        return json.loads(body)["notices"]

    def withdraw(self, svc, sid, notice_id, secret=None, **headers):
        return self.post(svc, WITHDRAW_NOTICE, {"sprint_id": sid,
                                                "secret": secret or self.secret(sid),
                                                "notice": notice_id}, **headers)

    def posted(self, svc, sid, notice):
        status, _, body = self.notice(svc, sid, notice)
        self.assertEqual(status, 200, body)
        return json.loads(body)["notice"]

    def rows(self, kind):
        return [row for row in support.log_rows(self.store) if row[2] == kind]

    def test_a_notice_is_posted_and_listed_by_another_sprint_of_the_project(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        b = svc.state_goal("owner/p01", OTHER_GOAL)
        before = len(support.log_rows(self.store))
        status, headers, body = self.notice(svc, a, CLAIM)
        rows = self.rows("notice.posted")
        self.assertEqual(len(support.log_rows(self.store)), before + 1)
        self.assertEqual(len(rows), 1)
        seq, at, _, project, payload = rows[0]
        self.assertEqual((status, headers["Content-Type"], body),
                         (200, "application/json", b'{"notice":%d}' % seq))
        self.assertEqual(project, "owner/p01")
        self.assertEqual(json.loads(payload), {
            "sprint_id": a, "goal": GOAL_TEXT, "notice": {**CLAIM, "text": "the page fold"}})
        self.assertEqual(self.assert_unchanged(svc, lambda: self.listed(svc, b)), [{
            "at": at, "id": seq, "kind": "claim", "sprint_id": a, "text": "the page fold",
            "title": sprints.sprint_title(svc._sprints[a]), "until": CLAIM["until"],
            "what": CLAIM["what"], "issue": 7, "live_fault": False}])

    def test_a_folder_wide_claim_is_refused_and_a_file_claim_is_listed(self):
        checkout = self.store.parent / "checkout"
        (checkout / "src").mkdir(parents=True)
        (checkout / "src" / "main.py").write_text("")
        support.write_registry(self.registry, [{"project_id": "owner/p01", "root": str(checkout)}])
        svc = self.start()
        a = self.approved(svc, "owner/p01")
        before = len(support.log_rows(self.store))
        status, _, body = self.notice(svc, a, {**CLAIM, "what": "src"})
        self.assertEqual(
            (status, body),
            (409, b"a claim's what names files or a narrow path, never a whole folder tree\n"))
        self.assertEqual(len(support.log_rows(self.store)), before)
        self.posted(svc, a, {**CLAIM, "what": "src/main.py"})
        listed = self.listed(svc, a)
        self.assertEqual([(e["what"], e["issue"], e["live_fault"]) for e in listed],
                         [("src/main.py", 7, False)])

    def test_a_sprint_of_another_project_never_sees_the_notice(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        c = svc.state_goal("owner/p00", GOAL_TEXT)
        self.posted(svc, a, CLAIM)
        self.assertEqual(self.listed(svc, c), [])

    def test_a_notice_over_a_bound_is_refused_with_the_member_and_appends_nothing(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        c = svc.state_goal("owner/p00", GOAL_TEXT)
        d = self.approved(svc, "owner/p01")
        svc.send_closing(d, self.secret(d), CLOSING)
        for name, notice, reason in (
                ("text", {**HEADS_UP, "text": "x" * 281},
                 "the notice's text is over 280 characters"),
                ("what", {**CLAIM, "what": "w" * 201},
                 "the notice's what is over 200 characters"),
                ("until", {**CLAIM, "until": "u" * 141},
                 "the notice's until is over 140 characters"),
                ("kind", {"kind": "fyi", "text": "t"}, sprints.NOTICE_KIND),
                ("to another project", {**HAND_OFF, "to": c}, sprints.NOTICE_TO_REFUSED),
                ("to a closed sprint", {**HAND_OFF, "to": d}, sprints.NOTICE_TO_REFUSED),
                ("to itself", {**HAND_OFF, "to": a}, sprints.NOTICE_TO_SELF)):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.notice(svc, a, notice))
                self.assertEqual((got[0], got[2]), (409, reason.encode() + b"\n"))
        for _ in range(5):
            self.posted(svc, a, HEADS_UP)
        with self.subTest("sixth"):
            got = self.assert_unchanged(svc, lambda: self.notice(svc, a, HEADS_UP))
            self.assertEqual((got[0], got[2]), (409, sprints.NOTICE_LIMIT.encode() + b"\n"))

    def test_withdraw_notice_ends_its_own_and_refuses_anothers_or_an_ended_one(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        b = svc.state_goal("owner/p01", OTHER_GOAL)
        n1 = self.posted(svc, a, CLAIM)
        n2 = self.posted(svc, b, HEADS_UP)
        status, _, body = self.withdraw(svc, a, n1)
        self.assertEqual((status, body), (200, b'{"notice":%d}' % n1))
        rows = self.rows("notice.withdrawn")
        self.assertEqual([json.loads(row[4]) for row in rows],
                         [{"sprint_id": a, "goal": GOAL_TEXT, "notice": n1}])
        self.assertEqual([entry["id"] for entry in self.listed(svc, b)], [n2])
        for name, sid, notice_id, reason in (
                ("ended", a, n1, "this notice has ended"),
                ("another's", a, n2, "this notice belongs to another sprint"),
                ("unknown", a, 999, "this notice is not known")):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.withdraw(svc, sid, notice_id))
                self.assertEqual((got[0], got[2]), (409, reason.encode() + b"\n"))

    def test_a_wrong_secret_or_a_sprint_not_open_is_refused_like_every_manager_write(self):
        svc = self.open()
        s = svc.state_goal("owner/p01", GOAL_TEXT)
        posted = self.posted(svc, s, CLAIM)
        d = self.approved(svc, "owner/p01")
        svc.send_closing(d, self.secret(d), CLOSING)
        g = svc.state_goal("owner/p01", GOAL_TEXT)
        gone_secret = self.secret(g)
        svc.withdraw_goal("owner/p01", g)
        stopping = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.stop_sprint("owner/p01", stopping)
        routes = (
            (NOTICE, lambda sid, secret, **h: self.notice(svc, sid, HEADS_UP, secret, **h),
             "bad notice", {"sprint_id": s, "notice": HEADS_UP}),
            (NOTICES, lambda sid, secret, **h: self.post(
                svc, NOTICES, {"sprint_id": sid, "secret": secret}, **h),
             "bad notices", {"sprint_id": s}),
            (WITHDRAW_NOTICE, lambda sid, secret, **h: self.withdraw(svc, sid, posted, secret, **h),
             "bad withdraw notice", {"sprint_id": s, "notice": posted}))
        for path, send, bad, without_secret in routes:
            with self.subTest(path, case="wrong secret"):
                got = self.assert_unchanged(svc, lambda: send(s, self.secret(s) + "x"))
                self.assertEqual((got[0], got[2]), (403, b"secret refused\n"))
            with self.subTest(path, case="dropped sprint"):
                got = self.assert_unchanged(svc, lambda: send(g, gone_secret))
                self.assertEqual((got[0], got[2]), (409, sprints.NOT_OPEN.encode() + b"\n"))
            with self.subTest(path, case="origin"):
                got = self.assert_unchanged(
                    svc, lambda: send(s, self.secret(s), Origin="http://example.com"))
                self.assertEqual((got[0], got[2]), (403, b"origin refused\n"))
            with self.subTest(path, case="no secret"):
                got = self.assert_unchanged(svc, lambda: self.post(svc, path, without_secret))
                self.assertEqual((got[0], got[2]), (400, bad.encode() + b"\n"))
        for path, send, _, _ in (routes[0], routes[2]):
            for name, sid, reason in (("closed", d, sprints.ENDED),
                                      ("stopping", stopping, sprints.ALREADY_STOPPING)):
                with self.subTest(path, case=name):
                    got = self.assert_unchanged(svc, lambda: send(sid, self.secret(sid)))
                    self.assertEqual((got[0], got[2]), (409, reason.encode() + b"\n"))
        with self.subTest("too large"):
            got = self.assert_unchanged(svc, lambda: support.post_page(
                svc.address, NOTICE, JSON, b"x" * (service.MAX_NOTICE_BYTES + 1)))
            self.assertEqual(got[0], 413)
        for path in (NOTICE, NOTICES, WITHDRAW_NOTICE):
            for method in ("GET", "PUT", "DELETE"):
                with self.subTest(path, method=method):
                    status, headers, _ = support.request(svc.address, method, path)
                    self.assertEqual((status, headers["Allow"]), (405, "POST"))
            self.assertIn(path, service.MANAGER_WRITES)
            self.assertNotIn(path, service.PAGE_WRITES)

    def test_the_notice_routes_call_no_tracker_write(self):
        ticks, prompts = [], []
        svc = self.open(tick=lambda *a: ticks.append(a),
                        owner_path=lambda *a, **k: prompts.append(a))
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        before = len(support.log_rows(self.store))
        self.posted(svc, a, CLAIM)
        kept = self.posted(svc, a, HEADS_UP)
        self.posted(svc, a, HAND_OFF)
        self.assertEqual(len(self.listed(svc, a)), 3)
        status, _, _ = self.withdraw(svc, a, kept)
        self.assertEqual(status, 200)
        self.assertEqual(ticks, [])
        self.assertEqual(prompts, [])
        self.assertEqual({row[2] for row in support.log_rows(self.store)[before:]},
                         {"notice.posted", "notice.withdrawn"})

    def test_the_secret_and_the_notice_text_appear_in_no_stderr_line(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        secret = self.secret(a)
        private = "a private plan"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            got = self.notice(svc, a, {**HEADS_UP, "text": private}, secret + "x")
            self.assertEqual((got[0], got[2]), (403, b"secret refused\n"))
            got = self.notice(svc, a, {**HEADS_UP, "text": private + "x" * 300})
            self.assertEqual(got[0], 409)
            got = self.notice(svc, a, {"kind": "heads-up", "text": private,
                                       "x\nconsole: approve_refused " + secret: 1})
            self.assertEqual((got[0], got[2]),
                             (409, b"a heads-up notice has only kind and text\n"))
        output = stderr.getvalue()
        self.assertEqual(output.splitlines(), [
            f"console: notice_refused {a} secret refused",
            f"console: notice_refused {a} the notice's text is over 280 characters",
            f"console: notice_refused {a} a heads-up notice has only kind and text"])
        for leaked in (secret, "approve_refused", private):
            self.assertNotIn(leaked, output)

    def test_notices_survive_a_restart(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        self.posted(svc, a, CLAIM)
        gone = self.posted(svc, a, HEADS_UP)
        self.assertEqual(self.withdraw(svc, a, gone)[0], 200)
        svc.close()
        again = self.start()
        self.assertEqual([entry["kind"] for entry in self.listed(again, a)], ["claim"])


FROZEN = "routes are frozen until Friday"


class OwnerNoticeRouteTest(Case):
    """The owner posts and withdraws a heads-up from the page (#1120, ADR-console-053)."""

    def open(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        return self.start(**kwargs)

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def owner(self, svc, path, body, **headers):
        return support.post_page(svc.address, path, {**JSON, **(headers or self.own(svc))},
                                 json.dumps(body).encode())

    def post_owner(self, svc, project_id, text, **headers):
        return self.owner(svc, OWNER_NOTICE, {"project_id": project_id, "text": text}, **headers)

    def withdraw_owner(self, svc, project_id, notice_id, **headers):
        return self.owner(svc, OWNER_WITHDRAW,
                          {"project_id": project_id, "notice": notice_id}, **headers)

    def posted(self, svc, project_id, text=FROZEN):
        status, _, body = self.post_owner(svc, project_id, text)
        self.assertEqual((status, body), (204, b""))
        return self.rows("notice.posted")[-1][0]

    def listed(self, svc, sid):
        status, _, body = support.post_page(svc.address, NOTICES, JSON, json.dumps(
            {"sprint_id": sid, "secret": self.secret(sid)}).encode())
        self.assertEqual(status, 200, body)
        return json.loads(body)["notices"]

    def rows(self, kind):
        return [row for row in support.log_rows(self.store) if row[2] == kind]

    def refused(self, svc, send, status, reason):
        got = self.assert_unchanged(svc, send)
        self.assertEqual((got[0], got[2]), (status, reason.encode() + b"\n"))

    def test_a_posted_owner_notice_is_stored_and_listed_as_the_owners(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        b = svc.state_goal("owner/p01", OTHER_GOAL)
        c = svc.state_goal("owner/p00", GOAL_TEXT)
        before = len(support.log_rows(self.store))
        status, _, body = self.owner(svc, OWNER_NOTICE, {
            "project_id": "owner/p01", "text": " routes are frozen until Friday "}, **self.own(svc))
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(len(support.log_rows(self.store)), before + 1)
        (seq, at, kind, project, payload), = self.rows("notice.posted")
        self.assertEqual((kind, project), ("notice.posted", "owner/p01"))
        self.assertEqual(json.loads(payload), {
            "poster": "owner", "notice": {"kind": "heads-up", "text": FROZEN}})
        for sid in (a, b):
            self.assertEqual(self.listed(svc, sid), [{
                "at": at, "id": seq, "kind": "heads-up", "owner": True, "sprint_id": None,
                "text": FROZEN, "title": None}])
        self.assertEqual(self.listed(svc, c), [])

    def test_an_owner_notice_is_refused_without_the_token_or_from_another_origin(self):
        svc = self.open()
        svc.state_goal("owner/p01", GOAL_TEXT)
        origin = f"http://127.0.0.1:{svc.address[1]}"
        bodies = {OWNER_NOTICE: {"project_id": "owner/p01", "text": FROZEN},
                  OWNER_WITHDRAW: {"project_id": "owner/p01", "notice": 1}}
        for path, body in bodies.items():
            for name, headers, reason in (
                    ("no token", {"Origin": origin}, "token refused"),
                    ("wrong token", {"Origin": origin, "X-Console-Token": "nope"},
                     "token refused"),
                    ("foreign origin", {"Origin": "http://evil.example",
                                        "X-Console-Token": self.token()}, "origin refused"),
                    ("no origin", {"X-Console-Token": self.token()}, "origin refused")):
                with self.subTest(path=path, case=name):
                    self.refused(svc, lambda: self.owner(svc, path, body, **headers), 403, reason)

    def test_an_owner_notice_over_its_bounds_or_a_sixth_is_refused_with_the_reason(self):
        svc = self.open()
        svc.state_goal("owner/p01", GOAL_TEXT)
        for name, project, text, reason in (
                ("long", "owner/p01", "x" * 281, "the notice's text is over 280 characters"),
                ("blank", "owner/p01", "  ", "the notice has no valid text"),
                ("line break", "owner/p01", "a\nb", "the notice has no valid text"),
                ("unregistered", "owner/p99", "t", sprints.UNREGISTERED),
                ("no sprint", "owner/p00", "t", sprints.OWNER_NOTICE_NO_SPRINT)):
            with self.subTest(name):
                self.refused(svc, lambda: self.post_owner(svc, project, text), 409, reason)
        for name, body in (("no text", {"project_id": "owner/p01"}),
                           ("text not a string", {"project_id": "owner/p01", "text": 3})):
            with self.subTest(name):
                self.refused(svc, lambda: self.owner(svc, OWNER_NOTICE, body, **self.own(svc)),
                             400, "bad owner notice")
        first = self.posted(svc, "owner/p01", "x" * 280)
        for _ in range(4):
            self.posted(svc, "owner/p01")
        with self.subTest("sixth"):
            self.refused(svc, lambda: self.post_owner(svc, "owner/p01", "one more"),
                         409, sprints.OWNER_NOTICE_LIMIT)
        self.assertEqual(self.withdraw_owner(svc, "owner/p01", first)[0], 204)
        self.assertEqual(self.post_owner(svc, "owner/p01", "one more")[0], 204)

    def test_withdraw_ends_the_owners_notice_and_refuses_what_it_cannot_end(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.state_goal("owner/p00", GOAL_TEXT)
        n1 = self.posted(svc, "owner/p01")
        status, _, body = self.post_page_json(svc, NOTICE, {
            "sprint_id": a, "secret": self.secret(a), "notice": HEADS_UP})
        self.assertEqual(status, 200, body)
        m = json.loads(body)["notice"]
        self.assertEqual(self.withdraw_owner(svc, "owner/p01", n1)[0], 204)
        (_, _, _, project, payload), = self.rows("notice.withdrawn")
        self.assertEqual((project, json.loads(payload)), ("owner/p01", {
            "poster": "owner", "notice": n1}))
        self.assertEqual([entry["id"] for entry in self.listed(svc, a)], [m])
        n2 = self.posted(svc, "owner/p01")
        for name, send, status, reason in (
                ("again", lambda: self.withdraw_owner(svc, "owner/p01", n1), 409,
                 sprints.NOTICE_ENDED),
                ("a managers", lambda: self.withdraw_owner(svc, "owner/p01", m), 409,
                 sprints.OWNER_NOTICE_MANAGERS),
                ("unknown", lambda: self.withdraw_owner(svc, "owner/p01", 999), 409,
                 sprints.NOTICE_UNKNOWN),
                ("another project's", lambda: self.withdraw_owner(svc, "owner/p00", n2), 409,
                 sprints.NOTICE_UNKNOWN),
                ("by a manager", lambda: self.post_page_json(svc, WITHDRAW_NOTICE, {
                    "sprint_id": a, "secret": self.secret(a), "notice": n2}), 409,
                 sprints.NOTICE_OWNERS),
                ("zero", lambda: self.owner(svc, OWNER_WITHDRAW, {
                    "project_id": "owner/p01", "notice": 0}, **self.own(svc)), 400,
                 "bad owner notice withdrawal")):
            with self.subTest(name):
                self.refused(svc, send, status, reason)

    def post_page_json(self, svc, path, body):
        return support.post_page(svc.address, path, JSON, json.dumps(body).encode())

    def test_withdraw_takes_the_owners_notice_off_the_board_and_the_blocks(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)

        def project():
            return next(e for e in json.loads(svc.view_bytes)["entries"]
                        if e["project_id"] == "owner/p01")

        n = self.posted(svc, "owner/p01")
        entry = project()
        self.assertEqual([(m["id"], m["owner"], m["poster"], m["text"]) for m in entry["notices"]],
                         [(n, True, "You", FROZEN)])
        self.assertTrue(entry["notice_post"])
        self.assertEqual(self.withdraw_owner(svc, "owner/p01", n)[0], 204)
        entry = project()
        self.assertEqual(entry["notices"], [])
        self.assertTrue(entry["notice_post"])
        self.assertEqual(self.listed(svc, a), [])

    def test_owner_notices_survive_a_restart(self):
        svc = self.open()
        a = svc.state_goal("owner/p01", GOAL_TEXT)
        gone = self.posted(svc, "owner/p01", "first")
        kept = self.posted(svc, "owner/p01", "second")
        self.assertEqual(self.withdraw_owner(svc, "owner/p01", gone)[0], 204)
        svc.close()
        again = self.start()
        self.assertEqual([(entry["id"], entry["text"]) for entry in self.listed(again, a)],
                         [(kept, "second")])

    def test_a_new_managers_first_prompt_carries_the_owners_notice(self):
        support.sign_in(self.store, "work")
        launches, queued = support.Launches(), support.Queued()
        svc = self.open(launcher=launches, dispatch=queued,
                        profile_dirs=[support.profile_dir(self.store, "work")])
        svc.state_goal("owner/p01", GOAL_TEXT)
        queued.run_next()
        self.posted(svc, "owner/p01")
        svc.state_goal("owner/p01", OTHER_GOAL)
        queued.run_next()
        prompt = launches.calls[-1].prompt
        line = "- heads-up from the owner, just now: routes are frozen until Friday"
        self.assertIn(line, prompt.splitlines())
        self.assertLess(prompt.index(line), prompt.index("The goal: "))
        self.assertEqual(support.goal_of(prompt), OTHER_GOAL)

    def test_the_owner_routes_print_neither_the_text_nor_the_token(self):
        svc = self.open()
        svc.state_goal("owner/p01", GOAL_TEXT)
        private = "a private plan"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.post_owner(svc, "owner/p00", private)[0], 409)
            self.assertEqual(self.post_owner(svc, "owner/p01", private + "x" * 300)[0], 409)
            n = self.posted(svc, "owner/p01", private)
            self.assertEqual(self.withdraw_owner(svc, "owner/p01", n + 100)[0], 409)
        output = stderr.getvalue()
        lines = output.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("console: owner_notice_refused owner/p00 "), lines[0])
        self.assertTrue(lines[1].startswith("console: owner_notice_refused owner/p01 "), lines[1])
        self.assertTrue(lines[2].startswith("console: owner_notice_withdraw_refused owner/p01 "),
                        lines[2])
        for leaked in (private, self.token()):
            self.assertNotIn(leaked, output)
