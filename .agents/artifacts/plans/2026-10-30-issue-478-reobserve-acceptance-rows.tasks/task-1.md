# Task 1: `acceptance-record reobserve` command and its contract

Spec § The `acceptance-record` command and Test seams item 2. Rests on D1, D3, D4, D5, D6 and D12. After this task, `acceptance-record reobserve` re-observes named `unverified` `code` rows of an acceptance record against required-check and command observations. It rewrites only the rows that changed, prints the derived state, is installed through the command table, runs in `just agent-workflow-tests`, and has its contract in `python/README.md`.

**Files:**
- Create: `python/agent_tools/acceptance_record.py`
- Create: `tests/test_acceptance_record.py`
- Modify: `lib/agent-tools.nix` (the `commands` list)
- Modify: `justfile` (the `agent-workflow-tests` member list)
- Modify: `python/README.md`

**Interfaces:**
- Consumes: `reject_duplicate_keys` and `reject_nonfinite_literal` from `agent_tools.canonical` (agent-helpers rule 4).
- Produces, all in `agent_tools.acceptance_record`:
  - `AcceptanceRecordError(Exception)`: every refusal. `main` prints `acceptance-record: <message>` on stderr and returns 2.
  - `parse(text: str) -> list[Row]`: the table's rows in record order, or `AcceptanceRecordError`. `Row` is a frozen dataclass `(index: int, cells: tuple[str, ...])`, where `index` is the row's 0-based line number in `text.split("\n")` and `cells` holds its 8 stripped, still-escaped cells.
  - `derive(verdicts: Iterable[str]) -> str`: `"unmet"` if any verdict is `unmet` or `unverified`, else `"human_pending"` if any is `human_pending`, else `"met"`.
  - `load_checks(raw: str) -> dict[str, list[tuple[str, str]]]`: check name → its `(bucket, link)` reports in input order.
  - `parse_ran(values: Sequence[str]) -> dict[str, int]`: command → exit code.
  - `reobserve(text: str, head: str, checks: Mapping, rows: Sequence[str], ran: Mapping) -> tuple[str, str, list[str]]`: the new text, the derived state and the changed `AC` ids in record order.
  - `main(argv: Sequence[str] | None = None) -> int`, and the CLI `acceptance-record reobserve --record <path> --head <sha> [--checks <path|->] [--row <ACn>]... [--ran <command>=<exit code>]...`. Task 3's guidance calls it with exactly that argv shape.

