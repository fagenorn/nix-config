# Design: emptying the diff-scope parking lot

Issue: https://github.com/fagenorn/nix-config/issues/31
Prior art (binding): `.claude/specs/2026-08-16-diff-scope-helper-design.md` — issue #21, ledger D1–D25.

## Intent

Issue #21 shipped `home/common/agent-skills/scripts/diff-scope.py` and its suite. Its final
review **deferred** — did not reject — five residuals. Nothing consumes the helper yet
(issue #21's D14/D17), so this is the last cheap moment to fix them: every one of them is a
correctness or hygiene gap that becomes a caller-visible bug the moment `ship-issue`'s
degradation gate and the scoped-review packet builder bind to the contract.

The five, four behavioural and one test-only:

1. **Text output is not line-safe for Unicode separators.** Issue #21's D25 made
   `--format text` escape every C0 character and DEL so that "one ranked file is exactly one
   physical line". It missed U+0085 (NEL), U+2028 (LS) and U+2029 (PS). Verified on
   Python 3.13.12: `str.splitlines()` splits on exactly ten characters — `\n \v \f \r \x1c
   \x1d \x1e \x85 \u2028 \u2029`. The first seven are C0 and already escaped; the last three
   pass through raw. A Unicode-aware consumer — including the suite's own
   `len(text.splitlines())` assertions — therefore reads one ranked file as two lines. The
   JSON form is unaffected (`ensure_ascii=True` escapes all three) and issue #21's D11 fixes
   that payload byte-for-byte, so the JSON branch must not move.

   The hazard is not hypothetical, and not confined to the helper: the first draft of *this
   spec* accidentally carried fourteen raw separators, and `splitlines()` read 371 lines from
   a file with 357 newlines. That is exactly the failure mode R1 describes, reproduced by
   accident in the document specifying the fix.

2. **`diff.relative` is not neutralised.** `measure` passes `-M` explicitly so the
   measurement never depends on the caller's `diff.renames` (issue #21's D3), but nothing
   does the same for `diff.relative`. `_git` runs with `cwd=<--root>`, and `--root` is
   allowed to be any directory inside a work tree. Verified on git 2.51.2: with
   `diff.relative=true` and cwd `src/`, `git diff --numstat -z -M` reports `a.txt` where the
   repository-root frame is `src/a.txt`. That silently breaks three things at once — the
   `--artifact-path` prefix match (issue #21's D8 fixes values as repo-root-relative), the
   numstat↔name-status join in `read_headers` (which raises `no --name-status row for ...`
   only by luck of both sides being skewed identically), and the ranking's path tie-break.

3. **The header-scan early return is unreachable by the suite.** `read_headers` returns `{}`
   without spawning `cat-file` when no row is a content candidate. The single CLI fixture
   repo always contains product rows, so no test reaches it. This is the accepted AC3
   residual from issue #21's review.

4. **The header scan is bounded in retention, not in buffering.** `_git` runs
   `cat-file --batch -z` under `subprocess.run(stdout=PIPE)`, so the whole batch response —
   every byte of every candidate blob — is materialised as one `bytes` object before
   `_parse_batch` clips each window to `HEADER_SCAN_BYTES`. Measured: capturing an 8 MiB
   payload through `subprocess.run(stdout=PIPE)` shows an 8.05 MiB `tracemalloc` peak. A
   review packet over a repository with a few large text assets pays that in full for an
   8 KiB question.

5. **The suite's git environment is not scrubbed.** `git_env()` does `dict(os.environ)` and
   overrides only config and identity keys. An invoking session exporting `GIT_DIR`,
   `GIT_WORK_TREE` or `GIT_INDEX_FILE` redirects every scratch-repo `git` call *and* every
   helper subprocess at an unrelated repository. Test-only, and exactly the hazard
   `CLAUDE.md` already documents for the `codex-plugin-cc` suite ("with the live
   Claude-session env unscrubbed, 4 upstream tests fail spuriously").

The public contract does not change: no new flag, no new output key, no changed JSON byte,
no new exclusion class, no threshold (issue #21's D9). Every change is either a bug fix
inside an existing documented behaviour or an internal mechanism swap.

## Requirements

Each maps 1:1 to an acceptance criterion and is stated so it is **falsifiable at base commit
`b59ff22`** — the "at base" column says what the base commit actually does.

| # | Requirement | Fails at `b59ff22` because |
|---|-------------|----------------------------|
| R1 | A ranked path containing U+2028 — and U+0085, U+2029 — renders as exactly one physical line for a `str.splitlines()` consumer, in `--format text`. `--format json` output is byte-identical to base for the same input. | `_escape_text` leaves all three raw, so `format_text` emits an embedded separator and `splitlines()` returns one extra line per such path. |
| R2 | With `diff.relative=true` configured in the repository and `--root` pointing at a subdirectory of the work tree, the measurement is identical to the same range measured with the config unset. | Both `git diff` calls inherit `diff.relative`, so every reported path loses its leading directory component and the accounting is computed in the wrong frame. |
| R3 | The `read_headers` early return — no content candidates, therefore no `cat-file` subprocess — is exercised by the suite, both end-to-end through the CLI and as a direct no-subprocess assertion. | No test reaches the branch; the only CLI fixture repo always carries product rows. |
| R4 | Measuring a range whose largest candidate blob is ≥ 4 MiB holds a peak traced allocation below 1 MiB. | `subprocess.run(stdout=PIPE)` buffers the entire `cat-file --batch` response, so the peak scales with total candidate content, not with `HEADER_SCAN_BYTES`. |
| R5 | The whole suite passes with `GIT_DIR` (and `GIT_WORK_TREE`, `GIT_INDEX_FILE`) set in the invoking environment to an unrelated path. | `git_env()` copies them through, so scratch-repo `git init` and every helper invocation target the inherited repository and fail or measure the wrong thing. |

R1–R4 are **full-lane** (behavioural changes to a helper with a fixed public contract; R4
additionally rewrites a subprocess I/O mechanism). R5 is **low-risk**, test-only.

## Design

All product changes are confined to `home/common/agent-skills/scripts/diff-scope.py`; all
test changes to `home/common/agent-skills/tests/test_diff_scope.py`.
`home/common/agent-skills/default.nix` and `justfile` already register the helper and its
suite and are **not** edited.

### R1 — escape the three Unicode line separators

`_escape_text` (the `TEXT_ESCAPES` constant plus the per-character loop) gains one branch.
The escaped set becomes exactly a superset of `str.splitlines()`'s boundary set.

- Wire form: `\u0085`, `\u2028`, `\u2029` — a backslash, a literal `u`, four lowercase hex
  digits. Per D1.
- The branch sits **after** the existing named-escape lookup and the C0/DEL test, so no
  existing rendering moves. `\\` stays doubled, which is what keeps the new escape
  unambiguously decodable alongside the existing `\xNN` form.
- The docstring is updated to say the escape set covers every character
  `str.splitlines()` treats as a boundary, and to name the verification (Python 3.13.12).
  Issue #21's D25 is amended in prose, not re-litigated.
- `format_json` and `_decode` are untouched. Surrogate-escaped bytes remain unescaped for
  the reason issue #21's D25 gives: `_emit` writes them back verbatim and none can end a
  line.

**The test.** Classifier layer, alongside the existing
`test_every_control_byte_in_a_path_is_escaped_in_text_output`:

- `test_unicode_line_separators_in_a_path_are_escaped_in_text_output` — scope a single row
  `"we\u2028ird.txt".encode()`, assert `format_text(result).splitlines()` has length 3 and
  that line 3 is `"  1  we\\u2028ird.txt"`. Subtests cover `\x85` and `\u2029` the same way.
  At base this yields four lines and fails on both assertions.
- CLI layer, on the shared fixture repo: `build_fixture_repo` gains one more head-side file
  whose name embeds U+2028 (`"ls\u2028path.txt".encode("utf-8")` — APFS accepts it; unlike
  the invalid-UTF-8 case issue #21's D19 had to keep at the classifier layer, this one
  creates cleanly — verified end to end on this host: APFS accepts the name, git stores it as
  `we\342\200\250ird.txt`, and `git diff --numstat -z -M` emits the raw bytes
  `we\xe2\x80\xa8ird.txt` verbatim). The fixture's row count moves from eleven to twelve and
  its product file count from seven to eight, so `DiffScopeCommandTest`'s class docstring
  ("eleven rows") and the existing counted assertions in
  `test_product_totals_exclude_every_class` (`5 lines, 7 files` → `6 lines, 8 files`),
  `test_every_row_git_emitted_is_accounted_for_exactly_once`,
  `test_an_artifact_path_matching_nothing_is_not_an_error`,
  `test_text_format_reports_the_same_totals` and
  `test_text_format_gives_each_ranked_file_exactly_one_line` are updated in the same commit.
  The last of those becomes the end-to-end proof: `len(text.splitlines()) == 2 + 8`, which at
  base is 10.

### R2 — neutralise `diff.relative`

Both `git diff` invocations in `measure` — the `--numstat` read and the `--name-status` read
— gain `--no-relative`, positioned with the other diff options next to `-M`. Per D2.

Verified on git 2.51.2 that `git diff --numstat -z -M --no-relative <range>` and
`git diff --name-status -z -M --no-relative <range>` both restore repository-root-relative
paths under `diff.relative=true` from a subdirectory. No other call site needs it:
`rev-parse` and `cat-file --batch` do not consult `diff.relative`, and `cat-file` addresses
content by `<oid>:<path>` in the root frame regardless of cwd.

**The test.** A new CLI-layer class `DiffScopeRelativeConfigTest` with its own
`TemporaryDirectory`, built by the existing `build_fixture_repo` and then
`git config diff.relative true`. Both measurements come from **that one repository**, and
differ only in `--root`:

- baseline: `--root <repo>` — at the work-tree root, `diff.relative=true` is a no-op, so this
  *is* the unconfigured answer AC2 names, without needing a second fixture to prove it;
- subject: `--root <repo>/src` (created by `build_fixture_repo`, and inside the work tree, so
  `_validate_root` passes).

Assert the two JSON payloads are equal in full — `product`, `excluded` and the whole `files`
list. Comparing whole payloads rather than totals is deliberate: the skew's first symptom is
in the path strings (`app.py` for `src/app.py`), and a totals-only assertion can stay green
while every path is wrong. At base the subject payload either reports stripped paths or exits
1 on the `no --name-status row for ...` join — either way the assertion reddens.

One fixture rather than two is the point: it isolates the single variable under test (cwd
depth) and removes any question of whether two separately-built scratch repos are comparable.

### R3 — cover the header-scan early return

No product change. Two tests, because the branch has two separable claims — "returns an
empty mapping" and "spawns no subprocess". Per D5.

- **CLI layer.** New class `DiffScopeAllExcludedRangeTest` with its own second scratch repo,
  built by a new module-level `build_no_candidate_repo(root)`: a base commit, then a head
  commit whose every row is a binary or a lockfile — a changed `assets/blob.bin` carrying NUL
  bytes, and a changed `pnpm-lock.yaml`.

  Note the shape this fixture must have, because it is easy to get wrong: a binary row is
  **product** by issue #21's D5, and it is skipped by `read_headers` for being binary, not for
  being excluded. So the correct assertions are exit 0,
  `product == {"changed_lines": 0, "changed_files": 1}`,
  `excluded == {"lockfile": 1, "generated": 0, "artifact": 0}`, and a single ranked entry
  `{"path": "assets/blob.bin", "changed_lines": 0, "binary": true}`. That is precisely the
  state the early return exists for: the range produced rows, none of them was a content
  candidate, and the measurement still came out. A fixture asserting `files == []` would be
  describing a different (and unreachable) range.
- **Direct.** Classifier layer,
  `test_read_headers_returns_without_spawning_git`: build two synthetic `DiffRow`s (one
  binary, one `pnpm-lock.yaml`) plus a matching statuses mapping, wrap the call in
  `unittest.mock.patch.object(module, "_git", side_effect=AssertionError("cat-file must not run"))`,
  and assert `read_headers(Path("/nonexistent"), "b", "h", rows, statuses) == {}`. The patch is
  what makes "no subprocess" an assertion rather than an inference; `unittest.mock` is stdlib
  and is added to the suite's imports.

### R4 — bound the header scan's buffering

This is the only structural change. `_git`'s `subprocess.run(stdout=PIPE)` cannot bound what
it reads, so the `cat-file --batch -z` call stops going through `_git` and gets a dedicated
**lockstep streaming reader**. Per D3.

`_parse_batch(payload: bytes, expected: int)` is replaced by a function that owns the
subprocess and consumes it one request at a time:

```
_batch_headers(root, requests) -> list[bytes]
    open  git cat-file --batch -z  via subprocess.Popen,
          stdin=PIPE, stdout=PIPE, stderr=<tempfile.TemporaryFile>
    for each request:
        write the one request, flush
        read the response header line
        validate it exactly as _parse_batch does today (D23 preserved verbatim)
        keep = min(size, HEADER_SCAN_BYTES) if type == b"blob" else 0
        window = read exactly `keep` bytes
        discard the remaining `size - keep` bytes in fixed 64 KiB chunks
        read exactly the 1-byte response terminator
    finally: close stdin (ignoring BrokenPipeError), close stdout, wait()
    on a clean loop, a non-zero return code raises DiffScopeError carrying stderr text
```

The `finally` closes **stdout before waiting**, in that order, on purpose: on the error path
git may be blocked mid-write, and closing our read end is what gives it EPIPE and lets
`wait()` return instead of hanging. On the success path git has already written everything
and is blocked reading stdin, so closing stdin ends it with status 0. A `BrokenPipeError`
from writing a request — git died early, e.g. on a malformed object id — is caught and
raised as `DiffScopeError` carrying the stderr text, so a dead subprocess still produces the
`diff-scope: ...` diagnostic every CLI error test asserts on rather than a traceback.

Four properties this is chosen for:

- **Deadlock-freedom is structural, not mitigated.** The hazard in the naive streaming
  rewrite is writing every request while git blocks writing stdout. Lockstep removes it by
  construction: a request is written only after the previous response — including its
  terminator — has been fully consumed, at which point git is blocked in `read()` on stdin
  and its stdout pipe is empty. One request is an object id plus a path plus a NUL, orders of
  magnitude below the 64 KiB pipe capacity, so the write cannot block either. **No writer
  thread, no thread at all**, which is what keeps the concurrency surface of this change at
  zero despite the full-lane classification.
- **stderr goes to a `tempfile.TemporaryFile`, never a third pipe.** Reading a stderr pipe
  without a thread is the *other* classic deadlock in this shape; a file has no capacity
  limit. It is read back after `wait()`.
- **Issue #21's D7 survives.** Still exactly one `cat-file` subprocess for the whole range —
  the latency argument D7 rests on is about process spawns, and lockstep changes only the
  pipe protocol inside that one process.
- **Issue #21's D23 survives.** The header validation — `endswith(b" missing")`, the
  three-part `rsplit`, the `int()` guard, all raising `DiffScopeError` — moves across
  unchanged, and the header line is now read by `readline()` on the stream, which is the same
  "stop at the first newline" behaviour the D23 comment already reasons about. That comment
  is carried over.

`read_headers`'s early return and request-building are unchanged; only its final two lines
change to call `_batch_headers(root, requests)`.

Prototyped on git 2.51.2 against a 4.5 MiB blob: correct windows (8192 / 4 / 5 bytes),
**peak traced allocation 177.8 KiB**, clean exit, no hang.

**The test seam — how the bound is observed.** `tracemalloc` around an in-process call to
`measure()`. Per D4.

New CLI-adjacent class `DiffScopeHeaderScanBoundTest`, own `TemporaryDirectory`, built by a
new `build_large_blob_repo(root)`: a base commit with a small seed file, then a head commit
adding a ≥ 4 MiB plain-text file with no generated marker (so it is a genuine content
candidate) plus one small sibling. The test imports the module through the existing
`load_module()` and calls `module.measure(root, base, head, ())` **in process**, wrapped in
`tracemalloc.start()` / `get_traced_memory()` / `stop()`, then asserts:

- the measurement is right — the large file is product, so the ranked list carries it and the
  totals include its churn (guards against passing by simply not reading anything);
- `peak < 1 * 1024 * 1024`.

Falsifiability at base is measured, not asserted: capturing an 8 MiB payload through
`subprocess.run(stdout=PIPE)` was observed at an 8.05 MiB `tracemalloc` peak, so the base
implementation exceeds the 1 MiB bound by roughly 4× on a 4 MiB fixture while the streaming
implementation sits ~24× under it. The margin is wide enough on both sides that the
threshold is not a tuning knob.

Rejected seams are recorded in D4: a fake-stream injection point asserts only that the *new*
code exists (it fails at base with `AttributeError`, which is coverage of an API, not of a
bound), and a per-row `git cat-file blob` with an early `close()` would be the only way to
bound *bytes crossing the pipe* rather than bytes retained — at the cost of one subprocess
per row, which reverses issue #21's D7.

### R5 — scrub the inherited git environment

`git_env()` gains a scrub of the environment variables that redirect git at another
repository, applied to the copied environment before the hermetic overrides are set. Per D7.

A module-level constant lists them, with a comment naming the criterion (variables that
relocate git's repository, work tree, index or object store):

```
GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
GIT_ALTERNATE_OBJECT_DIRECTORIES, GIT_COMMON_DIR, GIT_NAMESPACE
```

Each is `pop`ped with a default, so an absent variable is not an error. This covers both the
scratch-repo `git()` helper and `run_helper`, which already share `git_env()` — the single
choke point is why this is a five-line change.

**The test.** `test_the_suite_git_environment_is_immune_to_an_inherited_git_dir` on the
existing `DiffScopeCommandTest`: under
`unittest.mock.patch.dict(os.environ, {"GIT_DIR": "/nonexistent/other.git", "GIT_WORK_TREE": "/nonexistent/tree", "GIT_INDEX_FILE": "/nonexistent/index"})`,
assert that `git_env()` contains none of the three keys, and — the part that proves it
end-to-end — run the standard measurement through `run_helper` and assert the payload equals
the unpolluted baseline. At base the helper's own `git diff` resolves against
`/nonexistent/other.git` and exits 1, so the assertion on `returncode == 0` reddens first.

## Test seams

Both seams already exist and are inherited from issue #21's design; this slice adds no new
seam and no new harness.

- **Classifier layer** of `home/common/agent-skills/tests/test_diff_scope.py` — the module
  loaded through `load_module()` (issue #21's D20 `sys.modules` registration is load-bearing
  and untouched). Carries R1's escape assertions, R3's no-subprocess assertion, and R4's
  `tracemalloc` measurement (in-process, which is the only reason a memory bound is
  observable at all).
- **CLI layer** — `subprocess.run([sys.executable, SCRIPT, ...])` against scratch
  repositories under `tempfile.TemporaryDirectory`. Carries R1's end-to-end line count, R2,
  R3's all-excluded range, and R5.

New fixtures follow the existing precedent exactly — a module-level `build_*_repo(root)`
function plus a `unittest.TestCase` class owning its own `TemporaryDirectory` in
`setUpClass`/`tearDownClass`, driving git through `subprocess.run` **argv lists** per issue
#21's D18. The shared `build_fixture_repo` repository stays immutable across tests; no test
mutates another test's fixture config. Per D6.

## Out of scope

- **`normalize_artifact_path(".//x")` returning `b"/x"`.** Issue #21's review deferred this
  as a sixth residual; issue 31 names neither a bullet nor an acceptance criterion for it,
  and issue 32 covers spec/skill doc drift only. Per D8 — it is left open deliberately, not
  by oversight, and must be surfaced as a discussion item rather than silently dropped. The
  behaviour is conservative: the leading-slash rejection runs before the `./`-strip loop, so
  `.//x` normalises to a value no git path can match, which over-counts and never
  under-counts. Issue #21's D8 already establishes over-counting as the acceptable failure
  direction for this flag.
- **Any skill prose or consumer change.** Nothing binds `diff-scope` yet — issue #21's
  D14/D17 stand unchanged, and this slice does not create the first caller.
- **The JSON output contract.** Issue #21's D11 fixes it byte-for-byte; R1 touches only the
  text branch, and R2/R4 must leave the JSON bytes for any given range identical.
- **New exclusion classes, thresholds, verdicts, or any exit status meaning "too big."**
  Issue #21's D9.
- **`home/common/agent-skills/default.nix` and `justfile`.** Both already register the helper
  and the suite; issue #21's D15 registered `test_diff_scope.py` in
  `just agent-workflow-tests`.
- **Three-dot ranges, working-tree diffs, and the stdin-numstat mode** — issue #21's D2, D10.
- **Any `patchRevision` bump.** Nothing in `patches/agent-plugins/` is touched.

## Decision ledger

This ledger opens its own `D1…` numbering. Rows citing issue #21's ledger name that issue
explicitly.

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Escape U+0085, U+2028 and U+2029 in `--format text` as `\u0085` / `\u2028` / `\u2029` — backslash, literal `u`, four lowercase hex digits — leaving `--format json` and surrogate-escaped bytes exactly as they are | Verified on Python 3.13.12 that `str.splitlines()` boundaries are exactly `\n \v \f \r \x1c \x1d \x1e \x85 \u2028 \u2029`; the first seven are C0 and already covered, so these three close the set and make issue #21's D25 invariant ("one ranked file, one physical line") true for a Unicode-aware consumer. Four hex digits keep the new form textually disjoint from the existing two-digit `\xNN`, so a decoder can never read `\u0085` as `\x00` followed by `85` | `\x85` for U+0085 — same two-digit shape as the C0 escapes, so a byte-oriented decoder reproduces the raw byte `0x85`, which is not valid UTF-8 on its own; escaping every non-ASCII character — changes how every ordinary international path renders, for one hazard; a general `unicodedata.category(c) in {"Zl","Zp","Cf"}` sweep — a moving target across Python releases, and it escapes characters that cannot break a line |
| D2 | Neutralise `diff.relative` by adding `--no-relative` to both `git diff` calls in `measure`, beside the existing `-M` | Mirrors issue #21's D3, which passes `-M` as a diff option for the identical reason (the measurement must not depend on caller config), so the two neutralisations read as one pattern at one site. Verified on git 2.51.2 that `--no-relative` is accepted by both `--numstat` and `--name-status` and restores the root-relative frame issue #21's D8 requires. `_git` builds `["git", *arguments]`, so the `-c` form would have to be threaded in front of every subcommand — a change to `_git`'s signature for two call sites | `-c diff.relative=false` before the subcommand — needs a new `_git` parameter and applies the neutralisation at a site that cannot see which subcommand it is neutralising; setting it only on `--numstat` — the name-status join in `read_headers` skews independently and raises `no --name-status row for ...`; documenting "run diff-scope from the repository root" — turns a silent miscount into an unenforced convention |
| D3 | Replace the buffered `cat-file --batch -z` call with a dedicated **lockstep** streaming reader: `Popen`, one request written and flushed only after the previous response is fully consumed, window clipped to `HEADER_SCAN_BYTES`, remainder discarded in fixed 64 KiB chunks, stderr to a `tempfile.TemporaryFile` | Deadlock-freedom becomes structural rather than mitigated: git is provably blocked reading stdin whenever we write, and a single request is orders of magnitude under the 64 KiB pipe capacity, so **no writer thread is needed** and the concurrency surface of a full-lane change stays at zero. stderr to a file removes the second, less obvious pipe deadlock. Issue #21's D7 (one subprocess per range, for review-dispatch latency) and D23 (fail-loud header validation) both survive verbatim. Prototyped on git 2.51.2: 4.5 MiB blob, correct 8192/4/5-byte windows, 177.8 KiB peak, clean exit | A writer thread feeding all requests while a reader drains stdout — the textbook fix, but it buys nothing lockstep does not and introduces threading into a helper that has none; `--batch-command` — same buffering, same problem; one `git cat-file blob` per row with an early `close()` — the only form that bounds bytes *crossing* the pipe rather than bytes retained, at N subprocesses, reversing issue #21's D7 on the latency path it was chosen for; leaving `subprocess.run` and clipping later — the status quo AC4 rejects |
| D4 | Make the memory bound observable with `tracemalloc` around an **in-process** `measure()` call over a ≥ 4 MiB single-blob fixture, asserting `peak < 1 MiB` alongside an assertion that the large file was still measured correctly | This is the only seam that fails at the base commit for the *right reason* — the bound itself — rather than because a new symbol is absent. Measured both sides before choosing: `subprocess.run(stdout=PIPE)` over 8 MiB peaks at 8.05 MiB, the lockstep reader over 4.5 MiB peaks at 177.8 KiB, so the threshold sits ~4× under base and ~24× over head and is not a tuning knob. In-process is mandatory — `tracemalloc` cannot see across a subprocess boundary — which is why this test uses `load_module()` rather than `run_helper` | A fake-stream seam injected into the reader with a recorded max read size — asserts that the new API exists (`AttributeError` at base), not that anything is bounded; asserting peak RSS via `resource.getrusage` — process-wide, high water mark never falls, and confounded by the interpreter's own allocations; timing or `/usr/bin/time` — flaky on a shared runner; no test at all, "the code obviously reads less" — leaves AC4 unfalsifiable |
| D5 | Cover the `read_headers` early return **twice**: a CLI-layer all-excluded scratch repo, and a classifier-layer `unittest.mock.patch.object(module, "_git", side_effect=AssertionError)` assertion that the branch returns `{}` without spawning anything | The branch makes two separable claims and the issue's AC names the subprocess one ("the no-subprocess early return"). The CLI test proves the range really produces rows and still measures; only the patched-`_git` test proves no subprocess ran, which no end-to-end assertion can observe. `unittest.mock` is stdlib, so this adds no dependency | CLI test only — cannot distinguish "returned early" from "spawned `cat-file` and got nothing useful", so the AC's actual claim stays untested; patched test only — the issue explicitly asks for the CLI-layer second scratch repo; asserting on a process count via `psutil` — a new dependency for a fact a stdlib patch already yields |
| D6 | Every new fixture is a new module-level `build_*_repo(root)` plus its own `unittest.TestCase` class owning a `TemporaryDirectory`; the shared `build_fixture_repo` repository is never mutated by a test, and R1's U+2028 path is added to that shared fixture with the affected count assertions updated in the same commit | Reading the suite, this is its only fixture idiom — one builder function, one class, `setUpClass`/`tearDownClass`. Mutating the shared repo's config for R2 would make the suite order-dependent across `setUpClass`-shared state, the failure mode that is hardest to diagnose later. R1's separator path belongs in the shared fixture instead, because it is a *row shape* the standard range should carry — same reasoning that put the newline and double-quote paths there under issue #21's D19 | A lazily-built fixture hung off `DiffScopeCommandTest` — shares mutable state across tests for no saving; one mega-fixture serving all five residuals — the all-excluded repo must have no content candidates while the memory repo must have a large one, which are contradictory requirements; parameterising `build_fixture_repo` with flags — a fixture builder with modes is harder to read than three small builders |
| D7 | Scrub a named set of *repository-location* git variables in `git_env()` — `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_COMMON_DIR`, `GIT_NAMESPACE` — rather than the three the issue names or a blanket `GIT_*` sweep | The criterion, not the enumeration, is what makes this correct: any variable that relocates git's repository, work tree, index or object store poisons a scratch repo identically, and the four beyond the issue's three cost nothing and cannot misfire, since a hermetic scratch repo needs none of them. A blanket `GIT_*` sweep would also drop `GIT_EXEC_PATH` and `GIT_TEMPLATE_DIR`, which a Nix-provided git may legitimately rely on — turning a hygiene fix into a portability risk. `CLAUDE.md` already documents the same class of session-env poisoning for the `codex-plugin-cc` suite | Exactly the three named in the issue — leaves siblings that break the suite the same way; a blanket `GIT_*` scrub — risks removing variables the toolchain needs; `env -i` / an allowlist-only environment — loses `PATH` and `HOME`, so `sys.executable` and git itself stop resolving |
| D8 | Leave `normalize_artifact_path(".//x")` → `b"/x"` **out of scope**, recorded in `## Out of scope` and surfaced as a discussion item | Issue 31 names five residuals in its bullets and five acceptance criteria, and this is neither; issue 32 covers doc drift only, so nothing else claims it. Its failure direction is conservative — the value matches no git path, which over-counts and never under-counts — and issue #21's D8 already establishes over-counting as this flag's acceptable failure mode, so it is not urgent. Fixing it would also be a (tiny) change to a documented input contract, which is exactly what this slice promised not to touch | Fix it here as a one-line reorder of the leading-slash check and the `./`-strip loop — cheap, but widens a slice whose whole justification is "the parking lot the review defined", and adds an unlisted contract change to a full-lane branch; open it as a new issue now — premature before the parent has surfaced it; drop it silently — the failure this out-of-scope row exists to prevent |
| D9 | Run R4's in-process `measure()` inside `unittest.mock.patch.dict(os.environ, git_env(), clear=True)`, and land R5 before R4 so that scrub already exists | R4's seam is the only test that calls the helper *in process* (D4), so its git subprocesses inherit `os.environ` directly and never pass through `git_env()` — the single choke point D7 scrubs. Without this wrapper R5's own acceptance criterion ("the whole suite passes with `GIT_DIR` set in the invoking environment") would be falsified by the test R4 adds: the two residuals would silently conflict. Reusing `git_env()` keeps one definition of "hermetic" across both seams | Leaving the in-process call on the raw environment — reddens `GIT_DIR=… just agent-workflow-tests`, which is the R5 AC's literal wording; scrubbing `os.environ` once in a `setUpModule` — hides the poison from R5's own test, which must observe an inherited `GIT_DIR` to prove the scrub works; a second, test-local copy of the scrub list — two enumerations of D7's set, free to drift apart |
| D10 | Task 1's `git_env()` scrub also lands in `home/common/agent-skills/tests/test_ship_release_contracts.py`, as a duplicated `GIT_LOCATION_VARS` tuple + pop loop rather than a shared import | Phase-5 standards review (native reviewer, base `b59ff22`), verified live: that file defines its **own** unscrubbed `git_env()` and its `sh()` helper runs real `git init`/`git commit`, so `GIT_DIR=/nonexistent/other.git python3 .../test_ship_release_contracts.py` reddens 2 of 10 tests with `fatal: Invalid path '/nonexistent'`. It is in the `just agent-workflow-tests` recipe (`justfile:57-65`), and R5's acceptance criterion is that **the suite** passes under a poisoned environment — so the original "test changes only in `test_diff_scope.py`" constraint made that AC unreachable. No other suite in the recipe spawns git, so the widening stops there | Extracting a shared test-helper module — this plan adds no new file and the two suites share no helper today, so a new import surface costs more than seven duplicated lines; leaving it unscrubbed and narrowing the AC to `test_diff_scope.py` alone — rewrites the issue's acceptance criterion to match the plan instead of the reverse |
| D11 | Task 5 extends Task 4's `test_read_headers_returns_without_spawning_git` to patch **`_batch_headers`** as well as `_git`, and re-runs Task 4's Mutation A as part of Task 5's own gate | Phase-5 standards review. Task 4's assertion proves "no subprocess" by patching `_git`, which only works while `read_headers` reaches `cat-file` *through* `_git`. Task 5 replaces that call with `_batch_headers`, which opens its own `subprocess.Popen`; after T5, deleting the early return would let `_batch_headers(root, [])` spawn `cat-file` with zero requests, exit 0, return `[]`, and `dict(zip([], []))` is still `{}` — so the test would stay green over a real regression and D5's only load-bearing assertion would go hollow, invisibly, because Mutation A is otherwise run only at Task 4 time | Leaving the `_git`-only patch — ships a test that asserts nothing; deleting the test at T5 as superseded — drops AC3's coverage entirely; asserting on process tables instead — slow, racy, and platform-specific |
| D12 | Every decision citation this issue writes into source (comments, docstrings) names its document — `issue #21's D3`, `issue 31's D2` — while the existing bare citations are left untouched | Phase-5 standards review. `diff-scope.py` cites issue #21's ledger bare throughout (`(D25)` :146/:195, `(D8)` :269, `(D23)` :364, `(D7)` :374, `(D3)` :437, `(D19)` :467), so a bare new `(D2)` for **this** issue's D2 would read as issue #21's D2 ("three-dot ranges out of scope") — a different decision entirely. This matches the rule the plan already states for its own prose | Renumbering this issue's ledger to start past D25 — couples two independent documents forever; rewriting the existing bare citations to be qualified — churns lines this issue has no other reason to touch, inflating a contract-bearing diff |

## Verification

From the worktree root:

```sh
just agent-workflow-tests
```

The recipe (`justfile:59`) already registers
`home/common/agent-skills/tests/test_diff_scope.py`, so no wiring changes. Every new test
named above must be green, and the pre-existing tests in both suites must stay green — with
the five count assertions listed under R1 updated for the twelfth fixture row.

`just build` is **not** required: no `.nix` file is edited. The helper's Nix wiring seam from
issue #21's design is unaffected because neither the installed path nor the file's
executability changes.

Two checks worth running once by hand during implementation, since both underpin an AC and
neither is expressible as a repository test:

```sh
# R5 — the AC's literal wording: the suite survives a poisoned invoking environment
GIT_DIR=/nonexistent/other.git just agent-workflow-tests

# R4 — confirm the base-commit failure is real before the fix lands
git stash && python3 -m unittest ... DiffScopeHeaderScanBoundTest   # expected: fail
```
