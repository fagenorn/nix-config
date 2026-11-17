"""The console's pictures (#1089).

Run: just agent-workflow-tests
"""

import ast
import contextlib
import hashlib
import http.client
import io
import json
import os
import socket
import stat
import struct
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log, pictures, service, sprint, sprints, write_guard
from agent_tools.console.event_log import PICTURE_STORED, Event
from agent_tools.console.pictures import SIGNATURE

from . import accounts_sandbox
from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_messages import GOAL_TEXT, PARTS
from .test_console_questions import APPROVE, BRIEF, JSON
from .test_console_reports import CHECKED, REPORT
from .test_console_sprint_command import run_sprint
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

from .console_test_support import JPEG, PIXEL, WIDE  # noqa: F401 -- fixtures shared with the inbox suite (#1112)
from .console_test_support import get_page as get


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width=1, height=1, depth=8, colour=6, compression=0, filter_=0, interlace=0, pad=b"") -> bytes:
    header = struct.pack(">IIBBBBB", width, height, depth, colour, compression, filter_, interlace)
    return SIGNATURE + chunk(b"IHDR", header) + chunk(b"IEND", b"") + pad


def padded(total: int) -> bytes:
    return PIXEL[:-12] + chunk(b"paDd", b"\0" * (total - len(PIXEL) - 12)) + PIXEL[-12:]


def age(path, seconds):
    os.utime(path, (time.time() - seconds,) * 2)


class PngCheckTest(unittest.TestCase):
    def test_a_valid_header_passes_whatever_follows(self):
        for body in (PIXEL, WIDE, padded(4096), png(), png()[:33], png(pad=b"junk"),
                     png(colour=3, depth=1), png(interlace=1)):
            with self.subTest(length=len(body)):
                pictures.checked_png(body)

    def test_each_bad_body_names_its_reason(self):
        good = png()
        bad_crc = good[:32] + bytes([good[32] ^ 0xFF]) + good[33:]
        length_12 = good[:8] + struct.pack(">I", 12) + good[12:]
        not_ihdr = good[:12] + b"IDAT" + good[16:29] + struct.pack(">I", zlib.crc32(b"IDAT" + good[16:29])) + good[33:]
        rows = [
            ("signature", b"GIF89a" + b"\0" * 40, pictures.SIGNATURE_WRONG),
            ("jpeg", JPEG, pictures.SIGNATURE_WRONG),
            ("empty", b"", pictures.SIGNATURE_WRONG),
            ("cut-20", good[:20], pictures.HEADER_SHORT),
            ("cut-8", good[:8], pictures.HEADER_SHORT),
            ("bad-crc", bad_crc, pictures.HEADER_UNREADABLE),
            ("length-12", length_12, pictures.HEADER_UNREADABLE),
            ("not-ihdr", not_ihdr, pictures.HEADER_UNREADABLE),
            ("width-0", png(width=0), pictures.HEADER_UNREADABLE),
            ("height-huge", png(height=2 ** 31), pictures.HEADER_UNREADABLE),
            ("depth", png(colour=2, depth=4), pictures.HEADER_UNREADABLE),
            ("compression", png(compression=1), pictures.HEADER_UNREADABLE),
            ("filter", png(filter_=1), pictures.HEADER_UNREADABLE),
            ("interlace", png(interlace=2), pictures.HEADER_UNREADABLE),
        ]
        for name, body, reason in rows:
            with self.subTest(name):
                with self.assertRaises(pictures.NotPng) as caught:
                    pictures.checked_png(body)
                self.assertEqual(str(caught.exception), reason)


class PictureStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dir = self.root / "state/console/pictures"

    def test_a_store_writes_once_by_hash_with_its_modes(self):
        self.dir.mkdir(parents=True, mode=0o755)
        os.chmod(self.dir, 0o755)
        picture_id = hashlib.sha256(PIXEL).hexdigest()
        self.assertEqual(pictures.store(self.dir, PIXEL), (picture_id, True))
        self.assertEqual((self.dir / picture_id).read_bytes(), PIXEL)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir / picture_id).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(os.listdir(self.dir), [picture_id])

    def test_present_answers_only_for_a_regular_file_and_changes_nothing(self):
        picture_id, _ = pictures.store(self.dir, PIXEL)
        age(self.dir / picture_id, 2 * 86400)
        before = os.stat(self.dir / picture_id).st_mtime
        os.symlink(self.dir / picture_id, self.dir / ("e" * 64))
        (self.dir / ("c" * 64)).mkdir()
        self.assertTrue(pictures.present(self.dir, picture_id))
        self.assertEqual(os.stat(self.dir / picture_id).st_mtime, before)
        for name in ("e" * 64, "c" * 64, "d" * 64):
            with self.subTest(name[0]):
                self.assertFalse(pictures.present(self.dir, name))
        with self.assertRaises(ValueError):
            pictures.present(self.dir, "x")

    def test_a_second_store_writes_nothing_and_renews_the_age(self):
        picture_id, _ = pictures.store(self.dir, PIXEL)
        fd = os.open(self.dir / picture_id, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        inode = os.fstat(fd).st_ino
        age(self.dir / picture_id, 2 * 86400)
        self.assertEqual(pictures.store(self.dir, PIXEL), (picture_id, False))
        self.assertEqual(os.listdir(self.dir), [picture_id])
        self.assertFalse([n for n in os.listdir(self.dir) if n.startswith(".incoming-")])
        self.assertLess(time.time() - os.stat(self.dir / picture_id).st_mtime, 60)
        self.assertEqual(os.stat(self.dir / picture_id).st_ino, inode)
        self.assertEqual(os.fstat(fd).st_nlink, 1)

    def test_a_store_over_a_non_file_raises(self):
        picture_id = hashlib.sha256(PIXEL).hexdigest()
        (self.dir / picture_id).mkdir(parents=True)
        with self.assertRaises(OSError):
            pictures.store(self.dir, PIXEL)

    def test_read_answers_only_a_regular_file_by_a_valid_id(self):
        picture_id, _ = pictures.store(self.dir, PIXEL)
        secret = self.root / "secret"
        secret.write_bytes(b"secret")
        os.symlink(secret, self.dir / ("1" * 64))
        self.assertEqual(pictures.read(self.dir, picture_id), PIXEL)
        self.assertIsNone(pictures.read(self.dir, "0" * 64))
        self.assertIsNone(pictures.read(self.dir, "1" * 64))
        for bad in ("..", "../x", picture_id.upper(), picture_id[:-1], picture_id + "0", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pictures.read(self.dir, bad)

    def test_read_refuses_a_named_pipe_without_blocking(self):
        picture_id = "2" * 64
        self.dir.mkdir(parents=True, exist_ok=True)
        os.mkfifo(self.dir / picture_id)
        done = []
        reader = threading.Thread(
            target=lambda: done.append(pictures.read(self.dir, picture_id)), daemon=True)
        reader.start()
        reader.join(5)
        if reader.is_alive():
            # unblock the stuck open so the thread ends, then fail
            fd = os.open(self.dir / picture_id, os.O_WRONLY)
            os.close(fd)
            reader.join(5)
            self.fail("read blocked on a named pipe")
        self.assertEqual(done, [None])

    def test_references_come_from_pictures_lists_of_other_rows(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        events = [
            Event(1, "t", "report.x", None, {"pictures": [a, "bad", b.upper()]}),
            Event(2, "t", PICTURE_STORED, "o/p", {"picture": c, "sprint_id": "s", "pictures": [c]}),
            Event(3, "t", "other", None, {"pictures": a}),
        ]
        self.assertEqual(pictures.referenced(events), frozenset({a}))

    def test_an_inbox_rows_picture_entries_reference_their_ids(self):
        d = "d" * 64
        event = Event(4, "t", "inbox.changed", "o/p", {"pictures": [
            {"id": d, "line": "x.png", "pair": None}, {"id": "bad"}, {"line": "y"}]})
        self.assertEqual(pictures.referenced([event]), frozenset({d}))

    def test_the_stored_kind_is_the_event_logs_and_is_not_kept(self):
        a = "a" * 64
        self.assertEqual(pictures.entry("o/p", "s" * 16, a),
                         (event_log.PICTURE_STORED, "o/p", {"picture": a, "sprint_id": "s" * 16}))
        self.assertEqual(event_log.PICTURE_STORED, "picture.stored")
        self.assertNotIn(event_log.PICTURE_STORED, event_log.KEPT_KINDS)

    def test_the_sweep_removes_only_old_unreferenced_entries(self):
        now = 2_000_000_000.0
        self.dir.mkdir(parents=True)
        for name, seconds in (("old", 86400 + 60), ("old_kept", 86400 + 60), ("fresh", 60),
                              ("edge", 86400), (".incoming-x", 86400 + 60)):
            (self.dir / name).write_bytes(b"x")
            os.utime(self.dir / name, (now - seconds,) * 2)
        (self.dir / "sub").mkdir()
        os.utime(self.dir / "sub", (now - 86400 - 60,) * 2)
        self.assertEqual(pictures.sweep(self.dir, {"old_kept"}, now), 2)
        self.assertEqual(set(os.listdir(self.dir)), {"old_kept", "fresh", "edge", "sub"})
        self.assertEqual(pictures.sweep(self.root / "missing", set(), now), 0)
        plain = self.root / "plain"
        plain.write_bytes(b"x")
        with self.assertRaises(OSError):
            pictures.sweep(plain, set(), now)


class SandboxTest(Case):
    def test_every_path_this_module_uses_is_temporary(self):
        sandbox = accounts_sandbox.root()
        self.assertIsNotNone(sandbox)
        self.assertTrue(Path(os.environ["HOME"]).resolve().is_relative_to(sandbox.resolve()))
        temporary = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(self.store.resolve().is_relative_to(temporary))
        self.assertTrue(self.registry.resolve().is_relative_to(temporary))


PICTURE = "/api/picture"
ROOT = Path(__file__).resolve().parent.parent


class PictureCase(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def sprint(self, svc):
        return svc.state_goal("owner/p01", "make the importer resumable")

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def approved(self, svc, project_id="owner/p01"):
        sid = svc.state_goal(project_id, GOAL_TEXT)
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "brief": PARTS}).encode()
        self.assertEqual(support.post_page(svc.address, BRIEF, JSON, body)[0], 200)
        body = json.dumps({"project_id": project_id, "sprint_id": sid, "version": 1}).encode()
        self.assertEqual(
            support.post_page(svc.address, "/api/approve", self.own(svc, **JSON), body)[0], 204)
        return sid

    def write(self, name, data):
        path = self.store.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def secret_file(self, sid, text=None):
        return self.write("mine-secret", (text or self.secret(sid)).encode())

    def send(self, svc, sid, secret, body, **extra):
        headers = {"Content-Type": "image/png", "X-Console-Sprint": sid,
                   "X-Console-Secret": secret, **extra}
        headers = {name: value for name, value in headers.items() if value is not None}
        return support.post_page(svc.address, PICTURE, headers, body)

    def send_headers_only(self, svc, headers, length):
        connection = http.client.HTTPConnection(*svc.address, timeout=5)
        try:
            connection.putrequest("POST", PICTURE, skip_host=True)
            connection.putheader("Host", f"{svc.address[0]}:{svc.address[1]}")
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(length))
            connection.endheaders()
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def send_short(self, svc, sid, secret, body, length):
        """Send `body` under a larger Content-Length, then close the sending side."""
        with socket.create_connection(svc.address, timeout=5) as sock:
            sock.sendall((f"POST {PICTURE} HTTP/1.1\r\nHost: {svc.address[0]}:{svc.address[1]}\r\n"
                          f"Content-Type: image/png\r\nX-Console-Sprint: {sid}\r\n"
                          f"X-Console-Secret: {secret}\r\nContent-Length: {length}\r\n\r\n"
                          ).encode() + body)
            sock.shutdown(socket.SHUT_WR)
            answer = b""
            while chunk_ := sock.recv(4096):
                answer += chunk_
        return answer

    @property
    def pictures_dir(self):
        return self.store.parent / "pictures"

    def entries(self):
        return sorted(os.listdir(self.pictures_dir)) if self.pictures_dir.exists() else []

    def rows(self, kind):
        return [(json.loads(row[4]), row[3]) for row in support.log_rows(self.store)
                if row[2] == kind]


class PictureWriteTest(PictureCase):
    def test_a_png_with_the_secret_is_stored_once_by_its_hash(self):
        svc = self.open()
        sid = self.sprint(svc)
        status, headers, body = self.send(svc, sid, self.secret(sid), PIXEL)
        picture_id = hashlib.sha256(PIXEL).hexdigest()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body, json.dumps({"picture": picture_id}, separators=(",", ":")).encode())
        self.assertEqual(self.entries(), [picture_id])
        self.assertEqual((self.pictures_dir / picture_id).read_bytes(), PIXEL)
        self.assertEqual(stat.S_IMODE(os.stat(self.pictures_dir / picture_id).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.pictures_dir).st_mode), 0o700)
        self.assertEqual(self.rows(PICTURE_STORED),
                         [({"picture": picture_id, "sprint_id": sid}, "owner/p01")])

    def test_sending_it_again_returns_the_same_id_and_writes_no_second_file(self):
        svc = self.open()
        sid = self.sprint(svc)
        first = self.send(svc, sid, self.secret(sid), PIXEL)
        picture_id = hashlib.sha256(PIXEL).hexdigest()
        fd = os.open(self.pictures_dir / picture_id, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        inode = os.fstat(fd).st_ino
        second = self.send(svc, sid, self.secret(sid), PIXEL)
        self.assertEqual((second[0], second[2]), (200, first[2]))
        self.assertEqual(self.entries(), [picture_id])
        self.assertEqual(len(self.rows(PICTURE_STORED)), 2)
        self.assertEqual(os.stat(self.pictures_dir / picture_id).st_ino, inode)
        self.assertEqual(os.fstat(fd).st_nlink, 1)

    def test_a_picture_of_exactly_two_mib_is_taken(self):
        svc = self.open()
        sid = self.sprint(svc)
        self.assertEqual(self.send(svc, sid, self.secret(sid), padded(2097152))[0], 200)

    def test_each_refused_send_leaves_no_file_and_no_row(self):
        svc = self.open()
        sid = self.sprint(svc)
        secret = self.secret(sid)
        own = f"http://127.0.0.1:{svc.address[1]}"
        rows = [
            ("own-origin", lambda: self.send(svc, sid, secret, PIXEL, Origin=own),
             403, "origin refused"),
            ("foreign-origin", lambda: self.send(svc, sid, secret, PIXEL, Origin="http://evil.example"),
             403, "origin refused"),
            ("json", lambda: self.send(svc, sid, secret, PIXEL, **{"Content-Type": "application/json"}),
             415, "png only"),
            ("too-large", lambda: self.send_headers_only(
                svc, {"Content-Type": "image/png", "X-Console-Sprint": sid,
                      "X-Console-Secret": secret}, 2097153),
             413, "too large"),
            ("no-sprint", lambda: self.send(svc, sid, secret, PIXEL, **{"X-Console-Sprint": None}),
             400, "bad picture"),
            ("bad-sprint", lambda: self.send(svc, sid, secret, PIXEL, **{"X-Console-Sprint": "ABC"}),
             400, "bad picture"),
            ("two-secrets", lambda: self.send(svc, sid, secret, PIXEL,
                                              **{"X-Console-Secret": [secret, secret]}),
             400, "bad picture"),
            ("no-secret", lambda: self.send(svc, sid, secret, PIXEL, **{"X-Console-Secret": None}),
             400, "bad picture"),
            ("unknown-sprint", lambda: self.send(svc, "e" * 16, secret, PIXEL),
             409, "this sprint is not open"),
            ("wrong-secret", lambda: self.send(svc, sid, "A" * 43, PIXEL),
             403, "secret refused"),
            ("signature", lambda: self.send(svc, sid, secret, b"GIF89a" + b"\0" * 40),
             400, pictures.SIGNATURE_WRONG),
            ("renamed-jpeg", lambda: self.send(svc, sid, secret, JPEG),
             400, pictures.SIGNATURE_WRONG),
            ("truncated", lambda: self.send(svc, sid, secret, png()[:20]),
             400, pictures.HEADER_SHORT),
            ("empty", lambda: self.send(svc, sid, secret, b""),
             400, pictures.SIGNATURE_WRONG),
        ]
        for name, act, status, text in rows:
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                got = self.assert_unchanged(svc, act)
                self.assertEqual(got[0], status)
                self.assertEqual(got[1]["Content-Type"], "text/plain")
                self.assertEqual(got[2], text.encode() + b"\n")
                self.assertEqual(self.entries(), [])

    def test_an_incomplete_body_is_refused_and_leaves_no_file_and_no_row(self):
        svc = self.open()
        sid = self.sprint(svc)
        header = png()[:33]
        self.assertIsNone(pictures.checked_png(header))
        with contextlib.redirect_stderr(io.StringIO()):
            answer = self.assert_unchanged(
                svc, lambda: self.send_short(svc, sid, self.secret(sid), header, len(header) + 50))
        self.assertTrue(answer.startswith(b"HTTP/1.0 400") or answer.startswith(b"HTTP/1.1 400"),
                        answer)
        self.assertTrue(answer.endswith(b"bad picture\n"), answer)
        self.assertEqual(self.entries(), [])

    def test_the_secret_appears_in_no_stderr_line_or_answer(self):
        svc = self.open()
        sid = self.sprint(svc)
        secret = self.secret(sid)
        wrong = "A" * 43
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            first = self.send(svc, sid, wrong, PIXEL)
            second = self.send(svc, sid, secret, JPEG)
        text = captured.getvalue()
        self.assertIn(f"console: picture_refused {sid} secret refused", text)
        self.assertIn(f"console: picture_refused {sid} not a PNG:", text)
        for secret_value in (secret, wrong):
            self.assertNotIn(secret_value, text)
            self.assertNotIn(secret_value.encode(), first[2] + second[2])

    def test_other_methods_on_the_write_route_are_refused(self):
        svc = self.open()
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method):
                status, headers, _ = support.request(svc.address, method, PICTURE)
                self.assertEqual((status, headers["Allow"]), (405, "POST"))


