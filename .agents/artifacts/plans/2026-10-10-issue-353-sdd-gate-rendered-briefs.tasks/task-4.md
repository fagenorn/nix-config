# Task 4: `sdd-gate next` and `task-brief` on `PATH`

**Files:**
- Modify: `python/agent_tools/sdd_gate.py`
- Modify: `tests/test_sdd_gate.py`
- Create: `tests/fixtures/sdd-gate/skill/implementer-prompt.md`, `tests/fixtures/sdd-gate/golden-implementer-brief.md`
- Modify: `home/common/agent-skills/default.nix` (one `home.file` entry)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one assertion)
- Modify: `python/README.md` (the `sdd-gate` section)
- Modify: `home/common/agent-skills/README.md` (one subsection)
- Test: `tests/test_sdd_gate.py`

**Interfaces:**
- Consumes, from Task 3, in `agent_tools.sdd_gate`: `InvocationError`; `Refusal(step: str, detail: str, *, gate: str | None = None, report: dict | None = None)`; `Ledger` (`workspace`, `path`, `lines`, `top`); `open_ledger(plan: Path) -> Ledger`; `recorded_sha(ledger: Ledger, pattern: str) -> str | None` (the one distinct group-1 value among fully matching ledger lines, `None` when none, `Refusal("ledger", …)` when two differ); `task_base(ledger: Ledger, task: int) -> str`; `append_line(ledger: Ledger, line: str) -> None`; `pinned_head() -> str`; `Package` (`manifest_root`, `root`, `metrics`, `authority`); `package_gate(plan: Path, ledger: Ledger, base: str, head: str, done: list[str]) -> Package`; `workflow_state(step: str, *argv: str) -> dict`; `shared_values(plan: Path, ledger: Ledger, task: int, authority, documents: Sequence[Path]) -> dict[str, str]`; `write_atomic(path: Path, data: bytes) -> None`; the parser and `main`, which this task extends; and, in `tests/test_sdd_gate.py`, the `GateCase` base class with its helpers and the fixtures under `tests/fixtures/sdd-gate/`.
- Consumes, from Tasks 1–2, in `agent_tools.sdd_brief`: `BriefError`, `IMPLEMENTER_TEMPLATE`, `IMPLEMENTER_TOKENS`, `render`, `plan_section`, `task_row(plan_text: str, number: int) -> TaskRow` (`title`, `paths`), `select_standards`, `worker_block(repo_root: str, run_id: str, worker_id: str) -> str`.
- Produces: `next_task(args: argparse.Namespace, done: list[str]) -> dict` in `agent_tools.sdd_gate`, the `next` subcommand, and the installed command `~/.agents/bin/task-brief`.

**Invariants (spec "`sdd-gate next`: steps in order", "What the ledger holds"; D3, D4, D8, D11, D12):**
- Steps run in the order `ledger`, `ledger-complete`, `mark-progress`, `review-package`, `validate-report`, `budget-check`, `metrics-match`, `task-brief`, `prepare-brief`, `register-worker`, `write-brief`. A step that does not apply to the call does not run and is not listed in `completed_steps`.
- The ledger gains only these lines, one write each, and never the same line twice: `Delivery base: <sha40>`; `Task <N>: complete (commits <base7>..<head7>, review clean)` or `…, <K> parked)`; `Delivery gate: <base40>..<head40> root_bytes=<n> total_bytes=<n> file_count=<n> largest_member_bytes=<n>`; `Task <M>: dispatched (base <sha40>)`.
- Step `ledger` writes nothing until every one of its reads has passed.
- `mark-progress` never refuses the call: a non-zero exit is reported as `"refused"`.
- A worker is registered only after the brief has been rendered once in memory; a failed write releases that worker with `--event stopped` before the refusal is printed.
- `review` and every Task 3 test keep passing unchanged.
- `home/common/agent-skills/skills/sdd/scripts/task-brief` is not edited; it is installed as it is.

- [ ] **Step 1: Create the two fixtures**

`tests/fixtures/sdd-gate/skill/implementer-prompt.md`:

````markdown
# Fixture implementer template

