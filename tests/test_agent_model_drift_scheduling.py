import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_model_drift_test_support import (
    REPO_ROOT, DriftCliCase, coverage, digest, legacy_record_value, record_value,
    seal_record)


def full_metric(value, cohort):
    return {"value": value, "coverage": coverage(), "cohort_digest": cohort}


def scheduled_record(values):
    value = record_value()
    run = value["execution_telemetry"]["runs"][0]
    for name, metric in values.items():
        run["scheduling"][name] = metric
        value["execution_telemetry"]["source_coverage"]["scheduling"][name] = \
            copy.deepcopy(metric["coverage"])
    return seal_record(value)


def record_with_components(fresh, cache_create, cache_read):
    value = record_value()
    _set_input_components(value, fresh, cache_create, cache_read)
    return seal_record(value)


def legacy_record_with_components(fresh, cache_create, cache_read):
    value = legacy_record_value()
    _set_input_components(value, fresh, cache_create, cache_read)
    return seal_record(value)


def _set_input_components(value, fresh, cache_create, cache_read):
    components = (fresh, cache_create, cache_read)
    input_total = (None if any(item is None for item in components)
                   else sum(components))
    layers = (
        value["strata"]["claude"]["runs"][0]["tokens"],
        value["strata"]["claude"]["totals"],
        value["fleet"]["totals"],
    )
    for totals in layers:
        totals["fresh"] = fresh
        totals["cache_create"] = cache_create
        totals["cache_read"] = cache_read
        totals["input_total"] = input_total


