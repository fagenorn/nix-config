"""acceptance-record: ship re-observes an acceptance record's pending code rows (issue 478).

Each test drives `python -m agent_tools.acceptance_record` from source in a
throwaway directory holding one record, the way test_verified_tree.py drives
its command. No test imports `acceptance_record`.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

HEAD = "0123456789abcdef0123456789abcdef01234567"
NAME = "p.acceptance.md"
LINK = "https://github.com/fagenorn/nix-config/actions/runs/1/job/2"
HEADER = "| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |\n"
DELIMITER = "|----|-----------|------|------------------|----------|--------|------------|---------|\n"
TITLE = "# Acceptance record — issue 1\n\n"


def row(ac, kind, check, verdict, observed="—"):
    return f"| {ac} | criterion {ac} | {kind} | {check} | {observed} | abc1234 | host mbp | {verdict} |\n"


def record(*rows, after=""):
    return TITLE + HEADER + DELIMITER + "".join(rows) + after


def checks(*pairs):
    return json.dumps([{"name": name, "bucket": bucket, "link": LINK} for name, bucket in pairs])


MET = row("AC1", "code", "`just agent-workflow-tests`", "met")
PENDING = row("AC2", "code", "`just build`; CI `Nix Eval` green on the PR", "unverified",
              observed="just build: exit 0 at abc1234")
GREEN = checks(("Nix Eval", "pass"), ("Instruction Budget", "pass"))


def rewritten(ac, kind, check, verdict, observed):
    """The line the command writes for a changed row."""
    return f"| {ac} | criterion {ac} | {kind} | {check} | {observed} | {HEAD} | host mbp | {verdict} |\n"


class AcceptanceRecordTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name).resolve()
        self.path = self.dir / NAME

    def write(self, text, path=None):
        data = text.encode("utf-8")
        (path or self.path).write_bytes(data)
        self.inode = (path or self.path).stat().st_ino
        return data

    def run_tool(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.acceptance_record", *args],
                              cwd=self.dir, input=stdin, capture_output=True, text=True,
                              check=False, timeout=60)

    def reobserve(self, *args, checks_json=None, record_name=NAME, head=HEAD, stdin=None):
        argv = ["reobserve", "--record", record_name, "--head", head]
        if checks_json is not None:
            (self.dir / "checks.json").write_text(checks_json, encoding="utf-8")
            argv += ["--checks", "checks.json"]
        return self.run_tool(*argv, *args, stdin=stdin)

    def ok(self, done):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        answer = json.loads(done.stdout)
        self.assertEqual(done.stdout, json.dumps(answer, sort_keys=True,
                                                 separators=(",", ":")) + "\n")
        self.assertEqual(sorted(answer), ["acceptance_state", "changed"])
        return answer

    def refused(self, done, fragment, before, path=None):
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertEqual(done.stdout, "")
        lines = done.stderr.splitlines()
        self.assertEqual(len(lines), 1, done.stderr)
        self.assertTrue(lines[0].startswith("acceptance-record: "), lines[0])
        self.assertIn(fragment, lines[0])
        self.assertEqual((path or self.path).read_bytes(), before)

    def unchanged(self, done, state, before):
        """Exit 0 with nothing changed, and the record never replaced."""
        self.assertEqual(self.ok(done), {"acceptance_state": state, "changed": []})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, self.inode)

    def test_a_ci_pending_row_observed_green_becomes_met(self):
        self.write(record(MET, PENDING, after="\n## Notes\n\nkept | as written\n"))
        answer = self.ok(self.reobserve("--row", "AC2", checks_json=GREEN))
        self.assertEqual(answer, {"acceptance_state": "met", "changed": ["AC2"]})
        self.assertEqual(self.path.read_text(encoding="utf-8"), record(MET, rewritten(
            "AC2", "code", "`just build`; CI `Nix Eval` green on the PR", "met",
            f"just build: exit 0 at abc1234; ship re-observed Nix Eval: pass at 0123456 {LINK}"),
            after="\n## Notes\n\nkept | as written\n"))

    def test_a_failed_check_makes_the_row_unmet(self):
        self.write(record(MET, PENDING))
        answer = self.ok(self.reobserve("--row", "AC2", checks_json=checks(("Nix Eval", "fail"))))
        self.assertEqual(answer, {"acceptance_state": "unmet", "changed": ["AC2"]})
        self.assertEqual(self.path.read_text(encoding="utf-8"), record(MET, rewritten(
            "AC2", "code", "`just build`; CI `Nix Eval` green on the PR", "unmet",
            f"just build: exit 0 at abc1234; ship re-observed Nix Eval: fail at 0123456 {LINK}")))

    def test_pending_skipping_and_cancel_leave_the_row_unchanged(self):
        for bucket in ("pending", "skipping", "cancel"):
            with self.subTest(bucket=bucket):
                before = self.write(record(MET, PENDING))
                done = self.reobserve("--row", "AC2", checks_json=checks(("Nix Eval", bucket)))
                self.unchanged(done, "unmet", before)

    def test_a_name_reported_with_differing_buckets_is_unobserved(self):
        before = self.write(record(MET, PENDING))
        done = self.reobserve("--row", "AC2",
                              checks_json=checks(("Nix Eval", "pass"), ("Nix Eval", "fail")))
        self.unchanged(done, "unmet", before)
        done = self.reobserve("--row", "AC2",
                              checks_json=checks(("Nix Eval", "pass"), ("Nix Eval", "pass")))
        self.assertEqual(self.ok(done), {"acceptance_state": "met", "changed": ["AC2"]})

    def test_a_failure_wins_over_an_unobserved_span(self):
        check = "CI `Nix Eval` and `Instruction Budget` green"
        self.write(record(MET, row("AC2", "code", check, "unverified")))
        done = self.reobserve("--row", "AC2", checks_json=checks(
            ("Nix Eval", "pending"), ("Instruction Budget", "fail")))
        self.assertEqual(self.ok(done), {"acceptance_state": "unmet", "changed": ["AC2"]})
        self.assertEqual(self.path.read_text(encoding="utf-8"), record(MET, rewritten(
            "AC2", "code", check, "unmet",
            f"ship re-observed Instruction Budget: fail at 0123456 {LINK}")))

    def test_ran_commands_pass_on_exit_0_and_fail_otherwise(self):
        check = "`just build mbp` exits 0; CI `Nix Eval` is green"
        for code, outcome, verdict, state in (("0", "pass", "met", "met"),
                                              ("1", "fail", "unmet", "unmet")):
            with self.subTest(code=code):
                self.write(record(MET, row("AC2", "code", check, "unverified")))
                done = self.reobserve("--row", "AC2", "--ran", f"just build mbp={code}",
                                      checks_json=checks(("Nix Eval", "pass")))
                self.assertEqual(self.ok(done), {"acceptance_state": state, "changed": ["AC2"]})
                self.assertEqual(self.path.read_text(encoding="utf-8"), record(MET, rewritten(
                    "AC2", "code", check, verdict,
                    f"ship re-observed just build mbp: {outcome} at 0123456 (exit {code}); "
                    f"ship re-observed Nix Eval: pass at 0123456 {LINK}")))

    def test_a_ran_command_splits_at_its_last_equals_sign(self):
        self.write(record(row("AC1", "code", "`env A=1 just test` exits 0", "unverified")))
        done = self.reobserve("--row", "AC1", "--ran", "env A=1 just test=0")
        self.assertEqual(self.ok(done), {"acceptance_state": "met", "changed": ["AC1"]})
        self.assertEqual(self.path.read_text(encoding="utf-8"), record(rewritten(
            "AC1", "code", "`env A=1 just test` exits 0", "met",
            "ship re-observed env A=1 just test: pass at 0123456 (exit 0)")))

    def test_escaped_pipes_classified_kinds_and_annotated_met(self):
        attested = row("AC1", "evidence (classified)", "the `a \\| b` reading", "met (attested, see (D3))")
        check = "`grep -c x \\| wc -l` prints 0; CI `Nix Eval`"
        human = row("AC3", "human", "the user reads it", "human_pending")
        self.write(record(attested, row("AC2", "code (classified)", check, "unverified"), human))
        done = self.reobserve("--row", "AC2", "--ran", "grep -c x | wc -l=0",
                              checks_json=checks(("Nix Eval", "pass")))
        self.assertEqual(self.ok(done), {"acceptance_state": "human_pending", "changed": ["AC2"]})
        self.assertEqual(self.path.read_text(encoding="utf-8"), record(attested, rewritten(
            "AC2", "code (classified)", check, "met",
            "ship re-observed grep -c x \\| wc -l: pass at 0123456 (exit 0); "
            f"ship re-observed Nix Eval: pass at 0123456 {LINK}"), human))

    def test_line_endings_and_text_around_the_table_are_preserved(self):
        after = "\r\n## Notes\r\n\r\n| not | a row |\r\n"
        crlf = lambda text: text.replace("\r\n", "\n").replace("\n", "\r\n")
        self.write(crlf(record(MET, PENDING)) + after)
        self.ok(self.reobserve("--row", "AC2", checks_json=GREEN))
        expected = crlf(record(MET, rewritten(
            "AC2", "code", "`just build`; CI `Nix Eval` green on the PR", "met",
            f"just build: exit 0 at abc1234; ship re-observed Nix Eval: pass at 0123456 {LINK}"))) + after
        self.assertEqual(self.path.read_bytes(), expected.encode("utf-8"))

    def test_checks_may_come_from_stdin(self):
        self.write(record(MET, PENDING))
        done = self.run_tool("reobserve", "--record", NAME, "--head", HEAD, "--checks", "-",
                             "--row", "AC2", stdin=GREEN)
        self.assertEqual(self.ok(done), {"acceptance_state": "met", "changed": ["AC2"]})

    def test_a_rewrite_keeps_the_mode_and_leaves_no_temporary_file(self):
        self.write(record(MET, PENDING))
        self.path.chmod(0o640)
        self.ok(self.reobserve("--row", "AC2", checks_json=GREEN))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual(sorted(os.listdir(self.dir)), ["checks.json", NAME])

    def test_no_row_only_rederives_the_state(self):
        human = row("AC2", "human", "the user reads it", "human_pending")
        for rows, state in (((MET,), "met"), ((MET, PENDING), "unmet"), ((MET, human), "human_pending"),
                            ((row("AC1", "evidence", "`x`", "unmet"), human), "unmet"),
                            ((row("AC1", "code", "`x`", "met (attested)"),), "met")):
            with self.subTest(rows=rows):
                before = self.write(record(*rows))
                self.unchanged(self.reobserve(checks_json=GREEN), state, before)
                self.unchanged(self.reobserve(), state, before)

    def test_a_malformed_record_is_refused(self):
        cases = {
            "no acceptance header": TITLE + "| AC | Verdict |\n|----|----|\n| AC1 | met |\n",
            "repeats the acceptance header": record(MET) + "\n" + HEADER + DELIMITER + PENDING,
            "no delimiter row": TITLE + HEADER + MET,
            "has 9 cells": record(MET.replace("| met |", "| met | extra |")),
            "unknown kind": record(row("AC1", "codes", "`x`", "met")),
            "unknown verdict": record(row("AC1", "code", "`x`", "done")),
            "malformed AC": record(row("A1", "code", "`x`", "met")),
            "repeats AC1": record(MET, MET),
            "no acceptance rows": record(after="\nprose\n"),
        }
        for fragment, text in cases.items():
            with self.subTest(fragment=fragment):
                before = self.write(text)
                self.refused(self.reobserve(), fragment, before)

    def test_a_row_outside_the_admission_rule_is_refused(self):
        rows = (MET, PENDING, row("AC3", "evidence", "CI `Nix Eval`", "unverified"),
                row("AC4", "human", "CI `Nix Eval`", "human_pending"),
                row("AC5", "code", "CI `Nix Eval`", "unmet"))
        cases = ((("--row", "AC9"), GREEN, "AC9 names no record row"),
                 (("--row", "bogus"), GREEN, "bogus names no record row"),
                 (("--row", "AC2", "--row", "AC2"), GREEN, "repeats --row AC2"),
                 (("--row", "AC3"), GREEN, "AC3 is not a code row"),
                 (("--row", "AC4"), GREEN, "AC4 is not a code row"),
                 (("--row", "AC1"), GREEN, "AC1 is not unverified"),
                 (("--row", "AC5"), GREEN, "AC5 is not unverified"),
                 (("--row", "AC2"), checks(("Other", "pass")), "AC2 has no measurement"),
                 (("--row", "AC2"), None, "AC2 has no measurement"))
        for argv, observed, fragment in cases:
            with self.subTest(argv=argv, checks=observed):
                before = self.write(record(*rows))
                self.refused(self.reobserve(*argv, checks_json=observed), fragment, before)

    def test_malformed_arguments_and_checks_are_refused(self):
        cases = ((("--head", "0123456"), "--head"), (("--head", HEAD.upper()), "--head"),
                 (("--ran", "no exit code"), "--ran"), (("--ran", "=0"), "--ran"),
                 (("--ran", "x=-1"), "--ran"), (("--ran", "x=a"), "--ran"), (("--ran", "x="), "--ran"),
                 (("--ran", "x=0", "--ran", "x=1"), "repeats --ran x"),
                 (("--checks", "absent.json"), "--checks"), (("extra",), "unrecognized"))
        for argv, fragment in cases:
            with self.subTest(argv=argv):
                before = self.write(record(MET, PENDING))
                self.refused(self.run_tool("reobserve", "--record", NAME, "--head", HEAD, *argv),
                             fragment, before)
        before = self.write(record(MET, PENDING))
        self.refused(self.run_tool("reobserve", "--record", NAME), "--head", before)
        self.refused(self.run_tool("verify"), "invalid choice", before)
        entry = {"name": "Nix Eval", "bucket": "pass", "link": LINK}
        for raw, fragment in (('[{"name": "a", "name": "b", "bucket": "pass", "link": ""}]', "duplicate"),
                              ('[{"name": "a", "bucket": "pass", "link": NaN}]', "NaN"),
                              ("{}", "--checks"), ("[", "--checks"),
                              (json.dumps([{**entry, "extra": 1}]), "--checks"),
                              (json.dumps([{"name": "a", "bucket": "pass"}]), "--checks"),
                              (json.dumps([{**entry, "bucket": "neutral"}]), "--checks"),
                              (json.dumps([{**entry, "name": ""}]), "--checks"),
                              (json.dumps([{**entry, "link": 1}]), "--checks"),
                              (json.dumps([{**entry, "link": LINK + "\n| AC9 |"}]), "--checks")):
            with self.subTest(raw=raw):
                self.refused(self.reobserve("--row", "AC2", checks_json=raw), fragment, before)

    def test_only_a_regular_acceptance_record_is_read(self):
        before = self.write(record(MET, PENDING))
        other = self.dir / "q.md"
        other_before = self.write(record(MET, PENDING), path=other)
        self.refused(self.reobserve("--row", "AC2", checks_json=GREEN, record_name="q.md"),
                     ".acceptance.md", other_before, path=other)
        link = self.dir / "l.acceptance.md"
        link.symlink_to(NAME)
        self.refused(self.reobserve("--row", "AC2", checks_json=GREEN, record_name=link.name),
                     "symlink", before)
        (self.dir / "d.acceptance.md").mkdir()
        self.refused(self.reobserve(record_name="d.acceptance.md"), "regular file", before)
        self.refused(self.reobserve(record_name="gone.acceptance.md"), "gone.acceptance.md", before)
        self.path.write_bytes(record(MET).encode("utf-8") + b"\xff\n")
        self.refused(self.reobserve(), "UTF-8", self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
