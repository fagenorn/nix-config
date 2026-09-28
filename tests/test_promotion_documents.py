"""Seams 1 and 2 for the promotion documents (#127 D16): validate, capture, evaluate."""

import tempfile
import unittest
from pathlib import Path

from .promotion_test_support import (candidate_document, citation, draft, duplicate,
                                     evaluation_document, make_env, resolved_project,
                                     run, write_json)


class PromotionCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()
        self.root = self.tmp / "project"
        self.root.mkdir()
        self.env = make_env(self.tmp, resolved_project(self.root))


class ValidateTest(PromotionCase):
    def validate(self, document=None, text=None):
        path = self.tmp / "doc.json"
        if text is None:
            write_json(path, document)
        else:
            path.write_text(text, encoding="utf-8")
        return run(self.env, "validate", "--input", str(path))

    def assert_fault(self, document, pointer):
        code, payload, _ = self.validate(document)
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["error"]["code"], "invalid_document")
        self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])

    def test_each_kind_validates_and_nothing_is_resolved_or_written(self):
        for document in (draft(), candidate_document(), evaluation_document()):
            with self.subTest(kind=document["kind"]):
                self.assertEqual(self.validate(document)[:2], (0, {"valid": True}))
        self.assertFalse((self.tmp / "resolver-argv.jsonl").exists())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["bin", "doc.json", "project", "resolver-stdout.txt"])

    def test_section_presence_is_never_tied_to_state(self):
        evidence = {"bundle_path": "b.json", "bundle_id": "sha256:" + "d" * 64,
                    "state": "unmeasured", "gate_contract": "issue-70", "gate_version": 1}
        self.assertEqual(self.validate(candidate_document(evidence=evidence))[0], 0)

    def test_draft_faults_name_their_pointer(self):
        d = draft()
        faults = {
            "/lesson/title": draft(lesson=dict(d["lesson"], title="x" * 121)),
            "/lesson/source/path": draft(lesson=dict(d["lesson"], source=dict(
                citation(), path="/etc/passwd"))),
            "/lesson/source/revision": draft(lesson=dict(d["lesson"], source=dict(
                citation(), revision="abc"))),
            "/destination/layer": draft(destination=dict(d["destination"], layer="global")),
            "/destination/path": draft(destination=dict(d["destination"], path="a/../b.md")),
            "/destination/name": draft(destination=dict(d["destination"],
                                                        layer="native_adapter")),
            "/native_admission": draft(destination=dict(
                d["destination"], layer="native_extension", name="native.claude.op")),
            "/corroboration/repositories": draft(corroboration={
                "repositories": [citation()] * 9, "platform_governance": None}),
            "/local_duplicates/0/sha256": draft(local_duplicates=[duplicate(sha256="abc")]),
            "/local_duplicates/0/disposition": draft(
                local_duplicates=[duplicate(disposition="delete")]),
            "/schema_version": draft(schema_version=True),
            "/kind": draft(kind="promotion-other"),
            "/extra": draft(extra=1),
            "/lesson/generated_at": draft(lesson=dict(d["lesson"], generated_at="x")),
        }
        # A trailing newline must never pass an anchored pattern.
        trailing_newline = [
            ("/lesson/source/revision", draft(lesson=dict(d["lesson"], source=dict(
                citation(), revision="a" * 40 + "\n")))),
            ("/local_duplicates/0/sha256",
             draft(local_duplicates=[duplicate(sha256="a" * 64 + "\n")])),
            ("/destination/name", draft(destination=dict(
                d["destination"], layer="native_adapter", name="adapter.claude.x\n"))),
            ("/destination/name", draft(
                destination=dict(d["destination"], layer="native_extension",
                                 name="native.codex.op\n"),
                native_admission={"gate": "issue-64", "decision": "pending",
                                  "irreducible_scenario": "x"})),
        ]
        for pointer, document in [*faults.items(), *trailing_newline]:
            with self.subTest(pointer=pointer):
                self.assert_fault(document, pointer)

    def test_candidate_and_evaluation_faults_name_their_pointer(self):
        classification = {"rule": 4, "rule_id": "core_module",
                          "declared_layer": "standard_layer", "overridden_by_rule_1": False}
        evidence = {"bundle_path": "b.json", "bundle_id": "sha256:" + "d" * 64,
                    "state": "approved", "gate_contract": "issue-71", "gate_version": 1}
        faults = {
            "/candidate_id": candidate_document(candidate_id="sha256:xyz"),
            "/state": candidate_document(state="done"),
            "/classification/rule_id": candidate_document(classification=classification),
            "/evidence/gate_contract": candidate_document(evidence=evidence),
            "/tracker/ref": candidate_document(tracker={
                "ref": 0, "label": "promotion-candidate", "create_command": ["gh"]}),
            "/tracker/label": candidate_document(tracker={
                "ref": None, "label": "other", "create_command": ["gh"]}),
            "/history/0/to": candidate_document(history=[
                {"from": None, "to": "done", "actor": None, "rationale": None}]),
            "/outcome": evaluation_document(candidates=["sha256:" + "e" * 64]),
            "/commands": evaluation_document(commands=[]),
            "/scope/revision": evaluation_document(scope={
                "repository": "fagenorn/nix-config", "revision": "xyz"}),
        }
        # A trailing newline must never pass an anchored pattern.
        newline_id = "sha256:" + "e" * 64 + "\n"
        trailing_newline = [
            ("/candidate_id", candidate_document(candidate_id=newline_id)),
            ("/evidence/bundle_id", candidate_document(evidence=dict(
                evidence, gate_contract="issue-70", bundle_id=newline_id))),
            ("/candidates/0", evaluation_document(candidates=[newline_id], outcome="found")),
            ("/evaluation_id", evaluation_document(evaluation_id=newline_id)),
        ]
        for pointer, document in [*faults.items(), *trailing_newline]:
            with self.subTest(pointer=pointer):
                self.assert_fault(document, pointer)

    def test_unloadable_input_is_refused_with_the_empty_pointer(self):
        for text in ('{"kind": 1, "kind": 2}', '{"x": NaN}', "[]", "{ broken"):
            with self.subTest(text=text):
                code, payload, _ = self.validate(text=text)
                self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
                self.assertEqual(payload["error"]["violations"][0]["pointer"], "")
        code, payload, _ = run(self.env, "validate", "--input", str(self.tmp / "absent.json"))
        self.assertEqual((code, payload["error"]["code"]), (2, "unreadable_input"))
        self.assertEqual(payload["error"]["candidate_id"], None)

    def test_usage_errors_exit_2_without_json(self):
        code, payload, _ = run(self.env, "validate")
        self.assertEqual((code, payload), (2, None))
