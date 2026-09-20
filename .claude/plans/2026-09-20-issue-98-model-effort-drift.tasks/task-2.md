# Task 2: Add independent scheduling metrics and producer regression gates

**Files:**
- Modify: `scripts/agent-costs.py`
- Modify: `tests/test_agent_costs.py`

**Risk lane:** full — public scheduling schema, coverage/null semantics, and cohort compatibility.

**Interfaces:**
- Consumes: Task 1's `collect_execution_telemetry`, `coverage`, exact event window, transient dedup identities, and emitted run ids.
- Produces:
  - `SCHEDULING_METRICS = ("spawn_attempts", "capacity_rejections", "waits", "follow_ups", "wait_input_tokens", "covered_input_tokens", "slot_capacity_seconds", "claimed_slot_seconds")`.
  - Every run's `scheduling` is an object with exactly those keys. Every value is `{"value": int | None, "coverage": <coverage>, "cohort_digest": str | None}`.
  - Top-level `source_coverage.scheduling` has exactly the same metric keys and each value is the aggregate coverage object for that metric.
  - `def cohort_digest(identities: list[tuple[str, ...]]) -> str` — a `sha256:` digest over sorted canonical JSON identities, retained only long enough to compute the digest.
  - `def merge_metric_coverage(metrics: list[dict]) -> dict` — combines eligible/paired/reasons; any selected source/run with unavailable coverage prevents `full` and therefore projects the aggregate value as `null`.

**Invariants:**
- `spawn_attempts` is the only presently supported historical scheduling metric. In a bounded Claude cohort it counts deduplicated structured `Agent`/`Task` tool uses whose timestamps are inside the window. Complete timestamp coverage proves zero; missing timestamps make the value `null`, never zero.
- Codex and every other scheduling metric currently emit `source_unsupported`, `state: none`, `value: null`, and `cohort_digest: null`. No filename, token aggregate, cache-read counter, final message, or fixture supplies production scheduling evidence (D5).
- `wait_input_tokens` and `covered_input_tokens` may become numeric only together, with `full` coverage and the same non-null cohort digest. `slot_capacity_seconds` and `claimed_slot_seconds` may become numeric only together, with `full` coverage and a cohort digest equal to `canonical_digest(event_window)`; `claimed_slot_seconds <= slot_capacity_seconds`.
- A metric with `partial` or `none` always has `value: null`. A numeric value is a non-boolean integer `>= 0`; synthetic fixture values exercise projection rules but make no production-source claim.
- Routing coverage and state inputs are not changed by scheduling. Scheduling never adds a routing finding or edits a routing observation (D5).
- The producer emits no scheduling conclusion, ratio, or words/keys `waste`, `cheap`, `useful`, `savings`, `billing`, or `utilization` inside `execution_telemetry` (D5).
- The bounded event range used by all scheduling metrics is byte-identical to the routing `event_window`; there is no second scheduling range.

- [ ] **Step 1: Write the failing scheduling tests**

Add this class after Task 1's routing class. It reuses `ExecutionTelemetryRoutingTest.claude_pair` only as a fixture builder; every assertion stays at the `main(argv)` JSON seam.

