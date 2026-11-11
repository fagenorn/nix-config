"""Run journals (#858): incremental reads, the label-to-stage fold."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import deliveries

L1 = b'{"type":"launched"}\n'
L2 = b'{"type":"started","agentId":"a1","label":"setup","phase":"Setup"}\n'
SETUP = {"type": "started", "agentId": "a1", "label": "setup", "phase": "Setup"}
LAUNCHED = {"type": "launched"}


class CountingFile:
    """A binary file whose `read` adds the bytes it returns to the owner's counter."""

    def __init__(self, owner, handle):
        self._owner, self._handle = owner, handle

    def read(self, n=-1):
        data = self._handle.read(n)
        self._owner.bytes += len(data)
        return data

    def seek(self, *args):
        return self._handle.seek(*args)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def close(self):
        return self._handle.close()


class CountingOpener:
    def __init__(self, fail=None):
        self.calls, self.bytes, self.fail = 0, 0, fail

    def __call__(self, path):
        self.calls += 1
        if self.fail is not None and self.fail[0]:
            raise PermissionError("denied")
        return CountingFile(self, open(path, "rb"))


class JournalReaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / deliveries.JOURNAL_NAME

    def write(self, data):
        self.path.write_bytes(data)

    def append(self, data):
        with open(self.path, "ab") as handle:
            handle.write(data)

    def test_an_unchanged_journal_reads_no_bytes(self):
        self.write(L1 + L2)
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        first = reader.read(self.path)
        self.assertEqual(first.records, (LAUNCHED, SETUP))
        self.assertIs(first.from_start, True)
        self.assertEqual(opener.bytes, len(L1 + L2))
        second = reader.read(self.path)
        self.assertEqual(second.records, ())
        self.assertIs(second.from_start, False)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(opener.bytes, len(L1 + L2))

    def test_a_grown_journal_reads_only_the_new_bytes(self):
        self.write(L1)
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        reader.read(self.path)
        self.append(L2)
        before = opener.bytes
        grown = reader.read(self.path)
        self.assertEqual(grown.records, (SETUP,))
        self.assertIs(grown.from_start, False)
        self.assertEqual(opener.bytes - before, len(L2))
        self.append(L1)
        before = opener.bytes
        reader.read(self.path)
        self.assertEqual(opener.bytes - before, len(L1))

    def test_a_partial_line_waits_for_its_newline(self):
        self.write(L2[:20])
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        self.assertEqual(reader.read(self.path).records, ())
        self.append(L2[20:])
        self.assertEqual(reader.read(self.path).records, (SETUP,))
        self.assertEqual(opener.bytes, len(L2))

    def test_a_truncated_or_replaced_journal_is_read_from_the_start(self):
        self.write(L1 + L2)
        reader = deliveries.JournalReader()
        reader.read(self.path)
        self.write(L1)
        truncated = reader.read(self.path)
        self.assertEqual(truncated.records, (LAUNCHED,))
        self.assertIs(truncated.from_start, True)
        beside = self.dir / "new.jsonl"
        beside.write_bytes(L2 + L1)
        os.replace(beside, self.path)
        replaced = reader.read(self.path)
        self.assertEqual(replaced.records, (SETUP, LAUNCHED))
        self.assertIs(replaced.from_start, True)
        self.assertIs(reader.read(self.path).from_start, False)

    def test_a_missing_journal_reads_as_none(self):
        reader = deliveries.JournalReader()
        self.assertIsNone(reader.read(self.path))
        self.write(L1)
        self.assertEqual(reader.read(self.path).records, (LAUNCHED,))
        self.path.unlink()
        self.assertIsNone(reader.read(self.path))
        self.write(L1)
        again = reader.read(self.path)
        self.assertEqual(again.records, (LAUNCHED,))
        self.assertIs(again.from_start, True)

    def test_a_malformed_line_is_skipped(self):
        self.write(L1 + b"not json\n" + b"[1,2]\n" + b"\xff\n" + b"\n" + L2)
        chunk = deliveries.JournalReader().read(self.path)
        self.assertEqual(chunk.records, (LAUNCHED, SETUP))

    def test_moved_ms_is_the_journal_mtime(self):
        self.write(L1)
        os.utime(self.path, ns=(1_700_000_000_123_456_789,) * 2)
        reader = deliveries.JournalReader()
        self.assertEqual(reader.read(self.path).moved_ms, 1_700_000_000_123)
        self.assertEqual(reader.read(self.path).moved_ms, 1_700_000_000_123)

    def test_a_failed_read_is_unreadable_and_keeps_the_offset(self):
        fail = [False]
        opener = CountingOpener(fail)
        reader = deliveries.JournalReader(opener)
        self.write(L1)
        reader.read(self.path)
        self.append(L2)
        fail[0] = True
        failed = reader.read(self.path)
        self.assertIsInstance(failed, deliveries.Unreadable)
        self.assertTrue(failed.reason.startswith("PermissionError"))
        fail[0] = False
        before = opener.bytes
        recovered = reader.read(self.path)
        self.assertEqual(recovered.records, (SETUP,))
        self.assertIs(recovered.from_start, False)
        self.assertEqual(opener.bytes - before, len(L2))
        with mock.patch("agent_tools.console.deliveries.os.stat", side_effect=PermissionError("denied")):
            self.assertIsInstance(reader.read(self.path), deliveries.Unreadable)
        calls = opener.calls
        unchanged = reader.read(self.path)
        self.assertEqual(unchanged.records, ())
        self.assertIs(unchanged.from_start, False)
        self.assertEqual(opener.calls, calls)


if __name__ == "__main__":
    unittest.main()
