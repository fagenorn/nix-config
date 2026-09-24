"""Host agent-slot admission (#150): declaration, host-route, claims, control admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
POLICY = REPO / "home/common/agent-skills/artifact-budget-policy.json"
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"
ALTERNATIVE = "/from-issue <issue> --auto"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


def install_declaration(home, value):
    """Write `value` (JSON, or a str verbatim) as HOME's declaration; None removes it."""
    target = Path(home) / ".agents/share/host-declaration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if value is not None:
        target.write_text(value if isinstance(value, str) else json.dumps(value),
                          encoding="utf-8")
    return target


def boundary(case, raw):
    """Pipe raw bytes through the workflow-response boundary; return the parsed value."""
    checked = subprocess.run(
        [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
         "workflow-response", "--input", "-", "--policy", str(POLICY)],
        input=raw, capture_output=True, check=False)
    case.assertEqual((checked.returncode, checked.stdout), (0, raw), checked.stderr)
    return json.loads(raw)


class HostRouteTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def host_route(self, route):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), "host-route", "--route", route],
            capture_output=True, check=False, env={**os.environ, "HOME": str(self.home)})

    def answer(self, route):
        completed = self.host_route(route)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return boundary(self, completed.stdout)

    @staticmethod
    def unsupported(route, reason):
        return {"interface_version": 1, "kind": "host_route", "route": route,
                "support": "unsupported", "agent_slots": None,
                "reason_code": reason, "alternative": ALTERNATIVE}

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "codex": {"support": "unsupported"}}))
        install_declaration(self.home, committed)
        self.assertEqual(self.answer("claude-code"), {
            "interface_version": 1, "kind": "host_route", "route": "claude-code",
            "support": "supported", "agent_slots": 7, "reason_code": None,
            "alternative": None})
        self.assertEqual(self.answer("codex"),
                         self.unsupported("codex", "declared_unsupported"))

    def test_every_reason_code_is_a_typed_answer(self):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 4}}))
        self.assertEqual(self.answer("claude-code")["agent_slots"], 4)
        self.assertEqual(self.answer("gemini"),
                         self.unsupported("gemini", "route_undeclared"))
        install_declaration(self.home, None)
        self.assertEqual(self.answer("claude-code"),
                         self.unsupported("claude-code", "declaration_missing"))

    def test_invalid_declarations_answer_declaration_invalid(self):
        supported = {"support": "supported", "agent_slots": 7}
        for label, value in (
                ("below the floor", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": 3}})),
                ("boolean slots", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": True}})),
                ("host metric", {**declaration(**{"claude-code": supported}), "cpu": 8}),
                ("route member", declaration(**{"claude-code": {**supported, "memory": 1}})),
                ("unsupported with slots", declaration(codex={
                    "support": "unsupported", "agent_slots": 4})),
                ("reserved direct", declaration(direct=supported)),
                ("bad route name", declaration(**{"Claude Code": supported})),
                ("no routes", declaration()),
                ("schema two", {"schema_version": 2, "routes": {"claude-code": supported}}),
                ("duplicate key", '{"schema_version": 1, "schema_version": 1, "routes": '
                                  '{"claude-code": {"support": "supported", "agent_slots": 7}}}'),
                ("not json", "{"),
                ("integer past the conversion limit", '{"schema_version": ' + "1" * 5000
                                                      + ', "routes": {}}'),
                ("nesting past the recursion limit", "[" * 100000 + "]" * 100000)):
            with self.subTest(label):
                install_declaration(self.home, value)
                self.assertEqual(self.answer("claude-code"),
                                 self.unsupported("claude-code", "declaration_invalid"))

    def test_usage_errors_exit_two_and_nothing_is_written(self):
        install_declaration(self.home, json.loads(
            COMMITTED_DECLARATION.read_text(encoding="utf-8")))
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        for route in ("direct", "Claude Code", ""):
            with self.subTest(route=route):
                completed = self.host_route(route)
                self.assertEqual((completed.returncode, completed.stdout), (2, b""))
        self.answer("claude-code")
        self.assertEqual(
            sorted(path.relative_to(self.home) for path in self.home.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