**Invariants:**
- Only a `--row`-named row whose kind is `code` or `code (classified)` and whose verdict is `unverified` can change. `met`, `met (…)`, `unmet`, `human_pending`, `evidence` and `human` rows are never rewritten (D5).
- A changed row differs only in its `Observed`, `Commit` and `Verdict` cells. Every byte outside the changed rows is unchanged, `\r\n` endings and text after the table included (D6, D12).
- No change means no write: the record keeps its bytes and its inode. A refusal is exit 2, empty stdout, exactly one `acceptance-record: ` stderr line, and the record byte-identical.
- A rewrite replaces the record atomically through a temporary file in the same directory, keeps the record's permission bits and leaves no temporary file behind.
- Stdout on exit 0 is exactly one canonical JSON line (`sort_keys=True`, `separators=(",", ":")`) with the keys `acceptance_state` and `changed`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_acceptance_record.py` with exactly this content:

```python
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
                              (json.dumps([{**entry, "link": 1}]), "--checks")):
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
```

In `justfile`'s `agent-workflow-tests` recipe, add the member line `    tests/test_acceptance_record.py \` directly after `    tests/test_verified_tree.py \`.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_acceptance_record.py 2>&1 | tail -3'`
Expected: `Ran 16 tests`, `FAILED (failures=49)` (subtests counted). Every test fails because the subprocess exits 1 with `No module named agent_tools.acceptance_record`.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/acceptance_record.py`, a thin shell over importable functions (agent-helpers rule 2), with this module docstring (it is also `--help`'s description):

```python
"""acceptance-record: ship's re-observation of an acceptance record's pending code rows (issue 478).

`acceptance-record reobserve --record <path> --head <sha> [--checks <path|->] [--row <ACn>]...
[--ran <command>=<exit code>]...` reads the record's acceptance table under a closed grammar,
matches each named `unverified` `code` row's backticked measurements against the required checks
(`gh pr checks --required --json name,bucket,link`) and the commands run at `--head`, and applies
sdd's `code` rule: a failure makes the row `unmet`, all observed passes make it `met`, anything
unobserved leaves it unchanged. It prints `{acceptance_state, changed}` and replaces the record
only when a row changed. Every refusal exits 2 with one stderr line and the record untouched.
"""
```

Constants, used verbatim:

```python
ERROR_EXIT = 2
SUFFIX = ".acceptance.md"
HEADER = ("AC", "Criterion", "Kind", "Check or command", "Observed", "Commit", "Conditions", "Verdict")
AC_ID = re.compile(r"AC[1-9][0-9]*")
KIND = re.compile(r"(code|evidence|human)( \(classified\))?")
VERDICT = re.compile(r"met|met \(.+\)|unmet|unverified|human_pending")
DELIMITER_CELL = re.compile(r":?-+:?")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
EXIT_CODE = re.compile(r"[0-9]+")
SPAN = re.compile(r"`([^`]+)`")
PIPE = re.compile(r"(?<!\\)\|")
BUCKETS = frozenset({"pass", "fail", "pending", "skipping", "cancel"})
```

Every pattern is applied with `fullmatch`, except `SPAN.findall` and `PIPE.split`.

**Grammar (`parse`, D6, D12).** Split the decoded text on `"\n"` only. A line's trailing `"\r"` is not part of its content and is kept on rewrite. A line's cells are defined only when its content starts with `|`. `PIPE.split` must then leave a last piece that is empty after `strip()`, and the cells are the other pieces after the first, each `strip()`ped. The header is any line whose cells equal `HEADER`. Exactly one must exist in the whole file. The next line must have 8 cells, each a `DELIMITER_CELL`. After it, every line whose content starts with `|` is a row, and the first line that does not ends the table. Each row needs exactly 8 cells. `AC` must match `AC_ID` and be unique, `Kind` must match `KIND` and `Verdict` must match `VERDICT`. At least one row must exist.

**Observations.** `load_checks` uses `json.loads(raw, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)`. Catch `ValueError`, which covers `JSONDecodeError` and both hooks. The value must be a list. Each entry must be a dict with exactly the keys `name`, `bucket` and `link`: `name` a non-empty `str`, `bucket` in `BUCKETS`, `link` a `str`. `parse_ran` splits each value with `rpartition("=")`. The separator must be present, the command non-empty and the code an `EXIT_CODE`. A command given twice is refused.

**Re-observation (`reobserve`, D3, D4, D5).**
1. Admit every `--row` in argv order before computing anything. The id must not repeat an earlier one and must name a row. The row's `KIND` group 1 must be `code` and its verdict exactly `unverified`.
2. For each admitted row, its measurements are `SPAN.findall` over the raw `Check or command` cell, each with `\|` replaced by `|`, de-duplicated in first-seen order. A measurement matches the check of that name first, else the `--ran` command equal to it.
   - A check's outcome is its one bucket when every report of that name carries the same bucket and that bucket is `pass` or `fail`. Anything else is unobserved.
   - A command's outcome is `pass` for exit 0 and `fail` otherwise.
   - With no matching measurement, refuse.
3. Any `fail` makes the verdict `unmet`. Otherwise any unobserved match leaves the row unchanged, and it is not reported. Otherwise the verdict is `met`.
4. A changed row gets one entry per match whose outcome is `pass` or `fail`, in measurement order: `ship re-observed <span>: <outcome> at <head[:7]>`.
   - A check entry is followed by ` <link>` (the first report's link, omitted when empty).
   - A command entry is followed by ` (exit <n>)`.
   - Each entry has `|` replaced by `\|`.
   - The entries are joined by `; `. They replace an `Observed` cell that is empty or exactly `—`; otherwise they are appended after `; `.
5. Set `Commit` to `head` and `Verdict` to the new verdict. Render the line as `"| " + " | ".join(cells) + " |"` plus the original `"\r"` if it had one.
6. Derive the state over every row's final verdict. Return `"\n".join(lines)`, the state and the changed ids in record order.

**CLI shell (D12).** Subclass `argparse.ArgumentParser` as `_Parser` whose `error(self, message)` raises `AcceptanceRecordError(message)` (as in `review_package.py` and `sdd_gate.py`; do not override `exit`, so `--help` exits 0). Build it as `_Parser(prog="acceptance-record", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)` with `add_subparsers(dest="verb", required=True, parser_class=_Parser)` and one verb `reobserve`. That verb takes `--record` (required), `--head` (required), `--checks`, `--row` (`action="append", default=[]`) and `--ran` (`action="append", default=[]`). `main` wraps everything, `parse_args` included, in one `try` and checks, in this order:
1. `--head` against `FULL_SHA`.
2. `parse_ran`.
3. The record, in this order:
   - its name ends in `SUFFIX`;
   - `os.lstat` succeeds;
   - it is not `S_ISLNK`;
   - it is `S_ISREG`;
   - the bytes read;
   - they decode as strict UTF-8.
4. `parse`.
5. `--checks`, read from stdin for `-`, else as a UTF-8 file.
6. `reobserve`.

Only when `changed` is non-empty, write the new text atomically:
- `tempfile.mkstemp(dir=path.parent, prefix=".acceptance-record-")`;
- `os.fchmod` to the record's `stat.S_IMODE` mode;
- write the UTF-8 bytes, flush and `os.fsync`;
- `os.replace`.

If any step fails, unlink the temporary file. On success, `print` the canonical JSON line and return 0.

Refusal messages. Each is printed after `acceptance-record: `. The tests match the fragments shown in their cases.
- Arguments: the argparse message itself, for example `the following arguments are required: --head` or `unrecognized arguments: extra`.
- `--head` and `--ran`:
  - `--head must be a full 40-character lowercase sha: <value>`
  - `--ran needs <command>=<exit code>: <value>`
  - `repeats --ran <command>`
- The record file:
  - `record <path> must end in .acceptance.md`
  - `cannot read record <path>: <error>`
  - `record <path> is a symlink`
  - `record <path> is not a regular file`
  - `record <path> is not UTF-8`
- The grammar:
  - `record has no acceptance header`
  - `record repeats the acceptance header`
  - `record header has no delimiter row`
  - `record line <n> has <k> cells, not 8`
  - `record line <n> does not end in an unescaped pipe`
  - `record line <n> has a malformed AC: <value>`
  - `record repeats <ACn>`
  - `record <ACn> has unknown kind: <value>`
  - `record <ACn> has unknown verdict: <value>`
  - `record has no acceptance rows`
- `--checks`:
  - `cannot read --checks <path>: <error>`
  - `--checks is not strict JSON: <error>`
  - `--checks must be a JSON array`
  - `--checks entry <i> must have exactly name, bucket and link`
  - `--checks entry <i> is malformed`
- `--row`:
  - `repeats --row <ACn>`
  - `--row <value> names no record row`
  - `--row <ACn> is not a code row`
  - `--row <ACn> is not unverified`
  - `--row <ACn> has no measurement matching an observation`
- The write: `cannot write record <path>: <error>`

In `lib/agent-tools.nix`, add `"acceptance-record"` as the first entry of `commands` (the list is alphabetical). In `python/README.md`, insert this section directly before `## \`launch-scope\``, preceded by a blank line:

