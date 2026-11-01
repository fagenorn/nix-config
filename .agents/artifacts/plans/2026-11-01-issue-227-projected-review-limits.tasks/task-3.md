# Task 3: Ownership recording and the `sdd-gate next` projection steps

**Files:**
- Create: `python/agent_tools/review_record.py`
- Modify: `python/agent_tools/sdd_gate.py`
- Modify: `tests/test_sdd_gate.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes: `agent_tools.review_forecast.{_block, canonical_bytes, ForecastError, ancestor, history_commit}` (the accepted loader's block reader and Git helpers); `sdd_gate.{open_ledger, recorded_sha, task_base, append_line, write_atomic, Refusal, _refusal_object, _print}`.
- Produces:
  - `agent_tools.review_record.RecordError(Exception)`.
  - `agent_tools.review_record.recorded(repo: Path, plan: Path, task: int, base: str, head: str) -> tuple[bytes, bytes]`: the new root and task-`task` member bytes, computed from the bytes committed at `head`.
  - `sdd-gate record PLAN_FILE --task N` printing `{"command":"record","outcome":"ready","task":N,"head_sha":H,"paths":[<absolute root>,<absolute member>],"changed":bool}` (exit 0), or the existing refusal object with `gate: null` (exit 2). Steps, in order: `ledger`, `worktree`, `record`.
  - Ledger line `Task N: recorded (head <H40>)`, appended once.
  - In `tests/test_sdd_gate.py`: `class ForecastCase(GateCase)`, whose `setUp` makes the fixture plan carry a valid v3 forecast (D15) and exposes `self.forecast_base` (also assigned to `self.delivery_base`, so `NextTest.first()` passes it), `self.emit_forecast()`, `self.read_blocks()` and `self.record(task)`; the `next` tests below build on it.
- Consumes: Task 1's `agent_tools.review_gate.{capture, project_argv, summarize, plan_relative, GateError}`; `review_record.recorded`, the `Task N: recorded (head H)` line and `ForecastCase` from the recording half.
- Produces (callers in Tasks 4 and 5 rely on these exact names):
  - `next` steps, in order: `ledger`, `ledger-complete`, `mark-progress`, `evidence`, `review-package`, `validate-report`, `budget-check`, `metrics-match`, `projection`, `task-brief`, `prepare-brief`, `register-worker`, `write-brief` (D8).
  - Refusal at `projection`: exit 3 with `gate: "decompose_required"` and `report` = the canonical summary object; exit 2 with `gate: "failed"`, `report: null`, the capture reason as `detail`.
  - Workspace file `projection-<head7>-<M−1>.json` holding the validated result bytes; ledger line `Projection gate: <base40>..<head40> through <M−1> root_bytes=<n> total_bytes=<n> file_count=<n> largest_member_bytes=<n>`.
  - Ready object key `projection`: `{"completed_through": M−1, "head_sha": <head40>, "metrics": {...}}`, or `null` without `--task`.


**Invariants — recording (D2, D12):**
- `H` is the checkout's `HEAD`, or the head an existing `Task N: recorded (head H)` line names. `B` is the `Task N: dispatched (base B)` base. `C` is the committed forecast's `actual_evidence.head`.
- `ledger`: the ledger is this plan's; tasks 1..N−1 have `complete` lines; task N is dispatched and has no `complete` line; an earlier recorded head for N equals `H`.
- `worktree`: `git status --porcelain --untracked-files=no` names no path but the plan root and task N's member; `B != H` and `B` is an ancestor of `H`; `C` is an ancestor of `B`.
- `record`: the delivery block and every task block committed at `H` equal those committed at `B` (`a task commit edited the forecast` otherwise). From the blocks at `H` it makes exactly four changes: task N's `actual_ranges` gains `{base: B, head: H}`; when `B != C`, `actual_evidence.process_ranges` gains `{base: C, head: B, boundaries: [<proposed boundary>]}`; `actual_evidence.head`/`tree` become `H` and `H`'s tree; every `completed-tasks` prerequisite whose highest task is N gets `commit: H`, `tree: H`'s tree. Only the two JSON lines change, each rendered with `canonical_bytes` minus its final newline.
- Repeat-safe: `changed: false` with no write when both worktree files already hold the computed bytes, or when `HEAD` is a single-parent commit over `H` that changes only those two files and commits exactly those bytes. Writes are atomic; nothing is committed (the controller commits, D2).

**Invariants — `next` (D2, D8, D9, D12):**
- `ledger`: with `--completed N` the ledger must hold `Task N: recorded (head H)`; with `--task M` the tasks with `complete` lines, counting this call's `--completed`, are exactly 1..M−1.
- `ledger-complete` writes `Task N: complete (commits <B7>..<H7>, review clean | K parked)` with the recorded `H`, never the recording commit.
- `evidence` (only with `--completed`): `HEAD` has exactly one parent, that parent is `H`, `HEAD` changes only the plan root and task N's member, and both committed files equal `recorded(repo, plan, N, B, H)`. Any refusal carries gate `failed`.
- The actual gate always runs before `projection`; its refusal ends the call, so a projection never runs over or suppresses an actual failure.
- `projection` runs only with `--task M` when M has no `dispatched` line. It captures `project_argv(plan, delivery_base, HEAD, M−1)`. A re-dispatch runs no projection and requires the `Projection gate:` line through M−1 whose head is M's recorded dispatch base (`ledger` refusal otherwise).
- A plan without forecast blocks refuses at `projection` with gate `failed` (D9). `next --completed N` alone runs no projection.
- No dispatched line, brief or worker exists after either `projection` refusal.

- [ ] **Step 1: Write the failing tests** in `tests/test_sdd_gate.py` — first the recording half:

```python
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ForecastCase(GateCase):
    """The fixture plan with a v3 forecast whose delivery base is the fixture's plan commit (D15)."""

    def setUp(self):
        super().setUp()
        self.forecast_base = self.delivery_base = self.repo_git("rev-parse", "HEAD")
        package = {"spec": "spec.md", "plan": "plan.md", "tasks": ["plan.tasks/task-1.md", "plan.tasks/task-2.md"]}
        paths = [package["spec"], package["plan"], *package["tasks"]]
        bound = lambda size: [{"boundary": "all", "added_lines": 40, "deleted_lines": 0,
                               "record_bytes": size, "support": None}]
        def record(rid, owner, path, change, horizon, size):
            row = {"id": rid, "owner": owner, "path": path, "change": change, "last_task": horizon,
                   "bounds": bound(size)}
            row["bounds"][0]["support"] = {"kind": "authored-cumulative/v1", "covers": [rid]}
            return row
        self.delivery = {"schema_version": 3, "kind": "review-feasibility-delivery",
            "delivery_base": self.forecast_base, "proposed_boundary": "all", "derived_from": None,
            "boundaries": [{"id": "all", "parent": None, "tasks": [1, 2], "acceptance": "Fixture delivery",
                "depends_on": [], "prerequisite": {"kind": "delivery-base"}, "process_package": package,
                "process_forecast_ids": [f"p{n}" for n in range(4)],
                "process_commit_subject_bytes": [64, 64, 64]}],
            "process_records": [record(f"p{n}", 0, path, "add" if path == "spec.md" else "modify", 2, 4096)
                                for n, path in enumerate(paths)],
            "actual_evidence": {"kind": "git-range-ownership/v1", "head": self.forecast_base,
                "tree": self.repo_git("rev-parse", self.forecast_base + "^{tree}"), "process_ranges": []}}
        self.tasks = [{"schema_version": 3, "kind": "review-feasibility-task", "task": {"id": n,
            "commit_subject_bytes": [64, 64], "actual_ranges": [],
            "records": [record(f"r{n}", n, path, change, n, 2048)]}}
            for n, path, change in ((1, "src/app.py", "modify"), (2, "notes.txt", "add"))]
        self.write("spec.md", "# Fixture spec\n")
        self.emit_forecast()
        self.repo_commit("forecast")

    def emit_forecast(self):
        text = (FIXTURES / "plan.md").read_text(encoding="utf-8")
        self.write("plan.md", text + "\n## Review feasibility delivery\n\n```json\n"
                   + canonical(self.delivery) + "\n```\n")
        for n, block in enumerate(self.tasks, 1):
            member = (FIXTURES / f"plan.tasks/task-{n}.md").read_text(encoding="utf-8")
            self.write(f"plan.tasks/task-{n}.md", member + "\n## Review feasibility task\n\n```json\n"
                       + canonical(block) + "\n```\n")

    def read_blocks(self):
        def block(path, heading):
            lines = (self.repo / path).read_text(encoding="utf-8").splitlines()
            return json.loads(lines[lines.index(heading) + 3])
        return (block("plan.md", "## Review feasibility delivery"),
                [block(f"plan.tasks/task-{n}.md", "## Review feasibility task") for n in (1, 2)])

    def record(self, task):
        return self.gate("record", self.plan, "--task", task)


