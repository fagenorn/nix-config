# Task 1: Clock seam, skew rule and wait suffix for the flag commands

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new `LedgerClockSeamTest`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (new `LedgerClockTest`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces, in `workflow-state.py`, for Tasks 2 and 3:
  - `SUPPLIED_TIME_MAX_LEAD_SECONDS = 60`
  - `ledger_clock() -> datetime`
  - `supplied_time(value: str | None, label: str) -> datetime | None`
  - `ledger_time(supplied: datetime | None) -> datetime`
  - `backward_refusal(prefix: str, now: datetime, field: str, stored: str) -> WorkflowError`
- Produces, in `test_delivery_workflow.py`, for Task 2: the module constants `CLOCK_ENV`, `PINNED` and `SKEW`, and `LedgerClockTest` with its helpers `pin`, `at`, `clock_text`, `assert_clock_stamp`, `run_args` and `spawn_two`, exactly as written in Step 1.

**Invariants:**
- `ledger_clock` is the only function in `workflow-state.py` that holds the literal `"WORKFLOW_STATE_TEST_CLOCK"` or calls `datetime.now`, `datetime.utcnow`, `datetime.today`, `date.today`, `time.time` or `time.time_ns`. The delivery modules hold none of them (D1, D11).
- With the override unset or empty, `ledger_clock` returns `datetime.now(timezone.utc).replace(microsecond=0)`. When it is set, it returns the parsed value truncated to whole seconds. A value that does not parse, or one later than the real clock, raises `WorkflowError` (D2, D4).
- `supplied_time(None, …)` returns `None` and does not read the clock. Otherwise it parses the value with `parse_utc(value, label)`, reads `ledger_clock()` once, and refuses when `math.ceil(lead) > 60`. A time exactly 60 seconds ahead, and a past time of any age, are accepted (D6).
- Every flag command calls `supplied_time(args.now, "--now")` at the point where it parses `--now` today. That is before it reads any input file, and before `transact`. It calls `ledger_time(supplied)` as the first statement of its mutation, under the ledger lock. Nothing outside the mutation reads the resolved time (D7, D11).
- The six flag-command backward refusals keep their current prefixes and gain the suffix from `backward_refusal`. `register-worker`, `mark-progress` and `release-worker` use the field `run updated_at`. `progress`, `suspend` and the legacy `finish` use the field `attempt last_progress_at` (D8).
- A refused write leaves `state.json` byte-identical.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, add `import ast` and `from datetime import datetime, timezone` to the imports (neither is imported today). Then append:

```python
class LedgerClockSeamTest(LifecycleHarness, unittest.TestCase):
    """#309 D1, D2, D11: one clock seam, and an override that can only pin the present or past."""

    CLOCK_CALLS = frozenset({("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
                             ("date", "today"), ("time", "time"), ("time", "time_ns")})

    def setUp(self):
        super().setUp()
        self.cli_env.pop("WORKFLOW_STATE_TEST_CLOCK", None)

    def init_without_time(self):
        return self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id,
                            ok=False)

    def test_an_override_later_than_the_clock_is_refused(self):
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = "2999-01-01T00:00:00Z"
        refused = self.init_without_time()
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertRegex(refused.stderr,
                         r"^workflow-state: invalid WORKFLOW_STATE_TEST_CLOCK: "
                         r"2999-01-01T00:00:00Z is later than the clock "
                         r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$")
        self.assertFalse(self.state_path.exists())

    def test_a_malformed_override_is_refused(self):
        for value in ("yesterday", "2026-08-13T20:00:00"):
            with self.subTest(value=value):
                self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = value
                refused = self.init_without_time()
                self.assertEqual(
                    (refused.returncode, refused.stdout, refused.stderr),
                    (2, "", "workflow-state: invalid WORKFLOW_STATE_TEST_CLOCK: "
                            "expected an RFC3339 UTC timestamp\n"))
                self.assertFalse(self.state_path.exists())

    def test_the_override_pins_the_stamp_and_an_empty_one_is_the_clock(self):
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = "2026-09-30T12:00:00Z"
        self.assertEqual(self.init_without_time().returncode, 0)
        self.assertEqual(self.read_state()["updated_at"], "2026-09-30T12:00:00Z")
        self.run_id = "issue-14-empty-override"
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = ""
        self.assertEqual(self.init_without_time().returncode, 0)
        stamp = datetime.fromisoformat(self.read_state()["updated_at"].replace("Z", "+00:00"))
        self.assertLessEqual(abs((datetime.now(timezone.utc) - stamp).total_seconds()), 5)

    def sites(self, path):
        """(kind, innermost enclosing function name) for each clock call and override literal."""
        found = []

        def visit(node, owner):
            for child in ast.iter_child_nodes(node):
                inner = (child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                         else owner)
                if isinstance(child, ast.Constant) and child.value == "WORKFLOW_STATE_TEST_CLOCK":
                    found.append(("override", owner))
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and (child.func.value.id, child.func.attr) in self.CLOCK_CALLS):
                    found.append(("clock", owner))
                visit(child, inner)

        visit(ast.parse(path.read_text(encoding="utf-8")), None)
        return found

    def test_only_ledger_clock_reads_the_clock_or_the_override(self):
        scripts = SCRIPT.parent
        self.assertEqual(set(self.sites(SCRIPT)),
                         {("override", "ledger_clock"), ("clock", "ledger_clock")})
        others = [*sorted(scripts.glob("workflow_delivery*.py")),
                  *sorted((scripts / "delivery_model").glob("*.py"))]
        self.assertTrue(others)
        for path in others:
            with self.subTest(path=path.name):
                self.assertEqual(self.sites(path), [])
```

In `test_delivery_workflow.py`, add these imports: `from datetime import datetime, timedelta, timezone` and `from .test_workflow_state import LifecycleHarness`. Add these module constants after `SLUGLESS`:

```python
CLOCK_ENV = "WORKFLOW_STATE_TEST_CLOCK"
PINNED = "2026-09-30T12:00:00Z"
SKEW = ("workflow-state: {label} {supplied} is {lead} seconds ahead of the clock {clock}; "
        "a supplied time may lead it by at most 60 seconds — omit it to use the clock\n")
PROGRESS_ARGS = ("--issue", 14, "--attempt", 1, "--phase", 1, "--turn-count", 10,
                 "--context-tokens", 20000, "--turn-ceiling", 120, "--context-ceiling", 150000,
                 "--turn-headroom", 2, "--context-headroom", 10000,
                 "--next-needs-context", "true", "--artifacts-sufficient", "false",
                 "--remainder-self-contained", "false")
```

Then append the class:

```python
class LedgerClockTest(LifecycleHarness, unittest.TestCase):
    """#309: ledger time comes from the clock; a future supplied time is refused (D3–D8)."""

    def setUp(self):
        super().setUp()
        self.cli_env.pop(CLOCK_ENV, None)

    @property
    def run_args(self):
        return ("--repo-root", self.root, "--run-id", self.run_id)

    def pin(self, value=PINNED):
        self.cli_env[CLOCK_ENV] = value

    @staticmethod
    def at(base, seconds):
        moved = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(seconds=seconds)
        return moved.isoformat().replace("+00:00", "Z")

    @staticmethod
    def clock_text():
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def assert_clock_stamp(self, stamp):
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        recorded = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        self.assertLessEqual(abs((datetime.now(timezone.utc) - recorded).total_seconds()), 5,
                             stamp)

    def worktree(self, issue):
        return str(self.root / f"wt-{issue}")

    def spawn_two(self, now):
        """One control sweep at `now` spawning issues 14 and 15; their spawn actions by issue."""
        response = self.control_validated(
            now=now, issues=[14, 15],
            tracker=[self.tracker_fact(14), self.tracker_fact(15)],
            worktrees=[self.worktree_fact(issue, candidate={
                "path": self.worktree(issue), "state": "absent"}) for issue in (14, 15)],
            max_parallel=100)
        return {action["issue"]: action for action in response["actions"]
                if action["kind"] == "spawn"}

    def test_a_supplied_time_over_the_bound_is_refused_and_writes_nothing(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        self.spawn_two(PINNED)
        worker = json.loads(self.run_cli("register-worker", *self.run_args,
                                         "--action-id", "14:1:1").stdout)["worker_id"]
        ahead = self.at(PINNED, 900)
        never_read = self.root / "never-read.json"
        before = self.state_path.read_bytes()
        for name, args in (
                ("checkpoint-delivery", ("checkpoint-delivery", *self.run_args, "--now", ahead,
                                         "--checkpoint-file", never_read)),
                ("release-worker", ("release-worker", *self.run_args, "--now", ahead,
                                    "--worker-id", worker, "--event", "returned")),
                ("finish", ("finish", *self.run_args, "--now", ahead,
                            "--summary-file", never_read))):
            with self.subTest(command=name):
                refused = self.run_cli(*args, ok=False)
                self.assertEqual(
                    (refused.returncode, refused.stdout, refused.stderr),
                    (2, "", SKEW.format(label="--now", supplied=ahead, lead=900, clock=PINNED)))
                self.assertEqual(self.state_path.read_bytes(), before)
        at_bound = self.at(PINNED, 60)
        released = json.loads(self.run_cli("release-worker", *self.run_args, "--now", at_bound,
                                           "--worker-id", worker, "--event", "returned").stdout)
        self.assertEqual(released["released"], [worker])
        self.assertEqual(self.read_state()["updated_at"], at_bound)

    def test_every_flag_command_without_a_time_stamps_the_clock(self):
        self.run_cli("init-run", *self.run_args)
        self.assert_clock_stamp(self.read_state()["updated_at"])
        spawned = self.spawn_two(self.clock_text())
        custody, digest = spawned[14]["custody"], spawned[14]["contract_digest"]
        worker = json.loads(self.run_cli("register-worker", *self.run_args,
                                         "--action-id", "14:1:1").stdout)["worker_id"]
        self.assert_clock_stamp(self.read_state()["updated_at"])
        self.run_cli("release-worker", *self.run_args, "--worker-id", worker,
                     "--event", "returned")
        self.assert_clock_stamp(self.read_state()["updated_at"])
        self.init_worktree(self.worktree(14), branch="issue-14-ledger-clock")
        marked = json.loads(self.run_cli("mark-progress", *self.run_args,
                                         "--action-id", "14:1:1").stdout)
        self.assertEqual(marked["outcome"], "baseline")
        self.assert_clock_stamp(self.read_state()["updated_at"])
        self.run_cli("progress", *self.run_args, *PROGRESS_ARGS)
        self.assert_clock_stamp(
            self.read_state()["issues"]["14"]["attempts"][0]["last_progress_at"])
        report = {"interface_version": 2, "issue": 14, "custody": custody,
                  "contract_digest": digest, "delivery_observations": [],
                  "authority_observations": [], "reevaluation_evidence": [],
                  "requested_scope": None, "detail_state": "none", "report_path": None,
                  "notes": ""}
        checkpoint = self.root / "checkpoint.json"
        checkpoint.write_text(json.dumps(report), encoding="utf-8")
        self.run_cli("checkpoint-delivery", *self.run_args, "--checkpoint-file", checkpoint)
        self.assert_clock_stamp(self.read_state()["updated_at"])
        historical = {"issue": 14, "state": "failed", "pr_url": None, "merge_sha": None,
                      "issue_closed": False, "discussion_items": [], "detail_state": "none",
                      "report_path": None, "notes": "failed"}
        summary = {"interface_version": 2, "issue": 14, "state": "terminal_failed",
                   "custody": custody, "historical_owner_result": historical,
                   "delivery_contract_digest": digest, "delivery_observations": [],
                   "authority_observations": [], "reevaluation_evidence": [],
                   "detail_state": "none", "report_path": None, "notes": "failed"}
        summary_path = self.root / "summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        self.run_cli("finish", *self.run_args, "--summary-file", summary_path)
        self.assert_clock_stamp(self.read_state()["updated_at"])
        self.run_cli("suspend", *self.run_args, "--issue", 15, "--attempt", 1,
                     "--blocked-on", "usage_limit")
        self.assert_clock_stamp(self.read_state()["updated_at"])

    def test_a_backward_refusal_names_the_wait(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        self.spawn_two(PINNED)
        worker = json.loads(self.run_cli("register-worker", *self.run_args,
                                         "--action-id", "14:1:1").stdout)["worker_id"]
        earlier = self.at(PINNED, -37)
        before = self.state_path.read_bytes()
        for name, args, expected in (
                ("release-worker",
                 ("release-worker", *self.run_args, "--now", earlier, "--worker-id", worker,
                  "--event", "returned"),
                 f"workflow-state: release-worker time must not move backward: {earlier} is "
                 f"before the run updated_at {PINNED}; it would succeed in 37 seconds\n"),
                ("progress",
                 ("progress", *self.run_args, "--now", earlier, *PROGRESS_ARGS),
                 f"workflow-state: progress time must not move backward: {earlier} is "
                 f"before the attempt last_progress_at {PINNED}; it would succeed in "
                 f"37 seconds\n")):
            with self.subTest(command=name):
                refused = self.run_cli(*args, ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, "", expected))
                self.assertEqual(self.state_path.read_bytes(), before)
```

The assertions are the contract. If fixture plumbing needs a small change to reach the asserted behavior, the implementer may make it, for example a different but valid `--blocked-on` value. The refusal texts, the byte-equality checks and the 5-second bound may not change.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py -k LedgerClock`
Expected: FAIL. argparse refuses each omitted `--now` ("the following arguments are required: --now"). The override tests succeed instead of being refused. The skew and backward texts differ, and the scan finds no `ledger_clock`.

- [ ] **Step 3: Implement**

In `workflow-state.py`:

1. Add `import math`. After `format_utc`, add the seam and helpers. The bodies are fixed, because the scan and the exact texts depend on them:

```python
SUPPLIED_TIME_MAX_LEAD_SECONDS = 60


def ledger_clock() -> datetime:
    """The one place workflow-state reads the time (#309 D1, D2, D11).

    The system clock in UTC, truncated to whole seconds. A non-empty
    WORKFLOW_STATE_TEST_CLOCK pins the value for tests. It must parse and must
    not be later than the system clock, so it can pin only the present or past.
    """
    clock = datetime.now(timezone.utc).replace(microsecond=0)
    pinned = os.environ.get("WORKFLOW_STATE_TEST_CLOCK", "")
    if not pinned:
        return clock
    value = parse_utc(pinned, "WORKFLOW_STATE_TEST_CLOCK").replace(microsecond=0)
    if value > clock:
        raise WorkflowError(
            f"invalid WORKFLOW_STATE_TEST_CLOCK: {format_utc(value)} is later than "
            f"the clock {format_utc(clock)}")
    return value


def supplied_time(value: str | None, label: str) -> datetime | None:
    """A caller-supplied time, refused when it leads the clock by more than 60 s (#309 D6).

    ``None`` when the caller omitted it. The command then reads the clock
    under its ledger lock (D7). A past time of any age is accepted.
    """
    if value is None:
        return None
    parsed = parse_utc(value, label)
    clock = ledger_clock()
    lead = math.ceil((parsed - clock).total_seconds())
    if lead > SUPPLIED_TIME_MAX_LEAD_SECONDS:
        raise WorkflowError(
            f"{label} {format_utc(parsed)} is {lead} seconds ahead of the clock "
            f"{format_utc(clock)}; a supplied time may lead it by at most "
            f"{SUPPLIED_TIME_MAX_LEAD_SECONDS} seconds — omit it to use the clock")
    return parsed


def ledger_time(supplied: datetime | None) -> datetime:
    """The time a write records: the supplied one, else the clock read now (#309 D7).

    Call it under the ledger lock, as the mutation's first statement.
    """
    return ledger_clock() if supplied is None else supplied


def backward_refusal(prefix: str, now: datetime, field: str, stored: str) -> WorkflowError:
    """``prefix``, the stored time, and the whole seconds until the write would succeed (#309 D8)."""
    wait = math.ceil((parse_utc(stored, field) - now).total_seconds())
    return WorkflowError(f"{prefix}: {format_utc(now)} is before the {field} {stored}; "
                         f"it would succeed in {wait} seconds")
```

2. In `add_run_arguments`, change `--now` to `command.add_argument("--now", default=None, help="omit to use the clock; a supplied time may lead it by at most 60 seconds")`.

3. Apply the same pattern to `command_init_run`, `command_progress`, `command_suspend`, `command_finish` (the legacy branch), `command_finish_delivery`, `command_checkpoint_delivery`, `command_register_worker`, `command_mark_progress` and `command_release_worker`:
   - Replace the existing `parse_utc(args.now, "--now")` / `format_utc(...)` lines with `supplied = supplied_time(args.now, "--now")`, on the same line position. In `checkpoint-delivery` and `finish-delivery`, that line stays above the input-file read.
   - Make the mutation's first statements `now_value = ledger_time(supplied)` and `now = format_utc(now_value)`. In `checkpoint-delivery`, turn the `lambda` into a named inner function so that it can do this before calling `runtime.checkpoint_state`. In `init-run`, read the time inside `initialize` only on the branch that creates the state.
   - Check by reading each function that no statement outside the mutation reads `now` or `now_value`.

4. Replace the six flag-command `raise WorkflowError("… time must not move backward")` lines with `raise backward_refusal(<the same prefix string>, now_value, <field>, <stored>)`:
   - `progress`, `suspend` and the legacy `finish`: field `"attempt last_progress_at"`, stored `attempt["last_progress_at"]`.
   - `register-worker`, `release-worker` and `mark-progress` (prefix `"mark-progress refused: time must not move backward"`): field `"run updated_at"`, stored `state["updated_at"]`.

   Leave `control` and `direct-owner` to Task 2.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_admission_replay.py home/common/agent-skills/tests/test_host_admission.py 2>&1 | tail -5` (timeout 1200 s)
Expected: `OK`. The new `LedgerClock*` tests pass, and the existing suites, which supply past times, pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(workflow-state): stamp flag commands from one ledger clock (#309)"
```