class PictureRoundTest(PictureCase):
    Q = {"question": "Which layout reads better?", "blocks": "the card slice",
         "options": ["the old", "the new"], "recommended": "the new"}

    def stored(self, svc, sid, data):
        status, _, answer = self.send(svc, sid, self.secret(sid), data)
        self.assertEqual(status, 200)
        return json.loads(answer)["picture"]

    def ask(self, svc, sid, round_):
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "round": round_}).encode()
        return support.post_page(svc.address, "/api/ask", JSON, body)

    def round_with(self, *members):
        return {"questions": [{**self.Q, "pictures": list(members)}]}

    def own_round(self, svc):
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        b = self.stored(svc, sid, WIDE)
        members = [{"picture": a, "line": "the card before", "pair": "before"},
                   {"picture": b, "line": "the card after", "pair": "after"}]
        status, _, answer = self.ask(svc, sid, self.round_with(*members))
        self.assertEqual(status, 200, answer)
        return sid, a, b, members

    def test_a_round_with_its_own_pictures_stores_their_ids_and_lines(self):
        svc = self.open()
        sid, a, b, members = self.own_round(svc)
        ((payload, _),) = self.rows("questions.asked")
        self.assertEqual(payload["questions"][0]["pictures"], members)
        self.assertEqual(payload["pictures"], [a, b])
        self.assertEqual(
            view_of(svc)["inbox"]["open"][0]["pictures"],
            [{"id": a, "line": "the card before", "pair": "before"},
             {"id": b, "line": "the card after", "pair": "after"}])

    def test_a_question_naming_screenshots_with_no_picture_is_refused_and_appends_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        rows = support.log_rows(self.store)
        ask = "Judge the screenshots in /tmp/shots"
        status, _, answer = self.ask(svc, sid, {"questions": [{**self.Q, "question": ask}]})
        self.assertEqual((status, answer.strip()), (
            409, sprints.LOOK_WITHOUT_PICTURE.format(n=1, ask=ask).encode()))
        self.assertIn(b"pictures", answer)
        for member in ("question", "context"):
            for text in ("Is card.png right?", "Look in /x/screenshots/y"):
                with self.subTest(member=member, text=text):
                    got = self.ask(svc, sid, {"questions": [{**self.Q, member: text}]})
                    self.assertEqual(got[0], 409)
        self.assertEqual(support.log_rows(self.store), rows)
        status, _, answer = self.ask(svc, sid, self.round_with_question(
            ask, {"picture": a, "line": "the shots folder"}))
        self.assertEqual(status, 200, answer)
        self.assertEqual(len(self.rows("questions.asked")), 1)

    def test_a_question_naming_nothing_to_look_at_is_accepted_without_pictures(self):
        svc = self.open()
        sid = self.approved(svc)
        status, _, answer = self.ask(svc, sid, {"questions": [self.Q]})
        self.assertEqual(status, 200, answer)

    def round_with_question(self, ask, *members):
        return {"questions": [{**self.Q, "question": ask, "pictures": list(members)}]}

    def test_a_dry_run_with_withheld_files_does_not_refuse_the_look_rule(self):
        svc = self.open()
        sid = self.approved(svc)
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "dry_run": True,
                           "round": {"questions": [{**self.Q, "question": "Judge the screenshots"}]}}
                          ).encode()
        status, _, answer = support.post_page(svc.address, "/api/ask", JSON, body)
        self.assertEqual((status, json.loads(answer)), (200, {"questions": 1}))

    def test_a_dry_run_checks_a_round_and_writes_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        rows = support.log_rows(self.store)

        def dry(round_, **changes):
            body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "round": round_,
                               "dry_run": True, **changes}).encode()
            return support.post_page(svc.address, "/api/ask", JSON, body)
        status, _, answer = dry(self.round_with({"picture": a, "line": "the header"}))
        self.assertEqual((status, json.loads(answer)), (200, {"questions": 1}))
        status, _, answer = dry(self.round_with({"picture": "f" * 64, "line": "the header"}))
        self.assertEqual((status, answer.strip()),
                         (409, sprints.PICTURE_UNKNOWN.format(n=1, m=1).encode()))
        self.assertEqual(dry(self.round_with(), dry_run=False)[0], 400)
        self.assertEqual(support.log_rows(self.store), rows)

    def test_each_bad_picture_list_is_refused_with_its_reason_and_appends_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        other = self.approved(svc, "owner/p00")
        w = self.stored(svc, other, WIDE)
        gone = self.stored(svc, sid, padded(4096))
        os.unlink(self.pictures_dir / gone)
        before = os.stat(self.pictures_dir / a).st_mtime
        mine = {"picture": a, "line": "one"}
        unknown = {"picture": "f" * 64, "line": "one"}
        cases = (
            ("shape", "x", sprints.PICTURES_SHAPE.format(n=1)),
            ("too many", [mine] * 9, sprints.TOO_MANY_PICTURES.format(n=1)),
            ("file key", [{**mine, "file": "x"}], sprints.PICTURE_SHAPE.format(n=1, m=1)),
            ("no line", [{"picture": a}], sprints.PICTURE_SHAPE.format(n=1, m=1)),
            ("empty line", [{**mine, "line": ""}],
             sprints.PICTURE_MEMBER.format(n=1, m=1, member="line")),
            ("long line", [{**mine, "line": "l" * 141}],
             sprints.LINE_TOO_LONG.format(n=1, m=1)),
            ("pair twice", [{**mine, "pair": "before"}, {**mine, "pair": "before"}],
             sprints.PAIR_TWICE.format(n=1, pair="before")),
            ("unknown", [unknown], sprints.PICTURE_UNKNOWN.format(n=1, m=1)),
            ("foreign", [{"picture": w, "line": "one"}],
             sprints.PICTURE_FOREIGN.format(n=1, m=1)),
            ("gone", [{"picture": gone, "line": "one"}],
             sprints.PICTURE_UNKNOWN.format(n=1, m=1)),
            ("second unknown", [mine, unknown], sprints.PICTURE_UNKNOWN.format(n=1, m=2)),
        )
        for name, listed, reason in cases:
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                status, _, body = self.assert_unchanged(
                    svc, lambda: self.ask(svc, sid, {"questions": [{**self.Q, "pictures": listed}]}))
                self.assertEqual((status, body), (409, reason.encode() + b"\n"))
        self.assertEqual(self.rows("questions.asked"), [])
        self.assertEqual(os.stat(self.pictures_dir / a).st_mtime, before)

    def test_eight_pictures_with_140_character_lines_are_taken(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        status, _, answer = self.ask(
            svc, sid, self.round_with(*[{"picture": a, "line": "l" * 140}] * 8))
        self.assertEqual(status, 200, answer)
        ((payload, _),) = self.rows("questions.asked")
        self.assertEqual(len(payload["questions"][0]["pictures"]), 8)
        self.assertEqual(payload["pictures"], [a])

    def test_a_round_picture_outlives_the_sweep(self):
        svc = self.open()
        sid, a, b, _ = self.own_round(svc)
        age(self.pictures_dir / a, 2 * 86400)
        svc.retain()
        self.assertIn(a, self.entries())

    def test_a_round_without_pictures_logs_the_old_row(self):
        svc = self.open()
        sid = self.approved(svc)
        status, _, answer = self.ask(svc, sid, {"questions": [self.Q]})
        self.assertEqual(status, 200, answer)
        ((payload, _),) = self.rows("questions.asked")
        self.assertEqual(set(payload), {"sprint_id", "goal", "blocker", "questions"})


class ManagerPictureCase(PictureCase):
    """What the brief and report tests share: stored pictures and a manager's POST."""

    def stored(self, svc, sid, data):
        status, _, answer = self.send(svc, sid, self.secret(sid), data)
        self.assertEqual(status, 200)
        return json.loads(answer)["picture"]

    def post(self, svc, path, sid, key, value, secret=None, **extra):
        body = json.dumps({"sprint_id": sid, "secret": secret or self.secret(sid), key: value,
                           **extra}).encode()
        return support.post_page(svc.address, path, JSON, body)

    def own_pair(self, svc, sid):
        a = self.stored(svc, sid, PIXEL)
        b = self.stored(svc, sid, WIDE)
        members = [{"picture": a, "line": "the mock-up before", "pair": "before"},
                   {"picture": b, "line": "the mock-up after", "pair": "after"}]
        return a, b, members

    def bad_lists(self, svc, sid, owner, a):
        """Each bad `pictures` list with the reason its refusal gives."""
        other = svc.state_goal("owner/p00", GOAL_TEXT)
        w = self.stored(svc, other, padded(3072))
        self.assertNotIn(w, (a, self.stored(svc, sid, WIDE)))
        gone = self.stored(svc, sid, padded(4096))
        os.unlink(self.pictures_dir / gone)
        mine = {"picture": a, "line": "one"}
        unknown = {"picture": "f" * 64, "line": "one"}
        return unknown, (
            ("shape", "x", sprints.PART_PICTURES_SHAPE.format(owner=owner)),
            ("too many", [mine] * 9, sprints.PART_TOO_MANY_PICTURES.format(owner=owner)),
            ("file key", [{**mine, "file": "x"}], sprints.PART_PICTURE_SHAPE.format(owner=owner, m=1)),
            ("no line", [{"picture": a}], sprints.PART_PICTURE_SHAPE.format(owner=owner, m=1)),
            ("empty line", [{**mine, "line": ""}],
             sprints.PART_PICTURE_MEMBER.format(owner=owner, m=1, member="line")),
            ("long line", [{**mine, "line": "l" * 141}],
             sprints.PART_LINE_TOO_LONG.format(owner=owner, m=1)),
            ("pair twice", [{**mine, "pair": "before"}, {**mine, "pair": "before"}],
             sprints.PART_PAIR_TWICE.format(owner=owner, pair="before")),
            ("unknown", [unknown], sprints.PART_PICTURE_UNKNOWN.format(owner=owner, m=1)),
            ("foreign", [{"picture": w, "line": "one"}],
             sprints.PART_PICTURE_FOREIGN.format(owner=owner, m=1)),
            ("gone", [{"picture": gone, "line": "one"}],
             sprints.PART_PICTURE_UNKNOWN.format(owner=owner, m=1)),
            ("second unknown", [mine, unknown],
             sprints.PART_PICTURE_UNKNOWN.format(owner=owner, m=2)),
        )


class PictureBriefTest(ManagerPictureCase):
    def brief(self, svc, sid, pictures_, **extra):
        return self.post(svc, BRIEF, sid, "brief", {**PARTS, "pictures": pictures_}, **extra)

    def own_brief(self, svc):
        sid = self.sprint(svc)
        a, b, members = self.own_pair(svc, sid)
        status, _, answer = self.brief(svc, sid, members)
        self.assertEqual((status, json.loads(answer)), (200, {"version": 1}))
        return sid, a, b, members

    def test_a_brief_with_its_own_pictures_stores_their_ids_and_lines(self):
        svc = self.open()
        sid, a, b, members = self.own_brief(svc)
        ((payload, _),) = self.rows("brief.sent")
        self.assertEqual(payload["brief"]["pictures"], members)
        self.assertEqual(payload["pictures"], [a, b])
        item = view_of(svc)["inbox"]["open"][0]
        self.assertEqual(item["pictures"],
                         [{"id": a, "line": "the mock-up before", "pair": "before"},
                          {"id": b, "line": "the mock-up after", "pair": "after"}])
        self.assertNotIn("pictures", item["brief"])

    def test_each_bad_brief_picture_list_is_refused_with_its_reason_and_appends_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        a = self.stored(svc, sid, PIXEL)
        before = os.stat(self.pictures_dir / a).st_mtime
        unknown, cases = self.bad_lists(svc, sid, "brief", a)
        for name, listed, reason in cases:
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                status, _, body = self.assert_unchanged(
                    svc, lambda: self.brief(svc, sid, listed))
                self.assertEqual((status, body), (409, reason.encode() + b"\n"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                self.assert_unchanged(svc, lambda: self.brief(
                    svc, sid, [unknown], secret="wrong"))[::2],
                (403, b"secret refused\n"))
            self.assertEqual(
                self.assert_unchanged(svc, lambda: self.post(
                    svc, BRIEF, sid, "brief", {**PARTS, "done": "", "pictures": [unknown]}))[::2],
                (409, b"the brief has no done\n"))
        self.assertEqual(self.rows("brief.sent"), [])
        self.assertEqual(os.stat(self.pictures_dir / a).st_mtime, before)

    def test_eight_pictures_with_140_character_lines_are_taken(self):
        svc = self.open()
        sid = self.sprint(svc)
        a = self.stored(svc, sid, PIXEL)
        status, _, answer = self.brief(svc, sid, [{"picture": a, "line": "l" * 140}] * 8)
        self.assertEqual(status, 200, answer)
        ((payload, _),) = self.rows("brief.sent")
        self.assertEqual(len(payload["brief"]["pictures"]), 8)
        self.assertEqual(payload["pictures"], [a])

    def test_a_brief_without_pictures_logs_the_old_row(self):
        svc = self.open()
        sid = self.sprint(svc)
        status, _, answer = self.post(svc, BRIEF, sid, "brief", PARTS)
        self.assertEqual(status, 200, answer)
        ((payload, _),) = self.rows("brief.sent")
        self.assertEqual(set(payload), {"sprint_id", "version", "goal", "brief"})
        self.assertEqual(set(payload["brief"]), set(sprints.PARTS))

    def test_a_dry_run_checks_a_brief_and_writes_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        a = self.stored(svc, sid, PIXEL)
        before = os.stat(self.pictures_dir / a).st_mtime

        def dry(listed, **changes):
            return self.assert_unchanged(
                svc, lambda: self.brief(svc, sid, listed, **{"dry_run": True, **changes}))
        status, _, answer = dry([{"picture": a, "line": "one"}])
        self.assertEqual((status, json.loads(answer)), (200, {"checked": True}))
        self.assertEqual(answer, b'{"checked":true}')
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, answer = dry([{"picture": "f" * 64, "line": "one"}])
        self.assertEqual((status, answer.strip()),
                         (409, sprints.PART_PICTURE_UNKNOWN.format(owner="brief", m=1).encode()))
        self.assertEqual(dry([], dry_run=False)[0], 400)
        self.assertEqual(self.rows("brief.sent"), [])
        self.assertEqual(os.stat(self.pictures_dir / a).st_mtime, before)

    def test_brief_and_report_pictures_outlive_the_sweep(self):
        svc = self.open()
        sid, a, b, members = self.own_brief(svc)
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid, "version": 1}).encode()
        self.assertEqual(
            support.post_page(svc.address, "/api/approve", self.own(svc, **JSON), body)[0], 204)
        status, _, answer = self.post(svc, "/api/report", sid, "report", {
            **REPORT, "pictures": [{"picture": b, "line": "the mock-up after"}]})
        self.assertEqual(status, 200, answer)
        for picture_id in (a, b):
            age(self.pictures_dir / picture_id, 2 * 86400)
        svc.retain()
        self.assertEqual(self.entries(), sorted([a, b]))

    def test_recap_shows_only_the_briefs_parts(self):
        svc = self.open()
        sid, *_ = self.own_brief(svc)
        parts = svc.recap(sid, self.secret(sid))["brief"]["parts"]
        self.assertEqual(parts, sprints.checked_brief(PARTS))
        self.assertNotIn("pictures", parts)


