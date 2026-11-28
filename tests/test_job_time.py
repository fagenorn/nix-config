"""The job-time command of `agent_tools.delivery.job_time`.

Measures the median against the budget, the one marked issue, the trusted filer, the exact
issue text, the run and job listings of `file`, the merge-run boundary and the skipped red
runs of `observed`, the argument refusals and the committed wrapper run end to end against a
fake `gh`, over a stub tracker and a stub forge.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import job_time
from agent_tools.delivery.cleanup_issue import Issue, Refusal
from agent_tools.delivery.job_time import MARKER, GitHubJobTime, Reading, draft, run
from tests.test_branch_protection import (
    CLEANUP_WORKFLOW,
    WORKFLOW,
    WORKFLOWS,
    _top_level_block,
    green_without_work,
    job_blocks,
    job_if_expression,
    job_names,
    job_permission_lines,
    required_contexts,
    required_jobs,
    step_blocks,
    step_env,
    workflow_permissions,
)

TIER = "integration"  # this module reads the git index and runs a wrapper

REPO_ROOT = Path(__file__).resolve().parents[1]
JOB_TIME_WORKFLOW = WORKFLOWS / "job-time.yaml"
WRAPPER = "home/common/verify-pending/checks/dotnet-job-wall"
MERGE = "a" * 40
LISTING = "repos/o/r/actions/workflows/ci.yaml/runs?branch=main&event=push"
JOBS = "repos/o/r/actions/runs/{}/jobs?filter=latest&per_page=100"
START = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
NET = ".NET Solution"


class StubTracker:
    def __init__(self, issues=(), trusted=True):
        self.issues = list(issues)
        self.trusted = trusted
        self.created = []

    def open_issues(self):
        return self.issues

    def trusted_writer(self):
        return self.trusted

    def create(self, title, body):
        self.created.append((title, body))
        return 101


def issue(number, body):
    return Issue(number, body)


class RunTest(unittest.TestCase):
    def test_ten_green_runs_at_the_budget_file_one_issue_naming_the_job(self):
        tracker = StubTracker()

        outcome = run(tracker, [240_000] * 10, "main")

        self.assertEqual((outcome.action, outcome.issue), ("filed", 101))
        self.assertEqual(len(tracker.created), 1)
        self.assertIn(NET, tracker.created[0][0])
        self.assertIn("240.0 s", tracker.created[0][0])

    def test_a_median_under_the_budget_files_nothing(self):
        tracker = StubTracker()

        outcome = run(tracker, [239_999] * 10, "main")

        self.assertEqual(outcome.action, "within")
        self.assertEqual(tracker.created, [])

    def test_nine_green_runs_file_nothing(self):
        tracker = StubTracker()

        outcome = run(tracker, [300_000] * 9, "main")

        self.assertEqual((outcome.action, outcome.reading.runs), ("too_few", 9))
        self.assertEqual(tracker.created, [])

    def test_an_open_job_time_issue_files_nothing(self):
        tracker = StubTracker([
            issue(7, f"intro\n{MARKER}  \n"), issue(5, f"{MARKER}\r\nmore"),
            issue(3, f"see {MARKER} in a sentence")])

        outcome = run(tracker, [300_000] * 10, "main")

        self.assertEqual((outcome.action, outcome.issue), ("open", 5))
        self.assertEqual(tracker.created, [])

    def test_a_filer_that_would_not_be_trusted_files_nothing(self):
        tracker = StubTracker(trusted=False)

        with self.assertRaises(Refusal):
            run(tracker, [300_000] * 10, "main")

        self.assertEqual(tracker.created, [])

    def test_the_issue_text_is_exact(self):
        title, body = draft(Reading(10, 250_000), "main")

        self.assertEqual(
            title,
            "Job time: the .NET Solution job's median wall time over the last 10 green runs is "
            "250.0 s, not under the 240 s budget")
        self.assertEqual(
            body,
            "<!-- agent:job-time v1 -->\n"
            "The median wall time of the .NET Solution job over the last 10 green push runs of "
            "ci.yaml on main is 250.0 s, not under the 240 s budget.\n\n"
            "## What to change\n\n"
            "Make the .NET Solution job faster (its Nix store cache, its build or its tests) "
            "until the median of its last 10 green runs is under 240 s. A slow run never fails "
            "a change; this issue is the only signal.\n\n"
            "## Acceptance criteria\n\n"
            "- [ ] [evidence] The median wall time of the .NET Solution job over the last 10 "
            "green push runs on main is under 240 s — measured: the Job Time job log on "
            'main prints "action": "within"\n')


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run(run_id, conclusion="success", status="completed"):
    return {"id": run_id, "head_sha": MERGE if run_id == 100 else f"{run_id:040x}",
            "created_at": stamp(START + timedelta(minutes=run_id - 100)),
            "status": status, "conclusion": conclusion}


def make_job(wall, name=NET, status="completed", conclusion="success", run_id=100):
    begun = START + timedelta(minutes=run_id - 100)
    return {"name": name, "status": status, "conclusion": conclusion,
            "started_at": stamp(begun), "completed_at": stamp(begun + timedelta(seconds=wall))}


class SamplesTest(unittest.TestCase):
    def test_only_green_jobs_of_green_runs_count_and_reading_stops_at_ten(self):
        runs = {
            214: ("success", make_job(100, conclusion="failure", run_id=214)),
            213: ("success", None),
            212: ("success", make_job(100, status="in_progress", conclusion=None, run_id=212)),
            211: ("failure", make_job(100, run_id=211)),
        }
        for run_id in range(200, 211):
            runs[run_id] = ("success", make_job(run_id, run_id=run_id))
        listing = {"workflow_runs": [make_run(run_id, conclusion)
                                     for run_id, (conclusion, _) in runs.items()]}
        read = []

        def api_get(path):
            read.append(path)
            if path.startswith("repos/o/r/actions/workflows/"):
                return listing
            run_id = int(path.split("/runs/")[1].split("/")[0])
            job = runs[run_id][1]
            return {"jobs": [make_job(1, name="Nix Eval")] + ([job] if job else [])}

        with mock.patch.object(job_time.forge_api, "api_get", side_effect=api_get):
            found = GitHubJobTime("o/r", "main").samples()

        self.assertEqual(found, [run_id * 1000 for run_id in range(210, 200, -1)])
        self.assertEqual(read[0], f"{LISTING}&status=completed&per_page=50")
        self.assertNotIn(JOBS.format(211), read)
        self.assertTrue(all(path.endswith("jobs?filter=latest&per_page=100") for path in read[1:]))

    def test_a_listing_without_runs_is_a_payload_error(self):
        with mock.patch.object(job_time.forge_api, "api_get", return_value={"workflow_runs": 3}), \
                self.assertRaises(job_time.forge_api.ForgeError):
            GitHubJobTime("o/r", "main").samples()


class World:
    """A forge for `observed`: the merge run 100 and runs after it, each with a `.NET Solution` job."""

    def __init__(self, walls, conclusions=None, jobs=None, merge=True):
        self.walls = walls
        self.conclusions = conclusions or {}
        self.jobs = jobs or {}
        self.merge = merge

    def runs(self):
        return [make_run(run_id, self.conclusions.get(run_id, "success"))
                for run_id in sorted(self.walls)]

    def gets(self):
        gets = {f"{LISTING}&head_sha={MERGE}&per_page=100":
                {"workflow_runs": [make_run(100)] if self.merge else []}}
        for run_id, wall in self.walls.items():
            gets[JOBS.format(run_id)] = {"jobs": [
                make_job(1, name="Nix Eval", run_id=run_id),
                self.jobs.get(run_id) or make_job(wall, run_id=run_id)]}
        return gets

    def pages(self):
        runs = list(reversed(self.runs()))
        return {f"{LISTING}&created=>={stamp(START)}&per_page=100": [{"workflow_runs": runs}]}


def call(argv, gets=None, pages=None):
    """(exit code, parsed stdout or None, stderr, paths read) of `job_time.main(argv)` over a stub forge."""
    read = []

    def api_get(path):
        read.append(path)
        return gets[path]

    def api_pages(path):
        read.append(path)
        return pages[path]
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(job_time.forge_api, "api_get", side_effect=api_get), \
            mock.patch.object(job_time.forge_api, "api_pages", side_effect=api_pages), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = job_time.main(argv)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue(), read


def observed(world, runs="10"):
    argv = ["observed", "--repo", "o/r", "--branch", "main", "--merge", MERGE, "--runs", runs]
    return call(argv, world.gets(), world.pages())


class ObservedTest(unittest.TestCase):
    def test_observed_counts_only_green_runs_after_the_merge(self):
        nine = World({run_id: 200 for run_id in range(100, 110)})
        code, line, _, _ = observed(nine)
        self.assertEqual((code, line["state"]), (75, "not_yet"))

        ten = World({run_id: 200 for run_id in range(100, 111)})
        code, line, _, _ = observed(ten)
        self.assertEqual((code, line["state"]), (0, "met"))
        self.assertEqual([row["run"] for row in line["runs"]], list(range(101, 111)))
        self.assertEqual(line["budget_seconds"], 240.0)
        self.assertEqual(line["job"], NET)

        gets = nine.gets()
        gets[f"{LISTING}&head_sha={MERGE}&per_page=100"] = {"workflow_runs": []}
        self.assertEqual(call(["observed", "--repo", "o/r", "--branch", "main", "--merge", MERGE,
                               "--runs", "10"], gets, nine.pages())[0], 75)

    def test_observed_skips_red_runs_and_judges_the_median_against_the_budget(self):
        def world(walls):
            return World(
                {100: 1, 101: walls[0], 102: 200, 103: 200, 104: walls[1], 105: walls[2],
                 106: walls[3]},
                conclusions={103: "failure"},
                jobs={102: make_job(200, conclusion="failure", run_id=102)})

        code, line, _, read = observed(world([200, 230, 239, 250]), "4")
        self.assertEqual((code, line["state"], line["median_seconds"]), (0, "met", 234.5))
        self.assertEqual([row["run"] for row in line["runs"]], [101, 104, 105, 106])
        self.assertNotIn(JOBS.format(103), read)

        code, line, _, _ = observed(world([240, 240, 240, 240]), "4")
        self.assertEqual((code, line["state"]), (1, "not_met"))


class UnreadableInputTest(unittest.TestCase):
    """A payload the reader cannot trust is exit 2, never a dropped run or a KeyError."""

    def bad_jobs(self, run_id=101):
        late = make_job(200, run_id=run_id)
        yield "unreadable completed_at", dict(late, completed_at="not a time")
        yield "missing started_at", {k: v for k, v in late.items() if k != "started_at"}
        yield "reversed timestamps", dict(late, started_at=late["completed_at"],
                                          completed_at=late["started_at"])

    def test_a_green_job_with_unreadable_times_is_exit_2_not_a_dropped_run(self):
        for label, job in self.bad_jobs():
            with self.subTest(label=label):
                world = World({run_id: 300 if run_id == 101 else 200 for run_id in range(100, 112)},
                              jobs={101: job})
                code, line, err, _ = observed(world)
                self.assertEqual((code, line), (2, None))
                self.assertTrue(err.startswith("job-time: "), err)

    def test_file_reads_a_green_job_with_unreadable_times_as_exit_2(self):
        for label, job in self.bad_jobs(111):
            with self.subTest(label=label):
                runs = [make_run(run_id) for run_id in range(101, 112)]
                gets = {f"{LISTING}&status=completed&per_page=50": {"workflow_runs": runs}}
                for run_id in range(101, 112):
                    gets[JOBS.format(run_id)] = {"jobs": [job if run_id == 111 else
                                                          make_job(200, run_id=run_id)]}
                code, line, err, _ = call(["file", "--repo", "o/r", "--branch", "main"], gets)
                self.assertEqual((code, line), (2, None))
                self.assertTrue(err.startswith("job-time: "), err)

    def test_a_run_without_a_conclusion_key_is_exit_2_but_a_null_conclusion_is_read(self):
        runs = [make_run(run_id) for run_id in range(101, 112)]
        del runs[0]["conclusion"]
        gets = {f"{LISTING}&status=completed&per_page=50": {"workflow_runs": runs}}
        code, line, err, _ = call(["file", "--repo", "o/r", "--branch", "main"], gets)
        self.assertEqual((code, line), (2, None))
        self.assertTrue(err.startswith("job-time: "), err)

        world = World({run_id: 200 for run_id in range(100, 112)})
        world_runs = world.runs()
        del world_runs[5]["conclusion"]
        pages = {f"{LISTING}&created=>={stamp(START)}&per_page=100": [{"workflow_runs": world_runs}]}
        code, line, err, _ = call(
            ["observed", "--repo", "o/r", "--branch", "main", "--merge", MERGE, "--runs", "10"],
            world.gets(), pages)
        self.assertEqual((code, line), (2, None))
        self.assertTrue(err.startswith("job-time: "), err)

        pending = [make_run(run_id, conclusion=None, status="in_progress") for run_id in range(101, 103)]
        gets = {f"{LISTING}&status=completed&per_page=50": {"workflow_runs": pending}}
        code, line, _, _ = call(["file", "--repo", "o/r", "--branch", "main"], gets)
        self.assertEqual((code, line["action"]), (0, "too_few"))


class ArgumentTest(unittest.TestCase):
    def test_bad_arguments_exit_2_with_nothing_on_stdout(self):
        base = ["observed", "--repo", "o/r", "--branch", "main", "--merge", MERGE, "--runs", "10"]
        for flag, value in (("--repo", "bad"), ("--merge", "xyz"), ("--runs", "0")):
            argv = list(base)
            argv[argv.index(flag) + 1] = value
            with self.subTest(flag=flag):
                code, out, err, _ = call(argv)
                self.assertEqual((code, out), (2, None))
                self.assertTrue(err.startswith("job-time: "), err)

        code, out, err, _ = call(["file", "--repo", "bad", "--branch", "main"])
        self.assertEqual((code, out), (2, None))
        self.assertTrue(err.startswith("job-time: "), err)


FAKE_GH = """#!{python}
import json, os, sys

