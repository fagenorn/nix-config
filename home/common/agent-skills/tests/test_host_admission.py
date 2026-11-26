"""Host agent-slot admission (#150): the declaration module the conformance check reads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agent_tools.delivery import host_admission

REPO = Path(__file__).resolve().parents[4]
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"
HOST_DECLARATIONS = REPO / "home/common/agent-skills/host-declarations"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


class HostAdmissionTest(unittest.TestCase):
    def test_the_alternative_points_at_deliver_standard(self):
        self.assertEqual(host_admission.UNSUPPORTED_ALTERNATIVE, "/deliver-standard <issue>")

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "engine": {"support": "supported", "agent_slots": 8},
            "codex": {"support": "unsupported"}}))
        self.assertEqual(host_admission.validate_declaration(committed), committed)
        self.assertEqual(host_admission.verify_slots(committed), 1)
        self.assertIsNone(host_admission.verify_budget_seconds(committed))
        self.assertNotIn("verify_repository_slots", committed)
        self.assertEqual(host_admission.route_slots(committed, host_admission.ENGINE_ROUTE), 8)

    def test_the_eleven_m5_declaration_lets_nix_config_hold_two_verify_slots_and_jarbird_one(self):
        eleven = json.loads((HOST_DECLARATIONS / "eleven-m5.json").read_text(encoding="utf-8"))
        shared = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(host_admission.validate_declaration(eleven), eleven)
        self.assertEqual(host_admission.verify_slots(eleven), 2)
        self.assertEqual(host_admission.verify_budget_seconds(eleven), 600)
        self.assertEqual(eleven["verify_repository_slots"],
                         {"fagenorn/nix-config": 2, "elevenyellow/jarbird": 1})
        self.assertEqual(host_admission.repository_verify_slots(eleven, "fagenorn/nix-config"), 2)
        self.assertEqual(host_admission.repository_verify_slots(eleven, "elevenyellow/jarbird"), 1)
        self.assertEqual(host_admission.repository_verify_slots(eleven, "example/other"), 1)
        self.assertEqual({k: v for k, v in eleven.items()
                          if k not in ("verify_slots", "verify_budget_seconds",
                                       "verify_repository_slots")}, shared)

    def test_every_host_declaration_names_a_flake_host_and_validates(self):
        flake = (REPO / "flake.nix").read_text(encoding="utf-8")
        files = sorted(HOST_DECLARATIONS.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                self.assertIn(f'hostname = "{path.stem}";', flake)
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(host_admission.validate_declaration(value), value)

    def test_the_engine_route_counts_one_slot_per_live_session(self):
        one = declaration(engine={"support": "supported", "agent_slots": 1})
        self.assertEqual(host_admission.validate_declaration(one), one)
        self.assertEqual(host_admission.route_slots(one, "engine"), 1)
        self.assertEqual(host_admission.minimum_slots("engine"),
                         host_admission.ENGINE_SESSION_SLOTS)
        self.assertEqual(host_admission.ENGINE_SESSION_SLOTS, 1)
        self.assertEqual(host_admission.minimum_slots("claude-code"),
                         host_admission.MINIMUM_SUPPORTED_SLOTS)
        self.assertEqual(host_admission.MINIMUM_SUPPORTED_SLOTS, 4)
        for bad in (0, True):
            value = declaration(engine={"support": "supported", "agent_slots": bad})
            with self.subTest(bad), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.validate_declaration(value)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")

    def test_route_slots_names_why_a_route_is_not_admitted(self):
        value = declaration(**{"claude-code": {"support": "supported", "agent_slots": 7},
                               "codex": {"support": "unsupported"}})
        self.assertEqual(host_admission.route_slots(value, "claude-code"), 7)
        for route, code in (("engine", "route_undeclared"), ("codex", "declared_unsupported")):
            with self.subTest(route), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.route_slots(value, route)
            self.assertEqual(raised.exception.reason_code, code)

    def test_verify_slots_is_an_optional_top_level_count(self):
        supported = {"support": "supported", "agent_slots": 7}
        with_slots = {**declaration(**{"claude-code": supported}), "verify_slots": 3}
        without = declaration(**{"claude-code": supported})
        self.assertEqual(host_admission.validate_declaration(with_slots), with_slots)
        self.assertEqual(host_admission.validate_declaration(without), without)
        self.assertEqual(host_admission.verify_slots(with_slots), 3)
        self.assertEqual(host_admission.verify_slots(without), 1)
        self.assertEqual(host_admission.DEFAULT_VERIFY_SLOTS, 1)

    def test_a_verify_slots_that_is_not_a_positive_int_is_refused(self):
        supported = {"support": "supported", "agent_slots": 7}
        for bad in (0, -1, True, 1.5, "2"):
            value = {**declaration(**{"claude-code": supported}), "verify_slots": bad}
            with self.subTest(bad), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.validate_declaration(value)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")

    def test_verify_repository_slots_is_an_optional_map_of_repository_to_count(self):
        supported = {"support": "supported", "agent_slots": 7}
        named = {**declaration(**{"claude-code": supported}),
                 "verify_repository_slots": {"example/alpha": 2, "example/beta": 1,
                                             "example/.github": 3}}
        empty = {**declaration(**{"claude-code": supported}), "verify_repository_slots": {}}
        without = declaration(**{"claude-code": supported})
        self.assertEqual(host_admission.validate_declaration(named), named)
        self.assertEqual(host_admission.validate_declaration(empty), empty)
        self.assertEqual(host_admission.validate_declaration(without), without)
        self.assertEqual(host_admission.repository_verify_slots(named, "example/alpha"), 2)
        self.assertEqual(host_admission.repository_verify_slots(named, "example/beta"), 1)
        self.assertEqual(host_admission.repository_verify_slots(named, "example/gamma"), 1)
        self.assertEqual(host_admission.repository_verify_slots(named, "example/.github"), 3)
        self.assertEqual(host_admission.repository_verify_slots(empty, "example/alpha"), 1)
        self.assertEqual(host_admission.repository_verify_slots(without, "example/alpha"), 1)
        self.assertEqual(host_admission.DEFAULT_REPOSITORY_VERIFY_SLOTS, 1)

    def test_a_verify_repository_slots_that_is_not_a_map_of_owner_repo_to_a_positive_int_is_refused(self):
        supported = {"support": "supported", "agent_slots": 7}
        for bad in ([], "example/alpha", 2, {"example/alpha": 0}, {"example/alpha": -1},
                    {"example/alpha": True}, {"example/alpha": 1.5}, {"example/alpha": "2"},
                    {"Example/Alpha": 2}, {"alpha": 2}, {"a/b/c": 2}, {"/alpha": 2}, {"": 1},
                    {"example/.": 1}, {"example/..": 1}, {".example/alpha": 1}):
            value = {**declaration(**{"claude-code": supported}), "verify_repository_slots": bad}
            with self.subTest(bad=bad), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.validate_declaration(value)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")
            self.assertEqual(str(raised.exception), "verify_repository_slots")

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
            target.unlink()
            for label, make in (("directory", lambda: target.mkdir()),
                                ("dangling symlink", lambda: target.symlink_to(Path(raw) / "nowhere"))):
                with self.subTest(label), self.assertRaises(host_admission.DeclarationError) as unusable:
                    make()
                    host_admission.load_declaration()
                self.assertEqual(unusable.exception.reason_code, "declaration_invalid")
                if target.is_dir():
                    target.rmdir()
                else:
                    target.unlink()
            committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
            target.write_text(COMMITTED_DECLARATION.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(host_admission.load_declaration(), committed)

    def test_load_names_a_declaration_it_cannot_inspect_invalid_not_missing(self):
        with tempfile.TemporaryDirectory() as raw, \
                mock.patch.dict(os.environ, {"HOME": raw}):
            target = Path(raw) / ".agents/share/host-declaration.json"
            target.parent.mkdir(parents=True)
            target.write_text(COMMITTED_DECLARATION.read_text(encoding="utf-8"), encoding="utf-8")
            target.parent.chmod(0)
            try:
                if os.access(target, os.R_OK):
                    self.skipTest("the process bypasses directory permissions")
                with self.assertRaises(host_admission.DeclarationError) as raised:
                    host_admission.load_declaration()
            finally:
                target.parent.chmod(0o700)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")

    def test_verify_budget_seconds_is_an_optional_top_level_count(self):
        supported = {"support": "supported", "agent_slots": 7}
        with_budget = {**declaration(**{"claude-code": supported}), "verify_budget_seconds": 600}
        without = declaration(**{"claude-code": supported})
        self.assertEqual(host_admission.validate_declaration(with_budget), with_budget)
        self.assertEqual(host_admission.validate_declaration(without), without)
        self.assertEqual(host_admission.verify_budget_seconds(with_budget), 600)
        self.assertIsNone(host_admission.verify_budget_seconds(without))

    def test_a_verify_budget_seconds_that_is_not_a_positive_int_is_refused(self):
        supported = {"support": "supported", "agent_slots": 7}
        for bad in (0, -1, True, 1.5, "600"):
            value = {**declaration(**{"claude-code": supported}), "verify_budget_seconds": bad}
            with self.subTest(bad), self.assertRaises(host_admission.DeclarationError) as raised:
                host_admission.validate_declaration(value)
            self.assertEqual(raised.exception.reason_code, "declaration_invalid")


if __name__ == "__main__":
    unittest.main()