class PictureReportTest(ManagerPictureCase):
    def report(self, svc, sid, pictures_, **extra):
        return self.post(svc, "/api/report", sid, "report", {**REPORT, "pictures": pictures_},
                         **extra)

    def own_report(self, svc):
        sid = self.approved(svc)
        a, b, members = self.own_pair(svc, sid)
        status, _, answer = self.report(svc, sid, members)
        self.assertEqual(status, 200, answer)
        return sid, a, b, members

    def test_a_report_with_its_own_pictures_stores_their_ids_and_lines(self):
        svc = self.open()
        sid, a, b, members = self.own_report(svc)
        ((payload, _),) = self.rows("sprint.reported")
        self.assertEqual(payload["report"], {**CHECKED, "pictures": members})
        self.assertEqual(payload["pictures"], [a, b])
        entry = next(s for e in view_of(svc)["entries"] for s in e.get("sprints", [])
                     if s["sprint_id"] == sid)
        self.assertEqual(entry["pictures"],
                         [{"id": a, "line": "the mock-up before", "pair": "before"},
                          {"id": b, "line": "the mock-up after", "pair": "after"}])

    def test_each_bad_report_picture_list_is_refused_with_its_reason_and_appends_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        before = os.stat(self.pictures_dir / a).st_mtime
        unknown, cases = self.bad_lists(svc, sid, "report", a)
        for name, listed, reason in cases:
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                status, _, body = self.assert_unchanged(
                    svc, lambda: self.report(svc, sid, listed))
                self.assertEqual((status, body), (409, reason.encode() + b"\n"))
        drafting = self.sprint(svc)
        self.assertEqual(self.post(svc, BRIEF, drafting, "brief", PARTS)[0], 200)
        refused = (
            (lambda: self.report(svc, sid, [unknown], secret="wrong"),
             403, b"secret refused\n"),
            (lambda: self.post(svc, "/api/report", sid, "report",
                               {**REPORT, "status": "", "pictures": [unknown]}),
             409, sprints.REPORT_MEMBER.format(member="status").encode() + b"\n"),
            (lambda: self.report(svc, drafting, [unknown]),
             409, sprints.NOT_STARTED.encode() + b"\n"),
        )
        for action, status, text in refused:
            with self.subTest(text), contextlib.redirect_stderr(io.StringIO()):
                got = self.assert_unchanged(svc, action)
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual(self.rows("sprint.reported"), [])
        self.assertEqual(os.stat(self.pictures_dir / a).st_mtime, before)

    def test_a_report_without_pictures_logs_the_old_row(self):
        svc = self.open()
        sid = self.approved(svc)
        status, _, answer = self.post(svc, "/api/report", sid, "report", REPORT)
        self.assertEqual(status, 200, answer)
        ((payload, _),) = self.rows("sprint.reported")
        self.assertEqual(set(payload), {"sprint_id", "goal", "report"})
        self.assertEqual(set(payload["report"]), set(sprints.REPORT_MEMBERS))

    def test_a_dry_run_checks_a_report_and_writes_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        drafting = self.sprint(svc)
        self.assertEqual(self.post(svc, BRIEF, drafting, "brief", PARTS)[0], 200)
        listed = [{"picture": a, "line": "one"}]
        status, _, answer = self.assert_unchanged(
            svc, lambda: self.report(svc, sid, listed, dry_run=True))
        self.assertEqual((status, answer), (200, b'{"checked":true}'))
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, answer = self.assert_unchanged(
                svc, lambda: self.report(svc, drafting, [], dry_run=True))
        self.assertEqual((status, answer), (409, sprints.NOT_STARTED.encode() + b"\n"))
        self.assertEqual(self.rows("sprint.reported"), [])

    def test_a_report_picture_stays_the_sprints_after_retention_and_a_restart(self):
        now = ["2026-01-01T00:00:00.000000+00:00"]
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(log_clock=lambda: now[0])
        sid = self.approved(svc)
        picture_id = self.stored(svc, sid, PIXEL)
        listed = [{"picture": picture_id, "line": "the header"}]
        self.assertEqual(self.report(svc, sid, listed)[0], 200)
        now[0] = "2026-04-02T00:00:00.000000+00:00"
        svc.retain()
        self.assertEqual(self.rows(PICTURE_STORED), [])
        self.assertEqual(len(self.rows("sprint.reported")), 1)
        svc.close()
        svc = self.start(log_clock=lambda: now[0])
        self.assertEqual(self.entries(), [picture_id])
        status, _, answer = self.report(svc, sid, listed)
        self.assertEqual(status, 200, answer)
        self.assertEqual(len(self.rows("sprint.reported")), 2)