```
Subagent (fixture):
  description: "Implement Task N"
  prompt: |
    Task [TASK_NUMBER]: [TASK_NAME]

    Brief: [BRIEF_FILE]
    Report: [REPORT_FILE]

    [CONTEXT]

    Plan: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])

    Constraints:
    [GLOBAL_CONSTRAINTS]

    Seams:
    [TEST_SEAMS]

    ## Standards

    [STANDARDS]

    Stacks: [STACKS_DIR]

    ## Worker

    [LIFECYCLE_WORKER]

    End.
```
````

`tests/fixtures/sdd-gate/golden-implementer-brief.md` — assembled by hand for Task 1 of the fixture plan, the context text `Fits after setup.` / ``Use `value`.`` and no lifecycle identity, so the `[LIFECYCLE_WORKER]` line and the empty line after it are gone:

````markdown
Task 1: Change the value

Brief: @@WORKSPACE@@/task-1-brief.md
Report: @@WORKSPACE@@/task-1-report.md

Fits after setup.
Use `value`.

Plan: @@PLAN_ROOT@@ (@@PLAN_ROOT_BYTES@@, @@PLAN_TOTAL_BYTES@@, @@PLAN_FILE_COUNT@@, @@PLAN_LARGEST_MEMBER_BYTES@@)

Constraints:
- Python 3.11 standard library only.
- Paths are repository-relative.

Seams:
- The command, run from source.

## Standards

Source: @@HOME@@/.agents/standards/the-bar.md

# Fixture bar

Keep modules deep.

Source: @@STANDARDS@@/python-rules.md

# Fixture Python rules

Name the unit under test.

Stacks: @@HOME@@/.agents/standards/stacks

## Worker

End.
````

- [ ] **Step 2: Write the failing tests**

In `tests/test_sdd_gate.py` add, after the standard-library imports, the line `from agent_tools import sdd_brief` (followed by one empty line), and append this before the `if __name__` block:

````python
NEXT_STEPS = ["ledger", "mark-progress", "review-package", "validate-report", "budget-check",
              "metrics-match", "task-brief", "prepare-brief", "register-worker"]


