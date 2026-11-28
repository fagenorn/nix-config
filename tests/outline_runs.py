"""A run-tree builder for the tests of an outline run's store; not a test module.

`RunTree` writes runs, their results, their `call` events and their end through `engine_ledger`, under a root the
test owns, with `engine_ledger.runs_root` patched to it for the test.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger

NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
AT = "2026-11-27T12:00:00Z"
NO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


class RunTree:
    def __init__(self, test_case: unittest.TestCase, root: Path):
        self.root = Path(root)
        self.count = 0
        scratch = Path(tempfile.mkdtemp())
        test_case.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.scratch = scratch
        patcher = mock.patch.object(engine_ledger, "runs_root", return_value=self.root)
        patcher.start()
        test_case.addCleanup(patcher.stop)

    def run(self, procedure: str, steps: list[dict], *, issue: int, inputs: dict,
            parent: str | None = None) -> Path:
        self.count += 1
        procedures = self.scratch / f"procedures-{self.count}"
        procedures.mkdir()
        (procedures / f"{procedure}.json").write_text(json.dumps({"format": 1, "steps": steps}), encoding="utf-8")
        return engine_ledger.create_run(
            project="example/project", issue=issue, procedure=procedure, procedures_dir=procedures,
            platform_revision="0" * 40, host="host-a", inputs=dict(inputs), now=NOW,
            token=f"{self.count:04x}", root=self.root, parent=parent)

    def result(self, run_dir: Path, step: str, visit: int, result: dict) -> None:
        engine_ledger.store_result(run_dir, step=step, visit=visit, result=result, at=AT, wall_seconds=0,
                                   turns=0, tokens=dict(NO_TOKENS), spend_usd=0)

    def call(self, parent_dir: Path, step: str, visit: int, child_dir: Path, index: int, items: int) -> None:
        engine_ledger.append_event(parent_dir, {"event": "call", "at": AT, "step": step, "visit": visit,
                                                "child": Path(child_dir).name, "index": index, "items": items})

    def done(self, run_dir: Path) -> None:
        engine_ledger.append_event(run_dir, {"event": "run_done", "at": AT})