class PictureRetentionTest(PictureCase):
    def stored(self, svc, sid, body):
        status, _, answer = self.send(svc, sid, self.secret(sid), body)
        self.assertEqual(status, 200)
        return json.loads(answer)["picture"]

    def test_a_picture_no_row_references_is_removed_after_one_day(self):
        svc = self.open()
        sid = self.sprint(svc)
        first = self.stored(svc, sid, PIXEL)
        second = self.stored(svc, sid, WIDE)
        age(self.pictures_dir / first, 86400 + 60)
        age(self.pictures_dir / second, 86400 - 60)
        svc.retain()
        self.assertEqual(self.entries(), [second])
        self.assertEqual(len(self.rows(PICTURE_STORED)), 2)

    def test_a_referenced_picture_is_kept_whatever_its_age(self):
        svc = self.open()
        sid = self.sprint(svc)
        picture_id = self.stored(svc, sid, PIXEL)
        svc.log.append([("test.reference", None, {"pictures": [picture_id]})])
        age(self.pictures_dir / picture_id, 3 * 86400)
        svc.retain()
        self.assertEqual(self.entries(), [picture_id])

    def test_a_resend_renews_an_old_picture(self):
        svc = self.open()
        sid = self.sprint(svc)
        picture_id = self.stored(svc, sid, PIXEL)
        age(self.pictures_dir / picture_id, 2 * 86400)
        self.stored(svc, sid, PIXEL)
        svc.retain()
        self.assertEqual(self.entries(), [picture_id])

    def test_a_picture_is_kept_as_long_as_its_reference_row(self):
        now = ["2026-01-01T00:00:00.000000+00:00"]
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(log_clock=lambda: now[0])
        sid = self.sprint(svc)
        picture_id = self.stored(svc, sid, PIXEL)
        svc.log.append([("test.reference", None, {"pictures": [picture_id]})])
        age(self.pictures_dir / picture_id, 2 * 86400)
        svc.retain()
        self.assertEqual(self.entries(), [picture_id])
        now[0] = "2026-04-02T00:00:00.000000+00:00"
        svc.retain()
        self.assertEqual(self.rows("test.reference"), [])
        self.assertEqual(self.entries(), [])

    def test_a_round_picture_stays_the_sprints_after_retention_and_a_restart(self):
        now = ["2026-01-01T00:00:00.000000+00:00"]
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(log_clock=lambda: now[0])
        sid = self.approved(svc)
        picture_id = self.stored(svc, sid, PIXEL)
        member = {"picture": picture_id, "line": "the header"}
        round_ = {"questions": [{**PictureRoundTest.Q, "pictures": [member]}]}

        def ask(blocker):
            body = json.dumps({"sprint_id": sid, "secret": self.secret(sid),
                               "round": {**round_, "blocker": blocker}}).encode()
            return support.post_page(svc.address, "/api/ask", JSON, body)
        self.assertEqual(ask(False)[0], 200)
        now[0] = "2026-04-02T00:00:00.000000+00:00"
        svc.retain()
        self.assertEqual(self.rows(PICTURE_STORED), [])
        self.assertEqual(len(self.rows("questions.asked")), 1)
        svc.close()
        svc = self.start(log_clock=lambda: now[0])
        self.assertEqual(self.entries(), [picture_id])
        status, _, answer = ask(True)
        self.assertEqual(status, 200, answer)
        self.assertEqual(len(self.rows("questions.asked")), 2)

    def test_the_start_pass_sweeps_too(self):
        support.write_registry(self.registry, support.entries(2))
        picture_id, _ = pictures.store(self.pictures_dir, PIXEL)
        age(self.pictures_dir / picture_id, 2 * 86400)
        self.start()
        self.assertEqual(self.entries(), [])

    def test_a_failing_sweep_is_one_stderr_line_and_the_console_goes_on(self):
        support.write_registry(self.registry, support.entries(2))
        self.pictures_dir.parent.mkdir(parents=True, exist_ok=True)
        self.pictures_dir.write_bytes(b"not a directory")
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc = self.start()
            svc.retain()
        lines = [line for line in captured.getvalue().splitlines()
                 if line.startswith("console: picture_sweep_failed NotADirectoryError:")]
        self.assertEqual(len(lines), 2)


def values(headers, name):
    return [value for key, value in headers if key.lower() == name.lower()]


class ReadGuardTest(unittest.TestCase):
    def test_the_read_guard_table(self):
        host, token = "127.0.0.1:9", "t" * 43
        own = "http://127.0.0.1:9"
        refused_origin, refused_token = (403, "origin refused"), (403, "token refused")
        rows = [
            ("no-origin", [], [], [token], None),
            ("own", [own], ["same-origin"], [token], None),
            ("foreign", ["http://evil.example"], [], [token], refused_origin),
            ("null", ["null"], [], [token], refused_origin),
            ("two-origins", [own, own], [], [token], refused_origin),
            ("cross-site", [], ["cross-site"], [token], refused_origin),
            ("same-site", [], ["same-site"], [token], refused_origin),
            ("none", [], ["none"], [token], refused_origin),
            ("two-values", [], ["same-origin", "same-origin"], [token], refused_origin),
            ("no-token", [], [], [], refused_token),
            ("wrong-token", [], [], ["x" * 43], refused_token),
            ("two-tokens", [], [], [token, token], refused_token),
        ]
        for name, origins, sites, tokens, expected in rows:
            with self.subTest(name):
                self.assertEqual(
                    write_guard.read_refusal(host, origins, sites, tokens, token), expected)


class PictureReadTest(PictureCase):
    def stored(self, svc):
        sid = self.sprint(svc)
        status, _, answer = self.send(svc, sid, self.secret(sid), PIXEL)
        self.assertEqual(status, 200)
        return json.loads(answer)["picture"]

    def token_only(self):
        return {"X-Console-Token": self.token()}

    def test_a_picture_is_read_with_the_token_and_no_origin_or_its_own(self):
        svc = self.open()
        picture_id = self.stored(svc)
        own = f"http://127.0.0.1:{svc.address[1]}"
        token = self.token()
        for name, extra in (("token-only", {}), ("own-origin", {"Origin": own}),
                            ("both", {"Origin": own, "Sec-Fetch-Site": "same-origin"}),
                            ("site-only", {"Sec-Fetch-Site": "same-origin"})):
            with self.subTest(name):
                status, headers, body = get(svc.address, f"{PICTURE}/{picture_id}",
                                            {**self.token_only(), **extra})
                self.assertEqual(status, 200)
                self.assertEqual(body, PIXEL)
                self.assertEqual(values(headers, "Content-Type"), ["image/png"])
                self.assertEqual(values(headers, "X-Content-Type-Options"), ["nosniff"])
                self.assertEqual(values(headers, "Cache-Control"), ["private"])
                self.assertEqual(values(headers, "Content-Length"), [str(len(PIXEL))])
                self.assertFalse([v for _, v in headers if token in v])

    def test_a_read_without_the_token_or_from_another_origin_is_403(self):
        svc = self.open()
        picture_id = self.stored(svc)
        own = f"http://127.0.0.1:{svc.address[1]}"
        token = self.token_only()
        rows = [
            ({}, "token refused"),
            ({"Origin": own}, "token refused"),
            ({"X-Console-Token": "A" * 43}, "token refused"),
            ({**token, "Origin": "http://evil.example"}, "origin refused"),
            ({**token, "Origin": "null"}, "origin refused"),
            ({**token, "Sec-Fetch-Site": "cross-site"}, "origin refused"),
            ({**token, "Sec-Fetch-Site": "same-site"}, "origin refused"),
        ]
        for headers, text in rows:
            with self.subTest(headers=headers):
                status, answer_headers, body = get(svc.address, f"{PICTURE}/{picture_id}", headers)
                self.assertEqual(status, 403)
                self.assertEqual(values(answer_headers, "Content-Type"), ["text/plain"])
                self.assertEqual(values(answer_headers, "Cache-Control"), ["no-store"])
                self.assertEqual(body, text.encode() + b"\n")
                self.assertNotIn(PIXEL, body)

    def test_a_malformed_id_is_400_with_the_token(self):
        svc = self.open()
        picture_id = self.stored(svc)
        for path in ("/api/picture/..", "/api/picture/../events.sqlite3", "/api/picture/%2e%2e",
                     f"{PICTURE}/{picture_id.upper()}", f"{PICTURE}/{picture_id[:-1]}",
                     f"{PICTURE}/{picture_id}0", f"{PICTURE}/{picture_id}/x", "/api/picture/",
                     f"{PICTURE}/{picture_id}?x=1"):
            with self.subTest(path=path):
                status, _, body = get(svc.address, path, self.token_only())
                self.assertEqual((status, body), (400, b"bad picture id\n"))
        status, _, body = get(svc.address, "/api/picture/..")
        self.assertEqual((status, body), (403, b"token refused\n"))

    def test_an_unknown_id_is_404(self):
        svc = self.open()
        status, _, body = get(svc.address, f"{PICTURE}/{'0' * 64}", self.token_only())
        self.assertEqual((status, body), (404, b"this picture is not known\n"))

    def test_a_symlink_in_the_store_is_not_served(self):
        svc = self.open()
        self.stored(svc)
        os.symlink(self.token_file, self.pictures_dir / ("1" * 64))
        status, _, body = get(svc.address, f"{PICTURE}/{'1' * 64}", self.token_only())
        self.assertEqual(status, 404)
        self.assertNotIn(self.token().encode(), body)

    def test_other_methods_on_the_read_route_are_refused(self):
        svc = self.open()
        picture_id = self.stored(svc)
        for method in ("POST", "PUT", "DELETE", "HEAD"):
            with self.subTest(method):
                status, headers, _ = support.request(
                    svc.address, method, f"{PICTURE}/{picture_id}")
                self.assertEqual((status, headers["Allow"]), (405, "GET"))


