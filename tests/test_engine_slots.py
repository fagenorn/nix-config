"""Contract tests for the engine's agent slots (#1522): `engine deliver` runs only on a host whose
declaration admits the engine route.

Each case runs `engine deliver` as a child process against the stand-in project command
(tests/fixtures/engine-deliver/standin.py), with the host declaration the case writes.
"""

from __future__ import annotations

import unittest

from tests.test_engine_deliver import EngineProject, step

TIER = "integration"  # every case runs `engine deliver` against the stand-in command

CLAUDE_CODE = {"support": "supported", "agent_slots": 7}


class RouteRefusalTest(unittest.TestCase):
    def test_deliver_refuses_each_route_the_declaration_does_not_admit(self) -> None:
        cases = (
            ("missing", None, "declaration_missing"),
            ("invalid", "{", "declaration_invalid"),
            ("unsupported",
             {"schema_version": 1,
              "routes": {"claude-code": CLAUDE_CODE, "engine": {"support": "unsupported"}}},
             "declared_unsupported"),
            ("undeclared",
             {"schema_version": 1,
              "routes": {"claude-code": CLAUDE_CODE, "codex": {"support": "unsupported"}}},
             "route_undeclared"),
        )
        for label, value, code in cases:
            with self.subTest(label):
                project = EngineProject(self)
                project.declare(value)
                procedures = project.procedures([step("a", "standin-record", "done")])
                done = project.deliver(procedures)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith(f"engine: {code}:"), done.stderr)
                self.assertEqual(project.runs(), [])
                self.assertFalse(project.record.exists())
                self.assertFalse((project.world.home / ".agents/state/engine/runs").exists())

    def test_a_declaration_admitting_the_engine_route_runs(self) -> None:
        project = EngineProject(self)
        project.declare({"schema_version": 1,
                         "routes": {"engine": {"support": "supported", "agent_slots": 1}}})
        done = project.deliver(project.procedures([step("a", "standin-json", "done")]))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(project.runs()), 1)
