# Task 2: Issue-100 payload, schema version 2

The issue-100 model gains its compact payload with base85 packed digests (spec § *Solution*, § *Issue-100 payload*, § *Why a packed digest is still a whole record*; CP1, CP2, CP4, CP5, CP6, CP7, CP8, CP9, CP13, CP14, CP15, CP16, CP17). This task completes `python/`: the controller runs G2 on its accepted head.

**Files:**
- Modify: `python/agent_tools/review_issue100.py`
- Modify: `python/agent_tools/review_witness.py`, `python/agent_tools/review_derivation.py` (second contributions)
- Create: `tests/test_review_compact100.py`
- Modify: `tests/test_review_issue100.py`, `tests/test_review_witness.py`, `tests/test_review_replay.py` (second contributions)
- Modify: `justfile` (add `tests/test_review_compact100.py \` after `tests/test_review_issue100.py \`; second contribution)

**Interfaces:**
- Consumes, all in `review_issue100` today: `derive_100(issue_repo, live_repo, archive_dir, pins, limits)` (its body is the model builder), `validate_100(payload, pins)`, `_checked(pins)`, `_at_head(payload, pins)` (it reads the model's `edges` and the two range ends), `_refs(edges, path)`, `_counts(model)`, `_identified(row)`, `_PAIRS`, `_same`, `_require`, `KIND`, `Issue100Error`. Task 1's `expand_121` and `build_witness(components, models, raw)`. Support: `issue100_fixture`, `source_budget_env`.
- Produces (`review_issue100`):
  - `model_100(issue_repo, live_repo, archive_dir, pins, limits) -> dict`: the schema-1 model, exactly the object today's `derive_100` builds.
  - `compact_100(model: dict) -> dict`: the schema-2 payload. Pure. It packs the model and requires `expand_100` of the result to equal the model canonically; anything else is `Issue100Error("invalid_payload")` (CP14).
  - `expand_100(payload: dict) -> dict`: the model. Pure: no Git, pins or I/O, and the payload is not mutated.
  - `validate_100(payload: dict, pins) -> dict`: in order, `_checked(pins)` (`invalid_pins`), `expand_100`, SOURCE's pin checks on the expansion, then `compact_100(model)` equal to `payload` canonically (CP6). Returns the model.
  - `derive_100(...) -> dict`: same arguments; model, `compact_100`, `validate_100`; returns the payload.
- Produces (`review_witness`, `review_derivation`): the `models` mapping also holds `expand_100` of the issue-100 payload, and `validate_bundle` returns the issue-100 model under its member name. `review_replay` reads `summary` from that model, as its code already does.

**Invariants:**
- `expand_100` raises only `Issue100Error("invalid_payload")`: for anything but a `dict` with exactly the seventeen members of § *Issue-100 payload*, `schema_version` an `int` that is not a `bool` and equals 2, and the module's `KIND`; and for a wrong value type, a row of the wrong length, an index that is not an in-range `int`, or a packed string that is not base85 text decoding to whole 20-byte or 32-byte items. No raw exception escapes it.
- `expand_100` returns on every input (CP16): before the first-parent walk it refuses a repeated commit, a commit equal to the base, and a parent index that is not the base or an earlier commit. The suite below hangs without this.
- An entry reference (`live`, a record's `before` and `after`, a `head_trees` row, an overlap's base entry) is `null` or an index (CP17).
- `expand_100(compact_100(m))` equals `m`, and `compact_100(expand_100(p)) == p`, for every model and payload that validates. A packed string is `base64.b85encode` of the concatenated raw digests, so an object id is one 25-character token and a SHA-256 one 40-character token (CP2).
- Step 2 of validation keeps every SOURCE check an expansion can fail and drops each one that expansion makes true by construction (row ids, `edge_refs`, the summary against the tables, a contribution's `path` and `record_sha256` against its fresh row, an overlap's entries against its contribution). The counts against `pins.expected_counts`, the pinned raw-parent digest, both domains, the labels against `pins.process_paths`, the overlap paths, the directory-head rule and the criteria stay. A check stays only if a case in the suites turns it red. List the dropped checks in the task report.
- CP5's three reductions are not taken: every `before` is stored, paths are plain strings, and records are rows.
- Docstrings and comments touched describe the code as implemented.

**Reference packing.** This is the wire format, measured at planning on the real retained model: 62,118 B, and each direction reproduces the other byte for byte. It uses the module's `_at_head`, `_refs`, `_counts`, `_identified` and `_PAIRS`; `span` stands for an object with the payload's `head` and `base`, which is all `_at_head` reads from its second argument. The production functions add the closed checks of the first invariant; their names and decomposition are the implementer's.

```python
def _packed(hexes) -> str:
    return base64.b85encode(bytes.fromhex("".join(hexes))).decode("ascii")


def _unpacked(text, size) -> list:
    raw = base64.b85decode(text)
    return [raw[i:i + size].hex() for i in range(0, len(raw), size)]


def _pack(m: dict) -> dict:
    commits, rows = m["range"]["commits"], m["contributions"]
    nodes, records = [m["range"]["base"], *commits], [r for e in m["edges"] for r in e["records"]]
    used = [x for r in records for x in (r["before"], r["after"])]
    used += [row[k] for row in rows for k in ("head_entry", "live_entry")]
    used += [o["base_entry"] for o in m["pending_overlaps"]]
    groups = {}
    for e in used:
        if e is not None:
            groups.setdefault((e["mode"], e["kind"]), set()).add(e["oid"])
    entries, index = [], {}
    for key in sorted(groups):
        for oid in sorted(groups[key]):
            index[(*key, oid)] = len(index)
        entries.append([*key, _packed(sorted(groups[key]))])

    def ref(e):
        return None if e is None else index[(e["mode"], e["kind"], e["oid"])]
    fresh, historical = m["tables"]["fresh"], m["tables"]["historical"]
    paths = sorted({p for r in records for p in (r["path"], r["old_path"])}
                   | {r["path"] for r in fresh["records"]} | {o["path"] for o in m["pending_overlaps"]})
    at = {p: i for i, p in enumerate(paths)}
    table, seen, digests, edges = [], {}, [], []
    for edge in m["edges"]:
        refs = []
        for r in edge["records"]:
            key = canonical_bytes(r)
            if key not in seen:
                seen[key] = len(table)
                table.append([r["operation"], at[r["path"]], ref(r["before"]), ref(r["after"]), r["record_bytes"],
                              *([at[r["old_path"]]] if r["old_path"] != r["path"] else [])])
                digests.append(r["record_sha256"][len("sha256:"):])
            refs.append(seen[key])
        edges.append(refs)
    parents, position = [[] for _ in commits], {c: i for i, c in enumerate(commits)}
    for edge in m["parent_edges"]:
        parents[position[edge["commit"]]].append(nodes.index(edge["parent"]))
    return {"schema_version": 2, "kind": m["kind"], "range": {k: m["range"][k] for k in ("base", "head", "live")},
            "commits": _packed(commits), "parents": parents, "paths": paths, "entries": entries, "records": table,
            "record_sha256": _packed(digests), "edges": edges,
            "tables": {"historical": {"record_table_policy": historical["record_table_policy"],
                                      "bytes": [r["bytes"] for r in historical["records"]],
                                      "sha256": _packed([r["sha256"] for r in historical["records"]])},
                       "fresh": {"record_table_policy": fresh["record_table_policy"],
                                 "paths": [at[r["path"]] for r in fresh["records"]],
                                 "bytes": [r["bytes"] for r in fresh["records"]],
                                 "sha256": _packed([r["sha256"] for r in fresh["records"]])}},
            "live": [ref(row["live_entry"]) for row in rows],
            "head_trees": [[i, ref(row["head_entry"])] for i, row in enumerate(rows)
                           if row["head_entry"] and row["head_entry"]["kind"] == "tree"],
            "process": [i for i, row in enumerate(rows) if row["disposition"] == "historical_process"],
            "pending_overlaps": [[at[o["path"]], ref(o["base_entry"])] for o in m["pending_overlaps"]],
            "overlap_sha256": _packed([o[f"{a}_{b}_sha256"] for o in m["pending_overlaps"] for a, b in _PAIRS]),
            "criteria": [{k: v for k, v in row.items() if k != "text_sha256"} for row in m["criteria"]]}


def _expand(c: dict) -> dict:
    base, commits, paths = c["range"]["base"], _unpacked(c["commits"], 20), c["paths"]
    nodes = [base, *commits]
    if len(set(nodes)) != len(nodes):  # the first-parent walk below must terminate
        raise ValueError("repeated commit")
    for i, listed in enumerate(c["parents"]):
        if any(type(p) is not int or not 0 <= p <= i for p in listed):
            raise ValueError("parent is not the base or an earlier commit")
    entries = [{"mode": mode, "kind": kind, "oid": oid}
               for mode, kind, packed in c["entries"] for oid in _unpacked(packed, 20)]

    def entry(i):
        return None if i is None else dict(entries[i])
    digests = _unpacked(c["record_sha256"], 32)

    def record(i):
        row = c["records"][i]
        return {"operation": row[0], "path": paths[row[1]], "old_path": paths[row[5] if len(row) > 5 else row[1]],
                "before": entry(row[2]), "after": entry(row[3]), "record_bytes": row[4],
                "record_sha256": "sha256:" + digests[i]}
    parent_edges = [{"parent": nodes[p], "commit": commit, "parent_ordinal": n}
                    for commit, listed in zip(commits, c["parents"]) for n, p in enumerate(listed, 1)]
    edges = [{**raw, "records": [record(i) for i in refs]} for raw, refs in zip(parent_edges, c["edges"])]
    t = c["tables"]
    historical = [{"bytes": b, "sha256": s}
                  for b, s in zip(t["historical"]["bytes"], _unpacked(t["historical"]["sha256"], 32))]
    fresh = [{"path": paths[p], "bytes": b, "sha256": s}
             for p, b, s in zip(t["fresh"]["paths"], t["fresh"]["bytes"], _unpacked(t["fresh"]["sha256"], 32))]
    m = {"schema_version": 1, "kind": c["kind"], "parent_edges": parent_edges, "edges": edges,
         "range": {**c["range"], "commits": commits}}
    at_head = _at_head(m, span)
    trees, process, heads, lives, rows = dict(map(tuple, c["head_trees"])), set(c["process"]), {}, {}, []
    for i, (rec, live) in enumerate(zip(fresh, c["live"])):
        path = rec["path"]
        head, live = entry(trees[i]) if i in trees else at_head[path], entry(live)
        heads[path], lives[path] = head, live
        label = "historical_process" if i in process else "integrated" if head == live else "candidate"
        rows.append({"path": path, "record_sha256": rec["sha256"], "head_entry": head, "live_entry": live,
                     "edge_refs": _refs(edges, path), "disposition": label, "pending": None})
    digests, overlaps = _unpacked(c["overlap_sha256"], 32), []
    for n, (p, before) in enumerate(c["pending_overlaps"]):
        path = paths[p]
        overlaps.append(_identified({"path": path, "base_entry": entry(before), "live_entry": lives[path],
                                     "head_entry": heads[path],
                                     **{f"{a}_{b}_sha256": digests[3 * n + k] for k, (a, b) in enumerate(_PAIRS)}}))
    pending = {o["path"]: o["id"] for o in overlaps}
    m.update(contributions=[_identified({**row, "pending": pending.get(row["path"])
                                         if row["disposition"] == "candidate" else None}) for row in rows],
             pending_overlaps=overlaps,
             tables={"historical": {"record_table_policy": t["historical"]["record_table_policy"],
                                    "records": historical},
                     "fresh": {"record_table_policy": t["fresh"]["record_table_policy"], "records": fresh}},
             criteria=[{**row, "text_sha256": hashlib.sha256(row["text"].encode()).hexdigest()}
                       for row in c["criteria"]])
    m["summary"] = _counts(m)
    return m
```

- [ ] **Step 1: Write the failing tests.** Create `tests/test_review_compact100.py`:

```python
"""Issue-100 compact payload, schema 2: expansion to SOURCE's model, canonical form and refusals (issue 254)."""
import base64, copy, json, os, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_budget import describe
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import Issue100Error, compact_100, derive_100, expand_100, model_100, validate_100

from .retained_review_test_support import issue100_fixture, source_budget_env

MEMBERS = {"schema_version", "kind", "range", "commits", "parents", "paths", "entries", "records", "record_sha256",
           "edges", "tables", "live", "head_trees", "process", "pending_overlaps", "overlap_sha256", "criteria"}
KINDS = ({"k": 1}, [1], "s", 7, True, None)


def wire(value):
    """`value` as a consumer reads it from a bundle file."""
    return json.loads(canonical_bytes(value))


def tokens(packed, size):
    """The fixed-width base85 tokens of a packed string: 25 characters per object id, 40 per SHA-256."""
    return [packed[i:i + size] for i in range(0, len(packed), size)]


def exchange(rows, a, b):
    rows[a], rows[b] = rows[b], rows[a]


class Compact100Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); cls.addClassCleanup(shutil.rmtree, cls.tmp)
        cls.repo, cls.live, cls.archive, cls.pins = issue100_fixture(cls.tmp)
        with patch.dict(os.environ, source_budget_env(cls.tmp), clear=True):
            cls.limits = describe("review-package").limits
        cls.model = model_100(cls.repo, cls.live, cls.archive, cls.pins, cls.limits)
        cls.payload = wire(compact_100(cls.model))

    def refused(self, mutate):
        forged = copy.deepcopy(self.payload)
        mutate(forged)
        with self.assertRaises(Issue100Error) as caught:
            validate_100(forged, self.pins)
        self.assertEqual(caught.exception.code, "invalid_payload")

    def at(self, path):
        return self.payload["paths"].index(path)

    def fresh(self, path):
        return self.payload["tables"]["fresh"]["paths"].index(self.at(path))

    def test_payload_is_closed_and_expands_to_the_source_model(self):
        payload, model = self.payload, self.model
        self.assertEqual((set(payload), payload["schema_version"], model["schema_version"]), (MEMBERS, 2, 1))
        self.assertEqual(canonical_bytes(expand_100(payload)), canonical_bytes(model))
        self.assertEqual(canonical_bytes(validate_100(payload, self.pins)), canonical_bytes(model))
        self.assertEqual(derive_100(self.repo, self.live, self.archive, self.pins, self.limits), compact_100(model))
        self.assertEqual(compact_100(expand_100(payload)), payload)
        self.assertEqual(model["summary"], self.pins.expected_counts)
        # Packed members are whole digests: RFC 1924 base85 of the raw bytes, one fixed-width token per item.
        commits = tokens(payload["commits"], 25)
        self.assertEqual([base64.b85decode(token).hex() for token in commits], model["range"]["commits"])
        digests = tokens(payload["record_sha256"], 40)
        self.assertEqual(["sha256:" + base64.b85decode(token).hex() for token in digests],
                         list(dict.fromkeys(r["record_sha256"] for e in model["edges"] for r in e["records"])))
        self.assertEqual(len(payload["records"]), len(digests))
        self.assertLess(len(digests), model["summary"]["edge_records"])  # the merge repeats its side's records
        self.assertEqual([len(refs) for refs in payload["edges"]], [len(e["records"]) for e in model["edges"]])

    def test_source_encoding_and_other_versions_are_refused(self):
        for label, forged in (("source model", self.model), ("version 1", {**self.payload, "schema_version": 1}),
                              ("boolean version", {**self.payload, "schema_version": True}),
                              ("extra member", {**self.payload, "summary": self.model["summary"]}), ("list", [self.payload])):
            for call in (expand_100, lambda p: validate_100(p, self.pins)):
                with self.subTest(label), self.assertRaises(Issue100Error) as caught:
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
            # An entry reference is null or an index, so neither kind is malformed in its place.
            reference = path[0] == "live" or (path[0] == "pending_overlaps" and path[-1] == 1)
            variants.extend(put(path, kind) for kind in KINDS if type(kind) is not type(value)
                            and not (reference and (kind is None or type(kind) is int)))
            variants.append(put(path, KINDS))
        for key, value in payload.items():
            spread((key,), value)
        rename = next(n for n, row in enumerate(payload["records"]) if len(row) == 6)
        rows = [("range",), ("parents", 0), ("entries", 0), ("records", 0), ("records", rename), ("edges", 0),
                ("tables",), ("tables", "historical"), ("tables", "fresh"), ("tables", "fresh", "record_table_policy"),
                ("tables", "fresh", "paths"), ("tables", "fresh", "bytes"), ("live",), ("head_trees", 0), ("process",),
                ("pending_overlaps", 0), ("criteria", 0), ("criteria", 9)]
        for path in rows:
            row = payload
            for key in path:
                row = row[key]
            for key, value in (row.items() if isinstance(row, dict) else enumerate(row)):
                spread((*path, key), value)
        self.assertGreater(len(variants), 400)
        for variant in variants:
            with self.subTest(variant=repr(variant)[:160]):
                with self.assertRaises(Issue100Error) as caught:
                    validate_100(variant, self.pins)
                self.assertEqual(caught.exception.code, "invalid_payload")

    def test_altered_inputs_of_recomputed_members_are_refused(self):
        payload = self.payload
        merge = next(n for n, listed in enumerate(payload["parents"]) if len(listed) == 2)
        integrated, candidate, process = self.fresh("src/a.txt"), self.fresh("src/c.txt"), self.fresh("docs/plan.md")
        self.assertEqual((payload["process"], payload["head_trees"][0][0]), ([process], self.fresh("legacy")))
        written = next(n for n, row in enumerate(payload["records"]) if row[:2] == ["A", self.at("src/a.txt")])
        other = payload["records"][next(n for n, row in enumerate(payload["records"])
                                        if row[:2] == ["A", self.at("src/b.txt")])][3]
        tree, blob = payload["head_trees"][0][1], payload["live"][integrated]
        cases = {
            "parent_to_base": lambda p: p["parents"][merge].__setitem__(1, 0),
            "parent_to_earlier_commit": lambda p: p["parents"][-1].__setitem__(0, 1),
            "parent_to_later_commit": lambda p: p["parents"][0].__setitem__(0, len(p["parents"])),
            "parents_emptied": lambda p: p["parents"].__setitem__(0, []),
            "parents_reordered": lambda p: p["parents"][merge].reverse(),
            "parents_row_removed": lambda p: p["parents"].pop(),
            "parents_rows_exchanged": lambda p: exchange(p["parents"], merge, merge + 1),
            "commit_removed": lambda p: p.update(commits=p["commits"][25:]),
            "commits_exchanged": lambda p: p.update(commits=p["commits"][25:50] + p["commits"][:25] + p["commits"][50:]),
            "commit_repeated": lambda p: p.update(commits=p["commits"][:25] * 2 + p["commits"][50:]),
            "edge_row_removed": lambda p: p["edges"].pop(),
            "edge_record_dropped": lambda p: p["edges"][0].pop(),
            "edge_record_repeated": lambda p: p["edges"][0].append(p["edges"][0][-1]),
            "integrated_head_changed": lambda p: p["records"][written].__setitem__(3, other),
            "process_index_added": lambda p: p["process"].append(candidate),
            "process_index_removed": lambda p: p["process"].clear(),
            "live_set_to_the_head": lambda p: p["live"].__setitem__(
                candidate, next(row[3] for row in p["records"] if row[1] == self.at("src/c.txt"))),
            "overlap_path_changed": lambda p: p["pending_overlaps"][0].__setitem__(0, self.at("src/c.txt")),
            "overlap_removed": lambda p: (p["pending_overlaps"].pop(), p.update(overlap_sha256=p["overlap_sha256"][:120])),
            "overlap_on_a_non_candidate": lambda p: p["pending_overlaps"][0].__setitem__(0, self.at("src/a.txt")),
            "overlap_on_an_unrecorded_path": lambda p: p["pending_overlaps"][0].__setitem__(0, self.at("src/b.txt")),
            "overlap_digest_removed": lambda p: p.update(overlap_sha256=p["overlap_sha256"][40:]),
            "head_tree_on_a_file": lambda p: p["head_trees"].append([candidate, tree]),
            "head_tree_holding_a_blob": lambda p: p["head_trees"][0].__setitem__(1, blob),
            "head_tree_removed": lambda p: p["head_trees"].clear(),
            "criterion_text": lambda p: p["criteria"][0].update(text="another text"),
            "criterion_state": lambda p: p["criteria"][0].update(state="governing", superseded_by=None),
            "criterion_removed": lambda p: p["criteria"].pop(0),
            "criterion_digest_stored": lambda p: p["criteria"][0].update(text_sha256="0" * 64),
            "policies_exchanged": lambda p: (lambda t: t["historical"].update(
                record_table_policy=t["fresh"]["record_table_policy"]) or t["fresh"].update(
                record_table_policy=self.payload["tables"]["historical"]["record_table_policy"]))(p["tables"]),
            "historical_bytes_under_fresh": lambda p: p["tables"]["fresh"].update(bytes=p["tables"]["historical"]["bytes"]),
            "fresh_row_removed": lambda p: [p["tables"]["fresh"][k].pop() for k in ("paths", "bytes")],
            "range_live": lambda p: p["range"].update(live=p["range"]["base"]),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.refused(mutate)

    def test_noncanonical_spellings_of_the_same_facts_are_refused(self):
        payload = self.payload
        self.assertEqual(expand_100({**payload, "paths": [*payload["paths"], "zz/unused"]}), expand_100(payload))

        def records_exchanged(p):  # the same facts with two record rows out of first-use order
            exchange(p["records"], 0, 1)
            digests = tokens(p["record_sha256"], 40)
            exchange(digests, 0, 1)
            p["record_sha256"] = "".join(digests)
            p["edges"] = [[{0: 1, 1: 0}.get(i, i) for i in refs] for refs in p["edges"]]
        cases = {"unused_path": lambda p: p["paths"].append("zz/unused"),
                 "duplicate_path": lambda p: p["paths"].append(p["paths"][-1]),
                 "unused_record": lambda p: (p["records"].append(list(p["records"][0][:4]) + [1]),
                                             p.update(record_sha256=p["record_sha256"] + p["record_sha256"][:40])),
                 "duplicate_record": lambda p: (p["records"].append(list(p["records"][0])),
                                                p.update(record_sha256=p["record_sha256"] + p["record_sha256"][:40]),
                                                p["edges"][0].__setitem__(0, len(p["records"]) - 1)),
                 "duplicate_entry": lambda p: p["entries"][0].__setitem__(2, p["entries"][0][2] + p["entries"][0][2][-25:]),
                 "records_exchanged": records_exchanged,
                 "negative_index": lambda p: p["live"].__setitem__(0, p["live"][0] - sum(len(r[2]) // 25 for r in p["entries"])),
                 "true_for_one": lambda p: p["parents"][1].__setitem__(0, True),
                 "token_with_a_trailing_newline": lambda p: p.update(commits=p["commits"] + "\n")}
        self.assertEqual((payload["parents"][1], isinstance(payload["live"][0], int)), ([1], True))
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.refused(mutate)

    def test_file_and_directory_swaps_keep_their_tree_entries(self):
        payload = self.payload
        kinds = [row[1] for row in payload["entries"]]
        self.assertEqual(sorted(set(kinds)), ["blob", "tree"])
        first = sum(len(row[2]) // 25 for row in payload["entries"][:kinds.index("tree")])
        trees = range(first, first + len(payload["entries"][kinds.index("tree")][2]) // 25)
        sides = [(n, side) for n, row in enumerate(payload["records"]) for side in (2, 3) if row[side] in trees]
        self.assertEqual(sorted((payload["records"][n][0], payload["paths"][payload["records"][n][1]], side)
                                for n, side in sides), [("A", "tmp", 2), ("D", "legacy", 3)])
        self.assertIn(payload["head_trees"][0][1], trees)  # the head's `legacy` is a directory
        blob = payload["live"][self.fresh("src/a.txt")]
        for n, side in sides:
            with self.subTest(record=n):
                self.refused(lambda p: p["records"][n].__setitem__(side, blob))


if __name__ == "__main__":
    unittest.main()
```

  Then edit the published suites.
  - `tests/test_review_issue100.py` (CP14, CP15): import `compact_100` and `model_100`, and add `validated(model, pins)`, which returns `validate_100(compact_100(model), pins)`. Every case that reads or forges SOURCE members takes its object from `model_100(...)` where it called `derive_100(...)`, and calls `validated(...)` where it called `validate_100(...)` on that object. Unchanged: the three `validate_100({}, ...)` pin cases and the two `derive_100` failure cases. `test_derive_validates_and_preserves_inputs` asserts `validated(payload, self.pins) == payload` and `derive_100(...) == compact_100(payload)`. No case is dropped: measured at planning, all 21 pass against a stand-in with this routing.
  - `tests/test_review_witness.py`: `models(payloads)` also expands `issue-100-derived.json` with `expand_100`. The source-encoded case's tuple gains `("issue-100-derived.json", Issue100Error)`, and the authenticated-bundle case asserts schema versions `[2, 4]` for the two retained members. In `test_malformed_sibling_beside_an_unavailable_outcome_is_invalid` the issue-100 forgery becomes `hundred["process"] = []`: the process path relabelled, so the counts are no longer the pinned ones.
  - `tests/test_review_replay.py`: import `Issue100Error` and `expand_100`. `rebound`'s default models and the models of `test_source_encoded_members_are_refused_as_invalid_payload` also expand the issue-100 member, and that test's tuple gains `("issue-100-derived.json", Issue100Error, (1, 2))`.

- [ ] **Step 2: Run them and watch them fail.**

```bash
PYTHONPATH=python python3 -m unittest tests.test_review_compact100 2>&1 | tail -4
```

  Expected at the starting commit: `ImportError: cannot import name 'compact_100' from 'agent_tools.review_issue100'`.

- [ ] **Step 3: Implement** the produced interfaces and add the `justfile` line.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python timeout 1800 python3 -m unittest tests.test_review_compact100 tests.test_review_issue100 \
  tests.test_review_witness tests.test_review_derivation tests.test_review_replay 2>&1 | tail -3
if grep -q 'payload = derive_100(' tests/test_review_issue100.py; then exit 1; fi
if ! just --show agent-workflow-tests | grep -q 'tests/test_review_compact100.py'; then exit 1; fi
git diff --stat 7e17c8196569b0a96950f07ff886884690ffa224 -- python/agent_tools | tail -1
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  The five suites end `OK` within the timeout; a timeout means `expand_100` does not terminate (CP16). The `--stat` line names exactly five files.

- [ ] **Step 5: Commit.** Stage only the eight Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `feat(review): compact issue-100 payload to schema 2 (#254)`. A review-fix commit uses `fix(review): address Task-2 review findings (#254)`.

- [ ] **Step 6: G1, then G2 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, and renew G0 at `--completed-through 2`. Then run G2 at that accepted head and post its pin, as the plan root describes.

## Forecast basis

Estimates, priced as in Task 1.
- `review_issue100.py`: the reference packing (about 7,700 B), its closed checks, three wrappers and the edited validator, in about eight hunks: 33,792 B / +290 / −70.
- `review_witness.py`, cumulative: 13,312 B / +36 / −24. `review_derivation.py`, cumulative: 8,192 B / +12 / −8.
- `tests/test_review_compact100.py`: the suite above (13,624 B, 216 lines) plus twelve percent: 16,384 B / +260.
- `tests/test_review_issue100.py`: the routing edit measures 22,598 B / +47 / −37 at planning: 26,624 B / +60 / −45.
- `tests/test_review_witness.py`, cumulative: both tasks' edits measure 11,900 B / +27 / −10: 14,336 B / +34 / −14. `tests/test_review_replay.py`, cumulative: 7,824 B / +43 / −9 measured: 10,240 B / +52 / −12. `justfile`, cumulative: 2,560 B / +2.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":290,"boundary":"compact","deleted_lines":70,"record_bytes":33792,"support":{"covers":["t2-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":36,"boundary":"compact","deleted_lines":24,"record_bytes":13312,"support":{"covers":["t1-2","t2-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-2","last_task":2,"owner":2,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":12,"boundary":"compact","deleted_lines":8,"record_bytes":8192,"support":{"covers":["t1-3","t2-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-3","last_task":2,"owner":2,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":260,"boundary":"compact","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t2-4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-4","last_task":2,"owner":2,"path":"tests/test_review_compact100.py"},{"bounds":[{"added_lines":60,"boundary":"compact","deleted_lines":45,"record_bytes":26624,"support":{"covers":["t2-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-5","last_task":2,"owner":2,"path":"tests/test_review_issue100.py"},{"bounds":[{"added_lines":34,"boundary":"compact","deleted_lines":14,"record_bytes":14336,"support":{"covers":["t1-7","t2-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-6","last_task":2,"owner":2,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":52,"boundary":"compact","deleted_lines":12,"record_bytes":10240,"support":{"covers":["t1-8","t2-7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-7","last_task":2,"owner":2,"path":"tests/test_review_replay.py"},{"bounds":[{"added_lines":2,"boundary":"compact","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t1-9","t2-8"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-8","last_task":2,"owner":2,"path":"justfile"}]}}
```
