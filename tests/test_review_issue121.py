"""Issue-121 adapter: raw-parent ancestry, anchors, outcomes and payload (issue 234 D2, D5, D17; S9, S16, S17)."""
import copy
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
from agent_tools.review_budget import describe
from agent_tools.review_forecast import ForecastError
from agent_tools.review_git import HistoryError
from agent_tools.review_issue121 import (ContributionError, classify, contribution_edges, derive_121, plan_anchors,
                                         reconstruct_boundary, unavailable_ids, validate_121)

from .retained_review_test_support import (commit_files, git, linear_fixture, rehash_edges, snapshot,
                                           source_budget_env, ssh_signer, task7_fixture)

COMMON = {"boundary", "state", "prerequisite", "edge_ids", "estimate_refs"}
LABELS = ["aggregate.actual", "aggregate.projected", "tasks-1-3", "tasks-4-6", "tasks-7-8"]


def outcomes(payload):
    return [payload["aggregate"]["actual"], payload["aggregate"]["projected"], *payload["boundaries"]]


def rehash(row):
    return {**row, "id": telemetry_digest({k: v for k, v in row.items() if k != "id"})}


def edge_of(payload, commit):
    return next(e["id"] for e in payload["edges"] if e["commit"] == commit)


class Fixture:
    def build(self, tmp, **shape):
        repo, pins = linear_fixture(tmp, **shape)
        task7_pins, table = task7_fixture(repo, pins)
        with patch.dict(os.environ, source_budget_env(tmp), clear=True):
            authority = describe("review-package")
        return repo, pins, task7_pins, table, authority


