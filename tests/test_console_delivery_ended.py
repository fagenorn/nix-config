"""The digest names a delivery that ended, end to end through the service.

Run: just agent-workflow-tests
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"
SINGLE = Path(__file__).parent / "fixtures/console/journals/single.jsonl"


class DeliveryEndedTest(unittest.TestCase):
    def test_a_run_with_a_final_record_is_named_in_the_digest(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        registry = root / "state/fleet/registry.json"
        support.write_registry(registry, [{"project_id": "owner/p00", "root": "/srv/p00"}])
        now = time.time()  # the log stamps real time; the digest window follows the service clock
        svc = support.service(self, root / "state/console/events.sqlite3", registry,
                              session_dirs=[root / "sessions"], session_poll_seconds=3600,
                              clock=lambda: now)
        body = support.hook_body("session start", cwd="/srv/p00")
        sid = json.loads(body)["session_id"]
        svc.ingest_hook(body)
        session = root / "projects/-srv-p00" / sid
        journal = session / "subagents/workflows/wf_t1/journal.jsonl"
        journal.parent.mkdir(parents=True)
        journal.write_text("".join(SINGLE.read_text().splitlines(keepends=True)[:10]))
        svc.poll_deliveries()
        (session / "workflows").mkdir()
        (session / "workflows/wf_t1.json").write_text("{}")
        svc.poll_deliveries()
        (ended,) = json.loads(svc.view_bytes)["digest"]["recent"]
        self.assertEqual(ended["kind"], "delivery_ended")
        self.assertEqual(
            ended["sentence"], "The delivery of owner/p00 #858 ended: stopped at building.")


if __name__ == "__main__":
    unittest.main()
