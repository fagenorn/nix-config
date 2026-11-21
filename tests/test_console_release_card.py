"""The release card (#1401): its rows, fold, host store reader and `release-card post`."""

import contextlib
import http.server
import io
import json
import os
import pwd
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, release_card, service
from agent_tools.console.event_log import Event, EventLog
from agent_tools.release import release_profile
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

A = "2026-11-11T00:00:00.000000+00:00"
B = "2026-11-11T00:00:01.000000+00:00"
COMMIT = "a" * 40
VERSION = "v1.2.0"


def posted(seq, commit=COMMIT, version=VERSION, **extra):
    return Event(seq, A, event_log.RELEASE_CARD_POSTED, None,
                 {"commit": commit, "version": version, **extra})


def answered(seq, payload):
    return Event(seq, B, event_log.RELEASE_CARD_ANSWERED, None, payload)


class FoldTest(unittest.TestCase):
    def test_a_posted_card_is_open_and_the_owners_approve_approves_only_its_candidate(self):
        first = release_card.cards([posted(1)])
        self.assertEqual(first, {1: release_card.Card(1, COMMIT, VERSION, A, "open")})
        second = release_card.cards([answered(2, {"card": 1, "answer": "approve"})], first)
        self.assertEqual(second[1].state, "approved")
        self.assertEqual(first[1].state, "open")
        self.assertTrue(release_card.approved(second, COMMIT, VERSION))
        self.assertFalse(release_card.approved(second, COMMIT, "v1.2.1"))
        self.assertFalse(release_card.approved(second, "b" * 40, VERSION))

    def test_a_decline_a_second_answer_and_every_malformed_row_approve_nothing(self):
        declined = release_card.cards([posted(1), answered(2, {"card": 1, "answer": "decline"}),
                                       answered(3, {"card": 1, "answer": "approve"})])
        self.assertEqual(declined[1].state, "declined")
        self.assertFalse(release_card.approved(declined, COMMIT, VERSION))
        for payload in ({"card": 1, "answer": "approve", "by": "x@y.z"},
                        {"card": 1, "answer": "yes"},
                        {"card": 9, "answer": "approve"},
                        {"card": True, "answer": "approve"}):
            with self.subTest(payload=payload):
                folded = release_card.cards([posted(1), answered(2, payload)])
                self.assertFalse(release_card.approved(folded, COMMIT, VERSION))
                self.assertEqual(folded[1].state, "open")
        for row in (posted(1, commit="A" * 40), posted(1, version="latest"),
                    posted(1, title="t")):
            with self.subTest(row=row.payload):
                folded = release_card.cards([row, answered(2, {"card": 1, "answer": "approve"})])
                self.assertEqual(folded, {})
                self.assertFalse(release_card.approved(
                    folded, row.payload["commit"], row.payload["version"]))

    def test_standing_is_the_newest_open_or_approved_card_of_the_pair(self):
        folded = release_card.cards([posted(1), posted(2), answered(3, {"card": 2, "answer": "decline"})])
        self.assertEqual(release_card.standing(folded, COMMIT, VERSION).card_id, 1)
        self.assertIsNone(release_card.standing(folded, COMMIT, "v9.9.9"))


