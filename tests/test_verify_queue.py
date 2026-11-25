"""The verify slot queue store and its admission rule: tickets, reservations, holders and who is admitted.

Runs `agent_tools.delivery.verify_queue` in-process against a scratch directory per test; a second open
file description of a lock file stands in for another process.
Run: just agent-workflow-tests
"""

import errno
import fcntl
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import canonical
from agent_tools.delivery import verify_queue
from agent_tools.delivery.verify_queue import (
    Holder, RESUME_SECONDS, Waiter, admitted, clear_holder, group_lock_name, holder_counts, holders_text,
    join, leave, lock_queue, open_shared, place, read_holders, record_holder, repository_lock_paths,
    request_key, reserve, waiters)

TIER = "fast"


def W(seq, live, repo):
    return Waiter(seq, live, repo, "k")


class AdmissionTest(unittest.TestCase):
    def test_a_free_slot_goes_to_the_first_waiter_whose_repository_is_under_its_limit(self):
        ws = [W(1, False, "a"), W(2, False, "a"), W(3, False, "b")]
        self.assertEqual(admitted(ws, {"a": 1}, free=1, repository_limit=1), [W(3, False, "b")])

    def test_waiters_are_served_by_ticket_number(self):
        ws = [W(3, False, "c"), W(1, False, "a"), W(2, False, "b")]
        self.assertEqual(admitted(ws, {}, free=2, repository_limit=1), [W(1, False, "a"), W(2, False, "b")])
        self.assertEqual(place(ws, 3), 3)

    def test_every_live_waiter_is_served_before_every_ordinary_one(self):
        ws = [W(1, False, "a"), W(2, True, "b"), W(3, True, "c")]
        self.assertEqual(admitted(ws, {}, free=1, repository_limit=1), [W(2, True, "b")])
        self.assertEqual(place(ws, 1), 3)
        self.assertEqual(place(ws, 3), 2)

    def test_a_live_waiter_its_repository_holds_back_gets_no_priority(self):
        ws = [W(1, True, "a"), W(2, False, "b")]
        self.assertEqual(admitted(ws, {"a": 1}, free=1, repository_limit=1), [W(2, False, "b")])

    def test_a_repository_limit_of_two_admits_two_runs_of_one_repository(self):
        ws = [W(1, False, "a"), W(2, False, "a"), W(3, False, "b")]
        self.assertEqual(admitted(ws, {}, free=2, repository_limit=2), [W(1, False, "a"), W(2, False, "a")])
        self.assertEqual(admitted(ws, {}, free=2, repository_limit=1), [W(1, False, "a"), W(3, False, "b")])

    def test_runs_outside_a_repository_are_never_held_back_by_each_other(self):
        with tempfile.TemporaryDirectory() as scratch:
            counts = holder_counts(Path(scratch), [Holder(None, "x")], [], 1)
        self.assertEqual(counts, {})
        ws = [W(1, False, None), W(2, False, None)]
        self.assertEqual(admitted(ws, counts, free=2, repository_limit=1), ws)

    def test_no_free_slot_admits_no_one(self):
        self.assertEqual(admitted([W(1, False, "a")], {}, free=0, repository_limit=1), [])


class HolderCountTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def test_known_holders_are_counted_without_probing_the_repository_locks(self):
        with mock.patch.object(verify_queue, "held", side_effect=AssertionError("probed")):
            counts = holder_counts(self.dir, [Holder("a", "just test")], ["a", "b"], 1)
        self.assertEqual(counts, {"a": 1})

    def test_an_unknown_holder_makes_the_repository_locks_count(self):
        unknown = [Holder(None, "", known=False)]
        first = open_shared(repository_lock_paths(self.dir, "a", 1)[0])
        self.addCleanup(os.close, first)
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(holder_counts(self.dir, unknown, ["a", "b"], 1), {"a": 1, "b": 0})
        second = open_shared(repository_lock_paths(self.dir, "a", 2)[1])
        self.addCleanup(os.close, second)
        fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(holder_counts(self.dir, unknown, ["a", "b"], 2), {"a": 2, "b": 0})

    def test_the_repository_lock_names_start_with_the_existing_one(self):
        paths = repository_lock_paths(self.dir, "o/r", 3)
        existing = group_lock_name("o/r")
        digest = existing[len("repo-"):-len(".lock")]
        self.assertEqual([p.name for p in paths], [existing, f"repo-{digest}-1.lock", f"repo-{digest}-2.lock"])
        self.assertEqual([p.name for p in repository_lock_paths(self.dir, "o/r", 1)], [existing])

    def test_the_holders_are_described_in_plain_words(self):
        self.assertEqual(holders_text([]), "nothing")
        self.assertEqual(
            holders_text([Holder("o/r", "just test"), Holder(None, "just lint"), Holder(None, "", known=False)]),
            "o/r (just test), a run outside a repository (just lint), a verify run")


class TicketTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)
        self.opened = []

    def join(self, key="k", now=0, live=False, repository=None):
        ticket = join(self.dir, key, live, repository, now)
        self.opened.append(ticket)
        return ticket

    def tearDown(self):
        for ticket in self.opened:
            try:
                os.close(ticket.descriptor)
            except OSError:
                pass

    def content(self, ticket):
        return json.loads(ticket.path.read_text())

    def test_joins_number_tickets_one_past_every_ticket_present(self):
        old = os.umask(0o077)
        self.addCleanup(os.umask, old)
        first, second = self.join("a"), self.join("b")
        self.assertEqual((first.seq, second.seq), (1, 2))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["ticket-000000000001.lock", "ticket-000000000002.lock"])
        self.assertEqual(first.path.stat().st_mode & 0o777, 0o666)
        (self.dir / "ticket-000000000009.lock").write_text("")
        self.assertEqual(self.join("c").seq, 10)

    def test_a_ticket_whose_lock_is_gone_is_no_waiter_and_is_removed(self):
        t1, t2 = self.join(), self.join()
        os.close(t1.descriptor)
        self.assertEqual([w.seq for w in waiters(self.dir, t2, 0)], [2])
        self.assertFalse(t1.path.exists())

    def test_a_locked_ticket_of_another_waiter_is_listed(self):
        t1 = self.join("one", live=True, repository="o/r")
        t2 = self.join("two")
        listed = {w.seq: w for w in waiters(self.dir, t2, 0)}
        self.assertEqual(set(listed), {1, 2})
        self.assertEqual(listed[1], Waiter(1, True, "o/r", "one"))

    def test_a_reserved_ticket_holds_back_no_one(self):
        t1, t2 = self.join("k"), self.join()
        reserve(t1, now=1000)
        self.assertEqual([w.seq for w in waiters(self.dir, t2, 1000)], [2])
        self.assertTrue(t1.path.exists())
        t3 = self.join("k")
        reserved = {"key": "k", "live": False, "repository": None, "reserved_until": 5000}
        os.pwrite(t3.descriptor, json.dumps(reserved).encode(), 0)
        os.ftruncate(t3.descriptor, len(json.dumps(reserved)))
        self.assertEqual([w.seq for w in waiters(self.dir, t2, 1000)], [2])

    def test_a_reserved_ticket_is_taken_back_by_the_same_key_within_the_window(self):
        t1 = self.join("k", now=1000)
        self.join()
        reserve(t1, 1000)
        t3 = self.join("k", now=1000 + RESUME_SECONDS - 1)
        self.assertEqual(t3.seq, 1)
        self.assertEqual(t3.path, t1.path)
        self.assertIsNone(self.content(t3)["reserved_until"])

    def test_a_reservation_outlives_its_window_while_a_later_waiter_waits(self):
        t1 = self.join("k", now=1000)
        t2 = self.join()
        self.join()
        reserve(t1, 1000)
        late = 1000 + RESUME_SECONDS + 100
        waiters(self.dir, t2, late)
        self.assertTrue(t1.path.exists())
        self.assertEqual(self.join("k", now=late).seq, 1)

    def test_a_reservation_expires_after_its_window_once_no_later_waiter_waits(self):
        t1 = self.join("k", now=1000)
        t2 = self.join()
        leave(t2)
        reserve(t1, 1000)
        late = 1000 + RESUME_SECONDS + 1
        t3 = self.join("k", now=late)
        self.assertEqual(t3.seq, 2)
        self.assertNotEqual(t3.path, t1.path)
        waiters(self.dir, t3, late)
        self.assertFalse(t1.path.exists())

    def test_a_waiter_that_joined_after_the_window_does_not_keep_the_expired_reservation(self):
        t1 = self.join("k", now=1000)
        reserve(t1, 1000)
        late = 1000 + RESUME_SECONDS + 3600
        x = self.join("x", now=late)
        self.assertEqual(x.seq, 2)
        waiters(self.dir, x, late)
        self.assertFalse(t1.path.exists())
        again = self.join("k", now=late + 60)
        self.assertEqual(again.seq, 3)
        self.assertEqual([w.seq for w in waiters(self.dir, again, late + 60)], [2, 3])

    def test_a_ticket_without_a_reserved_until_is_no_waiter_and_never_stops_a_join(self):
        broken = self.dir / "ticket-000000000001.lock"
        broken.write_text(json.dumps({"key": "k", "live": False, "repository": None}))
        ticket = self.join("k", now=0)
        self.assertEqual(ticket.seq, 2)
        self.assertEqual([w.seq for w in waiters(self.dir, ticket, 0)], [2])
        self.assertFalse(broken.exists())

    def test_a_scan_that_runs_out_of_descriptors_removes_no_ticket(self):
        t1, t2 = self.join("one"), self.join("two")
        refused = OSError(errno.EMFILE, "Too many open files")
        real = verify_queue.open_shared

        def open_shared_but_for_t1(path):
            if path == t1.path:
                raise refused
            return real(path)

        with mock.patch.object(verify_queue, "open_shared", side_effect=open_shared_but_for_t1):
            with self.assertRaises(OSError):
                waiters(self.dir, t2, 0)
            with self.assertRaises(OSError):
                self.join("three")
        self.assertTrue(t1.path.exists())

    def test_another_key_never_takes_a_reserved_ticket(self):
        t1 = self.join("k")
        self.join()
        reserve(t1, 1000)
        self.assertEqual(self.join("other", now=1001).seq, 3)

    def test_leaving_removes_the_ticket(self):
        t1 = self.join()
        leave(t1)
        self.assertFalse(t1.path.exists())
        with self.assertRaises(OSError):
            os.fstat(t1.descriptor)

    def test_the_queue_lock_is_taken_by_one_process_at_a_time(self):
        a = lock_queue(self.dir)
        self.assertIsInstance(a, int)
        self.assertIsNone(lock_queue(self.dir))
        os.close(a)
        again = lock_queue(self.dir)
        self.assertIsInstance(again, int)
        os.close(again)

    def test_a_planted_symlink_at_a_ticket_name_is_never_written_through(self):
        victim = self.dir.parent / (self.dir.name + "-victim")
        victim.write_text("victim-original")
        self.addCleanup(victim.unlink)
        (self.dir / "ticket-000000000001.lock").symlink_to(victim)
        ticket = self.join()
        self.assertEqual(ticket.seq, 2)
        with self.assertRaises(OSError):
            open_shared(self.dir / "ticket-000000000001.lock")
        self.assertEqual(victim.read_text(), "victim-original")
        self.assertEqual([w.seq for w in waiters(self.dir, ticket, 0)], [2])
        self.assertEqual(victim.read_text(), "victim-original")


class HolderFileTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def lock(self, name):
        descriptor = open_shared(self.dir / name)
        self.addCleanup(self.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor

    @staticmethod
    def close(descriptor):
        try:
            os.close(descriptor)
        except OSError:
            pass

    def test_a_long_command_still_leaves_a_description_the_reader_parses(self):
        descriptor = self.lock("slot-0.lock")
        record_holder(descriptor, "o/r", "just " + "x" * 5000)
        (holder,) = read_holders(self.dir)
        self.assertTrue(holder.known)
        self.assertEqual(holder.repository, "o/r")
        self.assertTrue(holder.command.startswith("just xxx"))

    def test_a_held_slot_file_describes_its_holder(self):
        fd1 = self.lock("slot-1.lock")
        self.lock("slot-0.lock")
        record_holder(fd1, "o/r", "just test")
        self.assertEqual(read_holders(self.dir), [Holder(None, "", known=False), Holder("o/r", "just test")])
        clear_holder(fd1)
        self.assertEqual(read_holders(self.dir), [Holder(None, "", known=False)] * 2)
        os.close(fd1)
        self.assertEqual(read_holders(self.dir), [Holder(None, "", known=False)])

    def test_a_description_left_by_a_dead_holder_is_unknown(self):
        child = subprocess.Popen(["true"])
        child.wait()
        descriptor = self.lock("slot-0.lock")
        data = json.dumps({"command": "just test", "pid": child.pid, "repository": "o/r"}).encode()
        os.pwrite(descriptor, data, 0)
        self.assertEqual(read_holders(self.dir), [Holder(None, "", known=False)])

    def test_a_hard_link_at_a_slot_name_is_refused(self):
        victim = self.dir.parent / (self.dir.name + "-victim")
        victim.write_text("victim-original")
        self.addCleanup(victim.unlink)
        os.link(victim, self.dir / "slot-0.lock")
        with self.assertRaises(OSError):
            open_shared(self.dir / "slot-0.lock")
        self.assertEqual(read_holders(self.dir), [Holder(None, "", known=False)])
        self.assertEqual(victim.read_text(), "victim-original")


class RequestKeyTest(unittest.TestCase):
    def test_the_request_key_is_the_resolved_cwd_and_the_argv(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch).resolve()
            real, other = root / "real", root / "other"
            real.mkdir()
            other.mkdir()
            link = root / "link"
            link.symlink_to(real)
            argv = ["just", "test"]
            self.assertEqual(request_key(real, argv), request_key(link, argv))
            self.assertEqual(request_key(real, argv), canonical.telemetry_digest([str(real), argv]))
            self.assertNotEqual(request_key(real, argv), request_key(real, ["just", "lint"]))
            self.assertNotEqual(request_key(real, argv), request_key(other, argv))


if __name__ == "__main__":
    unittest.main()
