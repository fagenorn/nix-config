"""The spend reader's engine sessions: a session the run ledger names is spent under its run, stage and sprint."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import spend
from agent_tools.delivery import engine_ledger

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

FIXTURE = Path(__file__).parent / "fixtures/console/engine-spend"
FIXED = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc).timestamp()
SINCE = "2026-10-18"
AB = "41-20261116T090000Z-ab12"
EF = "41-20261116T091000Z-ef56"
CD = "42-20261116T090000Z-cd34"
SPRINT = "0123456789abcdef"


def counts(tokens):
    return (tokens["input"], tokens["cache_write"], tokens["cache_read"], tokens["output"])


def stamp(tree, when=FIXED):
    for path in Path(tree).rglob("*"):
        if path.is_file():
            os.utime(path, (when, when))


def copy_fixture(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    tree = Path(tmp.name) / "tree"
    shutil.copytree(FIXTURE, tree)
    stamp(tree)
    return tree


def event(**members):
    return (json.dumps(members, sort_keys=True, separators=(",", ":")) + "\n").encode()


class EngineSpendTest(unittest.TestCase):
    def setUp(self):
        self.tree = copy_fixture(self)

    def read(self, engine=True, reader=None, since=SINCE):
        reader = reader or spend.SpendReader(repo_of=lambda cwd: cwd)
        reader.read([self.tree / "projects"], since, None,
                    engine_root=self.tree / "runs" if engine else None)
        self.reader = reader
        return reader.snapshot()

    def view(self, snapshot):
        view = spend.spend_view(snapshot, today="2026-11-16", project_of={"/srv/p00": "p00"}.get,
                                profiles={})
        return view["days"][-1]

    def events(self, run):
        return self.tree / "runs" / run / "events.jsonl"

    def phases(self, d, run):
        return {phase: counts(tokens) for phase, tokens in d["run_phase"][run].items()}

    def test_a_session_a_runs_events_name_counts_under_the_run_and_its_steps_stage(self):
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertEqual(counts(d["run"][AB]), (1190, 0, 0, 7))
        self.assertEqual(self.phases(d, AB),
                         {"planning": (100, 0, 0, 7), "building": (1090, 0, 0, 0)})
        self.assertEqual(counts(d["aspect"]["deliveries"]), (2190, 0, 0, 7))
        self.assertEqual(snapshot.engine["e1"], spend.EngineSession(AB, "plan", "planning"))
        recorded = {}
        for name in ("e1", "e2", "e3", "e5"):
            for line in (self.tree / "projects/-srv-p00" / f"{name}.jsonl").read_text().splitlines():
                message = json.loads(line)["message"]
                usage = recorded.setdefault(message["id"], {})
                for field, count in message["usage"].items():
                    usage[field] = max(usage.get(field, 0), count)
        self.assertEqual(d["run"][AB]["input"], sum(u["input_tokens"] for u in recorded.values()))
        self.assertEqual(d["run"][AB]["output"], sum(u["output_tokens"] for u in recorded.values()))

    def test_a_transcript_read_before_its_events_is_attributed_once_they_are_read(self):
        originals = {path: path.read_bytes() for path in (self.tree / "runs").glob("*/events.jsonl")}
        for path in originals:
            path.write_bytes(b"")
        reader = spend.SpendReader(repo_of=lambda cwd: cwd)
        before = self.view(self.read(reader=reader))
        self.assertNotIn(AB, before["run"])
        self.assertEqual(counts(before["aspect"]["outside_sprint"])[0], 2193)
        for path, data in originals.items():
            path.write_bytes(data)
        after = self.view(self.read(reader=reader))
        self.assertEqual(counts(after["run"][AB]), (1190, 0, 0, 7))
        self.assertEqual(counts(after["total"]), counts(before["total"]))
        self.assertEqual(counts(after["total"]), (2203, 0, 0, 7))

    def test_the_ledgers_spend_figures_change_no_figure_in_the_view(self):
        first = self.view(self.read())
        path = self.events(AB)
        lines = path.read_text().splitlines()
        stored = next(i for i, line in enumerate(lines) if '"result_stored"' in line)
        document = json.loads(lines[stored])
        document["tokens"] = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        document["spend_usd"] = 0.0
        lines[stored] = json.dumps(document, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n")
        second = self.view(self.read())
        self.assertEqual(first, second)
        self.assertEqual(first["run"][AB]["input"], 1190)

    def test_a_resumed_session_counts_each_message_once_under_one_step(self):
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertEqual(snapshot.engine["e2"], spend.EngineSession(AB, "implement", "building"))
        self.assertEqual(counts(d["session"]["e2"]), (290, 0, 0, 0))
        self.assertEqual(sum(counts(t)[0] for t in d["run_phase"][AB].values()),
                         counts(d["run"][AB])[0])
        with self.events(AB).open("ab") as handle:
            handle.write(event(at="2026-11-16T09:20:00Z", event="session_resuming",
                               step="implement", visit=1, session="e2", attempt=3))
            handle.write(event(at="2026-11-16T09:21:00Z", event="step_entered", step="review",
                               visit=1, stage="final review"))
            handle.write(event(at="2026-11-16T09:22:00Z", event="session_starting", step="review",
                               visit=1, session="e2", role="reviewer", account="p1"))
        again = self.read()
        self.assertEqual(again.engine["e2"].step, "implement")
        self.assertNotIn("final review", self.view(again)["run_phase"][AB])

    def test_a_step_entered_twice_counts_both_sessions_under_its_stage(self):
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertEqual(snapshot.engine["e2"].step, "implement")
        self.assertEqual(snapshot.engine["e3"].step, "implement")
        built = sum(d["session"][name]["input"] for name in ("e2", "e3", "e5"))
        self.assertEqual(built, d["run_phase"][AB]["building"]["input"])
        self.assertEqual(built, 1090)

    def test_a_run_started_by_a_sprints_manager_adds_to_that_sprint_by_stage_and_one_started_outside_adds_to_none(self):
        d = self.view(self.read())
        self.assertEqual(counts(d["sprint"][SPRINT]), (1200, 0, 0, 7))
        self.assertEqual({p: counts(t) for p, t in d["sprint_phase"][SPRINT].items()},
                         {"manager": (10, 0, 0, 0), "planning": (100, 0, 0, 7),
                          "building": (1090, 0, 0, 0)})
        self.assertEqual(sum(t["input"] for t in d["sprint"].values()), 1200)
        self.assertEqual(counts(d["run"][CD]), (1000, 0, 0, 0))
        self.assertEqual(self.phases(d, CD), {"planning": (1000, 0, 0, 0)})
        self.assertEqual(counts(d["aspect"]["managers"]), (10, 0, 0, 0))
        self.assertEqual(counts(d["aspect"]["outside_sprint"]), (3, 0, 0, 0))

    def test_a_run_with_no_starter_adds_to_no_sprint(self):
        path = self.tree / "runs" / AB / "run.json"
        document = json.loads(path.read_text())
        del document["starter"]
        path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")))
        d = self.view(self.read())
        self.assertEqual(d["sprint"][SPRINT]["input"], 10)
        self.assertEqual(set(d["sprint_phase"][SPRINT]), {"manager"})

    def test_a_child_runs_session_counts_under_its_root_run(self):
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertEqual(snapshot.engine["e5"], spend.EngineSession(AB, "build", "building"))
        self.assertNotIn(EF, d["run"])

    def test_a_run_json_the_ledger_refuses_attributes_nothing(self):
        path = self.tree / "runs" / CD / "run.json"
        document = json.loads(path.read_text())
        del document["issue"]
        path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")))
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertNotIn("e4", snapshot.engine)
        self.assertNotIn(CD, d["run"])
        self.assertEqual(counts(d["aspect"]["outside_sprint"])[0], 1003)

    def test_an_event_file_dated_before_the_window_is_not_read(self):
        old = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).timestamp()
        os.utime(self.events(CD), (old, old))
        reader = spend.SpendReader(repo_of=lambda cwd: cwd)
        self.assertNotIn("e4", self.read(reader=reader).engine)
        os.utime(self.events(CD), (FIXED, FIXED))
        self.assertIn("e4", self.read(reader=reader).engine)

    def test_phase_shares_count_no_engine_session(self):
        snapshot = self.read()
        for program in (spend.BATCH, spend.STANDARD):
            self.assertEqual(spend.phase_shares(snapshot, program, "2026-11-16", "2026-11-16")[0], 0)

    def test_without_an_engine_root_nothing_is_attributed(self):
        snapshot = self.read(engine=False)
        self.assertEqual((dict(snapshot.engine), dict(snapshot.starters)), ({}, {}))
        self.assertNotIn(AB, self.view(snapshot)["run"])

    def test_the_recorded_runs_are_ledgers_the_engine_reads(self):
        for run_dir in (FIXTURE / "runs").iterdir():
            engine_ledger.read_run(run_dir)
            engine_ledger.replay(run_dir / "events.jsonl")

    def test_a_swept_run_keeps_its_attribution_while_its_events_are_in_the_window(self):
        inside = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp()
        for run in (AB, EF):
            os.utime(self.events(run), (inside, inside))
        reader = spend.SpendReader(repo_of=lambda cwd: cwd)
        self.read(reader=reader)
        for run in (AB, EF):
            shutil.rmtree(self.tree / "runs" / run)
        snapshot = self.read(reader=reader)
        d = self.view(snapshot)
        self.assertEqual(snapshot.engine["e1"], spend.EngineSession(AB, "plan", "planning"))
        self.assertEqual(snapshot.engine["e5"].run, AB)
        self.assertEqual(counts(d["run"][AB]), (1190, 0, 0, 7))
        self.assertEqual(counts(d["sprint"][SPRINT]), (1200, 0, 0, 7))
        later = self.read(reader=reader, since="2026-11-11")
        d = self.view(later)
        self.assertNotIn("e1", later.engine)
        self.assertNotIn(AB, d["run"])
        self.assertEqual(counts(d["aspect"]["outside_sprint"]), (1193, 0, 0, 7))
        self.assertIn("e4", later.engine)

    def test_a_reader_started_after_the_sweep_counts_the_sessions_as_ordinary(self):
        inside = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp()
        for run in (AB, EF):
            os.utime(self.events(run), (inside, inside))
            shutil.rmtree(self.tree / "runs" / run)
        snapshot = self.read()
        d = self.view(snapshot)
        self.assertNotIn("e1", snapshot.engine)
        self.assertEqual(counts(d["sprint"][SPRINT]), (10, 0, 0, 0))


class EngineSpendServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        items = support.entries(1)
        self.project_root = items[0]["root"]
        support.write_registry(self.registry, items)

    def test_the_service_spend_view_reads_the_engine_runs_root(self):
        shutil.copytree(FIXTURE / "runs", self.root / "runs")
        projects = self.root / "config/projects/-srv-p00"
        projects.mkdir(parents=True)
        for source in (FIXTURE / "projects/-srv-p00").glob("*.jsonl"):
            lines = [json.loads(line) for line in source.read_text().splitlines()]
            for line in lines:
                if "cwd" in line:
                    line["cwd"] = self.project_root
            (projects / source.name).write_text("".join(json.dumps(line) + "\n" for line in lines))
        stamp(self.root / "runs")
        stamp(self.root / "config")
        svc = support.service(self, self.store, self.registry,
                              session_dirs=[self.root / "config/sessions"],
                              engine_runs_root=self.root / "runs", clock=lambda: FIXED)
        svc.poll_spend()
        day = json.loads(svc.view_bytes)["spend"]["days"][-1]
        self.assertEqual(day["day"], "2026-11-16")
        self.assertEqual(day["run"][AB]["input"], 1190)


if __name__ == "__main__":
    unittest.main()
