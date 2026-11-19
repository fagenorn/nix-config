"""The guest writes of the console (#1263): a colleague starts and steers their own sprints.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import socket
import unittest

from agent_tools.console import guest, service, sprints

from agent_tools.console.event_log import MANAGER_STOPPED, QUESTIONS_ASKED

from . import console_test_support as support
from .console_test_support import PIXEL, WIDE
from .test_console_guest_page import GUEST, named, page_of
from .test_console_guest_service import (
    COLLEAGUE, GOAL, JSON, OTHER_HOST, PARTS, ROOT, STRANGER, TAILNET, GuestCase)
from .test_console_page import PAGE, START, full, has_class, nodes
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

SECOND = "second@example.invalid"
ACTOR = guest.GuestActor(COLLEAGUE, TAILNET)
THEIRS = guest.GuestActor(SECOND, TAILNET)
UNSET = object()
BAD = {"/api/goal": "bad goal", "/api/approve": "bad approve", "/api/reply": "bad reply",
       "/api/round-answer": "bad round answer", "/api/message": "bad message"}
QUESTION = {"question": "Which store keeps the checkpoints?", "blocks": "the resume slice",
            "options": ["sqlite", "files"], "recommended": "files"}


def walk(node):
    """Every mapping inside a decoded view."""
    if isinstance(node, dict):
        yield node
        for member in node.values():
            yield from walk(member)
    elif isinstance(node, list):
        for member in node:
            yield from walk(member)


def sprint_entry(view, sprint_id):
    return next(node for node in walk(view)
                if node.get("type") == "sprint" and node.get("sprint_id") == sprint_id)


def inbox_item(view, key):
    return next(item for item in view["inbox"]["open"] if item["key"] == key)


class GuestWriteCase(GuestCase):
    def setUp(self):
        super().setUp()
        self.rounds = {}

    def guest_post(self, svc, path, body, *, token=UNSET, origin=UNSET, logins=(COLLEAGUE,),
                   host="localhost", forwarded_host=TAILNET, extra=None, send_body=True,
                   method="POST"):
        token = self.guest_token() if token is UNSET else token
        origin = "https://" + TAILNET if origin is UNSET else origin
        headers = {**JSON, **(extra or {})}
        if token is not None:
            headers["X-Console-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        connection = support.UnixHTTPConnection(svc.guest_socket)
        try:
            connection.putrequest(method, path, skip_host=True)
            if host is not None:
                connection.putheader("Host", host)
            for name in ([] if forwarded_host is None else [forwarded_host]
                         if isinstance(forwarded_host, str) else forwarded_host):
                connection.putheader("X-Forwarded-Host", name)
            for login in logins:
                connection.putheader("Tailscale-User-Login", login)
            for name, value in headers.items():
                for member in value if isinstance(value, list) else [value]:
                    connection.putheader(name, member)
            connection.putheader("Content-Length", str(len(raw)) if send_body else "100")
            connection.endheaders(raw if send_body else b"")
            response = connection.getresponse()
            self.last_headers = dict(response.getheaders())
            got = response.status, response.read()
        finally:
            connection.close()
        svc.settle_guest_readings()
        return got

    def still(self, svc, action):
        before = {login: svc.guest_view_bytes(login) for login in (COLLEAGUE, SECOND)}
        result = self.unchanged(svc, action)
        for login, view in before.items():
            self.assertEqual(svc.guest_view_bytes(login), view)
        return result

    def rows(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def brief(self, svc, sid, version):
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "brief": PARTS}).encode()
        status, _, answer = support.post_page(svc.address, "/api/brief", JSON, body)
        self.assertEqual((status, json.loads(answer)), (200, {"version": version}))

    def picture(self, svc, sid, data):
        status, _, answer = support.post_page(
            svc.address, "/api/picture",
            {"Content-Type": "image/png", "X-Console-Sprint": sid,
             "X-Console-Secret": self.secret(sid)}, data)
        self.assertEqual(status, 200, answer)
        return json.loads(answer)["picture"]

    def ask(self, svc, sid, pictures=(), owner_only=False):
        question = dict(QUESTION)
        if owner_only:
            question["owner_only"] = True
        if pictures:
            question["pictures"] = [
                {"picture": self.picture(svc, sid, data), "line": f"the card {pair}", "pair": pair}
                for data, pair in pictures]
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid),
                           "round": {"questions": [question]}}).encode()
        status, _, answer = support.post_page(svc.address, "/api/ask", JSON, body)
        self.assertEqual(status, 200, answer)
        self.rounds[sid] = json.loads(answer)["round"]

    def waiting(self, svc, project_id, by):
        sid = svc.state_goal(project_id, GOAL, by=by)
        self.brief(svc, sid, 1)
        return sid

    def asking(self, svc, project_id, by, pictures=(), owner_only=False):
        sid = self.waiting(svc, project_id, by)
        svc.approve_brief(project_id, sid, 1)
        self.ask(svc, sid, pictures, owner_only)
        svc.read_inbox(sid, self.secret(sid))
        return sid

    def bodies(self, brief_sid, q_sid, project_id="owner/p01"):
        """One valid body per guest write, against the given sprints."""
        mine = {"project_id": project_id, "sprint_id": brief_sid}
        return {
            "/api/goal": {"project_id": project_id, "goal": GOAL},
            "/api/approve": {**mine, "version": 1},
            "/api/reply": {**mine, "version": 1, "reply": "split it"},
            "/api/round-answer": {"project_id": project_id, "sprint_id": q_sid,
                                  "round": self.rounds.get(q_sid, 1), "question": 0, "choice": 0},
            "/api/message": {**mine, "text": "keep the reader"},
        }


class GuestActionsTest(GuestWriteCase):
    def test_a_colleague_starts_and_steers_their_sprint_on_the_guest_port(self):
        self.seed()
        svc = self.start()
        status, body = self.guest_post(svc, "/api/goal", {"project_id": "owner/p01",
                                                          "goal": GOAL})
        self.assertEqual((status, body), (204, b""))
        (stated,) = self.rows("goal.stated")
        sid = stated["sprint_id"]
        self.brief(svc, sid, 1)
        mine = {"project_id": "owner/p01", "sprint_id": sid}
        status, _ = self.guest_post(svc, "/api/reply", {**mine, "version": 1,
                                                        "reply": "split it"})
        self.assertEqual(status, 204)
        self.brief(svc, sid, 2)
        status, _ = self.guest_post(svc, "/api/approve", {**mine, "version": 2})
        self.assertEqual(status, 204)
        self.ask(svc, sid)
        status, _ = self.guest_post(svc, "/api/round-answer", {
            **mine, "round": self.rounds[sid], "question": 0, "choice": 0})
        self.assertEqual(status, 204)
        status, _ = self.guest_post(svc, "/api/message", {**mine, "text": "keep the reader"})
        self.assertEqual(status, 204)
        for kind in ("goal.stated", "brief.replied", "brief.approved", "question.answered",
                     "sprint.messaged"):
            with self.subTest(kind):
                (row,) = [row for row in self.rows(kind) if row["sprint_id"] == sid]
                self.assertEqual(row["by"], COLLEAGUE)
        self.assertEqual(sprint_entry(json.loads(svc.view_bytes), sid)["started_by"], COLLEAGUE)

    def test_the_owner_s_rows_carry_no_actor(self):
        self.seed()
        svc = self.start()
        owner = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                 "X-Console-Token": self.owner_token(), **JSON}
        status, _, answer = support.post_page(
            svc.address, "/api/goal", owner,
            json.dumps({"project_id": "owner/p01", "goal": GOAL}).encode())
        self.assertEqual(status, 204, answer)
        (stated,) = self.rows("goal.stated")
        sid = stated["sprint_id"]
        status, _, answer = support.post_page(
            svc.address, "/api/message", owner, json.dumps({
                "project_id": "owner/p01", "sprint_id": sid, "text": "hello"}).encode())
        self.assertEqual(status, 204, answer)
        (messaged,) = self.rows("sprint.messaged")
        self.assertEqual(set(stated), {"sprint_id", "goal"})
        self.assertEqual(set(messaged), {"sprint_id", "goal", "text"})
        (entry,) = svc.read_inbox(sid, self.secret(sid))
        self.assertNotIn("by", entry)

    def test_the_guest_view_marks_what_the_colleague_may_steer(self):
        self.seed()
        svc = self.start()
        mine = self.waiting(svc, "owner/p01", ACTOR)
        own = self.waiting(svc, "owner/p01", None)
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertIs(sprint_entry(view, mine)["steer"], True)
        self.assertIs(sprint_entry(view, own)["steer"], False)
        self.assertIs(inbox_item(view, f"brief/{mine}")["steer"], True)
        self.assertIs(inbox_item(view, f"brief/{own}")["steer"], False)
        self.assertNotIn('"steer"', svc.view_bytes.decode())

    def test_a_guest_answer_reaches_the_manager_but_never_answers_a_look(self):
        self.seed()
        svc = self.start()
        plain = self.asking(svc, "owner/p01", ACTOR)
        look = self.asking(svc, "owner/p01", ACTOR,
                           pictures=[(PIXEL, "before"), (WIDE, "after")])
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertIs(inbox_item(view, f"question/{plain}/{self.rounds[plain]}/0")["steer"],
                      True)
        self.assertIs(inbox_item(view, f"question/{look}/{self.rounds[look]}/0")["steer"],
                      False)
        bodies = self.bodies(plain, plain)
        status, body = self.guest_post(svc, "/api/round-answer", bodies["/api/round-answer"])
        self.assertEqual(status, 204, body)
        (entry,) = svc.read_inbox(plain, self.secret(plain))
        self.assertEqual((entry["kind"], entry["by"]), ("answer", COLLEAGUE))
        bodies = self.bodies(look, look)
        status, body = self.still(svc, lambda: self.guest_post(
            svc, "/api/round-answer", bodies["/api/round-answer"]))
        self.assertEqual((status, body), (409, guest.OWNER_LOOK_TEXT.encode() + b"\n"))
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertIs(inbox_item(view, f"question/{look}/{self.rounds[look]}/0")["steer"],
                      False)


    def test_an_owner_only_question_is_the_owner_s_to_answer(self):
        self.seed()
        svc = self.start()
        sid = self.asking(svc, "owner/p01", ACTOR, owner_only=True)
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertIs(inbox_item(view, f"question/{sid}/{self.rounds[sid]}/0")["steer"], False)
        body = self.bodies(sid, sid)["/api/round-answer"]
        status, text = self.still(svc, lambda: self.guest_post(svc, "/api/round-answer", body))
        self.assertEqual((status, text), (409, guest.OWNER_ONLY_TEXT.encode() + b"\n"))
        self.assertEqual(self.rows("question.answered"), [])
        svc.answer_question("owner/p01", sid, self.rounds[sid], 0, 0, None)
        (row,) = self.rows("question.answered")
        self.assertNotIn("by", row)

    def test_a_stopped_sprint_s_brief_is_no_card_on_the_guest_page(self):
        self.seed()
        svc = self.start()
        sid = self.waiting(svc, "owner/p01", ACTOR)
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertEqual([i["key"] for i in view["inbox"]["open"]], [f"brief/{sid}"])
        svc.stop_sprint("owner/p01", sid)
        view = json.loads(svc.guest_view_bytes(COLLEAGUE))
        self.assertEqual(view["inbox"]["open"], [])
        self.assertEqual(json.loads(svc.view_bytes)["inbox"]["open"], [])


class GuestWriteTableTest(GuestWriteCase):
    def test_the_guest_writes_are_exactly_five(self):
        self.assertEqual(service.GUEST_WRITES, {
            "/api/goal", "/api/approve", "/api/reply", "/api/round-answer", "/api/message"})
        self.assertLessEqual(service.GUEST_WRITES, service.PAGE_WRITES)
        self.assertFalse(service.GUEST_WRITES & service.OWNER_ONLY)

    def world(self, svc):
        """Sprints of every owner and project, each with a waiting brief or an open question."""
        made = {}
        for name, project, by in (("mine", "owner/p01", ACTOR), ("own", "owner/p01", None),
                                  ("theirs", "owner/p01", THEIRS), ("other", "owner/p00", None)):
            made[name] = (self.waiting(svc, project, by), self.asking(svc, project, by))
        return made

    def merit_rows(self, made):
        """`(name, route, body, status, text)` for each refusal on its merits."""
        rows = [("goal on another project", "/api/goal",
                 self.bodies(*made["mine"], "owner/p00")["/api/goal"], 409,
                 guest.NOT_YOUR_PROJECT_TEXT)]
        for name, text, project in (("other", guest.NOT_YOUR_PROJECT_TEXT, "owner/p00"),
                                    ("own", guest.NOT_YOUR_SPRINT_TEXT, "owner/p01"),
                                    ("theirs", guest.NOT_YOUR_SPRINT_TEXT, "owner/p01")):
            bodies = self.bodies(*made[name], project)
            rows += [(f"{route} {name}", route, bodies[route], 409, text)
                     for route in sorted(service.GUEST_WRITES - {"/api/goal"})]
        bodies = self.bodies(*made["other"], "owner/p01")
        rows += [(f"{route} other in p01", route, bodies[route], 409, sprints.NOT_OPEN)
                 for route in sorted(service.GUEST_WRITES - {"/api/goal"})]
        bodies = self.bodies(*made["mine"])
        rows += [(f"{route} extra member", route, {**bodies[route], "by": "owner"}, 400,
                  BAD[route]) for route in sorted(service.GUEST_WRITES)]
        return rows

    def test_every_page_write_refuses_the_guest_with_nothing_appended(self):
        self.seed(colleagues={COLLEAGUE: ["owner/p01"], SECOND: ["owner/p01"]})
        svc = self.start()
        made = self.world(svc)
        for route in sorted(service.PAGE_WRITES - service.GUEST_WRITES):
            with self.subTest(route=route):
                status, body = self.still(svc, lambda: self.guest_post(
                    svc, route, b"", send_body=False))
                self.assertEqual((status, body), (403, guest.OWNER_ONLY_TEXT.encode() + b"\n"))
        origin = "https://" + TAILNET
        guards = (
            ("no token", {"token": None}, 403, "token refused"),
            ("wrong token", {"token": "x" * 43}, 403, "token refused"),
            ("owner token", {"token": self.owner_token()}, 403, "token refused"),
            ("no origin", {"origin": None}, 403, "origin refused"),
            ("http origin", {"origin": "http://" + TAILNET}, 403, "origin refused"),
            ("other origin", {"origin": "https://other.invented-tailnet.ts.net"}, 403,
             "origin refused"),
            ("two origins", {"origin": [origin, origin]}, 403, "origin refused"),
            ("no login", {"logins": ()}, 403, guest.NOT_SHARED_TEXT),
            ("two logins", {"logins": (COLLEAGUE, SECOND)}, 403, guest.NOT_SHARED_TEXT),
            ("forged login", {"logins": (STRANGER,)}, 403, guest.NOT_SHARED_TEXT),
            ("tailnet name as Host", {"host": TAILNET}, 403, guest.HOST_TEXT),
            ("other forwarded host", {"forwarded_host": OTHER_HOST}, 403, guest.HOST_TEXT),
            ("no Host", {"host": None}, 403, guest.HOST_TEXT),
            ("Host with a port", {"host": "localhost:80"}, 403, guest.HOST_TEXT),
            ("no forwarded host", {"forwarded_host": None}, 403, guest.HOST_TEXT),
            ("forwarded host with port", {"forwarded_host": TAILNET + ":443"}, 403,
             guest.HOST_TEXT),
            ("two forwarded hosts", {"forwarded_host": [TAILNET, TAILNET]}, 403, guest.HOST_TEXT),
            ("localhost origin", {"origin": "https://localhost"}, 403, "origin refused"),
            ("origin with port", {"origin": "https://" + TAILNET + ":443"}, 403,
             "origin refused"))
        for route in sorted(service.GUEST_WRITES):
            for name, kwargs, status, text in guards:
                with self.subTest(route=route, case=name):
                    got = self.still(svc, lambda: self.guest_post(
                        svc, route, b"", send_body=False, **kwargs))
                    self.assertEqual(got, (status, text.encode() + b"\n"))
            with self.subTest(route=route, case="a GET"):
                got = self.still(svc, lambda: self.guest_post(
                    svc, route, b"", send_body=False, method="GET"))
                self.assertEqual(got, (405, b"method not allowed\n"))
                self.assertEqual(self.last_headers["Allow"], "POST")
        for name, route, body, status, text in self.merit_rows(made):
            with self.subTest(case=name):
                got = self.still(svc, lambda: self.guest_post(svc, route, body))
                self.assertEqual(got, (status, text.encode() + b"\n"))
        with self.subTest(case="forged login on the owner's port"):
            got = self.still(svc, lambda: support.post_page(
                svc.address, "/api/goal",
                {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                 "X-Console-Token": self.owner_token(), "Tailscale-User-Login": COLLEAGUE,
                 **JSON}, json.dumps({"project_id": "owner/p01", "goal": GOAL}).encode()))
            self.assertEqual((got[0], got[2]), (403, guest.OWNER_PORT_TEXT.encode() + b"\n"))
        control = self.bodies(self.waiting(svc, "owner/p01", ACTOR),
                              self.asking(svc, "owner/p01", ACTOR))
        for route, body in control.items():
            with self.subTest(case="control", route=route):
                if route == "/api/reply":
                    body = {**body, "sprint_id": self.waiting(svc, "owner/p01", ACTOR)}
                self.assertEqual(self.guest_post(svc, route, body), (204, b""))

    def write_calls(self, svc):
        brief_sid = self.waiting(svc, "owner/p01", ACTOR)
        q_sid = self.asking(svc, "owner/p01", ACTOR)
        return (
            lambda: svc.state_goal("owner/p01", GOAL, by=ACTOR),
            lambda: svc.approve_brief("owner/p01", brief_sid, 1, by=ACTOR),
            lambda: svc.reply_brief("owner/p01", brief_sid, 1, "split it", by=ACTOR),
            lambda: svc.answer_question("owner/p01", q_sid, self.rounds[q_sid], 0, 0, None,
                                        by=ACTOR),
            lambda: svc.send_message("owner/p01", brief_sid, "hello", by=ACTOR))

    def refused(self, svc, calls, text):
        for call in calls:
            with self.subTest(text=text, call=call.__code__.co_firstlineno):
                def attempt(call=call):
                    with self.assertRaises(sprints.Refused) as raised:
                        call()
                    self.assertEqual(str(raised.exception), text)
                self.still(svc, attempt)

    def test_the_access_list_is_checked_again_at_write_time(self):
        self.seed()
        svc = self.start()
        calls = self.write_calls(svc)
        reading = self.status
        self.status = {"Self": {"DNSName": OTHER_HOST + ".",
                                "TailscaleIPs": reading["Self"]["TailscaleIPs"]}}
        svc.poll_serve()
        self.refused(svc, calls, guest.HOST_TEXT)
        self.status = None
        svc.poll_serve()
        self.refused(svc, calls, guest.NAME_UNREAD_TEXT)
        self.status = reading
        svc.poll_serve()
        svc.set_sharing(False)
        self.refused(svc, calls, guest.SHARING_OFF_TEXT)
        svc.set_sharing(True)
        svc.set_colleague(COLLEAGUE, ("owner/p00",))
        self.refused(svc, calls, guest.NOT_YOUR_PROJECT_TEXT)

    def test_a_removed_colleague_is_refused_at_write_time(self):
        self.seed()
        svc = self.start()
        calls = self.write_calls(svc)
        svc.remove_colleague(COLLEAGUE)
        self.refused(svc, calls, guest.NOT_SHARED_TEXT)

    def test_a_project_unregistered_since_the_page_loaded_is_refused_at_write_time(self):
        self.seed()
        svc = self.start()
        calls = self.write_calls(svc)
        support.write_registry(self.registry, support.entries(2)[:1])
        svc.refresh()
        self.refused(svc, calls, sprints.UNREGISTERED)

    def test_a_brief_of_a_stopping_or_stopped_sprint_takes_no_decision(self):
        self.seed()
        svc = self.start()
        sid = self.waiting(svc, "owner/p01", ACTOR)
        attempts = (lambda: svc.approve_brief("owner/p01", sid, 1, by=ACTOR),
                    lambda: svc.reply_brief("owner/p01", sid, 1, "split it", by=ACTOR))
        svc.stop_sprint("owner/p01", sid)
        self.refused(svc, attempts, sprints.ALREADY_STOPPING)
        with svc._ingest:
            svc._apply(svc.log.append([(MANAGER_STOPPED, "owner/p01", {"sprint_id": sid})]))
        self.refused(svc, attempts, sprints.ENDED)
        self.assertEqual(self.rows("brief.approved"), [])
        self.assertEqual(self.rows("brief.replied"), [])

    def test_a_late_brief_of_a_stopped_sprint_is_refused_when_sent(self):
        self.seed()
        svc = self.start()
        sid = self.waiting(svc, "owner/p01", ACTOR)
        svc.stop_sprint("owner/p01", sid)
        with svc._ingest:
            svc._apply(svc.log.append([(MANAGER_STOPPED, "owner/p01", {"sprint_id": sid})]))
        with self.assertRaises(sprints.Refused) as raised:
            svc.send_brief(sid, self.secret(sid), PARTS)
        self.assertEqual(str(raised.exception), sprints.ENDED)
        self.assertEqual(len(self.rows("brief.sent")), 1)

    def test_a_single_marked_picture_is_no_look_and_the_colleague_answers_it(self):
        self.seed()
        svc = self.start()
        for pair in ("before", "after"):
            with self.subTest(pair=pair):
                sid = self.asking(svc, "owner/p01", ACTOR, pictures=[(PIXEL, pair)])
                view = json.loads(svc.guest_view_bytes(COLLEAGUE))
                self.assertIs(
                    inbox_item(view, f"question/{sid}/{self.rounds[sid]}/0")["steer"], True)
                status, body = self.guest_post(
                    svc, "/api/round-answer", self.bodies(sid, sid)["/api/round-answer"])
                self.assertEqual((status, body), (204, b""))

    def test_no_refusal_or_stderr_line_names_the_login(self):
        self.seed(colleagues={COLLEAGUE: ["owner/p01"], SECOND: ["owner/p01"]})
        svc = self.start()
        made = self.world(svc)
        errors = io.StringIO()
        seen = []
        with contextlib.redirect_stderr(errors):
            for name, route, body, status, text in self.merit_rows(made):
                got = self.guest_post(svc, route, body)
                self.assertEqual(got[0], status, name)
                seen.append(got[1].decode())
        for text in (errors.getvalue(), *seen):
            self.assertNotIn("colleague@", text)
            self.assertNotIn("second@", text)
        self.assertIn("console: ", errors.getvalue())


class GuestDoorWriteTest(GuestWriteCase):
    def test_a_guest_never_answers_a_look_card_whichever_option(self):
        head = "a" * 40
        self.seed()
        posted, reads = [], []
        svc = self.start(look_reader=lambda slug, pr: reads.append((slug, pr)) or ("open", head),
                         look_recorder=lambda *args: posted.append(args) or 1)
        sid = self.waiting(svc, "owner/p01", ACTOR)
        svc.approve_brief("owner/p01", sid, 1)
        with svc._ingest:
            appended = svc.log.append([(QUESTIONS_ASKED, "owner/p01", {
                "sprint_id": sid, "goal": GOAL, "blocker": False, "look_repo": "owner/p01",
                "questions": [{**QUESTION, "look": {"issue": 7, "pr": 8, "head": head,
                                                    "approve": "files"}}]})])
            svc._apply(appended)
        round_id = appended[-1].seq
        asked = next(q for q in svc._sprints[sid].questions if q.round_id == round_id)
        self.assertEqual(asked.look, sprints.QuestionLook(7, 8, head, "files", repo="owner/p01"))
        self.assertEqual(asked.pictures, ())
        for choice in (0, 1):
            with self.subTest(choice=choice):
                got = self.still(svc, lambda: self.guest_post(svc, "/api/round-answer", {
                    "project_id": "owner/p01", "sprint_id": sid, "round": round_id,
                    "question": 0, "choice": choice}))
                self.assertEqual(got, (409, guest.OWNER_LOOK_TEXT.encode() + b"\n"))
        self.assertEqual(self.rows("question.answered"), [])
        self.assertEqual(posted, [])
        self.assertEqual(reads, [])

    def test_a_change_between_admission_and_the_write_refuses_it(self):
        def rename(svc):
            self.status = {"Self": {**self.status["Self"], "DNSName": OTHER_HOST + "."}}
            svc.poll_serve()

        def unread(svc):
            self.status = None
            svc.poll_serve()

        def renamed_back(svc):
            reading = self.status
            rename(svc)
            self.status = reading
            svc.poll_serve()

        def off_and_on(svc):
            svc.set_sharing(False)
            svc.set_sharing(True)

        def removed_and_added(svc):
            svc.remove_colleague(COLLEAGUE)
            svc.set_colleague(COLLEAGUE, ("owner/p01",))

        def narrowed_and_widened(svc):
            svc.set_colleague(COLLEAGUE, ("owner/p00",))
            svc.set_colleague(COLLEAGUE, ("owner/p01",))

        rows = (("rename", rename, guest.HOST_TEXT),
                ("unread", unread, guest.NAME_UNREAD_TEXT),
                ("off", lambda svc: svc.set_sharing(False), guest.SHARING_OFF_TEXT),
                ("removed", lambda svc: svc.remove_colleague(COLLEAGUE), guest.NOT_SHARED_TEXT),
                ("renamed and back", renamed_back, guest.REVOKED_TEXT),
                ("off and on", off_and_on, guest.REVOKED_TEXT),
                ("removed and added", removed_and_added, guest.REVOKED_TEXT),
                ("narrowed and widened", narrowed_and_widened, guest.REVOKED_TEXT))
        for name, change, text in rows:
            with self.subTest(change=name):
                self.setUp()
                self.seed()
                svc = self.start()
                snapshot = []

                def wrapped(svc=svc, change=change):
                    change(svc)
                    snapshot.append(support.log_rows(self.store))

                self.in_flight(svc, wrapped)
                got = self.guest_post(svc, "/api/goal",
                                      {"project_id": "owner/p01", "goal": GOAL})
                self.assertEqual(got, (409, text.encode() + b"\n"))
                self.assertEqual(len(snapshot), 1)
                self.assertEqual(support.log_rows(self.store), snapshot[0])

    def test_name_unread_refuses_every_guest_write_at_the_door(self):
        self.seed()
        self.status = None
        svc = self.start()
        for route in sorted(service.GUEST_WRITES):
            with self.subTest(route=route):
                got = self.still(svc, lambda: self.guest_post(
                    svc, route, b"", send_body=False))
                self.assertEqual(got, (403, guest.NAME_UNREAD_TEXT.encode() + b"\n"))

    def test_sharing_off_refuses_every_guest_write_at_the_door(self):
        self.seed(shared=False)
        svc = self.start()
        for route in sorted(service.GUEST_WRITES):
            with self.subTest(route=route):
                got = self.still(svc, lambda: self.guest_post(
                    svc, route, b"", send_body=False))
                self.assertEqual(got, (403, guest.SHARING_OFF_TEXT.encode() + b"\n"))

    def test_a_peer_neither_root_nor_the_owner_writes_nothing(self):
        self.seed()
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc = self.start(guest_peer_reader=lambda sock: os.geteuid() + 1)
            rows = support.log_rows(self.store)
            body = json.dumps({"project_id": "owner/p01", "goal": GOAL}).encode()
            head = ["POST /api/goal HTTP/1.1", "Host: localhost", f"X-Forwarded-Host: {TAILNET}",
                    f"Tailscale-User-Login: {COLLEAGUE}", "Content-Type: application/json",
                    f"X-Console-Token: {self.guest_token()}", f"Origin: https://{TAILNET}",
                    f"Content-Length: {len(body)}"]
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect(svc.guest_socket)
                try:
                    sock.sendall("\r\n".join(head).encode() + b"\r\n\r\n" + body)
                    got = sock.recv(1)
                except ConnectionResetError:
                    got = b""
        self.assertEqual(got, b"")
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(captured.getvalue().splitlines(), ["console: guest_refused not_permitted"])


class BothPagesTest(GuestWriteCase):
    def owner_post(self, svc, path, body):
        headers = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                   "X-Console-Token": self.owner_token(), **JSON}
        status, _, answer = support.post_page(svc.address, path, headers, json.dumps(body).encode())
        self.assertEqual(status, 204, answer)

    def test_both_pages_show_who_started_who_answered_and_who_wrote(self):
        self.seed()
        svc = self.start()
        mine = {"project_id": "owner/p01"}
        status, _ = self.guest_post(svc, "/api/goal", {**mine, "goal": GOAL})
        self.assertEqual(status, 204)
        (stated,) = self.rows("goal.stated")
        sid = stated["sprint_id"]
        self.brief(svc, sid, 1)
        mine["sprint_id"] = sid
        self.assertEqual(self.guest_post(svc, "/api/approve", {**mine, "version": 1})[0], 204)
        self.ask(svc, sid)
        self.assertEqual(self.guest_post(svc, "/api/round-answer", {
            **mine, "round": self.rounds[sid], "question": 0, "choice": 0})[0], 204)
        self.assertEqual(self.guest_post(svc, "/api/message", {**mine, "text": "keep the reader"})[0],
                         204)
        other = "Tidy the settings page"
        self.owner_post(svc, "/api/goal", {"project_id": "owner/p01", "goal": other})
        owner_sid = [row["sprint_id"] for row in self.rows("goal.stated")
                     if row["sprint_id"] != sid][0]
        self.owner_post(svc, "/api/message", {
            "project_id": "owner/p01", "sprint_id": owner_sid, "text": "owner note"})
        owner_frame = json.loads(svc.view_bytes)
        guest_frame = json.loads(svc.guest_view_bytes(COLLEAGUE))
        for name, page, frame, noted in (("owner", PAGE.read_bytes(), owner_frame, "You: owner note"),
                                         ("guest", GUEST, guest_frame, "The owner: owner note")):
            with self.subTest(name):
                snap = page_of(page, [START, {"frame": frame}, {"open": "earlier:" + sid}])
                (first,) = [n for n in nodes(snap["projects"]) if n["tag"] == "li"
                            and has_class(n, "sprint") and PARTS["title"] in full(n)]
                (second,) = [n for n in nodes(snap["projects"]) if n["tag"] == "li"
                             and has_class(n, "sprint") and other in full(n)]
                self.assertIn("started by " + COLLEAGUE, full(first))
                self.assertNotIn("started by", full(second))
                lines = [full(n) for n in named(snap["projects"], "message-text")]
                self.assertIn(f"Answered by {COLLEAGUE}: {QUESTION['options'][0]}", lines)
                self.assertIn(f"{COLLEAGUE}: keep the reader", lines)
                self.assertIn(noted, lines)


if __name__ == "__main__":
    unittest.main()


class GuestWriteDocsTest(unittest.TestCase):
    def test_the_records_say_guest_writes_ride_the_guest_door(self):
        adrs = ROOT / "docs/areas/console/adr"
        guard = (adrs / "008-only-the-page-writes-with-a-token-and-its-origin.md").read_text()
        for phrase in ("GuestHandler._guest_write", "ADR-console-078 D2",
                       "the guest door (ADR-console-077)"):
            self.assertIn(phrase, guard)
        (decision,) = [line for line in (adrs / (
            "066-a-named-colleague-reaches-the-console-only-through-tailscale-serve-on-a-guest-port.md"
        )).read_text().splitlines() if line.startswith("**D3.")]
        for phrase in ("admitted on the guest door as its reads are (ADR-console-077 D4)",
                       "a question that carries a look or a before-and-after pair is a look before "
                       "merge and stays the owner's"):
            self.assertIn(phrase, decision)
        contract = (ROOT / "python/agent_tools/console/manager-contract.md").read_text()
        self.assertIn("Only an answer whose `sprint inbox` entry carries no `by` is the owner's.",
                      contract)
        self.assertIn("An entry with `by` is a listed colleague's answer, which never answers a look",
                      contract)
