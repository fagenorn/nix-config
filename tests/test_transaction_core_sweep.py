"""Asserted sweep of the transaction core across four unlike project shapes (#204 D6, D17).

The prototype's autopilot printed where each (shape, scenario) cell landed; this table
asserts it against persisted history, including each scenario's custody events and the
evidence forms it voids. Every terminal cell's receipt is read back and asserted against its
bytes, and every parked cell has none (#209 D15).

Run: just agent-workflow-tests
"""

import ast
import hashlib
import inspect
import io
import re
import tempfile
import tokenize
import unittest
from pathlib import Path

from agent_tools import transaction_core
from agent_tools.transaction_core import RecoveryPlanRejected, TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_sweep_support import (
    AUTHORITY_CLASS, GAP_CELLS, PROTOTYPE_SCENARIOS, SCENARIOS, drive, shape_declaration,
    shape_recovery)
from .transaction_core_world import World

WITH_ACTIVATION = ("created", "awaiting_verification", "ready", "publishing", "published",
                   "activating", "proving", "succeeded")
WITHOUT_ACTIVATION = tuple(s for s in WITH_ACTIVATION if s != "activating")

LAPSED = WITH_ACTIVATION[:-1] + ("attention_required", "proving", "succeeded")
LAPSED_LIBRARY = WITHOUT_ACTIVATION[:-1] + ("attention_required", "proving", "succeeded")

RESUMED = WITH_ACTIVATION[:4] + ("attention_required", "publishing") + WITH_ACTIVATION[4:]
RESUMED_LIBRARY = (WITHOUT_ACTIVATION[:4] + ("attention_required", "publishing")
                   + WITHOUT_ACTIVATION[4:])

# (shape, scenario) -> (final state, states the history passes through,
#                       temporal forms voided, (first action's attempts, others' attempts))
SWEEP = {
    **{(shape, scenario): ("succeeded", path, frozenset(), attempts)
       for shape, path in (("platform", WITH_ACTIVATION), ("product", WITH_ACTIVATION),
                           ("daemon", WITH_ACTIVATION), ("library", WITHOUT_ACTIVATION))
       for scenario, attempts in (("success", (1, 1)), ("lease_renewal", (1, 1)),
                                  ("throttled_retry", (2, 2)))},
    ("platform", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"}), (1, 1)),
    ("product", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"}), (1, 1)),
    ("daemon", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot", "interval"}),
                                (1, 1)),
    ("library", "lease_lapse"): ("succeeded", LAPSED_LIBRARY, frozenset(), (1, 1)),
    **{(shape, "resume_after_crash"): (
        "succeeded", RESUMED_LIBRARY if shape == "library" else RESUMED, frozenset(), (2, 1))
       for shape in ("platform", "product", "daemon", "library")},
}
LAPSING = ("lease_lapse_detected", "lease_reacquired")
CUSTODY_EVENTS = {
    "success": ["lease_acquired", "lease_released"],
    "lease_renewal": ["lease_acquired", "lease_released"],
    "throttled_retry": ["lease_acquired", "lease_released"],
    "lease_lapse": ["lease_acquired", *LAPSING, "lease_released"],
    "resume_after_crash": ["lease_acquired", *LAPSING, "lease_released"],
}
PUB_PARK = WITH_ACTIVATION[:4] + ("attention_required",)
ACT_PARK = WITH_ACTIVATION[:6] + ("attention_required",)
PROOF_PARK = WITH_ACTIVATION[:7] + ("attention_required",)
ROLLED = ACT_PARK + ("recovering", "rolled_back")
ABANDON = WITH_ACTIVATION[:3] + ("attention_required", "abandoned")
TS, DV, NE = "target_satisfied", "diverged", "no_effect"


def succeeded(shape, **expect):
    return ("succeeded", WITHOUT_ACTIVATION if shape == "library" else WITH_ACTIVATION,
            expect)


def published(first, second, **more):
    return {first: "satisfied", second: "satisfied", **more}


# (shape, scenario) -> (final state, path, expectations): #207's committed landings.
LANDINGS = {
    ("platform", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_closure": "satisfied", "tag_release": "diverged"}}),
    ("product", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_image": "satisfied", "index_channel": "diverged"}}),
    ("daemon", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_helpers": "satisfied", "stage_helpers": "diverged"}}),
    ("library", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"upload_artifact": "satisfied", "bind_version": "diverged"}}),
    ("platform", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_closure", "tag_release", switch_host_a="diverged")}),
    ("product", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_image", "index_channel", deploy_api="diverged")}),
    ("daemon", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_helpers", "stage_helpers", install_job="diverged")}),
    ("library", "failed_activation"): succeeded("library"),
    ("platform", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["switch_host_a", "switch_host_b"],
        "satisfied": []}),
    ("product", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["deploy_api", "deploy_admin"],
        "satisfied": ["api_liveness", "admin_liveness"]}),
    ("daemon", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["install_job", "restart_job"],
        "satisfied": ["job_liveness"]}),
    ("library", "stale_false_positive_health"): succeeded("library"),
    ("platform", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 3,
        "exhausted_by": "budget"}),
    ("product", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 2,
        "exhausted_by": "window"}),
    ("daemon", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 2,
        "exhausted_by": "window"}),
    ("library", "expired_snapshot"): succeeded("library", members=[]),
    ("platform", "fleet_stall"): succeeded("platform"),
    ("product", "fleet_stall"): ("attention_required", ACT_PARK, {
        "actions": published("build_image", "index_channel", deploy_api="satisfied",
                             deploy_admin="satisfied", converge_fleet="in_progress")}),
    ("daemon", "fleet_stall"): succeeded("daemon"),
    ("library", "fleet_stall"): succeeded("library"),
}


