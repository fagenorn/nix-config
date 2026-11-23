"""The approve case's quick shutdown, publish-woken waits and copied reconcile repository (#1615).

Run: just agent-workflow-tests
"""

from __future__ import annotations

import socketserver
import sys
import threading
import time
import types
import unittest
from unittest import mock

from agent_tools.console import service

from . import approve_case_support as case_support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from .approve_case_support import PENDING, SERVER_POLL_SECONDS, awaited, quick_serve_forever, reconciled
from .test_console_approve_service import ApproveCase
from .test_console_register_service import READY, Case, Fake, git, reconcile_repository

TIER = "integration"  # every case runs the approve service against git repositories and a served socket


class QuickShutdownTest(ApproveCase):
    def watch_polls(self):
        seen = []
        changed = threading.Condition()

        class Recording(socketserver._ServerSelector):
            def select(self, timeout=None):
                with changed:
                    seen.append((next(iter(self.get_map().values())).fileobj, timeout))
                    changed.notify_all()
                return super().select(timeout)

        patcher = mock.patch.object(socketserver, "_ServerSelector", Recording)
        patcher.start()
        self.addCleanup(patcher.stop)

        def served(server):
            with changed:
                changed.wait_for(lambda: any(obj is server for obj, _ in seen), 5)
                return [timeout for obj, timeout in seen if obj is server]
        return served

    def test_a_case_console_serves_with_the_quick_shutdown_poll(self):
        served = self.watch_polls()
        self.start(Fake(plan=READY))
        server = self.svc._server
        timeouts = served(server)
        self.svc.close()
        self.assertTrue(timeouts)
        self.assertEqual(set(timeouts), {SERVER_POLL_SECONDS})
        self.assertLess(SERVER_POLL_SECONDS, 0.5)

    def test_a_restarted_console_serves_with_the_quick_shutdown_poll(self):
        served = self.watch_polls()
        self.start(Fake(plan=READY))
        self.restart()
        server = self.svc._server
        timeouts = served(server)
        self.svc.close()
        self.assertTrue(timeouts)
        self.assertEqual(set(timeouts), {SERVER_POLL_SECONDS})


class QuickShutdownPatchTest(unittest.TestCase):
    def test_the_quick_poll_patch_ends_with_the_test(self):
        class Probe(ApproveCase):
            def test_probe(self):
                self.start(Fake(plan=READY))
                self.assertIs(service.ConsoleServer.serve_forever, quick_serve_forever)

        result = unittest.TestResult()
        Probe("test_probe").run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertIs(service.ConsoleServer.serve_forever, socketserver.BaseServer.serve_forever)


