"""Issue-121 compact payload, schema 4: expansion to SOURCE's model, canonical form and refusals (issue 254)."""
import copy, json, os, shutil, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_budget import describe
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue121 import (ContributionError, compact_121, derive_121, expand_121, model_121,
                                         unavailable_ids, validate_121)

from .retained_review_test_support import commit_files, linear_fixture, source_budget_env, task7_fixture

MEMBERS = {"schema_version", "kind", "range", "classes", "paths", "entries", "edges", "signer_sha256", "anchors",
           "records", "outcomes", "operational_effects", "record_table_policy"}
KINDS = ({"k": 1}, [1], "s", 7, True, None)
LATE_FIX = dict(owners=(1, 2, 3, 6, 3, 2), touches={4: 3})  # tasks 1-3 stop at commit 4; commit 5 follows


def wire(value):
    """`value` as a consumer reads it from a bundle file."""
    return json.loads(canonical_bytes(value))


def built(tmp, extend=None, **shape):
    """`(repo, pins, task7_pins, table, authority)` over `linear_fixture`; `extend(repo, pins)` returns later pins."""
    repo, pins = linear_fixture(tmp, **shape)
    pins = extend(repo, pins) if extend else pins
    task7_pins, table = task7_fixture(repo, pins)
    with patch.dict(os.environ, source_budget_env(tmp), clear=True):
        return repo, pins, task7_pins, table, describe("review-package")


def swapped(repo, pins):
    """Three task-3 commits: a directory, the file that replaces it, and the directory that replaces the file."""
    commits = [commit_files(repo, files, "swap") for files in (
        {"dir/inner.txt": b"inner\n"}, {"dir/inner.txt": None, "dir": b"file\n"},
        {"dir": None, "dir/again.txt": b"again\n"})]
    return replace(pins, head=commits[-1], assignments=pins.assignments + tuple((c, 3, None) for c in commits))


def rewritten(tmp):
    def extend(repo, pins):
        member = f"{pins.plan_prefix}.tasks/task-3.md"
        commits = [commit_files(repo, {member: text}, "plan", sign_key=tmp / "signer")
                   for text in (b"first rewrite\n", b"second rewrite\n")]
        commits.append(commit_files(repo, {"src/late.txt": b"late\n"}, "late"))
        return replace(pins, head=commits[-1],
                       assignments=pins.assignments + tuple((c, 0, "process") for c in commits))
    return extend


