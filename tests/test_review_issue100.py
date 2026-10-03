"""Issue-100 verifier: archive envelope, two byte domains and the two-level payload (issue 234; S10, S11)."""
import hashlib, json, os, shutil, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import RECORD_POLICY_SHA256
from agent_tools.review_budget import describe
from agent_tools.review_forecast import ForecastError
from agent_tools.review_git import HistoryError
from agent_tools.review_issue100 import (ISSUE_100_PINS, Issue100Error, derive_100, fresh_records, historical_records,
                                         validate_100, verify_archive)

from .retained_review_test_support import issue100_fixture, snapshot, source_budget_env


def rehashed(row, **change):
    body = {**{k: v for k, v in row.items() if k != "id"}, **change}
    return {**body, "id": telemetry_digest(body)}


class Issue100Test(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.live, self.archive, self.pins = issue100_fixture(self.tmp)
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.limits = describe("review-package").limits

    def archive_bytes(self):
        return {p.relative_to(self.archive): p.read_bytes() for p in self.archive.rglob("*") if p.is_file()}

    def refused(self, call):
        with self.assertRaises(Issue100Error):
            call()

    def test_derive_validates_and_preserves_inputs(self):
        before = self.archive_bytes(), snapshot(self.repo), snapshot(self.live)
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        validate_100(payload, self.pins)
        merges = [e for e in payload["parent_edges"] if e["parent_ordinal"] > 1]
        self.assertEqual(len(merges), self.pins.expected_counts["merge_edges"])
        self.assertGreater(self.pins.expected_counts["merge_edges"], 0)
        self.assertEqual((self.archive_bytes(), snapshot(self.repo), snapshot(self.live)), before)

    def test_symlinked_oversized_or_wrong_digest_archive_member_is_refused(self):
        members = [self.archive / self.pins.producer_name, self.archive / self.pins.manifest_name,
                   sorted(self.archive.rglob("*.diff"))[0]]
        for member in members:
            original = member.read_bytes()
            for code, mutate in (
                    ("archive_unreadable", lambda: (member.unlink(), (self.tmp / "t").write_bytes(original),
                                                    member.symlink_to(self.tmp / "t"))),
                    ("archive_unreadable", lambda: member.write_bytes(original + b" ")),
                    ("archive_digest_mismatch", lambda: member.write_bytes(original[:-1] + b"X"))):
                with self.subTest(member=member.name, code=code):
                    mutate()
                    with self.assertRaises(Issue100Error) as caught:
                        verify_archive(self.archive, self.repo, self.pins)
                    self.assertEqual(caught.exception.code, code)
                    member.unlink(); member.write_bytes(original)

    def test_none_digest_pin_never_switches_the_digest_check_off(self):
        """Under a `None` pin a same-length forgery is refused, and so are the pinned bytes themselves."""
        for field, name, old, new in (("producer_sha256", self.pins.producer_name, b"/archive/", b"/archivX/"),
                                      ("manifest_sha256", self.pins.manifest_name, b'"subject":"c1"', b'"subject":"cX"')):
            member = self.archive / name
            original = member.read_bytes()
            forged = original.replace(old, new)
            self.assertEqual((len(forged), forged == original), (len(original), False))
            for raw in (forged, original):
                with self.subTest(field=field, forged=raw is forged):
                    member.write_bytes(raw)
                    with self.assertRaises(Issue100Error) as caught:
                        verify_archive(self.archive, self.repo, replace(self.pins, **{field: None}))
                    self.assertEqual(caught.exception.code, "archive_digest_mismatch")
            member.write_bytes(original)

    def test_digest_pinned_producer_without_an_artifact_path_is_an_archive_mismatch(self):
        member = self.archive / self.pins.producer_name
        envelope = json.loads(member.read_bytes())
        del envelope["artifact"]["path"]
        raw = json.dumps(envelope, sort_keys=True).encode()
        member.write_bytes(raw)
        pins = replace(self.pins, producer_bytes=len(raw), producer_sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(Issue100Error) as caught:
            verify_archive(self.archive, self.repo, pins)
        self.assertEqual(caught.exception.code, "archive_mismatch")

    def test_domain_label_or_policy_swap_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        tables = payload["tables"]
        h, f = tables["historical"]["record_table_policy"], tables["fresh"]["record_table_policy"]
        for historical, fresh in ((f, h), ({**h, "domain": f["domain"]}, f),
                                  ({**h, "policy_sha256": f["policy_sha256"]}, f)):
            swapped = {**payload, "tables": {"historical": {**tables["historical"], "record_table_policy": historical},
                                             "fresh": {**tables["fresh"], "record_table_policy": fresh}}}
            self.refused(lambda: validate_100(swapped, self.pins))

    def test_rehashed_edge_order_or_coverage_change_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        edges = payload["parent_edges"]
        for changed in ([edges[1], edges[0], *edges[2:]], edges[:-1],
                        [*edges[:-1], {**edges[-1], "parent": self.pins.live}]):
            self.refused(lambda: validate_100({**payload, "parent_edges": changed}, self.pins))

    def test_foreign_head_substituted_throughout_the_history_is_invalid(self):
        """`range.commits` ends at the pinned head, even when both edge tables agree on a substitute."""
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        commits, foreign = payload["range"]["commits"], "f" * 40
        self.assertEqual((commits[-1], foreign in commits), (self.pins.head, False))

        def swapped(oid):
            return foreign if oid == self.pins.head else oid

        def ends(rows):
            return [{**row, "parent": swapped(row["parent"]), "commit": swapped(row["commit"])} for row in rows]

        forged = {**payload, "range": {**payload["range"], "commits": [swapped(oid) for oid in commits]},
                  "parent_edges": ends(payload["parent_edges"]), "edges": ends(payload["edges"])}
        self.assertEqual(forged["range"]["head"], self.pins.head)
        with self.assertRaises(Issue100Error) as caught:
            validate_100(forged, self.pins)
        self.assertEqual(caught.exception.code, "invalid_payload")

    def test_consistently_rehashed_edge_tables_are_invalid(self):
        """Both edge levels changed together, with every contribution's references and id recomputed."""
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        raw, edges = payload["parent_edges"], payload["edges"]
        pairs = list(zip(raw, edges))

        def rebuilt(pairs):
            edges = [edge for _, edge in pairs]
            rows = []
            for row in payload["contributions"]:
                names = {row["path"]}
                for _ in edges:  # a fixed point over rename chains
                    names |= {n for e in edges for r in e["records"] if {r["path"], r["old_path"]} & names
                              for n in (r["path"], r["old_path"])}
                refs = [[e, n] for e, edge in enumerate(edges) for n, r in enumerate(edge["records"])
                        if {r["path"], r["old_path"]} & names]
                rows.append(rehashed(row, edge_refs=refs))
            return {**payload, "parent_edges": [p for p, _ in pairs], "edges": edges, "contributions": rows}

        validate_100(rebuilt(pairs), self.pins)  # the independent rebuild agrees with derivation
        merge = next(n for n, (p, _) in enumerate(pairs) if p["parent_ordinal"] == 2)
        outside = {"parent": self.pins.live}
        for changed in ([pairs[1], pairs[0], *pairs[2:]], pairs[:-1], [*pairs[:merge], *pairs[merge + 1:]],
                        [*pairs[:-1], tuple({**side, **outside} for side in pairs[-1])]):
            self.refused(lambda: validate_100(rebuilt(changed), self.pins))

    def test_rehashed_contribution_fact_change_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        rows = payload["contributions"]
        by = {row["disposition"]: n for n, row in reversed(list(enumerate(rows)))}
        pending = next(n for n, row in enumerate(rows) if row["pending"] is not None)
        ordinary = next(n for n, row in enumerate(rows) if row["disposition"] == "candidate" and row["pending"] is None)
        changes = [
            (by["candidate"], {"disposition": "integrated"}),
            (by["candidate"], {"live_entry": rows[by["candidate"]]["head_entry"]}),  # a candidate label over integration
            (by["candidate"], {"edge_refs": rows[by["candidate"]]["edge_refs"][:-1]}),
            (by["candidate"], {"record_sha256": "0" * 64}),
            (by["integrated"], {"disposition": "candidate"}),
            (by["integrated"], {"pending": rows[pending]["pending"]}),  # an overlap on a non-candidate
            (by["historical_process"], {"disposition": "candidate"}),
            (pending, {"pending": None}),
            (ordinary, {"pending": rows[pending]["pending"]}),  # one overlap referenced twice
            (pending, {"disposition": "reconciled"}),
        ]
        for index, change in changes:
            with self.subTest(index=index, change=change):
                changed = [*rows[:index], rehashed(rows[index], **change), *rows[index + 1:]]
                self.refused(lambda: validate_100({**payload, "contributions": changed}, self.pins))
        overlap = payload["pending_overlaps"][0]
        changed = [rehashed(overlap, live_entry=overlap["head_entry"]), *payload["pending_overlaps"][1:]]
        self.refused(lambda: validate_100({**payload, "pending_overlaps": changed}, self.pins))

    def test_summary_disagreeing_with_tables_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        summary = {**payload["summary"], "integrated": payload["summary"]["integrated"] + 1}
        self.refused(lambda: validate_100({**payload, "summary": summary}, self.pins))

    def test_edge_record_count_is_recomputed(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        edges = payload["edges"]
        used = {tuple(ref) for row in payload["contributions"] for ref in row["edge_refs"]}
        # The last record of an edge that no contribution references: only the count can change.
        n = next(n for n, edge in enumerate(edges) if edge["records"] and (n, len(edge["records"]) - 1) not in used)
        changed = [*edges[:n], {**edges[n], "records": edges[n]["records"][:-1]}, *edges[n + 1:]]
        with self.assertRaises(Issue100Error) as caught:
            validate_100({**payload, "edges": changed}, self.pins)
        self.assertEqual(caught.exception.code, "invalid_payload")
        summary = {**payload["summary"], "edge_records": payload["summary"]["edge_records"] - 1}
        self.refused(lambda: validate_100({**payload, "edges": changed, "summary": summary}, self.pins))

    def test_missing_superseded_criterion_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        criteria = [row for row in payload["criteria"] if row["id"] != "AC-OLD-01"]
        self.assertEqual(len(criteria), len(payload["criteria"]) - 1)
        self.refused(lambda: validate_100({**payload, "criteria": criteria}, self.pins))
        revived = [{**row, "state": "governing", "superseded_by": None} if row["id"] == "AC-OLD-01" else row
                   for row in payload["criteria"]]
        self.refused(lambda: validate_100({**payload, "criteria": revived}, self.pins))

    def test_historical_bytes_never_bound_fresh(self):
        self.assertNotEqual(self.pins.historical.bytes, self.pins.fresh.bytes)
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        tables = payload["tables"]
        swapped = {**payload, "tables": {**tables, "fresh": {**tables["fresh"], "records": tables["historical"]["records"]}}}
        self.refused(lambda: validate_100(swapped, self.pins))
        # Shape-valid: historical byte counts under the fresh paths and digests, so only the byte sum refuses.
        fresh, historical = tables["fresh"]["records"], tables["historical"]["records"]
        self.assertEqual(len(historical), len(fresh))
        borrowed = [{**record, "bytes": old["bytes"]} for record, old in zip(fresh, historical)]
        self.assertEqual(sum(record["bytes"] for record in borrowed), self.pins.historical.bytes)
        bound = {**payload, "tables": {**tables, "fresh": {**tables["fresh"], "records": borrowed}}}
        self.refused(lambda: validate_100(bound, self.pins))

    def test_inputs_unchanged_on_failure(self):
        before = self.archive_bytes(), snapshot(self.repo), snapshot(self.live)
        with self.assertRaises(Issue100Error) as caught:
            derive_100(self.repo, self.live, self.archive, replace(self.pins, producer_sha256="0" * 64), self.limits)
        self.assertEqual(caught.exception.code, "archive_digest_mismatch")
        self.assertEqual((self.archive_bytes(), snapshot(self.repo), snapshot(self.live)), before)

    def test_virtualized_history_is_unauthenticated(self):
        (self.repo / ".git/info/grafts").write_text(self.pins.head + "\n")
        with self.assertRaises(Issue100Error) as caught:
            derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        self.assertEqual(caught.exception.code, "history_unauthenticated")
        self.assertIsInstance(caught.exception.__cause__, (HistoryError, ForecastError))

    def test_archive_and_domains_report_their_pinned_identities(self):
        evidence = verify_archive(self.archive, self.repo, self.pins)
        shards = sorted(self.archive.rglob("*.diff"))
        self.assertEqual((evidence["producer_sha256"], evidence["manifest_sha256"]),
                         (self.pins.producer_sha256, self.pins.manifest_sha256))
        self.assertEqual([row["path"] for row in evidence["shards"]],
                         [p.relative_to(self.archive).as_posix() for p in shards])
        self.assertEqual(sum(row["bytes"] for row in evidence["shards"]), self.pins.historical.bytes)
        for records, domain in ((historical_records(self.repo, self.pins), self.pins.historical),
                                (fresh_records(self.repo, self.pins, self.limits), self.pins.fresh)):
            self.assertEqual((len(records), sum(r["bytes"] for r in records)), (domain.records, domain.bytes))
        for call in (lambda: fresh_records(self.repo, replace(self.pins, fresh=replace(self.pins.fresh, sha256="0" * 64)),
                                           self.limits),
                     lambda: historical_records(self.repo, replace(self.pins, historical=replace(self.pins.historical,
                                                                                                 records=1)))):
            with self.assertRaises(Issue100Error) as caught:
                call()
            self.assertEqual(caught.exception.code, "domain_mismatch")

    def test_real_pins_carry_the_spec_constants(self):
        pins = ISSUE_100_PINS
        self.assertEqual((pins.base, pins.head, pins.live),
                         ("6d4b7a49dd3a44c079c8310e902a86665a6805f0", "a7b7c6f45787c7c928d064b46ed499087b5b3c46",
                          "cba57498b1ec25f904bd2653029636c79abba41f"))
        self.assertEqual((pins.historical.name, pins.historical.bytes, pins.historical.records),
                         ("retained-git-records/v1", 1005707, 115))
        self.assertEqual((pins.fresh.name, pins.fresh.policy_sha256, pins.fresh.bytes, pins.fresh.records),
                         ("review-git-records/v1", RECORD_POLICY_SHA256, 1012913, 115))
        self.assertEqual(pins.expected_counts, {
            "commits": 82, "parent_edges": 91, "merge_edges": 9, "edge_records": 543, "contributions": 115,
            "historical_process": 8, "integrated": 38, "candidate": 69, "candidate_ordinary": 65,
            "candidate_reconciliation": 4, "pending_overlaps": 4, "reconciled": 0})
        self.assertEqual(len(pins.pending_paths), 4)
        self.assertEqual([c["state"] for c in pins.criteria], ["superseded"] * 5 + ["governing"] * 5)
        with self.assertRaises(Issue100Error) as caught:  # the real pins pass their own checks
            validate_100({}, pins)
        self.assertEqual(caught.exception.code, "invalid_payload")
        with self.assertRaises(Issue100Error) as caught:
            validate_100({}, replace(pins, recipe=pins.recipe[:-1]))
        self.assertEqual(caught.exception.code, "invalid_pins")


if __name__ == "__main__":
    unittest.main()
