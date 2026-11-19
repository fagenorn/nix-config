"""The peer lookup (#1294): which process holds a loopback connection's client end.

Run: just agent-workflow-tests
"""

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.console.peer import (
    LOOKUP_TIMEOUT_SECONDS, NOT_OWNER_TEXT, UNREADABLE_TEXT, Holder, parse_lsof, read_lsof,
    read_proc, reader_for, refusal)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

LSOF_FORWARD = """p52108
cpython3.13
u502
f7
n127.0.0.1:27184->127.0.0.1:53075
p65310
csshd-session
u502
f12
n127.0.0.1:53075->127.0.0.1:27184
p790
cssh
u502
f3
n127.0.0.1:49175->127.0.0.1:49167
"""
SERVER_ONLY = "".join(LSOF_FORWARD.splitlines(keepends=True)[:5])
CLIENT = ("127.0.0.1", 53075)
SERVER = ("127.0.0.1", 27184)
PCLIENT = ("127.0.0.1", 53083)
PSERVER = ("127.0.0.1", 27216)
PROC_CLIENT = "0100007F:CF5B"
PROC_SERVER = "0100007F:6A50"
V6_CLIENT = "0000000000000000FFFF00000100007F:CF5B"
V6_SERVER = "0000000000000000FFFF00000100007F:6A50"
HEADER = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
          "   uid  timeout inode\n")
LITTLE = unittest.skipUnless(sys.byteorder == "little", "the proc encoding below is little-endian")
LIVE = unittest.skipUnless(
    sys.platform == "darwin" or sys.platform.startswith("linux"), "needs lsof or /proc")


def table(rows):
    text = HEADER
    for i, (local, remote, state, uid, inode) in enumerate(rows):
        text += (f"{i}: {local} {remote} {state} 00000000:00000000 00:00000000 00000000 {uid} 0 "
                 f"{inode} 1 0000000000000000 20 4 30 10 -1\n")
    return text


def proc_root(tmp, tcp_rows, tcp6_rows=(), processes=None):
    root = Path(tmp)
    (root / "net").mkdir(parents=True, exist_ok=True)
    (root / "net/tcp").write_text(table(tcp_rows))
    (root / "net/tcp6").write_text(table(tcp6_rows))
    for pid, (uids, comm, inodes) in (processes or {}).items():
        fd = root / str(pid) / "fd"
        fd.mkdir(parents=True)
        for n, inode in enumerate(inodes):
            os.symlink(f"socket:[{inode}]", fd / str(n))
        u0, u1, u2, u3 = uids
        (root / str(pid) / "status").write_text(f"Name:\t{comm}\nUid:\t{u0}\t{u1}\t{u2}\t{u3}\n")
        (root / str(pid) / "comm").write_text(f"{comm}\n")
    return root


class RefusalTest(unittest.TestCase):
    def test_only_holders_all_of_the_owner_are_admitted(self):
        a = Holder(10, 501, "Safari")
        b = Holder(11, 502, "curl")
        s501 = Holder(None, 501, None)
        s502 = Holder(None, 502, None)
        other = ("other_user", NOT_OWNER_TEXT)
        absent = ("not_found", NOT_OWNER_TEXT)
        self.assertIsNone(refusal((a,), 501))
        self.assertIsNone(refusal((s501, a), 501))
        self.assertEqual(refusal((a, b), 501), other)
        self.assertEqual(refusal((b,), 501), other)
        self.assertEqual(refusal((s502, a), 501), other)
        self.assertEqual(refusal((s501,), 501), absent)
        self.assertEqual(refusal((), 501), absent)
        self.assertEqual(refusal(None, 501), ("unreadable", UNREADABLE_TEXT))


class LsofTest(unittest.TestCase):
    def test_an_owner_sshd_forward_is_its_holder(self):
        holders = parse_lsof(LSOF_FORWARD, CLIENT, SERVER)
        self.assertEqual(holders, (Holder(65310, 502, "sshd-session"),))
        self.assertIsNone(refusal(holders, 502))

    def test_the_server_end_alone_is_no_holder(self):
        self.assertEqual(parse_lsof(SERVER_ONLY, CLIENT, SERVER), ())

    def test_read_lsof_runs_lsof_once_with_no_state_filter(self):
        calls = []

        def stub_for(code, out, err=""):
            def stub(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, code, out, err)
            return stub

        result = read_lsof(CLIENT, SERVER, run=stub_for(0, LSOF_FORWARD))
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(
            argv, ["/usr/sbin/lsof", "-nP", "-iTCP@127.0.0.1:53075", "-Fpcun"])
        self.assertEqual(kwargs, {"capture_output": True, "text": True,
                                  "timeout": LOOKUP_TIMEOUT_SECONDS, "check": False})
        self.assertEqual(result, (Holder(65310, 502, "sshd-session"),))
        self.assertEqual(read_lsof(CLIENT, SERVER, run=stub_for(1, "")), ())
        self.assertEqual(read_lsof(CLIENT, SERVER, run=stub_for(0, SERVER_ONLY)), ())
        self.assertEqual(refusal((), 502), ("not_found", NOT_OWNER_TEXT))

    def test_a_failed_or_slow_lookup_reads_unreadable(self):
        def raising(error):
            def stub(argv, **kwargs):
                raise error
            return stub

        def returning(code, out, err=""):
            return lambda argv, **kwargs: subprocess.CompletedProcess(argv, code, out, err)

        stubs = {
            "oserror": raising(OSError("no lsof")),
            "timeout": raising(subprocess.TimeoutExpired("lsof", 2.0)),
            "bad uid": returning(
                0, "p65310\ncsshd-session\nuabc\nf12\nn127.0.0.1:53075->127.0.0.1:27184\n"),
            "partial then failure": returning(1, LSOF_FORWARD),
            "stderr on exit 1": returning(1, "", "lsof: can't open kernel memory\n"),
            "stderr on exit 0": returning(0, LSOF_FORWARD, "lsof: status error\n"),
            "warning that output is incomplete":
                returning(0, LSOF_FORWARD, "lsof: WARNING: can't stat() fuse file system\n"
                                           "      Output information may be incomplete.\n"),
            "exit 2": returning(2, ""),
        }
        for name, stub in stubs.items():
            with self.subTest(name):
                self.assertIsNone(read_lsof(CLIENT, SERVER, run=stub))


