"""The console's manager route and the page's brief writes (#887): brief, status, approve, reply.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json

from agent_tools.console import service, sprints, view

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_writes import Case

BRIEF = "/api/brief"
STATUS = "/api/sprint-status"
APPROVE = "/api/approve"
REPLY = "/api/reply"
GOAL_TEXT = "make the importer resumable"
PARTS = {"done": "the importer resumes after a crash", "excluded": ["no new formats"],
         "slices": ["checkpoint", "resume"], "risks": ["partial writes"],
         "asks": ["which store?"]}
JSON = {"Content-Type": "application/json"}


class BriefRouteTest(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def sprint(self, svc, project_id="owner/p01"):
        return svc.state_goal(project_id, GOAL_TEXT)

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def brief(self, svc, sid, secret, parts=PARTS, **headers):
        body = json.dumps({"sprint_id": sid, "secret": secret, "brief": parts}).encode()
        return support.post_page(svc.address, BRIEF, {**JSON, **headers}, body)

    def send(self, svc, sid, parts=PARTS):
        status, _, body = self.brief(svc, sid, self.secret(sid), parts)
        self.assertEqual(status, 200, body)
        return json.loads(body)["version"]

    def page(self, svc, path, body, **headers):
        return support.post_page(svc.address, path, self.own(svc, **{**JSON, **headers}),
                                 json.dumps(body).encode() if isinstance(body, dict) else body)

    def approve(self, svc, sid, version, project_id="owner/p01"):
        return self.page(svc, APPROVE, {"project_id": project_id, "sprint_id": sid,
                                        "version": version})

    def reply(self, svc, sid, version, reply, project_id="owner/p01"):
        return self.page(svc, REPLY, {"project_id": project_id, "sprint_id": sid,
                                      "version": version, "reply": reply})

    def status_of(self, svc, sid):
        got = support.request(svc.address, "GET", f"{STATUS}?sprint_id={sid}")
        self.assertEqual(got[0], 200)
        return json.loads(got[2])

    def entry_of(self, svc, sid):
        for entry in view_of(svc)["entries"]:
            for project in entry["projects"] if entry["type"] == "quiet_group" else [entry]:
                for sprint in project["sprints"]:
                    if sprint["sprint_id"] == sid:
                        return sprint
        self.fail("no sprint entry")

    def refused(self, svc, action, status, text):
        got = self.assert_unchanged(svc, action)
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got

    def test_a_brief_with_the_secret_becomes_one_open_item(self):
        svc = self.open()
        sid = self.sprint(svc)
        before = support.log_rows(self.store)
        got = self.brief(svc, sid, self.secret(sid))
        self.assertEqual((got[0], got[2]), (200, b'{"version":1}'))
        self.assertEqual(got[1]["Content-Type"], "application/json")
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        _, at, kind, project, payload = rows[-1]
        self.assertEqual((kind, project), ("brief.sent", "owner/p01"))
        self.assertEqual(json.loads(payload), {
            "sprint_id": sid, "version": 1, "goal": GOAL_TEXT, "brief": PARTS})
        current = view_of(svc)
        self.assertEqual(current["statement"]["inbox_items"], 1)
        self.assertEqual(current["statement"]["headline"], "1 thing needs you")
        self.assertEqual(current["statement"]["sentence"], view.BRIEF_SENTENCE)
        self.assertEqual(current["inbox"]["open"], [{
            "type": "inbox_item", "reason": "brief", "key": f"brief/{sid}",
            "project_id": "owner/p01", "sprint_id": sid, "goal": GOAL_TEXT, "version": 1,
            "brief": PARTS, "answered": False, "waiting_since": at}])

    def test_a_brief_with_empty_excluded_risks_or_asks_is_recorded(self):
        svc = self.open()
        cases = [{**PARTS, "excluded": []}, {**PARTS, "risks": []}, {**PARTS, "asks": []},
                 {**PARTS, "excluded": [], "risks": [], "asks": []}]
        for parts in cases:
            with self.subTest(parts=parts):
                sid = self.sprint(svc)
                before = support.log_rows(self.store)
                got = self.brief(svc, sid, self.secret(sid), parts)
                self.assertEqual((got[0], got[2]), (200, b'{"version":1}'))
                rows = support.log_rows(self.store)
                self.assertEqual(len(rows), len(before) + 1)
                self.assertEqual(rows[:len(before)], before)
                self.assertEqual(rows[-1][2], "brief.sent")
                self.assertEqual(json.loads(rows[-1][4])["brief"], parts)
                (item,) = [i for i in view_of(svc)["inbox"]["open"] if i["sprint_id"] == sid]
                self.assertEqual(item["brief"], parts)

    def test_a_refused_brief_appends_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        other = self.sprint(svc, "owner/p00")
        gone = self.sprint(svc)
        former = self.secret(gone)
        svc.withdraw_goal("owner/p01", gone)
        right = self.secret(sid)
        table = [
            ("wrong secret", sid, "A" * 43, PARTS, 403, b"secret refused"),
            ("another sprint's secret", sid, self.secret(other), PARTS, 403, b"secret refused"),
            ("empty secret", sid, "", PARTS, 403, b"secret refused"),
            ("unknown sprint", "f" * 16, right, PARTS, 409, b"this sprint is not open"),
            ("withdrawn sprint", gone, former, PARTS, 409, b"this sprint is not open"),
            ("empty slices", sid, right, {**PARTS, "slices": []}, 409,
             b"the brief has no slices"),
            ("blank done", sid, right, {**PARTS, "done": "  "}, 409, b"the brief has no done"),
            ("asks not a list", sid, right, {**PARTS, "asks": "which store?"}, 409,
             b"the brief has no asks"),
            ("excluded null", sid, right, {**PARTS, "excluded": None}, 409,
             b"the brief has no excluded"),
            ("empty slices with empty asks", sid, right, {**PARTS, "slices": [], "asks": []},
             409, b"the brief has no slices"),
            ("secret before parts", sid, "A" * 43,
             {k: v for k, v in PARTS.items() if k != "risks"}, 403, b"secret refused"),
        ]
        for part in PARTS:
            table.append((f"no {part}", sid, right, {k: v for k, v in PARTS.items() if k != part},
                          409, f"the brief has no {part}".encode()))
        for name, target, secret, parts, status, text in table:
            with self.subTest(name):
                got = self.refused(svc, lambda: self.brief(svc, target, secret, parts),
                                   status, text)
                self.assertEqual(got[1]["Content-Type"], "text/plain")
                self.assertEqual(got[1]["Connection"], "close")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.brief(svc, sid, "A" * 43)
        self.assertIn(f"console: brief_refused {sid} secret refused", err.getvalue())
        self.assertNotIn("A" * 43, err.getvalue())
        self.assertNotIn(right, err.getvalue())

    def test_a_brief_from_a_page_or_without_json_is_refused(self):
        svc = self.open()
        sid = self.sprint(svc)
        secret = self.secret(sid)
        valid = json.dumps({"sprint_id": sid, "secret": secret, "brief": PARTS}).encode()
        own = self.own(svc, **JSON)
        table = [
            ("origin", {**JSON, "Origin": own["Origin"]}, valid, 403, b"origin refused"),
            ("origin and token", own, valid, 403, b"origin refused"),
            ("media", {"Content-Type": "text/plain"}, valid, 415, b"json only"),
            ("too large", JSON, b"x" * (service.MAX_BRIEF_BYTES + 1), 413, b"too large"),
            ("not json", JSON, b"not json", 400, b"bad brief"),
            ("extra key", JSON, json.dumps({"sprint_id": sid, "secret": secret, "brief": PARTS,
                                            "x": 1}).encode(), 400, b"bad brief"),
            ("no secret", JSON, json.dumps({"sprint_id": sid, "brief": PARTS}).encode(),
             400, b"bad brief"),
            ("bad id", JSON, json.dumps({"sprint_id": "../x", "secret": secret,
                                         "brief": PARTS}).encode(), 400, b"bad brief"),
            ("scope key", JSON, json.dumps({"sprint_id": sid, "secret": secret,
                                            "brief": {**PARTS, "scope": "x"}}).encode(),
             400, b"bad brief"),
        ]
        for name, headers, body, status, text in table:
            with self.subTest(name):
                self.refused(svc, lambda: support.post_page(svc.address, BRIEF, headers, body),
                             status, text)
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method=method):
                got = self.assert_unchanged(
                    svc, lambda: support.request(svc.address, method, BRIEF))
                self.assertEqual(got[0], 405)
                self.assertEqual(got[1]["Allow"], "POST")

    def test_approving_starts_the_sprint(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.send(svc, sid)
        before = support.log_rows(self.store)
        got = self.approve(svc, sid, 1)
        self.assertEqual((got[0], got[2]), (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        self.assertEqual(rows[-1][2:4], ("brief.approved", "owner/p01"))
        self.assertEqual(json.loads(rows[-1][4]),
                         {"sprint_id": sid, "version": 1, "goal": GOAL_TEXT})
        current = view_of(svc)
        self.assertEqual(current["inbox"]["open"], [])
        self.assertEqual(current["statement"]["inbox_items"], 0)
        entry = self.entry_of(svc, sid)
        self.assertEqual((entry["state"], entry["state_text"]), ("starting", "starting"))
        expected = {"sprint_id": sid, "decision": "approved", "version": 1, "reply": None}
        self.assertEqual(svc.sprint_status(sid), expected)
        got = support.request(svc.address, "GET", f"{STATUS}?sprint_id={sid}")
        self.assertEqual(got[0], 200)
        self.assertEqual(got[1]["Content-Type"], "application/json")
        self.assertEqual(got[2], json.dumps(expected, sort_keys=True,
                                            separators=(",", ":")).encode())

    def test_a_reply_asks_for_changes_in_exact_words(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.send(svc, sid)
        words = "Drop slice 2.\nKeep the rest. "
        before = support.log_rows(self.store)
        got = self.reply(svc, sid, 1, words)
        self.assertEqual((got[0], got[2]), (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(len(rows), len(before) + 1)
        self.assertEqual(rows[-1][2:4], ("brief.replied", "owner/p01"))
        self.assertEqual(json.loads(rows[-1][4]),
                         {"sprint_id": sid, "version": 1, "goal": GOAL_TEXT, "reply": words})
        self.assertEqual(view_of(svc)["inbox"]["open"], [])
        self.assertEqual(self.entry_of(svc, sid)["state"], "drafting")
        self.assertEqual(self.status_of(svc, sid),
                         {"sprint_id": sid, "decision": "changes", "version": 1, "reply": words})

    def test_a_second_brief_replaces_the_first(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.send(svc, sid)
        second = {**PARTS, "slices": ["one slice"]}
        self.assertEqual(self.send(svc, sid, second), 2)
        (item,) = view_of(svc)["inbox"]["open"]
        self.assertEqual((item["version"], item["brief"]["slices"]), (2, ["one slice"]))
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 1)
        self.refused(svc, lambda: self.approve(svc, sid, 1), 409,
                     b"a newer brief replaced this one")
        self.assertEqual(self.approve(svc, sid, 2)[0], 204)
        self.assertEqual(self.send(svc, sid), 3)
        self.assertEqual(self.entry_of(svc, sid)["state"], "drafting")
        self.assertEqual(self.status_of(svc, sid),
                         {"sprint_id": sid, "decision": "none", "version": 3, "reply": None})
        (item,) = view_of(svc)["inbox"]["open"]
        self.assertEqual(item["version"], 3)
        again = self.sprint(svc)
        self.send(svc, again)
        self.assertEqual(self.reply(svc, again, 1, "redo")[0], 204)
        self.assertEqual(self.send(svc, again), 2)
        self.assertEqual(self.status_of(svc, again),
                         {"sprint_id": again, "decision": "none", "version": 2, "reply": None})
        self.assertIn(again, [i["sprint_id"] for i in view_of(svc)["inbox"]["open"]])

    def test_approve_and_reply_refusals(self):
        svc = self.open()
        sid = self.sprint(svc)
        fresh = self.sprint(svc)
        self.send(svc, sid)
        waiting = b"this brief is not waiting for you"
        self.refused(svc, lambda: self.approve(svc, "f" * 16, 1), 409,
                     b"this sprint is not open")
        self.refused(svc, lambda: self.approve(svc, sid, 1, "owner/p00"), 409,
                     b"this sprint is not open")
        self.refused(svc, lambda: self.reply(svc, "f" * 16, 1, "x"), 409,
                     b"this sprint is not open")
        self.refused(svc, lambda: self.approve(svc, fresh, 1), 409, waiting)
        self.refused(svc, lambda: self.reply(svc, fresh, 1, "x"), 409, waiting)
        self.refused(svc, lambda: self.reply(svc, sid, 1, "  "), 409, b"write the reply first")
        self.refused(svc, lambda: self.reply(svc, sid, 1, "x" * 2001), 409,
                     b"a reply is at most 2000 characters")
        self.refused(svc, lambda: self.approve(svc, sid, True), 400, b"bad approve")
        self.refused(svc, lambda: self.page(svc, REPLY, {
            "project_id": "owner/p01", "sprint_id": sid, "version": 1, "reply": "x",
            "extra": 1}), 400, b"bad reply")
        own = self.own(svc, **JSON)
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid, "version": 1}).encode()
        without = {k: v for k, v in own.items() if k != "X-Console-Token"}
        no_origin = {k: v for k, v in own.items() if k != "Origin"}
        for path in (APPROVE, REPLY):
            self.refused(svc, lambda: support.post_page(svc.address, path, without, body), 403,
                         b"token refused")
            self.refused(svc, lambda: support.post_page(svc.address, path, no_origin, body), 403,
                         b"origin refused")
            for method in ("GET", "PUT", "DELETE"):
                got = self.assert_unchanged(
                    svc, lambda: support.request(svc.address, method, path))
                self.assertEqual((got[0], got[1]["Allow"]), (405, "POST"))
        self.assertEqual(self.approve(svc, sid, 1)[0], 204)
        self.refused(svc, lambda: self.approve(svc, sid, 1), 409, waiting)
        self.refused(svc, lambda: self.reply(svc, sid, 1, "x"), 409, waiting)

    def test_status_answers_none_withdrawn_and_unknown(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.assertEqual(self.status_of(svc, sid),
                         {"sprint_id": sid, "decision": "none", "version": None, "reply": None})
        svc.withdraw_goal("owner/p01", sid)
        self.assertEqual(self.status_of(svc, sid), {
            "sprint_id": sid, "decision": "withdrawn", "version": None, "reply": None})
        got = support.request(svc.address, "GET", f"{STATUS}?sprint_id={'e' * 16}")
        self.assertEqual((got[0], got[2]), (404, b"this sprint is not known\n"))
        for query in ("?sprint_id=xyz", f"?sprint_id={sid}&sprint_id={sid}", "",
                      f"?sprint_id={sid}&x=1"):
            with self.subTest(query=query):
                got = support.request(svc.address, "GET", STATUS + query)
                self.assertEqual((got[0], got[2]), (400, b"bad sprint\n"))
        got = support.post_page(svc.address, STATUS, self.own(svc))
        self.assertEqual((got[0], got[1]["Allow"]), (405, "GET"))

    def test_briefs_approvals_and_replies_survive_a_restart(self):
        svc = self.open()
        a, b, c, d = (self.sprint(svc) for _ in range(4))
        self.send(svc, a)
        self.reply(svc, a, 1, "redo")
        self.send(svc, b)
        self.approve(svc, b, 1)
        self.send(svc, c)
        self.send(svc, c, {**PARTS, "slices": ["only"]})
        self.send(svc, d)
        svc.withdraw_goal("owner/p01", d)

        def snapshot(running):
            current = view_of(running)
            entries = [e for e in current["entries"] if e["type"] == "project"
                       and e["project_id"] == "owner/p01"]
            return (current["inbox"], entries, [running.sprint_status(s) for s in (a, b, c, d)])

        before = snapshot(svc)
        self.assertEqual([i["sprint_id"] for i in before[0]["open"]], [c])
        svc.close()
        second = self.start()
        after = snapshot(second)
        self.assertEqual(after, before)
        (item,) = after[0]["open"]
        self.assertEqual((item["sprint_id"], item["version"]), (c, 2))
        self.assertEqual(after[2][3]["decision"], "withdrawn")

    def test_the_digest_says_when_a_brief_arrives_and_when_it_is_approved(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.send(svc, sid)
        self.approve(svc, sid, 1)
        other = self.sprint(svc, "owner/p00")
        self.send(svc, other)
        self.reply(svc, other, 1, "redo")
        moments = view_of(svc)["digest"]["recent"]
        said = [m["sentence"] for m in moments]
        self.assertIn(f"A brief for owner/p01 arrived, version 1: {GOAL_TEXT}", said)
        self.assertIn(f"The brief for owner/p01 was approved, version 1: {GOAL_TEXT}", said)
        self.assertEqual(sorted(m["kind"] for m in moments if m["kind"].startswith("brief_")),
                         ["brief_approved", "brief_sent", "brief_sent"])

    def test_the_secret_is_never_echoed(self):
        svc = self.open()
        sid = self.sprint(svc)
        secret = self.secret(sid)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            right = self.brief(svc, sid, secret)
            wrong = self.brief(svc, sid, "A" * 43)
            malformed = support.post_page(svc.address, BRIEF, JSON, b"{" + secret.encode())
        served = [right[2], wrong[2], malformed[2], support.request(svc.address, "GET", "/")[2],
                  support.request(svc.address, "GET", "/api/state")[2], svc.view_bytes,
                  support.request(svc.address, "GET", f"{STATUS}?sprint_id={sid}")[2]]
        for blob in served:
            self.assertNotIn(secret.encode(), blob)
            self.assertNotIn(b"A" * 43, blob)
        self.assertNotIn(secret, err.getvalue())
        self.assertNotIn("A" * 43, err.getvalue())
        for row in support.log_rows(self.store):
            self.assertNotIn(secret, " ".join(map(str, row)))