answers = json.load(open(os.environ["JOB_TIME_FAKE_GH"]))
path = sys.argv[-1]
if path not in answers:
    sys.exit(1)
print(json.dumps(answers[path]))
"""


class WrapperTest(unittest.TestCase):
    def test_the_check_is_committed_executable_with_no_command_row(self):
        staged = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", WRAPPER],
            capture_output=True, text=True, check=True).stdout
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()

        self.assertTrue(staged.startswith("100755"), staged)
        self.assertNotIn('"job-time"', table)

    def test_the_check_runs_observed_against_the_forge(self):
        world = World({run_id: 200 for run_id in range(100, 104)})
        answers = {**world.gets(), **{path: pages for path, pages in world.pages().items()}}
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            gh = tmp / "gh"
            gh.write_text(FAKE_GH.format(python=sys.executable))
            gh.chmod(0o755)
            known = tmp / "answers.json"
            known.write_text(json.dumps(answers))

            done = subprocess.run(
                [str(REPO_ROOT / WRAPPER), "--repo", "o/r", "--branch", "main", "--merge", MERGE,
                 "--runs", "10"],
                cwd=REPO_ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}",
                     "JOB_TIME_FAKE_GH": str(known)})

        self.assertEqual(done.returncode, 75, done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual((line["state"], line["job"], line["budget_seconds"]),
                         ("not_yet", NET, 240.0))
        self.assertEqual([row["run"] for row in line["runs"]], [101, 102, 103])


class JobTimeWorkflowTest(unittest.TestCase):
    """The job that files the job-time issue when a push run of CI on main completes."""

    def test_runs_when_a_push_run_of_ci_on_main_completes_with_issue_write_and_no_other_write(self):
        self.assertEqual(
            ["  workflow_run:", "    workflows:", "      - CI", "    types:", "      - completed",
             "    branches:", "      - main"],
            [line for line in _top_level_block("on", JOB_TIME_WORKFLOW) if line.strip()],
        )
        # `workflows:` names the workflow by its `name:`.
        self.assertIn("name: CI", WORKFLOW.read_text(encoding="utf-8").splitlines())
        self.assertEqual(
            "github.event.workflow_run.event == 'push'",
            job_if_expression("job-time", JOB_TIME_WORKFLOW),
        )
        self.assertEqual(
            {"actions": "read", "contents": "read", "issues": "write"},
            workflow_permissions(JOB_TIME_WORKFLOW),
        )
        overrides = {
            key: job_permission_lines(block)
            for key, block in job_blocks(JOB_TIME_WORKFLOW).items()
            if job_permission_lines(block)
        }
        self.assertEqual({}, overrides)

    def test_readings_run_one_after_another(self):
        self.assertEqual(
            ["  group: job-time", "  cancel-in-progress: false", "  queue: max"],
            [line for line in _top_level_block("concurrency", JOB_TIME_WORKFLOW) if line.strip()],
        )

    def test_the_job_stores_the_token_then_reads_the_job_time_through_the_command(self):
        self.assertEqual({"Job Time": "job-time"}, job_names(JOB_TIME_WORKFLOW))
        steps = step_blocks("job-time", JOB_TIME_WORKFLOW)
        self.assertEqual(
            ["Checkout", "Store the workflow token for gh", "Read the job time"], list(steps)
        )
        cleanup_token = step_blocks("cleanup-issue", CLEANUP_WORKFLOW)[
            "Store the workflow token for gh"
        ]
        self.assertEqual(
            [line for line in cleanup_token if line.strip()],
            [line for line in steps["Store the workflow token for gh"] if line.strip()],
        )
        read_step = steps["Read the job time"]
        self.assertEqual(
            [
                "      - name: Read the job time",
                "        run: PYTHONPATH=python python3 -m agent_tools.delivery.job_time file"
                " --repo \"$GITHUB_REPOSITORY\" --branch \"$GITHUB_REF_NAME\"",
            ],
            [line for line in read_step if line.strip()],
        )
        # No `env:` on the command step: no token reaches the command.
        self.assertIsNone(step_env(read_step))
        text = JOB_TIME_WORKFLOW.read_text(encoding="utf-8")
        for key in ("defaults:", "shell:", "working-directory:", "continue-on-error:"):
            self.assertNotIn(key, text)
        self.assertEqual(
            ["    name: Job Time", "    if: github.event.workflow_run.event == 'push'",
             "    runs-on: ubuntu-24.04", "    timeout-minutes: 10", "    steps:"],
            [line for line in job_blocks(JOB_TIME_WORKFLOW)["job-time"]
             if line.startswith("    ") and not line.startswith("     ")],
        )
        self.assertEqual([], green_without_work(job_blocks(JOB_TIME_WORKFLOW)["job-time"], None))

    def test_the_job_is_not_a_required_context(self):
        self.assertNotIn("Job Time", required_contexts())
        self.assertEqual(JOB_TIME_WORKFLOW, required_jobs()["Job Time"][0])


if __name__ == "__main__":
    unittest.main()