def rolled(snapshot, selected, checked, restored, residue):
    return ("rolled_back", ROLLED, {"snapshot": snapshot, "selected": selected,
                                    "checked": checked, "restored": restored,
                                    "residue": residue})


def forward(reason, named, anchors=None):
    return ("attention_required", ACT_PARK, {"forward": reason, "named": named,
                                             "anchors": anchors})


# (shape, scenario) -> (final, path, expectations): #208's committed recovery landings.
RECOVERIES = {
    ("platform", "rollback"): rolled(
        {"build_closure": TS, "tag_release": TS, "switch_host_a": DV, "switch_host_b": NE},
        [("build_closure", "compensate"), ("tag_release", "compensate"),
         ("switch_host_a", "restore"), ("switch_host_a", "compensate")],
        ["switch_host_a"], ["switch_host_a"], ["build_closure", "tag_release", "switch_host_a"]),
    ("product", "rollback"): rolled(
        {"build_image": TS, "index_channel": TS, "deploy_api": DV, "deploy_admin": NE,
         "converge_fleet": NE},
        [("build_image", "compensate"), ("index_channel", "restore"), ("deploy_api", "restore")],
        ["index_channel", "deploy_api"], ["index_channel", "deploy_api"], ["build_image"]),
    ("daemon", "rollback"): rolled(
        {"build_helpers": TS, "stage_helpers": TS, "install_job": DV, "restart_job": NE},
        [("build_helpers", "compensate"), ("stage_helpers", "restore"),
         ("install_job", "restore")],
        ["stage_helpers", "install_job"], ["stage_helpers", "install_job"], ["build_helpers"]),
    ("platform", "irreversible_migration"): forward("unit_not_restorable", "switch_host_a",
                                                    ["switch_host_b"]),
    ("product", "irreversible_migration"): forward(
        "unit_not_restorable", "deploy_api", ["index_channel", "deploy_admin", "converge_fleet"]),
    ("daemon", "irreversible_migration"): forward("unit_not_restorable", "install_job",
                                                  ["stage_helpers", "restart_job"]),
    ("platform", "incompatible_restore"): forward("restore_incompatible", "switch_host_a"),
    ("product", "incompatible_restore"): forward("restore_incompatible", "index_channel"),
    ("daemon", "incompatible_restore"): forward("restore_incompatible", "stage_helpers"),
    **{(shape, "missing_rollback_anchor"): ("abandoned", ABANDON, {"missing": unit})
       for shape, unit in (("platform", "switch_host_a"), ("product", "index_channel"),
                           ("daemon", "stage_helpers"))},
    **{("library", scenario): succeeded("library")
       for scenario in ("rollback", "irreversible_migration", "incompatible_restore",
                        "missing_rollback_anchor")},
    **{(shape, "unsupported_operation"): ("rejected", None, {"binding": binding})
       for shape, binding in (("platform", "nix"), ("product", "api"), ("daemon", "job"),
                              ("library", "index"))},
}
# (shape, scenario) -> (final, path): the unobservable release parks and stays parked (#209 D14).
DISPOSALS = {(shape, "unknown_external_state"): ("attention_required", PUB_PARK)
             for shape in SHAPES}