class PictureCommandTest(PictureCase):
    def run_picture(self, svc, sid, file, secret_file, **kwargs):
        return run_sprint("picture", "--sprint", sid, "--secret-file", secret_file, "--file", file,
                          "--port", svc.address[1], **kwargs)

    def test_picture_prints_the_id_and_the_console_keeps_the_bytes(self):
        svc = self.open()
        sid = self.sprint(svc)
        shot = self.write("shot.png", PIXEL)
        result = self.run_picture(svc, sid, shot, self.secret_file(sid))
        expected = hashlib.sha256(PIXEL).hexdigest()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + "\n", ""))
        status, _, body = get(svc.address, f"{PICTURE}/{expected}", {"X-Console-Token": self.token()})
        self.assertEqual((status, body), (200, PIXEL))
        self.assertNotIn(self.secret(sid), result.stdout + result.stderr)

    def test_picture_takes_the_identity_from_the_environment(self):
        svc = self.open()
        sid = self.sprint(svc)
        shot = self.write("shot.png", PIXEL)
        result = run_sprint("picture", "--file", shot, "--port", svc.address[1],
                            env={"CONSOLE_SPRINT_ID": sid, "CONSOLE_SPRINT_SECRET": self.secret(sid)})
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, hashlib.sha256(PIXEL).hexdigest() + "\n", ""))

    def test_picture_refusals_exit_1_with_the_console_reason(self):
        svc = self.open()
        sid = self.sprint(svc)
        shot = self.write("shot.png", PIXEL)
        renamed = self.write("renamed.png", JPEG)
        good, wrong = self.secret_file(sid), self.write("wrong-secret", b"A" * 43)

        def refusals():
            return [self.run_picture(svc, sid, renamed, good),
                    self.run_picture(svc, sid, shot, wrong),
                    self.run_picture(svc, "e" * 16, shot, good)]
        results = self.assert_unchanged(svc, refusals)
        self.assertEqual(
            [(r.returncode, r.stdout, r.stderr) for r in results],
            [(1, "", "sprint: refused 400: " + pictures.SIGNATURE_WRONG + "\n"),
             (1, "", "sprint: refused 403: secret refused\n"),
             (1, "", "sprint: refused 409: this sprint is not open\n")])
        self.assertEqual(self.entries(), [])

    def test_picture_bad_input_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.secret_file(sid)
        missing = self.store.parent / "none.png"
        big = self.write("big.png", padded(3 * 1024 * 1024))

        def attempts():
            return [self.run_picture(svc, sid, missing, good),
                    self.run_picture(svc, sid, big, good),
                    run_sprint("picture", "--sprint", sid, "--file", self.write("shot.png", PIXEL),
                               "--port", svc.address[1])]
        gone, large, nosecret = self.assert_unchanged(svc, attempts)
        self.assertEqual((gone.returncode, gone.stdout), (2, ""))
        self.assertTrue(gone.stderr.startswith("sprint: cannot read "), gone.stderr)
        self.assertEqual((large.returncode, large.stdout, large.stderr),
                         (2, "", f"sprint: cannot send {big}: it is larger than 2 MiB\n"))
        self.assertEqual((nosecret.returncode, nosecret.stdout, nosecret.stderr),
                         (2, "", "sprint: no secret: pass --secret-file or set CONSOLE_SPRINT_SECRET\n"))
        self.assertEqual(self.entries(), [])

    def test_a_secret_a_header_cannot_carry_exits_2_without_printing_it(self):
        svc = self.open()
        sid = self.sprint(svc)
        shot = self.write("shot.png", PIXEL)
        real = self.secret(sid)
        files = [self.secret_file(sid, real + "\n\n"),
                 self.write("odd-secret", "s\u00e9cret\u20ac".encode())]

        def attempts():
            return [self.run_picture(svc, sid, shot, each) for each in files] + [
                run_sprint("picture", "--sprint", sid, "--file", shot, "--port", svc.address[1],
                           env={"CONSOLE_SPRINT_SECRET": "s\u00e9cret\u20ac"})]
        for result in self.assert_unchanged(svc, attempts):
            with self.subTest(stderr=result.stderr):
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, "", "sprint: the secret is not printable ASCII, so it cannot "
                                         "go in a header: no request sent\n"))
        self.assertEqual(self.entries(), [])

    def test_an_unreadable_answer_exits_1(self):
        shot = self.write("shot.png", PIXEL)
        secret = self.write("secret", b"s" * 43)
        err = io.StringIO()
        with mock.patch.object(sprint, "ask", return_value='{"picture":"X"}'), \
                contextlib.redirect_stderr(err):
            code = sprint.main(["picture", "--sprint", "a" * 16, "--secret-file", str(secret),
                                "--file", str(shot)])
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith("sprint: refused 200: unreadable answer: "),
                        err.getvalue())

    def test_the_docstring_states_the_picture_contract(self):
        doc = ast.get_docstring(ast.parse((ROOT / "python/agent_tools/console/sprint.py").read_text()))
        for needle in ("sprint picture", "--file", "POST /api/picture", "X-Console-Sprint",
                       "X-Console-Secret", "image/png", "larger than 2 MiB"):
            with self.subTest(needle):
                self.assertIn(needle, doc)


class PictureAskTest(PictureCase):
    Q = PictureRoundTest.Q

    def round_file(self, round_):
        return self.write("round.json", json.dumps(round_).encode())

    def ask(self, svc, sid, round_):
        return run_sprint("ask", "--sprint", sid, "--secret-file", self.secret_file(sid),
                          "--round-file", self.round_file(round_), "--port", svc.address[1])

    def test_ask_uploads_each_file_and_the_round_names_the_ids(self):
        svc = self.open()
        sid = self.approved(svc)
        before, after = self.write("before.png", PIXEL), self.write("after.png", WIDE)
        a, b = hashlib.sha256(PIXEL).hexdigest(), hashlib.sha256(WIDE).hexdigest()
        round_ = {"questions": [{**self.Q, "pictures": [
            {"file": str(before), "line": "the card before", "pair": "before"},
            {"file": str(after), "line": "the card after", "pair": "after"}]}]}
        got = self.ask(svc, sid, round_)
        ((payload, _),) = self.rows("questions.asked")
        (seq,) = [row[0] for row in support.log_rows(self.store) if row[2] == "questions.asked"]
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(got.stdout, f"sprint: round {seq} sent, 1 question\n")
        self.assertEqual(payload["questions"][0]["pictures"],
                         [{"picture": a, "line": "the card before", "pair": "before"},
                          {"picture": b, "line": "the card after", "pair": "after"}])
        self.assertEqual(payload["pictures"], [a, b])
        self.assertEqual(len(self.rows("picture.stored")), 2)
        self.assertEqual(self.entries(), sorted([a, b]))

    def test_ask_with_a_bad_picture_list_exits_1_and_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        before = self.write("before.png", PIXEL)
        cases = (
            ("nine", [{"file": str(before), "line": "the card"}] * 9,
             sprints.TOO_MANY_PICTURES.format(n=1)),
            ("no line", [{"file": str(before)}], sprints.PICTURE_SHAPE.format(n=1, m=1)),
            ("long line", [{"file": str(before), "line": "l" * 141}],
             sprints.LINE_TOO_LONG.format(n=1, m=1)),
        )
        for name, value, reason in cases:
            with self.subTest(name):
                got = self.assert_unchanged(
                    svc, lambda: self.ask(svc, sid, {"questions": [{**self.Q, "pictures": value}]}))
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (1, "", f"sprint: refused before sending: {reason}\n"))
                self.assertEqual(self.rows("picture.stored"), [])
                self.assertEqual(self.rows("questions.asked"), [])
                self.assertEqual(self.entries(), [])

    def test_ask_with_an_unreadable_or_oversize_file_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        good = self.write("good.png", PIXEL)
        big = self.write("big.png", padded(2 * 1024 * 1024 + 1))
        missing = self.store.parent / "none.png"

        def pictures_of(*files):
            return {"questions": [{**self.Q, "pictures": [
                {"file": str(f), "line": "a card"} for f in files]}]}
        for name, files in (("missing", (missing,)), ("oversize second", (good, big))):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, pictures_of(*files)))
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                if name == "missing":
                    self.assertTrue(got.stderr.startswith("sprint: cannot read"), got.stderr)
                else:
                    self.assertEqual(
                        got.stderr, f"sprint: cannot send {big}: it is larger than 2 MiB\n")
                self.assertEqual(self.rows("picture.stored"), [])
                self.assertEqual(self.rows("questions.asked"), [])

    def test_ask_with_a_refused_picture_exits_1_and_sends_no_round(self):
        svc = self.open()
        sid = self.approved(svc)
        renamed = self.write("renamed.png", JPEG)
        got = self.ask(svc, sid, {"questions": [{**self.Q, "pictures": [
            {"file": str(renamed), "line": "a card"}]}]})
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", "sprint: refused 400: " + pictures.SIGNATURE_WRONG + "\n"))
        self.assertEqual(self.rows("questions.asked"), [])

    def test_ask_with_a_round_too_large_once_ids_are_named_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        good = self.write("good.png", PIXEL)
        line = "\u00e9" * 140
        round_ = {"questions": [
            {**self.Q, "pictures": [{"file": str(good), "line": line}] * 8} for _ in range(10)]}
        got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, round_))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused before sending: the round is larger than "
            f"{service.MAX_ASK_BYTES} bytes\n"))
        self.assertEqual(self.rows("picture.stored"), [])
        self.assertEqual(self.rows("questions.asked"), [])
        self.assertEqual(self.entries(), [])

    def test_a_mixed_round_with_an_unknown_picture_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        good = self.write("good.png", PIXEL)
        other = self.approved(svc, "owner/p01")
        foreign = self.stored(svc, other, WIDE)
        for name, member in (("unknown", "f" * 64), ("another sprint's", foreign)):
            round_ = {"questions": [{**self.Q, "pictures": [
                {"file": str(good), "line": "the file"},
                {"picture": member, "line": "the named one"}]}]}
            with self.subTest(name):
                before = self.entries()
                rows = len(self.rows("picture.stored"))
                got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, round_))
                self.assertEqual((got.returncode, got.stdout), (1, ""))
                self.assertTrue(got.stderr.startswith("sprint: refused 409: "), got.stderr)
                self.assertEqual(len(self.rows("picture.stored")), rows)
                self.assertEqual(self.entries(), before)
                self.assertEqual(self.rows("questions.asked"), [])

    def test_a_mixed_round_with_an_open_round_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        self.assertEqual(self.ask(svc, sid, {"questions": [self.Q]}).returncode, 0)
        good = self.write("good.png", WIDE)
        round_ = {"questions": [{**self.Q, "pictures": [
            {"file": str(good), "line": "the file"}, {"picture": a, "line": "the named one"}]}]}
        got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, round_))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", f"sprint: refused 409: {sprints.ROUND_OPEN}\n"))
        self.assertEqual(len(self.rows("picture.stored")), 1)

    def test_a_mixed_round_with_a_known_picture_is_sent_whole(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        good = self.write("good.png", WIDE)
        b = hashlib.sha256(WIDE).hexdigest()
        got = self.ask(svc, sid, {"questions": [{**self.Q, "pictures": [
            {"file": str(good), "line": "the file"}, {"picture": a, "line": "the named one"}]}]})
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        ((payload, _),) = self.rows("questions.asked")
        self.assertEqual(payload["pictures"], [b, a])

    def test_ask_refuses_a_look_question_without_a_picture_and_takes_it_with_a_file(self):
        svc = self.open()
        sid = self.approved(svc)
        ask = "Judge the screenshots in /tmp/shots"
        got = self.assert_unchanged(svc, lambda: self.ask(svc, sid, {"questions": [
            {**self.Q, "question": ask}]}))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused 409: " + sprints.LOOK_WITHOUT_PICTURE.format(n=1, ask=ask)
            + "\n"))
        shot = self.write("shot.png", PIXEL)
        got = self.ask(svc, sid, {"questions": [{**self.Q, "question": ask, "pictures": [
            {"file": str(shot), "line": "the shots"}]}]})
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(len(self.rows("questions.asked")), 1)

    def test_ask_passes_an_already_sent_id_through(self):
        svc = self.open()
        sid = self.approved(svc)
        a = self.stored(svc, sid, PIXEL)
        got = self.ask(svc, sid, {"questions": [{**self.Q, "pictures": [
            {"picture": a, "line": "the header"}]}]})
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        ((payload, _),) = self.rows("questions.asked")
        self.assertEqual(payload["questions"][0]["pictures"], [{"picture": a, "line": "the header"}])

    def stored(self, svc, sid, data):
        status, _, answer = self.send(svc, sid, self.secret(sid), data)
        self.assertEqual(status, 200)
        return json.loads(answer)["picture"]

    def test_the_ask_docstring_states_the_picture_upload(self):
        doc = ast.get_docstring(ast.parse((ROOT / "python/agent_tools/console/sprint.py").read_text()))
        for needle in ("pictures", "file", "uploads"):
            with self.subTest(needle):
                self.assertIn(needle, doc)


