# diff-scope Residuals Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Close the five residuals issue #21's final review deferred on
`home/common/agent-skills/scripts/diff-scope.py`, before any caller binds the contract.

**Architecture:** Four product changes confined to one script and one test file. Two are
one-line-shaped (a new escape branch in `_escape_text`; `--no-relative` on both `git diff`
calls in `measure`), one is test-only (`git_env()` drops the git variables that relocate a
repository), and one is structural: the buffered `cat-file --batch -z` read is replaced by a
lockstep streaming reader that writes the next request only after the previous response is
fully consumed, so a header window costs `HEADER_SCAN_BYTES`, not the blob.

**Tech stack:** Python 3.13.12 standard library only (`argparse`, `subprocess`, `tempfile`,
`json`, `pathlib`, `unittest`, `unittest.mock`, `tracemalloc`). git 2.51.2. Test runner is
`python3 -m unittest`, driven by `just agent-workflow-tests`.

**Design:** `.claude/specs/2026-08-17-diff-scope-residuals-design.md` — that file owns the
decision ledger (D1–D9) this plan cites. Its prior art is
`.claude/specs/2026-08-16-diff-scope-helper-design.md` (issue #21, D1–D25); every citation of
that ledger names issue #21 explicitly, because the two ledgers reuse the same IDs.

## Global Constraints

- Standard library only. No new dependency, no new file, no new flag, no new output key.
- `--format json` output must be byte-identical to the base commit for any given range.
  Issue #21's D11 fixes that payload; only the text branch may move.
- Product changes go **only** in `home/common/agent-skills/scripts/diff-scope.py`; test
  changes **only** in `home/common/agent-skills/tests/test_diff_scope.py` and — for Task 1's
  environment scrub alone — `home/common/agent-skills/tests/test_ship_release_contracts.py`
  (per D10). No other suite in the `just agent-workflow-tests` recipe spawns git, so the
  scrub widens no further.
- `home/common/agent-skills/default.nix` and `justfile` are **not edited** — both already
  register the helper and its suite (issue #21's D15).
- No `.nix` file is edited, so `just build` is not part of any gate.
- `patches/agent-plugins/` is untouched; no `patchRevision` bump.
- **Every decision citation written into source (comments, docstrings) names its document**
  (per D12): `issue #21's D3`, `issue 31's D2`. `diff-scope.py`'s existing comments cite issue
  #21's ledger bare — `(D25)` at :146/:195, `(D8)` :269, `(D23)` :364, `(D7)` :374, `(D3)` :437,
  `(D19)` :467 — so a bare new `(D2)` would read as issue #21's D2 ("three-dot ranges out of
  scope"), which is a different decision. Leave the existing bare citations alone; qualify every
  citation this issue adds.
- Commits are SSH-signed by default. Never pass `--no-gpg-sign` or
  `-c commit.gpgsign=false`; surface a signing failure instead.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011BW621YtNATjTJfsJSJXnB
  ```

## Out of scope

Restated from the spec's `## Out of scope`, so no task widens into them:

- `normalize_artifact_path(".//x")` returning `b"/x"` — deliberately left open per D8. Do not
  fix it here; it is surfaced as a discussion item, not dropped.
- Any skill prose or consumer change. Nothing binds `diff-scope` yet (issue #21's D14/D17)
  and this slice does not create the first caller.
- The JSON output contract (issue #21's D11).
- New exclusion classes, thresholds, verdicts, or any exit status meaning "too big"
  (issue #21's D9).
- `home/common/agent-skills/default.nix` and `justfile`.
- Three-dot ranges, working-tree diffs, the stdin-numstat mode (issue #21's D2, D10).

## Test seams

Both seams already exist; this slice adds no new seam and no new harness.

- **Classifier layer** — the module loaded through `load_module()` in
  `home/common/agent-skills/tests/test_diff_scope.py`. Issue #21's D20 `sys.modules`
  registration inside `load_module()` is load-bearing and must not be touched. Carries R1's
  escape assertions, R3's no-subprocess assertion, and R4's `tracemalloc` measurement (the
  only in-process seam, and the only reason a memory bound is observable at all — per D4).
- **CLI layer** — `subprocess.run([sys.executable, SCRIPT, ...])` against scratch
  repositories under `tempfile.TemporaryDirectory`. Carries R1's end-to-end line count, R2,
  R3's all-excluded range, and R5.

Every new fixture is a new module-level `build_*_repo(root)` plus its own `unittest.TestCase`
owning a `TemporaryDirectory` in `setUpClass`/`tearDownClass`, driving git through
`subprocess.run` **argv lists** (issue #21's D18). Per D6.

**On D6 and the shared fixture.** D6 reads "the shared `build_fixture_repo` repository is
never mutated by a test, **and** R1's U+2028 path is added to that shared fixture". These are
not in tension: no *test* mutates the shared repo at run time (which is what would make the
suite order-dependent), while the *builder* gains one more head-side file. Task 2 therefore
edits `build_fixture_repo` and every assertion that counts its rows in one commit — the suite
is green at every task boundary, never between them.

## File structure

| File | Change | Responsibility after this plan |
|------|--------|-------------------------------|
| `home/common/agent-skills/scripts/diff-scope.py` | modify | Adds `UNICODE_LINE_SEPARATORS` + one `_escape_text` branch (T2); `--no-relative` on both `measure` diff calls (T3); `import tempfile`, `DISCARD_CHUNK_BYTES`, `_read_exactly`, `_discard_exactly`, `_stderr_text`, `_read_response`, `_batch_headers` replacing `_parse_batch` (T5). |
| `home/common/agent-skills/tests/test_diff_scope.py` | modify | Adds `import unittest.mock` + `import tracemalloc`; `GIT_LOCATION_VARS` + the `git_env()` scrub and its test (T1); the U+2028 fixture path and its six updated assertions (T2); `DiffScopeRelativeConfigTest` (T3); `build_no_candidate_repo` + `DiffScopeAllExcludedRangeTest` + the patched-`_git` test (T4); `build_large_blob_repo` + `DiffScopeHeaderScanBoundTest` (T5). |
| `home/common/agent-skills/tests/test_ship_release_contracts.py` | modify (T1 only) | Gains the same `GIT_LOCATION_VARS` tuple and pop loop in its own independent `git_env()` (per D10). It is the only other suite in the `just agent-workflow-tests` recipe that spawns git, and AC5's whole-suite gate cannot pass without it. Nothing else in this file changes. |
| `.claude/specs/2026-08-17-diff-scope-residuals-design.md` | already modified | Owns the ledger; D9 was appended during planning, D10–D12 during the Phase-5 standards review. Tasks cite it, they do not edit it. |

## Task index

| Task | Title | Files touched | Risk lane |
|------|-------|---------------|-----------|
| Task 1 | Scrub the inherited git environment (R5) | `home/common/agent-skills/tests/test_diff_scope.py`, `home/common/agent-skills/tests/test_ship_release_contracts.py` | low-risk |
| Task 2 | Escape the three Unicode line separators (R1) | `home/common/agent-skills/scripts/diff-scope.py`, `home/common/agent-skills/tests/test_diff_scope.py` | full |
| Task 3 | Neutralise `diff.relative` (R2) | `home/common/agent-skills/scripts/diff-scope.py`, `home/common/agent-skills/tests/test_diff_scope.py` | full |
| Task 4 | Cover the header-scan early return (R3) | `home/common/agent-skills/tests/test_diff_scope.py` | low-risk |
| Task 5 | Bound the header scan's buffering (R4) | `home/common/agent-skills/scripts/diff-scope.py`, `home/common/agent-skills/tests/test_diff_scope.py` | full |

Lane rationale where it is not self-evident: Task 2 and Task 3 change a public
output/measurement contract, so neither is low-risk despite its size; Task 5 owns a
subprocess lifecycle, which the low-risk lane excludes by definition. Tasks 1 and 4 add no
product behaviour — Task 1 changes only the suite's own harness, Task 4 changes nothing but
the suite.

**Order is load-bearing in one place only:** Task 1 must precede Task 5, because Task 5's
in-process seam reuses the scrubbed `git_env()` (D9). Tasks 2, 3 and 4 are independent of
each other.

## Decisions

Cited by ID from the spec's `## Decision ledger`; never restated here.

- D1 — the `\uNNNN` wire form for U+0085/U+2028/U+2029 (Task 2).
- D2 — `--no-relative` on both diff calls, not a `-c` form threaded through `_git` (Task 3).
- D3 — the lockstep streaming reader; issue #21's D7 and D23 preserved (Task 5).
- D4 — `tracemalloc` around an in-process `measure()`, not a fake-stream seam (Task 5).
- D5 — cover the early return twice: CLI repo plus patched-`_git` assertion (Task 4).
- D6 — one `build_*_repo` + one `TestCase` per new fixture; the U+2028 path joins the shared
  fixture with its count assertions in the same commit (Tasks 2–5).
- D7 — the named repository-location variables, not a blanket `GIT_*` sweep (Task 1).
- D8 — the `.//x` residual stays out of scope.
- D9 — Task 5's in-process `measure()` runs under `patch.dict(os.environ, git_env(),
  clear=True)`, and Task 1 lands first so that scrub exists.

## Verification, everywhere

Every task's final gate is the project gate, run from the worktree root
(`/Users/anis/tmp/nix-config/.claude/worktrees/issue-31-diff-scope-residuals`):

```sh
just agent-workflow-tests
```

`justfile:59` already lists `home/common/agent-skills/tests/test_diff_scope.py`. For the
per-step loops inside a task, use the targeted form (sub-second, and its output is small by
construction):

```sh
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k <name-fragment>
```

**Falsifiability protocol.** Where a task's criterion rests on a product change, the
implementer proves the new test fails without it:

```sh
git stash push -- home/common/agent-skills/scripts/diff-scope.py
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k <name-fragment>   # expect FAIL
git stash pop
```

Task 4 adds no product change, so it uses a mutation gate instead; its body spells that out.

---

### Task 1: Scrub the inherited git environment (R5)

**Files:**
- Modify: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: module-level `GIT_LOCATION_VARS: tuple[str, ...]` and a `git_env()` that returns
  an environment holding none of those names. Task 5 calls `git_env()` for the same purpose
  in process (D9).

**Invariants:**
- `git_env()` never carries a variable that relocates git's repository, work tree, index or
  object store — the criterion D7 names, not just the three the issue lists.
- `git_env()` still carries `PATH` and `HOME`, so `sys.executable` and `git` keep resolving:
  the scrub is `pop`-based on a copy of `os.environ`, never an allowlist.
- Every hermetic override `git_env()` already sets is unchanged.

- [ ] **Step 1: Write the failing test**

Add `import unittest.mock` directly under the existing `import unittest` in the test file's
import block, then add this method to `DiffScopeCommandTest` (after
`test_output_is_byte_identical_across_two_runs`):

```python
    def test_the_suite_git_environment_is_immune_to_an_inherited_git_dir(self):
        # An invoking session exporting GIT_DIR redirects every scratch-repo git
        # call and every helper subprocess at an unrelated repository (D7).
        poison = {
            "GIT_DIR": "/nonexistent/other.git",
            "GIT_WORK_TREE": "/nonexistent/tree",
            "GIT_INDEX_FILE": "/nonexistent/index",
        }
        baseline = self.measure("--artifact-path", self.ARTIFACT)
        with unittest.mock.patch.dict(os.environ, poison):
            env = git_env()
            for name in poison:
                self.assertNotIn(name, env)
            completed = run_helper(
                self.root, self.range, "--artifact-path", self.ARTIFACT
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout.decode("utf-8")), baseline)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k immune_to_an_inherited_git_dir`

Expected: FAIL — `assertNotIn` reports `'GIT_DIR' unexpectedly found` in the returned
environment. (If that assertion is removed the run still reddens one line later: the helper's
own `git rev-parse --is-inside-work-tree` resolves against `/nonexistent/other.git` and the
CLI exits 1.)

- [ ] **Step 3: Write the minimal implementation**

Add the constant immediately above `git_env()` and the scrub as the first thing `git_env()`
does to its copy — before the hermetic overrides, so an override can never be popped:

```python
GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)
```

`git_env()` keeps its signature and every existing key. Its body gains, right after
`env = dict(os.environ)`:

```python
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
```

Extend its docstring to state the criterion, not the enumeration: the variables dropped are
the ones that relocate git's repository, work tree, index or object store; a blanket `GIT_*`
sweep is rejected because it would also drop `GIT_EXEC_PATH` and `GIT_TEMPLATE_DIR`, which a
Nix-provided git may rely on (D7).

Then apply the **same** scrub to the second git-spawning suite in the recipe,
`home/common/agent-skills/tests/test_ship_release_contracts.py`, which defines its own
independent `git_env()` (that file's `git_env`, `env = dict(os.environ)`) and whose `sh()`
helper runs real `git init`/`git commit`. Add the identical `GIT_LOCATION_VARS` tuple and pop
loop there — duplicated rather than imported, because the two suites share no helper module
and this plan adds no new file (D10). Without it, AC5's whole-suite gate below fails: at the
base commit `GIT_DIR=/nonexistent/other.git` reddens 2 of that file's 10 tests with
`fatal: Invalid path '/nonexistent'`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k immune_to_an_inherited_git_dir`
Expected: PASS, 1 test.

Then the AC's literal wording — the whole suite under a poisoned environment. Two suites in
that recipe invoke git: `test_diff_scope.py` and `test_ship_release_contracts.py`. Both must
be scrubbed for this gate to pass (per D10); the remaining suites were verified not to spawn
git:

```sh
GIT_DIR=/nonexistent/other.git just agent-workflow-tests
```
Expected: OK, no failures, no errors.

Then the plain project gate: `just agent-workflow-tests` → OK.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_diff_scope.py \
        home/common/agent-skills/tests/test_ship_release_contracts.py
git commit -m "test(agent-skills): scrub inherited git location vars from the suite env"
```

---

### Task 2: Escape the three Unicode line separators (R1)

**Files:**
- Modify: `home/common/agent-skills/scripts/diff-scope.py`
- Modify: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: module-level `UNICODE_LINE_SEPARATORS: tuple[str, str, str]` in the script;
  `_escape_text(value: str) -> str` keeps its signature. `build_fixture_repo(root)` keeps its
  signature and gains one head-side file, so the shared fixture range is twelve rows and
  eight product files.

**Invariants:**
- One ranked file is exactly one physical line for a `str.splitlines()` consumer, for any
  path bytes whatsoever. The escaped set is a superset of `str.splitlines()`'s boundary set.
- `format_json` and `_decode` do not move; JSON bytes for any range are unchanged.
- Surrogate-escaped bytes stay unescaped (issue #21's D25) — the existing
  `test_a_non_utf8_path_is_not_escaped_by_the_text_formatter` must stay green untouched.
- The new escape is textually disjoint from the existing `\xNN` form: four hex digits, so no
  decoder can read `\u0085` as `\x00` followed by `85` (D1).
- **This task is atomic.** The fixture change and all six assertion updates land in one
  commit; splitting them leaves the suite red (D6).

- [ ] **Step 1: Write the failing tests**

**(a) Classifier layer.** Add to `DiffScopeClassifierTest`, immediately after
`test_every_control_byte_in_a_path_is_escaped_in_text_output`:

```python
    def test_unicode_line_separators_in_a_path_are_escaped_in_text_output(self):
        # str.splitlines() breaks on ten characters; seven are C0 and already
        # escaped, and these three close the set (D1). Four hex digits keep the
        # form disjoint from the two-digit \xNN escapes above.
        for character, escape in (
            ("\x85", "\\u0085"),
            ("\u2028", "\\u2028"),
            ("\u2029", "\\u2029"),
        ):
            with self.subTest(character=character):
                path = f"we{character}ird.txt".encode("utf-8")
                payload = self.module.format_text(self.scope([self.row(path, 1, 0)]))
                self.assertEqual(len(payload.splitlines()), 3)
                self.assertEqual(payload.splitlines()[2], f"  1  we{escape}ird.txt")
```

**(b) CLI layer, shared fixture.** In `build_fixture_repo`, add one head-side file directly
after the `qu"ote.txt` write and before `git(root, "add", "-A")`:

```python
    write(root, "ls\u2028path.txt".encode("utf-8"), b"separator path\n")
```

Then update every assertion that counts the shared fixture — all six, in this same edit:

1. `DiffScopeCommandTest`'s class docstring: "eleven rows" → "twelve rows", "five ordinary
   product files" → "six ordinary product files", and the tail sentence becomes "...two of
   which carry equal churn, and three of which carry a newline, a double quote and a U+2028
   line separator in their names."
2. `test_product_totals_exclude_every_class`:
   `{"changed_lines": 5, "changed_files": 7}` → `{"changed_lines": 6, "changed_files": 8}`.
3. `test_every_row_git_emitted_is_accounted_for_exactly_once`:
   `self.assertEqual(rows, 11)` → `self.assertEqual(rows, 12)`.
4. `test_an_artifact_path_matching_nothing_is_not_an_error`:
   `self.assertEqual(payload["product"]["changed_files"], 8)` → `9`.
5. `test_text_format_reports_the_same_totals`:
   `"product: 5 lines, 7 files"` → `"product: 6 lines, 8 files"`.
6. `test_text_format_gives_each_ranked_file_exactly_one_line`: `2 + 7` → `2 + 8`, and add one
   line above that assertion:

```python
        # The separator path is one added line, and one physical line.
        self.assertIn("  1  ls\\u2028path.txt\n", text)
```

Finally rename `test_paths_holding_a_newline_or_a_quote_survive_end_to_end` to
`test_paths_holding_a_newline_a_quote_or_a_separator_survive_end_to_end` and add a third
assertion to it, proving the raw bytes round-trip through APFS, `git diff -z` and the JSON
boundary:

```python
        self.assertIn("ls\u2028path.txt", paths)
```

The excluded counts do not move: the new row is ordinary product.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k separators_in_a_path_are_escaped`
Expected: FAIL — `4 != 3` on the `splitlines()` length, for the first subtest.

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k text_format_gives_each_ranked_file`
Expected: FAIL — the **`assertIn` added by item 6 is what reddens first**, because item 6
inserts it above the count assertion (`test_diff_scope.py:581`), which is therefore never
reached at base. The defect the count assertion guards is still real and still the point
(`11 != 10` — the raw U+2028 splits one ranked file in two); it simply is not the message you
will see. Do not reorder the assertions to chase the count message — either failure proves the
same base defect (the escaped `assertIn` line item 6 adds cannot match while the path is emitted raw).

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/diff-scope.py`, add a module-level constant beside
`TEXT_ESCAPES`:

```python
UNICODE_LINE_SEPARATORS = ("\x85", "\u2028", "\u2029")
```

`_escape_text(value: str) -> str` keeps its signature and its existing two branches in their
existing order. Insert exactly one new `elif`, **after** the C0/DEL test, so no existing
rendering moves:

```python
        elif character in UNICODE_LINE_SEPARATORS:
            pieces.append(f"\\u{ord(character):04x}")
```

Rewrite its docstring so it describes the escape set the code now produces: the set is a
superset of `str.splitlines()`'s boundary set, which on Python 3.13.12 is exactly
`\n \v \f \r \x1c \x1d \x1e \x85 \u2028 \u2029`; the first seven are C0 and take the named or
`\xNN` form, the last three take the four-digit `\uNNNN` form (D1); a literal backslash stays
doubled; surrogate-escaped bytes are still deliberately left alone because `_emit` writes them
back verbatim and none can end a line (issue #21's D25). Escape every backslash you mean
literally — the docstring is not raw, and the existing text already writes `\\xNN` for that
reason.

Amend `format_text`'s docstring in the same spirit: the one-file-one-line claim now holds for
a Unicode-aware consumer, not only a byte-oriented one. Do not touch `format_json` or
`_decode`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -v`
Expected: OK, every test in the file, including the six updated counts.

Falsifiability, both layers at once:

```sh
git stash push -- home/common/agent-skills/scripts/diff-scope.py
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k separators_in_a_path_are_escaped   # expect FAIL: 4 != 3
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k text_format_gives_each_ranked_file # expect FAIL: 11 != 10
git stash pop
```

JSON stability, since this task is the one that could disturb it — the assertion is on file
content, not on a commit range:

```sh
git diff -U0 -- home/common/agent-skills/scripts/diff-scope.py \
  | grep -c '^[+-].*\(format_json\|ensure_ascii\)' || true
```
Expected: `0` — no *changed* line touches the JSON branch. The `-U0` and the `^[+-]` anchor
matter: with default context this task's own `format_text` docstring edit drags the neighbouring
`ensure_ascii` sentence (`diff-scope.py:194-195`) into the diff window and the gate
false-positives; `|| true` keeps `grep -c`'s exit 1 on a zero count from reading as a failure.
`test_json_output_is_compact_key_sorted_and_ascii` (`test_diff_scope.py:277-288`) is the real
guarantee here — this grep is only a fast smoke check.

Then: `just agent-workflow-tests` → OK.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/diff-scope.py home/common/agent-skills/tests/test_diff_scope.py
git commit -m "fix(diff-scope): escape the three Unicode line separators in text output"
```

---

### Task 3: Neutralise `diff.relative` (R2)

**Files:**
- Modify: `home/common/agent-skills/scripts/diff-scope.py`
- Modify: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: `build_fixture_repo(root)`, `git(root, *arguments)`, `run_helper(root,
  *arguments)` — all existing module-level helpers in the test file. If Task 2 has already
  landed, `build_fixture_repo` builds a twelve-row fixture; this task asserts no counts, so
  either shape works.
- Produces: `DiffScopeRelativeConfigTest`. `measure(root, base, head, artifact_paths)` keeps
  its signature exactly.

**Invariants:**
- Every reported path is repository-root-relative regardless of `--root`'s depth in the work
  tree, which is what issue #21's D8 (`--artifact-path` values are root-relative) and
  `read_headers`' numstat↔name-status join both require.
- The measurement never depends on caller config: `-M` already pins `diff.renames`
  (issue #21's D3) and `--no-relative` now pins `diff.relative` at the same site (D2).
- `_git`'s signature does not change — the neutralisation is a diff option, not a `-c` form
  threaded in front of every subcommand (D2).
- `rev-parse` and `cat-file --batch` are not touched: neither consults `diff.relative`, and
  `cat-file` addresses content by `<oid>:<path>` in the root frame whatever the cwd.

- [ ] **Step 1: Write the failing test**

Append a new class to the test file, after `DiffScopeCommandTest`:

```python
class DiffScopeRelativeConfigTest(unittest.TestCase):
    """diff.relative must not reach the measurement, whatever --root points at.

    git's diff.relative both strips the leading directory from every reported
    path and drops the rows outside the cwd, so an unneutralised measurement
    taken from a subdirectory answers a different question in a different frame
    (D2).
    """

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = cls.temporary.name
        build_fixture_repo(cls.root)
        git(cls.root, "config", "diff.relative", "true")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def payload(self, root_argument):
        completed = run_helper(self.root, "HEAD~1..HEAD", "--root", root_argument)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.decode("utf-8"))

    def test_a_subdirectory_root_measures_the_same_range_as_the_work_tree_root(self):
        # At the work-tree root diff.relative is a no-op, so the baseline IS the
        # unconfigured answer -- one fixture, one variable (cwd depth).
        baseline = self.payload(self.root)
        # src/ is created by build_fixture_repo and is inside the work tree, so
        # _validate_root passes.
        subject = self.payload(os.path.join(self.root, "src"))
        # Whole payloads, not totals: the skew's first symptom is in the path
        # strings ("app.py" for "src/app.py"), and a totals-only assertion can
        # stay green while every path is wrong.
        self.assertEqual(subject, baseline)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k subdirectory_root_measures_the_same_range`
Expected: FAIL — the subject run exits 1 with
`diff-scope: git reported missing content for ...`, because the relative frame reports
`app.py` while `cat-file` resolves `<oid>:app.py` at the repository root. (`assertEqual(
completed.returncode, 0, ...)` inside `payload` is what reddens.)

- [ ] **Step 3: Write the minimal implementation**

In `measure`, add `--no-relative` to **both** `git diff` invocations, positioned with the
other diff options immediately after `-M`:

```python
    rows = parse_numstat(
        _git(root, "diff", "--numstat", "-z", "-M", "--no-relative", range_argument)
    )
```

and

```python
    statuses = parse_name_status(
        _git(root, "diff", "--name-status", "-z", "-M", "--no-relative", range_argument)
    )
```

Update the existing comment above the first call so it names both neutralisations and both
ledger rows — `-M` and `--no-relative` are passed explicitly so the measurement never depends
on the caller's `diff.renames` (issue #21's D3) or `diff.relative` (D2). Only the
`--name-status` call needs a matching note if the comment does not already cover it; do not
add a second `_git` parameter and do not touch any other call site.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k subdirectory_root_measures_the_same_range`
Expected: PASS, 1 test.

Falsifiability:

```sh
git stash push -- home/common/agent-skills/scripts/diff-scope.py
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k subdirectory_root_measures_the_same_range   # expect FAIL
git stash pop
```

Then: `just agent-workflow-tests` → OK. The pre-existing `DiffScopeCommandTest` measurements
must be unchanged: `--no-relative` is a no-op when `diff.relative` is unset, which those tests
prove by staying green.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/diff-scope.py home/common/agent-skills/tests/test_diff_scope.py
git commit -m "fix(diff-scope): pin the diff frame with --no-relative on both diff calls"
```

---

### Task 4: Cover the header-scan early return (R3)

**Files:**
- Modify: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: `load_module()`, `git`, `write`, `run_helper`, and — from Task 1 — the scrubbed
  `git_env()`. `read_headers(root: Path, base: str, head: str, rows: Sequence[DiffRow],
  statuses: dict[bytes, bytes]) -> dict[bytes, bytes]` is the product function under test; it
  is not modified.
- Produces: `build_no_candidate_repo(root)` and `DiffScopeAllExcludedRangeTest`, plus
  `DiffScopeClassifierTest.test_read_headers_returns_without_spawning_git`.

**Invariants:**
- **No product change in this task.** `home/common/agent-skills/scripts/diff-scope.py` must
  not appear in the commit.
- The fixture's range produces rows and still measures. A binary row is *product*
  (issue #21's D5) and is skipped by `read_headers` for being binary, not for being excluded
  — so `files` is not empty. A fixture asserting `files == []` would describe a different and
  unreachable range.
- The no-subprocess claim is an assertion, not an inference: `_git` is patched to raise, so
  any spawn attempt fails the test (D5).

- [ ] **Step 1: Write the failing tests**

**(a) Direct, classifier layer.** Add to `DiffScopeClassifierTest`, after
`test_a_row_whose_header_was_not_read_is_product`:

```python
    def test_read_headers_returns_without_spawning_git(self):
        # The early return makes two separable claims. This one -- that no
        # cat-file subprocess runs -- is invisible end to end, so patching _git
        # is what turns it into an assertion (D5).
        rows = [
            self.row(b"assets/blob.bin", None, None),
            self.row(b"pnpm-lock.yaml", 40, 2),
        ]
        statuses = {b"assets/blob.bin": b"M", b"pnpm-lock.yaml": b"M"}
        with unittest.mock.patch.object(
            self.module, "_git", side_effect=AssertionError("cat-file must not run")
        ):
            headers = self.module.read_headers(
                Path("/nonexistent"), "base", "head", rows, statuses
            )
        self.assertEqual(headers, {})
```

`Path` and `unittest.mock` are already imported (the latter by Task 1; add
`import unittest.mock` here if Task 1 has not landed).

**(b) CLI layer.** Add a module-level builder next to `build_fixture_repo`:

```python
def build_no_candidate_repo(root):
    """Two commits whose every row is binary or a lockfile: no content candidate."""
    git(root, "init", "-q", "-b", "main", ".")
    write(root, b"assets/blob.bin", b"\x00\x01\x02binary\x00")
    write(root, b"pnpm-lock.yaml", b"lock\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")

    write(root, b"assets/blob.bin", b"\x00\x01\x02BINARY CHANGED\x00\x00")
    write(root, b"pnpm-lock.yaml", b"lock\nmore\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "head")
```

and its class, after `DiffScopeCommandTest`:

```python
class DiffScopeAllExcludedRangeTest(unittest.TestCase):
    """A range that produces rows but no content candidate still measures.

    read_headers returns an empty mapping without spawning cat-file when every
    row is binary or a lockfile. The binary row is product (issue #21's D5) and
    is skipped for being binary, not for being excluded, so the answer is one
    product file carrying zero lines plus one excluded lockfile.
    """

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = cls.temporary.name
        build_no_candidate_repo(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_a_range_with_no_content_candidate_still_measures(self):
        completed = run_helper(self.root, "HEAD~1..HEAD")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(payload["product"], {"changed_lines": 0, "changed_files": 1})
        self.assertEqual(
            payload["excluded"], {"lockfile": 1, "generated": 0, "artifact": 0}
        )
        self.assertEqual(
            payload["files"],
            [{"path": "assets/blob.bin", "changed_lines": 0, "binary": True}],
        )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k read_headers_returns_without_spawning_git`
Expected: FAIL — `AttributeError` / `NameError` if `unittest.mock` is not imported, otherwise
this pair is *expected to pass immediately*: R3 is a coverage requirement, so the branch it
covers already exists. Step 4's mutation gate is what makes the pair falsifiable.

- [ ] **Step 3: Write the minimal implementation**

There is none. This task adds no product code — the early return already exists in
`read_headers`:

```python
    if not requests:
        return {}
```

Confirm the diff touches only the test file before continuing:

```sh
git diff --stat -- home/common/agent-skills/scripts/diff-scope.py
```
Expected: empty output.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k "read_headers_returns_without_spawning_git or no_content_candidate"`
Expected: PASS, 2 tests.

**Mutation gate (this task's falsifiability, in place of a stash).** Both tests must be
load-bearing; prove each against its own mutation and revert immediately.

Mutation A — delete the two `if not requests: return {}` lines from `read_headers`:

```sh
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k read_headers_returns_without_spawning_git
```
Expected: FAIL — `AssertionError: cat-file must not run`. Restore with
`git checkout -- home/common/agent-skills/scripts/diff-scope.py`. (The CLI test is
deliberately *not* expected to redden here: with no requests, `cat-file --batch` reads EOF and
exits 0, so only the patched test can observe the spawn — which is exactly why D5 asks for
both.)

Mutation B — make `_is_lockfile` return `False` unconditionally:

```sh
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k no_content_candidate
```
Expected: FAIL — `excluded["lockfile"]` is 0 and `files` carries a second entry. Restore with
`git checkout -- home/common/agent-skills/scripts/diff-scope.py`.

Then: `just agent-workflow-tests` → OK, and confirm
`git status --short home/common/agent-skills/scripts/diff-scope.py` is empty.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_diff_scope.py
git commit -m "test(diff-scope): cover the header-scan no-subprocess early return"
```

---

### Task 5: Bound the header scan's buffering (R4)

**Files:**
- Modify: `home/common/agent-skills/scripts/diff-scope.py`
- Modify: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: `git_env()` with Task 1's scrub already in place (D9); `load_module()`, `git`,
  `write`.
- Produces, in the script:
  - `DISCARD_CHUNK_BYTES = 65536`
  - `_read_exactly(stream, count: int) -> bytes`
  - `_discard_exactly(stream, count: int) -> None`
  - `_stderr_text(handle) -> str`
  - `_read_response(stream) -> bytes`
  - `_batch_headers(root: Path, requests: Sequence[bytes]) -> list[bytes]`

  `_parse_batch(payload, expected)` is **deleted** — no test references it. `read_headers`
  keeps its signature; only its last two lines change.
- Produces, in the tests: `LARGE_BLOB_LINE`, `LARGE_BLOB_LINES`,
  `build_large_blob_repo(root)`, `DiffScopeHeaderScanBoundTest`.

**Invariants:**
- Exactly one `cat-file` subprocess serves the whole range — issue #21's D7 survives; only
  the pipe protocol inside that process changes.
- Deadlock-freedom is **structural**: a request is written only after the previous response,
  terminator included, has been fully consumed, so git is provably blocked in `read()` on
  stdin whenever we write, and a request (an object id, a path, a NUL) is orders of magnitude
  below the 64 KiB pipe capacity. **No writer thread; no thread at all.**
- stderr goes to a `tempfile.TemporaryFile`, never a third pipe — a file has no capacity
  limit, so the second classic deadlock in this shape cannot occur. It is read back only
  after `wait()`.
- The `finally` closes stdin, then **stdout before `wait()`**: on an error path git may be
  blocked mid-write, and closing our read end is what gives it EPIPE so `wait()` returns
  instead of hanging.
- A dead subprocess still yields a `diff-scope: ...` diagnostic, never a traceback — a
  `BrokenPipeError` while writing a request becomes a `DiffScopeError` carrying git's stderr.
- Every header-validation rule from issue #21's D23 survives verbatim: the
  `endswith(b" missing")` test, the three-part `rsplit`, the `int()` guard, each raising
  `DiffScopeError`.
- Responses are consumed by declared byte size, never by a delimiter, so content holding
  newlines cannot desynchronise the stream. A non-blob type still has its content consumed.
- At most `HEADER_SCAN_BYTES` of any blob is retained; the remainder is dropped in fixed
  `DISCARD_CHUNK_BYTES` chunks.
- JSON output for any range is byte-identical to before this task.

- [ ] **Step 1: Write the failing test**

Add `import tracemalloc` to the test file's import block, then the fixture and its class at
the end of the file, before the `if __name__ == "__main__":` guard:

```python
LARGE_BLOB_LINE = b"lorem ipsum dolor sit amet, consectetur adipiscing\n"  # 50 bytes
LARGE_BLOB_LINES = 90_000  # 4.29 MiB, comfortably over the 4 MiB the design names


def build_large_blob_repo(root):
    """Two commits whose head side adds one plain-text blob well over 4 MiB.

    No NUL byte and no generated marker, so the big file is a genuine content
    candidate: read_headers must fetch a header window for it.
    """
    git(root, "init", "-q", "-b", "main", ".")
    write(root, b"seed.txt", b"seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")

    write(root, b"big.txt", LARGE_BLOB_LINE * LARGE_BLOB_LINES)
    write(root, b"small.txt", b"small\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "head")


class DiffScopeHeaderScanBoundTest(unittest.TestCase):
    """The header scan retains a window, not a blob.

    measure() runs in process because tracemalloc cannot see across a
    subprocess boundary (D4), and under a scrubbed environment because an
    in-process call reaches os.environ directly rather than through git_env()
    (D9).
    """

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = cls.temporary.name
        build_large_blob_repo(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_measuring_a_multi_megabyte_blob_stays_under_one_megabyte(self):
        with unittest.mock.patch.dict(os.environ, git_env(), clear=True):
            tracemalloc.start()
            try:
                result = self.module.measure(Path(self.root), "HEAD~1", "HEAD", ())
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        # The measurement must still be right: a bound met by reading nothing
        # would be no bound at all.
        churn = {row.path: row.churn for row in result.files}
        self.assertEqual(churn[b"big.txt"], LARGE_BLOB_LINES)
        self.assertEqual(result.changed_files, 2)
        self.assertLess(peak, 1 * 1024 * 1024)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k multi_megabyte_blob`
Expected: FAIL — `assertLess` reports a peak of roughly 4.5 MiB against the 1 MiB bound,
because `subprocess.run(stdout=PIPE)` materialises the whole `cat-file --batch` response as
one `bytes` object. The two correctness assertions above it pass.

- [ ] **Step 3: Write the minimal implementation**

Add `import tempfile` to the script's import block, directly after `import sys`. Add
`DISCARD_CHUNK_BYTES = 65536` beside `HEADER_SCAN_BYTES`. Delete `_parse_batch` entirely and
put these four functions in its place — this is the carve-out case: the exact wire protocol
and the exact teardown ordering are the decision, and prose cannot safely express them.

```python
def _read_exactly(stream, count: int) -> bytes:
    """Read exactly `count` bytes; a short read means the batch ended early."""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise DiffScopeError("truncated cat-file batch content")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _discard_exactly(stream, count: int) -> None:
    """Drop `count` bytes in fixed DISCARD_CHUNK_BYTES chunks, retaining none.

    This is what bounds the scan: the rest of a blob crosses the pipe but is
    never held, so peak allocation tracks the chunk size, not the blob.
    """
    remaining = count
    while remaining > 0:
        chunk = stream.read(min(remaining, DISCARD_CHUNK_BYTES))
        if not chunk:
            raise DiffScopeError("truncated cat-file batch content")
        remaining -= len(chunk)


def _stderr_text(handle) -> str:
    """Read a finished subprocess's stderr file back as a diagnostic string."""
    handle.seek(0)
    return handle.read().decode("utf-8", errors="replace").strip()


def _read_response(stream) -> bytes:
    """Consume one cat-file --batch response and return its header window.

    The response is consumed by its declared byte size, never by a delimiter,
    so content holding newlines cannot desynchronise the stream.

    Parse defensively and raise DiffScopeError for ANYTHING unparsable (issue
    #21's D23). readline() stops at the first newline, so for a `missing`
    answer -- which echoes the request verbatim -- a path holding a newline
    yields a fragment that neither ends with b" missing" nor rsplits into three
    parts. Letting that reach the unpack raises ValueError, which escapes
    main's `except DiffScopeError` and dies with a traceback instead of the
    `diff-scope: ...` message every CLI error test asserts on.
    """
    line = stream.readline()
    if not line:
        raise DiffScopeError("truncated cat-file batch response")
    header = line.removesuffix(b"\n")
    parts = header.rsplit(b" ", 2)
    if header.endswith(b" missing") or len(parts) != 3:
        # We only ever ask for a side git's own --name-status said exists, so a
        # missing answer is a hard error, never a fallback (issue #21's D7).
        raise DiffScopeError(f"git reported missing content for {header!r}")
    object_type, size_text = parts[1:]
    try:
        size = int(size_text)
    except ValueError:
        raise DiffScopeError(f"unparsable cat-file header {header!r}") from None
    # A non-blob type (a submodule gitlink resolves to a commit) yields b"",
    # which the classifier reads as not generated -- but its content is still
    # consumed, because position in the stream is what keeps us in sync.
    keep = min(size, HEADER_SCAN_BYTES) if object_type == b"blob" else 0
    window = _read_exactly(stream, keep)
    _discard_exactly(stream, size - keep)
    _read_exactly(stream, 1)  # one newline terminates each response
    return window


def _batch_headers(root: Path, requests: Sequence[bytes]) -> list[bytes]:
    """Return one header window per request, in request order.

    One `cat-file --batch -z` subprocess serves the whole range (issue #21's
    D7); only the pipe protocol inside it changes. It is driven in lockstep: a
    request is written only once the previous response -- content and
    terminator -- has been fully consumed, so git is blocked reading stdin
    whenever we write and its stdout pipe is empty. Deadlock-freedom is
    therefore structural rather than mitigated, and no writer thread is needed.
    stderr goes to a file, never a third pipe: reading a stderr pipe without a
    thread is the other classic deadlock in this shape (D3).
    """
    windows: list[bytes] = []
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                ["git", "cat-file", "--batch", "-z"],
                cwd=str(root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
            )
        except FileNotFoundError:
            raise DiffScopeError("git executable not found on PATH") from None
        died_early = False
        try:
            for request in requests:
                try:
                    process.stdin.write(request)
                    process.stdin.flush()
                except BrokenPipeError:
                    # git died before reading the request. Report its own
                    # diagnostic once wait() has reaped it, not a traceback.
                    died_early = True
                    break
                windows.append(_read_response(process.stdout))
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            # stdout closes BEFORE the wait, deliberately: on the error path git
            # may be blocked mid-write, and closing our read end gives it EPIPE
            # so wait() returns instead of hanging. On the success path git has
            # already written everything and is blocked reading stdin, so
            # closing stdin ends it with status 0.
            process.stdout.close()
            returncode = process.wait()
        detail = _stderr_text(errors)
        if died_early:
            raise DiffScopeError(f"git cat-file --batch exited early: {detail}")
        if returncode != 0:
            raise DiffScopeError(f"git cat-file --batch failed: {detail}")
    return windows
```

Then change the last two lines of `read_headers` — and nothing else in it; the early return
and the request-building are untouched:

```python
    if not requests:
        return {}
    return dict(zip(paths, _batch_headers(root, requests)))
```

`_git` keeps its `stdin_payload` parameter only if another call site still uses it; check with
`grep -n 'stdin_payload' home/common/agent-skills/scripts/diff-scope.py` and drop the
parameter (and its docstring mention) if `cat-file` was its only user.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k multi_megabyte_blob`
Expected: PASS, 1 test, peak far under 1 MiB.

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -v`
Expected: OK. The error-path tests inherited from issue #21 —
`test_an_unknown_revision_exits_one`, `test_a_malformed_range_exits_one`,
`test_a_path_shaped_revision_measures_the_same_as_its_object_id` — must all still print
`diff-scope:` on stderr and exit 1 rather than hanging or tracing back; treat a hang here as a
teardown-ordering bug in `_batch_headers`, not a flake.

**Re-arm Task 4's early-return assertion (D11).** Task 4's
`test_read_headers_returns_without_spawning_git` proves "no subprocess" by patching
`self.module._git`, which is load-bearing only while `read_headers` reaches `cat-file`
*through* `_git`. This task replaces that call with `_batch_headers(root, requests)`, which
opens its own `subprocess.Popen`, so the patch would stop covering the spawn: with the early
return deleted, `_batch_headers(root, [])` spawns `cat-file` with zero requests, exits 0,
returns `[]`, and `dict(zip([], []))` is still `{}` — the test would pass green over a real
regression. Extend that test's context manager to patch **both** names, e.g. add
`unittest.mock.patch.object(self.module, "_batch_headers", side_effect=AssertionError("cat-file must not run"))`
alongside the existing `_git` patch. This is a Task 5 invariant, not an optional tidy.

Then re-run Task 4's Mutation A under the new implementation — delete the two
`if not requests: return {}` lines from `read_headers`, run
`python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k read_headers_returns_without_spawning_git`,
expect FAIL with `AssertionError: cat-file must not run`, then restore with
`git checkout -- home/common/agent-skills/scripts/diff-scope.py`. A green run here means the
assertion has gone hollow and the task is not done.

Falsifiability:

```sh
git stash push -- home/common/agent-skills/scripts/diff-scope.py
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py -k multi_megabyte_blob   # expect FAIL: peak ~4.5 MiB
git stash pop
```

Final project gates, both forms:

```sh
just agent-workflow-tests
GIT_DIR=/nonexistent/other.git just agent-workflow-tests
```
Expected: OK in both. The second is the D9 check — it is the run that would redden if the
in-process `measure()` were not wrapped in `patch.dict(os.environ, git_env(), clear=True)`.

Leftover-process check, since this task owns a subprocess lifecycle:

```sh
pgrep -fl 'cat-file --batch' || echo "no surviving cat-file"
```
Expected: `no surviving cat-file`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/diff-scope.py home/common/agent-skills/tests/test_diff_scope.py
git commit -m "perf(diff-scope): stream the header scan in lockstep instead of buffering"
```

---

## Acceptance criteria coverage

| Issue 31 acceptance criterion | Task | Fails at `b59ff22` via |
|---|---|---|
| A ranked filename containing U+2028 (and U+0085, U+2029) round-trips through text output as a single line for a `splitlines()` consumer | Task 2 | `test_unicode_line_separators_in_a_path_are_escaped_in_text_output` (4 != 3) and `test_text_format_gives_each_ranked_file_exactly_one_line` (11 != 10) |
| With `diff.relative=true` and a non-root `--root`, path accounting matches the unconfigured baseline | Task 3 | `DiffScopeRelativeConfigTest` — subject run exits 1 on the `cat-file` join |
| The header-scan no-subprocess early return is exercised by the suite | Task 4 | coverage requirement; proved load-bearing by Mutation A (`AssertionError: cat-file must not run`) |
| Header scanning of a non-binary candidate reads no more than the scan budget of its content | Task 5 | `test_measuring_a_multi_megabyte_blob_stays_under_one_megabyte` (peak ~4.5 MiB vs 1 MiB) |
| The suite passes with `GIT_DIR` pointing at an unrelated repository | Task 1 | `test_the_suite_git_environment_is_immune_to_an_inherited_git_dir`, plus `GIT_DIR=… just agent-workflow-tests` |
| Demo: the suite passes with new tests named for each residual, one embedding U+2028 | Tasks 1–5 | `just agent-workflow-tests` after Task 5 |

## Standards review provenance

| Field | Value |
|-------|-------|
| Reviewer | Native fresh plan reviewer (`reviewer`, Opus/high), no inherited context |
| Fallback used | Yes — the Codex `plan-review` path was skipped deliberately |
| Fallback rationale | `codex-collaboration` budgets ~15 min for one isolated pass; at the Phase-5 boundary ~54 min of the attempt deadline remained for review + execution + ship. Issue #21's D24 set the precedent: prefer the native dispatch over waiting when the margin would starve execution. Logged here rather than as a ledger row because it is a process choice, not a design decision. |
| Base SHA reviewed | `b59ff22bf35ae172d78a686c0b3f55b4ac800f62` |
| Contract | `/Users/anis/.claude/skills/from-issue/REVIEW-CONTRACT.md` |
| Verdict | blocking (2 blocking, 3 should-fix, 3 discussion) |

Dispositions — every finding re-verified against the live worktree before it was applied:

| ID | Finding | Disposition |
|----|---------|-------------|
| B1 | AC5's whole-suite gate fails after Task 1; `test_ship_release_contracts.py` has its own unscrubbed `git_env()` | **Applied.** Re-verified live: 2 of 10 tests redden under `GIT_DIR=/nonexistent/other.git`, and the file is in the `just agent-workflow-tests` recipe. Global Constraints, Task index, File structure, Task 1 Step 3 and Step 5 updated; ledger row D10. |
| B2 | Task 5 silently guts Task 4's early-return assertion by moving the spawn off `_git` | **Applied.** Task 5 Step 4 now requires patching `_batch_headers` too and re-running Mutation A; ledger row D11. |
| S1 | In-script `(D2)` citations collide with issue #21's bare-cited ledger | **Applied.** New Global Constraint; ledger row D12. |
| S2 | Task 2's JSON-stability grep false-positives on its own docstring edit | **Applied.** Gate is now `git diff -U0 … \| grep -c '^[+-].*\(format_json\|ensure_ascii\)' \|\| true`, with the real guarantee named. |
| S3 | Task 2 Step 2's predicted failure message is the wrong assertion | **Applied.** Step 2 now names the `assertIn` as the first failure and forbids reordering to chase the count message. |
| Discussion: T4 mutation gate needs a clean `diff-scope.py` before it starts | **Accepted, no plan edit.** Task 4 Step 4 already checks `git status --short` after restoring, and `sdd` commits each task before the next begins. Noted here so a reviewer need not re-derive it. |
| Discussion: D8 (`.//x`) not blocking | **Accepted.** Stays out of scope; surfaced as a discussion item on the issue result. |
| Discussion: D4 measures what it claims | **Accepted, no action.** Reviewer confirmed `subprocess.run`'s buffering is Python-heap and therefore `tracemalloc`-visible, with 4x/24x margins. |

Findings verified as **sound, no change needed**: D2's completeness (all five `_git` call sites walked; only `measure`'s two diffs consult `diff.relative`), D3's deadlock-freedom, and Task 2's six-assertion count audit.
