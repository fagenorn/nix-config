# Task 1: The artifact-budget CLI becomes `invoke` plus two stream writes

This task implements spec § The shared core (D3). Everything `main` does after it receives its arguments moves into `invoke(argv, read_stdin) -> Outcome`, which returns the exit code, stdout bytes and stderr text instead of writing them. `main` becomes `invoke` plus its two stream writes, so the CLI and every in-process caller share one code path. The CLI's argv, exit codes, stdout bytes and refusal lines do not change, and `workflow-state` still spawns the CLI after this task (Task 2 moves it in-process).

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`

**Interfaces:**
- Consumes (base): `_parser()`, whose `_Parser.error` raises `ArtifactBudgetError` (subparsers inherit `_Parser`); `_load_policy_identity`, `_policy_path`, `_check_artifact`, `_canonical`, `_delivery_model`, the boundary validators, `ArtifactBudgetError` and its subclass `InputReadError`. In the tests: `SCRIPT`, `POLICY`, the module `artifact_budget` (imported through the `sys.path` insert at the top of the file) and `mock`.
- Produces (Task 2 relies on these names):
  - `Outcome`: `@dataclass(frozen=True)` with `exit_code: int`, `stdout: bytes`, `stderr: str`.
  - `invoke(argv: Sequence[str], read_stdin: Callable[[int], bytes]) -> Outcome`.
  - `main(argv: Sequence[str] | None = None) -> int`, signature unchanged.
  - Private: `_refuse(label: str, exc: BaseException) -> Outcome` and `_input_bytes(path: str, wire_max: int, read_stdin: Callable[[int], bytes]) -> bytes`.

**Invariants:**
- For any argv and stdin bytes, `invoke(argv, io.BytesIO(stdin).read)` returns the exit code, stdout bytes and stderr text that a `sys.executable` run of the script returns.
- `invoke` writes to no process stream and never reads `sys.stdin`. It calls `read_stdin` at most once, with `wire_max + 1`, and only when `--input` is `-`.
- `invoke` catches `ArtifactBudgetError` (and so `InputReadError`) and nothing else. Any other exception propagates, so the CLI still exits 1 with a traceback where it does today. Argparse's `-h`/`--help` still prints and raises `SystemExit(0)`.
- `main` reads stdin only when `invoke` calls its reader. After this task, `main`'s three lines are the file's only references to `sys.stdin`, `sys.stdout` and `sys.stderr`.
- Labels, exit codes (0, 2, 3), the policy identity check, both wire bounds and canonical output stay byte-identical (472 D1, D2).

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_artifact_budget.py`, add `import io` between `import importlib.util` and `import os`. Then insert this class directly before `class SkillNamedReplyTest(DeliveredCustody, unittest.TestCase):`:

```python
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
        merged = {"issue": 14, "state": "merged",
                  "pr_url": "https://github.com/fagenorn/nix-config/pull/15",
                  "merge_sha": "abc123abc123abc123abc123abc123abc123abcd",
                  "issue_closed": True, "discussion_items": [], "detail_state": "none",
                  "report_path": None, "notes": ""}
        return (
            ("accepted producer report", self.PRODUCER,
             b'{"state":"failed","artifact":null,"notes":"x"}', 0, None),
            ("accepted ship-summary report",
             ("validate-report", "--boundary", "ship-summary", "--input", "-"),
             json.dumps(merged).encode("utf-8"), 0, None),
            ("schema-refused report", self.PRODUCER,
             b'{"state":"failed","artifact":null,"decisions":[]}', 2, "invalid report"),
            ("report over the wire bound", self.PRODUCER, b" " * (wire + 1), 2,
             "invalid report"),
            ("unreadable detail input",
             ("validate-detail-input", "--input", str(directory / "missing.json")), b"", 2,
             "cannot read detail input"),
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
                    process = subprocess.run([sys.executable, str(SCRIPT), *argv], input=stdin,
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
        """`workflow-state` prints its own reply after a validation, so `invoke`
        writes to neither process stream and reads stdin only through its reader,
        which a command without `--input -` never calls."""
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
```

