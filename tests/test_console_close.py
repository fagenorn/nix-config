"""Closing the console service stops both of its servers at once, in a fraction of a second.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import service

from . import console_test_support as support
from .test_console_register_service import closing
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # each case starts the console's loopback and guest-socket servers


class CloseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"
        support.write_registry(self.registry, support.entries(1))

    def started(self):
        return support.service(self, self.store, self.registry, guest_socket=support.guest_socket_path(self))

    def test_closing_a_started_console_returns_within_a_fifth_of_a_second(self):
        svc = self.started()
        self.assertIsNotNone(svc._guest_server)
        began = time.monotonic()
        svc.close()
        took = time.monotonic() - began
        self.assertLess(took, 0.2, f"close took {took:.3f} s")

    def test_both_servers_are_asked_to_stop_before_either_is_waited_on(self):
        svc = self.started()
        entered = {"console": threading.Event(), "guest": threading.Event()}
        saw_other = {}

        def watching(own, other, server):
            shutdown = server.shutdown

            def wrapper():
                entered[own].set()
                saw_other[own] = entered[other].wait(1.0)
                shutdown()
            server.shutdown = wrapper

        watching("console", "guest", svc._server)
        watching("guest", "console", svc._guest_server)
        svc.close()
        self.assertEqual(saw_other, {"console": True, "guest": True})

    def test_close_returns_after_both_serve_loops_end_and_the_guest_socket_is_gone(self):
        svc = self.started()
        address = svc.address
        sock = Path(svc.guest_socket)
        self.assertTrue(sock.exists())
        svc.close()
        self.assertFalse(svc._thread.is_alive())
        self.assertFalse(svc._guest_thread.is_alive())
        self.assertFalse(sock.exists())
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(address, timeout=1)

    def test_a_console_that_never_started_closes_at_once(self):
        svc = service.ConsoleService(
            self.store, self.registry, port=0, session_dirs=lambda: [], repo_of=lambda cwd: cwd,
            peer_reader=support.OWNER_PEER, guest_socket=support.guest_socket_path(self))
        self.addCleanup(svc.close)
        closer, errors = closing(svc)
        closer.join(timeout=2)
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(Path(svc.guest_socket).exists())

    def test_a_stopper_thread_that_cannot_start_is_replaced_by_a_synchronous_shutdown(self):
        svc = self.started()
        address = svc.address
        sock = Path(svc.guest_socket)
        shutdowns = (svc._server.shutdown, svc._guest_server.shutdown)
        start = threading.Thread.start

        def refusing(thread):
            if thread._target in shutdowns:
                raise RuntimeError("can't start new thread")
            start(thread)

        with mock.patch.object(threading.Thread, "start", refusing):
            closer, errors = closing(svc)
            closer.join(timeout=5)
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(svc._thread.is_alive())
        self.assertFalse(svc._guest_thread.is_alive())
        self.assertFalse(sock.exists())
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(address, timeout=1)

    def test_an_activation_worker_published_while_close_joins_is_not_left_running(self):
        svc = self.started()
        release = threading.Event()
        self.addCleanup(release.set)

        def wait(run, stop):
            release.wait(5)
            raise service.activation_run.Stopped

        svc._activator = mock.Mock(wait=wait)
        publisher = mock.Mock(join=lambda: svc._wait_for_activation("run"))
        svc._activation_thread = publisher
        svc.close()
        left = [t.name for t in threading.enumerate() if t.name == service.ACTIVATE_THREAD]
        self.assertEqual(left, [])