```markdown
## `acceptance-record`

`acceptance-record reobserve --record <path> --head <sha> [--checks <path|->] [--row <ACn>]... [--ran <command>=<exit code>]...` (issue 478) is ship-issue's Phase 6 re-observation of an acceptance record. It reads the record's one table under the header `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` with a closed grammar: rows split on unescaped pipes into exactly eight cells, `AC<n>` is unique, the kind is `code`, `evidence` or `human` with an optional ` (classified)`, and the verdict is `met`, `met (<annotation>)`, `unmet`, `unverified` or `human_pending`; anything else exits 2. `--checks` is exactly what `gh pr checks <pr-num> --required --json name,bucket,link` prints, loaded strictly, and `--ran` names a command run at `--head` with its exit code, split at the last `=`. Each `--row` must name an `unverified` `code` row with at least one backticked span of its `Check or command` cell equal to a check name or a `--ran` command. A `pass` bucket or exit 0 passes and a `fail` bucket or any other exit fails, while `pending`, `skipping`, `cancel` and a name reported with differing buckets leave the span unobserved. Any failure makes the row `unmet`, otherwise any unobserved span leaves it unchanged, otherwise it becomes `met`. A changed row's `Observed` cell gains one `ship re-observed <span>: <pass|fail> at <head7>` entry per observed span, its `Commit` becomes `--head`, and no other byte of the record changes. The command prints `{acceptance_state, changed}`, deriving the state as sdd does (`unmet` before `human_pending` before `met`), and atomically replaces the record only when `changed` is non-empty. Every refusal exits 2 with one `acceptance-record: <message>` line and leaves the record untouched. It grades nothing: `evidence` and `human` rows are never admitted.
```

- [ ] **Step 4: Verify**

Run the Step 2 command.
Expected: `Ran 16 tests`, `OK`.

Run (timeout 120 s): `bash -c 'set -e; grep -qx "    \"acceptance-record\"" lib/agent-tools.nix; test "$(grep -c "tests/test_acceptance_record.py" justfile)" = 1; grep -qx "## \`acceptance-record\`" python/README.md; PYTHONPATH="$PWD/python" python3 -m agent_tools.acceptance_record --help | grep -q "acceptance-record reobserve --record <path> --head <sha>"'`
Expected: exit 0. At the start commit it exits 1, because `lib/agent-tools.nix` has no `acceptance-record` row.

Run `git add python/agent_tools/acceptance_record.py tests/test_acceptance_record.py` first: the flake sees only files git tracks. An unstaged module fails evaluation with `agent-tools: command acceptance-record has no module agent_tools.acceptance_record`. Then run the Build (Global Constraints).
Expected: no error line. The build import-checks the new module, and the command-table row resolves to `agent_tools.acceptance_record`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/acceptance_record.py tests/test_acceptance_record.py lib/agent-tools.nix justfile python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-tools): add acceptance-record reobserve (issue 478)" -m "<trailers>"
```
