"""Contract tests for `engine deliver` (#1512): a procedure of command steps to done or a stop.

Every command step runs a stand-in project command (tests/fixtures/engine-deliver/standin.py,
agent-helpers rule 5) in a hermetic project from `GuardPolicyWorld`; the engine itself runs as a
child process from source.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine, engine_commands, engine_ledger, engine_shell
from agent_tools.delivery.engine_commands import command_text
from agent_tools.delivery.engine_guard import Hook, judge, payload
from agent_tools.delivery.engine_ledger import RUN_ID_RE
from agent_tools.delivery.engine_shell import creation_lock_path, lock_holder, platform_revision
from tests.engine_guards import (
    GUARD_NAME, STANDIN_GUARD, payloads, real_guard, real_pre_push_hooks, recorder, script,
    standin_guard, write_settings)
from tests.guard_policy_world import REAL_GIT, GuardPolicyWorld

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
STANDIN = REPO_ROOT / "tests/fixtures/engine-deliver/standin.py"
SHIPPED = REPO_ROOT / "python/agent_tools/delivery/procedures"

LIFECYCLE_SPELLINGS: dict[str, list[str]] = {
    "publish": ["git", "-C", ".", "push", "origin", "HEAD:refs/heads/issue-7-topic"],
    "open-review": ["gh", "--repo", "example/engine", "pr", "create", "--title", "t", "--body", "b"],
    "land": ["/usr/bin/env", "gh", "pr", "merge", "7", "--repo", "example/engine", "--merge",
             "--delete-branch"],
    "tidy": ["git", "branch", "--delete", "issue-7-topic"],
    "cut": ["gh", "release", "new", "v1.0.0"],
}


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
        self.guard_log = self.tmp / "guard.log"
        self.release = self.tmp / "release"
        self.renewals = self.tmp / "renewals.log"
        self.answers = self.tmp / "answers.json"
        self.hold = self.tmp / "hold.pid"
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
        write_settings(self.world.home, str(standin_guard(
            self.tmp, "allow-guard", "allow", str(self.guard_log))))

    def use_guard(self, command: Path | str, timeout: object = 30, **extra) -> None:
        write_settings(self.world.home, str(command), timeout, extra=extra or None)

    def use_settings_text(self, text: str) -> None:
        path = self.world.home / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def record_tools(self) -> None:
        shims = self.tmp / "tool-shims"
        log = self.tmp / "tools.log"
        recorder(shims, "git", log, REAL_GIT)
        recorder(shims, "gh", log, None)
        self.env["PATH"] = f"{shims}{os.pathsep}{self.env['PATH']}"

    def git(self, *words: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([REAL_GIT, *words], cwd=self.root, env=self.env,
                              capture_output=True, text=True, check=check)

    def guard_repository(self) -> None:
        self.git("remote", "remove", "origin", check=False)
        self.git("remote", "add", "origin", "git@github.com:example/engine.git")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

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
            "standin-says-out-of-bounds": entry("verdict", "out-of-bounds", "0"),
            "standin-block": entry("block", str(self.release)),
            "release": entry("json", "0"),
            "count-a": entry("record", str(self.tmp / "a.log")),
            "count-b": entry("record", str(self.tmp / "b.log")),
            "count-c": entry("record", str(self.tmp / "c.log")),
            "count-d": entry("record", str(self.tmp / "d.log")),
            "standin-gate": entry("gate", str(self.tmp / "gate.log"),
                                  str(self.tmp / "gate-open")),
            "standin-effect": entry("effect", str(self.tmp / "effect.log"),
                                    str(self.tmp / "kill-before"), str(self.tmp / "kill-after")),
            "standin-effect-check": entry("effect-check", str(self.tmp / "effect.log"),
                                          str(self.tmp / "checks.log")),
            "standin-parity": entry("parity", str(self.tmp / "parity.log")),
            "standin-keep-alive": entry("answers", str(self.renewals), str(self.answers)),
            "standin-hold": entry("hold", str(self.hold), "0"),
        })
        land = ["gh", "pr", "merge", "7", "--repo", "example/engine", "--merge"]
        contract["bindings"]["commands"].update(
            {name: {"argv": argv, "cwd": ".", "env": []} for name, argv in {
                "land-bare": land, "land-subject": [*land, "--subject", "Land it"],
                "land-word": [*land, "--subject", "Land"],
                "tidy-merged": ["git", "branch", "-d", "issue-7-topic"],
                "ship-wrapper": ["/bin/sh", str(self.tmp / "ship.sh")]}.items()})
        contract["bindings"]["commands"].update(
            {name: {"argv": list(argv), "cwd": ".", "env": []}
             for name, argv in LIFECYCLE_SPELLINGS.items()})

    def calls(self, name: str) -> int:
        log = self.tmp / f"{name}.log"
        return len(log.read_text().splitlines()) if log.exists() else 0

    def argvs(self, name: str) -> list:
        log = self.tmp / f"{name}.log"
        return [json.loads(line)["argv"] for line in log.read_text().splitlines()] \
            if log.exists() else []

    def answer(self, *answers: dict) -> None:
        self.answers.write_text(json.dumps(list(answers)), encoding="utf-8")

    def renewal_calls(self) -> list[dict]:
        if not self.renewals.exists():
            return []
        return [json.loads(line) for line in self.renewals.read_text(encoding="utf-8").splitlines()]

    def procedures(self, steps: list[dict], *, inputs=("issue",), stops=None,
                   keep_alive: dict | None = None) -> Path:
        directory = Path(tempfile.mkdtemp(dir=self.tmp))
        default = {"needs-owner": {"need": "owner-decision", "reenter": steps[0]["id"]}}
        if keep_alive:
            default["claim-lost"] = {"need": "owner-decision", "reenter": steps[0]["id"]}
        document = {"format": 1,
                    "inputs": list(inputs),
                    "stops": stops or default,
                    "steps": steps}
        if keep_alive:
            document["keep_alive"] = keep_alive
        (directory / "deliver.json").write_text(json.dumps(document), encoding="utf-8")
        return directory

    def command(self, *words: str, cwd: Path | None = None, **kwargs):
        return [sys.executable, "-m", "agent_tools.delivery.engine", *words], {
            "cwd": cwd or self.root, "env": self.env, "text": True, **kwargs}

    def deliver(self, procedures: Path, issue: int = 1512, cwd: Path | None = None):
        argv, options = self.command("deliver", str(issue), "--procedures", str(procedures),
                                     cwd=cwd)
        return subprocess.run(argv, capture_output=True, timeout=120, **options)

    @contextlib.contextmanager
    def inside(self):
        """This process as `engine deliver` would find itself: in the project, with its env."""
        previous = os.getcwd()
        with mock.patch.dict(os.environ, self.env, clear=True):
            os.chdir(self.root)
            try:
                yield
            finally:
                os.chdir(previous)

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
         subcommand: str | None = None, on: dict | None = None, mutates: bool = False,
         max_visits: int | None = None, refused: str | None = None,
         holds: str = "run") -> dict:
    document = {"id": id, "stage": "setup", "kind": "command", "command": command,
                "holds": holds, "in": ["run.issue"],
                "on": {"refused": refused or failed, **(on or {"ok": ok, "failed": failed})}}
    if subcommand:
        document["subcommand"] = subcommand
    if mutates:
        document["mutates"] = True
        document["check"] = {"command": command}
    if max_visits is not None:
        document["max_visits"] = max_visits
    return document


def shape(events: list[dict]) -> list[tuple]:
    return [(e["event"], e.get("step"), e.get("visit")) for e in events]


def start_deliver(test: unittest.TestCase, project: EngineProject,
                  procedures: Path) -> subprocess.Popen:
    argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process = subprocess.Popen(argv, **options)
    test.addCleanup(process.communicate)
    test.addCleanup(process.kill)
    test.addCleanup(project.release.write_text, "go", encoding="utf-8")
    return process


def wait_for_process_started(project: EngineProject) -> Path:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        runs = project.runs()
        if runs and any(e["event"] == "process_started" for e in project.events(runs[0])):
            return runs[0]
        time.sleep(0.05)
    raise AssertionError("the run never started its step process")


LAUNCH = """
import os, runpy, shutil, sys
from agent_tools.delivery import engine_shell
real = engine_shell._validate
edited, source = sys.argv[1], sys.argv[-1]