class NextTest(GateCase):
    def brief(self, task=1):
        return self.workspace / f"task-{task}-implementer-dispatch.md"

    def next(self, *args, skill=SKILL):
        return self.gate("next", self.plan, "--skill-dir", skill,
                         "--standards", PROJECT_STANDARDS, *args)

    def first(self, *args, skill=SKILL):
        """The run's first call: it carries the delivery base."""
        return self.next("--task", 1, "--delivery-base", self.delivery_base, *args, skill=skill)

    def head(self):
        return self.repo_git("rev-parse", "HEAD")

    def delivery(self, head):
        """(manifest root, metrics, ledger line) of the cumulative gate at `head`."""
        root = self.package_root(self.delivery_base, head)
        metrics = self.budget_metrics("review-package", self.repo / root)
        return root, metrics, (
            f"Delivery gate: {self.delivery_base}..{head} root_bytes={metrics['root_bytes']} "
            f"total_bytes={metrics['total_bytes']} file_count={metrics['file_count']} "
            f"largest_member_bytes={metrics['largest_member_bytes']}")

    def workers(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["workers"]

    def test_the_first_call_records_both_bases_and_renders_the_implementer_brief(self):
        head = self.head()
        context = self.root / "context.md"
        context.write_text("Fits after setup.\nUse `value`.\n\n", encoding="utf-8")
        out = self.ready(self.first("--context-file", context))
        root, metrics, line = self.delivery(head)
        self.assertEqual(out, {
            "command": "next", "outcome": "ready", "completed": None, "task": 1,
            "brief_path": str(self.brief()),
            "report_path": str(self.workspace / "task-1-report.md"),
            "base_sha": head, "worker_id": None, "mark_progress": "skipped",
            "delivery": {"base_sha": self.delivery_base, "head_sha": head,
                         "manifest_root": root, "metrics": metrics},
            "standards": [str(self.bar), str(PROJECT_STANDARDS / "python-rules.md")]})
        self.assertEqual(self.ledger_lines()[1:], [
            f"Delivery base: {self.delivery_base}", line, f"Task 1: dispatched (base {head})"])
        self.assertEqual(self.brief().read_bytes(), self.golden("golden-implementer-brief.md"))
        self.assertEqual((self.workspace / "task-1-brief.md").read_bytes(),
                         (FIXTURES / "plan.tasks/task-1.md").read_bytes())

    def test_a_repeated_call_writes_no_second_ledger_line(self):
        first = self.first()
        self.ready(first)
        lines = self.ledger_lines()
        again = self.next("--task", 1)  # the ledger holds the delivery base now
        self.assertEqual((again.returncode, again.stdout), (0, first.stdout))
        self.assertEqual(self.ledger_lines(), lines)
        # No context: the [CONTEXT] line and the empty line after it are gone.
        self.assertIn("task-1-report.md\n\nPlan: ", self.brief().read_text(encoding="utf-8"))

    def test_the_delivery_base_must_be_known_and_must_not_change(self):
        header = self.ledger_lines()
        self.assert_gate_refused(self.next("--task", 1), command="next", step="ledger",
                                 gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), header)
        self.ready(self.first())
        lines = self.ledger_lines()
        self.assert_gate_refused(self.next("--task", 1, "--delivery-base", self.head()),
                                 command="next", step="ledger", gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), lines)

    def test_completing_a_task_appends_its_line_once(self):
        self.ready(self.first())
        base = self.head()
        self.write("src/app.py", "value = 2\n")
        head = self.repo_commit("task 1")
        out = self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(self.ledger_lines()[-3:], [
            f"Task 1: complete (commits {base[:7]}..{head[:7]}, review clean)",
            self.delivery(head)[2], f"Task 2: dispatched (base {head})"])
        self.assertEqual((out["completed"], out["task"], out["base_sha"]), (1, 2, head))
        self.assertEqual(out["standards"], [str(self.bar)])  # Task 2's row names notes.txt only
        lines = self.ledger_lines()
        self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(self.ledger_lines(), lines)

    def test_parked_findings_are_counted_and_the_last_call_renders_nothing(self):
        self.ready(self.next("--task", 2, "--delivery-base", self.delivery_base))
        base = self.head()
        self.write("notes.txt", "note\n")
        head = self.repo_commit("task 2")
        out = self.ready(self.next("--completed", 2, "--parked", 3))
        self.assertEqual(self.ledger_lines()[-2:], [
            f"Task 2: complete (commits {base[:7]}..{head[:7]}, 3 parked)", self.delivery(head)[2]])
        self.assertEqual([out[key] for key in ("task", "brief_path", "report_path", "base_sha",
                                               "worker_id")], [None] * 5)
        self.assertEqual((out["completed"], out["standards"]), (2, []))

    def test_completing_an_undispatched_task_is_refused_before_any_write(self):
        header = self.ledger_lines()
        self.assert_gate_refused(
            self.next("--completed", 2, "--delivery-base", self.delivery_base),
            command="next", step="ledger", gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), header)

    def test_an_over_budget_delivery_stops_before_the_next_dispatch(self):
        self.write("large.txt", "small\n")
        self.repo_commit("small")
        self.ready(self.first())
        self.write("large.txt", "X" * 70_000 + "\n")
        self.repo_commit("task 1")
        out = self.assert_gate_refused(
            self.next("--completed", 1, "--task", 2), command="next", step="validate-report",
            gate="decompose_required", steps=["ledger", "ledger-complete", "review-package"],
            code=3)
        self.assertEqual(out["report"]["state"], "decompose_required")
        self.assertTrue(self.ledger_lines()[-1].startswith("Task 1: complete ("))
        self.assertFalse(self.brief(2).exists())

    def test_a_task_without_an_index_row_is_refused_at_task_brief(self):
        self.assert_gate_refused(
            self.next("--task", 9, "--delivery-base", self.delivery_base), command="next",
            step="task-brief", gate=None,
            steps=["ledger", "review-package", "validate-report", "budget-check", "metrics-match"])
        self.assertFalse(any(line.startswith("Task 9") for line in self.ledger_lines()))

    def test_a_brief_that_cannot_be_prepared_is_refused_before_a_worker_is_registered(self):
        self.launch()
        drifted = self.root / "drifted"
        shutil.copytree(SKILL, drifted)
        template = drifted / "implementer-prompt.md"
        template.write_text(template.read_text(encoding="utf-8").replace(
            "    End.\n", "    End [SURPRISE].\n"), encoding="utf-8")
        cases = {"template drift": lambda: self.first(*self.identity(), skill=drifted),
                 "an unreadable context file": lambda: self.first(
                     "--context-file", self.root / "absent.md", *self.identity())}
        for name, call in cases.items():
            with self.subTest(case=name):
                self.assert_gate_refused(call(), command="next", step="prepare-brief", gate=None,
                                         steps=NEXT_STEPS[:7])
        self.assertEqual(self.workers(), [])
        self.assertFalse(self.brief().exists())

    def test_under_an_identity_the_worker_is_registered_and_named_in_the_brief(self):
        self.launch()
        out = self.ready(self.first(*self.identity()))
        self.assertEqual((out["worker_id"], out["mark_progress"]), ("14:1:1:w1", "baseline"))
        self.assertTrue(self.check_worker("14:1:1:w1")["live"])
        block = sdd_brief.worker_block(str(self.root), self.run_id, "14:1:1:w1")
        self.assertIn(f"## Worker\n\n{block}\n\nEnd.\n", self.brief().read_text(encoding="utf-8"))
        again = self.ready(self.next("--task", 1, *self.identity()))  # a re-dispatch of the task
        self.assertEqual((again["worker_id"], again["base_sha"], again["mark_progress"]),
                         ("14:1:1:w2", out["base_sha"], "unchanged"))

    def test_a_refused_progress_mark_does_not_stop_the_call(self):
        self.launch(worktree=self.root / "gone")
        out = self.ready(self.first(*self.identity()))
        self.assertEqual((out["mark_progress"], out["worker_id"]), ("refused", "14:1:1:w1"))

    def test_a_refused_registration_leaves_no_brief(self):
        self.launch()
        head = self.head()
        self.assert_gate_refused(self.first(*self.identity("14:1:9")), command="next",
                                 step="register-worker", gate=None, steps=NEXT_STEPS[:8])
        self.assertFalse(self.brief().exists())
        self.assertEqual(self.workers(), [])
        self.assertEqual(self.ledger_lines()[-1], f"Task 1: dispatched (base {head})")

    def test_a_failed_write_releases_the_worker_it_registered(self):
        self.launch()
        (self.brief() / "occupied").mkdir(parents=True)  # a rename cannot replace this directory
        self.assert_gate_refused(self.first(*self.identity()), command="next", step="write-brief",
                                 gate=None, steps=NEXT_STEPS)
        self.assertEqual([(worker["worker_id"], worker["release_event"])
                          for worker in self.workers()], [("14:1:1:w1", "stopped")])

    # test_a_failed_write_names_the_worker_it_could_not_release — see the note after this block.

    def test_an_invalid_next_invocation_prints_one_stderr_line(self):
        base = ("next", self.plan, "--skill-dir", SKILL)
        cases = {
            "neither --completed nor --task": base,
            "--parked without --completed": (*base, "--task", "1", "--parked", "1"),
            "--context-file without --task": (*base, "--completed", "1", "--context-file", "c.md"),
            "a short delivery base": (*base, "--task", "1", "--delivery-base", "abc1234"),
            "a worker id": (*base, "--task", "1", *self.identity(), "--worker-id", "14:1:1:w1"),
            "the stdin flag the design dropped": (*base, "--task", "1", "--context-stdin"),
        }
        for name, argv in cases.items():
            with self.subTest(case=name):
                done = self.gate(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
````

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, directly after the line `self.assertIn('".agents/bin/sdd-workspace"', nix_module)`, add:

```python
        self.assertIn('".agents/bin/task-brief"', nix_module)
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_gate.py -k NextTest`
Also write `NextTest.test_a_failed_write_names_the_worker_it_could_not_release`, placed where the comment in the block above marks it (replace the comment). It repeats the failed-write setup, and first replaces the `workflow-state` PATH shim, through the case's existing `write_executable`, with one that exits 1 for the `release-worker` subcommand and passes every other subcommand to the source command unchanged. It asserts the refusal has step `write-brief` and steps `NEXT_STEPS`, that `detail` contains `14:1:1:w1` and `release-worker`, and that `self.workers()` still lists `14:1:1:w1` with no release event (D15). Write it from the fixture's real shim text; the plan does not dictate its body.

Expected: 14 of the 15 tests fail. `next` is not a subcommand yet, so each call exits 2 with `sdd-gate: invalid invocation` and an empty stdout; `test_an_invalid_next_invocation_prints_one_stderr_line` expects exactly that and passes already.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_installed_policy_surface_matches_source_contract`
Expected: FAIL — `'".agents/bin/task-brief"' not found` in the Nix module text.

- [ ] **Step 4: Implement the `next` subcommand**

*Parsing.* `next` takes the positional `PLAN_FILE`, required `--skill-dir`, repeatable `--standards`, the three identity flags (no `--worker-id`), and optional `--completed N`, `--parked K`, `--task M`, `--context-file PATH`, `--delivery-base SHA`. `N`, `K` and `M` match `[1-9][0-9]*`; `SHA` matches `[0-9a-f]{40}` in full. Invalid invocations: neither `--completed` nor `--task`; `--parked` without `--completed`; `--context-file` without `--task`; a partial identity. There is no `--context-stdin` (D11).

*Step `ledger`.* `open_ledger(plan)`. The recorded delivery base is `recorded_sha(ledger, r"Delivery base: ([0-9a-f]{40})")`. Refuse (`Refusal("ledger", …)`) when none is recorded and `--delivery-base` is absent, or when both exist and differ. With `--completed N`, `task_base(ledger, N)` (refused when absent). With `--task M`, the task's recorded base is `recorded_sha` for its `dispatched` line and may be `None`. Only then, when no delivery base was recorded, `append_line(ledger, f"Delivery base: {sha}")`.

*Head.* `head = pinned_head()`, once, after step `ledger`.

*Step `ledger-complete`,* with `--completed N` only. Skip the write when a ledger line already starts with `Task <N>: complete`. Otherwise append `Task <N>: complete (commits <base7>..<head7>, review clean)`, or with `--parked K` the same line ending `, <K> parked)`; the two SHAs are the first seven characters of the task base and of `head`.

*Step `mark-progress`,* under an identity only. Run `workflow-state mark-progress --repo-root R --run-id I --action-id A`. The output's `mark_progress` is the reply's `outcome` when the exit is 0 and the reply is a JSON object with a string `outcome`; in every other case it is `"refused"`. Without an identity it is `"skipped"`. This step never raises.

*Steps `review-package` to `metrics-match`.* `package_gate(plan, ledger, delivery_base, head, done)`. After it passes, append the `Delivery gate:` line (the four metrics in the order `root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`) unless the ledger file already holds that exact line. Without `--task` the call is ready here.

*Step `task-brief`.* Run `task-brief <plan> <M>` by name. A non-zero exit or a command that cannot start is `Refusal("task-brief", <its stderr as one line>)`.

*Step `prepare-brief`.* When the task has no recorded base, append `Task <M>: dispatched (base <head>)` and use `head`; otherwise reuse the recorded base. Read the plan as UTF-8; `row = task_row(plan_text, M)`; `documents = select_standards(global_dir, entries, list(row.paths))`. The values are `shared_values(…)` plus `[TASK_NUMBER]` (`str(M)`), `[TASK_NAME]` (`row.title`), `[CONTEXT]` (the `--context-file` bytes decoded as strict UTF-8 with trailing `"\n"` characters removed, or `""` without the flag), `[GLOBAL_CONSTRAINTS]` and `[TEST_SEAMS]` (`plan_section` of `## Global Constraints` and `## Test seams`) and `[LIFECYCLE_WORKER]` (`""` for now). Read `<skill-dir>/implementer-prompt.md` and call `render` once with these values, discarding the result: it proves the brief renders before any worker exists. `BriefError`, `BudgetError`, `OSError` or `UnicodeDecodeError` is `Refusal("prepare-brief", …)`.