class RecordTest(ForecastCase):
    def test_record_rewrites_the_forecast_from_the_ledger_and_git(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        out = self.ready(self.record(1))
        self.assertEqual(out, {"command": "record", "outcome": "ready", "task": 1, "head_sha": head,
                               "paths": [str(self.plan), str(self.repo / "plan.tasks/task-1.md")],
                               "changed": True})
        delivery, tasks = self.read_blocks()
        self.assertEqual(tasks[0]["task"]["actual_ranges"], [{"base": base, "head": head}])
        self.assertEqual(delivery["actual_evidence"]["head"], head)
        self.assertEqual(delivery["actual_evidence"]["tree"], self.repo_git("rev-parse", head + "^{tree}"))
        self.assertEqual(delivery["actual_evidence"]["process_ranges"],
                         [{"base": self.forecast_base, "head": base, "boundaries": ["all"]}])
        self.assertIn(f"Task 1: recorded (head {head})", self.ledger_lines())
        recording = self.repo_commit("plan: record task 1 evidence")
        projected = subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "project",
            "--plan", str(self.plan), "--base", self.forecast_base, "--head", recording,
            "--completed-through", "1"], cwd=self.repo, env=self.env, capture_output=True)
        self.assertEqual(projected.returncode, 0, projected.stderr)
        again = self.ready(self.record(1))
        self.assertEqual((again["head_sha"], again["changed"]), (head, False))
        self.assertEqual(self.ledger_lines().count(f"Task 1: recorded (head {head})"), 1)

    def test_a_due_prerequisite_gets_the_recorded_identity(self):
        self.delivery["boundaries"][0]["process_commit_subject_bytes"] = [64] * 4
        child = {"id": "two", "parent": "all", "tasks": [2], "acceptance": "Second", "depends_on": ["one"],
                 "prerequisite": {"kind": "completed-tasks", "tasks": [1], "commit": None, "tree": None},
                 "process_package": {"spec": "two-spec.md", "plan": "two.md", "tasks": ["two.tasks/task-1.md"]},
                 "process_forecast_ids": ["q0", "q1", "q2"], "process_commit_subject_bytes": [64]}
        first = {**child, "id": "one", "tasks": [1], "depends_on": [], "prerequisite": {"kind": "delivery-base"},
                 "process_package": {"spec": "one-spec.md", "plan": "one.md", "tasks": ["one.tasks/task-1.md"]},
                 "process_forecast_ids": ["o0", "o1", "o2"]}
        self.delivery["boundaries"] += [first, child]
        for prefix, row in (("o", first), ("q", child)):
            for n, path in enumerate([row["process_package"]["spec"], row["process_package"]["plan"],
                                      *row["process_package"]["tasks"]]):
                self.delivery["process_records"].append({"id": f"{prefix}{n}", "owner": 0, "path": path,
                    "change": "add", "last_task": 2, "bounds": [{"boundary": row["id"], "added_lines": 1,
                    "deleted_lines": 0, "record_bytes": 512,
                    "support": {"kind": "authored-cumulative/v1", "covers": [f"{prefix}{n}"]}}]})
        for n, block in enumerate(self.tasks, 1):
            block["task"]["records"][0]["bounds"].append(
                {**block["task"]["records"][0]["bounds"][0], "boundary": "one" if n == 1 else "two"})
        self.emit_forecast(); self.repo_commit("children")
        _, head = self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.record(1))
        delivery, _ = self.read_blocks()
        self.assertEqual(delivery["boundaries"][2]["prerequisite"],
                         {"kind": "completed-tasks", "tasks": [1], "commit": head,
                          "tree": self.repo_git("rev-parse", head + "^{tree}")})

    def test_record_refuses_each_unsafe_state(self):
        refused = lambda: self.assert_gate_refused(self.record(1), command="record", step=step, gate=None,
                                                   steps=steps)
        step, steps = "ledger", []
        refused()                                                     # task 1 never dispatched
        base = self.repo_git("rev-parse", "HEAD")
        self.append_ledger(f"Task 1: dispatched (base {base})")
        step, steps = "worktree", ["ledger"]
        refused()                                                     # no task commit: B == H
        self.write("src/app.py", "value = 2\n"); self.repo_commit("task 1")
        self.write("stray.txt", "x\n"); self.repo_git("add", "stray.txt")
        refused()                                                     # extra dirty tracked path
        self.repo_git("rm", "-q", "--cached", "stray.txt"); (self.repo / "stray.txt").unlink()
        self.write("plan.md", (self.repo / "plan.md").read_text(encoding="utf-8").replace(
            '"record_bytes":2048', '"record_bytes":1024'))
        self.repo_commit("task 1 lowers its bound")
        step, steps = "record", ["ledger", "worktree"]
        refused()                                                     # a task commit edited the forecast
        self.append_ledger(f"Task 1: recorded (head {base})")
        step, steps = "ledger", []
        refused()                                                     # recorded head differs from HEAD's chain