class SchedulingProjectionTest(DriftCliCase):
    def test_absent_scheduling_is_unmeasured_and_does_not_change_routing(self):
        code, out, err = self.run()
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"]["state"], "conforming")
        self.assertEqual(report["scheduling"]["state"], "unmeasured")
        self.assertIsNone(report["scheduling"]["wait_token_share"])
        self.assertIsNone(report["scheduling"]["occupancy"])

    def test_one_supported_metric_is_partial_with_measured_zero(self):
        value = scheduled_record({"spawn_attempts": full_metric(0, digest([]))})
        code, out, _ = self.run(record=value)
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "partial")
        self.assertEqual(scheduling["metrics"]["spawn_attempts"]["value"], 0)
        self.assertIsNone(scheduling["metrics"]["waits"]["value"])

    def test_fully_covered_zero_metrics_are_measured_without_fake_ratios(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        window_cohort = digest(event_window)
        response_cohort = digest([["response", "covered-zero"]])
        values = {}
        for name in ("spawn_attempts", "capacity_rejections", "waits", "follow_ups"):
            values[name] = full_metric(0, digest([]))
        for name in ("wait_input_tokens", "covered_input_tokens"):
            values[name] = full_metric(0, response_cohort)
        for name in ("slot_capacity_seconds", "claimed_slot_seconds"):
            values[name] = full_metric(0, window_cohort)
        code, out, _ = self.run(record=scheduled_record(values))
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "measured")
        self.assertIsNone(scheduling["wait_token_share"])
        self.assertIsNone(scheduling["occupancy"])
        self.assertTrue(all(metric["value"] == 0
                            for metric in scheduling["metrics"].values()))

    def test_compatible_numerators_and_denominators_derive_ratios(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        response_cohort = digest([["response", "r1"], ["response", "r2"]])
        values = {
            "wait_input_tokens": full_metric(20, response_cohort),
            "covered_input_tokens": full_metric(100, response_cohort),
            "slot_capacity_seconds": full_metric(60, digest(event_window)),
            "claimed_slot_seconds": full_metric(30, digest(event_window)),
        }
        code, out, _ = self.run(record=scheduled_record(values))
        self.assertEqual(code, 0)
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "partial")
        self.assertEqual(scheduling["wait_token_share"], 0.2)
        self.assertEqual(scheduling["occupancy"], 0.5)

    def test_mismatched_cohorts_and_impossible_slots_are_input_errors(self):
        event_window = record_value()["execution_telemetry"]["event_window"]
        cases = {
            "token-cohort": {
                "wait_input_tokens": full_metric(1, digest(["wait"])),
                "covered_input_tokens": full_metric(2, digest(["covered"])),
            },
            "slot-cohort": {
                "slot_capacity_seconds": full_metric(10, digest(["wrong-window"])),
                "claimed_slot_seconds": full_metric(5, digest(event_window)),
            },
            "slot-order": {
                "slot_capacity_seconds": full_metric(5, digest(event_window)),
                "claimed_slot_seconds": full_metric(6, digest(event_window)),
            },
        }
        for name, values in cases.items():
            with self.subTest(case=name):
                code, out, err = self.run(record=scheduled_record(values))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

    def test_report_has_no_scheduling_conclusion_vocabulary(self):
        code, out, _ = self.run()
        self.assertEqual(code, 0)
        scheduling = json.dumps(json.loads(out)["scheduling"], sort_keys=True).lower()
        for forbidden in ("waste", "cheap", "useful", "savings", "billing", "utilization"):
            self.assertNotIn(forbidden, scheduling)

    def test_high_cache_read_ratio_is_context_only(self):
        code, out, err = self.run(record=record_with_components(100, 0, 900))
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["context"], {"cache_read_ratio": {
            "value": 0.9, "numerator": 900, "denominator": 1000,
            "coverage": "measured"}})
        self.assertEqual(report["state"], "conforming")
        self.assertEqual(report["routing"]["state"], "conforming")
        self.assertEqual(report["scheduling"]["state"], "unmeasured")
        encoded = json.dumps(report["context"], sort_keys=True).lower()
        for forbidden in ("cheap", "useful", "waste", "savings", "billing", "utilization"):
            self.assertNotIn(forbidden, encoded)

    def test_legacy_record_keeps_available_context_while_routing_is_unknown(self):
        code, out, err = self.run(record=legacy_record_with_components(25, 0, 75))
        self.assertEqual((code, err), (3, ""))
        report = json.loads(out)
        self.assertEqual(report["state"], "inconclusive")
        self.assertEqual(report["context"]["cache_read_ratio"]["value"], 0.75)
        self.assertEqual(report["scheduling"]["state"], "unmeasured")

    def test_cache_ratio_nulls_missing_and_zero_denominators(self):
        cases = (((None, None, None), None, None), ((0, 0, 0), 0, 0),
                 ((None, 0, 25), 25, None))
        for components, numerator, denominator in cases:
            with self.subTest(components=components):
                code, out, _ = self.run(record=record_with_components(*components))
                self.assertEqual(code, 0)
                ratio = json.loads(out)["context"]["cache_read_ratio"]
                self.assertEqual(ratio, {"value": None, "numerator": numerator,
                                         "denominator": denominator,
                                         "coverage": "unavailable"})

    def test_cache_ratio_projects_absent_fleet_total_members(self):
        cases = (("totals", None, None), ("cache_read", None, 0),
                 ("input_total", 0, None))
        for member, numerator, denominator in cases:
            with self.subTest(member=member):
                value = record_value()
                if member == "totals":
                    del value["fleet"][member]
                else:
                    del value["fleet"]["totals"][member]
                code, out, err = self.run(record=seal_record(value))
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out)["context"]["cache_read_ratio"], {
                    "value": None, "numerator": numerator,
                    "denominator": denominator, "coverage": "unavailable"})

    def test_invalid_cache_totals_are_malformed_without_report(self):
        cases = [record_with_components(*components) for components in ((0, 0, -1), (0, 0, True))]
        above_total = record_with_components(0, 0, 10)
        above_total["fleet"]["totals"]["input_total"] = 9
        cases.append(seal_record(above_total))
        for value in cases:
            with self.subTest(record=value):
                code, out, err = self.run(record=value)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")

    def test_zero_run_selected_source_prevents_false_measured_scheduling(self):
        names = ("spawn_attempts", "capacity_rejections", "waits", "follow_ups", "wait_input_tokens", "covered_input_tokens", "slot_capacity_seconds", "claimed_slot_seconds")
        unavailable = coverage("none", reasons=[{"code": "source_unsupported", "count": 1}])
        source_only = {"codex": {"routing": coverage("none", reasons=[{"code": "runtime_version_missing", "count": 1}]), "scheduling": {name: copy.deepcopy(unavailable) for name in names}}}
        value = record_value(selected=("claude", "codex"), source_only=source_only)
        run = value["execution_telemetry"]["runs"][0]
        run["scheduling"]["spawn_attempts"] = full_metric(0, digest([]))
        value["execution_telemetry"]["source_coverage"]["scheduling"]["spawn_attempts"] = copy.deepcopy(unavailable)
        code, out, err = self.run(record=seal_record(value))
        self.assertEqual((code, err), (3, ""))
        metric = json.loads(out)["scheduling"]["metrics"]["spawn_attempts"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["coverage"], unavailable)

    def test_multi_run_and_full_zero_source_only_aggregate_deterministically(self):
        names = ("spawn_attempts", "capacity_rejections", "waits", "follow_ups",
                 "wait_input_tokens", "covered_input_tokens",
                 "slot_capacity_seconds", "claimed_slot_seconds")
        source_only = {"codex": {"routing": coverage(),
                       "scheduling": {name: coverage() for name in names}}}
        value = record_value(selected=("claude", "codex"), source_only=source_only)
        first = value["execution_telemetry"]["runs"][0]
        second = copy.deepcopy(first)
        first["run_id"], second["run_id"] = "claude:repo:z", "claude:repo:a"
        window = value["execution_telemetry"]["event_window"]
        cohorts = {"spawn_attempts": (digest(["z"]), digest(["a"])),
                   "capacity_rejections": (digest(["rz"]), digest(["ra"])),
                   "waits": (digest(["wz"]), digest(["wa"])),
                   "follow_ups": (digest(["fz"]), digest(["fa"])),
                   "wait_input_tokens": (digest(["tz"]), digest(["ta"])),
                   "covered_input_tokens": (digest(["tz"]), digest(["ta"])),
                   "slot_capacity_seconds": (digest(window), digest(window)),
                   "claimed_slot_seconds": (digest(window), digest(window))}
        values = {"spawn_attempts": (2, 3), "capacity_rejections": (4, 5),
                  "waits": (6, 7), "follow_ups": (8, 9),
                  "wait_input_tokens": (20, 30), "covered_input_tokens": (100, 150),
                  "slot_capacity_seconds": (60, 40), "claimed_slot_seconds": (30, 10)}
        for name in names:
            first["scheduling"][name] = full_metric(values[name][0], cohorts[name][0])
            second["scheduling"][name] = full_metric(values[name][1], cohorts[name][1])
            value["execution_telemetry"]["source_coverage"]["scheduling"][name] = coverage()
        value["execution_telemetry"]["runs"] = [first, second]
        code, out, err = self.run(record=seal_record(value))
        self.assertEqual((code, err), (3, ""))
        scheduling = json.loads(out)["scheduling"]
        self.assertEqual(scheduling["state"], "measured")
        self.assertEqual(set(scheduling["metrics"]), set(names))
        for name in names:
            self.assertEqual(scheduling["metrics"][name], {
                "value": sum(values[name]), "coverage": coverage(),
                "cohort_digest": digest(sorted(cohorts[name]))})
        self.assertEqual(scheduling["wait_token_share"], 0.2)
        self.assertEqual(scheduling["occupancy"], 0.4)


class RepositoryWiringTest(unittest.TestCase):
    def test_justfile_wires_new_suite_without_dropping_issue_100_boundaries(self):
        text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        for required in ("home/common/agent-skills/tests/test_ship_release_contracts.py", "home/common/agent-skills/tests/test_agent_model_matrix.py", "home/common/agent-skills/tests/test_resolve_project.py", "tests/test_agent_costs.py", "tests/test_agent_model_drift_schema.py", "tests/test_agent_model_drift_routing.py", "tests/test_agent_model_drift_scheduling.py", "tests/test_agent_gate_bundle.py", "agent-model-drift *args:", "python3 scripts/agent-model-drift.py {{args}}"):
            self.assertIn(required, text)