def declared_nodes(shape):
    """Every publication and activation node id the shape's profile declares."""
    _, profile, _ = SHAPES[shape](World())
    activation = [] if profile["activation"] == "none" else profile["activation"]
    return sorted(node["id"] for node in [*profile["publication"], *activation])


def transitions(transaction):
    return [event for event in transaction.events if event["type"] == "transitioned"]


def states_passed(transaction):
    return ("created",) + tuple(event["to"] for event in transitions(transaction))


class SweepTableTest(unittest.TestCase):
    def assertReceipt(self, root, persisted):
        types = [e["type"] for e in persisted.events]
        if persisted.state not in ("succeeded", "rolled_back", "abandoned"):
            self.assertNotIn("receipt_sealed", types)
            return
        seal = persisted.events[-1]
        self.assertEqual(seal["type"], "receipt_sealed")
        receipt = TransactionStore(root).read_receipt(seal["receipt_digest"])
        self.assertEqual(receipt["outcome"], persisted.state)
        path = root / "receipts" / (seal["receipt_digest"].removeprefix("sha256:") + ".json")
        self.assertEqual("sha256:" + hashlib.sha256(path.read_bytes()[:-1]).hexdigest(),
                         seal["receipt_digest"])
        if persisted.state == "succeeded":
            self.assertTrue(receipt["postconditions"])
            self.assertTrue(all(p["observed"] is not None and p["effected"]
                                for p in receipt["postconditions"]))

    def test_the_table_covers_every_shape_for_every_ported_scenario(self):
        tables = (set(SWEEP), set(LANDINGS), set(RECOVERIES), set(DISPOSALS))
        self.assertEqual(set().union(*tables), {(shape, scenario) for shape in SHAPES
                                                for scenario in SCENARIOS})
        for i, first in enumerate(tables):
            for second in tables[i + 1:]:
                self.assertEqual(first & second, set())

    def test_every_cell_lands_where_the_table_says(self):
        for (shape, scenario), (final, path, voided, (first, rest)) in SWEEP.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                world = World()
                transaction_id = drive(root, shape, scenario, world=world)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertReceipt(root, persisted)
                self.assertEqual(persisted.creation_key, f"{shape}:{scenario}")
                self.assertEqual(persisted.state, final)
                self.assertEqual(states_passed(persisted), path)
                self.assertEqual({e["external_state"] for e in transitions(persisted)
                                  if e["to"] != "attention_required"}, {"known"})
                self.assertEqual([e["type"] for e in persisted.events
                                  if e["type"].startswith("lease_")],
                                 CUSTODY_EVENTS[scenario])
                self.assertEqual({e["form"] for e in persisted.evidence
                                  if not e["admissible"]}, voided)
                latest = {}
                for entry in persisted.evidence:
                    latest[entry["evidence_id"].rsplit("@", 1)[0]] = entry
                self.assertTrue(latest)
                self.assertTrue(all(entry["admissible"] for entry in latest.values()))
                if scenario == "lease_lapse":
                    lapse = next(e["seq"] for e in persisted.events
                                 if e["type"] == "lease_lapse_detected")
                    for entry in persisted.evidence:
                        if entry["seq"] < lapse:
                            self.assertEqual(entry["admissible"], entry["form"] == "event")
                            if not entry["admissible"]:
                                self.assertEqual(entry["void_reason"], "fence_changed")
                    self.assertIsNone(persisted.custody)
                for key in persisted.concurrency_keys:
                    record = TransactionStore(root).inspect_lease(key)
                    self.assertEqual(
                        (record["epoch"], record["holder"]),
                        (2 if CUSTODY_EVENTS[scenario][1] == "lease_lapse_detected" else 1,
                         None))
                declared = [e["action_id"] for e in persisted.events
                            if e["type"] == "action_declared"]
                attempts = {e["action_id"]: e["attempt"] for e in persisted.events
                            if e["type"] == "invocation_intended"}
                self.assertEqual([attempts[a] for a in declared],
                                 [first] + [rest] * (len(declared) - 1))
                self.assertEqual(sorted(e["name"] for e in persisted.actions),
                                 declared_nodes(shape))
                self.assertEqual({e["status"] for e in persisted.actions}, {"satisfied"})
                self.assertEqual(set(world.invokes), set(declared))
                self.assertEqual(set(world.invokes.values()),
                                 {2 if scenario == "throttled_retry" else 1})
                if scenario == "throttled_retry":
                    for identity in declared:
                        self.assertEqual(
                            [(e["attempt"], e["result"], e["error_class"])
                             for e in persisted.events if e["type"] == "invocation_returned"
                             and e["action_id"] == identity],
                            [(1, "rejected", "provider_throttled"), (2, "accepted", None)])
                types = [e["type"] for e in persisted.events]
                self.assertEqual(types.count("anchors_verified"),
                                 0 if shape == "library" else 1)
                self.assertNotIn("evidence_recorded", types)
                self.assertEqual((types.count("proof_cohort_started"),
                                  types.count("proof_sealed")), (1, 1))
                seal = next(e for e in persisted.events if e["type"] == "proof_sealed")
                self.assertEqual(persisted.proof["proof_cutoff_at"], seal["at"])
                required = [o for o in persisted.proof["obligations"] if o["required"]]
                self.assertTrue(required)
                self.assertEqual({o["latest_outcome"] for o in required}, {"satisfied"})
                self.assertEqual(
                    sorted(u["name"] for u in persisted.proof_plan["units"]),
                    declared_nodes(shape))

    def test_every_new_row_lands_where_the_committed_table_says(self):
        for (shape, scenario), (final, path, expect) in LANDINGS.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                world = World()
                transaction_id = drive(Path(tmp), shape, scenario, world=world)
                persisted = TransactionStore(Path(tmp)).load(transaction_id)
                self.assertReceipt(Path(tmp), persisted)
                types = [e["type"] for e in persisted.events]
                self.assertEqual((persisted.state, states_passed(persisted)), (final, path))
                self.assertTrue(set(world.invokes.values()) <= {1})
                names = {u["action_id"]: u["name"] for u in persisted.proof_plan["units"]}
                observed = [e for e in persisted.events if e["type"] == "obligation_observed"]
                cohorts = persisted.proof["cohorts"]
                if final == "succeeded":
                    self.assertEqual(CUSTODY_EVENTS["success"],
                                     [t for t in types if t.startswith("lease_")])
                    self.assertEqual([c["status"] for c in cohorts], ["sealed"])
                    if "members" in expect:
                        self.assertEqual(persisted.proof_plan["cohort"]["members"],
                                         expect["members"])
                    continue
                self.assertEqual([t for t in types if t.startswith("lease_")],
                                 ["lease_acquired"])
                self.assertIsNotNone(persisted.custody)
                last = transitions(persisted)[-1]
                if "actions" in expect:
                    self.assertEqual({a["name"]: a["status"] for a in persisted.actions},
                                     expect["actions"])
                    self.assertEqual(observed, [])
                    stuck = [a["action_id"] for a in persisted.actions
                             if a["status"] != "satisfied"]
                    self.assertEqual([world.invokes[a] for a in stuck], [1])
                    continue
                self.assertEqual(last["reason"], expect["reason"])
                self.assertEqual(last["external_state"], "known")
                if expect["reason"] == "proof_rejected":
                    [rejected] = [e for e in persisted.events if e["type"] == "proof_rejected"]
                    self.assertEqual([names[i.rsplit(":", 1)[1]] for i in rejected["obligations"]],
                                     expect["rejected"])
                    self.assertEqual(cohorts, [])
                    latest = {o["obligation_id"]: o["latest_outcome"]
                              for o in persisted.proof["obligations"]}
                    for obligation_id in expect["satisfied"]:
                        self.assertEqual(latest[obligation_id], "satisfied")
                else:
                    self.assertEqual([(c["status"], c["reason"]) for c in cohorts],
                                     [("failed", r) for r in expect["failed"]])
                    [exhausted] = [e for e in persisted.events
                                   if e["type"] == "proof_convergence_exhausted"]
                    self.assertEqual((exhausted["cohorts"], exhausted["exhausted_by"]),
                                     (len(expect["failed"]), expect["exhausted_by"]))
                    park = last["seq"]
                    self.assertFalse([e for e in persisted.events if e["seq"] > park])

    def test_every_recovery_row_lands_where_the_committed_table_says(self):
        for (shape, scenario), (final, path, expect) in RECOVERIES.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root, world = Path(tmp), World()
                if final == "rejected":
                    with self.assertRaises(RecoveryPlanRejected) as caught:
                        drive(root, shape, scenario, world=world)
                    self.assertEqual(caught.exception.reason, "unsupported_operation")
                    self.assertIn(f"unit 'unsupported_promote' operation 'promote' is not "
                                  f"offered by effect {expect['binding']!r}",
                                  str(caught.exception))
                    self.assertEqual((list(root.iterdir()), world.invokes), ([], {}))
                    continue
                transaction_id = drive(root, shape, scenario, world=world)
                store = TransactionStore(root)
                persisted = store.load(transaction_id)
                self.assertReceipt(root, persisted)
                types = [e["type"] for e in persisted.events]
                self.assertEqual((persisted.state, states_passed(persisted)),
                                 (final, path or WITHOUT_ACTIVATION))
                self.assertTrue(set(world.invokes.values()) <= {1})
                if final == "succeeded":
                    self.assertNotIn("recovery_started", types)
                    continue
                plan = persisted.recovery_plan
                names = {u["action_id"]: u["name"] for u in plan["units"]}
                edges = {e["action_id"]: (u["name"], e["action"])
                         for u in plan["units"] for e in u["edges"]}
                last = {e["type"]: e for e in persisted.events}
                leases = [t for t in types if t.startswith("lease_")]
                if final == "rolled_back":
                    started, settled = last["recovery_started"], last["recovery_settled"]
                    self.assertEqual({names[i]: c for i, c in started["effect_snapshot"].items()},
                                     expect["snapshot"])
                    self.assertEqual([edges[i] for i in started["selected"]], expect["selected"])
                    self.assertEqual([names[c["unit"]] for c in started["checks"]],
                                     expect["checked"])
                    self.assertEqual([names[i] for i in settled["restored"]], expect["restored"])
                    self.assertEqual([names[r["unit"]] for r in settled["residue"]],
                                     expect["residue"])
                    self.assertEqual([world.invokes.get(i) for i in started["selected"]],
                                     [1] * len(started["selected"]))
                    self.assertEqual(leases, ["lease_acquired", "lease_released"])
                elif final == "abandoned":
                    self.assertIn(f"{expect['missing']} (", transitions(persisted)[-2]["reason"])
                    self.assertIn("rollback_anchor_missing", world.notes[0])
                    self.assertIn("no_effect", world.notes[-1])
                    self.assertEqual((persisted.actions, world.invokes), ((), {}))
                    self.assertEqual(leases, ["lease_acquired", "lease_released"])
                else:
                    link = persisted.events[-1]
                    self.assertEqual((link["type"], link["reason"]),
                                     ("roll_forward_linked", expect["forward"]))
                    self.assertIn(f"{expect['named']} (", world.notes[-1])
                    self.assertEqual(leases, ["lease_acquired"])
                    self.assertNotIn("recovery_started", types)
                    self.assertTrue({a["name"] for a in persisted.actions} <= set(names.values()))
                    child = store.load(link["child_transaction_id"])
                    self.assertNotEqual(child.transaction_id, transaction_id)
                    self.assertEqual((child.state, child.recovery["recovers"], child.creation_key),
                                     ("created", transaction_id, f"{shape}:{scenario}:forward"))
                    if expect["anchors"] is not None:
                        [anchors] = [e for e in persisted.events if e["type"] == "anchors_verified"]
                        self.assertEqual([names[a["unit"]] for a in anchors["anchors"]],
                                         expect["anchors"])

    def test_an_unobservable_release_parks_and_no_disposition_is_admitted(self):
        for (shape, scenario), (final, path) in DISPOSALS.items():
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                root, world = Path(tmp), World()
                transaction_id = drive(root, shape, scenario, world=world)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertReceipt(root, persisted)
                self.assertEqual((persisted.state, states_passed(persisted)), (final, path))
                self.assertEqual(transitions(persisted)[-1]["external_state"], "unknown")
                first = next(e["action_id"] for e in persisted.events
                             if e["type"] == "action_declared")
                self.assertIn(first, {u["action_id"] for u in persisted.proof_plan["units"]
                                      if u["phase"] == "publication"})
                self.assertEqual(world.invokes, {first: 1})
                self.assertEqual({a["action_id"]: a["status"] for a in persisted.actions
                                  if a["attempts"]}, {first: "unknown"})
                self.assertEqual([note.split(" refused: ")[1].split(":")[0]
                                  for note in world.notes],
                                 ["effect_uncertain", "effect_uncertain", "human_required"])
                types = [e["type"] for e in persisted.events]
                self.assertNotIn("failure_disposed", types)
                self.assertFalse((root / "receipts").exists())
                self.assertIsNotNone(persisted.custody)

    def test_the_gate_is_the_fourteen_prototype_scenarios_by_four_shapes(self):
        self.assertEqual(PROTOTYPE_SCENARIOS, (
            "success", "throttled_retry", "resume_after_crash", "partial_publication",
            "failed_activation", "stale_false_positive_health", "expired_snapshot",
            "fleet_stall", "rollback", "irreversible_migration", "incompatible_restore",
            "missing_rollback_anchor", "unsupported_operation", "unknown_external_state"))
        self.assertEqual(set(SCENARIOS) - set(PROTOTYPE_SCENARIOS),
                         {"lease_renewal", "lease_lapse"})
        self.assertEqual((len(SHAPES) * len(PROTOTYPE_SCENARIOS), len(SHAPES) * len(SCENARIOS)),
                         (56, 64))

    def test_the_four_gap_cells_sit_on_the_rows_that_exhibit_them(self):
        self.assertEqual(GAP_CELLS, {
            "subject identity": "stale_false_positive_health", "lease loss": "resume_after_crash",
            "convergence livelock": "expired_snapshot",
            "unobservable release": "unknown_external_state"})
        self.assertTrue(set(GAP_CELLS.values()) <= set(PROTOTYPE_SCENARIOS))
        self.assertEqual(LANDINGS[("platform", GAP_CELLS["subject identity"])][2]["reason"],
                         "proof_rejected")
        self.assertIn("lease_reacquired", CUSTODY_EVENTS[GAP_CELLS["lease loss"]])
        self.assertEqual(LANDINGS[("platform", GAP_CELLS["convergence livelock"])][2]["reason"],
                         "proof_did_not_converge")
        self.assertIn(("platform", GAP_CELLS["unobservable release"]), DISPOSALS)

    def test_every_shape_declares_a_feasible_plan_whose_units_are_its_nodes(self):
        for shape in SHAPES:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                created = TransactionStore(Path(tmp)).create(
                    "probe", {"s": shape}, concurrency_keys=["k"],
                    proof=shape_declaration(shape), recovery=shape_recovery(shape),
                    authority_class=AUTHORITY_CLASS)
                plan = created.proof_plan
                self.assertEqual(sorted(u["name"] for u in plan["units"]),
                                 declared_nodes(shape))
                self.assertEqual(sorted(u["name"] for u in created.recovery_plan["units"]),
                                 declared_nodes(shape))
                self.assertLessEqual(plan["cohort"]["makespan_ms"], 90_000)

    def test_the_crashed_action_reads_intent_inspection_then_retry(self):
        def epoch(event):
            return min(v["epoch"] for v in event["fence"].values()) if "fence" in event else None

        for shape in SHAPES:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                world = World()
                transaction_id = drive(Path(tmp), shape, "resume_after_crash", world=world)
                persisted = TransactionStore(Path(tmp)).load(transaction_id)
                first = next(e["action_id"] for e in persisted.events
                             if e["type"] == "action_declared")
                trail = [(e["type"], e.get("attempt"), e.get("outcome"), epoch(e))
                         for e in persisted.events if e.get("action_id") == first]
                self.assertEqual(trail, [
                    ("action_declared", None, None, None),
                    ("action_inspected", None, "absent", 1),
                    ("invocation_intended", 1, None, 1),
                    ("action_inspected", None, "absent", 2),
                    ("invocation_intended", 2, None, 2),
                    ("invocation_returned", 2, None, 2),
                    ("action_inspected", None, "satisfied", 2)])
                self.assertEqual(world.invokes[first], 1)

    def test_the_lapse_row_exercises_every_temporal_form_before_the_lapse(self):
        with tempfile.TemporaryDirectory() as tmp:
            forms = set()
            for shape in ("product", "daemon"):
                (Path(tmp) / shape).mkdir()
                transaction_id = drive(Path(tmp) / shape, shape, "lease_lapse")
                persisted = TransactionStore(Path(tmp) / shape).load(transaction_id)
                lapse = next(e["seq"] for e in persisted.events
                             if e["type"] == "lease_lapse_detected")
                forms |= {e["form"] for e in persisted.evidence if e["seq"] < lapse}
            self.assertEqual(forms, {"event", "snapshot", "interval"})

    def test_recreating_a_driven_cell_returns_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = drive(Path(tmp), "library", "success")
            store = TransactionStore(Path(tmp))
            persisted = store.load(first)
            again = store.create("library:success", dict(persisted.subject),
                                 concurrency_keys=list(persisted.concurrency_keys),
                                 proof=shape_declaration("library"),
                                 recovery=shape_recovery("library"),
                                 authority_class=AUTHORITY_CLASS)
            self.assertEqual(again.transaction_id, first)
            self.assertEqual(len(again.events), len(persisted.events))


