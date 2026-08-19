from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).parents[4]
SCRIPT = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
FIXTURES = Path(__file__).parent / "fixtures/artifact-budgets"
sys.path.insert(0, str(SCRIPT.parent))
import artifact_budget


class ArtifactBudgetCliTest(unittest.TestCase):
    def run_check(self, kind: str, root: Path, policy: Path = POLICY):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "check", "--kind", kind,
             "--root", str(root), "--policy", str(policy), "--format", "json"],
            text=True, capture_output=True, check=False,
        )

    def run_validate(self, boundary: str, payload: object, use_stdin: bool):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if use_stdin:
            return subprocess.run(
                [sys.executable, str(SCRIPT), "validate-report", "--boundary", boundary,
                 "--input", "-", "--policy", str(POLICY)],
                input=encoded, capture_output=True, check=False,
            )
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate.json"
            candidate.write_bytes(encoded)
            return subprocess.run(
                [sys.executable, str(SCRIPT), "validate-report", "--boundary", boundary,
                 "--input", str(candidate), "--policy", str(POLICY)],
                capture_output=True, check=False,
            )

    def test_single_file_exact_boundary_and_unicode_plus_one(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "spec.md"
            path.write_bytes(b"x" * 65_536)
            exact = self.run_check("design-spec", path)
            self.assertEqual(exact.returncode, 0, exact.stderr)
            result = json.loads(exact.stdout)
            self.assertEqual(
                result["metrics"],
                {"root_bytes": 65_536, "total_bytes": 65_536,
                 "file_count": 1, "largest_member_bytes": 0},
            )
            path.write_bytes(b"x" * 65_535 + "é".encode("utf-8"))
            over = self.run_check("design-spec", path)
            self.assertEqual(over.returncode, 3, over.stderr)
            self.assertEqual(json.loads(over.stdout)["violations"],
                             ["root_bytes", "aggregate_bytes"])

    def test_plan_discovers_members_and_rejects_ninth_or_unindexed_member(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "plan.md"
            members = Path(raw) / "plan.tasks"
            members.mkdir()
            rows = []
            for number in range(1, 9):
                member = members / f"task-{number}.md"
                member.write_text(f"# Task {number}\n", encoding="utf-8")
                rows.append(f"Task {number} — T{number} — f{number} — full — "
                            f"[task-{number}.md](plan.tasks/task-{number}.md)")
            root.write_text("## Task index\n\n" + "\n\n".join(rows) + "\n", encoding="utf-8")
            self.assertEqual(self.run_check("implementation-plan", root).returncode, 0)
            (members / "task-9.md").write_text("# Task 9\n", encoding="utf-8")
            ninth = self.run_check("implementation-plan", root)
            self.assertEqual(ninth.returncode, 2)
            self.assertEqual(ninth.stdout, "")

    def test_valid_measurement_is_deterministic_and_violations_are_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "handoff.md"
            path.write_bytes(b"h" * 8_193)
            first = self.run_check("handoff", path)
            second = self.run_check("handoff", path)
            self.assertEqual(first.returncode, 3)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(set(json.loads(first.stdout)),
                             {"interface_version", "kind", "status", "metrics", "violations"})

    def test_malformed_policy_and_package_shape_fail_without_success_output(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "handoff.md"
            root.write_text("small", encoding="utf-8")
            policy = directory / "bad.json"
            policy.write_text('{"schema_version":true}', encoding="utf-8")
            result = self.run_check("handoff", root, policy)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())

    def test_installed_default_policy_symlink_is_trusted_but_explicit_symlink_is_not(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            share = directory / ".agents/share"
            share.mkdir(parents=True)
            installed = share / "artifact-budget-policy.json"
            installed.symlink_to(POLICY)
            root = directory / "handoff.md"
            root.write_text("small", encoding="utf-8")
            default = subprocess.run(
                [sys.executable, str(SCRIPT), "check", "--kind", "handoff",
                 "--root", str(root), "--format", "json"],
                text=True, capture_output=True, check=False,
                env={**os.environ, "HOME": str(directory)},
            )
            self.assertEqual(default.returncode, 0, default.stderr)
            report = subprocess.run(
                [sys.executable, str(SCRIPT), "validate-report", "--boundary", "producer",
                 "--input", "-"],
                input=b'{"state":"failed","artifact":null,"notes":"installed"}',
                capture_output=True, check=False,
                env={**os.environ, "HOME": str(directory)},
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            explicit = self.run_check("handoff", root, installed)
            self.assertEqual((explicit.returncode, explicit.stdout), (2, ""))

    def materialize_descriptor(self, item: dict[str, object], directory: Path) -> Path:
        kind = item["kind"]
        root = directory / {"design-spec": "spec.md", "implementation-plan": "plan.md",
                            "handoff": "handoff.md", "review-package": "review.json"}[kind]
        target = item["root_bytes"]
        member_sizes = item["member_bytes"]
        if kind in {"design-spec", "handoff"}:
            root.write_bytes(b"x" * target)
            return root
        if kind == "implementation-plan":
            members = directory / "plan.tasks"
            members.mkdir()
            rows = []
            for number, size in enumerate(member_sizes, 1):
                prefix = f"# Task {number}\n".encode()
                (members / f"task-{number}.md").write_bytes(prefix + b"x" * (size - len(prefix)))
                rows.append(f"Task {number} — T{number} — f — full — "
                            f"[task-{number}.md](plan.tasks/task-{number}.md)")
            prefix = ("## Task index\n\n" + "\n\n".join(rows) + "\n").encode()
            root.write_bytes(prefix + b" " * (target - len(prefix)))
            return root
        members = directory / "review.shards"
        members.mkdir()
        shards = []
        for number, size in enumerate(member_sizes, 1):
            path = members / f"shard-{number:03d}.diff"
            path.write_bytes(b"d" * size)
            shards.append({"path": f"review.shards/{path.name}", "bytes": size})
        manifest = {"interface_version": 1, "kind": "review-package", "purpose": "diff-review",
                    "range": {"base": "a" * 40, "head": "b" * 40},
                    "commits": [],
                    "stat": {"files_changed": len(shards), "insertions": 0, "deletions": 0},
                    "shards": shards, "total_diff_bytes": sum(member_sizes),
                    "coverage": {"complete": True, "file_diff_count": len(shards)}}
        prefix = json.dumps(manifest, separators=(",", ":")).encode()
        root.write_bytes(prefix + b" " * (target - len(prefix)))
        return root

    def test_repository_descriptors_drive_cli_results(self):
        for fixture_name in ("small-issue.json", "oversized-issue.json"):
            fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
            self.assertEqual(set(fixture), {"schema_version", "case", "artifacts"})
            for item in fixture["artifacts"]:
                self.assertEqual(set(item), {"kind", "case", "shape", "root_bytes",
                                             "member_bytes", "expected"})
                self.assertEqual(set(item["expected"]), {"exit_code", "status", "metrics",
                                                         "violations", "producer_state"})
                with self.subTest(fixture=fixture_name, case=item["case"]), \
                     tempfile.TemporaryDirectory() as raw:
                    root = self.materialize_descriptor(item, Path(raw))
                    result = self.run_check(item["kind"], root)
                    expected = item["expected"]
                    self.assertEqual(result.returncode, expected["exit_code"], result.stderr)
                    measured = json.loads(result.stdout)
                    self.assertEqual(measured["status"], expected["status"])
                    self.assertEqual(measured["metrics"], expected["metrics"])
                    self.assertEqual(measured["violations"], expected["violations"])
                    if result.returncode == 3:
                        self.assertNotEqual(measured["status"], "within_budget")

    @staticmethod
    def metrics():
        return {"root_bytes": 1, "total_bytes": 1, "file_count": 1,
                "largest_member_bytes": 0}

    def full(self, kind: str, over: bool = False):
        value = {"kind": kind, "path": f"artifacts/{kind}.json", "metrics": self.metrics(),
                 "budget_status": "over_budget" if over else "within_budget"}
        if over:
            value["violations"] = ["root_bytes"]
        return value

    def test_every_producer_report_matrix_row(self):
        rows = [
            ({"state": "complete", "artifact": self.full("handoff"), "notes": "ok"}, True),
            ({"state": "decompose_required", "artifact": self.full("design-spec", True), "notes": "ok"}, True),
            ({"state": "decompose_required", "artifact": self.full("implementation-plan", True), "notes": "ok"}, True),
            ({"state": "decompose_required", "artifact": self.full("review-package", True), "notes": "ok"}, True),
            ({"state": "stopped", "artifact": self.full("handoff", True), "notes": "ok"}, True),
            ({"state": "failed", "artifact": None, "notes": "no root"}, True),
            ({"state": "failed", "artifact": {"kind": "handoff", "path": "h.md"}, "notes": "root"}, True),
            ({"state": "complete", "artifact": self.full("handoff", True), "notes": "bad"}, False),
            ({"state": "decompose_required", "artifact": self.full("handoff", True), "notes": "bad"}, False),
            ({"state": "failed", "artifact": {"kind": "handoff", "path": "h.md", "metrics": self.metrics()}, "notes": "bad"}, False),
        ]
        for number, (payload, valid) in enumerate(rows):
            result = self.run_validate("producer", payload, number % 2 == 0)
            self.assertEqual(result.returncode, 0 if valid else 2)
            if valid:
                expected = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n").encode()
                self.assertEqual(result.stdout, expected)
            else:
                self.assertEqual((result.stdout, result.stderr),
                                 (b"", b"artifact-budget: invalid report\n"))

    def make_sdd(self, state, review, conformance, correctness, verification,
                 base, head, detail_state, report_path):
        notes = f"details: {report_path}" if report_path else "no durable detail"
        return {"state": state, "review_state": review,
                "conformance_verdict": conformance, "correctness_verdict": correctness,
                "verification_state": verification, "base_sha": base, "head_sha": head,
                "detail_state": detail_state, "report_path": report_path, "notes": notes}

    def test_every_sdd_report_matrix_row(self):
        detail = ".superpowers/issue-delivery/49/run-1/sdd-a.json"
        retained = ".superpowers/sdd/plan/retained-detail.json"
        valid = [
            self.make_sdd("complete", "clean", "clean", "clean", "passed", "a"*40, "b"*40, "none", None),
            self.make_sdd("residuals", "residuals", "clean", "findings", "passed", "a"*40, "b"*40, "present", detail),
            self.make_sdd("failed", "unknown", "not_run", "not_run", "not_run", None, None, "none", None),
            self.make_sdd("failed", "unknown", "not_run", "clean", "failed", "a"*40, "b"*40, "none", None),
            self.make_sdd("failed", "unknown", "clean", "findings", "failed", "a"*40, "b"*40, "present", detail),
            self.make_sdd("failed", "unknown", "findings", "clean", "passed", "a"*40, "b"*40, "unpublished", retained),
        ]
        invalid = [
            {**valid[0], "correctness_verdict": "findings"},
            {**valid[1], "detail_state": "none", "report_path": None, "notes": "none"},
            {**valid[2], "base_sha": "a"*40},
            {**valid[3], "conformance_verdict": "clean", "correctness_verdict": "clean"},
            {**valid[4], "report_path": None},
            {**valid[5], "state": "complete", "review_state": "clean"},
        ]
        for i, payload in enumerate(valid):
            self.assertEqual(self.run_validate("sdd", payload, i % 2 == 0).returncode, 0)
        for i, payload in enumerate(invalid):
            result = self.run_validate("sdd", payload, i % 2 == 1)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, b"", b"artifact-budget: invalid report\n"))

    def lifecycle(self):
        return {"ledger_repo_root": None, "run_id": None, "attempt": None,
                "owner": None, "owner_worktree": None, "issue_number": 49,
                "branch": "issue-49", "worktree_path": "/tmp/issue-49", "auto": True}

    def test_ship_handoff_and_summary_matrices(self):
        detail = ".superpowers/issue-delivery/49/run-1/sdd-a.json"
        retained = ".superpowers/sdd/plan/retained-detail.json"
        complete = {**self.lifecycle(), "state": "complete", "spec_artifact": self.full("design-spec"),
                    "plan_artifact": self.full("implementation-plan"), "head_sha": "b"*40,
                    "review_state": "clean", "report_path": None, "notes": "ok"}
        before = {**self.lifecycle(), "state": "failed", "spec_artifact": None,
                  "plan_artifact": None, "head_sha": None, "review_state": "unknown",
                  "report_path": None, "notes": "failed"}
        after = {**self.lifecycle(), "state": "failed", "spec_artifact": self.full("design-spec"),
                 "plan_artifact": self.full("implementation-plan"), "head_sha": "b"*40,
                 "review_state": "residuals", "report_path": detail, "notes": f"details: {detail}"}
        for value in (complete, before, after):
            self.assertEqual(self.run_validate("ship-handoff", value, True).returncode, 0)
        for value in ({**complete, "plan_artifact": None}, {**before, "spec_artifact": self.full("design-spec")},
                      {**after, "head_sha": None}):
            self.assertEqual(self.run_validate("ship-handoff", value, False).returncode, 2)

        summaries = [
            {"issue": 49, "state": "merged", "pr_url": "https://example.test/pr/1",
             "merge_sha": "c"*40, "issue_closed": True, "discussion_items": [],
             "detail_state": "none", "report_path": None, "notes": "none"},
            {"issue": 49, "state": "stopped", "pr_url": None, "merge_sha": None,
             "issue_closed": False, "discussion_items": [], "detail_state": "present",
             "report_path": detail, "notes": f"details: {detail}"},
            {"issue": 49, "state": "failed", "pr_url": None, "merge_sha": None,
             "issue_closed": False, "discussion_items": [], "detail_state": "unpublished",
             "report_path": retained, "notes": f"retained: {retained}"},
        ]
        for value in summaries:
            self.assertEqual(self.run_validate("ship-summary", value, True).returncode, 0)
        bad = [{**summaries[0], "merge_sha": None}, {**summaries[1], "discussion_items": ["lost"]},
               {**summaries[2], "report_path": None}]
        for value in bad:
            self.assertEqual(self.run_validate("ship-summary", value, False).returncode, 2)

    def test_ship_handoff_residuals_requires_durable_report_path(self):
        candidate = {**self.lifecycle(), "state": "complete",
                     "spec_artifact": self.full("design-spec"),
                     "plan_artifact": self.full("implementation-plan"),
                     "head_sha": "b" * 40, "review_state": "residuals",
                     "report_path": None, "notes": "detail was dropped"}
        result = self.run_validate("ship-handoff", candidate, use_stdin=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, b"", b"artifact-budget: invalid report\n"))

    def test_unpublished_rejects_the_delivery_home_itself(self):
        candidate = self.make_sdd(
            "failed", "unknown", "findings", "clean", "failed",
            "a" * 40, "b" * 40, "unpublished", ".superpowers/issue-delivery",
        )
        result = self.run_validate("sdd", candidate, use_stdin=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, b"", b"artifact-budget: invalid report\n"))

    def test_validate_report_rejects_wire_parse_and_io_failures(self):
        malformed = (b'{"state":"failed","state":"failed","artifact":null,"notes":"x"}',
                     b"\xff", b"[]", b"{}{}", b'{"value":NaN}')
        for raw in malformed:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate-report", "--boundary", "producer",
                 "--input", "-", "--policy", str(POLICY)], input=raw,
                capture_output=True, check=False)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, b"", b"artifact-budget: invalid report\n"))
        missing = subprocess.run(
            [sys.executable, str(SCRIPT), "validate-report", "--boundary", "producer",
             "--input", "/definitely/missing/report.json", "--policy", str(POLICY)],
            capture_output=True, check=False)
        self.assertEqual((missing.returncode, missing.stdout, missing.stderr),
                         (2, b"", b"artifact-budget: cannot read report\n"))
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "target.json"
            target.write_text('{"state":"failed","artifact":null,"notes":"x"}', encoding="utf-8")
            link = Path(raw) / "link.json"
            link.symlink_to(target)
            symlinked = subprocess.run(
                [sys.executable, str(SCRIPT), "validate-report", "--boundary", "producer",
                 "--input", str(link), "--policy", str(POLICY)], capture_output=True, check=False)
            self.assertEqual((symlinked.returncode, symlinked.stdout, symlinked.stderr),
                             (2, b"", b"artifact-budget: cannot read report\n"))
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        oversized = {"issue": 49, "state": "stopped",
                     "pr_url": "https://example.test/" + "x" * policy["phase_reports"]["wire_max_bytes"],
                     "merge_sha": None, "issue_closed": False, "discussion_items": [],
                     "detail_state": "none", "report_path": None, "notes": "wire bound"}
        over = self.run_validate("ship-summary", oversized, use_stdin=True)
        self.assertEqual((over.returncode, over.stdout, over.stderr),
                         (2, b"", b"artifact-budget: invalid report\n"))

    def test_validate_detail_input_is_one_strict_cli_boundary(self):
        finding = {"axis": "ship", "severity": "Minor", "status": "minor",
                   "text": "kept", "ruling": None}
        valid = {"interface_version": 1, "findings": [finding]}
        canonical = (json.dumps(valid, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "retained.json"
            path.write_bytes(canonical)
            accepted = subprocess.run(
                [sys.executable, str(SCRIPT), "validate-detail-input", "--input", str(path),
                 "--policy", str(POLICY)], capture_output=True, check=False)
            self.assertEqual((accepted.returncode, accepted.stdout, accepted.stderr), (0, canonical, b""))
        invalid = (b"", b"{", b'{"interface_version":2,"findings":[]}',
                   b'{"interface_version":1,"items":[]}', b'{"interface_version":1,"findings":[]}',
                   json.dumps({"interface_version": 1, "findings": [{**finding, "status": "unknown"}]}).encode(),
                   json.dumps({"interface_version": 1, "findings": [{**finding, "text": 1}]}).encode(),
                   json.dumps({"interface_version": 1, "findings": [{**finding, "status": "parked", "ruling": None}]}).encode())
        for payload in invalid:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate-detail-input", "--input", "-",
                 "--policy", str(POLICY)], input=payload, capture_output=True, check=False)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, b"", b"artifact-budget: invalid detail input\n"))

    def review_manifest(self, directory: Path, suffix="diff", size=4):
        root = directory / "review.json"
        members = directory / "review.shards"
        members.mkdir()
        member = members / f"shard-001.{suffix}"
        member.write_bytes(b"d" * size)
        manifest = {"interface_version": 1, "kind": "review-package", "purpose": "diff-review",
                    "range": {"base": "a"*40, "head": "b"*40}, "commits": [],
                    "stat": {"files_changed": 1, "insertions": 1, "deletions": 0},
                    "shards": [{"path": f"review.shards/{member.name}", "bytes": size}],
                    "total_diff_bytes": size,
                    "coverage": {"complete": True, "file_diff_count": 1}}
        root.write_text(json.dumps(manifest), encoding="utf-8")
        return root, member, manifest

    def test_review_manifest_member_boundary_and_reference_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root, member, manifest = self.review_manifest(Path(raw), size=65_536)
            self.assertEqual(self.run_check("review-package", root).returncode, 0)
            member.write_bytes(b"d" * 65_537)
            manifest["shards"][0]["bytes"] = 65_537
            manifest["total_diff_bytes"] = 65_537
            root.write_text(json.dumps(manifest), encoding="utf-8")
            over = self.run_check("review-package", root)
            self.assertEqual(over.returncode, 3)
            self.assertIn("member_bytes", json.loads(over.stdout)["violations"])

    def test_delivery_detail_manifest_uses_the_same_review_limits(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "delivery.json"
            members = directory / "delivery.shards"
            members.mkdir()
            record = (json.dumps({"axis": "correctness", "severity": "Minor", "status": "parked",
                                  "text": "detail", "ruling": "accepted"},
                                 sort_keys=True, separators=(",", ":")) + "\n").encode()
            (members / "shard-001.jsonl").write_bytes(record)
            manifest = {"interface_version": 1, "kind": "review-package", "purpose": "delivery-detail",
                        "context": {"issue": 49, "branch": "issue-49", "producer": "sdd"},
                        "shards": [{"path": "delivery.shards/shard-001.jsonl", "bytes": len(record)}],
                        "total_detail_bytes": len(record),
                        "coverage": {"complete": True, "finding_count": 1}}
            root.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_check("review-package", root).returncode, 0)
            invalid_record = (json.dumps({"axis": "correctness", "severity": "Minor",
                                          "status": "parked", "text": "detail", "ruling": None},
                                         sort_keys=True, separators=(",", ":")) + "\n").encode()
            (members / "shard-001.jsonl").write_bytes(invalid_record)
            manifest["shards"][0]["bytes"] = len(invalid_record)
            manifest["total_detail_bytes"] = len(invalid_record)
            root.write_text(json.dumps(manifest), encoding="utf-8")
            invalid_parked = self.run_check("review-package", root)
            self.assertEqual((invalid_parked.returncode, invalid_parked.stdout), (2, ""))
            (members / "shard-001.jsonl").write_bytes(record)
            manifest["shards"][0]["bytes"] = len(record)
            manifest["total_detail_bytes"] = len(record)
            manifest["context"]["issue"] = True
            root.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_check("review-package", root).returncode, 2)

    def test_review_manifest_rejects_boolean_in_every_integer_family(self):
        with tempfile.TemporaryDirectory() as raw:
            root, _, valid = self.review_manifest(Path(raw))
            mutations = {
                "interface_version": lambda m: m.__setitem__("interface_version", True),
                "files": lambda m: m["stat"].__setitem__("files_changed", True),
                "insertions": lambda m: m["stat"].__setitem__("insertions", True),
                "deletions": lambda m: m["stat"].__setitem__("deletions", True),
                "bytes": lambda m: m["shards"][0].__setitem__("bytes", True),
                "total": lambda m: m.__setitem__("total_diff_bytes", True),
                "coverage": lambda m: m["coverage"].__setitem__("file_diff_count", True),
            }
            for mutate in mutations.values():
                manifest = deepcopy(valid)
                mutate(manifest)
                root.write_text(json.dumps(manifest), encoding="utf-8")
                result = self.run_check("review-package", root)
                self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_unknown_gapped_symlinked_and_duplicate_package_entries_fail(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            members = directory / "plan.tasks"
            members.mkdir()
            (members / "task-2.md").write_text("# Task 2\n", encoding="utf-8")
            root.write_text("## Task index\n\nTask 2 — gap — f — full — [task-2.md](plan.tasks/task-2.md)\n", encoding="utf-8")
            self.assertEqual(self.run_check("implementation-plan", root).returncode, 2)
            (members / "notes.md").write_text("orphan", encoding="utf-8")
            self.assertEqual(self.run_check("implementation-plan", root).returncode, 2)
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            target = directory / "real.md"
            target.write_text("content", encoding="utf-8")
            link = directory / "handoff.md"
            link.symlink_to(target)
            self.assertEqual(self.run_check("handoff", link).returncode, 2)
        with tempfile.TemporaryDirectory() as raw:
            malformed = Path(raw) / "handoff.md"
            malformed.write_bytes(b"\xff")
            result = self.run_check("handoff", malformed)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_missing_symlinked_unreadable_and_duplicate_member_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            root.write_text("## Task index\n", encoding="utf-8")
            result = self.run_check("implementation-plan", root)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            real = directory / "real.tasks"
            real.mkdir()
            root = directory / "plan.md"
            root.write_text("## Task index\n", encoding="utf-8")
            (directory / "plan.tasks").symlink_to(real, target_is_directory=True)
            result = self.run_check("implementation-plan", root)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            members = directory / "plan.tasks"
            members.mkdir()
            target = directory / "target.md"
            target.write_text("# Task 1\n", encoding="utf-8")
            (members / "task-1.md").symlink_to(target)
            root.write_text("## Task index\n\nTask 1 — T — f — full — "
                            "[task-1.md](plan.tasks/task-1.md)\n", encoding="utf-8")
            result = self.run_check("implementation-plan", root)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            members = directory / "plan.tasks"
            members.mkdir()
            first = members / "task-1.md"
            first.write_text("# Task 1\n", encoding="utf-8")
            os_link = members / "task-2.md"
            os_link.hardlink_to(first)
            root.write_text("## Task index\n\nTask 1 — T — f — full — "
                            "[task-1.md](plan.tasks/task-1.md)\n\nTask 2 — T — f — full — "
                            "[task-2.md](plan.tasks/task-2.md)\n", encoding="utf-8")
            result = self.run_check("implementation-plan", root)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            members = directory / "plan.tasks"
            members.mkdir()
            member = members / "task-1.md"
            member.write_text("# Task 1\n", encoding="utf-8")
            root.write_text("## Task index\n\nTask 1 — T — f — full — "
                            "[task-1.md](plan.tasks/task-1.md)\n", encoding="utf-8")
            original = artifact_budget._read_regular
            def refuse(path, *, limit=None):
                if Path(path) == member:
                    raise artifact_budget.InputReadError("denied")
                return original(path, limit=limit)
            with mock.patch.object(artifact_budget, "_read_regular", side_effect=refuse):
                with self.assertRaises(artifact_budget.ArtifactBudgetError):
                    artifact_budget.check_artifact("implementation-plan", root, POLICY)

    def test_duplicate_unknown_and_scalar_policy_errors_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "handoff.md"
            root.write_text("small", encoding="utf-8")
            duplicate = directory / "duplicate.json"
            duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            self.assertEqual(self.run_check("handoff", root, duplicate).returncode, 2)
            base = json.loads(POLICY.read_text(encoding="utf-8"))
            mutations = [
                lambda p: p.__setitem__("unexpected", 1),
                lambda p: p.__setitem__("schema_version", True),
                lambda p: p["phase_reports"].__setitem__("notes_max_characters", 0),
                lambda p: p["phase_reports"].__setitem__("wire_max_bytes", 1.5),
                lambda p: p["artifacts"]["handoff"].__setitem__("root_max_bytes", 0),
                lambda p: p["artifacts"]["handoff"].__setitem__("aggregate_max_bytes", 0),
                lambda p: p["artifacts"]["handoff"].__setitem__("member_max_bytes", 1),
                lambda p: p["artifacts"]["handoff"].__setitem__("aggregate_max_bytes", 8193),
                lambda p: p["artifacts"]["implementation-plan"].__setitem__("max_members", True),
                lambda p: p["artifacts"]["implementation-plan"].__setitem__("member_max_bytes", -1),
                lambda p: p["artifacts"]["implementation-plan"].__setitem__("aggregate_max_bytes", 1),
            ]
            for number, mutate in enumerate(mutations):
                policy = deepcopy(base)
                mutate(policy)
                path = directory / f"bad-{number}.json"
                path.write_text(json.dumps(policy), encoding="utf-8")
                result = self.run_check("handoff", root, path)
                self.assertEqual((result.returncode, result.stdout), (2, ""))


if __name__ == "__main__":
    unittest.main()