class AncestryTest(Fixture, unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.pins, self.task7_pins, self.table, self.authority = self.build(self.tmp)
        self.edges = list(contribution_edges(self.repo, self.pins, classify(self.repo, self.pins)))

    def selector(self, edges):
        return reconstruct_boundary(self.repo, self.pins, boundary="tasks-1",
                                    prerequisite={"kind": "delivery-base"}, edges=edges, table=self.table,
                                    task7_pins=self.task7_pins, authority=self.authority)

    def entry_points(self, edges, env):
        def scoped(call):
            def run():
                with patch.dict(os.environ, env):
                    return call()
            return run
        return (scoped(lambda: contribution_edges(self.repo, self.pins, classify(self.repo, self.pins))),
                scoped(lambda: derive_121(self.repo, self.pins, self.task7_pins, self.authority)),
                scoped(lambda: self.selector(edges)))

    def test_clean_control_has_one_raw_edge_per_commit(self):
        commits = [c for c, _, _ in self.pins.assignments]
        self.assertEqual([e["commit"] for e in self.edges], commits)
        self.assertEqual([e["parent"] for e in self.edges], [self.pins.base, *commits[:-1]])
        self.assertEqual({e["parent_ordinal"] for e in self.edges}, {1})
        self.assertIn(self.selector(self.edges)["state"], {"measured", "projection_unavailable"})

    def test_clean_payload_validates_over_one_history(self):
        self.assertEqual(self.task7_pins.prerequisite_commit, self.pins.head)
        before = snapshot(self.repo)
        payload = derive_121(self.repo, self.pins, self.task7_pins, self.authority)
        self.assertEqual(snapshot(self.repo), before)
        self.assertIsNone(validate_121(payload, self.pins, self.table))
        self.assertEqual([r["boundary"] for r in payload["boundaries"]], ["tasks-1-3", "tasks-4-6", "tasks-7-8"])

    def test_virtualized_history_is_invalid_at_both_entry_points(self):
        commits = [c for c, _, _ in self.pins.assignments]
        target, extra = commits[3], commits[0]
        forged = rehash_edges(self.edges[:4] + [{**self.edges[3], "parent": extra, "parent_ordinal": 2}]
                              + self.edges[4:])
        gitdir = Path(git(self.repo, "rev-parse", "--absolute-git-dir"))
        outside = self.tmp / "grafts"; outside.write_text(f"{target} {commits[2]} {extra}\n")
        attacks = {
            "graft": (lambda: (gitdir / "info/grafts").write_text(f"{target} {commits[2]} {extra}\n"), {}),
            "replace_ref": (lambda: git(self.repo, "replace", "--graft", target, commits[2], extra), {}),
            "alternate_replace_base": (lambda: git(self.repo, "replace", "--graft", target, commits[2], extra,
                                                   env={"GIT_REPLACE_REF_BASE": "refs/alt/"}),
                                       {"GIT_REPLACE_REF_BASE": "refs/alt/"}),
            "shallow": (lambda: (gitdir / "shallow").write_text(commits[1] + "\n"), {}),
            "GIT_DIR": (lambda: None, {"GIT_DIR": str(gitdir)}),
            "GIT_OBJECT_DIRECTORY": (lambda: None, {"GIT_OBJECT_DIRECTORY": str(gitdir / "objects")}),
            "GIT_GRAFT_FILE": (lambda: None, {"GIT_GRAFT_FILE": str(outside)}),
        }
        for name, (apply, env) in attacks.items():
            with self.subTest(attack=name):
                apply()
                before = snapshot(self.repo)  # the entry points, not the attack setup, must write nothing
                try:
                    for call in self.entry_points(forged, env):
                        with self.assertRaises(ContributionError) as caught:
                            call()
                        self.assertEqual(caught.exception.code, "history_unauthenticated")
                        self.assertIsInstance(caught.exception.__cause__, (HistoryError, ForecastError))
                    self.assertEqual(snapshot(self.repo), before)
                finally:
                    for path in (gitdir / "info/grafts", gitdir / "shallow"):
                        path.unlink(missing_ok=True)
                    for ref in git(self.repo, "for-each-ref", "--format=%(refname)", "refs/replace/",
                                   "refs/alt/").split():
                        git(self.repo, "update-ref", "-d", ref)

    def test_rehashed_parent_deletion_or_reorder_is_invalid(self):
        for forged in (rehash_edges(self.edges[:2] + self.edges[3:]),
                       rehash_edges([self.edges[1], self.edges[0], *self.edges[2:]]),
                       rehash_edges(self.edges + [{**self.edges[-1], "parent_ordinal": 2}])):
            with self.assertRaises(ContributionError) as caught:
                self.selector(forged)
            self.assertEqual(caught.exception.code, "edge_table_mismatch")

    def test_hunk_header_digest_change_is_invalid(self):
        edge = self.edges[0]
        record = {**edge["records"][0], "hunk_header_sha256": "sha256:" + "0" * 64}
        self.assertNotEqual(edge["records"][0]["hunk_header_sha256"], record["hunk_header_sha256"])
        with self.assertRaises(ContributionError) as caught:
            self.selector(rehash_edges([{**edge, "records": [record, *edge["records"][1:]]}, *self.edges[1:]]))
        self.assertEqual(caught.exception.code, "edge_table_mismatch")

    def test_assignment_mutations_fail(self):
        rows = list(self.pins.assignments)
        first = rows[0]
        cases = {
            "unknown": [*rows[:2], ("f" * 40, 1, None), *rows[2:]],
            "task_zero": [(first[0], 0, None), *rows[1:]],
            "boolean_owner": [(first[0], True, None), *rows[1:]],
            "duplicate": [first, *rows],
            "multiple": [first, (first[0], 2, None), *rows[1:]],
            "owner_7": [(first[0], 7, None), *rows[1:]],
            "owner_8": [(first[0], 8, None), *rows[1:]],
            "reordered": [rows[1], rows[0], *rows[2:]],
            "omitted": rows[1:],
        }
        for name, mutated in cases.items():
            with self.subTest(case=name), self.assertRaises(ContributionError) as caught:
                classify(self.repo, replace(self.pins, assignments=tuple(mutated)))
            self.assertEqual(caught.exception.code, "assignment_mismatch")

    def test_forged_or_wrong_key_signature_and_substituted_plan_blob_fail(self):
        anchors = plan_anchors(self.repo, self.pins)
        self.assertEqual(len(anchors), 9)
        self.assertEqual({row["commit"] for row in anchors}, {self.pins.base})
        member = f"{self.pins.plan_prefix}.tasks/task-3.md"
        (self.tmp / "other").mkdir()
        other_key, _ = ssh_signer(self.tmp / "other")
        pins = self.pins
        for name, key in (("unsigned", None), ("wrong_key", other_key)):
            commit = commit_files(self.repo, {member: f"rewritten {name}\n".encode()}, name, sign_key=key)
            pins = replace(pins, head=commit, assignments=pins.assignments + ((commit, 0, "process"),))
            with self.subTest(writer=name), self.assertRaises(ContributionError) as caught:
                plan_anchors(self.repo, pins)
            self.assertEqual(caught.exception.code, "anchor_signature_invalid")
        root, task7 = self.pins.plan_blobs
        substituted = replace(self.pins, plan_blobs=((root[0], git(self.repo, "rev-parse",
                                                                   f"{self.pins.base}:{member}")), task7))
        with self.assertRaises(ContributionError) as caught:
            plan_anchors(self.repo, substituted)
        self.assertEqual(caught.exception.code, "anchor_blob_mismatch")

    def test_future_only_boundary_has_prerequisite_tree_and_table_records(self):
        payload = derive_121(self.repo, self.pins, self.task7_pins, self.authority)
        row = payload["boundaries"][2]
        head_tree = git(self.repo, "rev-parse", self.pins.head + "^{tree}")
        self.assertEqual(row["state"], "measured")  # this fixture's table composes
        self.assertEqual(row["prerequisite"], {"kind": "completed-tasks", "tasks": [1, 2, 3, 4, 5, 6],
                                               "commit": self.pins.head, "tree": head_tree})
        self.assertEqual(row["result_tree"], head_tree)
        self.assertEqual((row["edge_ids"], row["estimate_refs"]), ([], [telemetry_digest(self.table)]))
        records = [r for r in payload["records"] if r["scope"] == "tasks-7-8"]
        self.assertEqual(row["record_refs"], [r["id"] for r in records])
        expected = []
        for bound in self.table["rows"]:
            write, output = bound["operation"] == "write", bound.get("output", {"lines": 0})
            expected.append({"kind": "estimate", "scope": "tasks-7-8", "path": bound["new_path"],
                             "record_bytes": bound["record_bytes"], "added_lines": output["lines"],
                             "deleted_lines": bound["input"]["lines"] if write else 0})
        self.assertEqual([{k: v for k, v in r.items() if k != "id"} for r in records], expected)


class RouteTest(Fixture, unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def test_late_fix_touching_excluded_path_yields_unavailable_with_that_edge(self):
        repo, pins, task7_pins, table, authority = self.build(self.tmp, owners=(1, 2, 3, 6, 3), touches={4: 3})
        payload = derive_121(repo, pins, task7_pins, authority)
        self.assertIsNone(validate_121(payload, pins, table))
        commits = [c for c, _, _ in pins.assignments]
        row = payload["boundaries"][0]
        self.assertEqual(row["state"], "projection_unavailable")
        self.assertEqual(row["edge_ids"], [edge_of(payload, commits[n]) for n in (0, 1, 2, 4)])
        self.assertEqual(row["failure"], {"stage": "reconstruction", "code": "whole_path_preimage_unproved",
                                          "evidence_refs": [edge_of(payload, commits[4])]})
        selected = [e for e in payload["edges"] if e["owner"] in (1, 2, 3)]
        self.assertEqual(reconstruct_boundary(repo, pins, boundary="tasks-1-3", prerequisite={"kind": "delivery-base"},
                                              edges=payload["edges"], table=table, task7_pins=task7_pins,
                                              authority=authority), row)
        self.assertEqual(len(selected), 4)

    def test_prerequisite_without_matching_closure_is_unavailable(self):
        repo, pins, task7_pins, table, authority = self.build(self.tmp, owners=(1, 2, 4, 3, 5, 6))
        payload = derive_121(repo, pins, task7_pins, authority)
        self.assertIsNone(validate_121(payload, pins, table))
        commits = [c for c, _, _ in pins.assignments]
        row = payload["boundaries"][1]
        self.assertEqual(row["prerequisite"], {"kind": "completed-tasks", "tasks": [1, 2, 3],
                                               "commit": None, "tree": None})
        self.assertEqual(row["failure"], {"stage": "prerequisite", "code": "prerequisite_composition_unsupported",
                                          "evidence_refs": [edge_of(payload, commits[2])]})
        self.assertEqual(row["edge_ids"], [edge_of(payload, commits[n]) for n in (2, 4, 5)])
        self.assertIn("tasks-4-6", unavailable_ids(payload))


class PayloadTest(Fixture, unittest.TestCase):
    """Mutations of one clean payload: tasks 1-3 stop at commit 4, and commit 5 follows the failure."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.repo, cls.pins, _, cls.table, _ = shape = cls().build(cls.tmp, owners=(1, 2, 3, 6, 3, 2),
                                                                   touches={4: 3})
        cls.payload = derive_121(cls.repo, cls.pins, shape[2], shape[4])
        validate_121(cls.payload, cls.pins, cls.table)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def refused(self, mutate, *, no_table=False):
        payload = copy.deepcopy(self.payload)
        mutate(payload)
        with self.assertRaises(ContributionError) as caught:
            validate_121(payload, self.pins, None if no_table else self.table)
        self.assertEqual(caught.exception.code, "invalid_payload")

    def unavailable(self, payload, label, code):
        """`label`'s row as an estimate-stage failure, with its records gone."""
        row = next(r for r in outcomes(payload) if r["boundary"] == label)
        for key in ("result_tree", "record_refs", "measurement"):
            row.pop(key)
        row.update(state="projection_unavailable", failure={"stage": "estimate", "code": code, "evidence_refs": []})
        payload["records"] = [r for r in payload["records"] if r["scope"] != label]

    def test_tasks_7_8_outcome_is_bound_to_the_table(self):
        self.refused(lambda p: self.unavailable(p, "tasks-7-8", "unsupported_composition"))

        def untabled(p, future_code):  # what derive_121 writes when no Task-7 table derives
            for label, code in (("aggregate.projected", "inventory_mismatch"), ("tasks-7-8", future_code)):
                self.unavailable(p, label, code)
                next(r for r in outcomes(p) if r["boundary"] == label)["estimate_refs"] = []
        control = copy.deepcopy(self.payload)
        untabled(control, "inventory_mismatch")
        self.assertIsNone(validate_121(control, self.pins, None))
        self.refused(lambda p: untabled(p, "unsupported_estimate"), no_table=True)

    def failed(self, payload):
        return payload["boundaries"][0]

    def scope(self, payload, label):
        return [r for r in payload["records"] if r["scope"] == label]

    def test_unavailable_row_with_tree_metrics_or_records_fails_validation(self):
        self.assertEqual(self.failed(self.payload)["state"], "projection_unavailable")
        measured = self.payload["aggregate"]["actual"]
        for extra in ({"result_tree": "0" * 40}, {"measurement": measured["measurement"]},
                      {"record_refs": []}, {"budget_status": "within_budget"}, {"metrics": None}):
            with self.subTest(extra=sorted(extra)):
                self.refused(lambda p: self.failed(p).update(extra))
        def stray_record(p):
            row = rehash({**self.scope(p, "aggregate.actual")[0], "scope": "tasks-1-3"})
            p["records"].insert(len(self.scope(p, "aggregate.actual")) + len(self.scope(p, "aggregate.projected")), row)
        self.refused(stray_record)

    def test_edge_removed_or_reordered_after_failure_fails_validation(self):
        ids = self.failed(self.payload)["edge_ids"]
        self.assertEqual(self.failed(self.payload)["failure"]["evidence_refs"], [ids[3]])
        self.assertEqual(len(ids), 5)  # one selected edge follows the failed one
        for edited in (ids[:4], ids[:3] + ids[4:], [*ids[:3], ids[4], ids[3]], list(reversed(ids))):
            with self.subTest(edge_ids=len(edited)):
                self.refused(lambda p: self.failed(p).update(edge_ids=edited))

    def test_forged_or_removed_failure_reference_fails(self):
        failure = self.failed(self.payload)["failure"]
        excluded = next(e["id"] for e in self.payload["edges"] if e["owner"] == 6)
        for refs in (["sha256:" + "0" * 64], [excluded], [], failure["evidence_refs"] * 2):
            with self.subTest(refs=len(refs)):
                self.refused(lambda p: self.failed(p)["failure"].update(evidence_refs=refs))
        self.refused(lambda p: self.failed(p).pop("failure"))

    def test_duplicate_final_record_fails(self):
        def duplicate(p):
            first = self.scope(p, "aggregate.actual")[0]
            twin = rehash({**first, "record_bytes": first["record_bytes"] + 1})
            p["records"].insert(1, twin)
            p["aggregate"]["actual"]["record_refs"].insert(1, twin["id"])
        self.refused(duplicate)

    def test_record_refs_resolve_exactly_once(self):
        actual, projected = (self.payload["aggregate"][k]["record_refs"] for k in ("actual", "projected"))
        self.assertTrue(actual and projected)
        def other_scope(p):  # relocated in table order, so only the reference rule can refuse it
            future = {r["path"] for r in self.scope(p, "tasks-7-8")}
            moved = next(r for r in self.scope(p, "aggregate.projected") if r["path"] not in future)
            p["records"].remove(moved)
            relabeled = rehash({**moved, "scope": "tasks-7-8"})
            first = p["records"].index(self.scope(p, "tasks-7-8")[0])
            p["records"].insert(first + sum(path < moved["path"] for path in future), relabeled)
            keys = [(LABELS.index(r["scope"]), r["path"]) for r in p["records"]]
            self.assertEqual(keys, sorted(set(keys)))
            refs = p["aggregate"]["projected"]["record_refs"]
            refs[refs.index(moved["id"])] = relabeled["id"]
        mutations = {
            "unresolved": lambda p: p["aggregate"]["actual"]["record_refs"].__setitem__(0, "sha256:" + "0" * 64),
            "twice": lambda p: p["aggregate"]["actual"]["record_refs"].append(actual[0]),
            "two_outcomes": lambda p: p["aggregate"]["projected"]["record_refs"].append(actual[0]),
            "unreferenced": lambda p: p["aggregate"]["actual"]["record_refs"].pop(),
            "other_scope": other_scope,
            "wrong_estimate": lambda p: p["aggregate"]["projected"].update(estimate_refs=["sha256:" + "0" * 64]),
            "estimate_on_actual": lambda p: p["boundaries"][0].update(
                estimate_refs=[telemetry_digest(self.table)]),
            "missing_estimate": lambda p: p["boundaries"][2].update(estimate_refs=[]),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                self.refused(mutate)

    def test_payload_rows_are_closed(self):
        states = {}
        for label, row in zip(LABELS, outcomes(self.payload)):
            states[label] = row["state"]
            self.assertEqual(row["boundary"], label)
            if row["state"] == "measured":
                self.assertEqual(set(row), COMMON | {"result_tree", "record_refs", "measurement"})
                self.assertEqual(set(row["measurement"]), {"package_name", "packing_policy_sha256",
                                                           "artifact_policy_sha256", "metrics", "budget_status",
                                                           "violations"})
            else:
                self.assertEqual(set(row), COMMON | {"failure"})
                self.assertEqual(set(row["failure"]), {"stage", "code", "evidence_refs"})
        # This fixture forces both states: the late fix stops tasks 1-3 and leaves no tasks 1-3 closure.
        self.assertEqual({states["tasks-1-3"], states["tasks-4-6"]}, {"projection_unavailable"})
        self.assertEqual(unavailable_ids(self.payload), ("tasks-1-3", "tasks-4-6"))
        commit = self.pins.assignments[4][0]  # the late fix also fails the tasks 1-3 dependency replay
        self.assertEqual(self.payload["boundaries"][1]["failure"],
                         {"stage": "prerequisite", "code": "dependency_unavailable",
                          "evidence_refs": [edge_of(self.payload, commit)]})
        for record in self.payload["records"]:
            extra = {"record_sha256", "edge_ids"} if record["kind"] == "actual" else {"added_lines", "deleted_lines"}
            self.assertEqual(set(record), {"id", "kind", "scope", "path", "record_bytes"} | extra)
        self.refused(lambda p: p["aggregate"]["actual"].update(status=None))
        self.refused(lambda p: p["aggregate"]["actual"]["measurement"].update(status=None))


if __name__ == "__main__":
    unittest.main()
