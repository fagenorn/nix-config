# Task 1: Issue-121 payload, schema version 4

The issue-121 model gains its compact payload (spec § *Solution*, § *Issue-121 payload*; CP1, CP3, CP4, CP6, CP7, CP8, CP9, CP13, CP14, CP15, CP17). After this task `derive_121` returns the payload, `validate_121` takes it and returns the model, and the witness digests the model. Issue 100 is untouched until Task 2.

**Files:**
- Modify: `python/agent_tools/review_issue121.py`
- Modify: `python/agent_tools/review_witness.py` (first of two contributions)
- Modify: `python/agent_tools/review_derivation.py` (first of two)
- Modify: `python/agent_tools/review_replay.py` (docstrings only)
- Create: `tests/test_review_compact121.py`
- Modify: `tests/test_review_issue121.py`, `tests/test_review_witness.py` (first of two), `tests/test_review_replay.py` (first of two)
- Modify: `justfile` (add `tests/test_review_compact121.py \` after `tests/test_review_issue121.py \` in `agent-workflow-tests`; first of two)

**Interfaces:**
- Consumes, all in `review_issue121` today: `derive_121(repo, pins, task7_pins, authority)` (its body is the model builder), `validate_121(payload, pins, table)`, `_assigned(pins)`, `_lineage(edges)`, `_identified(row)`, `_same`, `_require`, `_closed`, `LABELS`, `_TASKS`, `KIND`, `ContributionError`, `unavailable_ids`. In `review_witness`: `_tables`, `build_witness(components, payloads, raw)`, `validate_bundle(...)`, `_ISSUE_121`. Support: `linear_fixture`, `task7_fixture`, `commit_files`, `source_budget_env`.
- Produces (`review_issue121`):
  - `model_121(repo, pins, task7_pins, authority) -> dict`: the schema-3 model, exactly the object today's `derive_121` builds. A private helper returns `(model, table)` so that `derive_121` can pass the Task-7 table to validation (CP14).
  - `compact_121(model: dict) -> dict`: the schema-4 payload. Pure. It packs the model and requires `expand_121` of the result to equal the model canonically; anything else, a malformed model included, is `ContributionError("invalid_payload")` (CP14).
  - `expand_121(payload: dict) -> dict`: the model. Pure: no Git, pins, table or I/O, and the payload is not mutated.
  - `validate_121(payload: dict, pins, table) -> dict`: in order, `_assigned(pins)` (pin faults keep `invalid_pins` and `assignment_mismatch`), `expand_121`, SOURCE's pin and table checks on the expansion, then `compact_121(model)` equal to `payload` canonically (CP6). Returns the model.
  - `derive_121(repo, pins, task7_pins, authority) -> dict`: same arguments; model, `compact_121`, `validate_121`; returns the payload.
  - `unavailable_ids(model)`: unchanged behaviour; it reads the model (CP13).
- Produces (`review_witness`): `build_witness(components, models, raw)`, where `models` maps the three fixture names to what the tables digest: here the issue-121 model, with the other two as they are. `validate_bundle` builds that mapping with `expand_121` at its tables step, calls `validate_121` where it does today, and returns the four members by name with the issue-121 model in place of its payload (CP7, CP13).
- Produces (`review_derivation`): `derive_bundle` hands `build_witness` the same mapping, built with `expand_121` (spec § *Witness, derivation, replay and commands*).

**Invariants:**
- `expand_121` raises only `ContributionError("invalid_payload")`: for anything but a `dict` with exactly the thirteen members of § *Issue-121 payload*, `schema_version` an `int` that is not a `bool` and equals 4, and the module's `KIND`; and for a wrong value type, a row of the wrong length, or an index that is not an in-range `int`. A `KeyError`, `IndexError`, `TypeError`, `AttributeError` or `ValueError` never escapes it.
- `expand_121(compact_121(m))` equals `m`, and `compact_121(expand_121(p)) == p`, for every model and payload that validates. The canonical bytes of the payload are the bundle file.
- Step 2 of validation keeps every SOURCE check an expansion can fail and drops each one that expansion makes true by construction (row ids, `edge_ids`, `record_refs`, an actual record's lineage, an edge's `parent`, `commit`, `parent_ordinal` and `owner`). A check stays only if a case in the suites turns it red. List the dropped checks in the task report.
- A SOURCE-encoded model is refused by `expand_121` and `validate_121` as `invalid_payload`; no reader for schema 3 exists (CP8).
- The witness's table names, its version 2, and its rows and digests for one set of facts are unchanged. An expansion refusal at the tables step leaves `validate_bundle` as the model's own `ContributionError`, not as `table_mismatch` (CP7). `MEMBER_MAX_BYTES` and `ANCHOR_MAX_BYTES` are unchanged (CP10).
- Exchanging two `edges` rows is not refused Git-free, and no test claims it (CP17).
- Docstrings and comments touched describe the code as implemented. The module docstrings of the four `python/` files say which object is the payload and which is the model.
- `tests/test_review_retained_full.py` names SOURCE members until Task 3 rewrites it, so the full-shape tier is not run between this task and Task 3.

**Reference packing.** This is the wire format, measured at planning on the real retained model: 48,917 B, and each direction reproduces the other byte for byte. It uses the module's `LABELS`, `_TASKS`, `_lineage` and `_identified`. The production functions add the closed checks of the first invariant; their names and decomposition are the implementer's.

```python
def _pack(m: dict) -> dict:
    edges = m["edges"]
    position = {edge["id"]: n for n, edge in enumerate(edges)}
    facts = [r for edge in edges for r in edge["records"]]
    paths = sorted({p for r in facts for p in (r["path"], r["old_path"])} | {r["path"] for r in m["records"]}
                   | {a["path"] for a in m["anchors"]})
    at, groups = {p: i for i, p in enumerate(paths)}, {}
    for r in facts:
        for e in (r["before"], r["after"]):
            if e is not None:
                groups.setdefault((e["mode"], e["kind"]), set()).add(e["oid"])
    entries, index = [], {}
    for key in sorted(groups):
        for oid in sorted(groups[key]):
            index[(*key, oid)] = len(index)
        entries.append([*key, sorted(groups[key])])

    def ref(e):
        return None if e is None else index[(e["mode"], e["kind"], e["oid"])]

    def fact(r):
        return [r["operation"], at[r["path"]], ref(r["before"]), ref(r["after"]), r["record_bytes"],
                r["record_sha256"], r["hunk_header_sha256"], *([at[r["old_path"]]] if r["old_path"] != r["path"] else [])]
    records = {}
    for r in m["records"]:
        slot = records.setdefault(r["scope"], {"kind": r["kind"], "rows": []})
        if slot["kind"] != r["kind"]:
            raise ValueError("mixed record kinds in one scope")
        slot["rows"].append([at[r["path"]], r["record_bytes"],
                             *((r["record_sha256"],) if r["kind"] == "actual" else (r["added_lines"], r["deleted_lines"]))])

    def outcome(row):
        out = {k: v for k, v in row.items() if k not in ("boundary", "edge_ids", "record_refs")}
        if "failure" in out:
            out["failure"] = {**out["failure"], "evidence_refs": [position[i] for i in out["failure"]["evidence_refs"]]}
        return out
    (signer,) = {a["signer_sha256"] for a in m["anchors"]}
    return {"schema_version": 4, "kind": m["kind"], "range": m["range"],
            "classes": [[c["commit"], c["owner"], *([] if c["reason"] is None else [c["reason"]])] for c in m["classes"]],
            "paths": paths, "entries": entries, "edges": [[fact(r) for r in edge["records"]] for edge in edges],
            "signer_sha256": signer, "anchors": [[at[a["path"]], a["commit"], a["blob"]] for a in m["anchors"]],
            "records": records,
            "outcomes": [outcome(r) for r in (m["aggregate"]["actual"], m["aggregate"]["projected"], *m["boundaries"])],
            "operational_effects": m["operational_effects"], "record_table_policy": m["record_table_policy"]}


def _expand(c: dict) -> dict:
    paths = c["paths"]
    entries = [{"mode": mode, "kind": kind, "oid": oid} for mode, kind, oids in c["entries"] for oid in oids]

    def entry(i):
        return None if i is None else dict(entries[i])
    classes = [{"commit": r[0], "owner": r[1], "reason": r[2] if len(r) > 2 else None} for r in c["classes"]]
    edges, parent = [], c["range"]["base"]
    for row, facts in zip(classes, c["edges"]):
        records = [{"operation": r[0], "path": paths[r[1]], "old_path": paths[r[7] if len(r) > 7 else r[1]],
                    "before": entry(r[2]), "after": entry(r[3]), "record_bytes": r[4], "record_sha256": r[5],
                    "hunk_header_sha256": r[6]} for r in facts]
        edges.append(_identified({"parent": parent, "commit": row["commit"], "parent_ordinal": 1, "records": records,
                                  "owner": row["owner"]}))
        parent = row["commit"]
    anchors = [_identified({"path": paths[p], "commit": commit, "blob": blob, "signer_sha256": c["signer_sha256"]})
               for p, commit, blob in c["anchors"]]

    def selected(label):
        return [e for e in edges if label.startswith("aggregate.") or e["owner"] in _TASKS[label]]
    records, refs = [], {}
    for label in LABELS:
        slot = c["records"].get(label)
        if slot is None:
            continue
        lineage = _lineage(selected(label))
        for r in slot["rows"]:
            row = {"kind": slot["kind"], "scope": label, "path": paths[r[0]], "record_bytes": r[1]}
            row.update({"record_sha256": r[2], "edge_ids": lineage[row["path"]]} if slot["kind"] == "actual"
                       else {"added_lines": r[2], "deleted_lines": r[3]})
            records.append(_identified(row))
            refs.setdefault(label, []).append(records[-1]["id"])
    outcomes = []
    for label, stored in zip(LABELS, c["outcomes"]):
        row = {"boundary": label, **stored, "edge_ids": [e["id"] for e in selected(label)]}
        if stored["state"] == "measured":
            row["record_refs"] = refs.get(label, [])
        else:
            row["failure"] = {**stored["failure"],
                              "evidence_refs": [edges[i]["id"] for i in stored["failure"]["evidence_refs"]]}
        outcomes.append(row)
    return {"schema_version": 3, "kind": c["kind"], "range": c["range"], "classes": classes, "edges": edges,
            "anchors": anchors, "records": records, "aggregate": {"actual": outcomes[0], "projected": outcomes[1]},
            "boundaries": outcomes[2:], "operational_effects": c["operational_effects"],
            "record_table_policy": c["record_table_policy"]}
```

- [ ] **Step 1: Write the failing tests.** Create `tests/test_review_compact121.py`:

```python
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
                ("outcomes", failed), ("outcomes", failed, "failure"), ("range",)]
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
```

  Then edit the published suites.
  - `tests/test_review_issue121.py` (CP14, CP15): import `compact_121` and `model_121`, and add `validated(model, pins, table)`, which returns `validate_121(compact_121(model), pins, table)`. Every case that reads or forges SOURCE members takes its object from `model_121(...)` where it called `derive_121(...)`, and calls `validated(...)` where it called `validate_121(...)` on that object. `assertIsNone(validate_121(x, ...))` becomes `assertEqual(validated(x, ...), x)`, and the rehashed anchor control compares with `payload`. The `derive_121` entry point in `entry_points` is unchanged. `test_last_assignment_must_be_the_pinned_head` passes `compact_121(model_121(...))` to `validate_121`. `test_clean_payload_validates_over_one_history` also asserts `derive_121(...) == compact_121(payload)`. No case is dropped: measured at planning, all 22 pass against a stand-in with this routing.
  - `tests/test_review_witness.py`: import `ContributionError` and `expand_121`. Add `models(payloads)`, which returns `{**payloads, "issue-121.json": expand_121(payloads["issue-121.json"])}`. `bound` and the stale-table case call `build_witness(components, models(payloads), raw)`. The authenticated-bundle case expects `{**models(self.payloads), WITNESS: ...}` and schema version 4. The witness-binding case reads its tables from `models(self.payloads)`. The forged-head-tree case forges `forged["outcomes"][spot]` for `spot` in `(0, 1, 4)`, with the prerequisite tree at 4. Add:

```python
    def test_source_encoded_member_is_invalid_payload_whatever_its_witness(self):
        clean = models(self.payloads)
        for name, error in (("issue-121.json", ContributionError),):
            raw = {**self.raw, name: canonical_bytes(clean[name])}  # SOURCE's encoding of the same facts
            raw[WITNESS] = canonical_bytes(build_witness(self.components, clean, raw))
            with self.subTest(member=name):
                with self.assertRaises(error) as caught:
                    validate_bundle(build_anchor(self.components, raw), raw, **self.kwargs())
                self.assertEqual(caught.exception.code, "invalid_payload")
