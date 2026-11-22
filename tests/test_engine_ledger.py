"""Contract tests for the engine run ledger (`agent_tools.delivery.engine_ledger`, #1511).

Covers run creation, the event wire format, the append and the result store
order rule, against the shipped toy procedures.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine, engine_ledger
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
    "call": {"event": "call", "at": AT, "step": "children", "visit": 1,
             "child": "1511-20261121T160232Z-c3d4", "index": 0, "items": 3},
    "keep_alive_ran": {"event": "keep_alive_ran", "at": AT, "step": "draft", "visit": 1,
                       "attempt": 1, "verdict": "renewed"},
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
                "sequence": 1, "started": "2026-11-21T16:02:31Z"})
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


class ChildRunTest(unittest.TestCase):
    def test_find_runs_returns_only_root_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_run = new_run(tmp)
            new_run(tmp, token="c3d4", now=NOW + timedelta(seconds=1), parent=root_run.name)
            self.assertEqual(engine_ledger.find_runs(Path(tmp), 1511, None), [root_run])
            self.assertEqual(engine_ledger.find_run(Path(tmp), 1511, None), root_run)

    def test_a_child_run_json_names_its_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_run = new_run(tmp)
            child = new_run(tmp, token="c3d4", now=NOW + timedelta(seconds=1),
                            parent=root_run.name)
            self.assertEqual(json.loads((child / "run.json").read_text())["parent"],
                             root_run.name)
            self.assertEqual(engine_ledger.read_run(child)["parent"], root_run.name)
            self.assertNotIn("parent", engine_ledger.read_run(root_run))
            self.assertEqual(engine_ledger.read_run(root_run)["sequence"], 1)
            self.assertEqual(engine_ledger.read_run(child)["sequence"], 2)
            later = new_run(tmp, token="e5f6", now=NOW + timedelta(seconds=2))
            self.assertEqual(engine_ledger.read_run(later)["sequence"], 3)
            self.assertEqual(engine_ledger.find_runs(Path(tmp), 1511, None),
                             [root_run, later])

    def test_a_parent_that_is_no_run_id_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LedgerError):
                new_run(tmp, parent="nope")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_a_run_json_whose_parent_is_no_run_id_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_run = new_run(tmp)
            child = new_run(tmp, token="c3d4", now=NOW + timedelta(seconds=1),
                            parent=root_run.name)
            copy = Path(tmp) / "copy" / child.name
            shutil.copytree(child, copy)
            document = json.loads((copy / "run.json").read_text())
            document["parent"] = "nope"
            (copy / "run.json").write_text(compact(document), encoding="utf-8")
            with self.assertRaises(LedgerError):
                engine_ledger.read_run(copy)


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
               {**EXAMPLES["call"], "index": -1},
               {**EXAMPLES["call"], "items": 0},
               {**EXAMPLES["call"], "index": 3, "items": 3},
               {**EXAMPLES["call"], "child": "nope"},
               {**EXAMPLES["call"], "index": True},
               {**EXAMPLES["keep_alive_ran"], "attempt": 0},
               {**EXAMPLES["keep_alive_ran"], "attempt": True},
               {**EXAMPLES["keep_alive_ran"], "verdict": ""},
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


FIXTURES = REPO_ROOT / "tests/fixtures/engine"
RUN = {"run": "1511-20261121T160231Z-a1b2", "project": "example/project", "issue": 1511}
ORPHAN_PROCESS = {"pid": 4343, "started": "2026-11-21T16:03:01Z", "step": "draft", "visit": 1}
STOP = {"name": "needs-owner", "need": "owner-decision"}


class SessionFileTest(unittest.TestCase):
    def test_a_session_file_is_stored_once_under_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            path = engine_ledger.store_session_file(run, "draft.1.json", b"{}")
            self.assertEqual(path, run / "sessions" / "draft.1.json")
            self.assertEqual(path.read_bytes(), b"{}")
            self.assertEqual(stat.S_IMODE((run / "sessions").stat().st_mode), 0o700)
            with self.assertRaises(LedgerError):
                engine_ledger.store_session_file(run, "draft.1.json", b"[]")
            self.assertEqual(path.read_bytes(), b"{}")
            for name in ("../x.1.json", "draft.0.json", "draft.1.txt"):
                with self.subTest(name=name), self.assertRaises(LedgerError):
                    engine_ledger.store_session_file(run, name, b"x")
            self.assertEqual([p.name for p in (run / "sessions").iterdir()], ["draft.1.json"])

    def test_creating_sessions_fsyncs_the_run_directory(self):
        synced: list[Path] = []
        real = engine_ledger._fsync_path

        def spy(path):
            synced.append(Path(path))
            real(path)

        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            with mock.patch.object(engine_ledger, "_fsync_path", side_effect=spy):
                engine_ledger.store_session_file(run, "draft.1.system.md", b"x")
            self.assertIn(run, synced)
            self.assertIn(run / "sessions", synced)


def live(pid, started):
    return True


def dead(pid, started):
    return False


def never(pid, started):
    raise AssertionError("probe called")


def fixture_lines(name: str) -> list[bytes]:
    return (FIXTURES / name).read_bytes().splitlines(keepends=True)


def state(name: str, probe, *, extra: bytes = b"", lines: list[bytes] | None = None):
    data = b"".join(lines) if lines is not None else (FIXTURES / name).read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        path.write_bytes(data + extra)
        return engine_ledger.fold(RUN, engine_ledger.replay(path), probe)


def expected(**members) -> dict:
    return {"run": RUN["run"], "project": RUN["project"], "issue": RUN["issue"], **members}


class FoldTableTest(unittest.TestCase):
    def test_each_recorded_run_folds_to_its_expected_state(self):
        rows = [
            ("running.jsonl", live, expected(
                stage="setup", step="scope", wait=None, stop=None, done=False,
                last_event="2026-11-21T16:02:36Z",
                process={"pid": 4242, "started": "2026-11-21T16:02:36Z", "step": "scope",
                         "visit": 1}, alive=True)),
            ("running.jsonl", dead, expected(
                stage="setup", step="scope", wait=None, stop=None, done=False,
                last_event="2026-11-21T16:02:36Z",
                process={"pid": 4242, "started": "2026-11-21T16:02:36Z", "step": "scope",
                         "visit": 1}, alive=False)),
            ("waiting.jsonl", never, expected(
                stage="building", step="draft",
                wait={"since": "2026-11-21T16:03:02Z", "until": "2026-11-21T18:00:00Z",
                      "wait": "usage-limit"},
                stop=None, done=False, last_event="2026-11-21T16:03:02Z", process=None,
                alive=False)),
            ("stopped.jsonl", never, expected(
                stage="setup", step="scope", wait=None, stop=STOP, done=False,
                last_event="2026-11-21T16:02:41Z", process=None, alive=False)),
            ("continued.jsonl", never, expected(
                stage="building", step="draft", wait=None, stop=None, done=False,
                last_event="2026-11-21T16:09:01Z", process=None, alive=False)),
            ("done.jsonl", never, expected(
                stage="landing", step="children", wait=None, stop=None, done=True,
                last_event="2026-11-21T16:21:00Z", process=None, alive=False)),
            ("orphan.jsonl", live, expected(
                stage="building", step="draft", wait=None, stop=STOP, done=False,
                last_event="2026-11-21T16:05:00Z", process=ORPHAN_PROCESS, alive=True)),
            ("orphan.jsonl", dead, expected(
                stage="building", step="draft", wait=None, stop=STOP, done=False,
                last_event="2026-11-21T16:05:00Z", process=ORPHAN_PROCESS, alive=False)),
        ]
        for fixture, probe, want in rows:
            with self.subTest(fixture=fixture, probe=probe.__name__):
                got = engine_ledger.fold(RUN, engine_ledger.replay(FIXTURES / fixture), probe)
                self.assertEqual(got.as_json(), want)

    def test_an_open_process_stays_reported_after_done_and_after_another_steps_result(self):
        orphan = fixture_lines("orphan.jsonl")
        done_state = state("", live, lines=orphan,
                           extra=b'{"at":"2026-11-21T16:06:00Z","event":"run_done"}\n')
        self.assertIs(done_state.done, True)
        self.assertEqual(done_state.process, ORPHAN_PROCESS)
        self.assertIs(done_state.alive, True)
        other_result = fixture_lines("stopped.jsonl")[2]
        other = state("", live, lines=orphan[:2] + [other_result] + orphan[2:])
        self.assertEqual(other.process, ORPHAN_PROCESS)
        self.assertIs(other.alive, True)

    def test_a_continued_run_closes_its_open_wait(self):
        folded = state("waiting.jsonl", never,
                       extra=b'{"at":"2026-11-21T16:30:00Z","event":"run_continued"}\n')
        self.assertIsNone(folded.wait)
        self.assertEqual(folded.last_event, "2026-11-21T16:30:00Z")

    def test_no_events_fold_to_an_empty_state(self):
        folded = engine_ledger.fold(RUN, [], never)
        for member in ("stage", "step", "wait", "stop", "last_event", "process"):
            self.assertIsNone(getattr(folded, member), member)
        self.assertIs(folded.done, False)
        self.assertIs(folded.alive, False)

    def test_the_fold_reads_no_file_and_no_clock(self):
        events = engine_ledger.replay(FIXTURES / "orphan.jsonl")

        def refuse(*args, **kwargs):
            raise AssertionError("the fold touched a file, process or clock")

        with mock.patch("builtins.open", refuse), mock.patch("os.open", refuse), \
                mock.patch("os.kill", refuse), mock.patch("time.time", refuse):
            folded = engine_ledger.fold(RUN, events, live)
        self.assertEqual(folded.as_json(), expected(
            stage="building", step="draft", wait=None, stop=STOP, done=False,
            last_event="2026-11-21T16:05:00Z", process=ORPHAN_PROCESS, alive=True))


class ReplayTest(unittest.TestCase):
    def test_a_file_cut_mid_line_folds_like_the_file_without_that_line(self):
        stopped = (FIXTURES / "stopped.jsonl").read_bytes()
        torn = (FIXTURES / "torn.jsonl").read_bytes()
        self.assertTrue(torn.startswith(stopped))
        self.assertFalse(torn.endswith(b"\n"))
        self.assertEqual(engine_ledger.replay(FIXTURES / "torn.jsonl"),
                         engine_ledger.replay(FIXTURES / "stopped.jsonl"))
        self.assertEqual(
            engine_ledger.fold(RUN, engine_ledger.replay(FIXTURES / "torn.jsonl"), live),
            engine_ledger.fold(RUN, engine_ledger.replay(FIXTURES / "stopped.jsonl"), live))

    def test_a_complete_last_line_without_a_newline_is_dropped(self):
        folded = state("stopped.jsonl", never,
                       extra=b'{"at":"2026-11-21T16:09:00Z","event":"run_continued"}')
        self.assertEqual(folded.stop, STOP)

    def test_a_malformed_middle_line_is_refused(self):
        first, second = fixture_lines("stopped.jsonl")[:2]
        bad_lines = [
            b"not json\n",
            b'{"at":"2026-11-21T16:02:31Z","event":"bogus"}\n',
            b'{"at":"2026-11-21T16:02:31Z","event":"step_entered","stage":"setup",'
            b'"step":"scope","step":"scope","visit":1}\n',
        ]
        for bad in bad_lines:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                path.write_bytes(first + bad + second)
                with self.assertRaises(LedgerError) as caught:
                    engine_ledger.replay(path)
                self.assertIn("line 2", str(caught.exception))

    def test_an_empty_file_is_no_events_and_an_absent_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with self.assertRaises(LedgerError):
                engine_ledger.replay(path)
            path.write_bytes(b"")
            self.assertEqual(engine_ledger.replay(path), [])


class ProbeTest(unittest.TestCase):
    def test_process_alive_reads_os_kill(self):
        self.assertIs(engine_ledger.process_alive(os.getpid(), ""), True)
        self.assertIs(engine_ledger.process_alive(0, ""), False)
        self.assertIs(engine_ledger.process_alive(-1, ""), False)
        for error, answer in ((ProcessLookupError, False), (PermissionError, True),
                              (OverflowError, False)):
            with self.subTest(error=error.__name__):
                with mock.patch("os.kill", side_effect=error):
                    self.assertIs(engine_ledger.process_alive(4242, ""), answer)


RUN_FIXTURE = FIXTURES / "runs" / "1511-20261121T160231Z-a1b2"
RUN_ID = RUN_FIXTURE.name


def home_with(tmp: str, *run_dirs: Path) -> Path:
    root = Path(tmp) / ".agents" / "state" / "engine" / "runs"
    root.mkdir(parents=True)
    for run_dir in run_dirs:
        copied = root / run_dir.name
        shutil.copytree(run_dir, copied)
        os.chmod(copied, 0o700)
    return root


def sibling_run(tmp: str, name: str, *, events: str | None = None, **members) -> Path:
    """A copy of the fixture run named `name` with `run.json` members replaced."""
    path = Path(tmp) / "variants" / name
    shutil.copytree(RUN_FIXTURE, path)
    document = json.loads((path / "run.json").read_text())
    document.update(members, run=name)
    (path / "run.json").write_text(compact(document))
    if events is not None:
        shutil.copyfile(FIXTURES / events, path / "events.jsonl")
    return path


def tree_digest(root: Path) -> list:
    entries = []
    for directory, names, files in os.walk(root):
        for name in [""] + names + files:
            path = Path(directory) / name if name else Path(directory)
            info = path.lstat()
            digest = None if stat.S_ISDIR(info.st_mode) else \
                hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((str(path.relative_to(root)), info.st_mode, info.st_mtime_ns, digest))
    return sorted(set(entries))


def run_status(home: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "agent_tools.delivery.engine", "status", *args],
                          env={**os.environ, "HOME": str(home)}, capture_output=True,
                          text=True, timeout=60)


def main_status(home: str, *argv: str):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"HOME": str(home)}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = engine.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class StatusTest(unittest.TestCase):
    def test_status_prints_exactly_the_fold_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = home_with(tmp, RUN_FIXTURE)
            before = tree_digest(Path(tmp) / ".agents")
            result = run_status(tmp, "1511")
            run_dir = root / RUN_ID
            expected = compact(engine_ledger.fold(
                engine_ledger.read_run(run_dir),
                engine_ledger.replay(run_dir / "events.jsonl"),
                engine_ledger.process_alive).as_json())
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(result.stdout, expected)
            printed = json.loads(result.stdout)
            self.assertEqual((printed["stage"], printed["step"]), ("setup", "scope"))
            self.assertEqual(printed["stop"], STOP)
            self.assertEqual(tree_digest(Path(tmp) / ".agents"), before)

    def test_status_with_no_run_prints_null_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_status(tmp, "1511")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '{"issue":1511,"run":null}\n')
            self.assertEqual(result.stderr, "")
            self.assertFalse((Path(tmp) / ".agents").exists())

    def test_status_reads_the_newest_run_of_the_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            newer = sibling_run(tmp, "1511-20261122T090000Z-zzzz", events="continued.jsonl")
            other = sibling_run(tmp, "1512-20261123T000000Z-aaaa", issue=1512)
            home_with(tmp, RUN_FIXTURE, newer, other)
            code, out, err = main_status(tmp, "status", "1511")
            self.assertEqual((code, err), (0, ""))
            printed = json.loads(out)
            self.assertEqual(printed["run"], "1511-20261122T090000Z-zzzz")
            self.assertEqual(printed["step"], "draft")

    def test_runs_of_two_projects_need_a_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = sibling_run(tmp, "1511-20261122T090000Z-zzzz", project="example/other")
            home_with(tmp, RUN_FIXTURE, other)
            code, out, err = main_status(tmp, "status", "1511")
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(len(err.splitlines()), 1)
            code, out, err = main_status(tmp, "status", "1511", "--project", "example/project")
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)["run"], RUN_ID)

    def test_a_run_json_project_of_the_wrong_type_is_a_refusal_not_a_traceback(self):
        for project in (["x"], {"a": 1}, 1):
            for extra in ((), ("--project", "example/project")):
                with self.subTest(project=project, extra=extra), \
                        tempfile.TemporaryDirectory() as tmp:
                    odd = sibling_run(tmp, "1511-20261122T090000Z-zzzz", project=project)
                    home_with(tmp, RUN_FIXTURE, odd)
                    result = run_status(tmp, "1511", *extra)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_a_bad_status_argument_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_with(tmp, RUN_FIXTURE)
            for argv in (["status"], ["status", "abc"], ["status", "0"],
                         ["status", "1511", "--bogus"]):
                with self.subTest(argv=argv):
                    code, out, err = main_status(tmp, *argv)
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(len(err.splitlines()), 1)
        with tempfile.TemporaryDirectory() as tmp:
            first, second = fixture_lines("stopped.jsonl")[:2]
            corrupt = sibling_run(tmp, RUN_ID)
            (corrupt / "events.jsonl").write_bytes(first + b"not json\n" + second)
            home_with(tmp, corrupt)
            code, out, err = main_status(tmp, "status", "1511")
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(len(err.splitlines()), 1)
            self.assertIn("line 2", err)


class ReviewDefectsTest(unittest.TestCase):
    def test_an_append_after_a_torn_tail_cuts_the_tail_and_replays(self):
        stopped = (FIXTURES / "stopped.jsonl").read_bytes()
        for tail in (b'{"at":"2026-11-21T16:09:00Z","event":"run_contin', b"{"):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as tmp:
                run = new_run(tmp)
                (run / "events.jsonl").write_bytes(stopped + tail)
                event = {"event": "run_continued", "at": "2026-11-21T16:10:00Z"}
                engine_ledger.append_event(run, event)
                self.assertEqual((run / "events.jsonl").read_bytes(), stopped + compact(event).encode())
                self.assertEqual(engine_ledger.replay(run / "events.jsonl"),
                                 engine_ledger.replay(FIXTURES / "stopped.jsonl") + [event])
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            (run / "events.jsonl").write_bytes(b'{"at":"2026')
            engine_ledger.append_event(run, EXAMPLES["run_done"])
            self.assertEqual((run / "events.jsonl").read_bytes(), compact(EXAMPLES["run_done"]).encode())

    def test_a_concurrent_append_never_loses_an_acknowledged_event_to_a_torn_tail_cut(self):
        stopped = (FIXTURES / "stopped.jsonl").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            (run / "events.jsonl").write_bytes(stopped + b'{"at":"2026-11-21T16:09:00Z","event":"run_contin')
            first = {"event": "run_continued", "at": "2026-11-21T16:10:00Z"}
            second = {"event": "run_done", "at": "2026-11-21T16:11:00Z"}
            real_truncate = os.ftruncate
            outcome = []

            def writer_a():
                engine_ledger.append_event(run, first)
                outcome.append("acknowledged")

            threads = []

            def truncate_while_a_appends(descriptor, length):
                # Only the first (writer B's) cut is interrupted by writer A.
                if not threads:
                    threads.append(threading.Thread(target=writer_a))
                    threads[0].start()
                    threads[0].join(timeout=1)
                real_truncate(descriptor, length)

            with mock.patch.object(os, "ftruncate", side_effect=truncate_while_a_appends):
                engine_ledger.append_event(run, second)
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(outcome, ["acknowledged"])
            self.assertCountEqual(engine_ledger.replay(run / "events.jsonl"),
                                  engine_ledger.replay(FIXTURES / "stopped.jsonl") + [first, second])

    def test_a_symlinked_entry_procedure_inside_the_directory_is_copied_under_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "procedures"
            shutil.copytree(PROCEDURES, source)
            (source / "alias.json").symlink_to("toy.json")
            run = new_run(tmp, procedure="alias", procedures_dir=source, root=Path(tmp) / "runs")
            copied = run / "procedure" / "alias.json"
            self.assertFalse(copied.is_symlink())
            self.assertEqual(copied.read_bytes(), (source / "toy.json").read_bytes())
            sums = (run / "procedure/SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn(f"{hashlib.sha256(copied.read_bytes()).hexdigest()}  alias.json\n", sums)

    def test_an_entry_procedure_that_resolves_outside_the_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "procedures"
            shutil.copytree(PROCEDURES, source)
            outside = Path(tmp) / "outside.json"
            outside.write_bytes((source / "toy.json").read_bytes())
            (source / "alias.json").symlink_to(outside)
            with self.assertRaises(LedgerError):
                new_run(tmp, procedure="alias", procedures_dir=source, root=Path(tmp) / "runs")
            self.assertFalse((Path(tmp) / "runs").exists())

    def test_a_second_writer_never_replaces_a_stored_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            store(run)
            with mock.patch("os.path.lexists", return_value=False):
                with self.assertRaises(LedgerError):
                    store(run, result={"verdict": "other"})
            self.assertEqual(json.loads((run / "results/scope.1.json").read_text()),
                             {"verdict": "ok"})
            self.assertEqual(len((run / "events.jsonl").read_text().splitlines()), 1)
            self.assertEqual([p.name for p in (run / "results").iterdir()], ["scope.1.json"])

    def test_a_writer_uses_its_own_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = new_run(tmp)
            foreign = run / "results" / ".scope.1.json.tmp"
            foreign.write_bytes(b"another writer pending")
            store(run)
            self.assertEqual(foreign.read_bytes(), b"another writer pending")
            self.assertEqual(json.loads((run / "results/scope.1.json").read_text()),
                             {"verdict": "ok"})

    def test_runs_of_one_second_are_ordered_by_creation_not_by_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = new_run(tmp, token="zzzz")
            second = new_run(tmp, token="aaaa")
            self.assertEqual([engine_ledger.read_run(p)["sequence"] for p in (first, second)],
                             [1, 2])
            self.assertEqual(engine_ledger.find_runs(Path(tmp), 1511, None), [first, second])
            self.assertEqual(engine_ledger.find_run(Path(tmp), 1511, None), second)

    def test_a_refusal_before_publication_leaves_no_run_and_no_temporary_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged: list[Path] = []

            def refuse(path):
                staged.append(path)
                raise RuntimeError("refused")

            with self.assertRaises(RuntimeError):
                new_run(tmp, before_publish=refuse)
            self.assertTrue(staged[0].name.endswith(".tmp"))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_creating_the_runs_hierarchy_fsyncs_each_parent_of_a_new_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "a" / "b" / "runs"
            synced: list[Path] = []
            real = engine_ledger._fsync_path

            def spy(path):
                synced.append(Path(path))
                real(path)

            with mock.patch.object(engine_ledger, "_fsync_path", side_effect=spy):
                new_run(tmp, root=root)
            for parent in (Path(tmp), Path(tmp) / "a", Path(tmp) / "a" / "b", root):
                self.assertIn(parent, synced)

    def test_the_fold_reports_the_last_unresolved_process_when_a_later_visit_resolves(self):
        first = {**EXAMPLES["process_started"], "step": "scope", "pid": 11}
        second = {**EXAMPLES["process_started"], "step": "draft", "pid": 22}
        stored = {**EXAMPLES["result_stored"], "step": "draft", "result": "results/draft.1.json"}
        probed = []

        def probe(pid, started):
            probed.append(pid)
            return True

        folded = engine_ledger.fold(RUN, [first, second, stored], probe)
        self.assertEqual(folded.process, {"pid": 11, "started": AT, "step": "scope", "visit": 1})
        self.assertIs(folded.alive, True)
        self.assertEqual(probed, [11])
        done = engine_ledger.fold(RUN, [first, second, stored,
                                        {**stored, "step": "scope", "result": "results/scope.1.json"}],
                                  never)
        self.assertIsNone(done.process)

    def test_a_run_json_whose_run_is_not_its_directory_name_is_refused(self):
        for recorded in (None, 7, "1511-20261121T160231Z-zzzz"):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as tmp:
                run = sibling_run(tmp, RUN_ID)
                document = json.loads((run / "run.json").read_text())
                document["run"] = recorded
                (run / "run.json").write_text(compact(document))
                with self.assertRaises(LedgerError):
                    engine_ledger.read_run(run)
                home_with(tmp, run)
                code, out, err = main_status(tmp, "status", "1511")
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(len(err.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
