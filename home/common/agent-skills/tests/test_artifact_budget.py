from __future__ import annotations

import errno
import json
import hashlib
import io
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent_tools.delivery import artifact_budget


ROOT = Path(__file__).parents[4]
COMMAND = (sys.executable, "-m", "agent_tools.delivery.artifact_budget")
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
FIXTURES = Path(__file__).parent / "fixtures/artifact-budgets"


class ArtifactBudgetCliTest(unittest.TestCase):
    def run_check(self, kind: str, root: Path, policy: Path = POLICY):
        return subprocess.run(
            [*COMMAND, "check", "--kind", kind,
             "--root", str(root), "--policy", str(policy), "--format", "json"],
            text=True, capture_output=True, check=False,
        )

    def run_validate(self, boundary: str, payload: object, use_stdin: bool):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if use_stdin:
            return subprocess.run(
                [*COMMAND, "validate-report", "--boundary", boundary,
                 "--input", "-", "--policy", str(POLICY)],
                input=encoded, capture_output=True, check=False,
            )
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate.json"
            candidate.write_bytes(encoded)
            return subprocess.run(
                [*COMMAND, "validate-report", "--boundary", boundary,
                 "--input", str(candidate), "--policy", str(POLICY)],
                capture_output=True, check=False,
            )

    def assert_refusal(self, result, label: str) -> str:
        """Exit 2, empty stdout, one stderr line `artifact-budget: <label>: <reason>` (issue 472 D1, D10)."""
        stdout, stderr = result.stdout, result.stderr
        if isinstance(stderr, str):
            stdout, stderr = stdout.encode("utf-8"), stderr.encode("utf-8")
        self.assertEqual((result.returncode, stdout), (2, b""), stderr)
        prefix = f"artifact-budget: {label}: ".encode("utf-8")
        self.assertTrue(stderr.startswith(prefix), stderr)
        self.assertTrue(stderr.endswith(b"\n"), stderr)
        self.assertEqual(stderr.count(b"\n"), 1, stderr)
        reason = stderr[len(prefix):-1].decode("utf-8")
        self.assertTrue(reason, stderr)
        self.assertEqual(reason, reason.strip(), stderr)
        return reason

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

    def test_plan_requires_one_nonempty_task_index_and_contiguous_reference_set(self):
        cases = {
            "missing": ("# Plan\n", {}),
            "empty": ("## Task index\n", {}),
            "missing_with_member": (
                "Task 1 — T — f — full — [task-1.md](plan.tasks/task-1.md)\n",
                {1: "# Task 1\n"},
            ),
            "duplicate": (
                "## Task index\n\nTask 1 — T — f — full — "
                "[task-1.md](plan.tasks/task-1.md)\n\n## Task index\n",
                {1: "# Task 1\n"},
            ),
        }
        for name, (root_text, task_texts) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                root = directory / "plan.md"
                members = directory / "plan.tasks"
                members.mkdir()
                root.write_text(root_text, encoding="utf-8")
                for number, task_text in task_texts.items():
                    (members / f"task-{number}.md").write_text(task_text, encoding="utf-8")
                result = self.run_check("implementation-plan", root)
                self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_valid_measurement_is_deterministic_and_violations_are_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "handoff.md"
            path.write_bytes(b"h" * 8_193)
            first = self.run_check("handoff", path)
            second = self.run_check("handoff", path)
            self.assertEqual(first.returncode, 3)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(set(json.loads(first.stdout)),
                             {"interface_version", "kind", "status", "metrics", "violations",
                              "overages"})

    def test_an_over_budget_check_reports_limit_and_overage(self):
        """Issue 472 AC3, D6, D7: overages carry each violated code's limit and how far over it is."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "handoff.md"
            path.write_bytes(b"h" * 8_193)
            over = self.run_check("handoff", path)
            self.assertEqual(over.returncode, 3, over.stderr)
            self.assertEqual(over.stdout, (
                '{"interface_version":1,"kind":"handoff","metrics":{"file_count":1,'
                '"largest_member_bytes":0,"root_bytes":8193,"total_bytes":8193},'
                '"overages":{"aggregate_bytes":{"limit":8192,"over_by":1},'
                '"root_bytes":{"limit":8192,"over_by":1}},"status":"over_budget",'
                '"violations":["root_bytes","aggregate_bytes"]}\n'))
            path.write_bytes(b"h" * 8_192)
            within = self.run_check("handoff", path)
            self.assertEqual(within.returncode, 0, within.stderr)
            self.assertEqual(json.loads(within.stdout)["overages"], {})

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
                [*COMMAND, "check", "--kind", "handoff",
                 "--root", str(root), "--format", "json"],
                text=True, capture_output=True, check=False,
                env={**os.environ, "HOME": str(directory)},
            )
            self.assertEqual(default.returncode, 0, default.stderr)
            report = subprocess.run(
                [*COMMAND, "validate-report", "--boundary", "producer",
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
                            "handoff": "handoff.md"}[kind]
        target = item["root_bytes"]
        member_sizes = item["member_bytes"]
        if kind in {"design-spec", "handoff"}:
            root.write_bytes(b"x" * target)
            return root
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

    def test_repository_descriptors_drive_cli_results(self):
        for fixture_name in ("small-issue.json", "oversized-issue.json"):
            fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
            self.assertEqual(set(fixture), {"schema_version", "case", "artifacts"})
            for item in fixture["artifacts"]:
                self.assertEqual(set(item), {"kind", "case", "shape", "root_bytes",
                                             "member_bytes", "expected"})
                self.assertEqual(set(item["expected"]), {"exit_code", "status", "metrics",
                                                         "violations", "overages",
                                                         "producer_state"})
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
                    self.assertEqual(measured["overages"], expected["overages"])
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
                self.assert_refusal(result, "invalid report")

    def test_a_producer_refusal_names_its_member_or_bound(self):
        """Issue 472 AC1, D2, D3: the notes bound and the key set are named; the notes text never is."""
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["notes_max_characters"]
        marker = "secret-notes-text"
        notes = marker + "n" * (bound + 1 - len(marker))
        for use_stdin in (True, False):
            with self.subTest(use_stdin=use_stdin):
                result = self.run_validate(
                    "producer", {"state": "failed", "artifact": None, "notes": notes}, use_stdin)
                reason = self.assert_refusal(result, "invalid report")
                self.assertIn("notes", reason)
                self.assertIn(str(bound), reason)
                self.assertIn(str(bound + 1), reason)
                self.assertNotIn(marker, reason)
        keys = {"state": "failed", "artifact": None, "decisions": []}
        reason = self.assert_refusal(self.run_validate("producer", keys, True), "invalid report")
        self.assertIn('"decisions"', reason)
        self.assertIn('"notes"', reason)

    def test_a_producer_refusal_names_the_failing_artifact_member(self):
        """Issue 472 D3: the producer boundary names state, or the artifact member its state breaks."""
        over = self.full("design-spec", True)
        rows = (
            ({"state": "done", "artifact": None}, ("state", "decompose_required")),
            ({"state": [], "artifact": None}, ("state", "decompose_required")),
            ({"state": "stopped", "artifact": over}, ("artifact.kind", "handoff")),
            ({"state": "decompose_required", "artifact": self.full("handoff", True)},
             ("artifact.kind",)),
            ({"state": "complete", "artifact": self.full("handoff", True)},
             ("artifact", '"violations"')),
            ({"state": "complete", "artifact": {**self.full("handoff"), "path": ""}},
             ("artifact.path",)),
            ({"state": "complete", "artifact": {**self.full("handoff"),
                                                "metrics": {**self.metrics(), "file_count": 0}}},
             ("artifact.metrics",)),
            ({"state": "decompose_required", "artifact": {**over, "budget_status": "within_budget"}},
             ("artifact.budget_status",)),
            ({"state": "decompose_required",
              "artifact": {**over, "violations": ["aggregate_bytes", "root_bytes"]}},
             ("artifact.violations",)),
            ({"state": "failed", "artifact": {"kind": "handoff", "path": "h.md",
                                              "metrics": self.metrics()}},
             ("artifact", '"metrics"')),
            ({"state": "failed", "artifact": "h.md"}, ("artifact",)),
        )
        for number, (fields, tokens) in enumerate(rows):
            with self.subTest(row=number):
                result = self.run_validate("producer", {**fields, "notes": "ok"}, number % 2 == 0)
                reason = self.assert_refusal(result, "invalid report")
                for token in tokens:
                    self.assertIn(token, reason)

    def test_validate_report_rejects_wire_parse_and_io_failures(self):
        malformed = (b'{"state":"failed","state":"failed","artifact":null,"notes":"x"}',
                     b"\xff", b"[]", b"{}{}", b'{"value":NaN}')
        for raw in malformed:
            result = subprocess.run(
                [*COMMAND, "validate-report", "--boundary", "producer",
                 "--input", "-", "--policy", str(POLICY)], input=raw,
                capture_output=True, check=False)
            self.assert_refusal(result, "invalid report")
        missing = subprocess.run(
            [*COMMAND, "validate-report", "--boundary", "producer",
             "--input", "/definitely/missing/report.json", "--policy", str(POLICY)],
            capture_output=True, check=False)
        self.assert_refusal(missing, "cannot read report")
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "target.json"
            target.write_text('{"state":"failed","artifact":null,"notes":"x"}', encoding="utf-8")
            link = Path(raw) / "link.json"
            link.symlink_to(target)
            symlinked = subprocess.run(
                [*COMMAND, "validate-report", "--boundary", "producer",
                 "--input", str(link), "--policy", str(POLICY)], capture_output=True, check=False)
            self.assert_refusal(symlinked, "cannot read report")
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        oversized = {"state": "failed", "notes": "wire bound",
                     "artifact": {"kind": "handoff",
                                  "path": "x" * policy["phase_reports"]["wire_max_bytes"]}}
        over = self.run_validate("producer", oversized, use_stdin=True)
        self.assert_refusal(over, "invalid report")

    def test_validate_report_rejects_escaped_lone_surrogate_without_traceback(self):
        result = subprocess.run(
            [*COMMAND, "validate-report", "--boundary", "producer",
             "--input", "-", "--policy", str(POLICY)],
            input=b'{"state":"failed","artifact":null,"notes":"\\ud800"}',
            capture_output=True, check=False,
        )
        self.assert_refusal(result, "invalid report")

    def test_refusal_reasons_name_the_wire_parse_read_and_policy_failure(self):
        """Issue 472 D1-D3, D13: a refusal names its failure, never a path or an input value."""
        report = [*COMMAND, "validate-report", "--boundary", "producer"]
        good = b'{"state":"failed","artifact":null,"notes":"x"}'
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["wire_max_bytes"]
        stdin_cases = (
            (b'{"state":"failed","state":"failed","artifact":null,"notes":"x"}',
             ("duplicate JSON key 'state'",)),
            (b'{"st\\nate":1,"st\\nate":2}', ("duplicate JSON key 'st\\nate'",)),
            (b"\xff", ("invalid JSON", "UTF-8")),
            (b"{}{}", ("invalid JSON", "column")),
            (b'{"value":NaN}', ("invalid JSON", "constant")),
            (b"[]", ("object",)),
            (b" " * (bound + 1), (str(bound),)),
        )
        for payload, tokens in stdin_cases:
            with self.subTest(payload=payload[:48]):
                result = subprocess.run(report + ["--input", "-", "--policy", str(POLICY)],
                                        input=payload, capture_output=True, check=False)
                reason = self.assert_refusal(result, "invalid report")
                for token in tokens:
                    self.assertIn(token, reason)
        # Exactly the wire bound in, one byte over it once canonical output adds its newline.
        padded = {"state": "failed", "notes": "canonical bound",
                  "artifact": {"kind": "handoff", "path": ""}}

        def compact(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")

        padded["artifact"]["path"] = "x" * (bound - len(compact(padded)))
        self.assertEqual(len(compact(padded)), bound)
        canonical = subprocess.run(
            [*COMMAND, "validate-report", "--boundary", "producer",
             "--input", "-", "--policy", str(POLICY)],
            input=compact(padded), capture_output=True, check=False)
        self.assertIn(str(bound), self.assert_refusal(canonical, "invalid report"))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            missing = directory / "missing-report.json"
            result = subprocess.run(report + ["--input", str(missing), "--policy", str(POLICY)],
                                    capture_output=True, check=False)
            self.assertEqual(self.assert_refusal(result, "cannot read report"),
                             os.strerror(errno.ENOENT))
            target = directory / "target.json"
            target.write_bytes(good)
            link = directory / "link.json"
            link.symlink_to(target)
            result = subprocess.run(report + ["--input", str(link), "--policy", str(POLICY)],
                                    capture_output=True, check=False)
            self.assertEqual(self.assert_refusal(result, "cannot read report"),
                             os.strerror(errno.ELOOP))
            broken = directory / "broken-policy.json"
            broken.write_bytes(b"{")
            schema = directory / "schema-policy.json"
            policy_value = json.loads(POLICY.read_text(encoding="utf-8"))
            policy_value["artifacts"]["handoff"]["root_max_bytes"] = 0
            schema.write_text(json.dumps(policy_value), encoding="utf-8")
            for policy in (broken, schema, directory / "absent-policy.json"):
                with self.subTest(policy=policy.name):
                    result = subprocess.run(report + ["--input", "-", "--policy", str(policy)],
                                            input=good, capture_output=True, check=False)
                    reason = self.assert_refusal(result, "invalid report")
                    self.assertIn("policy", reason)
                    self.assertNotIn(raw, reason)

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
            original = artifact_budget.os.access

            def refuse(path, mode, **kwargs):
                if Path(path) == member:
                    return False
                return original(path, mode, **kwargs)

            with mock.patch.object(artifact_budget.os, "access", side_effect=refuse):
                with self.assertRaises(artifact_budget.ArtifactBudgetError):
                    artifact_budget.check_artifact("implementation-plan", root, POLICY)

    def test_checker_rejects_path_replacement_during_single_descriptor_capture(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "handoff.md"
            replacement = directory / "replacement.md"
            root.write_text("original", encoding="utf-8")
            replacement.write_text("replacement", encoding="utf-8")
            original_fstat = os.fstat
            calls = 0

            def replace_before_stability_check(descriptor):
                nonlocal calls
                calls += 1
                if calls == 3:
                    os.replace(replacement, root)
                return original_fstat(descriptor)

            with mock.patch.object(artifact_budget.os, "fstat",
                                   side_effect=replace_before_stability_check):
                with self.assertRaisesRegex(artifact_budget.ArtifactBudgetError,
                                           "artifact changed during read"):
                    artifact_budget.check_artifact("handoff", root, POLICY)

    def test_checker_rejects_member_in_place_mutation_during_capture(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "plan.md"
            members = directory / "plan.tasks"
            members.mkdir()
            member = members / "task-1.md"
            member.write_text("# Task 1\n", encoding="utf-8")
            root.write_text("## Task index\n\nTask 1 — T — f — full — "
                            "[task-1.md](plan.tasks/task-1.md)\n", encoding="utf-8")
            original_fstat = os.fstat
            calls = 0

            def mutate_before_stability_check(descriptor):
                nonlocal calls
                calls += 1
                if calls == 5:
                    member.write_bytes(b"changed in place")
                return original_fstat(descriptor)

            with mock.patch.object(artifact_budget.os, "fstat",
                                   side_effect=mutate_before_stability_check):
                with self.assertRaisesRegex(artifact_budget.ArtifactBudgetError,
                                           "artifact changed during read"):
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


class InvokeParityTest(unittest.TestCase):
    """Issue 498 D3, D5: `invoke` returns exactly what one CLI run of the source
    script produces, and touches no process stream."""

    PRODUCER = ("validate-report", "--boundary", "producer", "--input", "-")

    def rows(self, directory: Path):
        """(name, argv without `--policy`, stdin, exit code, refusal label or None):
        one row per exit code and refusal label `invoke` can return."""
        wire = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["wire_max_bytes"]
        within, over = directory / "within.md", directory / "over.md"
        within.write_bytes(b"h" * 8_192)
        over.write_bytes(b"h" * 8_193)
        return (
            ("accepted producer report", self.PRODUCER,
             b'{"state":"failed","artifact":null,"notes":"x"}', 0, None),
            ("schema-refused report", self.PRODUCER,
             b'{"state":"failed","artifact":null,"decisions":[]}', 2, "invalid report"),
            ("report over the wire bound", self.PRODUCER, b" " * (wire + 1), 2,
             "invalid report"),
            ("argparse refusal",
             ("validate-report", "--boundary", "no-such-boundary", "--input", "-"), b"", 2,
             "invalid input"),
            ("check within budget",
             ("check", "--kind", "handoff", "--root", str(within), "--format", "json"), b"", 0,
             None),
            ("check over budget",
             ("check", "--kind", "handoff", "--root", str(over), "--format", "json"), b"", 3,
             None),
        )

    def test_invoke_returns_exactly_what_the_cli_process_produces(self):
        with tempfile.TemporaryDirectory() as raw:
            for name, argv, stdin, code, label in self.rows(Path(raw)):
                with self.subTest(name):
                    argv = [*argv, "--policy", str(POLICY)]
                    outcome = artifact_budget.invoke(argv, io.BytesIO(stdin).read)
                    process = subprocess.run([*COMMAND, *argv], input=stdin,
                                             capture_output=True, check=False)
                    self.assertEqual(
                        (outcome.exit_code, outcome.stdout, outcome.stderr),
                        (process.returncode, process.stdout, process.stderr.decode("utf-8")))
                    self.assertEqual(outcome.exit_code, code, outcome.stderr)
                    if label is None:
                        self.assertEqual(outcome.stderr, "")
                        self.assertTrue(outcome.stdout.endswith(b"\n"), outcome.stdout)
                    else:
                        self.assertEqual(outcome.stdout, b"")
                        self.assertTrue(outcome.stderr.startswith(f"artifact-budget: {label}: "),
                                        outcome.stderr)

    def test_invoke_touches_no_process_stream(self):
        """A caller prints its own reply after a validation, so `invoke` writes to
        neither process stream and reads stdin only through its reader, which a
        command without `--input -` never calls."""
        def no_stdin(size):
            raise AssertionError(f"stdin read ({size} bytes) by a command without --input -")

        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(sys, "stdin", None), \
                mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            rows = self.rows(Path(raw))
            codes = [artifact_budget.invoke(
                         [*argv, "--policy", str(POLICY)],
                         io.BytesIO(stdin).read if "-" in argv else no_stdin).exit_code
                     for _, argv, stdin, _, _ in rows]
        self.assertEqual(codes, [code for *_, code, _ in rows])
        for stream in (stdout, stderr):
            stream.flush()
            self.assertEqual(stream.buffer.getvalue(), b"")


class SkillSurfaceTest(unittest.TestCase):
    """Issue 689 D3: only the surface design, grill-with-docs, writing-plans and handoff call."""

    def run_cli(self, *argv, stdin="{}"):
        return subprocess.run([*COMMAND, *argv], input=stdin,
                              capture_output=True, text=True, timeout=60)

    def assert_parser_refusal(self, done, token):
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertTrue(done.stderr.startswith("artifact-budget: invalid input: "), done.stderr)
        self.assertIn(token, done.stderr)

    def test_the_committed_policy_holds_exactly_the_skill_kinds(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(sorted(policy), ["artifacts", "phase_reports", "schema_version", "unit"])
        self.assertEqual(sorted(policy["artifacts"]), ["design-spec", "handoff", "implementation-plan"])

    # Formerly valid payloads: every argv below, with its stdin, exited 0 before the trim.
    FAILED_SDD = {"state": "failed", "review_state": "unknown", "conformance_verdict": "not_run",
                  "correctness_verdict": "not_run", "verification_state": "not_run",
                  "base_sha": None, "head_sha": None, "acceptance_state": "not_applicable",
                  "detail_state": "none", "report_path": None, "notes": ""}
    FAILED_HANDOFF = {"state": "failed", "ledger_repo_root": None, "run_id": None, "attempt": None,
                      "owner": None, "owner_worktree": None, "action_id": None, "issue_number": 14,
                      "branch": "issue-14", "worktree_path": "/tmp/w", "spec_artifact": None,
                      "plan_artifact": None, "head_sha": None, "review_state": "unknown",
                      "acceptance_state": "not_applicable", "auto": False, "report_path": None,
                      "notes": ""}
    CHECKPOINT = {"interface_version": 2, "issue": 151,
                  "custody": {"action_id": "151:1:1", "attempt": 1, "kind": "implementation", "launch": 1},
                  "contract_digest": "sha256:7d4be1f805893d0ae096126ebf440dd8a196d2fe06e8cb48553b9c45c025cad4",
                  "delivery_observations": [], "authority_observations": [], "reevaluation_evidence": [],
                  "requested_scope": None, "detail_state": "none", "report_path": None, "notes": ""}
    MERGED_SUMMARY = {"issue": 14, "state": "merged",
                      "pr_url": "https://github.com/fagenorn/nix-config/pull/15",
                      "merge_sha": "abc123abc123abc123abc123abc123abc123abcd", "issue_closed": True,
                      "discussion_items": [], "detail_state": "none", "report_path": None, "notes": ""}
    BOOTSTRAP = {"interface_version": 3, "kind": "workflow_bootstrap", "run_id": "task-151-synthetic",
                 "requirements": [], "verification": []}
    DETAIL = {"interface_version": 1, "findings": [{"axis": "conformance", "severity": "Minor",
                                                     "status": "parked", "text": "f", "ruling": "r"}]}

    def test_retired_commands_kinds_and_boundaries_are_parser_refusals(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "review.shards").mkdir()
            (directory / "review.shards/shard-001.diff").write_bytes(b"dddd")
            manifest = directory / "review.json"
            manifest.write_text(json.dumps({
                "interface_version": 1, "kind": "review-" "package", "purpose": "diff-review",
                "range": {"base": "a" * 40, "head": "b" * 40}, "commits": [],
                "stat": {"files_changed": 1, "insertions": 1, "deletions": 0},
                "shards": [{"path": "review.shards/shard-001.diff", "bytes": 4}],
                "total_diff_bytes": 4, "coverage": {"complete": True, "file_diff_count": 1}}),
                encoding="utf-8")
            cases = [(("describe", "--kind", "handoff", "--format", "json"), None),
                     (("validate-detail-input", "--input", "-"), self.DETAIL),
                     (("check", "--kind", "review-" "package", "--root", str(manifest), "--format", "json"), None)]
            cases += [(("validate-report", "--boundary", boundary, "--input", "-"), payload)
                      for boundary, payload in (("sdd", self.FAILED_SDD), ("ship-handoff", self.FAILED_HANDOFF),
                                                ("ship-checkpoint", self.CHECKPOINT),
                                                ("ship-summary", self.MERGED_SUMMARY),
                                                ("workflow-response", self.BOOTSTRAP))]
            for argv, payload in cases:
                with self.subTest(argv=argv[:3]):
                    done = self.run_cli(*argv, "--policy", str(POLICY),
                                        stdin="{}" if payload is None else json.dumps(payload))
                    self.assert_parser_refusal(done, "invalid choice")

    def test_the_policy_pin_is_a_parser_refusal(self):
        # Both pinned calls, with this identity, exited 0 before the trim.
        identity = "sha256:" + hashlib.sha256(POLICY.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "handoff.md"
            root.write_text("# Handoff\n", encoding="utf-8")
            calls = [(("check", "--kind", "handoff", "--root", str(root), "--format", "json"), "{}"),
                     (("validate-report", "--boundary", "producer", "--input", "-"),
                      '{"state": "failed", "artifact": null, "notes": ""}')]
            for argv, stdin in calls:
                with self.subTest(command=argv[0]):
                    done = self.run_cli(*argv, "--policy", str(POLICY),
                                        "--expected-policy-sha256", identity, stdin=stdin)
                    self.assert_parser_refusal(done, "unrecognized arguments: --expected-policy-sha256")

    def test_a_projection_member_is_refused(self):
        # This report, with the committed policy's identity, was valid before the trim.
        identity = "sha256:" + hashlib.sha256(POLICY.read_bytes()).hexdigest()
        report = {"state": "complete", "notes": "n",
                  "artifact": {"kind": "implementation-plan", "path": "artifacts/implementation-plan.json",
                               "metrics": {"root_bytes": 1, "total_bytes": 1, "file_count": 1,
                                           "largest_member_bytes": 0},
                               "budget_status": "within_budget"},
                  "projection": {"schema_version": 1, "kind": "review-feasibility-summary",
                                 "state": "complete", "plan": "artifacts/implementation-plan.json",
                                 "base": "a" * 40, "head": "b" * 40, "completed_through": 0,
                                 "plan_package_sha256": "sha256:" + "1" * 64,
                                 "forecast_sha256": "sha256:" + "2" * 64,
                                 "packing_policy_sha256": "sha256:" + "3" * 64,
                                 "artifact_policy_sha256": identity,
                                 "metrics": {"root_bytes": 1000, "total_bytes": 3000, "file_count": 2,
                                             "largest_member_bytes": 2000},
                                 "violations": [], "recommended_boundary": None}}
        done = self.run_cli("validate-report", "--boundary", "producer", "--input", "-",
                            "--policy", str(POLICY), stdin=json.dumps(report))
        self.assertEqual(
            (done.returncode, done.stdout, done.stderr),
            (2, "", 'artifact-budget: invalid report: producer report members: unexpected "projection"\n'))

    def test_a_failed_producer_report_still_validates(self):
        done = self.run_cli("validate-report", "--boundary", "producer", "--input", "-",
                            "--policy", str(POLICY),
                            stdin='{"state": "failed", "artifact": null, "notes": ""}')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"state": "failed", "artifact": None, "notes": ""})


if __name__ == "__main__":
    unittest.main()
