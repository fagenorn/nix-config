"""The console's pictures (#1089).

Run: just agent-workflow-tests
"""

import hashlib
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
from . import console_test_support as support  # noqa: F401 -- shared fixtures for later tasks
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
