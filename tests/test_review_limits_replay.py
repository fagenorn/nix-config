"""Projected review limits, end to end, on an issue-121-shaped delivery (issue 227 AC1, AC4, AC6, AC8)."""
import json
import subprocess
import sys
import unittest

import tests.test_sdd_gate as sdd_cases

CHILDREN = (("first", [1, 2, 3], []), ("middle", [4, 5, 6], ["first"]), ("last", [7, 8], ["middle"]))
FEASIBILITY = [sys.executable, "-m", "agent_tools.review_feasibility"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ReplayTest(sdd_cases.GateCase):
    def setUp(self):
        super().setUp()
        self.base = self.delivery_base = self.repo_git("rev-parse", "HEAD")
        self.sizes = {n: (60000 if n >= 4 else 2048) for n in range(1, 9)}
        self.root_subjects = [64] * 4

    # -- the forecast -------------------------------------------------------
    def package(self, stem, count):
        return {"spec": f"{stem}-spec.md", "plan": f"{stem}.md",
                "tasks": [f"{stem}.tasks/task-{i}.md" for i in range(1, count + 1)]}

    def bound(self, boundary, size, rid):
        return {"boundary": boundary, "added_lines": 20, "deleted_lines": 0, "record_bytes": size,
                "support": {"kind": "authored-cumulative/v1", "covers": [rid]}}

    def boundaries(self, count, children):
        rows = [{"id": "all", "parent": None, "tasks": list(range(1, count + 1)), "acceptance": "Whole delivery",
                 "depends_on": [], "prerequisite": {"kind": "delivery-base"},
                 "process_package": self.package("plan", count),
                 "process_forecast_ids": [f"all-p{i}" for i in range(count + 2)],
                 "process_commit_subject_bytes": self.root_subjects}]
        closure = []
        for key, tasks, deps in children:
            rows.append({"id": key, "parent": "all", "tasks": tasks, "acceptance": f"Deliver {key}",
                         "depends_on": deps, "prerequisite": {"kind": "delivery-base"} if not deps else
                         {"kind": "completed-tasks", "tasks": list(closure), "commit": None, "tree": None},
                         "process_package": self.package(f"child-{key}", len(tasks)),
                         "process_forecast_ids": [f"{key}-p{i}" for i in range(len(tasks) + 2)],
                         "process_commit_subject_bytes": [64]})
            closure += tasks
        return rows

    def write_plan(self, count=8, children=CHILDREN, cite="", recovered=None):
        """Commit the plan package; `recovered` is task 1's already-landed (base, head) range."""
        rows = self.boundaries(count, children)
        process = []
        for row in rows:
            package = row["process_package"]
            for rid, path in zip(row["process_forecast_ids"], [package["spec"], package["plan"], *package["tasks"]]):
                change = "modify" if (self.repo / path).exists() and path.startswith("plan") else "add"
                process.append({"id": rid, "owner": 0, "path": path, "change": change, "last_task": count,
                                "bounds": [self.bound(row["id"], 4096, rid)]})
        delivery = {"schema_version": 3, "kind": "review-feasibility-delivery", "delivery_base": self.base,
                    "proposed_boundary": "all", "boundaries": rows, "process_records": process,
                    "derived_from": None, "actual_evidence": {"kind": "git-range-ownership/v1",
                    "head": recovered[1] if recovered else self.base,
                    "tree": self.repo_git("rev-parse", (recovered[1] if recovered else self.base) + "^{tree}"),
                    "process_ranges": []}}
        index = "\n".join(f"Task {n} — Step {n} — `src/t{n}.py` — full — [task-{n}.md](plan.tasks/task-{n}.md)"
                          for n in range(1, count + 1))
        head = (sdd_cases.FIXTURES / "plan.md").read_text(encoding="utf-8").split("## Task index")[0]
        self.write("plan-spec.md", "# Replay spec\n")
        self.write("plan.md", head + "## Task index\n\n" + index + "\n" + cite
                   + "\n## Review feasibility delivery\n\n```json\n" + canonical(delivery) + "\n```\n")
        for n in range(1, count + 1):
            owners = ["all", *(key for key, tasks, _ in children if n in tasks)]
            record = {"id": f"r{n}", "owner": n, "path": f"src/t{n}.py", "change": "add", "last_task": n,
                      "bounds": [self.bound(key, self.sizes[n], f"r{n}") for key in owners]}
            ranges = [{"base": recovered[0], "head": recovered[1]}] if recovered and n == 1 else []
            block = {"schema_version": 3, "kind": "review-feasibility-task", "task": {"id": n,
                     "commit_subject_bytes": [64, 64], "actual_ranges": ranges, "records": [record]}}
            self.write(f"plan.tasks/task-{n}.md", f"# Task {n}: Step {n}\n\n## Review feasibility task\n\n```json\n"
                       + canonical(block) + "\n```\n")
        return self.repo_commit("plan: issue-121-shaped forecast")

    # -- helpers -------------------------------------------------------------
    def feasibility(self, *args, raw=None):
        return subprocess.run([*FEASIBILITY, *map(str, args)], input=raw, cwd=self.repo, env=self.env,
                              capture_output=True)

    def next(self, *args):
        return self.gate("next", self.plan, "--skill-dir", sdd_cases.SKILL, *args)

    def snapshot(self):
        """HEAD, branches, ledger bytes and every workspace file's bytes, saved results included."""
        return (self.repo_git("rev-parse", "HEAD"), self.repo_git("branch", "--list"), self.ledger.read_bytes(),
                {p.name: p.read_bytes() for p in sorted(self.workspace.iterdir()) if p.is_file()})

    def grow_task_one(self):
        """Task 1 lands 200 KB over four files, each under the member limit; record and commit it."""
        for part in range(4):
            self.write(f"src/t1{'' if part == 0 else part}.py", "".join(f"v{part}_{n} = {n}\n" for n in range(4000)))
        task_head = self.repo_commit("task 1")
        self.assertEqual(self.ready(self.gate("record", self.plan, "--task", 1))["head_sha"], task_head)
        return task_head, self.repo_commit("plan: record task 1 evidence")

    # -- the replay ----------------------------------------------------------
    def test_an_oversized_plan_is_refused_at_planning_and_at_sdd_entry(self):
        self.root_subjects = [120] * 100
        head = self.write_plan()
        gated = self.feasibility("gate", "--plan", self.plan, "--base", self.base, "--head", head,
                                 "--completed-through", 0)
        self.assertEqual(gated.returncode, 3, gated.stderr)
        summary = json.loads(gated.stdout)
        self.assertEqual((summary["recommended_boundary"]["id"], summary["recommended_boundary"]["tasks"]),
                         ("first", [1, 2, 3]))
        refused = self.next("--task", 1, "--delivery-base", self.base)
        self.assertEqual(refused.returncode, 3, refused.stdout)
        self.assertEqual(json.loads(refused.stdout)["report"], summary)
        self.assertNotIn("Task 1: dispatched", self.ledger.read_text(encoding="utf-8"))

    def test_a_growing_plan_stops_before_task_2_and_only_a_fresh_child_continues(self):
        self.launch()
        self.write_plan()
        self.ready(self.next("--task", 1, "--delivery-base", self.base, *self.identity()))
        workers = json.loads(self.state_path.read_text(encoding="utf-8"))["workers"]
        task_head, recording = self.grow_task_one()
        refused = self.next("--completed", 1, "--task", 2, *self.identity())
        self.assertEqual(refused.returncode, 3, refused.stdout)
        stop = json.loads(refused.stdout)
        self.assertEqual((stop["step"], stop["gate"]), ("projection", "decompose_required"))
        summary = stop["report"]
        self.assertEqual((summary["head"], summary["completed_through"]), (recording, 1))
        self.assertEqual(summary["recommended_boundary"]["id"], "first")
        self.assertNotIn("Task 2: dispatched", self.ledger.read_text(encoding="utf-8"))
        self.assertFalse((self.workspace / "task-2-implementer-dispatch.md").exists())
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8"))["workers"], workers)
        before = self.snapshot()
        self.assertIn(f"projection-{recording[:7]}-1.json", before[3])                 # the saved result
        confirmed = self.feasibility("confirm", "--plan", self.plan, "--base", self.base, "--input", "-",
                                     raw=canonical(summary).encode() + b"\n")
        self.assertEqual((confirmed.returncode, json.loads(confirmed.stdout)), (3, summary), confirmed.stderr)
        # A fresh child: its own branch and base at the recommendation's prerequisite, recovered commits,
        # a new process package that cites the parent summary, and an empty ledger.
        child_root = self.root / "child"
        prerequisite = summary["recommended_boundary"]["prerequisite_commit"]
        self.repo_git("worktree", "add", "-q", "-b", "child-first", str(child_root), prerequisite)
        parent = (self.repo, self.plan, self.base, self.sizes)
        self.repo, self.plan, self.base = child_root, child_root / "plan.md", prerequisite
        self.repo_git("cherry-pick", task_head)
        recovered = (prerequisite, self.repo_git("rev-parse", "HEAD"))
        self.sizes = {n: 2048 for n in range(1, 4)}
        self.root_subjects = [64] * 4
        child_head = self.write_plan(3, (), f"\nParent stop: {summary['forecast_sha256']} at {summary['head']}\n",
                                     recovered)
        self.assertIn(summary["forecast_sha256"], self.plan.read_text(encoding="utf-8"))
        child_gate = self.feasibility("gate", "--plan", self.plan, "--base", prerequisite, "--head", child_head,
                                      "--completed-through", 1)
        self.assertEqual((child_gate.returncode, json.loads(child_gate.stdout)["state"]), (0, "complete"),
                         child_gate.stderr)
        workspace = self.run_tool("sdd-workspace", str(self.plan)).strip()
        self.assertNotEqual(workspace, str(self.workspace))
        self.assertFalse((sdd_cases.Path(workspace) / "progress.md").exists())
        self.repo, self.plan, self.base, self.sizes = parent
        # The parent is untouched and its summary still confirms.
        self.assertEqual(self.snapshot()[0], before[0])
        self.assertEqual(self.snapshot()[2:], before[2:])
        again = self.feasibility("confirm", "--plan", self.plan, "--base", self.base, "--input", "-",
                                 raw=canonical(summary).encode() + b"\n")
        self.assertEqual((again.returncode, again.stdout), (3, confirmed.stdout), again.stderr)

    def test_an_actual_overflow_is_never_hidden_by_a_fitting_projection(self):
        self.sizes = {n: 1024 for n in range(1, 9)}
        self.write_plan()
        self.ready(self.next("--task", 1, "--delivery-base", self.base))
        self.write("src/t1.py", "".join(f"value_{n} = {n}\n" for n in range(8000)))
        self.repo_commit("task 1")
        self.ready(self.gate("record", self.plan, "--task", 1)); self.repo_commit("plan: record task 1 evidence")
        refused = json.loads(self.next("--completed", 1, "--task", 2).stdout)
        self.assertEqual((refused["step"], refused["gate"]), ("validate-report", "decompose_required"))
        self.assertNotIn("through 1", self.ledger.read_text(encoding="utf-8"))
