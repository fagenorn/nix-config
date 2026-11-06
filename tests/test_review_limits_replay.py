"""Projected review limits on an issue-121-shaped delivery (issue 227), now advisory in sdd-gate (Stage 2c)."""
import json
import unittest

import tests.test_sdd_gate as sdd_cases

CHILDREN = (("first", [1, 2, 3], []), ("middle", [4, 5, 6], ["first"]), ("last", [7, 8], ["middle"]))


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
    def next(self, *args):
        return self.gate("next", self.plan, "--skill-dir", sdd_cases.SKILL, *args)

    # -- the replay ----------------------------------------------------------
    def test_an_oversized_forecast_no_longer_stops_sdd_entry(self):
        self.root_subjects = [120] * 100
        head = self.write_plan()
        # Stage 2c: sdd-gate no longer projects, so the forecast no longer stops execution.
        self.ready(self.next("--task", 1, "--delivery-base", self.base))
        self.assertIn(f"Task 1: dispatched (base {head})", self.ledger.read_text(encoding="utf-8"))

    def test_an_actual_overflow_is_never_hidden_by_a_fitting_forecast(self):
        self.sizes = {n: 1024 for n in range(1, 9)}
        self.write_plan()
        self.ready(self.next("--task", 1, "--delivery-base", self.base))
        self.write("src/t1.py", "".join(f"value_{n} = {n}\n" for n in range(8000)))
        head = self.repo_commit("task 1")
        out = self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(out["delivery"]["state"], "decompose_required")
        gate = [line for line in self.ledger.read_text(encoding="utf-8").splitlines()
                if line.startswith(f"Delivery gate: {self.base}..{head} ")]
        self.assertEqual(len(gate), 1)
        self.assertTrue(gate[0].endswith(" over_budget"))