```

  - `tests/test_review_replay.py`: import `expand_121`. `test_result_reports_the_issue100_summary` compares with `expand_121(json.loads(...))`. `test_forged_head_tree_is_refused_under_its_rebuilt_digest` forges `issue121["outcomes"][n]` for `n` in `(0, 1, 4)` and rebinds through the helper below. Add:

```python
    def rebound(self, bundle, components, payloads, raw, models=None):
        """Write `raw` into `bundle` under a rebuilt witness and anchor: `(the forger's own digest, anchor)`.
        The witness digests `models`, else the expansions of `payloads` (trust injection, RP7)."""
        models = models or {**payloads, "issue-121.json": expand_121(payloads["issue-121.json"])}
        raw["derivation-witness.json"] = canonical_bytes(build_witness(components, models, raw))
        anchor = build_anchor(components, raw)
        for name, data in {**raw, ANCHOR_NAME: canonical_bytes(anchor)}.items():
            (bundle / name).write_bytes(data)
        return telemetry_digest(anchor), anchor

    def test_source_encoded_members_are_refused_as_invalid_payload(self):
        """The SOURCE encoding of the same facts, under a witness and an anchor that are coherent with it."""
        source, expected, kwargs = self.shared()
        for name, error, versions in (("issue-121.json", ContributionError, (3, 4)),):
            bundle = Path(shutil.copytree(source, self.tmp / name))
            trusted_anchor, raw = authenticate(bundle, expected)
            payloads = {member: json.loads(data) for member, data in raw.items()}
            models = {**payloads, "issue-121.json": expand_121(payloads["issue-121.json"])}
            self.assertEqual((models[name]["schema_version"], payloads[name]["schema_version"]), versions)
            raw = {**raw, name: canonical_bytes(models[name])}
            components = {group: trusted_anchor[group] for group in GROUPS}
            forger, anchor = self.rebound(bundle, components, payloads, raw, models)
            self.assertEqual(authenticate(bundle, forger), (anchor, raw))
            with self.subTest(member=name):
                with self.assertRaises(error) as caught:
                    replay(bundle, forger, **kwargs)
                self.assertEqual(caught.exception.code, "invalid_payload")
                self.assertEqual(self.main(bundle, forger, kwargs), (2, b"", PREFIX + "invalid: invalid_payload\n"))
                (bundle / ANCHOR_NAME).write_bytes(canonical_bytes(trusted_anchor))  # the trusted anchor again
                self.refused("member_digest", bundle, expected, kwargs)