class PictureBriefCommandTest(ManagerPictureCase):
    def send_command(self, svc, sid, value, command):
        path = self.write(f"{command}.json", json.dumps(value).encode())
        return run_sprint(command, "--sprint", sid, "--secret-file", self.secret_file(sid),
                          f"--{command}-file", path, "--port", svc.address[1])

    def files(self):
        before, after = self.write("before.png", PIXEL), self.write("after.png", WIDE)
        return before, after, hashlib.sha256(PIXEL).hexdigest(), hashlib.sha256(WIDE).hexdigest()

    def test_brief_uploads_each_file_and_the_brief_names_the_ids(self):
        svc = self.open()
        sid = self.sprint(svc)
        before, after, a, b = self.files()
        got = self.send_command(svc, sid, {**PARTS, "pictures": [
            {"file": str(before), "line": "the mock-up before", "pair": "before"},
            {"file": str(after), "line": "the mock-up after", "pair": "after"}]}, "brief")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: brief version 1 sent\n", ""))
        ((payload, _),) = self.rows("brief.sent")
        self.assertEqual(payload["brief"]["pictures"],
                         [{"picture": a, "line": "the mock-up before", "pair": "before"},
                          {"picture": b, "line": "the mock-up after", "pair": "after"}])
        self.assertEqual(payload["pictures"], [a, b])
        self.assertEqual(len(self.rows("picture.stored")), 2)
        self.assertEqual(self.entries(), sorted([a, b]))

    def test_a_bad_brief_picture_list_exits_1_and_uploads_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.write("good.png", PIXEL)
        member = {"file": str(good), "line": "the mock-up"}
        cases = (
            ("nine", PARTS, [member] * 9, "the brief has more than 8 pictures"),
            ("no line", PARTS, [{"file": str(good)}],
             "the brief's picture 1 is not an object of picture, line and pair"),
            ("long line", PARTS, [{**member, "line": "l" * 141}],
             "the brief's picture 1's line is over 140 characters"),
            ("empty part", {**PARTS, "done": ""}, [member], "the brief has no done"),
        )
        for name, parts, listed, reason in cases:
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.send_command(
                    svc, sid, {**parts, "pictures": listed}, "brief"))
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (1, "", f"sprint: refused before sending: {reason}\n"))
                self.assertEqual(self.rows("picture.stored"), [])
                self.assertEqual(self.entries(), [])

    def test_a_brief_with_an_unreadable_or_oversize_file_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.write("good.png", PIXEL)
        big = self.write("big.png", padded(2 * 1024 * 1024 + 1))
        missing = self.store.parent / "none.png"
        for name, files in (("missing", (missing,)), ("oversize second", (good, big))):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.send_command(
                    svc, sid, {**PARTS, "pictures": [
                        {"file": str(f), "line": "a mock-up"} for f in files]}, "brief"))
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                if name == "missing":
                    self.assertTrue(got.stderr.startswith("sprint: cannot read"), got.stderr)
                else:
                    self.assertEqual(
                        got.stderr, f"sprint: cannot send {big}: it is larger than 2 MiB\n")
                self.assertEqual(self.rows("picture.stored"), [])
                self.assertEqual(self.rows("brief.sent"), [])

    def test_a_brief_too_large_once_ids_are_named_uploads_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.write("good.png", PIXEL)
        got = self.assert_unchanged(svc, lambda: self.send_command(svc, sid, {
            **PARTS, "done": "d" * 31000,
            "pictures": [{"file": str(good), "line": "\u00e9" * 140}] * 8}, "brief"))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", f"sprint: refused before sending: the brief is larger than "
            f"{service.MAX_BRIEF_BYTES} bytes\n"))
        self.assertEqual(self.rows("picture.stored"), [])
        self.assertEqual(self.entries(), [])

    def test_a_mixed_brief_with_an_unknown_or_foreign_picture_uploads_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.write("good.png", PIXEL)
        other = self.approved(svc, "owner/p01")
        foreign = self.stored(svc, other, padded(3072))
        for name, member, reason in (
                ("unknown", "f" * 64, "the brief's picture 1 is not known"),
                ("another sprint's", foreign, "the brief's picture 1 was sent by another sprint")):
            with self.subTest(name):
                before, rows = self.entries(), len(self.rows("picture.stored"))
                briefs = self.rows("brief.sent")
                got = self.assert_unchanged(svc, lambda: self.send_command(svc, sid, {
                    **PARTS, "pictures": [{"picture": member, "line": "the named one"},
                                          {"file": str(good), "line": "the file"}]}, "brief"))
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (1, "", f"sprint: refused 409: {reason}\n"))
                self.assertEqual(len(self.rows("picture.stored")), rows)
                self.assertEqual(self.entries(), before)
                self.assertEqual(self.rows("brief.sent"), briefs)

    def test_a_picture_refused_while_uploading_sends_no_brief(self):
        svc = self.open()
        sid = self.sprint(svc)
        good, renamed = self.write("good.png", PIXEL), self.write("renamed.png", JPEG)
        got = self.send_command(svc, sid, {**PARTS, "pictures": [
            {"file": str(good), "line": "the first"},
            {"file": str(renamed), "line": "the second"}]}, "brief")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", "sprint: refused 400: " + pictures.SIGNATURE_WRONG + "\n"))
        self.assertEqual(self.rows("brief.sent"), [])
        self.assertEqual(len(self.rows("picture.stored")), 1)
        self.assertEqual(self.entries(), [hashlib.sha256(PIXEL).hexdigest()])

    def test_a_brief_passes_an_already_sent_id_through(self):
        svc = self.open()
        sid = self.sprint(svc)
        a = self.stored(svc, sid, PIXEL)
        got = self.send_command(svc, sid, {**PARTS, "pictures": [
            {"picture": a, "line": "the header"}]}, "brief")
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        ((payload, _),) = self.rows("brief.sent")
        self.assertEqual(payload["brief"]["pictures"], [{"picture": a, "line": "the header"}])