```python
class ExecutionTelemetrySchedulingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_record(self, *, bounded=True):
        args = ["--projects-dir", str(self.root), "--days", "0", "--format", "json"]
        if bounded:
            args += ["--events-since", "2026-09-20T10:00:00Z",
                     "--events-before", "2026-09-20T11:00:00Z"]
        raw, code = run_main(*args)
        self.assertIsNone(code)
        return json.loads(raw)

    def write_root(self, *lines):
        project = self.root / "-Users-me-repo-issue-120-x"
        project.mkdir(parents=True, exist_ok=True)
        (project / "s1.jsonl").write_text("".join(lines), encoding="utf-8")

    def test_complete_bounded_source_distinguishes_measured_zero_from_null(self):
        self.write_root(assistant(
            "ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z",
            version="2.1.0", stop_reason="end_turn"))
        telemetry = self.run_record()["execution_telemetry"]
        scheduling = telemetry["runs"][0]["scheduling"]
        self.assertEqual(tuple(scheduling), agent_costs.SCHEDULING_METRICS)
        self.assertEqual(scheduling["spawn_attempts"], {
            "value": 0,
            "coverage": {"state": "full", "eligible_events": 0,
                         "paired_events": 0, "reasons": []},
            "cohort_digest": agent_costs.cohort_digest([]),
        })
        for name in agent_costs.SCHEDULING_METRICS[1:]:
            self.assertIsNone(scheduling[name]["value"], name)
            self.assertEqual(scheduling[name]["coverage"]["state"], "none", name)
            self.assertIn({"code": "source_unsupported", "count": 1},
                          scheduling[name]["coverage"]["reasons"], name)
            self.assertIsNone(scheduling[name]["cohort_digest"], name)
        self.assertEqual(telemetry["source_coverage"]["scheduling"]
                         ["spawn_attempts"], scheduling["spawn_attempts"]["coverage"])

    def test_spawn_attempts_are_event_time_selected_and_tool_id_deduped(self):
        launch = {"type": "tool_use", "id": "toolu-spawn", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "prompt": "review"}}
        outside = {"type": "tool_use", "id": "toolu-outside", "name": "Agent",
                   "input": {"subagent_type": "reviewer", "prompt": "old"}}
        self.write_root(
            assistant("outside", usage=USAGE_1, content=[outside],
                      timestamp="2026-09-20T09:59:59Z", version="2.1.0"),
            assistant("inside", usage=USAGE_1, content=[launch],
                      timestamp="2026-09-20T10:05:00Z", version="2.1.0"),
            assistant("inside", usage=USAGE_1, content=[launch],
                      timestamp="2026-09-20T10:05:00Z", version="2.1.0"),
        )
        metric = self.run_record()["execution_telemetry"]["runs"][0]
        metric = metric["scheduling"]["spawn_attempts"]
        self.assertEqual(metric["value"], 1)
        self.assertEqual(metric["coverage"]["state"], "full")
        self.assertEqual(metric["coverage"]["eligible_events"], 1)
        self.assertEqual(metric["coverage"]["paired_events"], 1)

    def test_missing_timestamp_and_unbounded_cohort_do_not_project_a_zero(self):
        launch = {"type": "tool_use", "id": "toolu-no-time", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "prompt": "review"}}
        self.write_root(assistant("launch", usage=USAGE_1, content=[launch],
                                  timestamp=None, version="2.1.0"))
        bounded = self.run_record()["execution_telemetry"]["runs"][0]
        bounded = bounded["scheduling"]["spawn_attempts"]
        self.assertIsNone(bounded["value"])
        self.assertIn({"code": "timestamp_missing", "count": 1},
                      bounded["coverage"]["reasons"])
        unbounded = self.run_record(bounded=False)["execution_telemetry"]["runs"][0]
        unbounded = unbounded["scheduling"]["spawn_attempts"]
        self.assertIsNone(unbounded["value"])
        self.assertIn({"code": "cohort_incomplete", "count": 1},
                      unbounded["coverage"]["reasons"])

    def test_telemetry_contains_no_scheduling_verdict_vocabulary(self):
        self.write_root(assistant(
            "ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z",
            version="2.1.0", stop_reason="end_turn"))
        telemetry = self.run_record()["execution_telemetry"]
        encoded = json.dumps(telemetry, sort_keys=True).lower()
        for forbidden in ("waste", "cheap", "useful", "savings", "billing", "utilization"):
            self.assertNotIn(forbidden, encoded)
```

- [ ] **Step 2: Run the scheduling class and watch it fail**

Run: `python3 -m unittest -v tests.test_agent_costs.ExecutionTelemetrySchedulingTest`

Expected: FAIL — Task 1 emits empty per-run scheduling objects and has no `SCHEDULING_METRICS` or `cohort_digest`.

- [ ] **Step 3: Implement scheduling collection and coverage**

Add the closed metric tuple and helpers above. During Task 1's telemetry scan, retain each in-window Claude launch tool id long enough to deduplicate and digest it. Project `spawn_attempts` only after every eligible launch has a valid timestamp and the event window is bounded; otherwise project null with the exact reason.

Create all other metric entries through one `unsupported_metric(reason_count=1)` constructor so null, coverage, and cohort behavior cannot drift by field. Validate the token-pair and slot-pair invariants in the producer projection function even though current sources cannot populate them; the validation raises `ValueError` on an internally inconsistent future collector rather than emitting a false metric.

Aggregate coverage by selected source and run. If `--strata both` selects Claude and Codex, Codex's unsupported spawn coverage prevents the fleet-level `spawn_attempts` from becoming full even when Claude is full; its aggregate value remains null.

- [ ] **Step 4: Run producer and full accounting verification**

Run: `python3 -m unittest -v tests/test_agent_costs.py`

Expected: PASS; scheduling tests distinguish zero from null and every pre-existing PR 156 accounting, attribution, digest, empty-window, and text-byte test remains green.

Run: `git diff --check "$DELIVERY_BASE" -- scripts/agent-costs.py tests/test_agent_costs.py`

Expected: exit `0`; the task owns no other path.

- [ ] **Step 5: Commit the producer-scheduling slice**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py
git commit -S -m "feat(telemetry): report scheduling coverage" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