```

Then the `next` half.

Re-base every `NextTest` case that passes `--task` on `ForecastCase` (the `Delivery base:` line it appends equals `--delivery-base`), and make cases that dispatch task M first complete and record tasks 1..M−1. Then add:

```python
SUMMARY_KEYS = {"artifact_policy_sha256", "base", "completed_through", "forecast_sha256", "head", "kind",
                "metrics", "packing_policy_sha256", "plan", "plan_package_sha256", "recommended_boundary",
                "schema_version", "state", "violations"}
GATE_STEPS = ["ledger", "review-package", "validate-report", "budget-check", "metrics-match"]


class NextProjectionTest(ForecastCase):
    def next(self, *args):
        return self.gate("next", self.plan, "--skill-dir", SKILL, "--standards", PROJECT_STANDARDS, *args)

    def first(self, *args):
        return self.next("--task", 1, "--delivery-base", self.forecast_base, *args)

    def workers(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["workers"]

    def complete(self, task, path, text):
        """Run task `task` to a committed recording; return (task head, recording head)."""
        _, head = self.start_task(task, path, text)
        self.ready(self.record(task))
        return head, self.repo_commit(f"plan: record task {task} evidence")

    def lines_matching(self, prefix):
        return [line for line in self.ledger_lines() if line.startswith(prefix)]

    def test_the_initial_projection_runs_after_the_actual_gate_and_before_dispatch(self):
        head = self.repo_git("rev-parse", "HEAD")
        out = self.ready(self.first())
        self.assertEqual((out["projection"]["completed_through"], out["projection"]["head_sha"]), (0, head))
        lines = self.ledger_lines()
        gate = next(i for i, l in enumerate(lines) if l.startswith("Delivery gate:"))
        projected = next(i for i, l in enumerate(lines) if l.startswith("Projection gate:"))
        dispatched = lines.index(f"Task 1: dispatched (base {head})")
        self.assertLess(gate, projected); self.assertLess(projected, dispatched)
        self.assertTrue(lines[projected].startswith(
            f"Projection gate: {self.forecast_base}..{head} through 0 root_bytes="))
        self.assertTrue((self.workspace / f"projection-{head[:7]}-0.json").is_file())

    def test_a_projected_overflow_stops_with_a_confirmable_summary(self):
        self.delivery["boundaries"][0]["process_commit_subject_bytes"] = [120] * 100
        self.emit_forecast(); head = self.repo_commit("oversized forecast")
        done = self.first()
        out = self.assert_gate_refused(done, command="next", step="projection", gate="decompose_required",
                                       steps=GATE_STEPS, code=3)
        self.assertEqual(set(out["report"]), SUMMARY_KEYS)
        self.assertEqual((out["report"]["state"], out["report"]["head"], out["report"]["completed_through"]),
                         ("decompose_required", head, 0))
        self.assertEqual(self.lines_matching("Task 1: dispatched"), [])
        self.assertFalse((self.workspace / "task-1-implementer-dispatch.md").exists())
        raw = json.dumps(out["report"]).encode()
        confirmed = subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "confirm",
            "--plan", str(self.plan), "--base", self.forecast_base, "--input", "-"], input=raw,
            cwd=self.repo, env=self.env, capture_output=True)
        self.assertEqual(confirmed.returncode, 3, confirmed.stderr)

    def test_an_invalid_projection_fails_before_dispatch_and_registers_nothing(self):
        self.launch()
        self.delivery["delivery_base"] = "0" * 40
        self.emit_forecast(); self.repo_commit("wrong forecast base")
        done = self.first(*self.identity())
        self.assert_gate_refused(done, command="next", step="projection", gate="failed",
                                 steps=["ledger", "mark-progress", *GATE_STEPS[1:]])
        self.assertEqual(self.lines_matching("Task 1: dispatched"), [])
        self.assertEqual(self.workers(), [])

    def test_post_task_order_needs_the_exact_recording_commit(self):
        self.ready(self.first())
        base = self.repo_git("rev-parse", "HEAD")
        _, task_head = self.start_task(1, "src/app.py", "value = 2\n")
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="ledger",
                                 gate=None, steps=[])                       # not recorded
        self.ready(self.record(1))
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="evidence",
                                 gate="failed", steps=["ledger", "ledger-complete"])  # not committed
        self.write("notes.txt", "smuggled\n"); recording = self.repo_commit("plan: record task 1 evidence")
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="evidence",
                                 gate="failed", steps=["ledger", "ledger-complete"])  # extra path
        self.repo_git("reset", "-q", "--hard", task_head)
        self.ready(self.record(1)); recording = self.repo_commit("plan: record task 1 evidence")
        out = self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(out["projection"]["head_sha"], recording)
        self.assertIn(f"Task 1: complete (commits {base[:7]}..{task_head[:7]}, review clean)",
                      self.ledger_lines())
        self.assertTrue(self.lines_matching(f"Projection gate: {self.forecast_base}..{recording} through 1 "))
        again = self.ready(self.next("--task", 2))                       # re-dispatch reuses the line
        self.assertEqual(len(self.lines_matching("Projection gate:")), 2)
        self.assertEqual(again["projection"]["head_sha"], recording)

    def test_an_actual_overflow_refuses_before_any_projection(self):
        self.ready(self.first())
        self.complete(1, "src/app.py", "".join(f"value_{n} = {n}\n" for n in range(8000)))
        out = self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next",
            step="validate-report", gate="decompose_required",
            steps=["ledger", "ledger-complete", "evidence", "review-package"], code=3)
        self.assertEqual(out["report"]["state"], "decompose_required")
        self.assertEqual(len(self.lines_matching("Projection gate:")), 1)
        self.assertEqual(self.lines_matching("Task 2: dispatched"), [])

    def test_completing_the_last_task_runs_no_projection(self):
        self.ready(self.first())
        self.complete(1, "src/app.py", "value = 2\n")
        self.ready(self.next("--completed", 1, "--task", 2))
        self.complete(2, "notes.txt", "notes\n")
        out = self.ready(self.next("--completed", 2))
        self.assertIsNone(out["projection"])
        self.assertEqual(len(self.lines_matching("Projection gate:")), 2)
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python timeout 1200 python3 -m unittest tests.test_sdd_gate.RecordTest tests.test_sdd_gate.NextProjectionTest 2>&1 | tail -3`
Expected: FAIL — `sdd-gate: invalid invocation` (no `record` subcommand) and `KeyError: 'projection'`.

- [ ] **Step 3: Implement**

- `review_record.recorded` reads committed bytes with `git show <commit>:<path>` (both commits), parses blocks with the loader's `_block`, applies the four changes, and replaces the single JSON line under each heading. A `ForecastError` from parsing becomes `RecordError` with its reason.
- `sdd_gate.record(args, done)` follows the steps and invariants above; `_parser` gains `record PLAN_FILE --task N`; `main` dispatches it. The module docstring and `python/README.md` § `sdd-gate` gain the `record` contract (its invocation, steps, ready object, ledger line and repeat rule).
- A recorded head that `HEAD` neither equals nor is the single-parent recording commit over refuses at `ledger`.
- `_ledger_reads` gains the recorded-head read and the 1..M−1 completeness rule; `next_task` inserts `evidence` after `mark-progress` and `projection` after the `Delivery gate:` line is written, and adds `projection` to the ready object.
- `projection` uses `capture(project_argv(plan, delivery_base, head, M - 1), cwd=ledger.top, authority=package.authority)`; on exit 0 or 3 it writes the validated bytes with `write_atomic` before acting; on exit 3 the refusal report is `summarize(capture, plan_relative(plan))`; a `GateError` is the `failed` refusal. The ledger line is appended once (`_ledger_has`).
- Update the module docstring step list (thirteen steps) and `python/README.md` § `sdd-gate` with the `record`-then-`next` order, the two new steps, the ledger line, the saved result and the ready object's `projection`.
- Update existing `NextTest` expectations whose ledgers or `completed_steps` gain the new steps; keep each test's intent.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 1200 python3 -m unittest tests/test_sdd_gate.py 2>&1 | tail -3` — Expected: `OK`.
Run: `timeout 3600 just build 2>&1 | tail -2` — Expected: success (stage the new module first).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_record.py python/agent_tools/sdd_gate.py tests/test_sdd_gate.py python/README.md
git commit -m "feat(sdd-gate): record ownership and project before dispatch"
```

Decisions: D2, D8, D9, D12, D15.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":3,"records":[{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}},{"added_lines":200,"boundary":"c2","deleted_lines":0,"record_bytes":10240,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/review_record.py"},{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":40,"record_bytes":24576,"support":{"covers":["r3b"],"kind":"authored-cumulative/v1"}},{"added_lines":260,"boundary":"c2","deleted_lines":40,"record_bytes":24576,"support":{"covers":["r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"python/agent_tools/sdd_gate.py"},{"bounds":[{"added_lines":450,"boundary":"all","deleted_lines":60,"record_bytes":28672,"support":{"covers":["r3c"],"kind":"authored-cumulative/v1"}},{"added_lines":450,"boundary":"c2","deleted_lines":60,"record_bytes":28672,"support":{"covers":["r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":3,"owner":3,"path":"tests/test_sdd_gate.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":8,"record_bytes":24576,"support":{"covers":["r1e","r3d"],"kind":"authored-cumulative/v1"}},{"added_lines":14,"boundary":"c2","deleted_lines":8,"record_bytes":24576,"support":{"covers":["r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":3,"owner":3,"path":"python/README.md"}]}}
```
