# Task 3: The read-only `owner-liveness` verb

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new `OwnerLivenessTest`)
- Test: `home/common/agent-skills/tests/test_delivered_control.py` (new `OwnerLivenessRemainderTest`)

**Interfaces:**
- Consumes: Task 2's boundary support for the `owner_liveness` reply (the tests validate every reply through `artifact-budget validate-report --boundary workflow-response`).
- Consumes, already in `workflow-state.py`: `ledger_clock()`, `supplied_time()`, `parse_utc()`, `format_utc()`, `launch_verdict()`, `read_state_unlocked()`, `require_regular_path()`, `resolve_repo_root()`, `parse_action_id()`, `RUN_ID_PATTERN`, `print_json()`.
- Produces, the CLI: `workflow-state owner-liveness --repo-root <root> --run-id <run-id> --action-id <action_id> --stall-minutes <N> [--since <UTC>]`, printing one reply line at exit 0. Task 5's skill and Task 6's replay call it.
- Produces, in `workflow-state.py`:
  - `supplied_time(value: str | None, label: str, *, clock: datetime | None = None) -> datetime | None`. With `clock` given it skew-checks against that value and does not call `ledger_clock()`. Without it, behavior is unchanged (D11).
  - `launch_progress_at(record: dict, workers: list[dict], action_id: str) -> datetime`.
  - `owner_liveness_reply(state: dict | None, action_id: str, reason: str, *, stall_minutes: int, since: datetime, clock: datetime) -> dict`.
  - `command_owner_liveness(args) -> int`.

