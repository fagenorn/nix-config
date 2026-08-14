from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "agent-evidence.py"
FIXTURES = Path(__file__).parent / "fixtures" / "evidence"


def run_validator(kind: str, fixture: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), kind, str(FIXTURES / fixture)],
        text=True,
        capture_output=True,
        check=False,
    )


class AgentEvidenceTest(unittest.TestCase):
    def fixture(self, name: str) -> object:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def run_document(
        self, kind: str, document: object
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json"
        ) as artifact:
            json.dump(document, artifact)
            artifact.flush()
            return subprocess.run(
                [sys.executable, str(SCRIPT), kind, artifact.name],
                text=True,
                capture_output=True,
                check=False,
            )

    def assert_diagnostic(
        self, completed: subprocess.CompletedProcess[str], code: str
    ) -> None:
        self.assertEqual(completed.returncode, 2, completed)
        self.assertEqual(completed.stdout, "")
        self.assertIn(f"{code} ", completed.stderr)

    def test_fresh_bridge_passes(self):
        completed = run_validator("bridge", "bridge-fresh-end-to-end.json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "VALID bridge bridge-fresh-e2e\n")
        self.assertEqual(completed.stderr, "")

    def test_stale_bridge_session_rejects(self):
        completed = run_validator("bridge", "bridge-stale-session.json")

        self.assert_diagnostic(completed, "BRIDGE_SESSION_STALE")

    def test_direct_success_does_not_replace_agent_mediated_result(self):
        completed = run_validator("bridge", "bridge-direct-only.json")

        self.assert_diagnostic(completed, "BRIDGE_MEDIATED_REQUIRED")
        fixture_text = (FIXTURES / "bridge-direct-only.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("did not return a Codex terminal result", fixture_text)

    def test_missing_and_duplicate_required_bridge_operations_reject(self):
        original = self.fixture("bridge-fresh-end-to-end.json")

        missing = deepcopy(original)
        missing["operations"].pop()
        self.assert_diagnostic(
            self.run_document("bridge", missing), "BRIDGE_OPERATION_REQUIRED"
        )

        duplicate = deepcopy(original)
        duplicate["operations"].append(deepcopy(duplicate["operations"][0]))
        self.assert_diagnostic(
            self.run_document("bridge", duplicate), "BRIDGE_OPERATION_DUPLICATE"
        )

        unknown = deepcopy(original)
        unknown["operations"][0]["name"] = "ad-hoc-review"
        self.assert_diagnostic(
            self.run_document("bridge", unknown), "BRIDGE_OPERATION_UNKNOWN"
        )

    def test_each_bridge_operation_requires_both_layers(self):
        original = self.fixture("bridge-fresh-end-to-end.json")

        for layer in ("direct", "agent_mediated"):
            with self.subTest(layer=layer):
                document = deepcopy(original)
                del document["operations"][0][layer]
                self.assert_diagnostic(
                    self.run_document("bridge", document), "BRIDGE_LAYER_REQUIRED"
                )

    def test_bridge_records_must_be_terminal_with_matching_payload(self):
        original = self.fixture("bridge-fresh-end-to-end.json")

        nonterminal = deepcopy(original)
        nonterminal["operations"][0]["direct"]["status"] = "running"
        self.assert_diagnostic(
            self.run_document("bridge", nonterminal),
            "BRIDGE_RECORD_NONTERMINAL",
        )

        completed_without_result = deepcopy(original)
        del completed_without_result["operations"][0]["direct"]["result"]
        self.assert_diagnostic(
            self.run_document("bridge", completed_without_result),
            "BRIDGE_RECORD_PAYLOAD_REQUIRED",
        )

        failed_without_failure = deepcopy(original)
        mediated = failed_without_failure["operations"][0]["agent_mediated"]
        mediated["status"] = "failed"
        del mediated["result"]
        self.assert_diagnostic(
            self.run_document("bridge", failed_without_failure),
            "BRIDGE_RECORD_PAYLOAD_REQUIRED",
        )

    def test_bridge_claim_must_match_combined_mediated_outcomes(self):
        original = self.fixture("bridge-fresh-end-to-end.json")

        certified_failure = deepcopy(original)
        mediated = certified_failure["operations"][0]["agent_mediated"]
        mediated["status"] = "failed"
        mediated["failure"] = "The mediated execution failed."
        del mediated["result"]
        self.assert_diagnostic(
            self.run_document("bridge", certified_failure),
            "BRIDGE_CLAIM_MISMATCH",
        )

        rejected_success = deepcopy(original)
        rejected_success["claim"]["status"] = "rejected"
        self.assert_diagnostic(
            self.run_document("bridge", rejected_success),
            "BRIDGE_CLAIM_MISMATCH",
        )

    def test_single_research_failure_passes_as_transient(self):
        completed = run_validator("research", "research-single-failure.json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout, "VALID research service-single-failure\n"
        )
        self.assertEqual(completed.stderr, "")

    def test_single_research_failure_cannot_be_promoted_to_standing(self):
        document = self.fixture("research-single-failure.json")
        document["claim"]["classification"] = "standing"

        self.assert_diagnostic(
            self.run_document("research", document),
            "RESEARCH_CORROBORATION_REQUIRED",
        )

    def test_corroborated_research_passes(self):
        completed = run_validator("research", "research-corroborated.json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "VALID research service-corroborated\n")
        self.assertEqual(completed.stderr, "")

    def test_research_observation_identity_is_unique_across_all_observations(self):
        original = self.fixture("research-corroborated.json")
        variants = (
            (
                "RESEARCH_OBSERVATION_ID_DUPLICATE",
                {
                    "id": "obs-1",
                    "execution_id": "exec-unreferenced",
                    "observed_at": "2026-08-14T13:02:00Z",
                    "source": "unreferenced source",
                    "outcome": "available",
                },
            ),
            (
                "RESEARCH_EXECUTION_ID_DUPLICATE",
                {
                    "id": "obs-unreferenced",
                    "execution_id": "exec-1",
                    "observed_at": "2026-08-14T13:02:00Z",
                    "source": "unreferenced source",
                    "outcome": "available",
                },
            ),
            (
                "RESEARCH_TIMESTAMP_DUPLICATE",
                {
                    "id": "obs-unreferenced",
                    "execution_id": "exec-unreferenced",
                    "observed_at": "2026-08-14T13:59:00+01:00",
                    "source": "unreferenced source",
                    "outcome": "available",
                },
            ),
        )

        for code, observation in variants:
            with self.subTest(code=code):
                document = deepcopy(original)
                document["observations"].append(observation)
                self.assert_diagnostic(self.run_document("research", document), code)

    def test_naive_timestamps_reject(self):
        bridge = self.fixture("bridge-fresh-end-to-end.json")
        bridge["captured_at"] = "2026-08-14T12:10:00"
        self.assert_diagnostic(
            self.run_document("bridge", bridge), "TIMESTAMP_TIMEZONE_REQUIRED"
        )

        research = self.fixture("research-single-failure.json")
        research["observations"][0]["observed_at"] = "2026-08-14T12:59:00"
        self.assert_diagnostic(
            self.run_document("research", research), "TIMESTAMP_TIMEZONE_REQUIRED"
        )

    def test_timestamp_normalization_overflow_reports_invalid_timestamp(self):
        document = self.fixture("research-single-failure.json")
        document["observations"][0]["observed_at"] = (
            "0001-01-01T00:00:00+23:59"
        )

        completed = self.run_document("research", document)

        self.assert_diagnostic(completed, "TIMESTAMP_INVALID")
        self.assertNotIn("Traceback", completed.stderr)

    def test_unsupported_schema_and_wrong_kind_reject(self):
        fixture_names = {
            "bridge": "bridge-fresh-end-to-end.json",
            "research": "research-corroborated.json",
        }
        expected_kinds = {
            "bridge": "research-observations",
            "research": "bridge-smoke",
        }

        for command, fixture_name in fixture_names.items():
            with self.subTest(command=command, problem="schema"):
                document = self.fixture(fixture_name)
                document["schema_version"] = 2
                self.assert_diagnostic(
                    self.run_document(command, document),
                    "SCHEMA_VERSION_UNSUPPORTED",
                )
            with self.subTest(command=command, problem="kind"):
                document = self.fixture(fixture_name)
                document["kind"] = expected_kinds[command]
                self.assert_diagnostic(
                    self.run_document(command, document), "KIND_MISMATCH"
                )

    def test_malformed_document_reports_sorted_diagnostics_without_traceback(self):
        document = {
            "schema_version": 1,
            "kind": "research-observations",
            "evidence_id": 42,
            "captured_at": None,
            "question": [],
            "claim": None,
            "observations": [None],
        }

        completed = self.run_document("research", document)

        self.assertEqual(completed.returncode, 2)
        self.assertNotIn("Traceback", completed.stderr)
        lines = completed.stderr.splitlines()
        self.assertEqual(lines, sorted(lines))


if __name__ == "__main__":
    unittest.main()
