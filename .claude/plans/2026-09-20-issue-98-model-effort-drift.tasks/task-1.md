# Task 1: Emit event-time routing telemetry while preserving accounting

**Files:**
- Modify: `scripts/agent-costs.py`
- Modify: `tests/test_agent_costs.py`

**Risk lane:** full — public telemetry schema, event-time semantics, and transcript correlation.

**Interfaces:**
- Consumes: existing `main(argv, *, executor_factory)`, `find_sessions`, `scan_paths`, `build_groups`, `collect_codex_groups`, `build_record`, and canonical `run_id` projection.
- Produces:
  - `EXECUTION_TELEMETRY_SCHEMA_VERSION = 1`, `EXECUTION_TELEMETRY_PRODUCER_VERSION = 1`, `TELEMETRY_REASON_CODES: tuple[str, ...]` in the exact Global Constraints order, and `ROUTING_AUTHORITIES = ("assistant-execution", "codex-rollout")`.
  - `def parse_rfc3339_utc(value: str) -> datetime` — accepts an RFC 3339 instant with `Z` or an explicit offset, returns an aware UTC value, and raises `ValueError` for a naive/invalid value.
  - `def event_in_window(value: object, start: datetime | None, end: datetime | None) -> bool | None` — `True`/`False` for a parseable timestamp against `[start, end)`, `None` when the source timestamp is absent or invalid.
  - `def coverage(eligible: int, paired: int, reasons: Counter) -> dict` — returns exactly `state`, `eligible_events`, `paired_events`, `reasons`; reasons are sorted `{"code", "count"}` objects. `full` requires no reasons and may carry zero; `partial` requires at least one pair but incomplete evidence; otherwise `none`.
  - `def collect_execution_telemetry(selected: tuple[str, ...], claude_root: Path | None, codex_root: Path | None, start: datetime | None, end: datetime | None, project_filter: str | None, executor_factory) -> dict` — scans all source files independently of the accounting cutoff and returns the complete version-1 subdocument.
  - `build_record(groups_by_stratum, window, execution_telemetry=None)` — always adds `execution_telemetry` before computing `record_id`; `None` produces the deterministic unbounded/no-source subdocument used by direct projection tests.
  - JSON-only CLI options `--events-since` and `--events-before`; both or neither, with `start < end`.

The exact producer subdocument is:

```json
{
  "schema_version": 1,
  "producer": {
    "name": "agent-costs",
    "version": 1,
    "harness_versions": {"claude": ["2.1.0"], "codex": null}
  },
  "event_window": {"start": "2026-09-20T10:00:00Z", "end": "2026-09-20T11:00:00Z"},
  "source_coverage": {
    "routing": {"state": "full", "eligible_events": 1, "paired_events": 1, "reasons": []},
    "source_only": {}
  },
  "runs": [{
    "run_id": "claude:repo:120",
    "routing": {"coverage": {}, "observations": []},
    "scheduling": {}
  }]
}
```

Task 1 fills `routing`; Task 2 adds top-level `scheduling`, replaces every run's empty `scheduling` object with the complete closed metric map, and adds scheduling coverage inside any `source_only` entry. `source_only` is keyed by selected `claude`/`codex` sources whose coverage contribution has no run; in Task 1 each entry is exactly `{"routing": <coverage>, "scheduling": {}}`. Each routing observation has exactly the declaration/requested/configured/observed/escalation/count/first/last members shown in the design. Declaration authority is exactly `structured-dispatch | runtime-agent-type | unknown`; requested/configured always have exactly `host`, `model`, `effort`; observed also has `authority`. `escalation` is null or exactly `{"source_dispatch_id": str | null, "reason_code": str | null}` so missing lineage remains a semantic drift finding rather than a parser failure.

