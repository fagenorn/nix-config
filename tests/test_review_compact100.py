"""Issue-100 compact payload, schema 2: expansion to SOURCE's model, canonical form and refusals (issue 254)."""
import base64, copy, json, os, shutil, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
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

    def refused(self, mutate, follow=False):
        forged, pins = copy.deepcopy(self.payload), self.pins
        mutate(forged)
        if follow:  # pinned: the forgery's own raw-parent digest and counts
            m = expand_100(forged)
            pins = replace(pins, parent_edges_sha256=telemetry_digest(m["parent_edges"]), expected_counts=m["summary"])
        with self.assertRaises(Issue100Error) as caught:
            validate_100(forged, pins)
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
                              ("float", {**self.payload, "schema_version": 2.0}), ("kind", {**self.payload, "kind": 2}),
                              ("extra member", {**self.payload, "summary": self.model["summary"]}), ("list", [self.payload])):
            for n, call in enumerate((expand_100, lambda p: validate_100(p, self.pins))):
                with self.subTest(label, call=n), self.assertRaises(Issue100Error) as caught:
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
            variants.extend((path, kind, put(path, kind)) for kind in KINDS if type(kind) is not type(value)
                            and not (reference and (kind is None or type(kind) is int)))
            variants.append((path, "removed", put(path, KINDS)))
        for key, value in payload.items():
            spread((key,), value)
        rename = next(n for n, row in enumerate(payload["records"]) if len(row) == 6)
        rows = [("range",), ("parents", 0), ("entries", 0), ("records", 0), ("records", rename), ("edges", 0),
                ("tables",), ("tables", "historical"), ("tables", "fresh"), ("tables", "fresh", "record_table_policy"),
                ("tables", "fresh", "paths"), ("tables", "fresh", "bytes"), ("live",), ("head_trees", 0), ("process",),
                ("pending_overlaps", 0), ("criteria", 0), ("criteria", 9), ("paths",), ("parents",)]
        for path in rows:
            row = payload
            for key in path:
                row = row[key]
            for key, value in (row.items() if isinstance(row, dict) else enumerate(row)):
                spread((*path, key), value)
        self.assertGreater(len(variants), 400)
        for path, kind, variant in variants:
            with self.subTest(path=path, kind=kind):
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
        # a new last entry of no file mode, and its index
        odd, last = ["10064x", "blob", payload["commits"][:25]], sum(len(row[2]) // 25 for row in payload["entries"])
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
            "process_index_moved": lambda p: p["process"].__setitem__(0, candidate),
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
            "fresh_path_repeated": lambda p: p["tables"]["fresh"]["paths"].__setitem__(
                self.fresh("tmp"), self.at("src/c.txt")),
            "index_below_the_table": lambda p: p["live"].__setitem__(candidate, -99),
            "record_digest_removed": lambda p: p.update(record_sha256=p["record_sha256"][40:]),
            "record_digest_cut": lambda p: p.update(record_sha256=p["record_sha256"][:-5]),
            "base_entry_mode": lambda p: (p["entries"].append(odd), p["pending_overlaps"][0].__setitem__(1, last)),
            "live_entry_mode": lambda p: (p["entries"].append(odd), p["live"].__setitem__(self.fresh("legacy"), last)),
        }
        pending = self.fresh("ci.yaml")
        head = next(row[3] for row in payload["records"] if row[1] == self.at("ci.yaml"))
        followed = {  # refused under following pins too
            "commit_after_the_head": lambda p: (p.update(commits=p["commits"] + "0" * 25), p["edges"].append([]),
                                                p["parents"].append([len(p["parents"])])),
            # ci.yaml integrated; its live entry stays in use
            "overlap_unreferenced": lambda p: (p["live"].__setitem__(candidate, p["live"][pending]),
                                               p["live"].__setitem__(pending, head)),
            "overlap_removed_followed": cases["overlap_removed"]}
        for name, mutate in {**cases, **followed}.items():
            with self.subTest(case=name):
                self.refused(mutate, name in followed)

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
