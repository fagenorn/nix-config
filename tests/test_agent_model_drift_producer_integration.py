"""Real agent-costs to agent-model-drift interoperability regressions."""

import contextlib
import io
import json
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_model_drift_test_support import (DriftCliCase, agent_model_drift,
                                             baseline_value, seal_baseline,
                                             seal_record)
from test_agent_costs import (USAGE_1, USAGE_2, agent_result, assistant, codex_meta,
                              codex_turn_context, codex_usage, run_main)


class MixedSourceCoverageProducerIntegrationTest(DriftCliCase):
    """Keep the producer's mixed assigned/unassigned Codex shape consumable."""

    def _rollout(self, meta, *events):
        records = [json.loads(line) for line in (meta + "".join(events)).splitlines()]
        records[0]["timestamp"] = "2026-09-20T10:05:00Z"
        records[0]["payload"]["cli_version"] = "0.1.0"
        for item in records[1:]:
            item["timestamp"] = "2026-09-20T10:06:00Z"
        return "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in records)

    def _producer_record(self):
        project = self.root / "claude" / "-Users-me-repo-issue-120-x"
        child = project / "s1" / "subagents"
        child.mkdir(parents=True)
        launch = {"type": "tool_use", "id": "toolu-route-1", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "role": "reviewer",
                            "prompt": "review", "model": "opus", "effort": "high"}}
        (project / "s1.jsonl").write_text(
            assistant("launch", usage=USAGE_1, content=[launch],
                      timestamp="2026-09-20T10:05:00Z", version="2.1.0")
            + agent_result("toolu-route-1", "agent-child-1",
                           timestamp="2026-09-20T10:05:30Z"), encoding="utf-8")
        (child / "child.jsonl").write_text(
            assistant("child", usage=USAGE_2, model="claude-opus-5-20260901",
                      effort="high", agent_id="agent-child-1", sidechain=True,
                      timestamp="2026-09-20T10:06:00Z", version="2.1.0"), encoding="utf-8")
        sessions = self.root / "codex" / "2026" / "09" / "20"
        sessions.mkdir(parents=True)
        spawn = {"subagent": {"thread_spawn": {
            "parent_thread_id": "parent", "depth": 1, "agent_role": "reviewer",
            "dispatch_id": "from-issue-plan-review", "model": "opus", "effort": "high"}}}
        (sessions / "assigned.jsonl").write_text(
            self._rollout(codex_meta("assigned", thread_source="subagent", source=spawn),
                          codex_turn_context("opus", "high"), codex_usage(10)),
            encoding="utf-8")
        (sessions / "unassigned.jsonl").write_text(
            self._rollout(codex_meta("unassigned", thread_source="subagent",
                                     source={"subagent": {}})), encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            raw, code = run_main("--projects-dir", str(self.root / "claude"),
                                 "--codex-sessions", str(self.root / "codex"),
                                 "--strata", "both", "--format", "json", "--days", "0",
                                 "--events-since", "2026-09-20T10:00:00Z",
                                 "--events-before", "2026-09-20T11:00:00Z")
        self.assertIsNone(code)
        self.assertEqual(stdout.getvalue(), "")
        return json.loads(raw)

    def _baseline(self):
        baseline = baseline_value(
            self.matrix, self.matrix_digest,
            harness_versions={"claude": ["2.1.0"], "codex": ["0.1.0"]},
        )
        baseline["dispatch_hosts"]["from-issue-plan-review"] = "codex"
        baseline["catalog"]["codex"] = {
            "models": {model: {"allowed": [model], "prohibited": []}
                       for model in sorted({role["model"] for role in self.matrix["roles"].values()})},
            "efforts": {effort: {"allowed": [effort], "prohibited": []}
                        for effort in sorted({role["effort"] for role in self.matrix["roles"].values()})},
        }
        return seal_baseline(baseline)

    def test_mixed_codex_run_and_source_only_coverage_reaches_reporter(self):
        record = self._producer_record()
        telemetry = record["execution_telemetry"]
        self.assertEqual([run["run_id"] for run in telemetry["runs"]],
                         ["claude:repo:120", "codex:repo:none"])
        self.assertEqual(telemetry["runs"][1]["routing"]["coverage"], {
            "state": "partial", "eligible_events": 1, "paired_events": 1,
            "reasons": [{"code": "execution_effort_missing", "count": 1},
                        {"code": "execution_model_missing", "count": 1}],
        })
        self.assertEqual(telemetry["source_coverage"]["source_only"]["codex"]["routing"], {
            "state": "none", "eligible_events": 1, "paired_events": 0,
            "reasons": [{"code": "request_missing", "count": 1}],
        })
        self.assertEqual(telemetry["source_coverage"]["routing"], {
            "state": "partial", "eligible_events": 3, "paired_events": 2,
            "reasons": [{"code": "execution_effort_missing", "count": 1},
                        {"code": "execution_model_missing", "count": 1},
                        {"code": "request_missing", "count": 1}],
        })

        code, out, err = self.run(record=record, baseline=self._baseline())
        self.assertEqual((code, err), (3, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "inconclusive")
        self.assertEqual(report["routing"]["eligible_events"], 3)
        self.assertIn("ROUTING_COVERAGE_MISSING",
                      [finding["code"] for finding in report["routing"]["findings"]])

        original = agent_model_drift.schema._telemetry

        def reject_mixed_source(value, selected):
            original(value, selected)
            run_sources = {run["run_id"].split(":", 1)[0] for run in value["runs"]}
            if run_sources & set(value["source_coverage"]["source_only"]):
                raise agent_model_drift.schema.InputError("legacy mixed source rejection")

        with mock.patch.object(agent_model_drift.schema, "_telemetry", reject_mixed_source):
            code, out, err = self.run(record=record, baseline=self._baseline())
        self.assertEqual((code, out), (2, ""))
        self.assertIn("legacy mixed source rejection", err)

        malformed = json.loads(json.dumps(record))
        malformed["execution_telemetry"]["source_coverage"]["routing"]["eligible_events"] = 1
        code, out, err = self.run(record=seal_record(malformed), baseline=self._baseline())
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err)
