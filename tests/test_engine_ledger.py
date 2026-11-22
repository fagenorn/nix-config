"""Contract tests for the engine run ledger (`agent_tools.delivery.engine_ledger`, #1511).

Covers run creation, the event wire format, the append and the result store
order rule, against the shipped toy procedures.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger
from agent_tools.delivery.engine_ledger import EVENT_MEMBERS, RUN_ID_RE, LedgerError

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"
DELIVERY = REPO_ROOT / "python/agent_tools/delivery"
NOW = datetime(2026, 11, 21, 16, 2, 31, tzinfo=timezone.utc)
AT = "2026-11-21T16:02:31Z"
INPUTS = {"holder": "host-a/s", "issue": 1511, "range": "origin/main...HEAD",
          "repo": "example/project"}
ZERO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def new_run(tmp: str | None = None, **overrides) -> Path:
    arguments = dict(project="example/project", issue=1511, procedure="toy",
                     procedures_dir=PROCEDURES, platform_revision="0" * 40,
                     host="host-a", inputs=dict(INPUTS), now=NOW, token="a1b2")
    if tmp is not None:
        arguments["root"] = Path(tmp)
    arguments.update(overrides)
    return engine_ledger.create_run(**arguments)


def store(run: Path, **overrides) -> Path:
    arguments = dict(step="scope", visit=1, result={"verdict": "ok"},
                     at="2026-11-21T16:02:40Z", wall_seconds=8.0, turns=0,
                     tokens=dict(ZERO_TOKENS), spend_usd=0)
    arguments.update(overrides)
    return engine_ledger.store_result(run, **arguments)


EXAMPLES = {
    "step_entered": {"event": "step_entered", "at": AT, "step": "scope", "visit": 1,
                     "stage": "setup"},
    "session_starting": {"event": "session_starting", "at": AT, "step": "draft", "visit": 1,
                         "session": "s-1", "role": "implementer", "account": "p1"},
    "process_started": {"event": "process_started", "at": AT, "step": "draft", "visit": 1,
                        "pid": 4242, "started": AT},
    "result_stored": {"event": "result_stored", "at": AT, "step": "scope", "visit": 1,
                      "result": "results/scope.1.json", "wall_seconds": 8.5, "turns": 3,
                      "tokens": dict(ZERO_TOKENS), "spend_usd": 0.25},
    "outcome_graded": {"event": "outcome_graded", "at": AT, "step": "scope", "visit": 1,
                       "outcome": "ok"},
    "transition_taken": {"event": "transition_taken", "at": AT, "step": "scope", "visit": 1,
                         "outcome": "ok", "to": "draft"},
    "wait_started": {"event": "wait_started", "at": AT, "wait": "usage-limit", "until": AT},
    "wait_ended": {"event": "wait_ended", "at": AT, "wait": "usage-limit"},
    "stop_reached": {"event": "stop_reached", "at": AT, "step": "scope",
                     "stop": "needs-owner", "need": "owner-decision"},
    "run_continued": {"event": "run_continued", "at": AT},
    "run_done": {"event": "run_done", "at": AT},
}


class RunCreationTest(unittest.TestCase):
    def test_creating_a_run_makes_a_0700_directory_with_run_json_and_a_hashed_procedure_copy(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp}):
            path = new_run()
            self.assertEqual(path, Path(tmp) / ".agents/state/engine/runs/1511-20261121T160231Z-a1b2")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(sorted(p.name for p in path.iterdir()),
                             ["events.jsonl", "procedure", "results", "run.json"])
            self.assertEqual((path / "events.jsonl").read_bytes(), b"")
            self.assertEqual(list((path / "results").iterdir()), [])
            self.assertEqual(engine_ledger.read_run(path), {
                "host": "host-a", "inputs": INPUTS, "issue": 1511,
                "platform_revision": "0" * 40, "procedure": "toy",
                "project": "example/project", "run": "1511-20261121T160231Z-a1b2",
                "started": "2026-11-21T16:02:31Z"})
            sources = sorted(p.name for p in PROCEDURES.iterdir()
                             if p.is_file() and p.suffix in (".json", ".md"))
            sums = (path / "procedure/SHA256SUMS").read_text(encoding="utf-8")
            listed = [line.split("  ", 1) for line in sums.splitlines()]
            self.assertTrue(sums.endswith("\n"))
            self.assertEqual([name for _, name in listed], sources)
            for digest, name in listed:
                copied = (path / "procedure" / name).read_bytes()
                self.assertEqual(copied, (PROCEDURES / name).read_bytes())
                self.assertEqual(digest, hashlib.sha256(copied).hexdigest())
            self.assertEqual(sorted(p.name for p in (path / "procedure").iterdir()),
                             sorted(sources + ["SHA256SUMS"]))

    def test_the_run_id_is_issue_time_and_four_characters(self):
        self.assertEqual(engine_ledger.make_run_id(1511, NOW, "a1b2"), "1511-20261121T160231Z-a1b2")
        with tempfile.TemporaryDirectory() as tmp:
            path = new_run(tmp, token=None)
            match = RUN_ID_RE.fullmatch(path.name)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), "1511")

    def test_a_run_id_that_exists_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = new_run(tmp)
            before = (path / "run.json").read_bytes()
            with self.assertRaises(LedgerError):
                new_run(tmp)
            self.assertEqual((path / "run.json").read_bytes(), before)

    def test_creation_leaves_no_temporary_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("os.rename", side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    new_run(tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            new_run(tmp)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["1511-20261121T160231Z-a1b2"])

    def test_an_absent_entry_procedure_is_refused(self):
        refused = [{"procedure": "absent"}, {"procedure": "Bad"},
                   {"inputs": {"HOME": "x"}}, {"inputs": {"a": 1.5}}]
        for overrides in refused:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(LedgerError):
                    new_run(tmp, **overrides)
                self.assertEqual(list(Path(tmp).iterdir()), [])


class EventShapeTest(unittest.TestCase):
    def test_each_event_type_round_trips_and_a_wrong_shape_is_refused(self):
        self.assertEqual(set(EVENT_MEMBERS), set(EXAMPLES))
        for kind, example in EXAMPLES.items():
            with self.subTest(kind=kind):
                self.assertEqual(engine_ledger.validate_event(dict(example)), example)
                variants = [{**example, "at": "2026-11-21 16:02:31"}, {**example, "x": 1}]
                variants += [{k: v for k, v in example.items() if k != member}
                             for member in example]
                for variant in variants:
                    with self.assertRaises(LedgerError):
                        engine_ledger.validate_event(variant)
        bad = [{"event": "bogus", "at": AT},
               {**EXAMPLES["step_entered"], "visit": True},
               {**EXAMPLES["step_entered"], "stage": "nowhere"},
               {**EXAMPLES["wait_started"], "wait": "coffee"},
               {**EXAMPLES["result_stored"], "result": "results/other.1.json"},
               "not an object"]
        for variant in bad:
            with self.subTest(variant=variant), self.assertRaises(LedgerError):
                engine_ledger.validate_event(variant)
        engine_ledger.validate_event({**EXAMPLES["wait_started"], "until": None})


class ResultOrderTest(unittest.TestCase):
    def test_a_failed_event_append_leaves_the_result_on_disk_and_no_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            with mock.patch.object(engine_ledger, "_append_line", side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    store(run)
            self.assertEqual(json.loads((run / "results/scope.1.json").read_text()),
                             {"verdict": "ok"})
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")

    def test_a_failed_result_write_appends_no_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            with mock.patch.object(engine_ledger, "_write_result", side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    store(run)
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")
            self.assertFalse((run / "results/scope.1.json").exists())

    def test_each_appended_line_is_fsynced_before_the_append_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            real = os.fsync
            snapshots: list[bytes] = []

            def spy(fd):
                with open(run / "events.jsonl", "rb") as handle:
                    snapshots.append(handle.read())
                real(fd)

            example = EXAMPLES["step_entered"]
            with mock.patch("os.fsync", side_effect=spy):
                engine_ledger.append_event(run, example)
            self.assertIn(compact(example).encode(), snapshots)
            with mock.patch("os.fsync", side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    engine_ledger.append_event(run, EXAMPLES["step_entered"])

    def test_a_result_event_naming_an_absent_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            event = {**EXAMPLES["result_stored"], "visit": 2, "result": "results/scope.2.json"}
            with self.assertRaises(LedgerError):
                engine_ledger.append_event(run, event)
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")

    def test_a_stored_result_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            store(run)
            with self.assertRaises(LedgerError):
                store(run, result={"verdict": "other"})
            self.assertEqual(json.loads((run / "results/scope.1.json").read_text()),
                             {"verdict": "ok"})
            self.assertEqual(len((run / "events.jsonl").read_text().splitlines()), 1)

    def test_the_ledger_module_imports_no_process_or_socket_module(self):
        tree = ast.parse((DELIVERY / "engine_ledger.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            for module in imported:
                self.assertNotIn(module.split(".")[0], ("subprocess", "socket"))


if __name__ == "__main__":
    unittest.main()