class ProcTest(unittest.TestCase):
    def build(self, *args, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return proc_root(tmp.name, *args, **kwargs)

    @LITTLE
    def test_the_holder_is_the_process_holding_the_client_ends_inode(self):
        root = self.build(
            [(PROC_CLIENT, PROC_SERVER, "05", 1000, 777),
             (PROC_SERVER, PROC_CLIENT, "08", 1000, 778),
             ("0100007F:0001", "0100007F:0002", "06", 1000, 0)],
            processes={4242: ((1000,) * 4, "curl", [777]),
                       4243: ((1000,) * 4, "python3", [778])})
        holders = read_proc(PCLIENT, PSERVER, root=root)
        self.assertEqual(holders, (Holder(None, 1000, None), Holder(4242, 1000, "curl")))
        self.assertIsNone(refusal(holders, 1000))

    @LITTLE
    def test_socket_owner_and_holder_credentials_that_differ_are_refused(self):
        other = ("other_user", NOT_OWNER_TEXT)
        absent = ("not_found", NOT_OWNER_TEXT)
        cases = {
            "foreign process": (1000, {4242: ((1001,) * 4, "curl", [777])}, other),
            "foreign socket owner": (1001, {4242: ((1000,) * 4, "curl", [777])}, other),
            "set-user-id process": (1000, {4242: ((1000, 0, 0, 1000), "curl", [777])}, other),
            "no holder": (1000, {}, absent),
        }
        for name, (row_uid, processes, expected) in cases.items():
            with self.subTest(name):
                root = self.build([(PROC_CLIENT, PROC_SERVER, "01", row_uid, 777)],
                                  processes=processes)
                self.assertEqual(refusal(read_proc(PCLIENT, PSERVER, root=root), 1000), expected)

    @LITTLE
    def test_a_v4_mapped_row_in_tcp6_is_found(self):
        root = self.build([], tcp6_rows=[(V6_CLIENT, V6_SERVER, "01", 1000, 777)],
                          processes={4242: ((1000,) * 4, "curl", [777])})
        self.assertEqual(read_proc(PCLIENT, PSERVER, root=root),
                         (Holder(None, 1000, None), Holder(4242, 1000, "curl")))

    def test_an_unreadable_table_or_holder_reads_unreadable(self):
        row = [(PROC_CLIENT, PROC_SERVER, "01", 1000, 777)]
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(read_proc(PCLIENT, PSERVER, root=Path(empty)))
        with tempfile.TemporaryDirectory() as tmp:
            root = proc_root(tmp, row)
            (root / "net/tcp6").unlink()
            self.assertIsNone(read_proc(PCLIENT, PSERVER, root=root))
        with tempfile.TemporaryDirectory() as tmp:
            root = proc_root(tmp, row, processes={4242: ((1000,) * 4, "curl", [777])})
            (root / "4242/status").unlink()
            self.assertIsNone(read_proc(PCLIENT, PSERVER, root=root))


class PlatformTest(unittest.TestCase):
    def test_reader_for_names_the_platforms(self):
        self.assertIs(reader_for("darwin"), read_lsof)
        self.assertIs(reader_for("linux"), read_proc)
        self.assertIsNone(reader_for("win32"))

    def pair(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname()[:2])
        self.addCleanup(client.close)
        accepted, _ = listener.accept()
        self.addCleanup(accepted.close)
        return listener, client, accepted

    def assert_attributed(self, listener, client):
        holders = reader_for(sys.platform)(client.getsockname()[:2], listener.getsockname()[:2])
        self.assertIsInstance(holders, tuple)
        with_pid = [holder for holder in holders if holder.pid is not None]
        self.assertTrue(with_pid)
        self.assertTrue(all(holder.uid == os.geteuid() for holder in holders))
        self.assertIn(os.getpid(), [holder.pid for holder in with_pid])

    @LIVE
    def test_the_platform_reader_attributes_a_connection_of_this_process(self):
        listener, client, _accepted = self.pair()
        self.assert_attributed(listener, client)

    @LIVE
    def test_a_half_closed_client_end_is_still_attributed(self):
        listener, client, accepted = self.pair()
        client.sendall(b"GET / HTTP/1.1\r\n\r\n")
        client.shutdown(socket.SHUT_WR)
        accepted.settimeout(5)
        while accepted.recv(4096):
            pass
        self.assert_attributed(listener, client)


if __name__ == "__main__":
    unittest.main()