**Invariants:**
- The telemetry pass is independent of `--days`: it visits every `.jsonl` below each selected source root, then filters individual events on timestamps. It never feeds a result into the accounting accumulators (D2, D7).
- A Claude observation requires one deduplicated `Agent`/`Task` tool-use id, one matching `tool_result.tool_use_id` whose `toolUseResult.agentId` is non-empty, and one child transcript whose `agentId` agrees. Requested model/effort come only from that tool input. Requested host is the explicit input `host` when it is the string `claude`, otherwise the intrinsic `claude` target when the field is absent. A present null/non-string host yields null plus `request_host_missing`; a present different string yields null plus `request_host_conflict`. Observed values come only from the paired child assistant execution (D2).
- `subagent_type` becomes a role only when it is a canonical matrix role string; `general-purpose`, `reviewer`, and `mechanic` remain ambiguous unless the exact request carries a canonical `role`. `dispatch_id` is used only when the request carries it as a field; prompt text is never searched (D2, D6).
- Claude source `version` and Codex `session_meta.payload.cli_version` are collected into sorted unique arrays. A selected source with no version evidence gets `null` and `runtime_version_missing`; no file name or installed binary supplies a version.
- A recognized Codex `thread_spawn` has intrinsic requested host `codex` with the same absent/equal/missing/conflict rules. Codex `turn_context` populates configured values only. A selected rollout proves observed host `codex`; observed model/effort stay `null` with their missing reasons until a future execution source carries them. No request host is copied from rollout location, configured context, or observed host when the structured spawn is absent.
- Top-level routing coverage merges every run coverage with one `source_only` routing contribution for each selected source that emits no telemetry run. Reason counts combine exactly; a zero-run selected source is never dropped (D2, D5).
- Observations aggregate only identical semantic tuples; count and first/last event time are updated, then observations and runs are sorted by canonical JSON/run id. Raw correlation ids and paths never enter the result.
- An unbounded event window is `{start: null, end: null}` and adds `cohort_incomplete`; it can never have routing coverage `full`.
- Existing token/cost fields and text output are unchanged. The existing `record_id` changes only because its documented body now includes `execution_telemetry` (D1, D7).

- [ ] **Step 1: Write the failing producer tests**

Replace the existing `assistant` fixture with this version, then add the result helper and test class verbatim after `run_main`:

