"""Contract tests for the engine's session reading (`agent_tools.delivery.engine_session`, #1514).

Covers reading a role file, rendering a prompt and reading a session result.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery.engine_session import (
    Reading, RoleError, read_result, read_role, render_prompt,
)

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "home/common/claude-code/agents"
ZERO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
DENIAL = {"tool_name": "Write", "tool_use_id": "toolu_01",
          "tool_input": {"file_path": "/etc/hosts"}}
RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 12345,
          "num_turns": 7, "result": "Status: stuck. I could not draft it.", "session_id": "x",
          "total_cost_usd": 0.4321,
          "usage": {"input_tokens": 11, "cache_creation_input_tokens": 22,
                    "cache_read_input_tokens": 33, "output_tokens": 44},
          "permission_denials": [DENIAL],
          "structured_output": {"status": "drafted", "summary": "s", "items": []}}


def raw(**overrides) -> bytes:
    document = dict(RESULT)
    document.update(overrides)
    return json.dumps({key: value for key, value in document.items()
                       if value is not ...}).encode()


class ReadResultTest(unittest.TestCase):
    def test_a_normal_result_gives_its_reply_prose_denials_and_measurements(self):
        self.assertEqual(read_result(json.dumps(RESULT).encode()), Reading(
            reply={"status": "drafted", "summary": "s", "items": []},
            prose="Status: stuck. I could not draft it.", denials=[DENIAL],
            subtype="success", wall_seconds=12.345, turns=7,
            tokens={"input": 11, "cache_write": 22, "cache_read": 33, "output": 44},
            spend_usd=0.4321))

    def test_no_structured_output_gives_no_reply_but_keeps_prose_and_measurements(self):
        reading = read_result(raw(structured_output=...))
        self.assertIsNone(reading.reply)
        self.assertEqual(reading.prose, "Status: stuck. I could not draft it.")
        self.assertEqual(reading.turns, 7)
        for value in (None, [1], "drafted"):
            with self.subTest(value=value):
                self.assertIsNone(read_result(raw(structured_output=value)).reply)

    def test_unreadable_stdout_reads_as_nothing(self):
        nothing = Reading(None, None, [], None, None, 0, dict(ZERO_TOKENS), 0)
        for stdout in (b"", b"not json", b"[1]", b'{"a":1,"a":2}',
                       b'{"num_turns":3,"num_turns":4}', b'{"num_turns":3,"total_cost_usd":NaN}'):
            with self.subTest(stdout=stdout):
                self.assertEqual(read_result(stdout), nothing)

    def test_invalid_measurements_read_as_zero(self):
        reading = read_result(raw(num_turns=True, total_cost_usd=-1, duration_ms=-5,
                                  usage={"input_tokens": "3"}))
        self.assertEqual((reading.turns, reading.spend_usd, reading.wall_seconds,
                          reading.tokens), (0, 0, None, ZERO_TOKENS))
        self.assertEqual(read_result(raw(num_turns=-1)).turns, 0)


def role_text(**fields: str) -> str:
    lines = {"name": None, "model": "opus", "effort": "high"}
    lines.update(fields)
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in lines.items()
                             if value is not None) + "---\nBody.\n"


class RoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def put(self, name: str, text: str) -> None:
        (self.directory / f"{name}.md").write_text(text, encoding="utf-8")

    def test_the_four_role_files_read_their_model_effort_tools_and_body(self):
        def listed(text: str, key: str):
            found = re.search(rf"^{key}: (.+)$", text, re.M)
            if found is None:
                return None
            return tuple(part.strip() for part in found.group(1).split(",") if part.strip())

        for name in ("planner", "implementer", "reviewer", "reviewer-lite"):
            shutil.copy(AGENTS / f"{name}.md", self.directory / f"{name}.md")
            text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
            with self.subTest(role=name):
                role = read_role(self.directory, name)
                self.assertEqual(role.name, name)
                self.assertEqual(role.model, re.search(r"^model: (.+)$", text, re.M).group(1))
                self.assertEqual(role.effort, re.search(r"^effort: (.+)$", text, re.M).group(1))
                self.assertEqual(role.tools, listed(text, "tools"))
                self.assertEqual(role.disallowed, listed(text, "disallowedTools"))
                self.assertEqual(role.body, text.partition("\n---\n")[2])
        self.assertIn("Agent(Explore)", read_role(self.directory, "planner").tools)
        implementer = read_role(self.directory, "implementer")
        self.assertIsNone(implementer.tools)
        self.assertTrue(implementer.disallowed)

    def test_a_role_file_that_cannot_give_a_role_is_refused(self):
        cases = {
            "a role outside the four": ("clerk", role_text()),
            "an absent file": ("planner", None),
            "no frontmatter": ("planner", "just text\n"),
            "no model": ("planner", role_text(model=None)),
            "an empty effort": ("planner", role_text(effort="")),
            "another role's name": ("planner", role_text(name="reviewer")),
            "tools with no name": ("planner", role_text(tools=",")),
            "not UTF-8": ("planner", None),
        }
        for label, (name, text) in cases.items():
            with self.subTest(label):
                for leftover in self.directory.iterdir():
                    leftover.unlink()
                if label == "not UTF-8":
                    (self.directory / f"{name}.md").write_bytes(b"---\nmodel: \xff\n---\n")
                elif text is not None:
                    self.put(name, text)
                with self.assertRaises(RoleError) as caught:
                    read_role(self.directory, name)
                self.assertIn(name, str(caught.exception))

    def test_a_role_value_that_would_put_a_forbidden_word_in_the_argv_is_refused(self):
        cases = (
            ("model", {"model": "--agent"}),
            ("effort", {"effort": "bypassPermissions"}),
            ("model", {"model": "opus --bare"}),
            ("tools", {"tools": "Read, --bare"}),
            ("disallowedTools", {"disallowedTools": "Write, --dangerously-skip-permissions"}),
            ("tools", {"tools": "Read,bypassPermissions"}),
            ("tools", {"tools": "Read, --setting-sources"}),
            ("effort", {"effort": "high medium"}),
        )
        for field, fields in cases:
            with self.subTest(fields=fields):
                self.put("planner", role_text(**fields))
                with self.assertRaises(RoleError) as caught:
                    read_role(self.directory, "planner")
                self.assertIn(field, str(caught.exception))
                self.assertIn("planner", str(caught.exception))
        self.put("planner", role_text(tools="Read, Bash(git status:*)"))
        self.assertEqual(read_role(self.directory, "planner").tools,
                         ("Read", "Bash(git status:*)"))


class PromptTest(unittest.TestCase):
    def test_placeholders_take_their_argument_words(self):
        self.assertEqual(
            render_prompt("Draft {{run.issue}} after {{ scope.items }}.",
                          (("run.issue", 1514), ("scope.items", ["a", "b"]))),
            'Draft 1514 after ["a","b"].')
        with self.assertRaises(ValueError):
            render_prompt("Use {{draft.summary}}.", ())


if __name__ == "__main__":
    unittest.main()