class PictureReportCommandTest(ManagerPictureCase):
    send_command = PictureBriefCommandTest.send_command
    files = PictureBriefCommandTest.files

    def test_a_non_ascii_secret_with_a_file_member_exits_2_for_a_brief_and_a_report(self):
        svc = self.open()
        good = self.write("good.png", PIXEL)
        for command, parts, sid in (("brief", PARTS, self.sprint(svc)),
                                    ("report", REPORT, self.approved(svc))):
            path = self.write(f"{command}.json", json.dumps(
                {**parts, "pictures": [{"file": str(good), "line": "x"}]}).encode())
            with self.subTest(command):
                got = self.assert_unchanged(svc, lambda: run_sprint(
                    command, "--sprint", sid, "--secret-file",
                    self.write("odd-secret", "s\u00e9cret".encode()), f"--{command}-file", path,
                    "--port", svc.address[1]))
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (2, "", "sprint: the secret is not printable ASCII, so it cannot "
                                         "go in a header: no request sent\n"))
                self.assertEqual(self.entries(), [])

    def test_the_docstring_states_the_secret_check_for_a_brief_and_a_report(self):
        doc = " ".join(ast.get_docstring(ast.parse(
            (ROOT / "python/agent_tools/console/sprint.py").read_text())).split())
        for needle in ("it checks that the secret is printable ASCII",
                       "a `picture` or `ask` secret, or a `brief` or `report` secret when the "
                       "object names a `file` member",
                       "a `sprint ask`, `sprint brief` or `sprint report` picture file is the "
                       "same exit 2, before any upload"):
            with self.subTest(needle):
                self.assertIn(needle, doc)

    def test_report_uploads_each_file_and_the_report_names_the_ids(self):
        svc = self.open()
        sid = self.approved(svc)
        before, after, a, b = self.files()
        got = self.send_command(svc, sid, {**REPORT, "pictures": [
            {"file": str(before), "line": "the mock-up before", "pair": "before"},
            {"file": str(after), "line": "the mock-up after", "pair": "after"}]}, "report")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: report sent\n", ""))
        ((payload, _),) = self.rows("sprint.reported")
        self.assertEqual(payload["report"]["pictures"],
                         [{"picture": a, "line": "the mock-up before", "pair": "before"},
                          {"picture": b, "line": "the mock-up after", "pair": "after"}])
        self.assertEqual(payload["pictures"], [a, b])

    def test_a_picture_refused_while_uploading_sends_no_report(self):
        svc = self.open()
        sid = self.approved(svc)
        good, renamed = self.write("good.png", PIXEL), self.write("renamed.png", JPEG)
        got = self.send_command(svc, sid, {**REPORT, "pictures": [
            {"file": str(good), "line": "the first"},
            {"file": str(renamed), "line": "the second"}]}, "report")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", "sprint: refused 400: " + pictures.SIGNATURE_WRONG + "\n"))
        self.assertEqual(self.rows("sprint.reported"), [])
        self.assertEqual(len(self.rows("picture.stored")), 1)
        self.assertEqual(self.entries(), [hashlib.sha256(PIXEL).hexdigest()])

    def test_a_report_before_approval_with_a_file_uploads_nothing(self):
        svc = self.open()
        sid = self.sprint(svc)
        good = self.write("good.png", PIXEL)
        got = self.assert_unchanged(svc, lambda: self.send_command(svc, sid, {
            **REPORT, "pictures": [{"file": str(good), "line": "the look"}]}, "report"))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", f"sprint: refused 409: {sprints.NOT_STARTED}\n"))
        self.assertEqual(self.rows("picture.stored"), [])
        self.assertEqual(self.entries(), [])

    def test_a_bad_report_picture_list_exits_1_and_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        good = self.write("good.png", PIXEL)
        member = {"file": str(good), "line": "the look"}
        for name, value, reason in (
                ("nine", {**REPORT, "pictures": [member] * 9},
                 "the report has more than 8 pictures"),
                ("empty status", {**REPORT, "status": "", "pictures": [member]},
                 "the report has no valid status")):
            with self.subTest(name):
                got = self.assert_unchanged(svc, lambda: self.send_command(
                    svc, sid, value, "report"))
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (1, "", f"sprint: refused before sending: {reason}\n"))
                self.assertEqual(self.rows("picture.stored"), [])
                self.assertEqual(self.entries(), [])

    def test_a_report_too_large_once_ids_are_named_uploads_nothing(self):
        svc = self.open()
        sid = self.approved(svc)
        good = self.write("good.png", PIXEL)
        path = self.write("report.json", json.dumps({**REPORT, "pictures": [
            {"file": str(good), "line": "l" * 140}] * 8}).encode())
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(service, "MAX_REPORT_BYTES", 1024), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = sprint.main(["report", "--sprint", sid, "--secret-file",
                                str(self.secret_file(sid)), "--report-file", str(path),
                                "--port", str(svc.address[1])])
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertEqual(
            err.getvalue(), "sprint: refused before sending: the report is larger than 1024 bytes\n")
        self.assertEqual(self.rows("picture.stored"), [])


class PictureCommandDocsTest(unittest.TestCase):
    def test_the_brief_and_report_docstring_states_the_picture_upload(self):
        doc = ast.get_docstring(ast.parse((ROOT / "python/agent_tools/console/sprint.py").read_text()))
        for needle in ("the brief is larger than", "the report is larger than", "named by nothing"):
            with self.subTest(needle):
                self.assertIn(needle, doc)


class PictureDocsTest(unittest.TestCase):
    def doc(self, path):
        return " ".join((ROOT / path).read_text().split())

    def test_adr_036_records_the_picture_store(self):
        name = "docs/areas/console/adr/036-the-console-keeps-a-managers-pictures-and-serves-them-only-to-the-page.md"
        self.assertTrue((ROOT / name).is_file())
        text = self.doc(name)
        self.assertEqual(
            (ROOT / name).read_text().splitlines()[0],
            "# ADR-console-036 — The console keeps a manager's pictures and serves them only to the page")
        for needle in ("#1089", "POST /api/picture", "X-Console-Sprint", "X-Console-Secret",
                       "image/png", "2 MiB", "413", "SHA-256", "0600", "0700", "picture.stored",
                       "`pictures`", "one day", "ADR-console-009", "ADR-console-013",
                       "ADR-console-019"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertIn("POST /api/picture", self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        self.assertIn("ADR-console-036", self.doc(
            "docs/areas/console/adr/009-events-are-kept-for-90-days.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Picture**:", context)
        self.assertIn("ADR-console-036", context)
        self.assertIn("| Picture | Console |", self.doc("docs/CONTEXT-MAP.md"))

    def test_adr_008_lists_the_picture_read(self):
        adr008 = "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"
        adr036 = "docs/areas/console/adr/036-the-console-keeps-a-managers-pictures-and-serves-them-only-to-the-page.md"
        lines = (ROOT / adr008).read_text().splitlines()
        status = next(row for row in lines if row.startswith("- **Status:**"))
        self.assertEqual(
            status, "- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                    "ADR-console-028, ADR-console-029, ADR-console-030, ADR-console-036, "
                    "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004")
        decided = next(row for row in lines if row.startswith("- **Decided in:**"))
        self.assertTrue(decided.endswith("#1089, #1120, #1176, #1193, #1237"))
        text = self.doc(adr008)
        for needle in ("GET /api/picture/<id>", "Sec-Fetch-Site", "same-origin", "omit",
                       "ADR-console-036"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        text = self.doc(adr036)
        for needle in ("GET /api/picture/<id>", "Cache-Control: private", "nosniff",
                       "bad picture id", "404", "Sec-Fetch-Site"):
            with self.subTest(needle):
                self.assertIn(needle, text)

    def test_adr_038_records_the_question_pictures(self):
        name = ("docs/areas/console/adr/038-a-managers-question-shows-its-pictures-on-the-card-"
                "and-full-size-in-a-viewer.md")
        self.assertEqual(
            (ROOT / name).read_text().splitlines()[0],
            "# ADR-console-038 — A manager's question shows its pictures on the card and full "
            "size in a viewer")
        text = self.doc(name)
        for needle in ("#1090", "8", "140", "before", "after", "X-Console-Token", "object URL",
                       "blob:", "Escape", "inert", "480", "ADR-console-002", "ADR-console-019",
                       "ADR-console-033", "ADR-console-036", "#1091"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        adr = "docs/areas/console/adr/"
        for path, amended in (
                ("019-a-managers-questions-arrive-as-inbox-items.md",
                 "- **Status:** accepted; amended by ADR-console-038, ADR-console-040"),
                ("036-the-console-keeps-a-managers-pictures-and-serves-them-only-to-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-038 and ADR-console-045")):
            with self.subTest(path):
                lines = (ROOT / adr / path).read_text().splitlines()
                self.assertEqual(next(r for r in lines if r.startswith("- **Status:**")), amended)
        lines = (ROOT / adr / "002-the-desk-page-design-rules.md").read_text().splitlines()
        status = next(r for r in lines if r.startswith("- **Status:**"))
        self.assertTrue(status.endswith("ADR-console-035, ADR-console-038, ADR-console-052, ADR-console-056"), status)
        context = (ROOT / "docs/areas/console/CONTEXT.md").read_text()
        for term in ("**Question round**:", "**Picture**:"):
            entry = context[context.index(term):].split("\n\n")[0]
            self.assertIn("ADR-console-038", entry, term)

    def test_adr_041_records_the_brief_and_report_pictures(self):
        adr = "docs/areas/console/adr/"
        name = adr + "041-a-managers-brief-and-report-show-their-pictures-on-the-card.md"
        self.assertEqual(
            (ROOT / name).read_text().splitlines()[0],
            "# ADR-console-041 — A manager's brief and report show their pictures on the card")
        text = self.doc(name)
        for needle in ("#1091", "`pictures`", "8", "140", "before", "after", "brief.sent",
                       "sprint.reported", "dry_run", "Detail", "recap", "ADR-console-013",
                       "ADR-console-014", "ADR-console-036", "ADR-console-038"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        for path, amended in (
                ("013-a-managers-brief-is-approved-or-redirected-on-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-041"),
                ("038-a-managers-question-shows-its-pictures-on-the-card-and-full-size-in-a-viewer.md",
                 "- **Status:** accepted; amended by ADR-console-041 and ADR-console-045")):
            with self.subTest(path):
                lines = (ROOT / adr / path).read_text().splitlines()
                self.assertEqual(next(r for r in lines if r.startswith("- **Status:**")), amended)
        with self.subTest("014"):
            lines = (ROOT / adr / "014-a-managers-report-becomes-the-sprints-line.md"
                     ).read_text().splitlines()
            self.assertEqual(next(r for r in lines if r.startswith("- **Status:**")),
                             "- **Status:** accepted; amended by ADR-console-041, ADR-console-042, ADR-console-048")
        context = (ROOT / "docs/areas/console/CONTEXT.md").read_text()
        for term in ("**Brief**:", "**Report**:", "**Picture**:"):
            entry = context[context.index(term):].split("\n\n")[0]
            self.assertIn("ADR-console-041", entry, term)