class PublishWaitTest(ApproveCase):
    def clock(self, sleeps, on_sleep=None):
        """A stand-in `time` for both test modules' helpers: it records every sleep, then really sleeps."""
        real_sleep = time.sleep

        def sleep(seconds):
            sleeps.append(seconds)
            if on_sleep is not None:
                on_sleep()
            real_sleep(seconds)
        stand_in = types.SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        for module in (sys.modules[__name__], case_support, sys.modules[Case.__module__]):
            patcher = mock.patch.object(module, "time", stand_in)
            patcher.start()
            self.addCleanup(patcher.stop)
        return stand_in

    def controlled(self, now):
        """A stand-in `time` on a controlled clock, and a stand-in console whose waits advance it."""
        def sleep(seconds):
            raise AssertionError("slept")
        waits = []

        def wait(seen, timeout):
            waits.append((seen, timeout))
            now[0] += timeout
            return None
        patcher = mock.patch.object(
            case_support, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
        patcher.start()
        self.addCleanup(patcher.stop)
        return types.SimpleNamespace(version=7, closing=False, wait_for_change=wait), waits

    def test_registered_returns_on_the_publish_without_sleeping(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.start(Fake(plan=READY, block=gate))
        repo = reconciled(self.parent, contract=True)
        sleeps = []
        self.clock(sleeps, on_sleep=gate.set)
        real = self.svc.wait_for_change
        with mock.patch.object(self.svc, "wait_for_change",
                               side_effect=lambda seen, timeout: (gate.set(), real(seen, timeout))[1]) as spy:
            shown = self.registered(repo)
        self.assertEqual((shown["root"], shown["status"]), (str(repo), "done"))
        self.assertEqual(sleeps, [])
        self.assertTrue(spy.called)

    def test_a_wait_on_a_closed_console_waits_out_its_recheck(self):
        self.start(Fake(plan=READY))
        self.svc.close()
        sleeps = []
        self.clock(sleeps)
        found = awaited(self.svc, lambda: PENDING, bound=0.12, recheck=0.05)
        self.assertIs(found, PENDING)
        self.assertTrue(sleeps)
        self.assertLessEqual(len(sleeps), 4)
        self.assertTrue(all(s <= 0.05 for s in sleeps), sleeps)

    def test_awaited_does_not_probe_once_its_deadline_has_passed(self):
        now = [0.0]
        svc, waits = self.controlled(now)
        probes = []
        found = awaited(svc, lambda: (probes.append(now[0]), "late" if now[0] >= 1.0 else PENDING)[1],
                        bound=1.0, recheck=0.5)
        self.assertIs(found, PENDING)
        self.assertEqual(probes, [0.0, 0.5])
        self.assertEqual(waits, [(7, 0.5), (7, 0.5)])

    def test_awaited_returns_an_event_within_its_bound(self):
        now = [0.0]
        svc, waits = self.controlled(now)
        probes = []
        found = awaited(svc, lambda: (probes.append(now[0]), "on time" if now[0] >= 0.5 else PENDING)[1],
                        bound=1.0, recheck=0.5)
        self.assertEqual(found, "on time")
        self.assertEqual(probes, [0.0, 0.5])
        self.assertEqual(waits, [(7, 0.5)])

    def test_awaited_returns_a_falsey_answer_at_once(self):
        now = [0.0]
        svc, waits = self.controlled(now)
        for answer in (None, [], 0, ""):
            with self.subTest(answer=answer):
                self.assertIs(awaited(svc, lambda: answer, bound=1.0, recheck=0.5), answer)
        self.assertEqual(waits, [])

    def test_settled_of_nothing_returns_at_once_on_an_idle_service(self):
        self.start(Fake(plan=READY))
        started = time.monotonic()
        self.assertEqual(self.settled(0, bound=5), [])
        self.assertLess(time.monotonic() - started, 5)

    def test_until_returns_a_completed_step_whose_registration_view_is_none(self):
        self.start(Fake(plan=READY))
        with mock.patch.object(self.svc, "_approving", False), \
                mock.patch.object(self, "steps", return_value=["opened"]), \
                mock.patch.object(self, "view", return_value={"registration": None}):
            started = time.monotonic()
            self.assertIsNone(self.until("opened", bound=5))
            self.assertLess(time.monotonic() - started, 5)

    def test_settled_row_never_returns_the_previous_registrations_row(self):
        self.start(Fake(plan=READY))
        old, new = {"root": "r", "result": "registered"}, {"root": "r", "result": "failed"}
        current = [old]
        self.svc._registering = "r"
        self.addCleanup(setattr, self.svc, "_registering", None)
        finish = threading.Thread(target=lambda: self.finish(current, new))
        started = []

        def rows(kind):
            found = [(1, payload) for payload in current]
            if not started:
                started.append(True)
                finish.start()
                finish.join(0.3)
            return found

        with mock.patch.object(self, "rows", side_effect=rows):
            self.assertEqual(self.settled_row("r", bound=10), new)
        finish.join(10)

    def finish(self, current, new):
        "What a registration's worker does under the lock: record the result, then clear the run mark."
        with self.svc._ingest:
            current.append(new)
            self.svc._registering = None

    def test_the_reconcile_templates_are_forgotten_with_their_directory(self):
        with mock.patch.dict(case_support._RECONCILE_TEMPLATES, clear=True):
            first = reconciled(self.parent / "one")
            self.assertTrue(first.is_dir())
            root = case_support._RECONCILE_TEMPLATES["root"]
            case_support.forget_reconcile_templates(root)
            self.assertFalse(root.exists())
            self.assertEqual(case_support._RECONCILE_TEMPLATES, {})
            second = reconciled(self.parent / "two")
            self.assertTrue(second.is_dir())
            self.assertNotEqual(case_support._RECONCILE_TEMPLATES["root"], root)
            case_support.forget_reconcile_templates(case_support._RECONCILE_TEMPLATES["root"])

    def test_wait_done_fails_in_its_words_once_its_bound_passes(self):
        self.start(Fake(plan=READY))
        started = time.monotonic()
        with self.assertRaises(AssertionError) as raised:
            self.wait_done(self.parent / "never", bound=0.2)
        self.assertIn("no registration result", str(raised.exception))
        self.assertGreaterEqual(time.monotonic() - started, 0.2)

    def test_until_reads_steps_and_view_under_the_ingest_lock(self):
        self.opened()
        held = []
        real_steps, real_view = self.steps, self.view
        with mock.patch.object(self, "steps", side_effect=lambda: (
                held.append(self.svc._ingest.locked()), real_steps())[1]), \
                mock.patch.object(self, "view", side_effect=lambda: (
                    held.append(self.svc._ingest.locked()), real_view())[1]):
            shown = self.until("opened")
        self.assertEqual(shown, real_view()["registration"])
        self.assertTrue(held)
        self.assertTrue(all(held), held)


class ReconciledCopyTest(ApproveCase):
    def test_a_reconciled_copy_is_the_reconcile_build_with_its_own_origin(self):
        with mock.patch.object(case_support, "reconcile_repository", wraps=reconcile_repository) as spy:
            first = reconciled(self.parent / "a", contract=True)
            second = reconciled(self.parent / "b", contract=True)
        git(first, "diff-index", "--quiet", "HEAD", "--")
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(first, (self.parent / "a" / "reconcile").resolve())
        self.assertEqual(git(first, "config", "--get", "remote.origin.url").strip(),
                         str(self.parent / "a" / "origin.git"))
        self.assertEqual(git(first, "log", "--format=%s"), "legacy\none\n")
        self.assertEqual(git(first, "branch", "--show-current").strip(), "main")
        self.assertTrue((first / ".agents/project.json").is_file())
        self.assertEqual((first / ".out-of-scope/a.md").read_text(), "# rejected a\n")
        self.assertEqual(git(first, "status", "--porcelain"), "")
        git(first, "commit", "-q", "--allow-empty", "-m", "x")
        git(first, "push", "-q", "origin", "main")
        self.assertNotEqual(git(self.parent / "a" / "origin.git", "rev-parse", "main"),
                            git(self.parent / "b" / "origin.git", "rev-parse", "main"))
        self.assertEqual(second, (self.parent / "b" / "reconcile").resolve())

    def test_a_reconciled_copy_without_a_contract_has_no_contract_file(self):
        root = reconciled(self.parent / "c")
        self.assertFalse((root / ".agents").exists())
        self.assertEqual(git(root, "log", "--format=%s"), "legacy\none\n")
