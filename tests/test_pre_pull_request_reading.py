"""The verify check that a delivery started after a merge lists a local result of a command.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import pre_pull_request_reading as reading
from agent_tools.system.forge_api import ForgeError
from tests.test_verify_checks import committed_mode, run_from_root

TIER = "fast"
WRAPPER = "home/common/verify-pending/checks/pre-pull-request-conformance"
MERGE = "a" * 40
BOUNDARY = "2026-11-27T10:00:00Z"
AFTER = "2026-11-27T12:00:00Z"
LATER = "2026-11-28T09:00:00Z"
BEFORE = "2026-11-26T15:00:00Z"
RAN = ("## Why\nx\n## Evidence\nVerification before the pull request: lint passed (agnostic-lint, "
       "skill-lint); test-touched passed (30 suite members passed); conformance passed (every ci rule).\n"
       "## Merge danger\nnone\n")
NOT_RAN = RAN.replace("; conformance passed (every ci rule)", "")
ARGV = ["--repo", "o/r", "--merge", MERGE, "--command", "conformance"]


def pull(number, created, body, status="ahead"):
    return {"number": number, "created_at": created, "body": body, "_status": status}


def start_of(number):
    return f"{number:040d}"


def pulls_path(page):
    return f"repos/o/r/pulls?state=all&sort=created&direction=desc&per_page=100&page={page}"


class Forge:
    """A stand-in forge serving exact paths; any other path is an AssertionError."""

    def __init__(self, pages, repeat=False):
        self.pages, self.repeat, self.paths = pages, repeat, []

    def __call__(self, path):
        self.paths.append(path)
        if path == f"repos/o/r/commits/{MERGE}":
            return {"commit": {"committer": {"date": BOUNDARY}}}
        for number in range(1, 12):
            if path == pulls_path(number):
                index = 0 if self.repeat else number - 1
                if index < len(self.pages):
                    return [{k: v for k, v in p.items() if k != "_status"} for p in self.pages[index]]
        for page in self.pages:
            for p in page:
                n = p["number"]
                if path == f"repos/o/r/pulls/{n}/commits?per_page=100":
                    return [{"sha": f"{n:040x}", "parents": [{"sha": start_of(n)}]}]
                if path == f"repos/o/r/compare/{MERGE}...{start_of(n)}":
                    return {"status": p["_status"]}
        raise AssertionError(f"unserved path {path}")

    def read_of(self, fragment):
        return [p for p in self.paths if fragment in p]


def run(forge):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = reading.main(ARGV, read=forge)
    return code, json.loads(out.getvalue())


def met(number):
    return {"status": "met", "since": BOUNDARY, "pr": number, "command": "conformance"}


NOT_YET = {"status": "not_yet", "since": BOUNDARY, "pr": None, "command": "conformance"}


class DeliveryAfterTheMergeTest(unittest.TestCase):
    def test_the_first_delivery_started_after_the_merge_that_ran_the_command_is_met(self):
        forge = Forge([[pull(1902, LATER, NOT_RAN), pull(1900, AFTER, RAN), pull(1895, BEFORE, RAN)]])
        code, document = run(forge)
        self.assertEqual(code, 0)
        self.assertEqual(document, met(1900))

    def test_a_delivery_that_started_before_the_merge_is_skipped(self):
        forge = Forge([[pull(1900, AFTER, RAN), pull(1899, "2026-11-27T11:00:00Z", RAN, "behind"),
                        pull(1898, "2026-11-27T10:30:00Z", RAN, "diverged")]])
        code, document = run(forge)
        self.assertEqual(code, 0)
        self.assertEqual(document, met(1900))
        self.assertTrue(forge.read_of(f"compare/{MERGE}...{start_of(1898)}"))
        self.assertTrue(forge.read_of(f"compare/{MERGE}...{start_of(1899)}"))

    def test_only_deliveries_started_before_the_merge_is_not_yet(self):
        code, document = run(Forge([[pull(1899, "2026-11-27T11:00:00Z", RAN, "behind")]]))
        self.assertEqual((code, document), (75, NOT_YET))

    def test_a_newer_delivery_that_ran_the_command_is_met(self):
        code, document = run(Forge([[pull(1902, LATER, RAN), pull(1900, AFTER, NOT_RAN)]]))
        self.assertEqual((code, document), (0, met(1902)))

    def test_ci_commentary_alone_is_not_yet(self):
        body = ("## Why\nruns conformance\n## Acceptance\nConformance in CI\n## Evidence\n"
                "lint pass, test-touched pass. CI ran .github/workflows/conformance.yaml and the required "
                "CI Conformance check passed.\nMerge danger: conformance passed may be slow\n")
        code, document = run(Forge([[pull(1900, AFTER, body)]]))
        self.assertEqual((code, document), (75, NOT_YET))

    def test_each_written_form_of_a_local_result_is_met(self):
        bodies = [
            RAN,
            "Evidence\n- lint: pass.\n- Conformance: pass. 41 checks.\nMerge danger\nlow\n",
            "**Evidence**\n- conformance: 41 checks ran, all passed\n",
            "## Evidence\nCONFORMANCE PASSED\n",
            "## Evidence\n- conformance (pass): 41 checks\n",
            "## Evidence\n- conformance -> pass\n",
            "## Evidence\n- conformance: pass (purpose ci, 41 checks)\n",
            "## Evidence\nCI on this pull request runs the full declared verification. conformance passed\n",
        ]
        for body in bodies:
            with self.subTest(body=body):
                code, document = run(Forge([[pull(1900, AFTER, body)]]))
                self.assertEqual((code, document), (0, met(1900)))

    def test_a_result_word_in_another_clause_does_not_count(self):
        bodies = ["## Evidence\nconformance skipped; lint passed\n",
                  "## Evidence\nconformance skipped\nlint passed\n",
                  "## Evidence\nconformance skipped. lint passed\n"]
        for body in bodies:
            with self.subTest(body=body):
                code, document = run(Forge([[pull(1900, AFTER, body)]]))
                self.assertEqual((code, document), (75, NOT_YET))

    def test_a_longer_word_is_not_the_command(self):
        bodies = ["## Evidence\nlint pass, conformance-report pass, test-touched pass\n",
                  "## Evidence\nlint pass, pre-conformance pass\n"]
        for body in bodies:
            with self.subTest(body=body):
                code, document = run(Forge([[pull(1900, AFTER, body)]]))
                self.assertEqual((code, document), (75, NOT_YET))

    def test_a_pull_with_no_evidence_heading_is_not_a_delivery(self):
        for body in ["manual change", None, "## Why\nEvidence of the bug: conformance passed\n"]:
            with self.subTest(body=body):
                forge = Forge([[pull(1901, LATER, RAN), pull(1900, AFTER, body)]])
                code, document = run(forge)
                self.assertEqual((code, document), (0, met(1901)))
                self.assertEqual(forge.read_of("pulls/1900/commits"), [])

    def test_a_tie_on_created_at_is_broken_by_number(self):
        code, document = run(Forge([[pull(1901, AFTER, RAN), pull(1900, AFTER, RAN)]]))
        self.assertEqual((code, document), (0, met(1900)))

    def test_no_pull_after_the_merge_is_not_yet(self):
        code, document = run(Forge([[pull(1895, BEFORE, RAN)]]))
        self.assertEqual((code, document), (75, NOT_YET))


class PagingTest(unittest.TestCase):
    def test_paging_stops_at_the_boundary(self):
        full = [pull(5000 - i, LATER, "manual change") for i in range(100)]
        older = [pull(1900, AFTER, RAN)] + [pull(1800 - i, BEFORE, RAN) for i in range(99)]
        forge = Forge([full, older])
        code, document = run(forge)
        self.assertEqual((code, document), (0, met(1900)))
        self.assertEqual(forge.read_of("pulls?state=all"), [pulls_path(1), pulls_path(2)])

    def test_ten_full_pages_after_the_boundary_are_unreadable(self):
        full = [pull(5000 - i, LATER, "manual change") for i in range(100)]
        forge = Forge([full], repeat=True)
        code, document = run(forge)
        self.assertEqual(code, 75)
        self.assertEqual(document["status"], "forge_unreadable")
        self.assertEqual(len(forge.read_of("pulls?state=all")), 10)
        self.assertEqual(forge.read_of("page=11"), [])

    def test_a_forge_error_is_not_yet(self):
        def failing(path):
            raise ForgeError("gh_failed", "boom")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = reading.main(ARGV, read=failing)
        self.assertEqual(code, 75)
        self.assertEqual(json.loads(out.getvalue())["status"], "forge_unreadable")


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(WRAPPER), "100755")

    def test_the_wrapper_exits_75_with_not_yet_through_a_stub_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            gh = Path(tmp) / "gh"
            gh.write_text('#!/bin/sh\ncase "$2" in\n'
                          "repos/o/r/commits/*) echo '{\"commit\": {\"committer\": "
                          "{\"date\": \"2026-11-27T10:00:00Z\"}}}' ;;\n"
                          "*) echo '[]' ;;\nesac\n")
            gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
            proc = run_from_root([WRAPPER, *ARGV], env_extra={"PATH": tmp + os.pathsep + os.environ["PATH"]})
        self.assertEqual(proc.returncode, 75, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), NOT_YET)


if __name__ == "__main__":
    unittest.main()
