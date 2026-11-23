"""Contract tests for a continued engine run that cannot be resumed as it was: a run whose
procedure copy is in a format the engine does not read ends `superseded`, and the same
`engine deliver` call opens a new run from the current procedures.

The hermetic project, the stand-in command and the shared step helpers come from
tests/test_engine_deliver.py.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.delivery import engine_ledger
from tests.test_engine_continue import gated
from tests.test_engine_deliver import EngineProject, run_continued, step

TIER = "integration"  # every case runs `engine deliver` against the stand-in command


def seed(project: EngineProject, procedures: Path, token: str) -> Path:
    root = project.world.home / ".agents/state/engine/runs"
    return engine_ledger.create_run(
        project="example/engine", issue=1512, procedure="deliver",
        procedures_dir=procedures, platform_revision="source", host="test",
        inputs={"issue": 1512}, now=datetime(2026, 11, 21, tzinfo=timezone.utc),
        token=token, root=root)


def history(project: EngineProject) -> list[dict]:
    path = project.world.home / ".agents/state/engine/history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rewrite(path: Path, **members) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(members)
    path.write_text(json.dumps(document), encoding="utf-8")


class SupersededTest(unittest.TestCase):
    def test_a_copy_in_a_format_the_engine_does_not_read_ends_superseded_and_the_same_call_opens_a_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        future = project.procedures([step("a", "standin-record", "done")])
        rewrite(future / "deliver.json", format=2)
        old = seed(project, future, "aaaa")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "done")
        self.assertNotEqual(line["run"], old.name)
        self.assertEqual(len(project.runs()), 2)
        self.assertEqual([(e["event"], e["step"], e["stop"], e["need"])
                          for e in project.events(old)],
                         [("stop_reached", "deliver", "superseded", "nothing")])
        (new,) = [run for run in project.runs() if run != old]
        self.assertEqual(project.events(new)[-1]["event"], "run_done")
        self.assertTrue(project.record.exists())
        lines = [entry for entry in history(project) if entry["run"] == old.name]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["end"], lines[0]["need"]), ("superseded", "nothing"))

    def test_a_superseded_run_is_never_continued_again_and_names_its_last_entered_step(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (old,) = project.runs()
        rewrite(old / "procedure/deliver.json", format=2)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(project.events(old)[-1]["stop"], "superseded")
        self.assertEqual(project.events(old)[-1]["step"], "g")
        self.assertNotEqual(json.loads(second.stdout)["run"], old.name)
        (project.tmp / "gate-open").write_text("", encoding="utf-8")
        third = project.deliver(procedures)
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertEqual(json.loads(third.stdout)["run"], json.loads(second.stdout)["run"])
        self.assertEqual(len(project.runs()), 2)
        (new,) = [run for run in project.runs() if run != old]
        self.assertEqual(len(run_continued(project.events(new))), 1)

    def test_a_copy_that_differs_only_in_content_is_continued(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (old,) = project.runs()
        path = old / "procedure/deliver.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        for item in document["steps"]:
            if item["id"] == "d":
                item["stage"] = "building"
        path.write_text(json.dumps(document), encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], old.name)
        self.assertEqual(len(project.runs()), 1)
        events = project.events(old)
        self.assertFalse([e for e in events if e.get("stop") == "superseded"])
        self.assertEqual(len(run_continued(events)), 1)

    def test_a_copy_that_does_not_parse_is_refused_and_nothing_is_written(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        old = seed(project, procedures, "aaaa")
        (old / "procedure/deliver.json").write_bytes(b"not json")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual((old / "events.jsonl").read_bytes(), b"")
        self.assertEqual(project.runs(), [old])


if __name__ == "__main__":
    unittest.main()