PROJECT_NAMES = frozenset({"nix", "nixos", "darwin", "fagenorn", "palmier", "nodo", "argus"})
PROVIDER_NAMES = frozenset({
    "github", "gitlab", "gh", "git", "ghcr", "docker", "oci", "railway", "launchd",
    "launchctl", "plist", "homebrew", "brew", "cachix", "sops", "anthropic", "claude",
    "codex"})
PROVIDER_VERBS = frozenset({
    "push", "merge", "tag", "deploy", "switch", "restart", "rebuild", "upload", "rebase",
    "checkout"})
FORBIDDEN_WORDS = PROJECT_NAMES | PROVIDER_NAMES | PROVIDER_VERBS
_NOT_CODE = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                       tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER})


def _docstring_starts(source):
    starts = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                starts.add((first.value.lineno, first.value.col_offset))
    return starts


def neutrality_findings(source):
    """Every forbidden whole word in `source`'s code, comments and docstrings excluded."""
    docstrings = _docstring_starts(source)
    findings = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _NOT_CODE:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", token.string)
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        for word in re.split(r"[^0-9a-z]+", text.lower()):
            if word in FORBIDDEN_WORDS:
                findings.append((token.start[0], word))
    return findings


from agent_tools import (transaction_custody, transaction_disposition, transaction_history,
                         transaction_invocation, transaction_plan, transaction_proof,
                         transaction_receipt, transaction_recovery, transaction_recovery_plan,
                         transaction_storage)

