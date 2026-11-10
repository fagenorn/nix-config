"""Host agent-slot admission (#150): the declaration module the conformance check reads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agent_tools import host_admission

REPO = Path(__file__).resolve().parents[4]
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


class HostAdmissionTest(unittest.TestCase):
    def test_the_alternative_points_at_deliver_standard(self):
        self.assertEqual(host_admission.UNSUPPORTED_ALTERNATIVE, "/deliver-standard <issue>")

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "codex": {"support": "unsupported"}}))
        self.assertEqual(host_admission.validate_declaration(committed), committed)

    def test_invalid_declarations_are_refused(self):
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
                ("schema two", {"schema_version": 2, "routes": {"claude-code": supported}})):
            with self.subTest(label), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.validate_declaration(value)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")

    def test_load_reads_the_installed_file(self):
        with tempfile.TemporaryDirectory() as raw, \
                mock.patch.dict(os.environ, {"HOME": raw}):
            target = Path(raw) / ".agents/share/host-declaration.json"
            with self.assertRaises(host_admission.DeclarationError) as missing:
                host_admission.load_declaration()
            self.assertEqual(missing.exception.reason_code, "declaration_missing")
            target.parent.mkdir(parents=True)
            for label, text in (
                    ("not json", "{"),
                    ("duplicate key", '{"schema_version": 1, "schema_version": 1, "routes": '
                                      '{"claude-code": {"support": "supported", "agent_slots": 7}}}')):
                with self.subTest(label), self.assertRaises(host_admission.DeclarationError) as invalid:
                    target.write_text(text, encoding="utf-8")
                    host_admission.load_declaration()
                self.assertEqual(invalid.exception.reason_code, "declaration_invalid")
            committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
            target.write_text(COMMITTED_DECLARATION.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(host_admission.load_declaration(), committed)


if __name__ == "__main__":
    unittest.main()
