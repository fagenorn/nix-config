"""The console suites' held-publish helper fails a test whose reader never met the held publish.

Run: just agent-workflow-tests
"""
import tempfile
import time
import unittest
from pathlib import Path

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # the case starts the console's loopback service


class HoldThePublishTest(unittest.TestCase):
    def test_a_held_publish_that_the_reader_never_met_fails_the_test(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "state/console/events.sqlite3"
        registry = Path(tmp.name) / "state/fleet/registry.json"
        support.write_registry(registry, [{"project_id": "owner/p00", "root": "/srv/p00"}])
        svc = support.service(self, store, registry, session_dirs=[Path(tmp.name) / "sessions"])
        with self.assertRaisesRegex(AssertionError, "was not held until the reader reached"):
            with support.hold_the_publish(svc, "session.hook", wait=0.2):
                support.post_hook(svc.address, support.hook_body("finished turn"))
                support.wait_rows(store, "session.hook", 1)
                time.sleep(0.6)


if __name__ == "__main__":
    unittest.main()