NEUTRAL_MODULES = (transaction_core, transaction_history, transaction_receipt,
                   transaction_disposition, transaction_recovery, transaction_recovery_plan,
                   transaction_proof, transaction_plan, transaction_invocation,
                   transaction_custody, transaction_storage)


class NeutralityTest(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(transaction_core)

    def test_the_shipped_modules_name_no_project_provider_or_provider_verb(self):
        for module in NEUTRAL_MODULES:
            with self.subTest(module=module.__name__):
                self.assertEqual(neutrality_findings(inspect.getsource(module)), [])

    def test_a_provider_verb_planted_in_code_is_found(self):
        planted = self.source + "\n\ndef deploy_everything():\n    return None\n"
        self.assertEqual([word for _, word in neutrality_findings(planted)], ["deploy"])

    def test_the_same_word_in_a_comment_or_docstring_is_not_code(self):
        for planted in ("\n# deploy the candidate\n",
                        '\n\ndef neutral():\n    """Deploy nothing."""\n    return None\n'):
            with self.subTest(planted=planted):
                self.assertEqual(neutrality_findings(self.source + planted), [])

    def test_matching_is_by_whole_word_and_covers_string_literals(self):
        self.assertEqual(neutrality_findings("associated = 'pushed'\n"), [])
        self.assertEqual(neutrality_findings("where = 'git-tag'\n"), [(1, "git"), (1, "tag")])

    def test_camel_case_identifiers_are_split_on_case_boundaries(self):
        planted = ("class DeployRefused(Exception):\n    pass\n\n"
                   "x = GitPush\ny = HTTPServerRebase\n")
        self.assertEqual(neutrality_findings(planted),
                         [(1, "deploy"), (4, "git"), (4, "push"), (5, "rebase")])
        self.assertEqual(neutrality_findings("Pushed = Associated\n"), [])


if __name__ == "__main__":
    unittest.main()
