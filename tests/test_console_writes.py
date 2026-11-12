"""The console's page writes (#861): the per-install token, the console's origin, the look route.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import re
import sqlite3
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console, digest, service, write_guard

from agent_tools.console import answer, sprints
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer

from . import console_test_support as support
from .forge_world import ForgeWorld
from .test_console_answer import ASK7 as CHECK_ITEM, C, ITEM, view_of
from .test_console_stream import open_stream, next_frame
from .test_console_tracker import Scripted
from .test_forge_owner_action import ISSUE, SLUG, box_body, comment

LOOK = "/api/looked"
ANSWER = "/api/answer"
CHECK = "/api/check-answer"
GOAL = "/api/goal"
WITHDRAW = "/api/withdraw"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"
        self.token_file = self.store.parent / "page-token"

    def start(self, **kwargs):
        return support.service(self, self.store, self.registry, **kwargs)

    def token(self):
        return self.token_file.read_text().strip()

    def own(self, svc, **headers):
        return {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                "X-Console-Token": self.token(), **headers}

    def assert_unchanged(self, svc, action):
        rows, version = support.log_rows(self.store), svc.version
        result = action()
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(svc.version, version)
        return result

    def assert_refused(self, svc, headers, status, text, **kwargs):
        got = self.assert_unchanged(
            svc, lambda: support.post_page(svc.address, LOOK, headers, **kwargs))
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got


class WriteRouteTest(Case):
    def test_a_look_with_the_token_from_the_page_origin_is_recorded(self):
        svc = self.start()
        before = support.log_rows(self.store)
        status, headers, body = support.post_page(svc.address, LOOK, self.own(svc))
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(headers["Cache-Control"], "no-store")
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        self.assertEqual(rows[-1][2:], (digest.LOOKED, None, "{}"))

    def test_a_write_without_the_token_is_refused_and_changes_nothing(self):
        svc = self.start()
        _, headers, _ = self.assert_refused(
            svc, {"Origin": f"http://127.0.0.1:{svc.address[1]}"}, 403, b"token refused")
        self.assertEqual(headers["Content-Type"], "text/plain")
        self.assertEqual(headers["Connection"], "close")

    def test_a_write_with_a_wrong_token_is_refused_and_changes_nothing(self):
        svc = self.start()
        self.assert_refused(
            svc, self.own(svc, **{"X-Console-Token": "A" * 43}), 403, b"token refused")

    def test_a_write_from_another_origin_is_refused_and_changes_nothing(self):
        svc = self.start()
        port = svc.address[1]
        for origin in ("http://example.test", "null", f"http://localhost:{port}",
                       f"https://127.0.0.1:{port}"):
            with self.subTest(origin=origin):
                self.assert_refused(svc, self.own(svc, Origin=origin), 403, b"origin refused")

    def test_a_write_from_a_terminal_without_an_origin_is_refused_and_changes_nothing(self):
        svc = self.start()
        self.assert_refused(svc, {}, 403, b"origin refused")
        self.assert_refused(
            svc, {"X-Console-Token": self.token()}, 403, b"origin refused")

    def test_two_origins_or_two_tokens_are_refused(self):
        svc = self.start()
        own = self.own(svc)
        self.assert_refused(
            svc, {**own, "Origin": [own["Origin"], own["Origin"]]}, 403, b"origin refused")
        self.assert_refused(
            svc, {**own, "X-Console-Token": [own["X-Console-Token"]] * 2}, 403, b"token refused")

    def test_a_write_with_a_body_is_refused(self):
        svc = self.start()
        self.assert_refused(svc, self.own(svc), 400, b"no body", body=b"{}")
        self.assert_refused(
            svc, self.own(svc, **{"Transfer-Encoding": "chunked"}), 400, b"no body")

    def test_a_foreign_host_is_refused_before_the_guard(self):
        svc = self.start()
        status, _, body = support.post_page(
            svc.address, LOOK, self.own(svc), host="evil.test")
        self.assertEqual((status, body), (403, b"loopback only\n"))

    def test_every_page_write_route_is_guarded(self):
        svc = self.start()
        self.assertEqual(service.PAGE_WRITES,
                         {"/api/looked", "/api/answer", "/api/check-answer", "/api/goal",
                          "/api/withdraw", "/api/approve", "/api/reply",
                          "/api/retry-manager"})
        for path in service.PAGE_WRITES:
            with self.subTest(path=path):
                status, _, body = support.post_page(
                    svc.address, path,
                    {"Origin": f"http://127.0.0.1:{svc.address[1]}"})
                self.assertEqual((status, body), (403, b"token refused\n"))

    def test_other_methods_on_the_look_route_are_refused(self):
        svc = self.start()
        for method in ("GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, LOOK)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "POST")


class AnswerRouteTest(Case):
    def open(self, **kwargs):
        support.write_registry(self.registry, support.entries(1))
        kwargs = {"tracker": Scripted([ITEM]), **kwargs}
        svc = service.ConsoleService(
            self.store, self.registry, port=0, tracker_seconds=3600,
            slug_of=lambda root: SLUG, activity=lambda root: time.time(), session_dirs=lambda: [],
            profile_dirs=lambda: [], repo_of=lambda cwd: cwd,
            branch_pattern_of=lambda repo: "issue-<num>-<slug>", **kwargs)
        svc.poll_tracker()
        svc.start()
        self.addCleanup(svc.close)
        return svc

    def test_the_check_route_maps_refusals(self):
        ask = CHECK_ITEM
        word = {"project_id": "owner/p00", "key": ask["key"], "answer": "passed",
                "version": ask["version"]}
        calls = []

        def owner_path(*args, **kwargs):
            calls.append((args, kwargs))
            if self.raises is not None:
                raise self.raises

        self.raises = None
        svc = self.open(tracker=Scripted([ask]), owner_path=owner_path)
        headers = self.headers(svc)
        post = lambda body, hdrs=headers: support.post_page(
            svc.address, CHECK, hdrs, json.dumps(body).encode() if not isinstance(body, bytes) else body)
        table = [
            ("bad word", post({**word, "answer": "maybe"}), 400, b"bad answer\n"),
            ("no version", post({k: v for k, v in word.items() if k != "version"}), 400, b"bad answer\n"),
            ("unknown key", post({**word, "key": "octo/widgets#99/1"}), 409,
             answer.NOT_OPEN.encode() + b"\n"),
            ("not json", post(json.dumps(word), self.headers(svc, **{"Content-Type": "text/plain"})), 415,
             b"json only\n"),
        ]
        for name, got, status, text in table:
            with self.subTest(name):
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual(calls, [])
        for error, status, text, line in [
                (verify_answer.Refused(verify_answer.ALREADY), 409, verify_answer.ALREADY.encode() + b"\n",
                 f"console: answer_refused owner/p00 {ask['key']} {verify_answer.ALREADY}"),
                (ForgeError("gh_failed", "HTTP 502"), 502, None, "gh_failed: HTTP 502")]:
            with self.subTest(error=type(error).__name__):
                self.raises = error
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    got = post(word)
                self.assertEqual(got[0], status)
                if text is not None:
                    self.assertEqual(got[2], text)
                self.assertIn(line, err.getvalue())
        self.assertEqual(len(calls), 2)
        self.assertEqual([i["key"] for i in view_of(svc)["inbox"]["open"]], [ask["key"]])

    def body(self, **over):
        return json.dumps(
            {"project_id": "owner/p00", "key": ITEM["key"], "choices": [1, 0], **over}).encode()

    def headers(self, svc, **extra):
        return self.own(svc, **{"Content-Type": "application/json", **extra})

    def refused(self, svc, headers, status, text, body=None, **kwargs):
        got = self.assert_unchanged(svc, lambda: support.post_page(
            svc.address, ANSWER, headers, self.body() if body is None else body, **kwargs))
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got

    def test_an_answer_from_the_page_ticks_exactly_that_box_as_the_owner(self):
        world = ForgeWorld(self)
        world.comment_store(SLUG, ISSUE, [comment(C, box_body())])
        world.respond_json("gh", ["api", f"repos/{SLUG}/issues/{ISSUE}"],
                           {"number": ISSUE, "state": "open"})
        svc = self.open()
        status, headers, body = support.post_page(
            svc.address, ANSWER, self.headers(svc), self.body())
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(world.stored()[0]["body"], box_body(ticks={(0, 1), (1, 0)}))
        patches = [argv for argv in world.argvs("gh") if "-X" in argv]
        self.assertEqual(len(patches), 1)
        self.assertIn(f"repos/{SLUG}/issues/comments/{C}", patches[0])
        self.assertTrue(all(call["token_visible"] is False for call in world.calls()))
        self.assertEqual(view_of(svc)["statement"]["inbox_items"], 0)

    def test_an_answer_without_the_token_or_from_another_origin_is_refused_and_ticks_nothing(self):
        ticks = []
        svc = self.open(tick=lambda *args: ticks.append(args))
        own = self.headers(svc)
        origin = own["Origin"]
        token = own["X-Console-Token"]
        without = {k: v for k, v in own.items() if k != "X-Console-Token"}
        no_origin = {k: v for k, v in own.items() if k != "Origin"}
        table = [
            ("no token", without, b"token refused", {}),
            ("wrong token", {**own, "X-Console-Token": "A" * 43}, b"token refused", {}),
            ("two tokens", {**own, "X-Console-Token": [token, token]}, b"token refused", {}),
            ("other origin", {**own, "Origin": "http://example.test"}, b"origin refused", {}),
            ("null origin", {**own, "Origin": "null"}, b"origin refused", {}),
            ("no origin", no_origin, b"origin refused", {}),
            ("foreign host", own, b"loopback only", {"host": "evil.test"}),
        ]
        for name, headers, text, kwargs in table:
            with self.subTest(name):
                self.refused(svc, headers, 403, text, **kwargs)
        with self.subTest("guard before body"):
            self.refused(svc, without, 403, b"token refused", body=b"x" * 10000)
        self.assertEqual(origin, own["Origin"])
        self.assertEqual(ticks, [])

    def test_an_answer_body_is_checked_before_it_is_read(self):
        ticks = []
        svc = self.open(tick=lambda *args: ticks.append(args))
        table = [
            ("not json type", self.headers(svc, **{"Content-Type": "text/plain"}), b"json only", None),
            ("chunked", self.headers(svc, **{"Transfer-Encoding": "chunked"}), b"length required", None),
            ("too large", self.headers(svc), b"too large", b"x" * (service.MAX_ANSWER_BYTES + 1)),
        ]
        bad = [b"not json", self.body(extra=1), self.body(choices=[True, 0]), self.body(choices=[]),
               self.body(choices=[-1, 0]), self.body(key=""), b"[1, 2]",
               b'{"project_id": "owner/p00", "key": "k"}',
               b'{"project_id": "owner/p00", "project_id": "owner/p01", "key": "k", "choices": [0]}']
        table += [(f"bad {i}", self.headers(svc), b"bad answer", body) for i, body in enumerate(bad)]
        for name, headers, text, body in table:
            with self.subTest(name):
                status = {b"json only": 415, b"length required": 411, b"too large": 413}.get(text, 400)
                self.refused(svc, headers, status, text, body=body)
        self.assertEqual(ticks, [])
        self.assertEqual([i["key"] for i in view_of(svc)["inbox"]["open"]], [ITEM["key"]])

    def test_a_refused_tick_answers_with_its_reason_and_logs_it(self):
        key = ITEM["key"]
        table = [
            (answer.Refused(answer.CHANGED), 409, b"the prompt changed on the tracker\n",
             f"console: answer_refused owner/p00 {key} the prompt changed on the tracker"),
            (ForgeError("gh_failed", "gh: Server Error\n(HTTP 502)"), 502,
             b"the tracker refused the tick: gh_failed: gh: Server Error (HTTP 502)\n",
             f"console: answer_tick_failed owner/p00 {key} gh_failed: gh: Server Error (HTTP 502)"),
            (RuntimeError("boom"), 500, b"answer failed\n",
             "console: answer_failed RuntimeError: boom"),
        ]
        for error, status, text, line in table:
            with self.subTest(error=type(error).__name__):
                def tick(*args, error=error):
                    raise error

                svc = self.open(tick=tick)
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    got = self.assert_unchanged(svc, lambda: support.post_page(
                        svc.address, ANSWER, self.headers(svc), self.body()))
                self.assertEqual((got[0], got[2]), (status, text))
                self.assertIn(line, err.getvalue())
                self.assertEqual(
                    [i["key"] for i in view_of(svc)["inbox"]["open"]], [key])
                svc.close()

    def test_other_methods_on_the_answer_route_are_refused(self):
        svc = self.start()
        for method in ("GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, ANSWER)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "POST")


class GoalRouteTest(Case):
    def open(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        return self.start(**kwargs)

    def headers(self, svc, **extra):
        return self.own(svc, **{"Content-Type": "application/json", **extra})

    def goal_body(self, project_id="owner/p01", goal="make the importer resumable"):
        return json.dumps({"project_id": project_id, "goal": goal}).encode()

    def withdraw_body(self, sprint_id, project_id="owner/p01"):
        return json.dumps({"project_id": project_id, "sprint_id": sprint_id}).encode()

    @property
    def secrets_dir(self):
        return self.store.parent / "sprint-secrets"

    def sprints_of(self, svc, project_id):
        entries = []
        for entry in view_of(svc)["entries"]:
            entries += entry["projects"] if entry["type"] == "quiet_group" else [entry]
        (found,) = [e for e in entries if e["project_id"] == project_id]
        return found["sprints"]

    def post(self, svc, path, body, **extra):
        return support.post_page(svc.address, path, self.headers(svc, **extra), body)

    def refused(self, svc, path, body, status, text, **extra):
        got = self.assert_unchanged(svc, lambda: self.post(svc, path, body, **extra))
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got

    def test_a_goal_from_the_page_appends_one_event_and_shows_a_sprint(self):
        svc = self.open()
        before = support.log_rows(self.store)
        status, _, body = self.post(
            svc, GOAL, self.goal_body(goal="  make the importer resumable  "))
        self.assertEqual((status, body), (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        _, at, kind, project, payload = rows[-1]
        self.assertEqual((kind, project), ("goal.stated", "owner/p01"))
        payload = json.loads(payload)
        self.assertEqual(set(payload), {"goal", "sprint_id"})
        self.assertEqual(payload["goal"], "make the importer resumable")
        self.assertTrue(sprints.SPRINT_ID.fullmatch(payload["sprint_id"]))
        self.assertEqual(self.sprints_of(svc, "owner/p01"), [{
            "type": "sprint", "sprint_id": payload["sprint_id"],
            "goal": "make the importer resumable", "state": "drafting",
            "state_text": "drafting the brief", "stated_at": at,
            "age_text": "stated just now", "manager_text": "managers are not available on this host yet",
            "manager_state": "unavailable", "manager_until": None, "retry": False, "sessions": []}])
        self.assertEqual(view_of(svc)["recent_projects"][0], "owner/p01")

    def test_an_unregistered_empty_or_over_long_goal_is_refused_and_appends_nothing(self):
        svc = self.open()
        table = [
            ("owner/zz", "a goal", b"this project is not registered"),
            ("owner/p01", "", b"write the goal first"),
            ("owner/p01", " \n\t ", b"write the goal first"),
            ("owner/p01", "x" * 2001, b"a goal is at most 2000 characters"),
            ("owner/zz", "", b"this project is not registered"),
        ]
        for project_id, goal, text in table:
            with self.subTest(project_id=project_id, goal=goal[:5]):
                got = self.refused(
                    svc, GOAL, self.goal_body(project_id, goal), 409, text)
                self.assertEqual(got[1]["Content-Type"].split(";")[0], "text/plain")
        self.assertTrue(not self.secrets_dir.exists() or list(self.secrets_dir.iterdir()) == [])
        status, _, body = self.post(svc, GOAL, self.goal_body(goal="é" * 2000))
        self.assertEqual((status, body), (204, b""))

    def test_a_goal_body_is_checked_before_it_is_read(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", "g")
        cases = [
            (GOAL, "bad goal", service.MAX_GOAL_BYTES, [
                b"not json", b"[1]",
                json.dumps({"project_id": "owner/p01", "goal": "g", "extra": 1}).encode(),
                json.dumps({"project_id": "owner/p01", "goal": None}).encode(),
                json.dumps({"project_id": "", "goal": "g"}).encode(),
                b'{"project_id": "owner/p01", "project_id": "owner/p00", "goal": "g"}']),
            (WITHDRAW, "bad withdraw", service.MAX_WITHDRAW_BYTES, [
                b"not json", b"[1]",
                json.dumps({"project_id": "owner/p01", "sprint_id": sid, "extra": 1}).encode(),
                self.withdraw_body("../x"),
                json.dumps({"project_id": "owner/p01"}).encode(),
                json.dumps({"project_id": "", "sprint_id": sid}).encode(),
                ('{"project_id": "owner/p01", "project_id": "owner/p00", "sprint_id": "%s"}'
                 % sid).encode()]),
        ]
        for path, bad, limit, bodies in cases:
            valid = self.goal_body() if path == GOAL else self.withdraw_body(sid)
            with self.subTest(path=path, check="media"):
                self.refused(svc, path, valid, 415, b"json only",
                             **{"Content-Type": "text/plain"})
            with self.subTest(path=path, check="chunked"):
                self.refused(svc, path, valid, 411, b"length required",
                             **{"Transfer-Encoding": "chunked"})
            with self.subTest(path=path, check="too large"):
                self.refused(svc, path, b"x" * (limit + 1), 413, b"too large")
            for i, body in enumerate(bodies):
                with self.subTest(path=path, bad=i):
                    self.refused(svc, path, body, 400, bad.encode())
        self.assertEqual([s["sprint_id"] for s in self.sprints_of(svc, "owner/p01")], [sid])

    def test_a_goal_or_withdraw_without_the_token_or_from_another_origin_is_refused(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", "g")
        own = self.headers(svc)
        token = own["X-Console-Token"]
        without = {k: v for k, v in own.items() if k != "X-Console-Token"}
        no_origin = {k: v for k, v in own.items() if k != "Origin"}
        table = [
            ("no token", without, b"token refused", {}),
            ("wrong token", {**own, "X-Console-Token": "A" * 43}, b"token refused", {}),
            ("two tokens", {**own, "X-Console-Token": [token, token]}, b"token refused", {}),
            ("other origin", {**own, "Origin": "http://example.test"}, b"origin refused", {}),
            ("null origin", {**own, "Origin": "null"}, b"origin refused", {}),
            ("no origin", no_origin, b"origin refused", {}),
            ("foreign host", own, b"loopback only", {"host": "evil.test"}),
        ]
        for path, valid in ((GOAL, self.goal_body()), (WITHDRAW, self.withdraw_body(sid))):
            for name, headers, text, kwargs in table:
                with self.subTest(path=path, case=name):
                    got = self.assert_unchanged(svc, lambda: support.post_page(
                        svc.address, path, headers, valid, **kwargs))
                    self.assertEqual((got[0], got[2]), (403, text + b"\n"))
            with self.subTest(path=path, case="guard before body"):
                got = self.assert_unchanged(svc, lambda: support.post_page(
                    svc.address, path, without, b"x" * 100000))
                self.assertEqual((got[0], got[2]), (403, b"token refused\n"))
        self.assertEqual([s["sprint_id"] for s in self.sprints_of(svc, "owner/p01")], [sid])
        self.assertTrue((self.secrets_dir / sid).exists())

    def test_every_page_write_route_is_guarded_and_takes_only_post(self):
        svc = self.open()
        for path in (GOAL, WITHDRAW):
            for method in ("GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                with self.subTest(path=path, method=method):
                    status, headers, _ = support.request(svc.address, method, path)
                    self.assertEqual(status, 405)
                    self.assertEqual(headers["Allow"], "POST")

    def test_a_withdrawal_appends_one_row_hides_the_sprint_and_removes_its_secret(self):
        svc = self.open()
        sid = svc.state_goal("owner/p01", "make the importer resumable")
        for name, body in (("another project", self.withdraw_body(sid, "owner/p00")),
                           ("unknown sprint", self.withdraw_body("f" * 16))):
            with self.subTest(name):
                self.refused(svc, WITHDRAW, body, 409, b"this sprint is not open")
                self.assertEqual(
                    [s["sprint_id"] for s in self.sprints_of(svc, "owner/p01")], [sid])
                self.assertTrue((self.secrets_dir / sid).exists())
        before = support.log_rows(self.store)
        status, _, body = self.post(svc, WITHDRAW, self.withdraw_body(sid))
        self.assertEqual((status, body), (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        self.assertEqual(rows[-1][2:4], ("goal.withdrawn", "owner/p01"))
        self.assertEqual(json.loads(rows[-1][4]),
                         {"goal": "make the importer resumable", "sprint_id": sid})
        self.assertEqual(self.sprints_of(svc, "owner/p01"), [])
        self.assertFalse((self.secrets_dir / sid).exists())
        sentences = [m["sentence"] for m in view_of(svc)["digest"]["recent"]]
        self.assertIn("The goal for owner/p01 was withdrawn: make the importer resumable",
                      sentences)
        self.refused(svc, WITHDRAW, self.withdraw_body(sid), 409, b"this sprint is not open")

    def test_a_stated_sprint_survives_a_restart_and_a_withdrawn_one_does_not(self):
        svc = self.open()
        kept = svc.state_goal("owner/p01", "make the importer resumable")
        gone = svc.state_goal("owner/p01", "drop me")
        svc.withdraw_goal("owner/p01", gone)
        secret = (self.secrets_dir / kept).read_text()
        before = self.sprints_of(svc, "owner/p01")
        svc.close()
        rows = support.log_rows(self.store)
        second = self.start()
        after = self.sprints_of(second, "owner/p01")
        self.assertEqual([s["sprint_id"] for s in after], [kept])
        self.assertEqual(after[0]["goal"], "make the importer resumable")
        self.assertEqual(after[0]["stated_at"], before[0]["stated_at"])
        self.assertEqual((self.secrets_dir / kept).read_text(), secret)
        self.assertEqual([r for r in support.log_rows(self.store) if r[2].startswith("goal.")],
                         [r for r in rows if r[2].startswith("goal.")])

    def test_the_sprint_secret_is_owner_only_and_never_served(self):
        svc = self.open()
        response = open_stream(self, svc)
        next_frame(response)
        status, _, posted = self.post(svc, GOAL, self.goal_body())
        self.assertEqual((status, posted), (204, b""))
        frame = next_frame(response)
        for _ in range(20):
            if b"drafting the brief" in frame:
                break
            frame = next_frame(response)
        self.assertIn(b"drafting the brief", frame)
        (sid,) = [p.name for p in self.secrets_dir.iterdir()]
        self.assertEqual(stat.S_IMODE((self.secrets_dir / sid).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.secrets_dir.stat().st_mode), 0o700)
        secret = (self.secrets_dir / sid).read_text().strip()
        self.assertRegex(secret, r"^[A-Za-z0-9_-]{43}$")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.post(svc, GOAL, self.goal_body(goal="again"))
            self.post(svc, WITHDRAW, self.withdraw_body(sid))
        served = [posted, support.request(svc.address, "GET", "/")[2],
                  support.request(svc.address, "GET", "/api/state")[2], svc.view_bytes, frame]
        for blob in served:
            self.assertNotIn(secret.encode(), blob)
        self.assertNotIn(secret, err.getvalue())
        for row in support.log_rows(self.store):
            self.assertNotIn(secret, " ".join(map(str, row)))

    def test_a_failed_append_leaves_no_secret(self):
        svc = self.open()
        err = io.StringIO()
        with mock.patch.object(svc.log, "append", side_effect=sqlite3.OperationalError("boom")):
            with contextlib.redirect_stderr(err):
                status, _, body = self.post(svc, GOAL, self.goal_body())
        self.assertEqual((status, body), (500, b"goal failed\n"))
        self.assertIn("console: goal_failed OperationalError: boom", err.getvalue())
        self.assertTrue(not self.secrets_dir.exists() or list(self.secrets_dir.iterdir()) == [])


class TokenTest(Case):
    def test_the_token_is_created_once_and_kept(self):
        first = self.start()
        mode = stat.S_IMODE(self.token_file.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertRegex(self.token_file.read_text(), r"^[A-Za-z0-9_-]{43}\n$")
        token = first.page_token
        first.close()
        second = self.start()
        self.assertEqual(second.page_token, token)

    def test_the_page_carries_the_token_and_nothing_else_does(self):
        svc = self.start()
        token = svc.page_token.encode()
        _, _, page = support.request(svc.address, "GET", "/")
        self.assertIn(token, page)
        self.assertNotIn(b"__CONSOLE_TOKEN__", page)
        support.post_page(svc.address, LOOK, self.own(svc))
        self.assertNotIn(token, support.request(svc.address, "GET", "/api/state")[2])
        self.assertNotIn(token, svc.view_bytes)
        self.assertFalse([row for row in support.log_rows(self.store)
                          if token.decode() in " ".join(map(str, row))])

    def test_a_malformed_token_file_stops_the_service(self):
        self.token_file.parent.mkdir(parents=True)
        self.token_file.write_text("short\n")
        with self.assertRaises(write_guard.TokenError):
            service.ConsoleService(self.store, self.registry, port=0)
        self.assertFalse(self.store.exists())

    def test_console_main_reports_an_unusable_token(self):
        self.token_file.parent.mkdir(parents=True)
        self.token_file.write_text("short\n")
        err = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(service, "default_store", return_value=self.store))
            stack.enter_context(
                mock.patch.object(service, "default_registry", return_value=self.registry))
            stack.enter_context(mock.patch.object(
                service.ConsoleService, "start", side_effect=AssertionError("started")))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = console.main(["--port", "0"])
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith("console: page token unusable: "))


class GuardTest(unittest.TestCase):
    def test_the_refusal_table(self):
        token = "t" * 43
        origin, no, bad = (403, "origin refused"), None, (403, "token refused")
        table = [
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [token], no),
            ("localhost:9", ["http://localhost:9"], [token], no),
            ("127.0.0.1:9", [], [token], origin),
            ("127.0.0.1:9", ["http://example.test"], [token], origin),
            ("127.0.0.1:9", ["http://127.0.0.1:9"] * 2, [token], origin),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [], bad),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], ["u" * 43], bad),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [token, token], bad),
        ]
        for host, origins, tokens, expected in table:
            with self.subTest(origins=origins, tokens=tokens):
                self.assertEqual(write_guard.refusal(host, origins, tokens, token), expected)


if __name__ == "__main__":
    unittest.main()
