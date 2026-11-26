"""The replies and files a stubbed run uses to drive the verify fix rounds on the fixture project."""

from __future__ import annotations

from tests.engine_stubbed_world import IMPLEMENTED

def implementing(path: str, text: str, **members) -> dict:
    return {"reply": {**IMPLEMENTED["reply"], **members}, "commit": {"path": path, "text": text}}


NO_UNRELATED = {"test": "", "evidence": ""}
CHECK_FORMAT = r"""import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FormatTest(unittest.TestCase):
    def test_each_fixture_json_is_two_space_indented(self):
        for path in sorted((ROOT / "fixture").glob("*.json")):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            self.assertEqual(text, json.dumps(json.loads(text), indent=2) + "\n",
                             f"{relative} is not two-space indented")
"""
FORMAT = {"checks/check_format.py": CHECK_FORMAT}
FOUR_SPACES = '{\n    "greeting": "hello"\n}\n'
TWO_SPACES = '{\n  "greeting": "hello"\n}\n'
FOUR = implementing("fixture/greeting.json", FOUR_SPACES)
ATTESTED = {"whitespace_insignificant": True, "whitespace_evidence": "fixture/greeting.json: indentation only"}
PASS_ATTESTED = {"verdict": "pass", "findings": [], **ATTESTED}
PASS_PLAIN = {"verdict": "pass", "findings": [], "whitespace_insignificant": False,
              "whitespace_evidence": "not whitespace-only"}
RETESTED = {"reply": {"status": "done", "notes": "n", "tests": ["checks/check_format.py"], "clean": True},
            "same_head": {}}


def fixing(path: str, text: str, **reply) -> dict:
    """A verify fix reply that commits `text` to `path`, naming no file outside the diff and no unrelated test."""
    return {"reply": {"status": "done", "notes": "n", "tests": [], "outside_diff": [], "unrelated": NO_UNRELATED,
                      **reply},
            "commit": {"path": path, "text": text}}


TWO = fixing("fixture/greeting.json", TWO_SPACES, tests=["checks/check_format.py"])