class Compact121Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); cls.addClassCleanup(shutil.rmtree, cls.tmp)
        (cls.tmp / "late").mkdir()
        cls.repo, cls.pins, cls.task7_pins, cls.table, cls.authority = built(cls.tmp / "late", **LATE_FIX)
        cls.model = model_121(cls.repo, cls.pins, cls.task7_pins, cls.authority)
        cls.payload = wire(compact_121(cls.model))

    def refused(self, mutate, payload=None, pins=None, table=None):
        forged = copy.deepcopy(payload or self.payload)
        mutate(forged)
        with self.assertRaises(ContributionError) as caught:
            validate_121(forged, pins or self.pins, table or self.table)
        self.assertEqual(caught.exception.code, "invalid_payload")

    def shape(self, name, extend=None, **shape):
        (self.tmp / name).mkdir()
        repo, pins, task7_pins, table, authority = built(self.tmp / name, extend, **shape)
        return model_121(repo, pins, task7_pins, authority), pins, table

    def test_payload_is_closed_and_expands_to_the_source_model(self):
        self.assertEqual((set(self.payload), self.payload["schema_version"]), (MEMBERS, 4))
        self.assertEqual(self.model["schema_version"], 3)
        self.assertEqual(canonical_bytes(expand_121(self.payload)), canonical_bytes(self.model))
        self.assertEqual(canonical_bytes(validate_121(self.payload, self.pins, self.table)), canonical_bytes(self.model))
        self.assertEqual(derive_121(self.repo, self.pins, self.task7_pins, self.authority), compact_121(self.model))
        self.assertEqual(unavailable_ids(expand_121(self.payload)), ("tasks-1-3", "tasks-4-6"))
        self.assertLess(len(canonical_bytes(self.payload)), len(canonical_bytes(self.model)) // 2)

    def test_every_fixture_shape_round_trips(self):
        shapes = {"measured": {}, "interleaved": dict(owners=(1, 2, 4, 3, 5, 6)), "swap": dict(owners=(1, 2), extend=swapped)}
        for name, shape in shapes.items():
            with self.subTest(shape=name):
                model, pins, table = self.shape(name, **shape)
                payload = wire(compact_121(model))
                self.assertEqual(canonical_bytes(validate_121(payload, pins, table)), canonical_bytes(model))
                self.assertEqual(compact_121(expand_121(payload)), payload)

    def test_source_encoding_and_other_versions_are_refused(self):
        for label, forged in (("source model", self.model), ("version 3", {**self.payload, "schema_version": 3}),
                              ("boolean version", {**self.payload, "schema_version": True}),
                              ("extra member", {**self.payload, "aggregate": {}}), ("list", [self.payload])):
            for call in (expand_121, lambda p: validate_121(p, self.pins, self.table)):
                with self.subTest(label), self.assertRaises(ContributionError) as caught:
                    call(forged)
                self.assertEqual(caught.exception.code, "invalid_payload")

    def test_malformed_model_is_invalid_payload(self):
        for forged in (self.payload, {**self.model, "anchors": []}, {**self.model, "boundaries": [[]]}):
            with self.subTest(members=sorted(forged)[:2]), self.assertRaises(ContributionError) as caught:
                compact_121(forged)
            self.assertEqual(caught.exception.code, "invalid_payload")

    def test_every_malformed_member_is_invalid_payload(self):
        payload, variants = self.payload, []

        def put(path, value):
            forged = copy.deepcopy(payload)
            holder = forged
            for key in path[:-1]:
                holder = holder[key]
            if value is KINDS:  # removal
                del holder[path[-1]]
            else:
                holder[path[-1]] = value
            return forged

        def spread(path, value):
            variants.extend(put(path, kind) for kind in KINDS if type(kind) is not type(value))
            variants.append(put(path, KINDS))
        for key, value in payload.items():
            spread((key,), value)
        failed = next(n for n, row in enumerate(payload["outcomes"]) if row["state"] != "measured")
        rows = [("classes", 0), ("classes", 3), ("entries", 0), ("edges", 0), ("edges", 0, 0), ("anchors", 0),
                ("records", "aggregate.actual"), ("records", "aggregate.actual", "rows", 0),
                ("records", "tasks-7-8", "rows", 0), ("outcomes", 0), ("outcomes", 0, "measurement"),
                ("outcomes", failed), ("outcomes", failed, "failure"), ("range",), ("outcomes",)]
        for path in rows:
            row = payload
            for key in path:
                row = row[key]
            for key, value in (row.items() if isinstance(row, dict) else enumerate(row)):
                spread((*path, key), value)
        self.assertGreater(len(variants), 300)
        for variant in variants:
            with self.subTest(variant=repr(variant)[:160]):
                with self.assertRaises(ContributionError) as caught:
                    validate_121(variant, self.pins, self.table)
                self.assertEqual(caught.exception.code, "invalid_payload")

    def test_altered_inputs_of_recomputed_members_are_refused(self):
        def exchange(rows, a, b):
            rows[a], rows[b] = rows[b], rows[a]
        failed = self.payload["outcomes"][2]
        self.assertEqual((failed["state"], failed["failure"]["evidence_refs"]), ("projection_unavailable", [4]))
        actual = self.payload["records"]["aggregate.actual"]["rows"]
        self.assertEqual(self.payload["outcomes"][3]["failure"], {
            "stage": "prerequisite", "code": "dependency_unavailable", "evidence_refs": [4]})

        def unestimated(p, code):  # the projection as an estimate-stage failure, its records gone
            p["records"].pop("aggregate.projected")
            kept = {k: p["outcomes"][1][k] for k in ("prerequisite", "estimate_refs")}
            p["outcomes"][1] = {**kept, "state": "projection_unavailable",
                                "failure": {"stage": "estimate", "code": code, "evidence_refs": []}}
        control = copy.deepcopy(self.payload)
        unestimated(control, "unsupported_composition")
        self.assertEqual(unavailable_ids(validate_121(control, self.pins, self.table))[0], "aggregate.projected")
        cases = {
            "class_moved": lambda p: exchange(p["classes"], 0, 1),
            "class_removed": lambda p: p["classes"].pop(),
            "class_reowned": lambda p: p["classes"][0].__setitem__(1, 2),
            "class_reason_added": lambda p: p["classes"][0].append("process"),
            "edge_removed": lambda p: p["edges"].pop(2),
            "edge_added": lambda p: p["edges"].append([]),
            "edge_record_path": lambda p: p["edges"][0][0].__setitem__(1, p["edges"][1][0][1]),
            "record_row_in_another_scope": lambda p: p["records"].setdefault(
                "tasks-1-3", {"kind": "actual", "rows": []})["rows"].append(p["records"]["aggregate.actual"]["rows"].pop(0)),
            "record_row_duplicated": lambda p: p["records"]["aggregate.actual"]["rows"].insert(1, list(actual[0])),
            "record_rows_reordered": lambda p: exchange(p["records"]["aggregate.actual"]["rows"], 0, 1),
            "record_kind": lambda p: p["records"]["aggregate.actual"].update(kind="estimate"),
            "estimate_row_bytes": lambda p: p["records"]["tasks-7-8"]["rows"][0].__setitem__(1, 1),
            "failure_ref_outside_selection": lambda p: p["outcomes"][2]["failure"].update(evidence_refs=[3]),
            "failure_ref_removed": lambda p: p["outcomes"][2]["failure"].update(evidence_refs=[]),
            "failure_ref_repeated": lambda p: p["outcomes"][2]["failure"].update(evidence_refs=[4, 4]),
            "failure_ref_out_of_range": lambda p: p["outcomes"][2]["failure"].update(evidence_refs=[6]),
            "signer": lambda p: p.update(signer_sha256="sha256:" + "0" * 64),
            "anchor_removed": lambda p: p["anchors"].pop(),
            "outcome_removed": lambda p: p["outcomes"].pop(),
            "outcome_boundary_stored": lambda p: p["outcomes"][0].update(boundary="aggregate.actual"),
            "result_tree": lambda p: p["outcomes"][4].update(result_tree="f" * 40),
            "prerequisite_tree_removed": lambda p: p["outcomes"][4]["prerequisite"].update(tree=None),
            "dependency_ref_outside_tasks_1_3": lambda p: p["outcomes"][3]["failure"].update(evidence_refs=[3]),
            "dependency_code_exchanged": lambda p: p["outcomes"][3]["failure"].update(
                code="prerequisite_composition_unsupported"),
            "estimate_rows_under_an_actual_outcome": lambda p: p["records"].update(
                {"aggregate.actual": p["records"]["tasks-7-8"]}),
            "invented_estimate_code": lambda p: unestimated(p, "invented"),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.refused(mutate)

    def test_anchor_is_bound_to_the_latest_edge_writing_its_path(self):
        model, pins, table = self.shape("anchors", extend=rewritten(self.tmp / "anchors"), owners=(1, 2))
        payload = wire(compact_121(model))
        member = payload["paths"].index(f"{pins.plan_prefix}.tasks/task-3.md")
        n = next(n for n, row in enumerate(payload["anchors"]) if row[0] == member)
        writers = [c for c, _, reason in pins.assignments if reason == "process"]
        self.assertEqual(payload["anchors"][n][1], writers[1])
        for name, change in {"earlier_writer": (1, writers[0]), "later_non_writer": (1, writers[2]), "base": (1, pins.base),
                             "foreign_blob": (2, "f" * 40)}.items():
            with self.subTest(case=name):
                self.refused(lambda p: p["anchors"][n].__setitem__(*change), payload, pins, table)

    def test_noncanonical_spellings_of_the_same_facts_are_refused(self):
        self.assertEqual(expand_121({**self.payload, "paths": [*self.payload["paths"], "zz/unused"]}), expand_121(self.payload))
        group = next(n for n, row in enumerate(self.payload["entries"]) if len(row[2]) > 1)

        def reversed_group(p):
            first = sum(len(row[2]) for row in p["entries"][:group])
            size = len(p["entries"][group][2])
            p["entries"][group][2].reverse()
            for edge in p["edges"]:
                for row in edge:
                    for side in (2, 3):
                        if row[side] is not None and first <= row[side] < first + size:
                            row[side] = first + (size - 1 - (row[side] - first))
        cases = {"unused_path": lambda p: p["paths"].append("zz/unused"),
                 "unused_entry": lambda p: p["entries"][-1][2].append("f" * 40),
                 "duplicate_path": lambda p: p["paths"].append(p["paths"][-1]),
                 "reversed_entry_group": reversed_group,
                 "negative_path_index": lambda p: p["anchors"][0].__setitem__(0, p["anchors"][0][0] - len(p["paths"])),
                 "true_for_one": lambda p: p["classes"][0].__setitem__(1, True),
                 "empty_record_scope": lambda p: p["records"].update({"tasks-1-3": {"kind": "actual", "rows": []}})}
        self.assertEqual(self.payload["classes"][0][1], 1)
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.refused(mutate)

    def test_file_and_directory_swap_keeps_its_tree_entries(self):
        model, pins, table = self.shape("swapped", extend=swapped, owners=(1, 2))
        payload = wire(compact_121(model))
        kinds = [row[1] for row in payload["entries"]]
        self.assertIn("tree", kinds)
        first = sum(len(row[2]) for row in payload["entries"][:kinds.index("tree")])
        trees = range(first, first + len(payload["entries"][kinds.index("tree")][2]))
        sides = [(e, n, side) for e, edge in enumerate(payload["edges"]) for n, row in enumerate(edge)
                 for side in (2, 3) if row[side] in trees]
        directory = payload["paths"].index("dir")
        self.assertEqual([(payload["edges"][e][n][0], payload["edges"][e][n][1], side) for e, n, side in sides],
                         [("A", directory, 2), ("D", directory, 3)])
        blob = payload["edges"][0][0][3]
        for e, n, side in sides:
            with self.subTest(edge=e):
                self.refused(lambda p: p["edges"][e][n].__setitem__(side, blob), payload, pins, table)


if __name__ == "__main__":
    unittest.main()
