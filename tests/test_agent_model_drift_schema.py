import contextlib
import copy
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_model_drift_test_support import (DriftCliCase, agent_model_drift,
    baseline_value, coverage, legacy_record_value, record_value, seal_baseline,
    seal_record)

class BaselineLifecycleTest(DriftCliCase):
    def test_fresh_matching_zero_event_cohort_is_deterministic_and_conforming(self):
        first, second = self.run(), self.run(); self.assertEqual(first, second)
        code, out, err = first; self.assertEqual((code,err),(0,"")); report=json.loads(out)
        self.assertEqual(set(report), {"schema_version", "kind", "evaluated_at", "inputs", "state", "routing", "scheduling", "context"})
        self.assertEqual(report["kind"], "agent-model-drift-report")
        self.assertEqual(report["evaluated_at"], "2026-09-20T12:00:00Z")
        self.assertEqual(report["inputs"], {"record": record_value()["record_id"], "matrix": self.matrix_digest, "baseline": baseline_value(self.matrix, self.matrix_digest)["baseline_id"]})
        self.assertEqual(report["state"], "conforming"); self.assertEqual(report["routing"], {"state":"conforming","eligible_events":0,"evaluated_events":0,"comparisons":[],"findings":[]})
    def test_valid_legacy_v1_is_unknown_not_malformed(self):
        code,out,err=self.run(record=legacy_record_value()); self.assertEqual((code,err),(3,"")); report=json.loads(out); self.assertEqual([x["code"] for x in report["routing"]["findings"]],["IDENTITY_MISSING","ROUTING_COVERAGE_MISSING"])
    def test_source_only_coverage_is_checked(self):
        unavailable=coverage("none",reasons=[{"code":"source_unsupported","count":1}]); source_only={"codex":{"routing":coverage("none",reasons=[{"code":"runtime_version_missing","count":1}]),"scheduling":{x:copy.deepcopy(unavailable) for x in ("spawn_attempts","capacity_rejections","waits","follow_ups","wait_input_tokens","covered_input_tokens","slot_capacity_seconds","claimed_slot_seconds")}}}
        value=record_value(selected=("claude","codex"),source_only=source_only); self.assertEqual(self.run(record=value)[0],3)
        value["execution_telemetry"]["source_coverage"]["routing"]=coverage(); self.assertEqual(self.run(record=seal_record(value))[0],2)
    def test_baseline_lifecycle_and_identity_are_inconclusive(self):
        baseline=baseline_value(self.matrix,self.matrix_digest,valid_before="2026-09-20T12:00:00Z"); code,out,err=self.run(baseline=baseline); self.assertEqual((code,err),(3,"")); self.assertIn("BASELINE_STALE",[x["code"] for x in json.loads(out)["routing"]["findings"]])
    def test_malformed_inputs_exit_two(self):
        for bad in (None, [], {"unknown": True}):
            value=record_value(); value["execution_telemetry"]=bad
            code,out,err=self.run(record=seal_record(value)); self.assertEqual(code,2); self.assertEqual(out,""); self.assertTrue(err)

    def test_lifecycle_and_concrete_identity_incompatibility_exit_three(self):
        cases = {"unbounded": (record_value(start=None, end=None), None, "WINDOW_UNBOUNDED"),
                 "future": (None, baseline_value(self.matrix, self.matrix_digest, captured_at="2026-09-20T13:00:00Z"), "BASELINE_FUTURE"),
                 "outside": (record_value(start="2026-09-19T23:00:00Z"), None, "WINDOW_OUTSIDE_BASELINE"),
                 "identity-missing": (record_value(harness={"claude":None}), None, "IDENTITY_MISSING"),
                 "producer-mismatch": (None, baseline_value(self.matrix,self.matrix_digest,producer={"name":"agent-costs","version":2,"telemetry_schema_version":1}), "IDENTITY_MISMATCH"),
                 "harness-mismatch": (None, baseline_value(self.matrix,self.matrix_digest,harness_versions={"claude":["2.0.0"]}), "IDENTITY_MISMATCH"),
                 "matrix-mismatch": (None, baseline_value(self.matrix,"sha256:" + "0"*64), "IDENTITY_MISMATCH")}
        for name,(record,baseline,expected) in cases.items():
            with self.subTest(name=name):
                code,out,err=self.run(record=record,baseline=baseline); self.assertEqual((code,err),(3,"")); self.assertIn(expected,[x["code"] for x in json.loads(out)["routing"]["findings"]])

    def test_malformed_baseline_boundaries_exit_two_with_empty_stdout(self):
        valid=baseline_value(self.matrix,self.matrix_digest); cases=[]
        for name in ("wrong-type","bad-time","missing-dispatch","extra-dispatch","missing-model-tier","extra-effort-tier","overlap","unsupported-version","unknown-member","bad-classification"):
            candidate=copy.deepcopy(valid)
            if name=="wrong-type": candidate["dispatch_hosts"]=[]
            elif name=="bad-time": candidate["captured_at"]="not-a-time"
            elif name=="missing-dispatch": candidate["dispatch_hosts"].pop(next(iter(candidate["dispatch_hosts"])))
            elif name=="extra-dispatch": candidate["dispatch_hosts"]["unknown"]="claude"
            elif name=="missing-model-tier": candidate["catalog"]["claude"]["models"].pop("opus")
            elif name=="extra-effort-tier": candidate["catalog"]["claude"]["efforts"]["ultra"]={"allowed":["ultra"],"prohibited":[]}
            elif name=="overlap": candidate["catalog"]["claude"]["models"]["opus"]["prohibited"]=list(candidate["catalog"]["claude"]["models"]["opus"]["allowed"])
            elif name=="unsupported-version": candidate["schema_version"]=2
            elif name=="bad-classification": candidate["catalog"]["claude"]["models"]["opus"]["allowed"]=1
            else: candidate["extra"]=True
            cases.append(seal_baseline(candidate))
        for candidate in cases:
            code,out,err=self.run(baseline=candidate); self.assertEqual(code,2); self.assertEqual(out,""); self.assertTrue(err)

    def test_corrupted_ids_duplicate_keys_and_observation_shapes_exit_two(self):
        for record, baseline in ((dict(record_value(),record_id="sha256:"+"0"*64),None),(None,dict(baseline_value(self.matrix,self.matrix_digest),baseline_id="sha256:"+"0"*64))):
            code,out,err=self.run(record=record,baseline=baseline); self.assertEqual(code,2); self.assertEqual(out,""); self.assertTrue(err)
        record=record_value(); record["execution_telemetry"]["runs"][0]["routing"]["observations"]=[{"garbage":True}]
        code,out,err=self.run(record=seal_record(record)); self.assertEqual(code,2); self.assertEqual(out,"")
        duplicate=self.root/"duplicate.json"; duplicate.write_text('{"schema_version":1,"schema_version":1}')
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            code=agent_model_drift.main(["--record",str(self.write("record.json",record_value())),"--baseline",str(duplicate),"--matrix-root",str(self.matrix_root),"--now","2026-09-20T12:00:00Z"])
        self.assertEqual(code,2); self.assertEqual(stdout.getvalue(),""); self.assertTrue(stderr.getvalue())

    def test_coverage_metric_and_window_boundaries_exit_two(self):
        record=record_value(); route=record["execution_telemetry"]["runs"][0]["routing"]["coverage"]; route.update(eligible_events=1,paired_events=0)
        record["execution_telemetry"]["source_coverage"]["routing"].update(eligible_events=1,paired_events=0)
        code,out,err=self.run(record=seal_record(record)); self.assertEqual(code,2); self.assertEqual(out,"")
        record=record_value(start="2026-09-20T11:00:00Z",end="2026-09-20T10:00:00Z")
        code,out,err=self.run(record=record); self.assertEqual(code,2); self.assertEqual(out,"")

    def test_malformed_record_and_rejected_matrix_exit_two(self):
        bad_type=record_value(); bad_type["execution_telemetry"]=[]
        bad_version=record_value(); bad_version["schema_version"]=2
        unknown=record_value(); unknown["extra"]=True
        for candidate in map(seal_record,(bad_type,bad_version,unknown)):
            code,out,err=self.run(record=candidate); self.assertEqual(code,2); self.assertEqual(out,""); self.assertTrue(err)
        path=self.matrix_root/"home/common/agent-skills/model-matrix.json"
        matrix=json.loads(path.read_text()); matrix["roles"]["reviewer"]["model"]="sonnet"; path.write_text(json.dumps(matrix))
        code,out,err=self.run(); self.assertEqual(code,2); self.assertEqual(out,""); self.assertTrue(err)
