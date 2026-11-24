"""The interrupted-run back-off, its streak store and its log line for the verify-pending runner.

Covers the back-off curve, the private streak store (held, cleared, damaged), the one log line a
person or a parser reads, the pass interval the schedules share and the lease that holds two runs
and the longest wait.
Run: just agent-workflow-tests
"""

import contextlib
import io
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.verification import verify_exec as vx, verify_interrupt as vi, verify_run as vr

TIER = "integration"  # its pass cases run PassBase passes against ForgeWorld and spawn real children

NOW = datetime(2026, 11, 24, 15, 29, 4, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]
LINE = (
    "2026-11-24T15:29:04Z interrupted host=eleven-m5 repo=octo/widgets issue=7 check=0 ac=AC4 "
    "signal=SIGTERM next=2026-11-24T15:30:04Z then=rerun"
)
NOTE = dict(
    host="eleven-m5", repo="octo/widgets", issue=7, check=0, ac="AC4", signal=15,
    next_at=NOW + timedelta(seconds=60), then="rerun",
)


class InterruptStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.path = self.tmp / "state" / "interrupted.json"

    def test_the_back_off_doubles_from_the_base_to_the_ceiling(self):
        self.assertEqual([vi.backoff_seconds(n) for n in range(6)], [60, 120, 240, 300, 300, 300])
        self.assertEqual((vi.BACKOFF_BASE_SECONDS, vi.BACKOFF_CEILING_SECONDS), (60, 300))

    def test_a_held_streak_counts_up_and_a_clear_ends_it(self):
        store = vi.Interruptions(self.path, clock=lambda: NOW)
        self.assertEqual(store.streak("k"), 0)
        self.assertEqual(store.hold("k"), 1)
        self.assertEqual(store.hold("k"), 2)
        self.assertEqual(store.hold("j"), 1)
        self.assertEqual(vi.Interruptions(self.path, clock=lambda: NOW).streak("k"), 2)
        store.clear("k")
        self.assertEqual(store.streak("k"), 0)
        self.assertEqual(store.streak("j"), 1)
        self.assertEqual(store.backoff("j"), 120)

    def test_clearing_with_no_store_creates_nothing(self):
        vi.Interruptions(self.path, clock=lambda: NOW).clear("k")
        self.assertFalse(self.path.parent.exists())

    def test_a_damaged_store_reads_as_no_streak(self):
        for text in ("", "not json", "[]", '{"v": 1, "streaks": {"k": "2"}}',
                     '{"v": 1, "streaks": {"k": -1}}', '{"v": 1, "streaks": {"k": true}}'):
            with self.subTest(text=text):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(text)
                store = vi.Interruptions(self.path, clock=lambda: NOW)
                self.assertEqual(store.streak("k"), 0)
                self.assertEqual(store.hold("k"), 1)

    def test_the_store_is_private(self):
        vi.Interruptions(self.path, clock=lambda: NOW).hold("k")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_the_store_lives_in_the_runner_state_directory(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            path = vi.Interruptions.at_home(clock=lambda: NOW).path
        self.assertEqual(path, self.tmp / ".agents/state/verify-pending/interrupted.json")

    def test_a_key_names_the_repo_issue_block_version_and_check(self):
        self.assertEqual(vi.key("octo/widgets", 7, "10.abcd", 0), "octo/widgets#7/10.abcd/0")

    def test_the_log_line_has_the_check_the_signal_and_the_next_run(self):
        logged = []
        store = vi.Interruptions(self.path, clock=lambda: NOW, log=logged.append)
        store.note(**NOTE)
        self.assertEqual(logged, [LINE])
        self.assertEqual(vi.parse_line(logged[0]), {
            "at": "2026-11-24T15:29:04Z", "host": "eleven-m5", "repo": "octo/widgets", "issue": 7,
            "check": 0, "ac": "AC4", "signal": "SIGTERM", "next": "2026-11-24T15:30:04Z", "then": "rerun",
        })

    def test_other_lines_do_not_parse(self):
        for text in ("2026-11-24T15:32:31Z pass start host=eleven-m5", LINE.replace("then=rerun", "then=later"),
                     LINE + " ", ""):
            with self.subTest(text=text):
                self.assertIsNone(vi.parse_line(text))

    def test_a_signal_is_named_by_its_name_or_number(self):
        self.assertEqual([vi.signal_name(n) for n in (15, 9, 200)], ["SIGTERM", "SIGKILL", "200"])

    def test_the_default_log_is_this_moments_stderr(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            store = vi.Interruptions(self.path, clock=lambda: NOW)
            store.note(**NOTE)
        self.assertEqual(buffer.getvalue(), LINE + "\n")

    def test_the_next_pass_is_one_interval_after_the_run_started(self):
        times = [NOW]
        store = vi.Interruptions(self.path, clock=lambda: times[-1])
        times.append(NOW + timedelta(seconds=100))
        self.assertEqual(store.next_pass(), NOW + timedelta(seconds=900))
        times.append(NOW + timedelta(seconds=1000))
        self.assertEqual(store.next_pass(), NOW + timedelta(seconds=1000))

    def test_the_pass_interval_is_the_schedules(self):
        darwin = (REPO_ROOT / "hosts/common/darwin-verify-pending.nix").read_text()
        home = (REPO_ROOT / "home/common/verify-pending/default.nix").read_text()
        self.assertEqual(vi.PASS_INTERVAL_SECONDS, 900)
        self.assertEqual(darwin.count(f"StartInterval = {vi.PASS_INTERVAL_SECONDS};"), 2)
        self.assertIn(f'OnUnitActiveSec = "{vi.PASS_INTERVAL_SECONDS // 60}min";', home)

    def test_two_runs_and_the_ceiling_fit_in_one_lease(self):
        self.assertLess(2 * vx.TIMEOUT + vi.BACKOFF_CEILING_SECONDS, vr.LEASE.total_seconds())


if __name__ == "__main__":
    unittest.main()
