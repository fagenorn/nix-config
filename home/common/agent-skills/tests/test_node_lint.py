"""The Node adapter's contract (#1467): the pinned tools record, ..."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import agent_platform

TIER = "integration"  # git worlds, nix-built node and eslint, the conformance engine

VALID = {"schema_version": 1, "node": "/abs/node", "eslint": "/abs/eslint"}


def write_record(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class NodeToolsRecordTest(unittest.TestCase):
    """The record the platform package pins node and eslint in."""

    def test_the_record_under_the_platform_root_names_the_two_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "home").mkdir()
            write_record(base / "root" / "node-tools.json", json.dumps(VALID))
            env = {"AGENT_PLATFORM_ROOT": str(base / "root"), "HOME": str(base / "home")}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(agent_platform.node_tools(), ("/abs/node", "/abs/eslint"))

    def test_with_no_root_the_record_is_read_from_home_share(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            expected = home / ".agents" / "share" / "node-tools.json"
            write_record(expected, json.dumps(VALID))
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                os.environ.pop("AGENT_PLATFORM_ROOT", None)
                self.assertEqual(agent_platform.node_tools(), ("/abs/node", "/abs/eslint"))
                self.assertEqual(agent_platform.node_tools_path(), expected)

    def test_a_non_empty_root_never_falls_back_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "root").mkdir()
            write_record(base / "home" / ".agents" / "share" / "node-tools.json", json.dumps(VALID))
            env = {"AGENT_PLATFORM_ROOT": str(base / "root"), "HOME": str(base / "home")}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(agent_platform.NodeToolsError):
                    agent_platform.node_tools()

    def test_a_missing_or_malformed_record_is_refused(self) -> None:
        cases = {
            "no file": None,
            "not json": "not json",
            "not an object": "[]",
            "member missing": json.dumps({"schema_version": 1, "node": "/n"}),
            "extra member": json.dumps({**VALID, "extra": 1}),
            "schema version 2": json.dumps({**VALID, "schema_version": 2}),
            "schema version bool": json.dumps({**VALID, "schema_version": True}),
            "relative node": json.dumps({**VALID, "node": "node"}),
            "empty eslint": json.dumps({**VALID, "eslint": ""}),
        }
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                root.mkdir()
                if text is not None:
                    write_record(root / "node-tools.json", text)
                with mock.patch.dict(os.environ, {"AGENT_PLATFORM_ROOT": str(root)}):
                    with self.assertRaises(agent_platform.NodeToolsError) as caught:
                        agent_platform.node_tools()
                self.assertIn("node-tools.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
