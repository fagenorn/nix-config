"""The interrupted-run back-off, its streak store and its log line for the verify-pending runner.

Covers the back-off curve, the private streak store (held, cleared, damaged), the one log line a
person or a parser reads, the pass interval the schedules share and the lease that holds two runs
and the longest wait.
Run: just agent-workflow-tests
"""

import contextlib
import io
import os
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.verification import (
    verify_exec as vx, verify_interrupt as vi, verify_pending, verify_run as vr,
)

from .test_verify_pending import ISSUE, SLUG, TIP, PassBase, Refs, bkey, check, line

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


TERM = "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)"


class InterruptedPassTest(PassBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = self.tmp / "interrupted.json"
        self.runs = self.tmp / "runs"
        self.waits, self.logged = [], []

    def stub(self, name, body):
        script = self.world.checkout / "scripts" / name
        script.write_text(
            f"#!{sys.executable}\nopen({str(self.runs)!r}, 'a').write('x')\n{body}\n", encoding="utf-8")
        script.chmod(0o755)
        return check(run={"script": f"scripts/{name}"})

    def interruptions(self):
        return vi.Interruptions(self.store, clock=lambda: NOW, sleep=self.waits.append, log=self.logged.append,
                                started=NOW)

    def run_pass(self):
        return [entry for node in vr.list_held(SLUG)
                for entry in vr.pass_issue(self.project, "mbp", node, Refs(), interruptions=self.interruptions())]

    def run_count(self):
        return len(self.runs.read_text()) if self.runs.exists() else 0

    def streak_of(self, held):
        return self.interruptions().streak(vi.key(SLUG, ISSUE, bkey(held), 0))

    def test_a_check_a_signal_ends_twice_is_held_interrupted_twice_and_never_failed(self):
        held = self.stub("term.py", TERM)
        self.hold(held)
        lines = self.run_pass()
        self.assertEqual(lines, [line(0, "AC1", "pending", "interrupted_twice")])
        self.assertEqual(self.run_count(), 2)
        self.assertEqual(self.waits, [60])
        self.assertEqual(self.markers("verify-result"), [])
        self.assertNotIn("verification-failed", self.world.issue()["labels"])
        self.assertEqual(len(self.markers("verify-due")), 1)
        self.assertEqual(self.logged, [
            "2026-11-24T15:29:04Z interrupted host=mbp repo=octo/widgets issue=7 check=0 ac=AC1 "
            "signal=SIGTERM next=2026-11-24T15:30:04Z then=rerun",
            "2026-11-24T15:29:04Z interrupted host=mbp repo=octo/widgets issue=7 check=0 ac=AC1 "
            "signal=SIGTERM next=2026-11-24T15:44:04Z then=held",
        ])
        self.assertEqual(self.streak_of(held), 1)

    def test_a_rerun_that_completes_is_recorded_and_ends_the_streak(self):
        killed = self.tmp / "killed"
        held = self.stub("once.py", (
            f"import pathlib, sys\nmark = pathlib.Path({str(killed)!r})\n"
            f"if mark.exists():\n    sys.exit(0)\nmark.write_text('x')\n{TERM}"))
        self.hold(held)
        key = vi.key(SLUG, ISSUE, bkey(held), 0)
        self.interruptions().hold(key)
        self.interruptions().hold(key)
        lines = self.run_pass()
        self.assertEqual(lines, [line(0, "AC1", "pass", "changed"), line(None, None, "closed", "verified")])
        self.assertEqual(self.run_count(), 2)
        self.assertEqual(self.waits, [240])
        self.assertEqual(len(self.logged), 1)
        self.assertTrue(self.logged[0].endswith("then=rerun"))
        self.assertEqual(self.streak_of(held), 0)

    def test_the_back_off_doubles_on_each_later_interrupted_pass_to_the_ceiling(self):
        held = self.stub("term.py", TERM)
        self.hold(held)
        passes = [self.run_pass() for _ in range(5)]
        self.assertEqual(passes, [[line(0, "AC1", "pending", "interrupted_twice")]] * 5)
        self.assertEqual(self.waits, [60, 120, 240, 300, 300])
        self.assertEqual(self.run_count(), 10)
        self.assertEqual(self.markers("verify-result"), [])
        self.assertEqual(self.streak_of(held), 5)

    def test_a_completed_run_restarts_the_back_off_at_the_base(self):
        mode = self.tmp / "mode"
        held = self.stub("flip.py", (
            f"import pathlib, sys\nif pathlib.Path({str(mode)!r}).read_text() == 'term':\n"
            f"    {TERM.replace(chr(10), chr(10) + '    ')}\nsys.exit(75)"))
        self.hold(held)
        mode.write_text("term")
        self.run_pass()
        mode.write_text("later")
        second = self.run_pass()
        mode.write_text("term")
        self.run_pass()
        self.assertEqual(second, [line(0, "AC1", "pending", "not_yet")])
        self.assertEqual(self.waits, [60, 60])
        self.assertEqual(self.run_count(), 5)

    def test_a_first_run_that_completes_never_waits_or_writes_a_store(self):
        self.hold(self.stub("ok.py", "import sys\nsys.exit(0)"))
        self.run_pass()
        self.assertEqual((self.waits, self.logged), ([], []))
        self.assertFalse(self.store.exists())
        self.assertEqual(self.run_count(), 1)

    def test_a_host_wide_sigterm_reaches_the_runner_and_its_check_and_the_check_is_rerun_once(self):
        held = self.stub("wide.py", (
            "import os, signal\nos.kill(os.getppid(), signal.SIGTERM)\nos.kill(os.getpid(), signal.SIGTERM)"))
        self.hold(held)
        before = signal.getsignal(signal.SIGTERM)
        with vi.survive() as received:
            lines = self.run_pass()
        self.assertEqual(lines, [line(0, "AC1", "pending", "interrupted_twice")])
        self.assertEqual(received, [signal.SIGTERM, signal.SIGTERM])
        self.assertEqual(self.run_count(), 2)
        self.assertEqual(self.waits, [60])
        self.assertEqual([entry.rsplit(" ", 1)[1] for entry in self.logged], ["then=rerun", "then=held"])
        self.assertEqual(self.markers("verify-result"), [])
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


class ClassifyInterruptTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_a_run_a_signal_ended_is_interrupted(self):
        script = self.tmp / "term.py"
        script.write_text(f"#!{sys.executable}\n{TERM}\n", encoding="utf-8")
        script.chmod(0o755)
        result = vx.execute([str(script)], self.tmp)
        self.assertEqual((result.exit, result.timed_out), (-15, False))
        self.assertEqual(vx.signal_of(result.exit), 15)
        self.assertEqual(vx.classify(result, None), "interrupted")

    def test_a_shell_report_of_a_signal_is_interrupted(self):
        for code, number in ((-9, 9), (143, 15), (137, 9), (129, 1)):
            with self.subTest(exit=code):
                self.assertEqual(vx.signal_of(code), number)
                self.assertEqual(vx.classify(vx.Result(code, "", "", False), None), "interrupted")

    def test_exits_that_name_no_signal_are_not_interrupted(self):
        for code, outcome in ((0, "met"), (1, "not_met"), (75, "not_yet"), (2, "exit_unexpected"),
                              (128, "exit_unexpected"), (200, "exit_unexpected"), (255, "exit_unexpected"),
                              (None, "exit_unexpected")):
            with self.subTest(exit=code):
                self.assertIsNone(vx.signal_of(code))
                self.assertEqual(vx.classify(vx.Result(code, "", "", False), None), outcome)

    def test_a_timeout_stays_a_timeout(self):
        for code in (None, -9):
            with self.subTest(exit=code):
                self.assertEqual(vx.classify(vx.Result(code, "", "", True), None), "timeout")


class SurviveTest(unittest.TestCase):
    def child(self, code):
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")}
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)

    def test_sigterm_and_sighup_are_survived_and_recorded(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                done = self.child(
                    "import os, signal\nfrom agent_tools.verification import verify_interrupt as vi\n"
                    f"with vi.survive() as got:\n    os.kill(os.getpid(), {int(sig)})\nprint(got)")
                self.assertEqual((done.returncode, done.stdout), (0, f"[{int(sig)}]\n"))

    def test_other_signals_and_signals_after_survive_still_end_the_process(self):
        self.assertEqual(vi.SURVIVED, (signal.SIGTERM, signal.SIGHUP))
        cases = {
            "inside": (signal.SIGINT, "with vi.survive():\n    os.kill(os.getpid(), {n})\n"),
            "after": (signal.SIGTERM, "with vi.survive():\n    pass\nos.kill(os.getpid(), {n})\n"),
        }
        for name, (sig, body) in cases.items():
            with self.subTest(case=name):
                done = self.child("import os\nfrom agent_tools.verification import verify_interrupt as vi\n"
                                  + body.format(n=int(sig)) + "import time\ntime.sleep(5)")
                self.assertEqual(done.returncode, -sig)


class RunWiringTest(unittest.TestCase):
    def run_main(self, pass_repo):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        home = self.home
        entries = [{"project_id": "a/one", "root": str(home)}, {"project_id": "a/two", "root": str(home)}]

        @contextlib.contextmanager
        def source(entry):
            bindings = {"tracker": {"kind": "github", "repo_slug": entry["project_id"]}, "commands": {}}
            yield vx.Source({"bindings": bindings}, home, TIP, "main")

        with (mock.patch.dict(os.environ, {"HOME": str(home)}),
              mock.patch.object(verify_pending.forge_api, "logged_in", return_value=True),
              mock.patch.object(verify_pending.agent_platform, "read_registry", return_value=entries),
              mock.patch.object(vx, "project_source", source),
              mock.patch.object(vr, "pass_repo", pass_repo),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            return verify_pending.main(["run", "--host", "mbp"])

    def test_one_run_hands_one_store_under_home_to_every_project(self):
        pass_repo = mock.Mock(return_value=[])
        code = self.run_main(pass_repo)
        self.assertEqual(code, 0)
        self.assertEqual(pass_repo.call_count, 2)
        stores = [call.kwargs["interruptions"] for call in pass_repo.call_args_list]
        self.assertIs(stores[0], stores[1])
        self.assertEqual(stores[0].path, self.home / ".agents" / "state" / "verify-pending" / "interrupted.json")

    def test_a_run_catches_sigterm_and_sighup_while_it_passes_the_projects(self):
        seen = []
        pass_repo = mock.Mock(side_effect=lambda *a, **k: seen.append(
            (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP))) or [])
        before = signal.getsignal(signal.SIGTERM)
        code = self.run_main(pass_repo)
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 2)
        for handler in (h for pair in seen for h in pair):
            self.assertTrue(callable(handler))
            self.assertNotIn(handler, (signal.SIG_DFL, signal.SIG_IGN))
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


if __name__ == "__main__":
    unittest.main()
