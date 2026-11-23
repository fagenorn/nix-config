"""Contract tests for the engine's reaping of its sessions (`agent_tools.delivery.engine_session.reaping`, #1517).

Covers when a stop closes the session registry and that no session is spawned after it closes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_session
from agent_tools.delivery.engine_session import launch

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReapingTest(unittest.TestCase):
    def test_only_a_stop_in_the_main_thread_closes_the_session_registry(self):
        script = textwrap.dedent("""
            import json, sys, threading
            from agent_tools.delivery import engine_session as session

            codes, ending = [], []

            def run():
                ending.append(session.ending())
                codes.append(session.launch([sys.executable, "-c", "pass"], ".", "",
                                            on_start=lambda pid: None).exit_code)

            try:
                with session.reaping():
                    raise ValueError("an ordinary exception")
            except ValueError:
                pass
            run()

            def worker():
                try:
                    with session.reaping():
                        raise KeyboardInterrupt
                except KeyboardInterrupt:
                    pass

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            run()
            try:
                with session.reaping():
                    raise KeyboardInterrupt
            except KeyboardInterrupt:
                pass
            run()
            run()
            print(json.dumps({"codes": codes, "ending": ending}))
        """)

        ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                             env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")},
                             timeout=60)

        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout),
                         {"codes": [0, 0, 127, 127], "ending": [False, False, True, True]})

    def test_a_sigterm_the_interpreter_has_taken_ends_the_engine_before_the_main_thread_runs_it(self):
        script = textwrap.dedent("""
            import json, os, signal
            from agent_tools.delivery import engine_session as session

            seen = []
            with session.reaping():
                wake = signal.set_wakeup_fd(-1)  # the descriptor the C handler writes to
                signal.set_wakeup_fd(wake)
                os.write(wake, bytes([signal.SIGINT]))
                seen.append(session.ending())
                os.write(wake, bytes([signal.SIGTERM]))
                seen.append(session.ending())
            print(json.dumps({"seen": seen, "after": session.ending()}))
        """)

        ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                             env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")},
                             timeout=60)

        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout), {"seen": [False, True], "after": True})

    def test_a_session_is_never_spawned_after_the_registry_closes(self):
        real = subprocess.Popen
        closers: list[threading.Thread] = []
        closed_at_spawn: list[bool] = []

        def popen(*args, **kwargs):
            # A shutdown reaching the registry just as a worker is about to spawn its session.
            closer = threading.Thread(target=engine_session._reap)
            closers.append(closer)
            closer.start()
            closer.join(0.5)
            closed_at_spawn.append(engine_session._closed)
            return real(*args, **kwargs)

        with mock.patch.object(engine_session, "_closed", False), \
                mock.patch.object(subprocess, "Popen", popen):
            launched = launch(["sleep", "30"], tempfile.gettempdir(), "",
                              on_start=lambda pid: None)
            for closer in closers:
                closer.join(30)
        self.assertEqual(closed_at_spawn, [False])
        self.assertEqual(launched.exit_code, -signal.SIGKILL)
