"""The console's pictures (#1089).

Run: just agent-workflow-tests
"""

import contextlib
import hashlib
import http.client
import io
import json
import os
import stat
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path

from agent_tools.console import event_log, pictures
from agent_tools.console.event_log import PICTURE_STORED, Event
from agent_tools.console.pictures import SIGNATURE

from . import accounts_sandbox
from . import console_test_support as support
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f00050001ff56c72f0d0000000049454e44ae426082")
WIDE = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000002000000010806000000f4227f8a0000000e4944415478da636060f8ff1f84010dfb03fd9a369bf10000000049454e44ae426082")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"


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

    def test_references_come_from_pictures_lists_of_other_rows(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        events = [
            Event(1, "t", "report.x", None, {"pictures": [a, "bad", b.upper()]}),
            Event(2, "t", PICTURE_STORED, "o/p", {"picture": c, "sprint_id": "s", "pictures": [c]}),
            Event(3, "t", "other", None, {"pictures": a}),
        ]
        self.assertEqual(pictures.referenced(events), frozenset({a}))

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
