# Task 1: The refusal line

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `_refuse(label: str, exc: BaseException) -> int` in `artifact_budget.py`. It is the one writer of every refusal line, and Task 2 relies on it to surface its reasons.
  - `_decode_json(raw: bytes, subject: str = "JSON") -> object`. Its refusals start `invalid <subject>: `.
  - The test method `ArtifactBudgetCliTest.assert_refusal(self, result, label: str) -> str`, which returns the reason. Tasks 2 and 3 call it.

**Invariants:**
- Each refusal from `validate-report` and `validate-detail-input` exits 2, writes nothing to stdout and writes exactly one stderr line, `artifact-budget: <class>: <reason>\n`. `<class>` is one of `invalid report`, `cannot read report`, `invalid detail input` and `cannot read detail input`. `check`, `describe` and argument errors keep `invalid input` (D1, D5).
- The reason is non-empty and has no leading or trailing whitespace and no newline. The writer collapses every whitespace run to one space, and falls back to the exception's class name when the message is empty (D2, D12).
- A read failure's reason is the OS error string (`os.strerror` text) and never the path. A policy fault's reason says `policy` (D13).
- No input moves between accepted and refused. A successful `validate-report`, `validate-detail-input`, `check` or `describe` writes the same bytes as at base.

- [ ] **Step 1: Write the failing tests**

Add `import errno` to the module imports, keeping them sorted as they are now. Add this method directly after `run_validate`:

```python
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
```

Replace each of the 15 exact-stderr assertions. Today each compares stderr with `b"artifact-budget: invalid report\n"`, `b"artifact-budget: cannot read report\n"` or `b"artifact-budget: invalid detail input\n"`, usually together with the exit code and stdout. Each becomes `self.assert_refusal(<result>, "<class>")`, with the class it pinned. Keep the inputs, the loops and every other assertion. The sites are:
- `test_ship_handoff_v2_acceptance_state_is_required_closed_and_paired`: the `rejected` loop.
- `test_workflow_response_takes_its_own_wire_bound`: `refused`. Also assert `self.assertIn(str(response_bound), reason)` on the returned reason.
- `test_ship_handoff_reads_under_the_response_wire_bound`: `refused`. Also assert `str(response_bound)` is in the reason.
- `test_every_producer_report_matrix_row`: the `else` branch.
- `test_every_sdd_report_matrix_row`: the `invalid` loop.
- `assert_rejected`: its body becomes `self.assert_refusal(self.run_validate(boundary, payload, use_stdin), "invalid report")`.
- `test_ship_handoff_residuals_requires_durable_report_path` and `test_unpublished_rejects_the_delivery_home_itself`.
- `test_validate_report_rejects_wire_parse_and_io_failures`: the `malformed` loop, `missing`, `symlinked` and `over`.
- `test_validate_report_rejects_escaped_lone_surrogate_without_traceback`.
- `test_validate_detail_input_is_one_strict_cli_boundary` (the `invalid` loop) and `test_validate_detail_input_rejects_escaped_lone_surrogate_without_traceback`: class `invalid detail input`.

In `test_describe_pins_exact_policy_bytes_for_every_operation`, replace the `refused` assertion with the lines below. `invalid input` is the class `check` already uses for a policy fault:

```python
                    label = {"check": "invalid input", "validate-report": "invalid report",
                             "validate-detail-input": "invalid detail input"}[argv[0]]
                    self.assertIn("policy", self.assert_refusal(refused, label))
```

Add this test after `test_validate_report_rejects_escaped_lone_surrogate_without_traceback`:

```python
    def test_refusal_reasons_name_the_wire_parse_read_and_policy_failure(self):
        """Issue 472 D1-D3, D13: a refusal names its failure, never a path or an input value."""
        report = [sys.executable, str(SCRIPT), "validate-report", "--boundary", "producer"]
        good = b'{"state":"failed","artifact":null,"notes":"x"}'
        bound = json.loads(POLICY.read_text(encoding="utf-8"))["phase_reports"]["wire_max_bytes"]
        stdin_cases = (
            (b'{"state":"failed","state":"failed","artifact":null,"notes":"x"}',
             ('duplicate key "state"',)),
            (b'{"st\\nate":1,"st\\nate":2}', ('duplicate key "st\\nate"',)),
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
        summary = {"issue": 49, "state": "stopped", "pr_url": "", "merge_sha": None,
                   "issue_closed": False, "discussion_items": [], "detail_state": "none",
                   "report_path": None, "notes": "canonical bound"}

        def compact(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")

        prefix = "https://example.test/"
        summary["pr_url"] = prefix + "x" * (bound - len(compact(summary)) - len(prefix))
        self.assertEqual(len(compact(summary)), bound)
        canonical = subprocess.run(
            [sys.executable, str(SCRIPT), "validate-report", "--boundary", "ship-summary",
             "--input", "-", "--policy", str(POLICY)],
            input=compact(summary), capture_output=True, check=False)
        self.assertIn(str(bound), self.assert_refusal(canonical, "invalid report"))
        detail = subprocess.run(
            [sys.executable, str(SCRIPT), "validate-detail-input", "--input", "-",
             "--policy", str(POLICY)], input=b"{", capture_output=True, check=False)
        self.assertIn("invalid JSON", self.assert_refusal(detail, "invalid detail input"))
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
            for policy in (broken, directory / "absent-policy.json"):
                with self.subTest(policy=policy.name):
                    result = subprocess.run(report + ["--input", "-", "--policy", str(policy)],
                                            input=good, capture_output=True, check=False)
                    reason = self.assert_refusal(result, "invalid report")
                    self.assertIn("policy", reason)
                    self.assertNotIn(raw, reason)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py`.