```python
def assistant(msg_id, usage=None, content=None, model="claude-opus-5",
              effort="xhigh", stop_reason="tool_use", cwd="/Users/me/repo",
              agent_id=None, attribution_skill=None, sidechain=False, *,
              timestamp=None, version=None):
    value = {
        "type": "assistant", "cwd": cwd, "effort": effort,
        "agentId": agent_id, "attributionSkill": attribution_skill,
        "isSidechain": sidechain,
        "message": {"id": msg_id, "model": model,
                    "stop_reason": stop_reason, "usage": usage,
                    "content": content or []},
    }
    if timestamp is not None:
        value["timestamp"] = timestamp
    if version is not None:
        value["version"] = version
    return record(value)


def agent_result(tool_id, agent_id, *, timestamp, status="completed"):
    return record({
        "type": "user",
        "timestamp": timestamp,
        "message": {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": tool_id, "content": "done",
        }]},
        "toolUseResult": {
            "agentId": agent_id, "agentType": "reviewer",
            "status": status, "content": "done",
        },
    })


class ExecutionTelemetryRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    REQUEST_HOST_ABSENT = object()

    def claude_pair(self, *, request_at="2026-09-20T10:05:00Z",
                    execution_at="2026-09-20T10:06:00Z",
                    request_host=REQUEST_HOST_ABSENT):
        project = self.root / "-Users-me-repo-issue-120-x"
        child_dir = project / "s1" / "subagents"
        child_dir.mkdir(parents=True)
        launch_input = {"subagent_type": "reviewer", "role": "reviewer",
                        "model": "opus", "effort": "high",
                        "prompt": "review the delivery"}
        if request_host is not self.REQUEST_HOST_ABSENT:
            launch_input["host"] = request_host
        launch = {"type": "tool_use", "id": "toolu-route-1", "name": "Agent",
                  "input": launch_input}
        root_file = project / "s1.jsonl"
        root_file.write_text(
            assistant("launch", usage=USAGE_1, content=[launch],
                      timestamp=request_at, version="2.1.0")
            + agent_result("toolu-route-1", "agent-child-1",
                           timestamp="2026-09-20T10:05:30Z"),
            encoding="utf-8",
        )
        (child_dir / "child.jsonl").write_text(
            assistant("child-turn", usage=USAGE_2, model="claude-opus-5-20260901",
                      effort="high", agent_id="agent-child-1", sidechain=True,
                      timestamp=execution_at, version="2.1.0"),
            encoding="utf-8",
        )
        return root_file

    def json_record(self, *extra):
        raw, code = run_main(
            "--projects-dir", str(self.root), "--days", "1", "--format", "json",
            "--events-since", "2026-09-20T10:00:00Z",
            "--events-before", "2026-09-20T11:00:00Z", *extra,
        )
        self.assertIsNone(code)
        return json.loads(raw)

    def test_exact_claude_request_result_child_pair_is_observed(self):
        old_file = self.claude_pair()
        os.utime(old_file, (1, 1))
        result = self.json_record()["execution_telemetry"]
        self.assertEqual(result["event_window"], {
            "start": "2026-09-20T10:00:00Z", "end": "2026-09-20T11:00:00Z"})
        self.assertEqual(result["producer"], {
            "name": "agent-costs", "version": 1,
            "harness_versions": {"claude": ["2.1.0"]},
        })
        self.assertEqual(result["source_coverage"]["routing"], {
            "state": "full", "eligible_events": 1, "paired_events": 1,
            "reasons": [],
        })
        self.assertEqual(result["source_coverage"]["source_only"], {})
        self.assertEqual(len(result["runs"]), 1)
        run = result["runs"][0]
        self.assertEqual(run["run_id"], "claude:repo:120")
        self.assertEqual(run["routing"]["coverage"],
                         result["source_coverage"]["routing"])
        self.assertEqual(run["routing"]["observations"], [{
            "declaration": {"dispatch_id": None, "role": "reviewer",
                            "authority": "runtime-agent-type"},
            "requested": {"host": "claude", "model": "opus", "effort": "high"},
            "configured": {"host": None, "model": None, "effort": None},
            "observed": {"host": "claude", "model": "claude-opus-5-20260901",
                         "effort": "high", "authority": "assistant-execution"},
            "escalation": None, "count": 1,
            "first_event_at": "2026-09-20T10:06:00Z",
            "last_event_at": "2026-09-20T10:06:00Z",
        }])
        self.assertEqual(result["runs"][0]["scheduling"], {})

    def test_requested_host_missing_or_conflicting_is_null_with_coverage_reason(self):
        for host, reason in ((None, "request_host_missing"),
                             ("codex", "request_host_conflict")):
            with self.subTest(host=host):
                self.claude_pair(request_host=host)
                telemetry = self.json_record()["execution_telemetry"]
                observation = telemetry["runs"][0]["routing"]["observations"][0]
                self.assertIsNone(observation["requested"]["host"])
                self.assertNotEqual(observation["configured"]["host"], "claude")
                self.assertNotEqual(observation["observed"]["host"],
                                    observation["requested"]["host"])
                self.assertIn({"code": reason, "count": 1},
                              telemetry["source_coverage"]["routing"]["reasons"])

    def test_event_window_uses_event_time_while_accounting_keeps_file_mtime(self):
        old_file = self.claude_pair()
        os.utime(old_file, (1, 1))
        record_value = self.json_record()
        self.assertEqual(record_value["strata"]["claude"]["runs"], [])
        self.assertEqual(record_value["execution_telemetry"]["runs"][0]
                         ["routing"]["observations"][0]["count"], 1)

    def test_missing_execution_timestamp_is_inconclusive_not_outside(self):
        self.claude_pair(execution_at=None)
        routing = self.json_record()["execution_telemetry"]["source_coverage"]["routing"]
        self.assertEqual(routing["state"], "none")
        self.assertEqual(routing["paired_events"], 0)
        self.assertIn({"code": "timestamp_missing", "count": 1}, routing["reasons"])

    def test_unpaired_event_flags_and_invalid_range_are_usage_errors(self):
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(self.root), "--format", "json",
                                 "--events-since", "2026-09-20T10:00:00Z")
        self.assertEqual((out, code), ("", 2))
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main(
                "--projects-dir", str(self.root), "--format", "json",
                "--events-since", "2026-09-20T11:00:00Z",
                "--events-before", "2026-09-20T10:00:00Z")
        self.assertEqual((out, code), ("", 2))

    def test_codex_turn_context_is_configured_and_not_observed(self):
        codex = self.root / "codex" / "2026" / "09" / "20"
        codex.mkdir(parents=True)
        (codex / "rollout.jsonl").write_text(
            codex_meta("thread-1", thread_source="subagent",
                       source={"subagent": {"thread_spawn": {
                           "parent_thread_id": "parent", "depth": 1,
                           "agent_role": "reviewer", "model": "gpt-5.6-sol",
                           "effort": "high"}}})
            + codex_turn_context("gpt-5.6-sol", "high") + codex_usage(10),
            encoding="utf-8",
        )
        raw, code = run_main(
            "--projects-dir", "/nonexistent/claude", "--codex-sessions", str(self.root / "codex"),
            "--strata", "codex", "--format", "json", "--days", "0",
            "--events-since", "2026-08-04T00:00:00Z",
            "--events-before", "2026-08-05T00:00:00Z",
        )
        self.assertIsNone(code)
        observation = json.loads(raw)["execution_telemetry"]["runs"][0]
        observation = observation["routing"]["observations"][0]
        self.assertEqual(observation["requested"],
                         {"host": "codex", "model": "gpt-5.6-sol",
                          "effort": "high"})
        self.assertEqual(observation["configured"],
                         {"host": "codex", "model": "gpt-5.6-sol", "effort": "high"})
        self.assertEqual(observation["observed"],
                         {"host": "codex", "model": None, "effort": None,
                          "authority": "codex-rollout"})
```

