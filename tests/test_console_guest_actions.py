"""The guest writes of the console (#1263): a colleague starts and steers their own sprints.

Run: just agent-workflow-tests
"""
import contextlib
import http.client
import io
import json
import unittest

from agent_tools.console import guest, service, sprints

from . import console_test_support as support
from .console_test_support import PIXEL, WIDE
from .test_console_guest_service import (
    COLLEAGUE, GOAL, JSON, PARTS, STRANGER, TAILNET, GuestCase)
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
                   host=TAILNET, extra=None, send_body=True, method="POST"):
        token = self.guest_token() if token is UNSET else token
        origin = "https://" + TAILNET if origin is UNSET else origin
        headers = {**JSON, **(extra or {})}
        if token is not None:
            headers["X-Console-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        connection = http.client.HTTPConnection(*svc.guest_address, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True)
            if host is not None:
                connection.putheader("Host", host)
            for login in logins:
                connection.putheader("Tailscale-User-Login", login)
            for name, value in headers.items():
                for member in value if isinstance(value, list) else [value]:
                    connection.putheader(name, member)
            connection.putheader("Content-Length", str(len(raw)) if send_body else "100")
            connection.endheaders(raw if send_body else b"")
            response = connection.getresponse()
            self.last_headers = dict(response.getheaders())
            return response.status, response.read()
        finally:
            connection.close()

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

    def ask(self, svc, sid, pictures=()):
        question = dict(QUESTION)
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

    def asking(self, svc, project_id, by, pictures=()):
        sid = self.waiting(svc, project_id, by)
        svc.approve_brief(project_id, sid, 1)
        self.ask(svc, sid, pictures)
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
            ("other host", {"host": "other.invented-tailnet.ts.net"}, 403, guest.HOST_TEXT))
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

    def test_the_access_list_is_checked_again_at_write_time(self):
        self.seed()
        svc = self.start()
        brief_sid = self.waiting(svc, "owner/p01", ACTOR)
        q_sid = self.asking(svc, "owner/p01", ACTOR)

        def calls():
            return (
                lambda: svc.state_goal("owner/p01", GOAL, by=ACTOR),
                lambda: svc.approve_brief("owner/p01", brief_sid, 1, by=ACTOR),
                lambda: svc.reply_brief("owner/p01", brief_sid, 1, "split it", by=ACTOR),
                lambda: svc.answer_question("owner/p01", q_sid, self.rounds[q_sid], 0, 0, None,
                                            by=ACTOR),
                lambda: svc.send_message("owner/p01", brief_sid, "hello", by=ACTOR))

        def refused(text):
            for call in calls():
                with self.subTest(text=text, call=call.__code__.co_firstlineno):
                    def attempt(call=call):
                        with self.assertRaises(sprints.Refused) as raised:
                            call()
                        self.assertEqual(str(raised.exception), text)
                    self.still(svc, attempt)

        svc.set_tailnet("other.invented-tailnet.ts.net")
        refused(guest.HOST_TEXT)
        svc.set_tailnet(TAILNET)
        svc.set_tailnet(None)
        refused(guest.SHARING_OFF_TEXT)
        svc.set_tailnet(TAILNET)
        svc.set_colleague(COLLEAGUE, ("owner/p00",))
        refused(guest.NOT_YOUR_PROJECT_TEXT)
        svc.set_colleague(COLLEAGUE, ("owner/p01",))
        svc.remove_colleague(COLLEAGUE)
        refused(guest.NOT_SHARED_TEXT)

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


if __name__ == "__main__":
    unittest.main()