The 8,192-byte handoff limit is the policy's, as `test_an_over_budget_check_reports_limit_and_overage` already pins. Each row's exit code and label were confirmed against the base CLI at plan time.

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `test_artifact_budget.py` with `-k InvokeParityTest`.
Expected: `FAILED (errors=9)`, 2 tests. Every error is `AttributeError: module 'artifact_budget' has no attribute 'invoke'`: eight subtests and the stream test.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/artifact_budget.py` (the imports already provide `dataclass`, `Callable` and `Sequence`):

1. Change `_input_bytes`'s signature to `def _input_bytes(path: str, wire_max: int, read_stdin: Callable[[int], bytes]) -> bytes:` and its stdin read to `raw = read_stdin(wire_max + 1)`. Leave the rest of the function as it is.

2. Replace `_refuse` with the following, preceded by the new `Outcome` class:

```python
@dataclass(frozen=True)
class Outcome:
    """What one artifact-budget run produces: its exit code, its stdout bytes and
    its stderr text (issue 498 D3)."""

    exit_code: int
    stdout: bytes
    stderr: str


def _refuse(label: str, exc: BaseException) -> Outcome:
    """The one refusal: exit 2, no stdout, and the stderr line
    `artifact-budget: <label>: <reason>`.

    The reason is the error's message with each whitespace run collapsed to one
    space, or the error's class name when the message is empty (issue 472 D1, D2).
    """
    reason = " ".join(str(exc).split()) or type(exc).__name__
    return Outcome(2, b"", f"artifact-budget: {label}: {reason}\n")
```

3. Rename `main` to `invoke` and give it this signature and docstring. Its `try:` body and its final `except ArtifactBudgetError as exc: return _refuse("invalid input", exc)` stay as they are, apart from the four edits in 4.

```python
def invoke(argv: Sequence[str], read_stdin: Callable[[int], bytes]) -> Outcome:
    """Run one artifact-budget command and return its outcome instead of writing
    it (issue 498 D3).

    `argv` excludes the program name. `read_stdin(size)` is called once, and only
    for `--input -`. Nothing is written to a process stream and nothing exits,
    except argparse's own `-h`/`--help`. Only an `ArtifactBudgetError` becomes a
    refusal; any other exception propagates.
    """
```

4. Inside `invoke`, make these edits. Every `return _refuse(...)` already returns the right value.
   - `describe`: replace `sys.stdout.buffer.write(_canonical({...}))` followed by `return 0` with `return Outcome(0, _canonical({...}), "")`, keeping the same dict.
   - `check`: replace the write and `return 0 if result.status == "within_budget" else 3` with `return Outcome(0 if result.status == "within_budget" else 3, _canonical(result.to_dict()), "")`.
   - Input read: `raw = _input_bytes(args.input, wire_max, read_stdin)`.
   - Success: replace `sys.stdout.buffer.write(output)` followed by `return 0` with `return Outcome(0, output, "")`.

5. Add the new `main` directly after `invoke`, before `if __name__ == "__main__":`. The reader is a lambda so that `sys.stdin` is looked up only when the reader is called. A command without `--input -` never touches stdin, as before, even when stdin is closed.

```python
def main(argv: Sequence[str] | None = None) -> int:
    """The CLI: `invoke` over this process's arguments and binary stdin, with the
    outcome written to stdout and stderr."""
    outcome = invoke(sys.argv[1:] if argv is None else argv,
                     lambda size: sys.stdin.buffer.read(size))
    sys.stdout.buffer.write(outcome.stdout)
    sys.stderr.write(outcome.stderr)
    return outcome.exit_code
```

Change nothing else. In particular, the parser, the labels, the policy branch that returns `invalid report` or `invalid detail input`, and `_delivery_model` stay as they are. This shape was prototyped at plan time: both new tests passed with it, and the module ran 59 tests.

- [ ] **Step 4: Verify**

Run the focused form with `-k InvokeParityTest`.
Expected: `OK`, 2 tests.

Run the focused form on the whole `test_artifact_budget.py` (it takes about 6 minutes on a loaded host).
Expected: `OK`, 59 tests (57 at base).

Run `bash -c 'set -e; f=home/common/agent-skills/scripts/artifact_budget.py; test "$(grep -c "sys\.std" "$f")" = 3; first=$(grep -n "sys\.std" "$f" | head -1 | cut -d: -f1); test "$first" -gt "$(grep -n "^def main" "$f" | cut -d: -f1)"; echo streams-ok'`.
Expected: `streams-ok`. At base there are five `sys.std` lines and the first of them precedes `def main`, so this gate fails there.

Run `git status --short`.
Expected: exactly ` M home/common/agent-skills/scripts/artifact_budget.py` and ` M home/common/agent-skills/tests/test_artifact_budget.py`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
launch-commit … -- -m "refactor(issue-498): split the artifact-budget CLI into an importable invoke core" -m "<session trailers>"
```

Verify: `git status --short -- home/common/agent-skills` prints nothing.