class ShapeTest(unittest.TestCase):
    def test_the_card_accepts_exactly_the_pairs_the_release_driver_accepts(self):
        versions = ("v1.2.0", "v0.1.0", "v" + "1" * 70 + ".0.0", "latest", "1.2.0", "v1.2",
                    "v01.2.0", "-v1", "")
        for version in versions:
            for commit in (COMMIT, "A" * 40, "a" * 39):
                with self.subTest(version=version, commit=commit[:3] + str(len(commit))):
                    driver = release_profile.candidate_problem(
                        {"version": version, "commit": commit, "title": "t", "notes": ""}) is None
                    self.assertEqual(release_card.valid_pair(commit, version), driver)
                    if driver:
                        release_card.posted_row(commit, version)
                    else:
                        with self.assertRaises(ValueError):
                            release_card.posted_row(commit, version)
        self.assertEqual(release_card.posted_row(COMMIT, VERSION),
                         ("release_card.posted", None, {"commit": COMMIT, "version": VERSION}))
        self.assertFalse(release_card.valid_pair(1, VERSION))

    def test_rows_and_parsers_refuse_what_the_fold_ignores(self):
        for card, answer in ((0, "approve"), (True, "approve"), (1, "yes")):
            with self.subTest(card=card, answer=answer), self.assertRaises(ValueError):
                release_card.answered_row(card, answer)
        self.assertEqual(release_card.answered_row(4, "decline"),
                         ("release_card.answered", None, {"card": 4, "answer": "decline"}))
        good = json.dumps({"commit": COMMIT, "version": VERSION}).encode()
        self.assertEqual(release_card.parse_post(good), (COMMIT, VERSION))
        for body in (json.dumps({"commit": COMMIT, "version": VERSION, "x": 1}).encode(),
                     json.dumps({"commit": COMMIT}).encode(),
                     b'{"commit": "%s", "commit": "%s", "version": "v1.2.0"}'
                     % (COMMIT.encode(), COMMIT.encode()),
                     b'{"commit": NaN, "version": "v1.2.0"}', b"[]", b"\xff"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                release_card.parse_post(body)
        self.assertEqual(release_card.parse_answer(b'{"card": 3, "answer": "approve"}'),
                         (3, "approve"))
        for body in (b'{"card": 0, "answer": "approve"}', b'{"card": true, "answer": "approve"}',
                     b'{"card": 3, "answer": "Approve"}', b'{"card": 3}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                release_card.parse_answer(body)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_store_reader_reads_what_the_log_wrote_and_refuses_an_absent_or_older_store(self):
        path = self.tmp / "events.sqlite3"
        log = EventLog(path)
        (row,) = log.append([release_card.posted_row(COMMIT, VERSION)])
        log.append([release_card.answered_row(row.seq, release_card.APPROVE)])
        log.append([(event_log.PERMIT_LANDED, None, {"x": 1})])
        log.close()
        found = release_card.store_cards(path)
        self.assertEqual([(c.card_id, c.state) for c in found.values()], [(row.seq, "approved")])
        missing = self.tmp / "missing.sqlite3"
        with self.assertRaises(release_card.Unreadable):
            release_card.store_cards(missing)
        self.assertFalse(missing.exists())
        older = self.tmp / "older.sqlite3"
        connection = sqlite3.connect(older)
        connection.execute(f"PRAGMA user_version = {event_log.SCHEMA_VERSION - 1}")
        connection.close()
        with self.assertRaises(release_card.Unreadable):
            release_card.store_cards(older)

    def test_an_approval_older_than_the_retention_window_does_not_count(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        path = self.tmp / "events.sqlite3"
        log = EventLog(path, clock=lambda: start.isoformat(timespec="microseconds"))
        (row,) = log.append([release_card.posted_row(COMMIT, VERSION)])
        log.append([release_card.answered_row(row.seq, release_card.APPROVE)])
        log.close()
        inside = release_card.store_cards(path, now=start + timedelta(days=89))
        outside = release_card.store_cards(path, now=start + timedelta(days=91))
        self.assertTrue(release_card.approved(inside, COMMIT, VERSION))
        self.assertFalse(release_card.approved(outside, COMMIT, VERSION))

    def test_the_host_store_is_the_passwd_home_not_the_callers_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            store = release_card.host_store()
        self.assertEqual(store, Path(pwd.getpwuid(os.getuid()).pw_dir)
                         / ".agents/state/console/events.sqlite3")
        self.assertNotIn(self.tmp, store.parents)
        self.assertEqual(release_card.DEFAULT_PORT, service.DEFAULT_PORT)


class Recorder(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.server.seen.append((self.command, self.path, dict(self.headers),
                                 self.rfile.read(length)))
        status, text = self.server.reply
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PostTest(unittest.TestCase):
    def serve(self, status, text):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        server.seen, server.reply = [], (status, text)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = release_card.main(list(argv))
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()

    def test_release_card_post_sends_one_plain_request_and_reports_the_card(self):
        server = self.serve(200, '{"card": 3, "state": "open"}')
        port = str(server.server_address[1])
        code, out, _ = self.run_main("post", "--commit", COMMIT, "--version", VERSION,
                                     "--port", port)
        self.assertEqual((code, out), (0, "release-card: card 3 is open\n"))
        ((method, path, headers, body),) = server.seen
        self.assertEqual((method, path), ("POST", "/api/release-card"))
        self.assertNotIn("Origin", headers)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"commit": COMMIT, "version": VERSION})
        server.seen.clear()
        server.reply = (409, "nope")
        code, _, err = self.run_main("post", "--commit", COMMIT, "--version", VERSION,
                                     "--port", port)
        self.assertEqual((code, err), (1, "release-card: refused 409: nope\n"))
        probe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        closed = str(probe.server_address[1])
        probe.server_close()
        code, _, err = self.run_main("post", "--commit", COMMIT, "--version", VERSION,
                                     "--port", closed)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("release-card: console unreachable on 127.0.0.1:"), err)
        server.seen.clear()
        for argv in (("post", "--commit", "ABC", "--version", VERSION, "--port", port),
                     ("post", "--commit", COMMIT, "--vers", VERSION, "--port", port)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(*argv)[0], 2)
        self.assertEqual(server.seen, [])


if __name__ == "__main__":
    unittest.main()