Expected: FAIL in about 15 tests. Each failure is `assert_refusal`'s prefix assertion, for example `AssertionError: False is not true : b'artifact-budget: invalid report\n'`, because base writes the class without `: <reason>`.

- [ ] **Step 3: Write the minimal implementation**

All edits are in `artifact_budget.py`.

1. **The writer.** Add it above `main`:

```python
def _refuse(label: str, exc: BaseException) -> int:
    """Write the one refusal line, `artifact-budget: <label>: <reason>`, and return 2.

    The reason is the error's message with each whitespace run collapsed to one
    space, or the error's class name when the message is empty (issue 472 D1, D2).
    """
    reason = " ".join(str(exc).split()) or type(exc).__name__
    sys.stderr.write(f"artifact-budget: {label}: {reason}\n")
    return 2
```

2. **`main`.** Bind each caught error (`except ArtifactBudgetError as exc:`). The three validate catch sites that write a bare class today return `_refuse(f"invalid {label}", exc)` instead. The `InputReadError` site returns `_refuse(f"cannot read {label}", exc)`. The outer handler returns `_refuse("invalid input", exc)`. The policy block still re-raises for `check` and `describe`, and `label` keeps its two values, `report` and `detail input`. The canonical-output check raises `ArtifactBudgetError(f"canonical output exceeds the {wire_max}-byte wire bound")`.
3. **Input read.** `_read_regular` raises `InputReadError(exc.strerror)` when the open or the read fails with an `OSError` that has a `strerror`. Otherwise it raises `InputReadError("path cannot be opened")`, which covers a `ValueError` for a NUL byte and an `OSError` without `strerror`. It keeps `InputReadError("not a regular file")`. Its `limit` refusal becomes `ArtifactBudgetError(f"input exceeds the {limit}-byte wire bound")`. `_input_bytes`'s stdin refusal becomes `ArtifactBudgetError(f"input exceeds the {wire_max}-byte wire bound")`.
4. **JSON.** `_pairs_no_duplicates` raises `ArtifactBudgetError(f"duplicate key {json.dumps(key)}")`, and `_reject_constant` raises `ArtifactBudgetError("non-standard constant")`. `_decode_json` gains `subject: str = "JSON"`:
   - `UnicodeDecodeError` gives `f"invalid {subject}: invalid UTF-8 at byte {exc.start}: {exc.reason}"`.
   - `json.JSONDecodeError` gives `f"invalid {subject}: {exc.msg} at line {exc.lineno} column {exc.colno}"`, and never `exc.doc`.
   - An `ArtifactBudgetError` from the hooks gives `f"invalid {subject}: {exc}"`.
   - Every branch chains with `from exc`.
5. **Policy (D13).** `_parse_policy` calls `_decode_json(raw, "policy JSON")`. `_load_policy_identity` raises `ArtifactBudgetError(f"cannot read policy: {exc}")`, where `exc` is the `InputReadError`. `policy identity disagreement` and `cannot resolve installed policy` keep their text.

Leave `JSON root is not an object` and every validator message as they are. Task 2 sharpens the validators.

- [ ] **Step 4: Verify**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py`.
Expected: PASS, 47 tests, `OK`.

Run: `bash -c 'if rg -n "b\"artifact-budget: (invalid|cannot read) (report|detail input)\\\\n\"" home/common/agent-skills/tests/test_artifact_budget.py; then exit 1; fi'`
Expected: exit 0 with no output. At base it lists 15 lines and exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
git commit -m "feat(artifact-budget): name the reason on every refusal line (issue 472)"
```