*Step `register-worker`,* under an identity only. `workflow_state("register-worker", "register-worker", "--repo-root", R, "--run-id", I, "--action-id", A)`; a reply without a string `worker_id` is refused at this step. Set `[LIFECYCLE_WORKER]` to `worker_block(R, I, worker_id)`, `R` and `I` exactly as given on the command line.

*Step `write-brief`.* `write_atomic` the rendered brief to `task-<M>-implementer-dispatch.md` in the workspace. On `OSError`: when this call registered a worker, run `workflow-state release-worker --repo-root R --run-id I --worker-id <worker_id> --event stopped`; then `Refusal("write-brief", …)`. When that release exits 0 the detail is the write error alone. When it exits non-zero or cannot start, the step is still `write-brief` and the one-line detail holds the write error, then the worker id, the statement that it is still registered, and the exact `release-worker … --event stopped` command to run before calling `next` again (D15). The refusal object's key set does not change.

*Output.* Ready, in this key order: `command`, `outcome`, `completed`, `task`, `brief_path`, `report_path`, `base_sha`, `worker_id`, `mark_progress`, `delivery` (`base_sha`, `head_sha`, `manifest_root`, `metrics`), `standards`. `completed`, `task`, `brief_path`, `report_path`, `base_sha` and `worker_id` are `null` when they do not apply; `standards` is `[]` without `--task`. `base_sha` is the task's base; `report_path` is `task-<M>-report.md` in the workspace. Refusals and exit codes are Task 3's.

