"""The procedure format's terms the engine and the check share live in `procedure_terms`."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from agent_tools.delivery import procedure_check, procedure_terms

TIER = "integration"

DELIVERY = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery"


def imported_modules(source: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


class TermsTest(unittest.TestCase):
    def test_the_ledger_session_and_commands_import_the_terms_not_the_validator(self):
        for name in ("engine_ledger.py", "engine_session.py", "engine_commands.py"):
            with self.subTest(name):
                modules = imported_modules(DELIVERY / name)
                self.assertNotIn("agent_tools.delivery.procedure_check", modules)
                self.assertIn("agent_tools.delivery.procedure_terms", modules)

    def test_the_validator_uses_the_engines_terms(self):
        for name in ("STAGES", "NEEDS", "ROLES", "WAITS", "NAME_RE", "INPUT_RE", "PLACEHOLDER_RE",
                     "OUT_OF_BOUNDS", "NO_REPLY", "CLAIM_LOST", "QUOTA_WAIT", "SUPERSEDED",
                     "readable_format", "_inside", "_strict_load"):
            with self.subTest(name):
                self.assertIs(getattr(procedure_check, name), getattr(procedure_terms, name))


if __name__ == "__main__":
    unittest.main()