```

- [ ] **Step 2: Run them and watch them fail.**

```bash
PYTHONPATH=python python3 -m unittest tests.test_review_compact121 2>&1 | tail -4
```

  Expected at the starting commit: `ImportError: cannot import name 'compact_121' from 'agent_tools.review_issue121'`.

- [ ] **Step 3: Implement** the produced interfaces. `validate_bundle` keeps its order of refusals; only the object that its tables step and its return read changes. Add the `justfile` line.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_compact121 tests.test_review_issue121 \
  tests.test_review_witness tests.test_review_derivation tests.test_review_replay 2>&1 | tail -3
if grep -q 'assertIsNone(validate_121' tests/test_review_issue121.py; then exit 1; fi
if ! just --show agent-workflow-tests | grep -q 'tests/test_review_compact121.py'; then exit 1; fi
git diff --stat 7e17c8196569b0a96950f07ff886884690ffa224 -- python/agent_tools | tail -1
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  The five suites end `OK` (about ten minutes). The `--stat` line names exactly four files. `tests.test_review_derivation` passes unchanged, which shows the command shells and the bundle shape are untouched.

- [ ] **Step 5: Commit.** Stage only the nine Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `feat(review): compact issue-121 payload to schema 4 (#254)`. A review-fix commit uses `fix(review): address Task-1 review findings (#254)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 1`.

## Forecast basis

Estimates. A modify record is the U10 diff against `DELIVERY_BASE`; an add is the file plus one byte per line plus 512.
- `review_issue121.py`: the reference packing (about 5,300 B), its closed checks, three wrappers and the edited validator, in about eight hunks of twenty context lines: 30,720 B / +250 / −60.
- `review_witness.py`, first of two: four hunks, 12,288 B / +30 / −20. `review_derivation.py`, first of two: 7,168 B / +10 / −6. `review_replay.py`: 6,144 B / +8 / −8.
- `tests/test_review_compact121.py`: the suite above (13,319 B, 228 lines) plus twelve percent: 16,384 B / +260.
- `tests/test_review_issue121.py`: the routing edit measures 20,228 B / +32 / −22 at planning: 24,576 B / +45 / −30.
- `tests/test_review_witness.py`, first of two: 13,312 B / +28 / −10. `tests/test_review_replay.py`, first of two: 9,216 B / +46 / −10. `justfile`, first of two: 2,048 B / +1.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":250,"boundary":"compact","deleted_lines":60,"record_bytes":30720,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":30,"boundary":"compact","deleted_lines":20,"record_bytes":12288,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-2","last_task":2,"owner":1,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":10,"boundary":"compact","deleted_lines":6,"record_bytes":7168,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-3","last_task":2,"owner":1,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":8,"boundary":"compact","deleted_lines":8,"record_bytes":6144,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-4","last_task":1,"owner":1,"path":"python/agent_tools/review_replay.py"},{"bounds":[{"added_lines":260,"boundary":"compact","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-5","last_task":1,"owner":1,"path":"tests/test_review_compact121.py"},{"bounds":[{"added_lines":45,"boundary":"compact","deleted_lines":30,"record_bytes":24576,"support":{"covers":["t1-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-6","last_task":1,"owner":1,"path":"tests/test_review_issue121.py"},{"bounds":[{"added_lines":28,"boundary":"compact","deleted_lines":10,"record_bytes":13312,"support":{"covers":["t1-7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-7","last_task":2,"owner":1,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":46,"boundary":"compact","deleted_lines":10,"record_bytes":9216,"support":{"covers":["t1-8"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-8","last_task":2,"owner":1,"path":"tests/test_review_replay.py"},{"bounds":[{"added_lines":1,"boundary":"compact","deleted_lines":0,"record_bytes":2048,"support":{"covers":["t1-9"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-9","last_task":2,"owner":1,"path":"justfile"}]}}
```