**Invariants:**
- Read-only: no `transact`, no `workflow_paths`, no lock, no write. The ledger file's bytes and the set of paths under the repo root are identical before and after every call, refused or not (D2).
- The clock is read exactly once per call, through `ledger_clock()`. A supplied `--since` is skew-checked against that same reading (D2, D11).
- Argument checks, each `WorkflowError` → exit 2, empty stdout, one stderr line: `RUN_ID_PATTERN` (`invalid run_id`); `parse_action_id` (`invalid action_id`); `--stall-minutes` must fullmatch `[1-9][0-9]{0,8}` (`invalid --stall-minutes: expected a positive integer`); `--since`, when given, must fullmatch `\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ` and parse (`invalid --since: expected an RFC3339 UTC timestamp`), and must lead the clock by at most 60 seconds (#309's skew line with label `--since`) (D4, D11).
- `since` is the supplied value, else the clock. The reply echoes it in canonical form (D4).
- The launch verdict comes from `launch_verdict(runtime, state, action_id)`, with `state` `None` for a missing ledger, exactly as `check-launch` reads it (`unknown_run`). An unreadable or invalid ledger exits 2.
- For `reason == "current"`, the record is `issues[<issue>]["delivery_remainders"][-1]` for an action id containing `:r`, else `issues[<issue>]["attempts"][-1]`. `progress_at` is the latest of: the record's `last_progress_at` when present and not null (remainders have none); `record["launches"][-1]["at"]`; and every non-null `registered_at` and `released_at` of a worker in `state.get("workers", [])` whose `launch` equals the action id. Nothing else counts (D3).
- `stall_at = max(progress_at, since) + stall_minutes minutes`. Verdict: `past_deadline` when `clock >= record["deadline_at"]` (checked first, D10); else `live` when `clock < stall_at`, with `wait_seconds = math.ceil((stall_at - clock).total_seconds())`, which is at least 1; else `stalled`. Stored ledger times may carry fractional seconds (a supplied `--now` on `progress`, `register-worker` or `release-worker` is kept as given), so every stored time that feeds `progress_at` is truncated to whole seconds (`.replace(microsecond=0)`, the same truncation `ledger_clock()` applies) before the comparison; `since` and the clock are already whole seconds, so `progress_at`, `stall_at` and `wait_seconds` are whole seconds and the reply always passes the boundary's whole-second check. The ledger's stored bytes are never rewritten (Phase-5 PR310-01, D14).
- For any other reason: `verdict` `not_current`, and `progress_at`, `stall_at` and `wait_seconds` are `null`.
- The reply is printed with `print_json` (sorted keys, compact) and passes the workflow-response boundary unchanged. The verb does not run that validator itself (D11).

- [ ] **Step 1: Write the failing tests**

Append to `test_workflow_state.py` (it already imports `json`, `os`, `subprocess`, `sys`, `ARTIFACT_BUDGET`, `BUDGET_POLICY` and `DEFAULT_NOW = "2026-08-13T20:00:00Z"`):

```python
class OwnerLivenessTest(LifecycleHarness, unittest.TestCase):
    """#310 D2-D5, D10, D11: workflow-state owner-liveness."""

    SKEW = ("workflow-state: --since {s} is {n} seconds ahead of the clock {c}; a supplied "
            "time may lead it by at most 60 seconds — omit it to use the clock\n")

    def setUp(self):
        super().setUp()
        self.init_run()
        self.worktrees = {n: str(self.root / f"wt-{n}") for n in (14, 16)}
        response = self.control(
            now=DEFAULT_NOW, issues=[14, 16], max_parallel=2, attempt_budget_minutes=180,
            tracker=[self.tracker_fact(n) for n in (14, 16)],
            worktrees=[self.worktree_fact(n, candidate={"path": self.worktrees[n],
                                                         "state": "absent"})
                       for n in (14, 16)])
        self.assertEqual([a["id"] for a in response["actions"] if a["kind"] == "spawn"],
                         ["14:1:1", "16:1:1"])

    def inventory(self):
        return (self.state_path.read_bytes(),
                sorted(p.relative_to(self.root) for p in self.root.rglob("*")))

    def call(self, clock, *, action_id="14:1:1", stall="30", since=None, run_id=None):
        # The pinned clock is scoped to this one call, so later ledger writes in
        # the same test are skew-checked against the real clock (PR310-02).
        previous = self.cli_env.get("WORKFLOW_STATE_TEST_CLOCK")
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = clock
        args = ["owner-liveness", "--repo-root", self.root,
                "--run-id", self.run_id if run_id is None else run_id,
                "--action-id", action_id, "--stall-minutes", stall]
        if since is not None:
            args += ["--since", since]
        try:
            before = self.inventory()
            completed = self.run_cli(*args, ok=False)
            self.assertEqual(self.inventory(), before)
        finally:
            if previous is None:
                self.cli_env.pop("WORKFLOW_STATE_TEST_CLOCK", None)
            else:
                self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = previous
        return completed

    def liveness(self, clock, **kwargs):
        completed = self.call(clock, **kwargs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return self.validated_response(completed.stdout)

    def reply(self, verdict, since, progress_at, stall_at, wait, *, action_id="14:1:1",
              reason="current"):
        return {"interface_version": 1, "kind": "owner_liveness", "action_id": action_id,
                "reason": reason, "verdict": verdict, "since": since,
                "progress_at": progress_at, "stall_at": stall_at, "wait_seconds": wait}

    def assert_refused(self, completed, stderr):
        self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                         (2, "", stderr))

    def test_live_names_the_seconds_left_from_the_clock(self):
        self.assertEqual(self.liveness("2026-08-13T20:10:07Z"), self.reply(
            "live", "2026-08-13T20:10:07Z", "2026-08-13T20:00:00Z",
            "2026-08-13T20:40:07Z", 1800))
        # A since ahead of the clock (within the skew) lengthens the wait past the bound.
        self.assertEqual(
            self.liveness("2026-08-13T20:10:07Z", since="2026-08-13T20:10:37Z"),
            self.reply("live", "2026-08-13T20:10:37Z", "2026-08-13T20:00:00Z",
                       "2026-08-13T20:40:37Z", 1830))

    def test_stalled_exactly_at_stall_at(self):
        since = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness("2026-08-13T20:39:59Z", since=since), self.reply(
            "live", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", 1))
        self.assertEqual(self.liveness("2026-08-13T20:40:00Z", since=since), self.reply(
            "stalled", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", None))

    def test_past_deadline_wins_over_stalled(self):
        since = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness("2026-08-13T22:59:59Z", since=since)["verdict"],
                         "stalled")
        self.assertEqual(self.liveness("2026-08-13T23:00:00Z", since=since), self.reply(
            "past_deadline", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", None))

    def test_a_since_later_than_progress_moves_stall_at(self):
        self.assertEqual(
            self.liveness("2026-08-13T20:30:00Z", since="2026-08-13T20:20:00Z")["stall_at"],
            "2026-08-13T20:50:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:30:00Z")["stall_at"],
                         "2026-08-13T21:00:00Z")

    def test_only_this_launchs_workers_move_progress(self):
        worker = self.register_worker(action_id="14:1:1", now="2026-08-13T20:20:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:21:00Z", since=DEFAULT_NOW)
                         ["progress_at"], "2026-08-13T20:20:00Z")
        self.release_worker(worker_id=worker["worker_id"], event="returned",
                            now="2026-08-13T20:25:00Z")
        self.register_worker(action_id="16:1:1", now="2026-08-13T20:30:00Z")
        ours = self.liveness("2026-08-13T20:31:00Z", since=DEFAULT_NOW)
        self.assertEqual((ours["progress_at"], ours["stall_at"]),
                         ("2026-08-13T20:25:00Z", "2026-08-13T20:55:00Z"))
        theirs = self.liveness("2026-08-13T20:31:00Z", action_id="16:1:1", since=DEFAULT_NOW)
        self.assertEqual(theirs["progress_at"], "2026-08-13T20:30:00Z")

    def test_fractional_stored_progress_is_truncated_and_never_rewritten(self):
        # PR310-01: a supplied fractional --now is stored as given; the reply
        # truncates it to whole seconds and passes the boundary unchanged.
        self.progress(issue=14, phase=1, now="2026-08-13T20:15:00.750000Z")
        stored = self.state_path.read_bytes()
        reply = self.liveness("2026-08-13T20:16:00Z", since=DEFAULT_NOW)
        self.assertEqual((reply["progress_at"], reply["stall_at"], reply["wait_seconds"]),
                         ("2026-08-13T20:15:00Z", "2026-08-13T20:45:00Z", 1740))
        self.assertEqual(self.state_path.read_bytes(), stored)

    def test_recorded_progress_moves_progress(self):
        self.progress(issue=14, phase=1, now="2026-08-13T20:15:00Z")
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][-1]["last_progress_at"],
                         "2026-08-13T20:15:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:16:00Z", since=DEFAULT_NOW)
                         ["progress_at"], "2026-08-13T20:15:00Z")

    def test_a_launch_that_is_not_current_is_not_current(self):
        self.assertEqual(
            self.liveness("2026-08-13T20:10:00Z", run_id="no-such-run"),
            self.reply("not_current", "2026-08-13T20:10:00Z", None, None, None,
                       reason="unknown_run"))
        self.suspend(issue=14, attempt=1, blocked_on="transport", now="2026-08-13T20:05:00Z")
        self.resume(issue=14, worktree=self.worktrees[14], now="2026-08-13T20:06:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:10:00Z")["reason"], "superseded_launch")
        self.assertEqual(self.liveness("2026-08-13T20:10:00Z")["verdict"], "not_current")
        resumed = self.liveness("2026-08-13T20:10:00Z", action_id="14:1:2")
        self.assertEqual((resumed["verdict"], resumed["progress_at"]),
                         ("live", "2026-08-13T20:06:00Z"))

    def test_malformed_arguments_are_refused_without_a_write(self):
        clock = "2026-08-13T20:10:00Z"
        for stall in ("0", "-1", "01", "1.5", "abc", "", "1234567890"):
            with self.subTest(stall=stall):
                self.assert_refused(self.call(clock, stall=stall), "workflow-state: invalid "
                                    "--stall-minutes: expected a positive integer\n")
        for since in ("yesterday", "2026-08-13T20:10:00.5Z", "2026-08-13T20:10:00+00:00"):
            with self.subTest(since=since):
                self.assert_refused(self.call(clock, since=since), "workflow-state: invalid "
                                    "--since: expected an RFC3339 UTC timestamp\n")
        self.assert_refused(self.call(clock, action_id="14:1"),
                            "workflow-state: invalid action_id\n")
        self.assert_refused(self.call(clock, run_id="bad/run"),
                            "workflow-state: invalid run_id\n")

    def test_a_since_over_the_skew_bound_is_refused(self):
        clock = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness(clock, since="2026-08-13T20:11:00Z")["since"],
                         "2026-08-13T20:11:00Z")
        self.assert_refused(self.call(clock, since="2026-08-13T20:11:01Z"), self.SKEW.format(
            s="2026-08-13T20:11:01Z", n=61, c=clock))

    def test_the_boundary_refuses_a_mutated_reply(self):
        live = self.liveness("2026-08-13T20:10:00Z")
        stalled = self.liveness("2026-08-13T20:40:00Z", since="2026-08-13T20:10:00Z")
        for name, value in (("stall_at_off_minute", {**live, "stall_at": "2026-08-13T20:40:30Z"}),
                            ("wait_on_stalled", {**stalled, "wait_seconds": 60})):
            with self.subTest(name=name):
                checked = subprocess.run(
                    [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                     "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
                    input=json.dumps(value), capture_output=True, text=True, check=False,
                    env=self.cli_env)
                self.assertEqual(checked.returncode, 2)
```

The harness helpers used above (`init_run`, `control`, `tracker_fact`, `worktree_fact`, `register_worker`, `release_worker`, `progress`, `suspend`, `resume`, `read_state`, `validated_response`, `run_cli`, `state_path`) all exist in `LifecycleHarness`. `register_worker` returns the parsed reply, whose `worker_id` is `14:1:1:w1`.

Append to `test_delivered_control.py` (add `from unittest import mock` to its imports):

```python
class OwnerLivenessRemainderTest(DeliveredControlHarness, unittest.TestCase):
    """#310 D3, D12: owner-liveness serves a delivery-remainder launch."""

    def liveness(self, minute, action_id, since=None):
        argv = ["owner-liveness", *self.run_args, "--action-id", action_id,
                "--stall-minutes", "90"]
        if since is not None:
            argv += ["--since", since]
        before = self.ledger.read_bytes()
        with mock.patch.dict(os.environ, {"WORKFLOW_STATE_TEST_CLOCK": at(minute)}):
            completed = self.cli(*argv)
        self.assertEqual(self.ledger.read_bytes(), before)
        return json.loads(self.validated("workflow-response", completed.stdout))

    def test_a_remainder_launch_is_measured_from_its_own_launch(self):
        self.setup_run()
        spawned = self.control(0, recorded={DELIVERED: None}, contracts=True)
        launched = [a["custody"] for a in spawned["actions"] if a["kind"] in DISPATCH]
        for minute in (31, 62, 93):
            response = self.control(minute, recorded={DELIVERED: "matching_issue_branch"})
            launched = [a["custody"] for a in response["actions"] if a["kind"] in DISPATCH]
        remainder = self.fail_after_selection(launched[0], at(94))
        action_id = remainder["custody"]["action_id"]
        self.assertEqual(action_id, f"{DELIVERED}:r1:1")
        self.assertEqual(self.liveness(100, action_id), {
            "interface_version": 1, "kind": "owner_liveness", "action_id": action_id,
            "reason": "current", "verdict": "live", "since": at(100),
            "progress_at": at(94), "stall_at": at(190), "wait_seconds": 5400})
        self.assertEqual(self.liveness(190, action_id, since=at(100))["verdict"], "stalled")
        self.assertEqual(self.liveness(274, action_id, since=at(100))["verdict"],
                         "past_deadline")
        self.assertEqual(self.liveness(100, launched[0]["action_id"])["verdict"],
                         "not_current")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k OwnerLiveness`
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py -k OwnerLivenessRemainder`
Expected: FAIL. argparse rejects `owner-liveness` as an invalid choice (exit 2, usage on stderr).

- [ ] **Step 3: Write the minimal implementation**

In `workflow-state.py`:
- Give `supplied_time` the keyword-only `clock` parameter: `clock = ledger_clock() if clock is None else clock` replaces the unconditional read. Every existing caller is unchanged.
- Add `launch_progress_at` and `owner_liveness_reply` as pure functions with the contracts in Invariants. `owner_liveness_reply` builds every reply member, formats times with `format_utc`, and reads `record["deadline_at"]` and record times with `parse_utc`. Read optional members with `.get`, because `read_state_unlocked` returns an older schema's document as stored (as `command_resume_pack` notes).
- Add `command_owner_liveness(args)` in this order: run-id check, `parse_action_id`, the `--stall-minutes` pattern, the `--since` pattern (when given), `clock = ledger_clock()`, `since = supplied_time(args.since, "--since", clock=clock)` or `clock` when omitted, resolve the repo root and read the state exactly as `command_check_launch` does, `launch_verdict`, then `print_json(owner_liveness_reply(…))` and return 0.
- Register the subparser after `current-launch`:

```python
    owner_liveness = subparsers.add_parser("owner-liveness", description=(
        "Answer whether one owner launch has recorded ledger progress within "
        "--stall-minutes, measured from the later of its last progress and --since "
        "(default: the clock). It takes no lock and writes nothing. It is the one "
        "read-only command that reads the clock, once; a supplied --since may lead "
        "it by at most 60 seconds."))
    owner_liveness.add_argument("--repo-root", required=True)
    owner_liveness.add_argument("--run-id", required=True)
    owner_liveness.add_argument("--action-id", required=True)
    owner_liveness.add_argument("--stall-minutes", required=True)
    owner_liveness.add_argument("--since", default=None)
    owner_liveness.set_defaults(handler=command_owner_liveness)
```

`--stall-minutes` deliberately has no argparse `type`, so a bad value gets one stderr line (D11).

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k OwnerLiveness -k LedgerClockSeam -k CheckLaunch`
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py`
Expected: PASS. `LedgerClockSeamTest`'s source scan still finds the clock call and the override only in `ledger_clock`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_delivered_control.py
git commit -m "feat(workflow-state): read-only owner-liveness verb (#310)"
```