- [ ] **Step 2: Run the new producer class and watch it fail**

Run: `python3 -m unittest -v tests.test_agent_costs.ExecutionTelemetryRoutingTest`

Expected: FAIL/ERROR — the CLI rejects `--events-since/--events-before` and emitted records have no `execution_telemetry`.

- [ ] **Step 3: Implement the event-time routing projection**

Add the constants and functions in **Interfaces**. Keep cost scanning unchanged; use a distinct all-file telemetry pass. Parse each source line once in that pass, retain correlation ids only in local dictionaries, aggregate only after exact linkage, and delete those ids at projection. Canonicalize all accepted times to `YYYY-MM-DDTHH:MM:SS[.fraction]Z` and compare aware UTC values. Resolve request host before execution pairing from the explicit launch member and recognized transport target rules above; do not consult configured or observed fields. Preserve missing/conflicting request-host reasons in both run and aggregate coverage.

For Claude, resolve the projected run with the same project/issue rules as `build_groups`; for Codex, use the same thread grouping as `collect_codex_groups`. Do not join existing `models`, `efforts`, or `agents_by_type` counters. Build the telemetry document before `build_record`, and include it in `body` before calling `canonical_digest`.

When no explicit event window is present, emit the same schema with null bounds, retain any bounded observations the source can state, and add `cohort_incomplete` so routing cannot become full. When a source is selected but has no runtime version field, set its harness version to `null` and add `runtime_version_missing`. If a selected source emits no telemetry run, write its coverage to `source_only` and merge that contribution into top-level routing coverage.

- [ ] **Step 4: Verify the producer contract and accounting oracle**

Run: `python3 -m unittest -v tests.test_agent_costs.ExecutionTelemetryRoutingTest tests.test_agent_costs.BuildRecordTest tests.test_agent_costs.TextByteIdentityTest tests.test_agent_costs.ScanCodexFileTest`

Expected: PASS; the new routing class passes, all existing record/dedup/text tests remain green, and the golden text bytes are unchanged.

Run: `git diff --check -- scripts/agent-costs.py tests/test_agent_costs.py`

Expected: exit `0`; any whitespace error or change outside the two pathspecs leaves the task incomplete.

- [ ] **Step 5: Commit the producer-routing slice**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py
git commit -S -m "feat(telemetry): emit observed routing evidence" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
