"""Offline tests for scripts/agent-gate-bundle.py.

Run: python3 -m unittest -v tests/test_agent_gate_bundle.py
"""

import contextlib
import importlib.util
import inspect
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "agent-gate-bundle.py"

_spec = importlib.util.spec_from_file_location("agent_gate_bundle", SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

IDENTITY = {
    "bound": {"commit": {"base": "aaa", "candidate": "bbb"},
              "project_contract_version": {"base": "1", "candidate": "1"},
              "shared_platform_version": {"base": "1", "candidate": "1"}},
    "pinned": {"evaluator_version": {"base": "e1", "candidate": "e1"},
               "rubric_version": {"base": "r1", "candidate": "r1"},
               "environment_fingerprint": {"base": "f1", "candidate": "f1"},
               "builds": {
                   "claude": {"agent": {"base": "a1", "candidate": "a1"},
                              "model": {"base": "m1", "candidate": "m1"}},
                   "codex": {"agent": {"base": "a2", "candidate": "a2"},
                             "model": {"base": "m2", "candidate": "m2"}}}},
}


def make_record(tmp, name, runs):
    """Write a record document; `runs` maps stratum -> [(run_id, input_total)]."""
    body = {
        "schema_version": 1, "kind": "agent-cost-record",
        "window": {"days": 7, "cutoff_epoch": None, "strata": sorted(runs),
                   "sources": {s: "/x" for s in runs}},
        "strata": {s: {"cost_basis": "list-price", "totals": {"runs": len(v)},
                       "runs": [{"run_id": rid, "stratum": s, "project": "repo",
                                 "issue": "120", "outcome": "completed",
                                 "tokens": {"input_total": total, "fresh": total,
                                            "cache_create": 0, "cache_read": 0,
                                            "output": 0, "reasoning": None},
                                 "cost_usd": None, "peak_ctx": total,
                                 "turns": 1, "sessions": 1, "subagents": 0}
                                for rid, total in v]}
                   for s, v in runs.items()},
        "fleet": {"informative": True, "totals": {}}, "notes": "n",
    }
    document = dict(body, record_id=gate.canonical_digest(body),
                    generated_at="2026-09-02T00:00:00Z")
    path = tmp / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


def trial(path, document, stratum, run_id):
    return {"record": str(path), "run_id": run_id,
            "record_id": document["record_id"]}


def make_case(tmp, case_id, case_class, totals, quality=None, **extra):
    """`totals` maps stratum -> (base list, candidate list) of input_total ints."""
    strata = {}
    for stratum, (base, candidate) in totals.items():
        sides = {}
        for side, values in (("base", base), ("candidate", candidate)):
            trials = []
            for index, total in enumerate(values):
                run_id = f"{stratum}:repo:{case_id}-{side}-{index}"
                path, document = make_record(
                    tmp, f"{case_id}-{stratum}-{side}-{index}.json",
                    {stratum: [(run_id, total)]})
                trials.append(trial(path, document, stratum, run_id))
            sides[side] = trials
        sides["quality"] = quality or {
            "critical_all_pass": True,
            "evaluator_stability": "stable",
            "noncritical_median": {"base": 87.0, "candidate": 86.0}}
        sides.update(extra)
        strata[stratum] = sides
    return {"case_id": case_id, "case_class": case_class, "strata": strata}


def make_manifest(tmp, cases):
    return {"schema_version": 1, "kind": "agent-gate-trials",
            "identity": json.loads(json.dumps(IDENTITY)),
            "expansion": {"expanded": False, "checkpoint_ref": None},
            "cases": cases}


def full_cases(tmp, totals=None):
    """One case per core class, all with the same trial totals."""
    totals = totals or {s: ([1000, 1000, 1000], [800, 800, 800]) for s in gate.STRATA}
    return [make_case(tmp, klass, klass, totals) for klass in gate.CORE_CASE_CLASSES]


class ManifestDocumentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, payload):
        path = self.tmp / "trials.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                        encoding="utf-8")
        return path

    def test_valid_manifest_loads(self):
        loaded = gate.load_manifest(self.write(make_manifest(self.tmp, full_cases(self.tmp))))
        self.assertEqual(loaded["kind"], "agent-gate-trials")

    def test_missing_file_is_a_manifest_error(self):
        with self.assertRaises(gate.ManifestError):
            gate.load_manifest(self.tmp / "absent.json")

    def test_duplicate_json_key_is_a_manifest_error(self):
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write('{"kind": "a", "kind": "b"}'))
        self.assertTrue(any(d.code == "JSON_INVALID" for d in caught.exception.diagnostics))

    def test_unknown_top_level_key_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["state"] = "approved"
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write(payload))
        codes = {d.code for d in caught.exception.diagnostics}
        self.assertIn("FIELD_UNKNOWN", codes)

    def test_unknown_case_class_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["cases"][0]["case_class"] = "exempt"
        with self.assertRaises(gate.ManifestError):
            gate.load_manifest(self.write(payload))

    def test_wrong_kind_and_schema_version_are_manifest_errors(self):
        for mutate in ({"kind": "agent-gate-bundle"}, {"schema_version": 2}):
            payload = dict(make_manifest(self.tmp, full_cases(self.tmp)), **mutate)
            with self.assertRaises(gate.ManifestError):
                gate.load_manifest(self.write(payload))

    def test_absent_evaluator_stability_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        del payload["cases"][0]["strata"]["claude"]["quality"]["evaluator_stability"]
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write(payload))
        self.assertIn("FIELD_REQUIRED", {d.code for d in caught.exception.diagnostics})

    def test_invalid_rubric_values_are_manifest_errors(self):
        for value in (101.0, -1.0, True, "87"):
            payload = make_manifest(self.tmp, full_cases(self.tmp))
            payload["cases"][0]["strata"]["claude"]["quality"][
                "noncritical_median"]["candidate"] = value
            with self.subTest(value=value):
                with self.assertRaises(gate.ManifestError):
                    gate.load_manifest(self.write(payload))

    def test_a_bool_is_not_an_integer_count(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["cases"][0]["strata"]["claude"]["checks"] = {
            "static_fallback_checks": {"base": True, "candidate": 0},
            "discovery_preflight_ops": {"base": 100, "candidate": 50}}
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write(payload))
        self.assertIn("FIELD_TYPE", {d.code for d in caught.exception.diagnostics})

    def test_json_nan_and_infinity_literals_are_rejected(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        for literal in ("NaN", "Infinity", "-Infinity"):
            raw = json.dumps(payload).replace(
                '"candidate": 86.0', '"candidate": ' + literal, 1)
            with self.subTest(literal=literal):
                with self.assertRaises(gate.ManifestError):
                    gate.load_manifest(self.write(raw))

    def test_inconsistent_expansion_metadata_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["expansion"] = {"expanded": "yes", "checkpoint_ref": None}
        with self.assertRaises(gate.ManifestError):
            gate.load_manifest(self.write(payload))


class ResolveTrialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def codes(self, manifest):
        evidence, diagnostics = gate.resolve_trials(manifest)
        return evidence, {d.code for d in diagnostics}

    def test_complete_manifest_resolves_to_evidence(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(evidence["cases"]), 4)
        context = evidence["cases"][0]["strata"]["claude"]["context"]
        self.assertEqual(context["base_median"], 1000)
        self.assertEqual(context["candidate_median"], 800)
        self.assertEqual(context["delta_tokens"], -200)
        self.assertAlmostEqual(context["delta_pct"], -20.0)
        self.assertEqual(len(context["trials"]["base"]), 3)
        self.assertEqual(context["trials"]["base"][0]["input_total"], 1000)
        self.assertEqual(context["trials"]["base"][0]["generated_at"],
                         "2026-09-02T00:00:00Z")
        self.assertEqual(context["trials"]["base"][0]["outcome"], "completed")
        self.assertIsNone(evidence["cases"][0]["strata"]["claude"]["checks"])
        self.assertIsNone(evidence["cases"][0]["strata"]["claude"]["maintenance"])

    def test_missing_core_case_class_is_diagnosed(self):
        cases = full_cases(self.tmp)[:3]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("CASE_CLASS_MISSING", codes)

    def test_empty_cases_is_diagnosed(self):
        evidence, codes = self.codes(make_manifest(self.tmp, []))
        self.assertIsNone(evidence)
        self.assertIn("CASES_EMPTY", codes)

    def test_evidence_timestamps_are_bound_into_the_resolved_trial(self):
        # two manifests identical but for the cited records' generated_at
        first = make_manifest(self.tmp, full_cases(self.tmp))
        stamps = []
        for stamp in ("2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"):
            manifest = make_manifest(self.tmp, full_cases(self.tmp))
            for entry in manifest["cases"][0]["strata"]["claude"]["base"]:
                path = Path(entry["record"])
                document = json.loads(path.read_text(encoding="utf-8"))
                document["generated_at"] = stamp
                path.write_text(json.dumps(document), encoding="utf-8")
            evidence, diagnostics = gate.resolve_trials(manifest)
            self.assertEqual(diagnostics, [])
            stamps.append(evidence["cases"][0]["strata"]["claude"]
                          ["context"]["trials"]["base"][0]["generated_at"])
        self.assertEqual(stamps, ["2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"])
        self.assertIsNotNone(first)

    def test_unstable_evaluator_is_diagnosed(self):
        cases = full_cases(self.tmp)
        cases[0]["strata"]["claude"]["quality"]["evaluator_stability"] = "unstable"
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("EVALUATOR_UNSTABLE", codes)

    def test_only_three_or_an_expanded_ten_pairs_are_accepted(self):
        for count, expanded, ref, ok in ((3, False, None, True),
                                         (4, False, None, False),
                                         (9, True, "ck-1", False),
                                         (10, False, None, False),
                                         (10, True, "ck-1", True),
                                         (10, True, None, False),
                                         (3, False, "ck-1", False)):
            totals = {s: ([1000] * count, [800] * count) for s in gate.STRATA}
            manifest = make_manifest(self.tmp, full_cases(self.tmp, totals))
            manifest["expansion"] = {"expanded": expanded, "checkpoint_ref": ref}
            evidence, codes = self.codes(manifest)
            with self.subTest(count=count, expanded=expanded, ref=ref):
                if ok:
                    self.assertIsNotNone(evidence)
                else:
                    self.assertIsNone(evidence)
                    self.assertTrue(
                        codes & {"TRIALS_CARDINALITY", "EXPANSION_INCONSISTENT"}, codes)

    def test_a_self_consistent_malformed_record_cannot_resolve(self):
        for mutate in ({"kind": "agent-gate-bundle"},
                       {"schema_version": 2},
                       {"generated_at": ""}):
            manifest = make_manifest(self.tmp, full_cases(self.tmp))
            entry = manifest["cases"][0]["strata"]["claude"]["base"][0]
            path = Path(entry["record"])
            document = json.loads(path.read_text(encoding="utf-8"))
            body = {k: v for k, v in dict(document, **mutate).items()
                    if k not in ("record_id", "generated_at")}
            document = dict(document, **mutate)
            document["record_id"] = gate.canonical_digest(body)  # re-digested!
            entry["record_id"] = document["record_id"]
            path.write_text(json.dumps(document), encoding="utf-8")
            evidence, codes = self.codes(manifest)
            with self.subTest(mutate=mutate):
                self.assertIsNone(evidence)
                self.assertIn("RECORD_INVALID", codes)

    def test_missing_or_wrongly_typed_nested_run_fields_do_not_raise(self):
        for mutate in (lambda run: run.pop("tokens"),
                       lambda run: run.__setitem__("tokens", []),
                       lambda run: run["tokens"].pop("input_total"),
                       lambda run: run["tokens"].__setitem__("input_total", -1),
                       lambda run: run["tokens"].__setitem__("input_total", True),
                       lambda run: run.__setitem__("peak_ctx", "big"),
                       lambda run: run.__setitem__("outcome", 7)):
            manifest = make_manifest(self.tmp, full_cases(self.tmp))
            entry = manifest["cases"][0]["strata"]["claude"]["base"][0]
            path = Path(entry["record"])
            document = json.loads(path.read_text(encoding="utf-8"))
            mutate(document["strata"]["claude"]["runs"][0])
            body = {k: v for k, v in document.items()
                    if k not in ("record_id", "generated_at")}
            document["record_id"] = gate.canonical_digest(body)
            entry["record_id"] = document["record_id"]
            path.write_text(json.dumps(document), encoding="utf-8")
            evidence, codes = self.codes(manifest)   # must not raise
            with self.subTest(mutate=mutate):
                self.assertIsNone(evidence)
                self.assertIn("RECORD_INVALID", codes)

    def test_two_trials_a_side_is_insufficient(self):
        totals = {s: ([1000, 1000], [800, 800]) for s in gate.STRATA}
        manifest = make_manifest(self.tmp, full_cases(self.tmp, totals))
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertIsNone(evidence)
        rendered = gate.render(diagnostics)
        self.assertTrue(any(
            line.startswith("TRIALS_INSUFFICIENT $.cases[0].strata.claude: "
                            "2 paired trials, 3 required") for line in rendered), rendered)

    def test_unequal_side_lengths_are_unpaired(self):
        totals = {s: ([1000, 1000, 1000], [800, 800, 800, 800]) for s in gate.STRATA}
        evidence, codes = self.codes(make_manifest(self.tmp, full_cases(self.tmp, totals)))
        self.assertIsNone(evidence)
        self.assertIn("TRIALS_UNPAIRED", codes)

    def test_repeated_citations_on_a_side_are_not_distinct_trials(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        claude["base"] = [claude["base"][0]] * 3       # one run, cited three times
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertIsNone(evidence)
        rendered = gate.render(diagnostics)
        self.assertIn("TRIALS_DUPLICATE $.cases[0].strata.claude.base: "
                      "3 cited trials, 1 distinct (record_id, run_id)", rendered)

    def test_a_partial_duplicate_is_caught_too(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        codex = manifest["cases"][0]["strata"]["codex"]
        codex["candidate"][1] = codex["candidate"][0]  # two of three distinct
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertIsNone(evidence)
        self.assertIn("TRIALS_DUPLICATE $.cases[0].strata.codex.candidate: "
                      "3 cited trials, 2 distinct (record_id, run_id)",
                      gate.render(diagnostics))

    def test_the_same_run_cited_across_sides_is_not_a_duplicate(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        claude["candidate"] = list(claude["base"])     # delta 0 buys no approval
        evidence, codes = self.codes(manifest)
        self.assertNotIn("TRIALS_DUPLICATE", codes)
        self.assertIsNotNone(evidence)

    def test_absent_stratum_is_diagnosed(self):
        cases = full_cases(self.tmp)
        del cases[0]["strata"]["codex"]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("STRATUM_MISSING", codes)

    def test_absent_quality_is_diagnosed(self):
        cases = full_cases(self.tmp)
        del cases[0]["strata"]["claude"]["quality"]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("QUALITY_MISSING", codes)

    def test_pinned_identity_mismatch_is_diagnosed(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        manifest["identity"]["pinned"]["rubric_version"]["candidate"] = "r2"
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("IDENTITY_MISMATCH", codes)

    def test_bound_identity_may_differ_but_not_be_empty(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        self.assertEqual(gate.resolve_trials(manifest)[1], [])   # base != candidate commit
        manifest["identity"]["bound"]["commit"]["candidate"] = ""
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("IDENTITY_INCOMPLETE", codes)

    def test_unreadable_missing_and_tampered_records_are_diagnosed(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        claude["base"][0]["record"] = str(self.tmp / "gone.json")
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RECORD_UNREADABLE", codes)

        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        path = Path(claude["base"][0]["record"])
        document = json.loads(path.read_text(encoding="utf-8"))
        document["strata"]["claude"]["runs"][0]["tokens"]["input_total"] = 1
        path.write_text(json.dumps(document), encoding="utf-8")
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RECORD_DIGEST_MISMATCH", codes)

        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        manifest["cases"][0]["strata"]["claude"]["base"][0]["run_id"] = "claude:repo:nope"
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RUN_NOT_FOUND", codes)


def context(base, candidate, base_trials=None, candidate_trials=None):
    delta = candidate - base
    return {"base_median": base, "candidate_median": candidate,
            "delta_tokens": delta,
            "delta_pct": (100 * delta / base) if base else None,
            "trials": {
                "base": [{"run_id": f"b{i}", "record_id": "sha256:x",
                          "generated_at": "2026-09-02T00:00:00Z", "outcome": "completed",
                          "input_total": total, "peak_ctx": total}
                         for i, total in enumerate(base_trials or [base] * 3)],
                "candidate": [{"run_id": f"c{i}", "record_id": "sha256:x",
                               "generated_at": "2026-09-02T00:00:00Z", "outcome": "completed",
                               "input_total": total, "peak_ctx": total}
                              for i, total in enumerate(candidate_trials or [candidate] * 3)]}}


def quality(base=87.0, candidate=87.0, critical=True, stability="stable"):
    return {"critical_all_pass": critical, "evaluator_stability": stability,
            "noncritical_median": {"base": base, "candidate": candidate}}


def stratum(ctx, qual=None, checks=None, maintenance=None):
    return {"context": ctx, "quality": qual or quality(),
            "checks": checks, "maintenance": maintenance}


def evidence(*case_specs):
    """Each spec is (case_id, case_class, {stratum: stratum_dict})."""
    return {"cases": [{"case_id": cid, "case_class": klass, "strata": strata}
                      for cid, klass, strata in case_specs]}


def flat(claude, codex=None):
    """One case, both strata; `codex` defaults to a flat no-change stratum."""
    return evidence(("c1", "cold-resolution",
                     {"claude": claude, "codex": codex or stratum(context(1000, 1000))}))


class GatePrimitiveTest(unittest.TestCase):
    def test_context_saving_boundaries(self):
        self.assertTrue(gate.context_saves(-500, -1.0))       # exactly 500 tokens
        self.assertTrue(gate.context_saves(-100, -10.0))      # exactly 10 percent
        self.assertFalse(gate.context_saves(-499, -9.99))
        self.assertFalse(gate.context_saves(0, 0.0))
        self.assertFalse(gate.context_saves(-400, None))      # zero base median

    def test_context_regression_bound_is_conjunctive(self):
        self.assertFalse(gate.context_breaches(129, 2.0))     # exactly 2 percent
        self.assertFalse(gate.context_breaches(128, 2.1))     # exactly 128 tokens
        self.assertTrue(gate.context_breaches(129, 2.1))
        self.assertTrue(gate.context_breaches(400, None))     # zero base median, rose

    def test_quality_fails_ignores_the_stability_declaration(self):
        # instability is Task 3's EVALUATOR_UNSTABLE, not a quality veto (D37)
        self.assertFalse(gate.quality_fails(quality(stability="unstable")))

    def test_quality_bound_is_one_sided(self):
        self.assertFalse(gate.quality_fails(quality(87.0, 82.0)))   # exactly 5 points
        self.assertTrue(gate.quality_fails(quality(87.0, 81.9)))
        self.assertFalse(gate.quality_fails(quality(80.0, 95.0)))   # candidate is better
        self.assertTrue(gate.quality_fails(quality(87.0, 87.0, critical=False)))

    def test_checks_gate_boundaries(self):
        fires = {"static_fallback_checks": {"base": 3, "candidate": 0},
                 "discovery_preflight_ops": {"base": 100, "candidate": 80}}
        self.assertTrue(gate.checks_save(fires))                     # exactly 20 percent
        self.assertFalse(gate.checks_save(None))
        self.assertFalse(gate.checks_save(dict(fires, discovery_preflight_ops={
            "base": 100, "candidate": 81})))
        self.assertFalse(gate.checks_save(dict(fires, static_fallback_checks={
            "base": 0, "candidate": 0})))                            # nothing disappeared
        self.assertFalse(gate.checks_save(dict(fires, static_fallback_checks={
            "base": 3, "candidate": 1})))                            # not every invocation

    def test_maintenance_gate_boundaries(self):
        fires = {"manual_update_sites": {"base": 8, "candidate": 4},
                 "new_hand_authored_projections": 0}
        self.assertTrue(gate.maintenance_saves(fires))               # exactly 50 percent
        self.assertFalse(gate.maintenance_saves(None))
        self.assertFalse(gate.maintenance_saves(dict(fires, manual_update_sites={
            "base": 8, "candidate": 5})))
        self.assertFalse(gate.maintenance_saves(dict(fires, manual_update_sites={
            "base": 1, "candidate": 1})))                            # no site removed
        self.assertFalse(gate.maintenance_saves(dict(
            fires, new_hand_authored_projections=1)))


class DecideTest(unittest.TestCase):
    def test_context_saving_with_a_clean_other_stratum_is_approved(self):
        self.assertEqual(gate.decide(flat(stratum(context(1000, 800)))), "approved")

    def test_no_gate_fires_is_rejected(self):
        self.assertEqual(gate.decide(flat(stratum(context(1000, 999)))), "rejected")

    def test_quality_veto_beats_a_firing_gate(self):
        vetoed = stratum(context(1000, 800), quality(87.0, 70.0))
        self.assertEqual(gate.decide(flat(vetoed)), "rejected")

    def test_a_regression_elsewhere_in_the_same_stratum_blocks_the_saving(self):
        both = evidence(
            ("c1", "cold-resolution", {"claude": stratum(context(1000, 800)),
                                       "codex": stratum(context(1000, 1000))}),
            ("c2", "routine-issue", {"claude": stratum(context(1000, 1200)),
                                     "codex": stratum(context(1000, 1000))}))
        self.assertEqual(gate.decide(both), "rejected")

    def test_a_regression_in_the_other_stratum_blocks_the_saving(self):
        blocked = flat(stratum(context(1000, 800)),
                       codex=stratum(context(1000, 1200)))
        self.assertEqual(gate.decide(blocked), "rejected")

    def test_checks_and_maintenance_gates_can_carry_an_approval_alone(self):
        checks = stratum(context(1000, 1000), checks={
            "static_fallback_checks": {"base": 3, "candidate": 0},
            "discovery_preflight_ops": {"base": 40, "candidate": 25}})
        self.assertEqual(gate.decide(flat(checks)), "approved")
        upkeep = stratum(context(1000, 1000), maintenance={
            "manual_update_sites": {"base": 8, "candidate": 3},
            "new_hand_authored_projections": 0})
        self.assertEqual(gate.decide(flat(upkeep)), "approved")

    def test_straddling_pairs_are_unmeasured_and_dominate_the_quality_veto(self):
        straddle = stratum(context(1000, 1000,
                                   base_trials=[1000, 1000, 1000],
                                   candidate_trials=[400, 1400, 1200]),
                           quality(87.0, 60.0))
        self.assertEqual(gate.straddling_cases(flat(straddle)),
                         [(0, "c1", "claude")])
        self.assertEqual(gate.decide(flat(straddle)), "unmeasured")

    def test_ten_pairs_straddle_exactly_as_three_do(self):
        base = [1000] * 10
        candidate = [400] + [1400] * 9
        straddle = stratum(context(1000, 1400, base, candidate))
        self.assertEqual(gate.decide(flat(straddle)), "unmeasured")

    def test_empty_or_absent_evidence_is_unmeasured(self):
        self.assertEqual(gate.decide({"cases": []}), "unmeasured")
        self.assertEqual(gate.decide(None), "unmeasured")

    def test_gate_results_report_every_axis(self):
        gates = gate.gate_results(flat(stratum(context(1000, 800))))
        self.assertEqual(set(gates),
                         {"quality", "context", "checks", "maintenance", "cross_stratum"})
        self.assertTrue(gates["quality"]["passed"])
        self.assertTrue(gates["context"]["claude"]["fired"])
        self.assertFalse(gates["context"]["codex"]["fired"])
        self.assertEqual(gates["context"]["claude"]["saving_cases"], ["c1"])
        self.assertEqual(gates["context"]["claude"]["breaching_cases"], [])
        self.assertTrue(gates["cross_stratum"]["claude"]["qualifies"])

def run_cli(*argv):
    """main() with stdout captured; returns (exit code, parsed bundle or None)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate.main(list(argv))
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None)


class BundleCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def manifest_file(self, manifest, name="trials.json"):
        path = self.tmp / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return str(path)

    def saving_manifest(self):
        return make_manifest(self.tmp, full_cases(self.tmp))

    def flat_manifest(self):
        totals = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}
        return make_manifest(self.tmp, full_cases(self.tmp, totals))

    def test_approved_bundle_exits_zero_with_no_diagnostics(self):
        code, bundle = run_cli("--trials", self.manifest_file(self.saving_manifest()))
        self.assertEqual(code, 0)
        self.assertEqual(bundle["state"], "approved")
        self.assertEqual(bundle["kind"], "agent-gate-bundle")
        self.assertEqual(bundle["gate_contract"], "issue-70")
        self.assertEqual(bundle["gate_version"], 1)
        self.assertEqual(bundle["diagnostics"], [])
        self.assertIsNone(bundle["override"])
        self.assertEqual(bundle["identity"]["pinned"]["rubric_version"]["base"], "r1")

    def test_rejected_bundle_exits_three(self):
        code, bundle = run_cli("--trials", self.manifest_file(self.flat_manifest()))
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "rejected")
        self.assertEqual(bundle["diagnostics"], [])

    def test_a_run_cited_three_times_cannot_reach_approved(self):
        pristine = self.saving_manifest()
        code, bundle = run_cli("--trials", self.manifest_file(pristine, "clean.json"))
        self.assertEqual((code, bundle["state"]), (0, "approved"))   # regression guard

        repeated = self.saving_manifest()
        for stratum in gate.STRATA:
            block = repeated["cases"][0]["strata"][stratum]
            for side in gate.SIDES:
                block[side] = [block[side][0]] * 3
        code, bundle = run_cli("--trials", self.manifest_file(repeated, "dup.json"))
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "unmeasured")
        self.assertTrue(any(line.startswith("TRIALS_DUPLICATE ")
                            for line in bundle["diagnostics"]), bundle["diagnostics"])

    def test_bundle_id_is_stable_and_covers_the_state(self):
        path = self.manifest_file(self.saving_manifest())
        first = run_cli("--trials", path)[1]
        second = run_cli("--trials", path)[1]
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        body = {k: v for k, v in first.items()
                if k not in ("bundle_id", "generated_at")}
        self.assertEqual(first["bundle_id"], gate.canonical_digest(body))
        other = run_cli("--trials", self.manifest_file(self.flat_manifest(), "b.json"))[1]
        self.assertNotEqual(first["bundle_id"], other["bundle_id"])

    def test_an_override_bearing_bundle_id_is_reproducible(self):
        path = self.manifest_file(self.flat_manifest(), "ovr.json")
        argv = ("--trials", path, "--override", "further experimentation approved",
                "--override-by", "anis", "--override-at", "2026-09-02T12:00:00Z")
        first, second = run_cli(*argv)[1], run_cli(*argv)[1]
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(first["override"]["authorized_at"], "2026-09-02T12:00:00Z")
        later = run_cli(*argv[:-1], "2026-09-03T12:00:00Z")[1]
        self.assertNotEqual(first["bundle_id"], later["bundle_id"])

    def test_override_without_a_timestamp_is_a_usage_error(self):
        path = self.manifest_file(self.flat_manifest(), "novrat.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--trials", path, "--override", "why", "--override-by", "anis")
        self.assertEqual(caught.exception.code, 2)

    def test_an_empty_override_reason_is_a_usage_error(self):
        # An unexpanded shell variable: the flag is present, its value is not.
        # Absence is what waives the companions, and "" is not absence.
        path = self.manifest_file(self.flat_manifest(), "emptyreason.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--trials", path, "--override", "")
        self.assertEqual(caught.exception.code, 2)

    def test_a_blank_override_companion_is_a_usage_error(self):
        # Every field of the block is hashed into bundle_id as the record of
        # who authorized what; a blank one records nothing (D38).
        path = self.manifest_file(self.flat_manifest(), "blankby.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--trials", path, "--override", "why", "--override-by", "  ",
                    "--override-at", "2026-09-02T12:00:00Z")
        self.assertEqual(caught.exception.code, 2)

    def test_a_malformed_override_timestamp_is_a_usage_error(self):
        path = self.manifest_file(self.flat_manifest(), "badat.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--trials", path, "--override", "why", "--override-by", "anis",
                    "--override-at", "2026-09-02 12:00:00")
        self.assertEqual(caught.exception.code, 2)

    def test_unreadable_manifest_is_exit_two_with_no_document(self):
        code, bundle = run_cli("--trials", str(self.tmp / "absent.json"))
        self.assertEqual(code, 2)
        self.assertIsNone(bundle)

    def test_emitter_refuses_a_state_the_evidence_does_not_earn(self):
        manifest = self.flat_manifest()
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertEqual(diagnostics, [])
        with self.assertRaises(gate.BundleIntegrityError):
            gate.assemble_bundle(manifest, evidence, [], None, "approved")


class NoUpgradeTableTest(unittest.TestCase):
    """One row per manifest surface that might try to buy an approval."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, manifest, name):
        path = self.tmp / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return str(path)

    def area(self, name):
        """A private record directory per row. Rows reuse the same case ids, so
        one row's records would otherwise overwrite a neighbour's on disk and
        make it fail for a citation fault instead of the fault it is named for.
        """
        path = self.tmp / name
        path.mkdir()
        return path

    def rows(self):
        flat = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}

        area = self.area("declared_state")
        declared_state = make_manifest(area, full_cases(area))
        declared_state["state"] = "approved"

        area = self.area("declared_id")
        declared_id = make_manifest(area, full_cases(area))
        declared_id["bundle_id"] = "sha256:" + "0" * 64

        empty_cases = make_manifest(self.area("empty_cases"), [])

        area = self.area("absent_stratum")
        absent_stratum = make_manifest(area, full_cases(area))
        del absent_stratum["cases"][0]["strata"]["codex"]

        area = self.area("missing_class")
        missing_class = make_manifest(area, full_cases(area)[:3])

        area = self.area("straddle")
        straddle = make_manifest(area, full_cases(area, dict(
            flat, claude=([1000, 1000, 1000], [300, 1500, 1400]))))

        area = self.area("mismatched")
        mismatched = make_manifest(area, full_cases(area))
        mismatched["identity"]["pinned"]["environment_fingerprint"]["candidate"] = "f2"

        area = self.area("exempted")
        exempted = make_manifest(area, full_cases(area, flat))
        exempted["cases"][0]["required"] = False

        # per D36: a retained-subset count, and ten pairs with no recorded checkpoint
        area = self.area("retained")
        retained = make_manifest(area, full_cases(area, {
            s: ([1000] * 5, [800] * 5) for s in gate.STRATA}))

        area = self.area("unchecked_ten")
        unchecked_ten = make_manifest(area, full_cases(area, {
            s: ([1000] * 10, [800] * 10) for s in gate.STRATA}))

        area = self.area("checkpoint_without_expansion")
        checkpoint_without_expansion = make_manifest(area, full_cases(area))
        checkpoint_without_expansion["expansion"] = {
            "expanded": False, "checkpoint_ref": "ck-1"}

        # per D37
        area = self.area("unstable")
        unstable = make_manifest(area, full_cases(area))
        unstable["cases"][0]["strata"]["claude"]["quality"][
            "evaluator_stability"] = "unstable"

        # per D34: a wrong-kind record, re-digested so it is self-consistent
        area = self.area("wrong_kind")
        wrong_kind = make_manifest(area, full_cases(area))
        entry = wrong_kind["cases"][0]["strata"]["claude"]["base"][0]
        cited = Path(entry["record"])
        document = dict(json.loads(cited.read_text(encoding="utf-8")),
                        kind="agent-gate-bundle")
        body = {k: v for k, v in document.items()
                if k not in ("record_id", "generated_at")}
        document["record_id"] = entry["record_id"] = gate.canonical_digest(body)
        cited.write_text(json.dumps(document), encoding="utf-8")

        # per D34: a rubric value outside [0, 100] is a document fault
        area = self.area("impossible_score")
        impossible_score = make_manifest(area, full_cases(area))
        impossible_score["cases"][0]["strata"]["claude"]["quality"][
            "noncritical_median"]["candidate"] = 1000.0

        return [
            ("manifest-declared state", declared_state, 2),
            ("manifest-declared bundle_id", declared_id, 2),
            ("per-case required opt-out", exempted, 2),
            ("empty cases", empty_cases, 3),
            ("absent stratum", absent_stratum, 3),
            ("missing core case class", missing_class, 3),
            ("straddling case", straddle, 3),
            ("mismatched pinned identity", mismatched, 3),
            ("selectively retained 5 pairs", retained, 3),
            ("ten pairs, no recorded checkpoint", unchecked_ten, 3),
            ("checkpoint without a declared expansion", checkpoint_without_expansion, 3),
            ("declared-unstable evaluator", unstable, 3),
            ("self-consistent wrong-kind record", wrong_kind, 3),
            ("rubric value outside [0, 100]", impossible_score, 2),
        ]

    def test_no_row_yields_an_approval(self):
        for index, (label, manifest, expected_code) in enumerate(self.rows()):
            with self.subTest(row=label):
                code, bundle = run_cli("--trials", self.write(manifest, f"m{index}.json"))
                self.assertEqual(code, expected_code)
                self.assertNotEqual(code, 0)
                if bundle is not None:
                    self.assertEqual(bundle["state"], "unmeasured")
                    self.assertTrue(bundle["diagnostics"])

    def test_a_straddling_bundle_says_why(self):
        straddle = dict(self.rows()[6][1])
        _code, bundle = run_cli("--trials", self.write(straddle, "straddle.json"))
        self.assertTrue(any(line.startswith("CASE_STRADDLES_GATE")
                            for line in bundle["diagnostics"]), bundle["diagnostics"])

    def test_a_tampered_record_cannot_certify(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        cited = Path(manifest["cases"][0]["strata"]["claude"]["base"][0]["record"])
        document = json.loads(cited.read_text(encoding="utf-8"))
        document["strata"]["claude"]["runs"][0]["tokens"]["input_total"] = 10
        cited.write_text(json.dumps(document), encoding="utf-8")
        code, bundle = run_cli("--trials", self.write(manifest, "tampered.json"))
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "unmeasured")

    def test_override_records_authority_without_changing_the_verdict(self):
        flat = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}
        manifest = make_manifest(self.tmp, full_cases(self.tmp, flat))
        code, bundle = run_cli("--trials", self.write(manifest, "override.json"),
                               "--override", "further experimentation approved",
                               "--override-by", "anis",
                               "--override-at", "2026-09-02T12:00:00Z")
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "rejected")
        self.assertEqual(set(bundle["override"]),
                         {"reason", "authorized_by", "authorized_at", "scope"})
        self.assertEqual(bundle["override"]["scope"], "further-experimentation")
        self.assertEqual(bundle["override"]["authorized_by"], "anis")


class NoUpgradeStructureTest(unittest.TestCase):
    """D14's two layers, checked structurally rather than only behaviourally."""

    def test_the_verdict_authority_sees_only_the_evidence(self):
        self.assertEqual(list(inspect.signature(gate.decide).parameters),
                         ["evidence"])

    def test_no_authorization_name_reaches_the_verdict_authority(self):
        # Literal, and prose counts: a docstring naming the flag is one rename
        # away from a parameter that honours it. Scoped to `decide` alone --
        # every other function in the module is free to spell it (D14).
        self.assertNotIn("override", inspect.getsource(gate.decide))

    def test_the_emitter_re_decides_before_it_writes(self):
        self.assertIn("decide(", inspect.getsource(gate.assemble_bundle))


if __name__ == "__main__":
    unittest.main()