Update the module docstring from the code: it now states both invocations and both step orders.

- [ ] **Step 5: Install `task-brief` on `PATH`**

In `home/common/agent-skills/default.nix`, directly after the `".agents/bin/sdd-workspace"` entry, add:

```nix
    ".agents/bin/task-brief" = {
      source = ./skills/sdd/scripts/task-brief;
      executable = true;
    };
```

`task-brief` looks for `sdd-workspace` in its own directory (`dirname "$0"`), and `~/.agents/bin/` holds both, so the script needs no change (D1).

- [ ] **Step 6: Document**

- `python/README.md`, section ``## `sdd-gate` ``: extend it from the implemented code with the `next` invocation and its flags, its eleven step names in order, the four ledger line shapes and who reads them (`review` and `next` read `dispatched`; `workflow-state resume-pack` reads `complete`), the ready object's members, that `mark-progress` never refuses the call, and that a failed brief write releases the worker it registered.
- `home/common/agent-skills/README.md`: add a subsection `### task-brief on PATH` at the end of `## Lifecycle helpers`. It says, in two or three sentences written from what you installed: `~/.agents/bin/task-brief` is the sdd skill's `scripts/task-brief`, installed beside `sdd-workspace`; `sdd-gate next` runs it by name because a packaged command reaches an executable outside the package by its name on `PATH` (`docs/standards/agent-helpers.md` rule 3); the script finds `sdd-workspace` next to itself in both locations.

- [ ] **Step 7: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_gate.py` (timeout 900 s)
Expected: `OK`, 25 tests, no warnings.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_task_brief.py home/common/agent-skills/tests/test_sdd_workspace.py` (timeout 900 s)
Expected: `OK` (skips allowed).

Run: `git diff --stat cd4b1746e5a844a17f806ccf791e6840e26d4cb2 -- home/common/agent-skills/skills/sdd/scripts home/common/agent-skills/scripts python/agent_tools/review_package.py python/agent_tools/review_publish.py python/agent_tools/review_budget.py`
Expected: no output.

Run: `just build` (timeout 3600 s)
Expected: exit 0.

Run, after that build: `test -x "$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')/.agents/bin/task-brief"`
Expected: exit 0 (the built home tree holds an executable `task-brief`).

- [ ] **Step 8: Commit**

```bash
git add python/agent_tools/sdd_gate.py tests/test_sdd_gate.py tests/fixtures/sdd-gate home/common/agent-skills/default.nix home/common/agent-skills/tests/test_workflow_skill_contracts.py python/README.md home/common/agent-skills/README.md
git commit -m "feat(issue-353): sdd-gate next advances the ledger and renders the implementer brief"
```
