"""Contract tests for `engine deliver` (#1512): a procedure of command steps to done or a stop.

Every command step runs a stand-in project command (tests/fixtures/engine-deliver/standin.py,
agent-helpers rule 5) in a hermetic project from `GuardPolicyWorld`; the engine itself runs as a
child process from source.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.delivery import engine, engine_ledger
from agent_tools.delivery.engine_ledger import RUN_ID_RE
from agent_tools.delivery.engine_shell import creation_lock_path, lock_holder, platform_revision
from tests.guard_policy_world import GuardPolicyWorld

REPO_ROOT = Path(__file__).resolve().parents[1]
STANDIN = REPO_ROOT / "tests/fixtures/engine-deliver/standin.py"
SHIPPED = REPO_ROOT / "python/agent_tools/delivery/procedures"


def ANY_SENTENCE(test: unittest.TestCase, value: object) -> None:
    test.assertIsInstance(value, str)
    test.assertTrue(value)
    test.assertTrue(value.endswith("."), value)
    test.assertNotIn("\n", value)


class EngineProject:
    def __init__(self, test_case: unittest.TestCase) -> None:
        self.test = test_case
        self.world = GuardPolicyWorld(test_case)
        self.tmp = Path(tempfile.mkdtemp(dir=self.world.tmp))
        self.record = self.tmp / "record.log"
        self.release = self.tmp / "release"
        self.root = self.world.project("example/engine", "example/engine", register=False,
                                       mutate=self.add_standins)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        decoy = self.bin / "forge-claim"
        decoy.write_text(f"#!/bin/sh\nexec {sys.executable} {STANDIN} verdict held_by 0 \"$@\"\n",
                         encoding="utf-8")
        decoy.chmod(0o755)
        self.env = {key: value for key, value in self.world.env.items()
                    if key != "AGENT_PLATFORM_ROOT"}
        self.env["PATH"] = f"{self.bin}{os.pathsep}{self.world.env['PATH']}"

    def add_standins(self, contract: dict) -> None:
        def entry(*words: str) -> dict:
            return {"argv": [sys.executable, str(STANDIN), *words], "cwd": ".", "env": []}
        contract["bindings"]["commands"].update({
            "standin-json": entry("json", "0"),
            "standin-record": entry("record", str(self.record)),
            "standin-fail": entry("silent", "1"),
            "standin-says-failed": entry("verdict", "failed", "0"),
            "standin-says-maybe": entry("verdict", "maybe", "0"),
            "standin-says-exhausted": entry("verdict", "exhausted", "0"),
            "standin-block": entry("block", str(self.release)),
        })

    def procedures(self, steps: list[dict], *, inputs=("issue",), stops=None) -> Path:
        directory = Path(tempfile.mkdtemp(dir=self.tmp))
        document = {"format": 1,
                    "keep_alive": {"command": "forge-claim", "subcommand": "renew",
                                   "in": ["run.issue"]},
                    "inputs": list(inputs),
                    "stops": stops or {"needs-owner": {"need": "owner-decision",
                                                       "reenter": steps[0]["id"]}},
                    "steps": steps}
        (directory / "deliver.json").write_text(json.dumps(document), encoding="utf-8")
        return directory

    def command(self, *words: str, cwd: Path | None = None, **kwargs):
        return [sys.executable, "-m", "agent_tools.delivery.engine", *words], {
            "cwd": cwd or self.root, "env": self.env, "text": True, **kwargs}

    def deliver(self, procedures: Path, issue: int = 1512, cwd: Path | None = None):
        argv, options = self.command("deliver", str(issue), "--procedures", str(procedures),
                                     cwd=cwd)
        return subprocess.run(argv, capture_output=True, timeout=120, **options)

    def status(self, issue: int):
        argv, options = self.command("status", str(issue))
        return subprocess.run(argv, capture_output=True, timeout=120, **options)

    def runs(self) -> list[Path]:
        root = self.world.home / ".agents/state/engine/runs"
        if not root.is_dir():
            return []
        return sorted(entry for entry in root.iterdir() if RUN_ID_RE.match(entry.name))

    @staticmethod
    def events(run: Path) -> list[dict]:
        return engine_ledger.replay(run / "events.jsonl")


def step(id: str, command: str, ok: str | None, *, failed: str = "needs-owner",
         subcommand: str | None = None, on: dict | None = None) -> dict:
    document = {"id": id, "stage": "setup", "kind": "command", "command": command,
                "in": ["run.issue"], "on": on or {"ok": ok, "failed": failed}}
    if subcommand:
        document["subcommand"] = subcommand
    return document


def shape(events: list[dict]) -> list[tuple]:
    return [(e["event"], e.get("step"), e.get("visit")) for e in events]


class DeliverTest(unittest.TestCase):
    def test_a_three_command_procedure_runs_to_done_and_records_every_step_in_order(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("a", "standin-json", "b"), step("b", "standin-record", "c"),
            step("c", "standin-json", "done")])
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stderr)
        runs = project.runs()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(len(done.stdout.splitlines()), 1)
        line = json.loads(done.stdout)
        ANY_SENTENCE(self, line.pop("detail"))
        self.assertEqual(line, {"end": "done", "need": None, "run": run.name})
        self.assertEqual(RUN_ID_RE.match(run.name).group(1), "1512")
        expected = []
        for name in "abc":
            expected += [("step_entered", name, 1), ("process_started", name, 1),
                         ("result_stored", name, 1), ("outcome_graded", name, 1),
                         ("transition_taken", name, 1)]
        expected.append(("run_done", None, None))
        events = project.events(run)
        self.assertEqual(shape(events), expected)
        taken = [e for e in events if e["event"] == "transition_taken"]
        self.assertEqual([e["to"] for e in taken], ["b", "c", "done"])
        self.assertEqual({e["outcome"] for e in taken}, {"ok"})
        self.assertEqual(json.loads((run / "results/b.1.json").read_text())["argv"], ["1512"])
        document = json.loads((run / "run.json").read_text())
        self.assertEqual(document["platform_revision"], "source")
        self.assertEqual(document["procedure"], "deliver")
        self.assertEqual(document["project"], "example/engine")
        self.assertEqual(document["inputs"], {"issue": 1512})
        status = project.status(1512)
        self.assertEqual(status.returncode, 0, status.stderr)
        state = json.loads(status.stdout)
        self.assertIs(state["done"], True)
        self.assertIsNone(state["stop"])

    def test_a_failing_command_reaches_the_stop_with_its_code_name_and_need(self):
        for command in ("standin-fail", "standin-says-failed"):
            with self.subTest(command=command):
                project = EngineProject(self)
                stopped = project.deliver(project.procedures([step("a", command, "done")]))
                self.assertEqual(stopped.returncode, 3, stopped.stderr)
                run = project.runs()[0]
                self.assertEqual(len(stopped.stdout.splitlines()), 1)
                line = json.loads(stopped.stdout)
                ANY_SENTENCE(self, line.pop("detail"))
                self.assertEqual(line, {"end": "needs-owner", "need": "owner-decision",
                                        "run": run.name})
                events = project.events(run)
                last = events[-1]
                self.assertEqual((last["event"], last["step"], last["stop"], last["need"]),
                                 ("stop_reached", "a", "needs-owner", "owner-decision"))
                graded = [e for e in events if e["event"] == "outcome_graded"]
                self.assertEqual([e["outcome"] for e in graded], ["failed"])
                state = json.loads(project.status(1512).stdout)
                self.assertEqual(state["stop"], {"name": "needs-owner",
                                                 "need": "owner-decision"})

    def test_a_platform_command_runs_its_source_module_never_a_program_on_path(self):
        project = EngineProject(self)
        procedures = project.procedures([step(
            "a", "forge-claim", None, subcommand="status",
            on={"free": "needs-owner", "held_by": "needs-owner", "stale": "needs-owner",
                "error": "done"})])
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        run = project.runs()[0]
        result = json.loads((run / "results/a.1.json").read_text())
        self.assertEqual((result["verdict"], result["error"]), ("error", "usage"))
        self.assertNotIn("argv", result)
        taken = [e for e in project.events(run) if e["event"] == "transition_taken"]
        self.assertEqual([(e["step"], e["outcome"]) for e in taken], [("a", "error")])

    def test_an_unmapped_verdict_is_a_fault_with_no_outcome_event(self):
        project = EngineProject(self)
        faulted = project.deliver(project.procedures([step("a", "standin-says-maybe", "done")]))
        self.assertEqual(faulted.returncode, 1)
        self.assertEqual(faulted.stdout, "")
        self.assertEqual(len(faulted.stderr.splitlines()), 1)
        self.assertIn("maybe", faulted.stderr)
        last = project.events(project.runs()[0])[-1]
        self.assertEqual((last["event"], last["step"]), ("result_stored", "a"))

    def test_the_reserved_exhausted_verdict_is_a_fault_with_no_outcome_or_transition(self):
        project = EngineProject(self)
        bounded = step("a", "standin-says-exhausted", None, on={
            "ok": "done", "failed": "needs-owner", "exhausted": "needs-owner"})
        bounded["max_visits"] = 2
        faulted = project.deliver(project.procedures([bounded]))
        self.assertEqual(faulted.returncode, 1)
        self.assertEqual(faulted.stdout, "")
        self.assertIn("exhausted", faulted.stderr)
        run = project.runs()[0]
        events = project.events(run)
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("result_stored", "a"))
        self.assertEqual([e for e in events if e["event"] in ("outcome_graded", "transition_taken")],
                         [])
        state = json.loads(project.status(1512).stdout)
        self.assertEqual((state["stop"], state["done"]), (None, False))

    def test_the_run_follows_its_own_procedure_copy(self):
        project = EngineProject(self)
        steps = [step("a", "standin-block", "b"), step("b", "standin-json", "done")]
        procedures = project.procedures(steps)
        argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.kill)
        self.addCleanup(process.communicate)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            runs = project.runs()
            if runs and any(e["event"] == "process_started" for e in project.events(runs[0])):
                break
            time.sleep(0.05)
        else:
            self.fail("the run never started its step process")
        edited = json.loads((procedures / "deliver.json").read_text())
        edited["steps"][0]["on"]["ok"] = "needs-owner"
        (procedures / "deliver.json").write_text(json.dumps(edited), encoding="utf-8")
        project.release.write_text("go", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["end"], "done")


class RefusalTest(unittest.TestCase):
    def assertRefused(self, project: EngineProject, done, word: str) -> None:
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn(word, done.stderr)
        self.assertEqual(project.runs(), [])
        self.assertFalse(project.record.exists())

    def test_an_unknown_command_id_refuses_the_procedure_before_any_process(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "b"),
                                         step("b", "no-such-command", "done")])
        self.assertRefused(project, project.deliver(procedures), "unknown_command")

    def test_a_procedure_the_engine_cannot_run_is_refused(self):
        def shipped(project: EngineProject) -> Path:
            directory = project.tmp / "shipped"
            shutil.copytree(SHIPPED, directory)
            (directory / "toy.json").rename(directory / "deliver.json")
            return directory

        def with_mutation(project: EngineProject) -> Path:
            first = step("a", "standin-record", "done")
            first["mutates"] = True
            return project.procedures([first])

        def empty(project: EngineProject) -> Path:
            return Path(tempfile.mkdtemp(dir=project.tmp))

        cases = {
            "an undeclared input": (
                "repo", lambda p: p.procedures([step("a", "standin-record", "done")],
                                               inputs=("issue", "repo"))),
            "a mutating step": ("mutates", with_mutation),
            "an agent step": ("agent", shipped),
            "no deliver.json": ("deliver.json", empty),
        }
        for name, (word, build) in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                self.assertRefused(project, project.deliver(build(project)), word)
        with self.subTest("outside any project"):
            project = EngineProject(self)
            procedures = project.procedures([step("a", "standin-record", "done")])
            outside = Path(tempfile.mkdtemp(dir=project.tmp))
            self.assertRefused(project, project.deliver(procedures, cwd=outside),
                               "not_onboarded")


class LockTest(unittest.TestCase):
    def start(self, project: EngineProject, procedures: Path) -> subprocess.Popen:
        argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.communicate)
        self.addCleanup(process.kill)
        self.addCleanup(project.release.write_text, "go", encoding="utf-8")
        return process

    def test_a_second_deliver_during_a_run_exits_already_running_and_appends_nothing(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-block", "done")])
        first = self.start(project, procedures)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            runs = project.runs()
            if runs and any(e["event"] == "process_started" for e in project.events(runs[0])):
                break
            time.sleep(0.05)
        else:
            self.fail("the run never started its step process")
        run = runs[0]
        before = (run / "events.jsonl").read_bytes()
        runs_before = project.runs()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 4, second.stdout + second.stderr)
        self.assertEqual(len(second.stdout.splitlines()), 1)
        line = json.loads(second.stdout)
        ANY_SENTENCE(self, line.pop("detail"))
        self.assertIsInstance(line["process"].pop("started"), str)
        self.assertEqual(line, {"end": None, "need": None, "process": {"pid": first.pid},
                                "run": run.name})
        self.assertEqual((run / "events.jsonl").read_bytes(), before)
        self.assertEqual(project.runs(), runs_before)
        self.assertEqual(json.loads((run / "lock").read_text())["pid"], first.pid)
        project.release.write_text("go", encoding="utf-8")
        self.assertEqual(first.wait(60), 0)
        self.assertEqual(project.events(run)[-1]["event"], "run_done")

    def test_creating_a_run_waits_for_the_issue_creation_lock(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        root = project.world.home / ".agents/state/engine/runs"
        root.mkdir(parents=True, mode=0o700)
        descriptor = os.open(creation_lock_path(root, 1512), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        process = self.start(project, procedures)
        time.sleep(1.0)
        self.assertIsNone(process.poll())
        self.assertEqual(project.runs(), [])
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        self.assertEqual(process.wait(60), 0)
        self.assertEqual(len(project.runs()), 1)

    def test_a_stopped_run_is_not_joined_by_a_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-fail", "done")])
        self.assertEqual(project.deliver(procedures).returncode, 3)
        run = project.runs()[0]
        before = (run / "events.jsonl").read_bytes()
        again = project.deliver(procedures)
        self.assertEqual(again.returncode, 2, again.stdout + again.stderr)
        self.assertEqual(again.stdout, "")
        self.assertEqual(len(again.stderr.splitlines()), 1, again.stderr)
        self.assertEqual(len(project.runs()), 1)
        self.assertEqual((run / "events.jsonl").read_bytes(), before)

    def test_a_done_run_lets_the_next_deliver_start_a_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        self.assertEqual(project.deliver(procedures).returncode, 0)
        again = project.deliver(procedures)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(len(project.runs()), 2)

    def seed_runs(self, project: EngineProject, procedures: Path, *, done: str, other: str):
        """Two runs of the issue started in one second: `done` is finished, `other` is not."""
        root = project.world.home / ".agents/state/engine/runs"
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        runs = {}
        for token in (done, other):
            runs[token] = engine_ledger.create_run(
                project="example/engine", issue=1512, procedure="deliver",
                procedures_dir=procedures, platform_revision="source", host="test",
                inputs={"issue": 1512}, now=now, token=token, root=root)
        engine_ledger.append_event(runs[done], {"event": "run_done",
                                                "at": "2026-11-21T00:00:01Z"})
        return runs[other]

    def test_a_done_run_never_hides_a_running_run_started_in_the_same_second(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        running = self.seed_runs(project, procedures, done="zzzz", other="aaaa")
        descriptor = os.open(running / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, json.dumps({"pid": os.getpid(),
                                         "started": "2026-11-21T00:00:00Z"}).encode("utf-8"))
        runs_before = project.runs()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 4, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], running.name)
        self.assertEqual(project.runs(), runs_before)

    def test_a_done_run_never_hides_a_stopped_run_started_in_the_same_second(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        stopped = self.seed_runs(project, procedures, done="zzzz", other="aaaa")
        runs_before = project.runs()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        self.assertIn(stopped.name, second.stderr)
        self.assertEqual(project.runs(), runs_before)

    def test_lock_holder_reads_only_a_held_lock(self):
        with tempfile.TemporaryDirectory() as name:
            run_dir = Path(name)
            self.assertIsNone(lock_holder(run_dir))
            self.assertFalse((run_dir / "lock").exists())
            content = {"pid": 42, "started": "2026-11-21T00:00:00Z"}
            (run_dir / "lock").write_text(json.dumps(content), encoding="utf-8")
            self.assertIsNone(lock_holder(run_dir))
            descriptor = os.open(run_dir / "lock", os.O_RDWR)
            self.addCleanup(os.close, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self.assertEqual(lock_holder(run_dir), content)


class ShapeTest(unittest.TestCase):
    def test_deliver_takes_only_an_issue_and_a_procedures_directory(self):
        import argparse
        parser = engine.build_parser()
        action = next(a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({a.dest for a in action.choices["deliver"]._actions},
                         {"help", "issue", "procedures"})

    def test_the_platform_revision_is_the_package_directory_or_source(self):
        self.assertEqual(platform_revision({}), "source")
        self.assertEqual(platform_revision({"AGENT_PLATFORM_ROOT": ""}), "source")
        root = "/nix/store/" + "a" * 32 + "-agent-platform/share/agent-platform"
        self.assertEqual(platform_revision({"AGENT_PLATFORM_ROOT": root}),
                         "a" * 32 + "-agent-platform")


if __name__ == "__main__":
    unittest.main()
