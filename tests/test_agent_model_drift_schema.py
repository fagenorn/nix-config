import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_model_drift_test_support import DriftCliCase, baseline_value, coverage, legacy_record_value, record_value, seal_record

class BaselineLifecycleTest(DriftCliCase):
    def test_fresh_matching_zero_event_cohort_is_deterministic_and_conforming(self):
        first, second = self.run(), self.run(); self.assertEqual(first, second)
        code, out, err = first; self.assertEqual((code,err),(0,"")); report=json.loads(out)
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
        value=record_value(); value["execution_telemetry"]=[]; self.assertEqual(self.run(record=seal_record(value))[0],2)