def wrapper(directory, table):
    result = real(directory, table)
    engine_shell._validate = real
    shutil.copyfile(edited, os.path.join(source, "deliver.json"))
    return result

engine_shell._validate = wrapper
sys.argv = ["engine"] + sys.argv[2:]
runpy.run_module("agent_tools.delivery.engine", run_name="__main__")
"""


def gated(project: EngineProject, b_holds: str = "head", c_holds: str = "run") -> Path:
    return project.procedures([
        step("a", "count-a", "c"), step("b", "count-b", "g", holds=b_holds),
        step("c", "count-c", "b", holds=c_holds), step("g", "standin-gate", "done"),
        step("d", "count-d", "done")],
        stops={"needs-owner": {"need": "owner-decision", "reenter": "d"}})


def head(project: EngineProject) -> str:
    return project.world.git(project.root, "rev-parse", "HEAD").strip()


def heads(events: list[dict], step_id: str) -> list:
    return [e.get("head") for e in events
            if e["event"] == "result_stored" and e["step"] == step_id]


def run_continued(events: list[dict]) -> list[dict]:
    return [e for e in events if e["event"] == "run_continued"]


class ContinueTest(unittest.TestCase):
    def first_stop(self, project: EngineProject, procedures: Path) -> Path:
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        return project.runs()[0]

    def test_a_second_deliver_continues_a_stopped_run_at_its_stops_reentry_step(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        self.assertEqual(json.loads(first.stdout)["end"], "needs-owner")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual(line["end"], "done")
        self.assertEqual(line["run"], json.loads(first.stdout)["run"])
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual(len(continued), 1)
        self.assertIsInstance(continued[0].pop("at"), str)
        self.assertEqual(continued[0], {"event": "run_continued", "step": "d"})
        kinds = [e["event"] for e in events]
        self.assertLess(kinds.index("stop_reached"), kinds.index("run_continued"))
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 1, 1, 1, 1])
        self.assertEqual(heads(events, "b"), [head(project)])
        self.assertEqual(heads(events, "a"), [None])
        self.assertEqual(heads(events, "c"), [None])
        self.assertTrue(all("head" not in e for e in events
                            if e["event"] == "result_stored" and e["step"] != "b"))

    def test_a_moved_head_reenters_at_the_earliest_head_step_and_runs_no_earlier_run_step_again(self):
        project = EngineProject(self)
        procedures = gated(project, c_holds="head")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        before = head(project)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(json.loads(second.stdout)["run"], json.loads(first.stdout)["run"])
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual([(e["step"], e["visit"]) for e in continued], [("c", 1)])
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 2, 2, 2, 0])
        self.assertEqual(heads(events, "c"), [before, head(project)])
        self.assertEqual(heads(events, "b"), [before, head(project)])
        for name in ("c", "b", "g"):
            self.assertEqual([e["visit"] for e in events
                              if e["event"] == "step_entered" and e["step"] == name], [1, 2])

    def test_a_live_result_is_redone_by_a_continued_run_though_the_head_stayed(self):
        project = EngineProject(self)
        procedures = gated(project, b_holds="live", c_holds="live")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("c", 1)])
        self.assertEqual([project.calls(n) for n in ("a", "c", "b", "gate", "d")],
                         [1, 2, 2, 2, 0])

    def test_a_stop_that_reenters_a_graded_decide_grades_it_again_at_its_visit(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("r", "count-a", "t"),
            {"id": "t", "stage": "setup", "kind": "decide", "grader": "toy-tally",
             "in": ["run.issue"], "holds": "run", "on": {"accept": "done",
                                                         "revise": "needs-owner"}}],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "t"}})
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], json.loads(first.stdout)["run"])
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        continued = run_continued(events)
        self.assertEqual(len(continued), 1)
        self.assertIsInstance(continued[0].pop("at"), str)
        self.assertEqual(continued[0], {"event": "run_continued", "step": "t", "visit": 1})
        self.assertEqual(len([e for e in events if e["event"] == "stop_reached"]), 2)
        self.assertEqual(project.calls("a"), 1)

    def test_a_result_stored_just_before_its_grading_is_graded_from_the_ledger_not_run_again(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("a", "standin-gate", "c", failed="b"), step("b", "count-b", "done"),
            step("c", "count-c", "done")])
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        run = project.runs()[0]
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        cut = next(i for i, line in enumerate(lines)
                   if json.loads(line)["event"] == "result_stored") + 1
        self.assertEqual(json.loads(lines[cut - 1])["outcome"], "failed")
        (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
        (run / "results/b.1.json").unlink()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], run.name)
        after = project.events(run)[cut:]
        self.assertEqual(shape(after), [
            ("outcome_graded", "a", 1), ("transition_taken", "a", 1),
            ("run_continued", "b", 1), ("step_entered", "b", 1), ("process_started", "b", 1),
            ("result_stored", "b", 1), ("outcome_graded", "b", 1),
            ("transition_taken", "b", 1), ("run_done", None, None)])
        self.assertEqual(after[0]["outcome"], "failed")
        self.assertEqual(after[1]["to"], "b")
        self.assertEqual([project.calls("gate"), project.calls("c"), project.calls("b")],
                         [1, 0, 2])

    def test_a_stop_the_owner_never_saw_is_reported_not_walked_past(self):
        for last in ("result_stored", "transition_taken"):
            with self.subTest(killed_after=last):
                project = EngineProject(self)
                procedures = project.procedures([
                    step("a", "standin-gate", "c"), step("b", "count-b", "done"),
                    step("c", "count-c", "done")],
                    stops={"needs-owner": {"need": "owner-decision", "reenter": "b"}})
                run = self.first_stop(project, procedures)
                lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
                cut = next(i for i, line in enumerate(lines)
                           if json.loads(line)["event"] == last) + 1
                (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
                second = project.deliver(procedures)
                self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
                self.assertEqual(json.loads(second.stdout)["end"], "needs-owner")
                after = [e["event"] for e in project.events(run)[cut:]]
                owed = ["outcome_graded", "transition_taken"] if last == "result_stored" else []
                self.assertEqual(after, [*owed, "stop_reached"])
                self.assertEqual(run_continued(project.events(run)), [])
                self.assertEqual(project.calls("b"), 0)
                third = project.deliver(procedures)
                self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
                self.assertEqual([e["step"] for e in run_continued(project.events(run))], ["b"])

    def test_a_run_killed_between_its_grading_and_its_transition_records_the_transition_once(self):
        project = EngineProject(self)
        procedures = project.procedures([
            step("a", "standin-gate", "c", failed="b"), step("b", "count-b", "done"),
            step("c", "count-c", "done")])
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        run = project.runs()[0]
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        cut = next(i for i, line in enumerate(lines)
                   if json.loads(line)["event"] == "outcome_graded") + 1
        (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
        (run / "results/b.1.json").unlink()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        after = project.events(run)[cut:]
        self.assertEqual(shape(after), [
            ("transition_taken", "a", 1),
            ("run_continued", "b", 1), ("step_entered", "b", 1), ("process_started", "b", 1),
            ("result_stored", "b", 1), ("outcome_graded", "b", 1),
            ("transition_taken", "b", 1), ("run_done", None, None)])
        self.assertEqual((after[0]["outcome"], after[0]["to"]), ("failed", "b"))

    def test_a_stop_reached_by_the_opening_decision_is_reported_after_a_kill_left_no_event(self):
        project = EngineProject(self)
        decision = {"id": "d", "stage": "setup", "kind": "decide", "grader": "toy-tally",
                    "holds": "run", "in": ["run.issue"],
                    "on": {"accept": "done", "revise": "needs-owner"}}
        procedures = project.procedures([decision])
        run = self.first_stop(project, procedures)
        (run / "events.jsonl").write_text("", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(second.stderr, "")
        self.assertEqual(json.loads(second.stdout)["end"], "needs-owner")
        self.assertEqual([e["event"] for e in project.events(run)], ["stop_reached"])

    def test_the_head_is_read_from_the_project_though_git_dir_names_another_checkout(self):
        project = EngineProject(self)
        other = Path(tempfile.mkdtemp(dir=project.tmp))
        project.world.git(other, "init", "--quiet")
        project.world.git(other, "commit", "--quiet", "--allow-empty", "-m", "elsewhere")
        elsewhere = project.world.git(other, "rev-parse", "HEAD").strip()
        before = head(project)
        self.assertNotEqual(elsewhere, before)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            self.assertEqual(engine_shell.read_head(str(project.root)), before)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        after = head(project)
        self.assertNotEqual(after, before)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            self.assertEqual(engine_shell.read_head(str(project.root)), after)

    def test_a_head_that_moves_while_its_step_runs_leaves_the_result_stale(self):
        project = EngineProject(self)
        procedures = project.procedures(
            [step("a", "standin-block", "g", holds="head"), step("g", "standin-gate", "done")],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "g"}})
        first = start_deliver(self, project, procedures)
        run = wait_for_process_started(project)
        project.world.git(project.root, "commit", "--quiet", "--allow-empty", "-m", "moved")
        project.release.write_text("go", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 3, stdout + stderr)
        self.assertEqual(heads(project.events(run), "a"), [None])
        (project.tmp / "gate-open").write_text("go", encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        events = project.events(run)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("a", 1)])
        self.assertEqual(len([e for e in events
                              if e["event"] == "process_started" and e["step"] == "a"]), 2)
        self.assertEqual(project.calls("gate"), 2)
        self.assertEqual(heads(events, "a"), [None, head(project)])

    def test_a_continued_run_reads_its_own_procedure_copy_not_the_source(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        shutil.rmtree(procedures)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(project.calls("d"), 1)

    def seed(self, project: EngineProject, procedures: Path, *tokens: str) -> list[Path]:
        root = project.world.home / ".agents/state/engine/runs"
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        return [engine_ledger.create_run(
            project="example/engine", issue=1512, procedure="deliver",
            procedures_dir=procedures, platform_revision="source", host="test",
            inputs={"issue": 1512}, now=now, token=token, root=root) for token in tokens]

    def test_two_open_runs_of_the_issue_are_refused_and_left_unchanged(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        runs = self.seed(project, procedures, "aaaa", "bbbb")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        for run in runs:
            self.assertIn(run.name, done.stderr)
            self.assertEqual((run / "events.jsonl").read_bytes(), b"")
        self.assertEqual(project.runs(), sorted(runs))
        self.assertFalse(project.record.exists())

    def test_a_run_that_reached_done_without_its_done_event_is_finished_without_running_a_step(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        (run,) = self.seed(project, procedures, "aaaa")
        at = "2026-11-21T00:00:01Z"
        engine_ledger.append_event(run, {"event": "step_entered", "at": at, "step": "a",
                                         "visit": 1, "stage": "setup"})
        engine_ledger.store_result(run, step="a", visit=1, result={}, at=at, wall_seconds=0,
                                   turns=0, tokens=dict(engine_shell.NO_TOKENS), spend_usd=0,
                                   outcome="ok")
        engine_ledger.append_event(run, {"event": "outcome_graded", "at": at, "step": "a",
                                         "visit": 1, "outcome": "ok"})
        engine_ledger.append_event(run, {"event": "transition_taken", "at": at, "step": "a",
                                         "visit": 1, "outcome": "ok", "to": "done"})
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        events = project.events(run)
        self.assertEqual(events[-1]["event"], "run_done")
        self.assertEqual(run_continued(events), [])
        self.assertFalse(project.record.exists())


def mutating(project: EngineProject) -> Path:
    m = step("m", "standin-effect", "b")
    m.update({"mutates": True, "check": {"command": "standin-effect-check"}})
    return project.procedures([step("a", "count-a", "m"), m, step("b", "count-b", "done")])


def looped(project: EngineProject) -> Path:
    a = step("a", "count-a", "p", holds="live")
    p = step("p", "standin-parity", None,
             on={"ok": "m", "failed": "needs-owner", "exhausted": "b"})
    p["max_visits"] = 2
    m = step("m", "standin-effect", None,
             on={"ok": "p", "failed": "needs-owner", "exhausted": "b"})
    m.update({"in": ["p.n"], "max_visits": 2, "mutates": True,
              "check": {"command": "standin-effect-check"}})
    return project.procedures([a, p, m, step("b", "count-b", "done")])


class MutatingContinueTest(unittest.TestCase):
    def test_a_run_killed_after_a_mutating_command_took_effect_does_not_run_it_again(self):
        project = EngineProject(self)
        procedures = mutating(project)
        (project.tmp / "kill-after").write_text("1512", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.calls("effect"), 1)
        run = project.runs()[0]
        self.assertFalse([e for e in project.events(run)
                          if e["event"] == "result_stored" and e["step"] == "m"])
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual((line["end"], line["run"]), ("done", run.name))
        self.assertEqual(project.runs(), [run])
        self.assertEqual(project.calls("effect"), 1)
        self.assertEqual(project.calls("checks"), 1)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(project.events(run))],
                         [("m", 1)])
        self.assertEqual(json.loads((run / "results/m.2.json").read_text()),
                         {"argv": ["1512"], "verdict": "ok"})
        self.assertEqual((project.calls("a"), project.calls("b")), (1, 1))

    def test_a_rewind_through_a_mutating_loop_checks_every_replayed_visit_and_repeats_no_effect(self):
        project = EngineProject(self)
        procedures = looped(project)
        (project.tmp / "kill-after").write_text("1", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        run = project.runs()[0]
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        line = json.loads(second.stdout)
        self.assertEqual((line["end"], line["run"]), ("done", run.name))
        events = project.events(run)
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("a", 1)])
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        self.assertEqual(project.argvs("checks"), [["0"], ["1"]])
        self.assertEqual([e["visit"] for e in events
                          if e["event"] == "step_entered" and e["step"] == "m"], [1, 2, 3, 4])
        self.assertEqual(json.loads((run / "results/m.3.json").read_text()),
                         {"argv": ["0"], "verdict": "ok"})
        self.assertEqual(json.loads((run / "results/m.4.json").read_text()),
                         {"argv": ["1"], "verdict": "ok"})
        self.assertEqual((project.calls("a"), project.calls("b")), (2, 1))

    def test_a_kill_after_the_first_iteration_effect_repeats_no_effect_when_the_replay_visits_other_arguments_first(self):
        project = EngineProject(self)
        procedures = looped(project)
        (project.tmp / "kill-after").write_text("0", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.argvs("effect"), [["0"]])
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual(project.argvs("effect"), [["0"], ["1"]])
        # the check is owed to the step, so the other arguments are checked too: harmless, they ran nothing yet
        self.assertEqual(project.argvs("checks"), [["1"], ["0"]])

    def test_a_mutating_command_whose_check_finds_no_effect_runs_after_the_check(self):
        project = EngineProject(self)
        procedures = mutating(project)
        (project.tmp / "kill-before").write_text("go", encoding="utf-8")
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, -signal.SIGKILL, first.stdout + first.stderr)
        self.assertEqual(project.calls("effect"), 0)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        self.assertEqual((project.calls("effect"), project.calls("checks")), (1, 1))
        self.assertEqual(json.loads((project.runs()[0] / "results/m.2.json").read_text()),
                         {"argv": ["1512"]})

    def test_a_first_visit_of_a_mutating_step_runs_no_check(self):
        project = EngineProject(self)
        done = project.deliver(mutating(project))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        self.assertEqual((project.calls("effect"), project.calls("checks")), (1, 0))


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
                "error": "done", "refused": "needs-owner"})])
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
            "ok": "done", "failed": "needs-owner", "refused": "needs-owner",
            "exhausted": "needs-owner"})
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

    def test_a_command_diagnostic_still_reaches_the_engine_stderr(self):
        project = EngineProject(self)
        project.answer({"stdout": "{\"verdict\":\"ok\"}", "stderr": "marker-diagnostic\n",
                        "exit": 0})
        done = project.deliver(project.procedures([
            step("a", "standin-keep-alive", None,
                 on={"ok": "done", "failed": "needs-owner", "refused": "needs-owner"})]))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("marker-diagnostic", done.stderr)

    def test_a_printed_out_of_bounds_verdict_is_a_fault_with_no_outcome(self):
        project = EngineProject(self)
        faulted = project.deliver(project.procedures([
            step("a", "standin-says-out-of-bounds", None,
                 on={"ok": "done", "failed": "needs-owner", "refused": "needs-owner",
                     "out-of-bounds": "needs-owner"})]))
        self.assertEqual(faulted.returncode, 1)
        self.assertEqual(faulted.stdout, "")
        self.assertEqual(len(faulted.stderr.splitlines()), 1)
        self.assertIn("out-of-bounds", faulted.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("result_stored", "a"))
        self.assertEqual([e for e in events if e["event"] in ("outcome_graded", "transition_taken")],
                         [])

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


class BoundsTest(unittest.TestCase):
    def sleeping(self, project: EngineProject, on: dict) -> Path:
        """One command step that sleeps, since the release file is never created."""
        return project.procedures(
            [step("a", "standin-block", None, on=on)],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "a"},
                   "step-failed": {"need": "retry", "reenter": "a"}})

    def assert_gone(self, pid: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail(f"process {pid} outlived its step")

    def test_a_command_past_its_wall_bound_is_ended_and_out_of_bounds(self):
        project = EngineProject(self)
        procedures = self.sleeping(project, {"ok": "done", "failed": "needs-owner",
                                             "refused": "needs-owner",
                                             "out-of-bounds": "step-failed"})
        started = time.monotonic()
        with project.inside(), mock.patch.object(engine_commands, "PROJECT_WALL_SECONDS", 1):
            code, line = engine_shell.deliver(1520, procedures)
        elapsed = time.monotonic() - started
        self.assertEqual((code, line["end"], line["need"]), (3, "step-failed", "retry"))
        self.assertLess(elapsed, 20)
        run = project.runs()[0]
        self.assertEqual(json.loads((run / "results/a.1.json").read_text()),
                         {"bound": "wall-time"})
        events = project.events(run)
        stored = [e for e in events if e["event"] == "result_stored"]
        self.assertGreaterEqual(stored[0]["wall_seconds"], 1)
        self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                         ["out-of-bounds"])
        pids = [e["pid"] for e in events if e["event"] == "process_started"]
        self.assertEqual(len(pids), 1)
        self.assert_gone(pids[0])

    def test_a_command_past_its_wall_bound_that_does_not_map_it_is_graded_then_a_fault(self):
        project = EngineProject(self)
        procedures = self.sleeping(project, {"ok": "done", "failed": "needs-owner", "refused": "needs-owner"})
        with project.inside(), mock.patch.object(engine_commands, "PROJECT_WALL_SECONDS", 1):
            with self.assertRaises(engine_shell.Fault) as raised:
                engine_shell.deliver(1520, procedures)
        self.assertIn("out-of-bounds", str(raised.exception))
        run = project.runs()[0]
        self.assertEqual(json.loads((run / "results/a.1.json").read_text()),
                         {"bound": "wall-time"})
        events = project.events(run)
        self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                         ["out-of-bounds"])
        self.assertEqual([e for e in events if e["event"] == "transition_taken"], [])

    def test_a_closed_stderr_does_not_keep_a_killed_command_from_being_graded(self):
        class Closed:
            class buffer:
                @staticmethod
                def write(data: bytes) -> int:
                    raise BrokenPipeError(32, "Broken pipe")

                flush = write

        project = EngineProject(self)
        project.answer({"stdout": "", "stderr": "diagnostic\n", "exit": 0, "sleep": 30})
        procedures = project.procedures(
            [step("a", "standin-keep-alive", None,
                  on={"ok": "done", "failed": "needs-owner", "refused": "needs-owner",
                      "out-of-bounds": "step-failed"})],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "a"},
                   "step-failed": {"need": "retry", "reenter": "a"}})
        with (project.inside(), mock.patch.object(engine_commands, "PROJECT_WALL_SECONDS", 1),
              mock.patch.object(sys, "stderr", Closed)):
            code, line = engine_shell.deliver(1520, procedures)
        self.assertEqual((code, line["end"]), (3, "step-failed"))
        events = project.events(project.runs()[0])
        self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                         ["out-of-bounds"])

    def test_a_sigterm_to_the_engine_group_ends_a_running_command(self):
        project = EngineProject(self)
        procedures = self.sleeping(project, {"ok": "done", "failed": "needs-owner",
                                             "refused": "needs-owner",
                                             "out-of-bounds": "step-failed"})
        argv, options = project.command("deliver", "1520", "--procedures", str(procedures))
        engine = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True, **options)
        pids: list[int] = []

        def cleanup() -> None:
            for kill in (lambda: os.killpg(engine.pid, signal.SIGKILL),
                         lambda: [os.kill(pid, signal.SIGKILL) for pid in pids]):
                try:
                    kill()
                except ProcessLookupError:
                    pass
            engine.communicate()

        self.addCleanup(cleanup)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not pids:
            runs = project.runs()
            if runs:
                pids.extend(e["pid"] for e in project.events(runs[0])
                            if e["event"] == "process_started" and e["step"] == "a")
            time.sleep(0.05)
        self.assertTrue(pids, "the run never started its step process")
        os.killpg(engine.pid, signal.SIGTERM)
        engine.communicate(timeout=30)
        self.assert_gone(pids[0])


class FindingsTest(unittest.TestCase):
    def test_a_project_command_the_platform_declares_without_a_table_row_runs(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures([step("a", "release", "done")]))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_failure_to_take_the_run_lock_publishes_no_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        with project.inside(), \
                mock.patch.object(engine_shell, "_take_run_lock", side_effect=OSError("no lock")):
            with self.assertRaises(engine_shell.Refused):
                engine_shell.deliver(1512, procedures)
        self.assertEqual(project.runs(), [])
        self.assertFalse(project.record.exists())

    def test_a_new_runs_hierarchy_fsyncs_each_parent_of_a_new_directory(self):
        project = EngineProject(self)
        shutil.rmtree(project.world.home / ".agents", ignore_errors=True)
        synced: list[Path] = []
        real = engine_ledger._fsync_path

        def spy(path):
            synced.append(Path(path))
            real(path)

        with project.inside(), mock.patch.object(engine_ledger, "_fsync_path", side_effect=spy):
            os.close(engine_shell._lock_creation(1512))
        root = project.world.home / ".agents/state/engine/runs"
        for directory in (root, root.parent, root.parent.parent):
            self.assertIn(directory, synced)
            self.assertIn(directory.parent, synced)

    def test_a_deeply_nested_entry_is_a_refusal_not_a_traceback(self):
        project = EngineProject(self)
        directory = Path(tempfile.mkdtemp(dir=project.tmp))
        (directory / "deliver.json").write_text(
            '{"format":1,"inputs":["issue"],"stops":{},"steps":[{"id":"a","in":'
            + "[" * 100000 + "]" * 100000 + "}]}", encoding="utf-8")
        done = project.deliver(directory)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(project.runs(), [])

    def test_engine_check_accepts_the_project_command_ids_deliver_accepts(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        argv, options = project.command("check", "--procedures", str(procedures))
        inside = subprocess.run(argv, capture_output=True, timeout=120, **options)
        self.assertEqual(inside.returncode, 0, inside.stdout + inside.stderr)
        outside = Path(tempfile.mkdtemp(dir=project.tmp))
        argv, options = project.command("check", "--procedures", str(procedures), cwd=outside)
        elsewhere = subprocess.run(argv, capture_output=True, timeout=120, **options)
        self.assertEqual(elsewhere.returncode, 1, elsewhere.stdout + elsewhere.stderr)
        self.assertIn("unknown_command", elsewhere.stdout)

    def test_engine_check_refuses_each_lifecycle_spelling_that_does_not_map_refused(self):
        project = EngineProject(self)
        ids = list(LIFECYCLE_SPELLINGS)

        def steps(*, mapped: bool) -> list[dict]:
            return [{"id": name, "stage": "landing", "kind": "command", "command": name,
                     "holds": "run",
                     "on": {"ok": ids[i + 1] if i + 1 < len(ids) else "done",
                            "failed": "needs-owner",
                            **({"refused": "needs-owner"} if mapped else {})}}
                    for i, name in enumerate(ids)]

        def check(directory: Path):
            argv, options = project.command("check", "--procedures", str(directory))
            return subprocess.run(argv, capture_output=True, timeout=120, **options)

        unmapped = check(project.procedures(steps(mapped=False)))
        self.assertEqual(unmapped.returncode, 1, unmapped.stdout + unmapped.stderr)
        refusals = json.loads(unmapped.stdout)["refusals"]
        self.assertEqual([(r["defect"], r["step"]) for r in refusals],
                         [("unmapped_outcome", name) for name in ids])
        for refusal in refusals:
            self.assertIn("'refused'", refusal["detail"])
        mapped = check(project.procedures(steps(mapped=True)))
        self.assertEqual(mapped.returncode, 0, mapped.stdout + mapped.stderr)


def literal(name: str, on: dict, command: str | None = None) -> dict:
    """A command step with no `in`, so the judged text carries no issue number."""
    return {"id": name, "stage": "landing", "kind": "command", "command": command or name,
            "holds": "run", "on": on}


ALLOW_ON = {"ok": "done", "failed": "needs-owner", "refused": "needs-owner"}


class GuardDeliverTest(unittest.TestCase):
    def tee(self, project: EngineProject, name: str = "tee") -> Path:
        log = project.tmp / f"{name}.log"
        project.use_guard(standin_guard(
            project.tmp, name, "tee", str(log), str(real_guard(project.tmp / "guard-fixture"))))
        return log

    def test_a_merge_without_delete_branch_is_refused_by_the_real_guard_and_runs_nothing(self):
        on = {"ok": "done", "failed": "needs-owner", "refused": "guard-refused"}
        cases = {
            "land-bare": "gh pr merge 7 --repo example/engine --merge",
            "land-subject": 'gh pr merge 7 --repo example/engine --merge --subject "Land it"',
            "land-word": 'gh pr merge 7 --repo example/engine --merge --subject "Land"',
        }
        for command, text in cases.items():
            with self.subTest(command):
                project = EngineProject(self)
                project.guard_repository()
                project.record_tools()
                log = self.tee(project)
                stops = {"guard-refused": {"need": "owner-decision", "reenter": command},
                         "needs-owner": {"need": "owner-decision", "reenter": command}}
                stopped = project.deliver(project.procedures(
                    [literal(command, on)], stops=stops))
                self.assertEqual(stopped.returncode, 3, stopped.stdout + stopped.stderr)
                self.assertEqual(json.loads(stopped.stdout)["end"], "guard-refused")
                run = project.runs()[0]
                self.assertEqual(
                    [e["event"] for e in project.events(run)],
                    ["step_entered", "result_stored", "outcome_graded", "transition_taken",
                     "stop_reached"])
                graded = [e for e in project.events(run) if e["event"] == "outcome_graded"]
                self.assertEqual([e["outcome"] for e in graded], ["refused"])
                logged = payloads(log)
                self.assertEqual(len(logged), 1)
                judged = logged[0]["payload"]
                self.assertEqual(judged["tool_input"]["command"], text)
                direct = subprocess.run(
                    [str(project.tmp / "guard-fixture/bin" / GUARD_NAME)],
                    input=payload(judged["tool_input"]["command"], judged["cwd"]),
                    capture_output=True, cwd=judged["cwd"])
                reason = direct.stderr.decode("utf-8")
                self.assertTrue(reason.endswith("\n"))
                reason = reason[:-1]
                stored = json.loads((run / f"results/{command}.1.json").read_text())
                self.assertEqual(stored, {"reason": reason, "verdict": "refused"})
                self.assertIn("missing --delete-branch", reason)
                if command != "land-bare":
                    self.assertIn("missing --delete-branch: it may be omitted only in a "
                                  "repository with a declared integration branch", reason)
                tools = payloads(project.tmp / "tools.log")
                self.assertNotIn(["pr", "merge", "7", "--repo", "example/engine", "--merge"],
                                 [line["argv"] for line in tools])
                self.assertFalse([line for line in tools if "merge" in line["argv"]])

    def test_an_allowed_branch_delete_runs_the_text_the_real_guard_judged(self):
        project = EngineProject(self)
        project.git("branch", "issue-7-topic")
        project.record_tools()
        log = self.tee(project)
        done = project.deliver(project.procedures([literal("tidy-merged", ALLOW_ON)]))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        logged = payloads(log)
        self.assertEqual(len(logged), 1)
        judged = logged[0]["payload"]
        self.assertEqual(os.path.realpath(judged["cwd"]), os.path.realpath(project.root))
        self.assertEqual(judged, {"cwd": judged["cwd"], "hook_event_name": "PreToolUse",
                                  "tool_input": {"command": "git branch -d issue-7-topic"},
                                  "tool_name": "Bash"})
        self.assertEqual(payloads(project.tmp / "tools.log"),
                         [{"argv": ["branch", "-d", "issue-7-topic"]}])
        self.assertEqual(project.git("rev-parse", "--verify", "--quiet",
                                     "refs/heads/issue-7-topic", check=False).returncode, 1)

    def refused_once(self, project: EngineProject, reason_word: str) -> dict:
        done = project.deliver(project.procedures([literal("a", ALLOW_ON, "standin-record")]))
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        run = project.runs()[0]
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        stored = json.loads((run / "results/a.1.json").read_text())
        self.assertEqual(stored["verdict"], "refused")
        self.assertIn(reason_word, stored["reason"])
        self.assertFalse(project.record.exists())
        self.assertEqual([e for e in project.events(run) if e["event"] == "process_started"], [])
        return stored

    def test_settings_that_lose_the_guard_during_a_run_refuse_the_next_command(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-block", "b"),
                                         step("b", "standin-record", "done")])
        argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.communicate)
        self.addCleanup(process.kill)
        self.addCleanup(project.release.write_text, "go", encoding="utf-8")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            runs = project.runs()
            if runs and any(e["event"] == "process_started" and e["step"] == "a"
                            for e in project.events(runs[0])):
                break
            time.sleep(0.05)
        else:
            self.fail("the run never started its step process")
        run = runs[0]
        project.use_settings_text(json.dumps({"hooks": {"PreToolUse": []}}))
        project.release.write_text("go", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 3, stdout + stderr)
        self.assertEqual(json.loads(stdout)["end"], "needs-owner")
        stored = json.loads((run / "results/b.1.json").read_text())
        self.assertEqual(stored["verdict"], "refused")
        self.assertIn("no usable guard", stored["reason"])
        self.assertFalse(project.record.exists())
        started = [e["step"] for e in project.events(run) if e["event"] == "process_started"]
        self.assertEqual(started, ["a"])

    def test_a_guard_past_its_timeout_or_missing_is_refused_and_runs_nothing(self):
        with self.subTest("timeout"):
            project = EngineProject(self)
            pidfile = project.tmp / "pids"
            project.use_guard(standin_guard(project.tmp, "g", "sleep", str(pidfile)), timeout=1)
            started = time.monotonic()
            self.refused_once(project, "did not answer within")
            self.assertLess(time.monotonic() - started, 15)
            pids = [int(word) for word in pidfile.read_text().split()]
            self.assertEqual(len(pids), 2)
            deadline = time.monotonic() + 5
            for pid in pids:
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    self.fail(f"process {pid} outlived the guard timeout")
        with self.subTest("missing"):
            project = EngineProject(self)
            project.use_guard(project.tmp / "missing/bin/claude-bash-lifecycle-guard")
            self.refused_once(project, "missing")

    def test_a_settings_shape_with_no_usable_guard_refuses_before_any_run(self):
        missing = "missing/bin/claude-bash-lifecycle-guard"
        for name in ("arguments", "nul", "huge timeout", "other hook"):
            with self.subTest(name):
                project = EngineProject(self)
                other = project.tmp / "other.log"
                word = {"arguments": "arguments", "nul": "absolute path",
                        "huge timeout": "timeout", "other hook": "not the lifecycle guard"}[name]
                if name == "arguments":
                    project.use_guard(project.tmp / missing, args=["--x"])
                elif name == "nul":
                    project.use_guard("/g\u0000x/bin/claude-bash-lifecycle-guard")
                elif name == "huge timeout":
                    project.use_settings_text(json.dumps({"hooks": {"PreToolUse": [
                        {"matcher": "Bash", "hooks": [{
                            "type": "command", "command": "/g/bin/claude-bash-lifecycle-guard",
                            "timeout": "TIMEOUT"}]}]}}).replace('"TIMEOUT"', "1e400"))
                else:
                    project.use_guard(script(project.tmp / "other-hook", sys.executable,
                                             str(STANDIN_GUARD), "allow", str(other)))
                done = project.deliver(project.procedures(
                    [literal("a", ALLOW_ON, "standin-record")]))
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn(word, done.stderr)
                self.assertEqual(project.runs(), [])
                self.assertFalse(project.record.exists())
                if name == "other hook":
                    self.assertEqual(payloads(other), [])

    def test_each_lifecycle_verb_by_another_id_or_spelling_gets_the_guard_call(self):
        for name, argv in LIFECYCLE_SPELLINGS.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.record_tools()
                log = project.tmp / "g.log"
                project.use_guard(standin_guard(
                    project.tmp, "g", "refuse", str(log),
                    "lifecycle guard: refused by the stand-in."))
                done = project.deliver(project.procedures([literal(name, ALLOW_ON)]))
                self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
                logged = payloads(log)
                self.assertEqual(len(logged), 1)
                self.assertEqual(logged[0]["payload"]["tool_input"]["command"],
                                 command_text(argv))
                stored = json.loads((project.runs()[0] / f"results/{name}.1.json").read_text())
                self.assertEqual(stored, {"reason": "lifecycle guard: refused by the stand-in.",
                                          "verdict": "refused"})
                run_argv = argv[2:] if argv[0] == "/usr/bin/env" else argv[1:]
                self.assertNotIn(run_argv,
                                 [line["argv"] for line in payloads(project.tmp / "tools.log")])

    def test_a_wrapper_entry_that_pushes_is_judged_by_the_pre_push_hook_as_in_a_session(self):
        project = EngineProject(self)
        project.guard_repository()
        remote = project.tmp / "remote.git"
        subprocess.run([REAL_GIT, "init", "--bare", "--quiet", str(remote)], check=True)
        (project.tmp / "ship.sh").write_text(
            f"exec {REAL_GIT} -C {project.root} push {remote} HEAD:refs/heads/issue-7-topic\n",
            encoding="utf-8")
        hooks = real_pre_push_hooks(project.tmp / "pre-push-fixture")
        gitconfig = project.tmp / "gitconfig"
        gitconfig.write_text(f"[core]\n\thooksPath = {hooks}\n", encoding="utf-8")
        project.env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
        project.env.pop("CLAUDECODE", None)
        done = project.deliver(project.procedures([literal("ship-wrapper", ALLOW_ON)]))
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        logged = payloads(project.guard_log)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["payload"]["tool_input"]["command"],
                         command_text(["/bin/sh", str(project.tmp / "ship.sh")]))
        self.assertIn("lifecycle guard pre-push", done.stderr)
        self.assertEqual(subprocess.run(
            [REAL_GIT, "--git-dir", str(remote), "rev-parse", "--verify", "--quiet",
             "refs/heads/issue-7-topic"], capture_output=True).returncode, 1)

    def test_a_flag_shaped_release_title_keeps_the_spelling_the_real_guard_accepts(self):
        project = EngineProject(self)
        project.guard_repository()
        hook = Hook(str(real_guard(project.tmp / "guard-fixture")), 30)
        argv = ["gh", "release", "create", "v1.0.0", "--repo", "example/engine", "--verify-tag",
                "--title", "--body", "--notes-file", "/tmp/n.md"]
        good = judge(hook, command_text(argv), str(project.root))
        bad = judge(hook, 'gh release create v1.0.0 --repo example/engine --verify-tag '
                          '--title "--body" "--notes-file" /tmp/n.md', str(project.root))
        self.assertFalse(bad.allowed)
        self.assertTrue("does not match an accepted form" in bad.reason
                        or "exactly as the accepted form" in bad.reason, bad.reason)
        self.assertTrue(good.allowed, good.reason)


class RefusalTest(unittest.TestCase):
    def assertRefused(self, project: EngineProject, done, word: str) -> None:
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn(word, done.stderr)
        self.assertEqual(project.runs(), [])
        self.assertFalse(project.record.exists())

    def test_a_host_without_the_guard_hook_starts_no_command_run(self):
        project = EngineProject(self)
        project.use_settings_text(json.dumps({"hooks": {"PreToolUse": []}}))
        done = project.deliver(project.procedures([step("a", "standin-record", "done")]))
        self.assertRefused(project, done, "lifecycle guard")

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

        keep_alive = {"command": "standin-keep-alive", "in": ["run.issue"]}

        def no_claim_lost(project: EngineProject) -> Path:
            return project.procedures(
                [step("a", "standin-record", "done")], keep_alive=keep_alive,
                stops={"needs-owner": {"need": "owner-decision", "reenter": "a"}})

        def with_mutation(project: EngineProject) -> Path:
            first = step("a", "standin-record", "done", mutates=True)
            del first["check"]
            return project.procedures([first])

        def mutating_decide(project: EngineProject) -> Path:
            return project.procedures([{
                "id": "d", "stage": "setup", "kind": "decide", "grader": "toy-tally",
                "holds": "run", "mutates": True, "on": {"accept": "done", "revise": "needs-owner"}}],
                keep_alive=keep_alive)

        def empty(project: EngineProject) -> Path:
            return Path(tempfile.mkdtemp(dir=project.tmp))

        cases = {
            "an undeclared input": (
                "repo", lambda p: p.procedures([step("a", "standin-record", "done")],
                                               inputs=("issue", "repo"))),
            "a mutating step without a check": ("check", with_mutation),
            "a keep-alive with no claim-lost stop": ("missing_claim_lost", no_claim_lost),
            "a mutating decide step": ("marked mutates", mutating_decide),
            "a group step": ("group", shipped),
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
        return start_deliver(self, project, procedures)

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
        project.use_settings_text(json.dumps({"hooks": {"PreToolUse": []}}))
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

    def test_a_second_deliver_exits_already_running_though_the_source_procedure_is_gone(self):
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
        (procedures / "deliver.json").unlink()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 4, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], runs[0].name)
        project.release.write_text("go", encoding="utf-8")
        self.assertEqual(first.wait(60), 0)

    def test_the_procedure_that_runs_is_the_one_checked_when_the_source_changes_after_its_check(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        edited = json.loads((procedures / "deliver.json").read_text())
        edited["steps"][0]["on"]["ok"] = "b"
        edited["steps"].append(step("b", "no-such-command", "done"))
        edited_path = project.tmp / "edited.json"
        edited_path.write_text(json.dumps(edited), encoding="utf-8")
        _, options = project.command()
        process = subprocess.run(
            [sys.executable, "-c", LAUNCH, str(edited_path), "deliver", "1512",
             "--procedures", str(procedures)], capture_output=True, timeout=120, **options)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("unknown_command", process.stderr)
        self.assertFalse(project.record.exists())
        self.assertEqual(project.runs(), [])

    def test_a_continuer_waits_for_a_lock_renewal_and_reports_the_renewed_holder(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-fail", "done")])
        self.assertEqual(project.deliver(procedures).returncode, 3)
        run = project.runs()[0]
        root = project.world.home / ".agents/state/engine/runs"
        creation = os.open(creation_lock_path(root, 1512), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, creation)
        fcntl.flock(creation, fcntl.LOCK_EX)
        held = os.open(run / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX)
        os.ftruncate(held, 0)
        before = (run / "events.jsonl").read_bytes()
        runs_before = project.runs()
        process = self.start(project, procedures)
        time.sleep(1.0)
        self.assertIsNone(process.poll())
        self.assertEqual((run / "events.jsonl").read_bytes(), before)
        os.write(held, json.dumps({"pid": os.getpid(),
                                   "started": "2026-11-21T00:00:00Z"}).encode("utf-8"))
        fcntl.flock(creation, fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 4, stdout + stderr)
        line = json.loads(stdout)
        self.assertEqual(line["process"]["pid"], os.getpid())
        self.assertEqual(line["run"], run.name)
        self.assertEqual((run / "events.jsonl").read_bytes(), before)
        self.assertEqual(project.runs(), runs_before)

    def test_status_reports_the_later_run_of_a_second_not_the_one_with_the_greater_token(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        later = self.seed_runs(project, procedures, done="zzzz", other="aaaa")
        status = project.status(1512)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["run"], later.name)

    def test_a_stopped_run_is_continued_not_joined_by_a_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-fail", "done")])
        self.assertEqual(project.deliver(procedures).returncode, 3)
        again = project.deliver(procedures)
        self.assertEqual(again.returncode, 3, again.stdout + again.stderr)
        self.assertEqual(len(project.runs()), 1)
        events = project.events(project.runs()[0])
        self.assertEqual([(e["step"], e["visit"]) for e in run_continued(events)], [("a", 1)])
        self.assertEqual([e["visit"] for e in events
                          if e["event"] == "step_entered" and e["step"] == "a"], [1, 2])

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

    def test_a_done_run_never_hides_an_open_run_started_in_the_same_second(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-json", "done")])
        open_run = self.seed_runs(project, procedures, done="zzzz", other="aaaa")
        runs_before = project.runs()
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], open_run.name)
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
