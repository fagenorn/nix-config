"""Seams 1 and 2 for the promotion documents (#127 D16): validate, capture, evaluate."""

import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.canonical import telemetry_digest

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
        for text in ('{"kind": 1, "kind": 2}', '{"x": NaN}', "[]", "{ broken",
                     "[" * 100000):
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


CANDIDATES = ".agents/knowledge/promotions/candidates"


class CaptureTest(PromotionCase):
    def capture(self, document=None, output=None, *extra, env=None, cwd=None):
        source = write_json(self.root / ".agents/knowledge/promotions/drafts/d.json",
                            document or draft())
        (self.root / CANDIDATES).mkdir(parents=True, exist_ok=True)
        target = output or self.root / CANDIDATES / "c.json"
        code, payload, err = run(env or self.env, "capture", "--input", str(source),
                                 "--output", str(target), *extra, cwd=cwd)
        return code, payload, target

    def test_capture_writes_and_prints_a_captured_candidate(self):
        code, payload, target = self.capture(None, None, "--repo-root", str(self.root))
        self.assertEqual(code, 0, payload)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        authored = {m: draft()[m] for m in ("lesson", "destination", "corroboration",
                                            "local_duplicates", "native_admission")}
        self.assertEqual(payload["candidate_id"], telemetry_digest(authored))
        self.assertEqual([payload["state"], payload["classification"], payload["evidence"],
                          payload["deployment"], payload["tracker"]["ref"]],
                         ["captured", None, None, None, None])
        self.assertEqual(payload["history"], [{"from": None, "to": "captured",
                                               "actor": None, "rationale": None}])
        self.assertEqual(run(self.env, "validate", "--input", str(target))[0], 0)

    def test_create_command_is_the_exact_labelled_argv(self):
        payload = self.capture()[1]
        body = "\n".join([
            f"candidate: {payload['candidate_id']}",
            "document: .agents/knowledge/promotions/candidates/c.json",
            "source: fagenorn/argus AGENTS.md@unpinned### How we collaborate",
            "destination: standard_layer standards/the-bar "
            "home/common/agent-skills/standards/the-bar.md#### Investigate before changing",
            "corroboration: fagenorn/argus AGENTS.md### How we collaborate",
            "corroboration: elevenyellow/nodocom CLAUDE.md### How we collaborate"])
        self.assertEqual(payload["tracker"]["create_command"], [
            "gh", "issue", "create", "--repo", "fagenorn/nix-config",
            "--label", "promotion-candidate",
            "--title", "promotion: Investigate before changing", "--body", body])
        self.assertNotIn(draft()["lesson"]["statement"], body)

    def test_governance_proof_adds_its_line(self):
        document = draft(corroboration={"repositories": [], "platform_governance": "ADR"})
        body = self.capture(document)[1]["tracker"]["create_command"][-1]
        self.assertEqual(body.splitlines()[-1], "platform_governance: provided")

    def test_the_tracker_is_never_touched(self):
        self.assertEqual(self.capture()[0], 0)
        self.assertEqual(sorted(p.name for p in (self.tmp / "bin").iterdir()),
                         ["resolve-project"])

    def test_repo_root_is_passed_only_when_given(self):
        self.capture(None, None, "--repo-root", str(self.root))
        (self.root / CANDIDATES / "c.json").unlink()
        self.capture(cwd=self.root)
        argv = [json.loads(line) for line in (self.tmp / "resolver-argv.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(argv, [["resolve", "--repo-root", str(self.root)], ["resolve"]])

    def test_output_must_be_new_and_under_the_root(self):
        code, payload, target = self.capture(None, self.tmp / "outside.json")
        self.assertEqual((code, payload["error"]["code"]), (2, "output_outside_root"))
        self.assertFalse(target.exists())
        code, payload, target = self.capture(None, self.root / "missing" / "c.json")
        self.assertEqual((code, payload["error"]["code"]), (2, "output_outside_root"))
        self.assertFalse(target.parent.exists())
        existing = write_json(self.root / CANDIDATES / "c.json", {"keep": 1})
        before = existing.read_bytes()
        code, payload, _ = self.capture()
        self.assertEqual((code, payload["error"]["code"]), (2, "output_exists"))
        self.assertEqual(existing.read_bytes(), before)

    def test_resolver_failures_are_contract_unresolvable(self):
        refused = '{"error":{"code":"not_onboarded","repair_id":"x","violations":[]}}'

        def own(name):
            # One stub directory per case: make_env writes a fixed stub path, so
            # sharing self.tmp would let the last case's stub serve every case.
            sub = self.tmp / name
            sub.mkdir()
            return sub

        cases = {
            "not_onboarded": make_env(own("not_onboarded"), resolver_exit=2,
                                      resolver_stdout=refused),
            "garbage": make_env(own("garbage"), resolver_stdout="nope"),
            "gitlab": make_env(own("gitlab"), resolved_project(self.root, kind="gitlab")),
            "absent": dict(self.env, PATH=str(self.tmp / "empty-bin")),
        }
        for name, env in cases.items():
            with self.subTest(case=name):
                code, payload, target = self.capture(env=env)
                self.assertEqual((code, payload["error"]["code"]),
                                 (2, "contract_unresolvable"))
                self.assertFalse(target.exists())
                if name == "not_onboarded":
                    self.assertEqual(payload["error"]["violations"][0]["message"],
                                     "not_onboarded")

    def test_an_invalid_draft_writes_nothing(self):
        bad = draft(destination=dict(draft()["destination"], layer="global"))
        code, payload, target = self.capture(bad)
        self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
        self.assertFalse(target.exists())


class EvaluateTest(PromotionCase):
    SWEEP = "gh issue list --repo fagenorn/nix-config --label promotion-candidate --state open"

    def evaluate(self, *extra):
        target = self.root / "evaluation.json"
        code, payload, _ = run(self.env, "evaluate", "--output", str(target), *extra)
        return code, payload, target

    def test_an_empty_sweep_records_its_commands_verbatim(self):
        code, payload, target = self.evaluate("--command", self.SWEEP,
                                              "--command", "rg -n 'Investigate' .")
        self.assertEqual(code, 0, payload)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        self.assertEqual([payload["outcome"], payload["candidates"], payload["commands"],
                          payload["scope"]],
                         ["empty", [], [self.SWEEP, "rg -n 'Investigate' ."],
                          {"repository": "fagenorn/nix-config", "revision": None}])
        body = {k: v for k, v in payload.items() if k != "evaluation_id"}
        self.assertEqual(payload["evaluation_id"], telemetry_digest(body))

    def test_named_candidates_make_the_outcome_found(self):
        ids = ["sha256:" + "b" * 64, "sha256:" + "a" * 64]
        code, payload, _ = self.evaluate("--command", "x", "--candidate", ids[0],
                                         "--candidate", ids[1], "--revision", "f" * 40)
        self.assertEqual((code, payload["outcome"], payload["candidates"],
                          payload["scope"]["revision"]), (0, "found", ids, "f" * 40))

    def test_command_is_required(self):
        code, payload, target = self.evaluate()
        self.assertEqual((code, payload, target.exists()), (2, None, False))

    def test_malformed_flags_are_invalid_documents(self):
        for flags, pointer in ((("--candidate", "abc"), "/candidates/0"),
                               (("--revision", "xyz"), "/scope/revision")):
            with self.subTest(pointer=pointer):
                code, payload, target = self.evaluate("--command", "x", *flags)
                self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
                self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])
                self.assertFalse(target.exists())

    def test_recorded_commands_never_run(self):
        marker = self.tmp / "ran"
        self.assertEqual(self.evaluate("--command", f"touch {marker}")[0], 0)
        self.assertFalse(marker.exists())
