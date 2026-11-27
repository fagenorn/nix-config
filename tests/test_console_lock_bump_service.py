"""The console process runs the lock bump pass beside the service: flags, loop and one line per step.

Run: just agent-workflow-tests
"""
import contextlib
import io
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import approve, lock_bump
from agent_tools.console import console as console_module
from agent_tools.project_contract import agent_platform
from tests.test_console_lock_bump import ENTRIES, REV_B, FakeBuilder, FakeForge, FakeTracker
from tests.accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

FLAGS = ["--lock-bump-project", "fagenorn/engine-fixture", "--lock-bump-branch", "main",
         "--platform-repo", "fagenorn/nix-config"]


def bump_threads():
    return [thread for thread in threading.enumerate() if thread.name == lock_bump.LOCK_BUMP_THREAD]


class StubService:
    """A console service that is asked to stop as soon as it starts."""

    built = []
    closed = []
    handlers = []

    def __init__(self, *args, **kwargs):
        StubService.built.append(self)
        self.address = ("127.0.0.1", 1)

    def start(self):
        for handler in StubService.handlers:
            handler()

    def close(self):
        StubService.closed.append(self)


class RecordingBumper:
    constructed = []
    called = threading.Event()
    cancels = []

    def __init__(self, *args, **kwargs):
        RecordingBumper.constructed.append((args, kwargs))

    def __call__(self, cancel):
        RecordingBumper.cancels.append(cancel)
        RecordingBumper.called.set()
        return []


class ConsoleMainTest(unittest.TestCase):
    def setUp(self):
        for holder in (StubService.built, StubService.closed, StubService.handlers,
                       RecordingBumper.constructed, RecordingBumper.cancels):
            holder.clear()
        RecordingBumper.called.clear()
        self.starts = []

        def start(bumper, stop, seconds=lock_bump.LOCK_BUMP_SECONDS):
            self.starts.append(bumper)
            return real_start(bumper, stop, seconds)

        real_start = lock_bump.start
        for patch in (mock.patch.object(console_module.service, "ConsoleService", StubService),
                      mock.patch.object(console_module.lock_bump, "Bumper", RecordingBumper),
                      mock.patch.object(console_module.lock_bump, "start", start),
                      mock.patch.object(console_module.signal, "signal",
                                        side_effect=lambda number, handler: StubService.handlers.append(
                                            lambda: handler(number, None)))):
            patch.start()
            self.addCleanup(patch.stop)

    def main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return console_module.main(argv)

    def test_the_lock_bump_flags_run_the_bumper_beside_the_service_until_stopped(self):
        self.assertEqual(self.main(["--port", "0", *FLAGS]), 0)
        self.assertEqual(RecordingBumper.constructed,
                         [(("fagenorn/engine-fixture", "main", "fagenorn/nix-config"), {})])
        self.assertTrue(RecordingBumper.called.wait(5))
        self.assertTrue(RecordingBumper.cancels[0].is_set())
        self.assertEqual(bump_threads(), [])
        self.assertEqual(len(StubService.closed), 1)

    def test_without_the_flags_no_bumper_is_built(self):
        self.assertEqual(self.main(["--port", "0"]), 0)
        self.assertEqual((RecordingBumper.constructed, self.starts), ([], []))

    def test_a_partial_flag_set_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            self.main(FLAGS[:2])
        self.assertEqual((raised.exception.code, StubService.built), (2, []))

    def test_a_project_that_is_not_a_slug_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            self.main(["--lock-bump-project", "fixture", *FLAGS[2:]])
        self.assertEqual((raised.exception.code, StubService.built), (2, []))


class LoopTest(unittest.TestCase):
    def test_the_loop_passes_at_once_and_stops_with_its_event(self):
        stop, called, seen = threading.Event(), threading.Event(), []

        def bumper(cancel):
            seen.append(cancel)
            called.set()

        thread = lock_bump.start(bumper, stop, seconds=3600)
        self.assertTrue(called.wait(5))
        self.assertEqual(seen, [stop])
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_a_failing_pass_is_one_line_and_the_loop_goes_on(self):
        stop, second, calls = threading.Event(), threading.Event(), []

        def bumper(cancel):
            calls.append(cancel)
            if len(calls) == 1:
                raise RuntimeError("boom")
            second.set()

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            thread = lock_bump.start(bumper, stop, seconds=0.01)
            self.assertTrue(second.wait(5))
            stop.set()
            thread.join(5)
        self.assertIn("console: lock_bump_loop_failed RuntimeError: boom", err.getvalue())


class BumperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = io.StringIO()
        self.builder = FakeBuilder()

    def bumper(self, registry=lambda: ENTRIES):
        return lock_bump.Bumper(
            "octo/fixture", "main", "octo/platform", forge=FakeForge(), tracker=FakeTracker(),
            builder=self.builder, registry=registry, latest=lambda: REV_B,
            state_path=self.tmp / "lock-bumps.json", out=self.out)

    def test_each_step_is_one_line(self):
        self.bumper()(threading.Event())
        self.assertEqual(self.out.getvalue(), f"console: lock_bump octo/fixture opened {REV_B[:12]} 7 -\n")

    def test_a_refused_pass_is_one_failed_line_and_no_steps(self):
        reason = "the remote origin of /srv/fixture is not octo/fixture"
        self.builder.pin = mock.Mock(side_effect=lock_bump.BumpRefused(reason))
        self.assertEqual(self.bumper()(threading.Event()), [])
        self.assertEqual(self.out.getvalue(), f"console: lock_bump_failed octo/fixture BumpRefused: {reason}\n")

    def test_an_unreadable_registry_is_one_failed_line(self):
        def unreadable():
            raise agent_platform.PlatformManifestError("registry", [{"pointer": "", "message": "x"}])

        self.assertEqual(self.bumper(unreadable)(threading.Event()), [])
        self.assertTrue(self.out.getvalue().startswith("console: lock_bump_failed octo/fixture PlatformManifestError: "))
        self.assertEqual(len(self.out.getvalue().splitlines()), 1)

    def test_a_cancelled_pass_prints_nothing(self):
        self.builder.pin = mock.Mock(side_effect=approve.Cancelled())
        self.assertEqual(self.bumper()(threading.Event()), [])
        self.assertEqual(self.out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
