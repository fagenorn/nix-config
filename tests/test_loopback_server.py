"""The loopback server the verify-check suites share shuts down without waiting out the default poll (#1727).

It lives beside, not in, the verify-checks suite to keep that file from growing past the B17 budget.

Run: just agent-workflow-tests
"""
import time
import unittest

from tests.test_verify_checks import ConsoleHandler, loopback_server

TIER = "integration"  # it binds a loopback port


class LoopbackServerTest(unittest.TestCase):
    def test_a_loopback_server_shuts_down_without_waiting_out_the_default_poll(self):
        server = loopback_server(ConsoleHandler)
        self.addCleanup(server.server_close)
        started = time.monotonic()
        server.shutdown()
        self.assertLess(time.monotonic() - started, 0.25)
