# diff-scope Helper Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/21
Spec: `.claude/specs/2026-08-16-diff-scope-helper-design.md` (the decision ledger there is
the source of truth; this plan cites rows by ID and never restates them)

**Goal:** Extract "how big is this change, in product terms?" out of hand-executed skill
prose into one tested executable, `diff-scope`, on `~/.agents/bin`.

**Architecture:** A stdlib-only Python 3 script split into a **pure core** (a `DiffRow`
value type, a three-class classifier, a churn ranking, two output formatters) and a **git
layer** (three subprocesses: `diff --numstat -z -M`, `diff --name-status -z -M`, and one
batched `cat-file --batch -z` for the rows whose generated-header status needs blob
content). The seam between them is what lets every exclusion class be tested without a
scratch repository, per the spec's "Internal shape" section. Nix installs the script at
`~/.agents/bin/diff-scope`; `home.sessionPath` already carries that directory.

**Tech stack:** Python 3 standard library only (`argparse`, `dataclasses`, `json`,
`pathlib`, `subprocess`, `sys`), `unittest`, Nix / home-manager (`home.file`), `just`.
`pkgs.python3` is already declared in `home/common/agent-skills/default.nix`.

**This is a prefactoring.** It ships the helper, its tests and its wiring, and changes the
behaviour of no skill. Nothing calls `diff-scope` when this branch lands — deliberately,
per D14.

## Global Constraints

- **Stdlib only.** No third-party imports. `stacks/python.md`: "The environment is
  declared, never installed ad hoc"; the module already declares `pkgs.python3`.
- **House style**, matching `scripts/{agent-evidence,agent-model-matrix,workflow-state}.py`:
  `#!/usr/bin/env python3`, `from __future__ import annotations`, frozen dataclasses,
  `def main(argv: list[str] | None = None) -> int`, `raise SystemExit(main())`,
  diagnostics to `stderr`, machine output via
  `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
- **No prose change ships in this slice** — no skill edit, no README, no `CLAUDE.md` line.
  Per D17. The branch touches exactly four files.
- **No `patchRevision` bump**; nothing under `patches/agent-plugins/` is touched.
- **Never disable GPG signing.** No `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface
  a signing failure rather than working around it. (`git log --show-signature` printing
  "No signature" here is a pre-existing *verification* gap — `gpg.ssh.allowedSignersFile`
  is unset — not a signing failure. Do not "fix" it.)
- **Commit trailer**, on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- **Verification** is `just build` (there is no lint suite) plus
  `just agent-workflow-tests`. Never run `just switch` or any activation.
- **Payload discipline.** Summarise test and build output to the failing lines; never
  paste a whole run into a report.

### CLI contract (fixed by the spec — do not renegotiate)

```
diff-scope <base>..<head> [--root PATH] [--artifact-path PATH]... [--format json|text]
```

Exit `0` whenever a measurement was produced — an empty range and an all-excluded range
are both valid measurements of zero. Exit `1` when no measurement could be made. Exit `2`
is argparse's own usage error. There is no exit status meaning "this change is large"
(D9).

Default JSON payload, one compact object plus one trailing newline:

```json
{"range":"<base>..<head>",
 "product":{"changed_lines":412,"changed_files":13},
 "files":[{"path":"<repo-relative>","changed_lines":214,"binary":false}],
 "excluded":{"lockfile":2,"generated":1,"artifact":5}}
```

`excluded` always carries all three keys, zero when a class matched nothing, so
`len(files) + sum(excluded.values())` equals the number of rows git emitted.

## Test seams

Both seams already exist; no new seam is invented, and an implementer that needs one has
found a plan bug rather than a licence.

1. **`home/common/agent-skills/tests/test_diff_scope.py`**, stdlib `unittest`, two layers
   following `test_agent_model_matrix.py` verbatim:
   - **Classifier layer** — `importlib.util.spec_from_file_location` loads
     `scripts/diff-scope.py`; tests drive the pure classifier over synthetic rows. Every
     exclusion class, the ranking tie-break, the all-excluded case, the carve-out, the
     single-class counting order and both output formats live here. The loader **must**
     register the module in `sys.modules` before `exec_module` — one line more than
     `test_agent_model_matrix.py`'s version, and the difference between a working suite and
     every test erroring in `setUpClass` (D20).
   - **CLI layer** — `subprocess.run([sys.executable, SCRIPT, ...])` against a scratch git
     repository under a `TemporaryDirectory`. Covers only what the classifier layer
     structurally cannot: real `-z` parsing, a real rename, a real binary row, a real
     base-side content read for a *deleted* generated file, paths holding a newline and a
     double quote, the sum invariant against git's own row count, the exit-1 paths, and
     byte-identical stdout across two runs.
2. **`just build` plus a `home-files` store-path check** — the Nix wiring seam, described
   in Task 3. Non-destructive: it builds an attribute and inspects the store path, and
   never activates.

Deliberately **not** a seam: a skill eval. `diff-scope` is not a skill and no skill
references it in this slice.

## Task index

| Task | Title | Files touched | Risk lane |
|------|-------|---------------|-----------|
| 1 | Pure accounting core — rows, classifier, ranking, formatters | `home/common/agent-skills/scripts/diff-scope.py` (create), `home/common/agent-skills/tests/test_diff_scope.py` (create) | **full** |
| 2 | Git layer and CLI | `home/common/agent-skills/scripts/diff-scope.py` (modify), `home/common/agent-skills/tests/test_diff_scope.py` (modify) | **full** |
| 3 | Install the helper and register the suites | `home/common/agent-skills/default.nix` (modify), `justfile` (modify) | **low-risk** |

**Lane rationale.** Tasks 1 and 2 are `full`: together they define a new public CLI
contract that two skills will bind to, introduce new behaviour, and establish the test
seam — none of which is mechanical or locally bounded. Task 3 is `low-risk`: it is a
four-line application of the established `home.file` + `executable = true` pattern and a
test-runner list edit, both bounded and both verified by a deterministic build gate, and
it touches nothing on the low-risk exclusion list (no concurrency, lifecycle, destructive
operation, security, release, migration, and no contract decision of its own — the
contract was settled in Tasks 1 and 2).

## Decisions

The spec owns the single decision ledger. This plan adds no decisions of its own beyond
three rows appended to that ledger during planning:

- **D17** — ship no prose change at all; the slice is exactly four files. Resolves the
  "whatever doc line the repo's conventions require" question to *none*.
- **D18** — `test_diff_scope.py` carries its own hermetic `git_env()` and drives git
  through `subprocess.run` **argv lists**, never a `bash -c` command string; no shared
  test-helper module is extracted.
- **D19** — write both output formats as bytes through `sys.stdout.buffer` with
  `errors="surrogateescape"`; assert the non-UTF-8 path at the classifier layer only.
- **D20** — `load_module()` registers the module in `sys.modules` before `exec_module`,
  departing from `test_agent_model_matrix.py`'s loader by one required line.

Tasks cite ledger rows inline. Read the ledger before starting any task.

### Verified facts every task may rely on

These were probed against **git 2.51.2** and **Python 3.13.12** on this host during
planning. They are stated here so no task re-derives them:

- `git diff --numstat -z -M` emits one NUL-terminated record per row. A normal record is
  `<add>\t<del>\t<path>`; a **rename** record is `<add>\t<del>\t` with an empty third
  field, followed by two further NUL-terminated tokens, `<old>` then `<new>`; a **binary**
  record is `-\t-\t<path>`. Path bytes are verbatim — no C-quoting, no brace form.
- `git diff --name-status -z -M` emits `<status>\0<path>\0`, and `R100\0<old>\0<new>\0`
  for a rename.
- `git cat-file --batch` **without** `-z` splits a newline-containing path into two bogus
  `missing` requests; `--batch -z` returns the correct blob. `-z` changes only the
  *input* framing: the output stays `<oid> <type> <size>\n<size bytes>\n`, and a missing
  object is `<echoed request> missing\n`.
- numstat paths are **repository-root-relative** even when git runs in a subdirectory.
- Reading a deleted file's base-side content as `<base-rev>:<path>` works and is how the
  deleted-generated-file case is covered.
- APFS **refuses** to create a filename containing invalid UTF-8 (`OSError` errno 92);
  newline and double-quote filenames create cleanly. Hence D19.
- `print()` of a surrogateescape-decoded path raises `UnicodeEncodeError`;
  `json.dumps(..., ensure_ascii=True)` renders it safely as a `\udcff` escape. Hence D19.
- A module loaded by `spec_from_file_location` **and left out of `sys.modules`** raises
  `AttributeError: 'NoneType' object has no attribute '__dict__'` from `dataclasses._is_type`
  for *any* dataclass field, because `from __future__ import annotations` makes annotations
  strings that `dataclasses` resolves via `sys.modules[cls.__module__]`. Hence D20.
- `just agent-workflow-tests` at the base commit: **Ran 70 tests, OK**.
  `test_agent_evidence.py` + `test_agent_model_matrix.py` run together: **42 tests, OK**
  (confirms D15 is safe to act on).
- The build gate is falsifiable at the base commit: the `home-files` store path contains
  `.agents/bin/{agent-evidence,agent-model-matrix,context-map-lint,resolve-bindings,workflow-state}`
  and **no** `diff-scope`.

---

### Task 1: Pure accounting core

The classifier, the ranking and the output formatters, with no git and no CLI. This task
delivers an **importable module**, not yet an executable: the shebang, `main` and the git
layer all arrive in Task 2, so nothing half-wired is committed here and the file is not
made executable until Task 3.

**Files:**
- Create: `home/common/agent-skills/scripts/diff-scope.py`
- Create (test): `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all at module scope, for Task 2 and the test suite:
  - `EXCLUSION_CLASSES: tuple[str, ...]` = `("lockfile", "generated", "artifact")` — the
    fixed classification order of D11.
  - `LOCKFILE_NAMES: frozenset[bytes]`, `LOCKFILE_SUFFIX: bytes`,
    `GENERATED_MARKERS: tuple[bytes, ...]`, `HEADER_SCAN_LINES: int` = 5,
    `HEADER_SCAN_BYTES: int` = 8192.
  - `class DiffRow` — frozen dataclass with fields
    `path: bytes`, `additions: int | None`, `deletions: int | None`,
    `header: bytes | None = None`; properties `binary: bool` and `churn: int`.
  - `class ScopeResult` — frozen dataclass with fields `files: tuple[DiffRow, ...]` and
    `excluded: dict[str, int]`; properties `changed_lines: int` and `changed_files: int`.
  - `def classify_row(row: DiffRow, artifact_paths: Sequence[bytes]) -> str | None`
  - `def scope_rows(rows: Iterable[DiffRow], artifact_paths: Sequence[bytes]) -> ScopeResult`
  - `def format_json(range_text: str, result: ScopeResult) -> str`
  - `def format_text(result: ScopeResult) -> str`
  - `def _is_lockfile(path: bytes) -> bool` — Task 2 reuses this to skip content reads.
  - `def _decode(path: bytes) -> str`

**Invariants:**
- `len(result.files) + sum(result.excluded.values()) == len(rows)` for every input.
- `result.excluded` always carries exactly the three keys of `EXCLUSION_CLASSES`, zero
  when a class matched nothing.
- Each excluded row is counted **once**, under the first class it matches in the order
  lockfile → generated → artifact (D11).
- A binary row is product: it adds one to `changed_files` and zero to `changed_lines`
  (D5), and it is never scanned for a generated header (D6).
- Ranking is `(churn descending, raw path bytes ascending)` — a total order, so the same
  rows in any input order yield the same output order (D12).
- Paths are carried as `bytes` end to end and decoded only at the output boundary, with
  `errors="surrogateescape"` (D19).
- `format_json` output is pure ASCII (`ensure_ascii=True`) and ends with exactly one
  newline.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_diff_scope.py`:

```python
"""Contracts for the diff-scope product-accounting helper.

Two layers, per the design's Test seams section. The classifier layer imports
scripts/diff-scope.py directly and drives the pure classifier over synthetic
rows shaped the way the git layer actually emits them -- a binary row carrying
absent counts rather than zeros, a rename row already reduced to its
destination path. The CLI layer (added with the git layer) runs the script as a
subprocess against scratch git repositories under a TemporaryDirectory; it
talks to no network and touches no repository but its own.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).parents[4]
SCRIPT = REPO_ROOT / "home/common/agent-skills/scripts/diff-scope.py"


def load_module():
    """Import scripts/diff-scope.py as a module.

    The sys.modules registration is required, not decorative: the script uses
    `from __future__ import annotations`, so its dataclass field annotations are
    strings, and dataclasses resolves them through sys.modules[cls.__module__].
    Without the registration every dataclass in the module raises AttributeError
    at import. test_agent_model_matrix.py omits this line only because the script
    it loads defines no dataclass.
    """
    spec = importlib.util.spec_from_file_location("diff_scope", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DiffScopeClassifierTest(unittest.TestCase):
    """The pure classifier, over rows shaped the way the git layer emits them."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def row(self, path, additions=1, deletions=1, header=None):
        return self.module.DiffRow(
            path=path, additions=additions, deletions=deletions, header=header
        )

    def scope(self, rows, artifact_paths=()):
        return self.module.scope_rows(rows, artifact_paths)

    # --- lockfile class --------------------------------------------------

    def test_lockfile_row_is_excluded_while_its_product_sibling_survives(self):
        result = self.scope(
            [self.row(b"pnpm-lock.yaml", 40, 2), self.row(b"src/app.py", 3, 1)]
        )
        self.assertEqual([row.path for row in result.files], [b"src/app.py"])
        self.assertEqual(result.changed_lines, 4)
        self.assertEqual(result.changed_files, 1)
        self.assertEqual(result.excluded["lockfile"], 1)

    def test_every_lockfile_spelling_is_recognised(self):
        for path in (
            b"pnpm-lock.yaml",
            b"package-lock.json",
            b"bun.lockb",
            b"go.sum",
            b"Cargo.lock",
            b"deep/nested/Gemfile.lock",
        ):
            with self.subTest(path=path):
                result = self.scope([self.row(path, 10, 10)])
                self.assertEqual(result.files, ())
                self.assertEqual(result.excluded["lockfile"], 1)

    def test_a_path_merely_containing_lock_is_product(self):
        result = self.scope([self.row(b"src/locking.py", 2, 0)])
        self.assertEqual([row.path for row in result.files], [b"src/locking.py"])
        self.assertEqual(result.excluded["lockfile"], 0)

    # --- generated class -------------------------------------------------

    def test_generated_row_is_excluded_while_its_product_sibling_survives(self):
        result = self.scope(
            [
                self.row(
                    b"api/types.ts",
                    90,
                    10,
                    header=b"// Code generated by protoc-gen-ts.\nexport {};\n",
                ),
                self.row(b"src/app.py", 3, 1),
            ]
        )
        self.assertEqual([row.path for row in result.files], [b"src/app.py"])
        self.assertEqual(result.changed_lines, 4)
        self.assertEqual(result.changed_files, 1)
        self.assertEqual(result.excluded["generated"], 1)

    def test_auto_generated_marker_is_recognised(self):
        result = self.scope([self.row(b"Model.cs", 5, 5, header=b"// <auto-generated>\n")])
        self.assertEqual(result.files, ())
        self.assertEqual(result.excluded["generated"], 1)

    def test_marker_below_the_fifth_line_stays_product(self):
        # ship-issue/SYNC.md carries "// Code generated by" as prose in a table.
        # A whole-file scan would classify a hand-written skill document as
        # machine-generated and silently shrink every branch that edits it.
        header = b"\n".join(
            [b"one", b"two", b"three", b"four", b"five", b"// Code generated by tool"]
        )
        result = self.scope([self.row(b"skills/ship-issue/SYNC.md", 7, 1, header=header)])
        self.assertEqual(
            [row.path for row in result.files], [b"skills/ship-issue/SYNC.md"]
        )
        self.assertEqual(result.excluded["generated"], 0)

    def test_a_binary_row_is_never_classified_as_generated(self):
        result = self.scope(
            [self.row(b"assets/logo.png", None, None, header=b"// Code generated by x")]
        )
        self.assertEqual([row.path for row in result.files], [b"assets/logo.png"])
        self.assertEqual(result.excluded["generated"], 0)

    def test_a_row_whose_header_was_not_read_is_product(self):
        result = self.scope([self.row(b"src/app.py", 2, 0, header=None)])
        self.assertEqual([row.path for row in result.files], [b"src/app.py"])
        self.assertEqual(result.excluded["generated"], 0)

    # --- artifact class and the carve-out --------------------------------

    def test_only_the_named_artifact_is_excluded(self):
        rows = [
            self.row(b".claude/specs/2026-08-16-diff-scope-helper-design.md", 120, 0),
            self.row(b".claude/specs/2026-01-01-historical-design.md", 30, 4),
            self.row(b"src/app.py", 3, 1),
        ]
        result = self.scope(
            rows, (b".claude/specs/2026-08-16-diff-scope-helper-design.md",)
        )
        self.assertEqual(
            [row.path for row in result.files],
            [b".claude/specs/2026-01-01-historical-design.md", b"src/app.py"],
        )
        self.assertEqual(result.changed_lines, 38)
        self.assertEqual(result.excluded["artifact"], 1)

    def test_without_artifact_paths_a_historical_artifact_still_counts(self):
        rows = [
            self.row(b".claude/specs/2026-08-16-diff-scope-helper-design.md", 120, 0),
            self.row(b".claude/specs/2026-01-01-historical-design.md", 30, 4),
            self.row(b"src/app.py", 3, 1),
        ]
        result = self.scope(rows)
        self.assertEqual(result.changed_files, 3)
        self.assertEqual(result.changed_lines, 158)
        self.assertEqual(result.excluded["artifact"], 0)

    def test_artifact_prefix_matches_a_directory_not_a_sibling_prefix(self):
        rows = [
            self.row(b".claude/plans/run.md", 10, 0),
            self.row(b".claude/plans-archive/old.md", 7, 0),
        ]
        result = self.scope(rows, (b".claude/plans",))
        self.assertEqual(
            [row.path for row in result.files], [b".claude/plans-archive/old.md"]
        )
        self.assertEqual(result.excluded["artifact"], 1)

    # --- ranking, sums, and the zero cases --------------------------------

    def test_ranking_is_churn_descending_with_a_raw_byte_tie_break(self):
        rows = [
            self.row(b"b.txt", 5, 5),
            self.row(b"a.txt", 5, 5),
            self.row(b"c.txt", 9, 0),
        ]
        result = self.scope(rows)
        self.assertEqual(
            [row.path for row in result.files], [b"a.txt", b"b.txt", b"c.txt"]
        )
        self.assertEqual([row.churn for row in result.files], [10, 10, 9])

    def test_ranking_does_not_depend_on_input_order(self):
        forward = [
            self.row(b"a.txt", 5, 5),
            self.row(b"b.txt", 5, 5),
            self.row(b"c.txt", 9, 0),
        ]
        reverse = list(reversed(forward))
        self.assertEqual(
            [row.path for row in self.scope(forward).files],
            [row.path for row in self.scope(reverse).files],
        )

    def test_a_binary_row_is_one_product_file_and_zero_product_lines(self):
        result = self.scope(
            [self.row(b"assets/logo.png", None, None), self.row(b"src/app.py", 3, 1)]
        )
        self.assertEqual(result.changed_files, 2)
        self.assertEqual(result.changed_lines, 4)
        binary_row = next(
            row for row in result.files if row.path == b"assets/logo.png"
        )
        self.assertTrue(binary_row.binary)
        self.assertEqual(binary_row.churn, 0)

    def test_a_pure_rename_is_a_zero_churn_row_that_is_not_binary(self):
        result = self.scope([self.row(b"pkg/new.txt", 0, 0)])
        self.assertEqual(result.files[0].churn, 0)
        self.assertFalse(result.files[0].binary)
        self.assertEqual(result.changed_files, 1)

    def test_a_range_of_only_excluded_rows_measures_zero(self):
        rows = [
            self.row(b"pnpm-lock.yaml", 40, 2),
            self.row(b"api/types.ts", 90, 10, header=b"// Code generated by protoc.\n"),
            self.row(b".claude/plans/run.md", 200, 0),
        ]
        result = self.scope(rows, (b".claude/plans/run.md",))
        self.assertEqual(result.files, ())
        self.assertEqual(result.changed_lines, 0)
        self.assertEqual(result.changed_files, 0)
        self.assertEqual(
            result.excluded, {"lockfile": 1, "generated": 1, "artifact": 1}
        )

    def test_an_empty_row_set_measures_zero(self):
        result = self.scope([])
        self.assertEqual(result.files, ())
        self.assertEqual(result.changed_lines, 0)
        self.assertEqual(result.changed_files, 0)
        self.assertEqual(
            result.excluded, {"lockfile": 0, "generated": 0, "artifact": 0}
        )

    def test_each_row_is_counted_under_exactly_one_class(self):
        # A generated file under an artifact path counts once, as generated:
        # the order is lockfile -> generated -> artifact and the first match wins.
        rows = [
            self.row(b".claude/plans/gen.md", 10, 0, header=b"<auto-generated>\n"),
            self.row(b".claude/plans/Cargo.lock", 4, 4),
            self.row(b"src/app.py", 3, 1),
        ]
        result = self.scope(rows, (b".claude/plans",))
        self.assertEqual(
            result.excluded, {"lockfile": 1, "generated": 1, "artifact": 0}
        )
        self.assertEqual(
            len(result.files) + sum(result.excluded.values()), len(rows)
        )

    # --- output formats ---------------------------------------------------

    def test_json_output_is_compact_key_sorted_and_ascii(self):
        result = self.scope(
            [self.row(b"src/app.py", 3, 1), self.row(b"assets/logo.png", None, None)]
        )
        self.assertEqual(
            self.module.format_json("base..head", result),
            '{"excluded":{"artifact":0,"generated":0,"lockfile":0},'
            '"files":[{"binary":false,"changed_lines":4,"path":"src/app.py"},'
            '{"binary":true,"changed_lines":0,"path":"assets/logo.png"}],'
            '"product":{"changed_files":2,"changed_lines":4},'
            '"range":"base..head"}\n',
        )

    def test_a_non_utf8_path_survives_json_encoding(self):
        # APFS cannot hold such a name, so this hazard is only reachable here
        # and never from the CLI layer's scratch repositories (D19).
        result = self.scope([self.row(b"src/bad-\xff.py", 2, 0)])
        payload = self.module.format_json("base..head", result)
        self.assertEqual(payload, payload.encode("ascii").decode("ascii"))
        self.assertEqual(
            json.loads(payload)["files"][0]["path"], "src/bad-\udcff.py"
        )

    def test_text_output_names_the_totals_and_ranks_the_files(self):
        result = self.scope(
            [
                self.row(b"src/app.py", 3, 1),
                self.row(b"assets/logo.png", None, None),
                self.row(b"pnpm-lock.yaml", 40, 2),
            ]
        )
        self.assertEqual(
            self.module.format_text(result),
            "product: 4 lines, 2 files\n"
            "excluded: 1 lockfile, 0 generated, 0 artifact\n"
            "  4  src/app.py\n"
            "  0  assets/logo.png (binary)\n",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -5`

Expected: every test errors in `setUpClass` — `FileNotFoundError` from
`spec.loader.exec_module`, because `scripts/diff-scope.py` does not exist. Do not proceed
until the failure is that one.

- [ ] **Step 3: Write the minimal implementation**

Create `home/common/agent-skills/scripts/diff-scope.py`. **No shebang yet** — this task
delivers an importable module; Task 2 adds the shebang together with `main`.

Module docstring: `"""Measure a git range in product terms: changed lines, changed files, churn ranking."""`

Imports: `from __future__ import annotations`, then `from collections.abc import Iterable, Sequence`, `from dataclasses import dataclass`, `import json`.

Constants, exactly:

```python
EXCLUSION_CLASSES = ("lockfile", "generated", "artifact")
LOCKFILE_SUFFIX = b".lock"
LOCKFILE_NAMES = frozenset(
    {b"package-lock.json", b"bun.lockb", b"go.sum", b"pnpm-lock.yaml"}
)
GENERATED_MARKERS = (b"<auto-generated>", b"// Code generated by")
HEADER_SCAN_LINES = 5
HEADER_SCAN_BYTES = 8192
```

`LOCKFILE_NAMES` is the `ship-issue/SYNC.md` allowlist reduced — the `**/*.lock` glob
already subsumes `Cargo.lock`, which `LOCKFILE_SUFFIX` covers. It is a constant here, not
parsed from `SYNC.md` (D13); leave `SYNC.md` untouched.

`DiffRow` — frozen dataclass. `path` is the row's **destination** path as raw bytes,
repository-root-relative: the new path on a rename and the single printed path everywhere
else, including a deletion (D4). `additions`/`deletions` are `None` on a binary row,
because git prints `-` rather than a count. Properties:

```python
    @property
    def binary(self) -> bool:
        """True when git reported no line counts for this row."""
        return self.additions is None or self.deletions is None

    @property
    def churn(self) -> int:
        """Additions plus deletions; zero for a binary row, which has no counts."""
        if self.binary:
            return 0
        return self.additions + self.deletions
```

`ScopeResult` — frozen dataclass over `files: tuple[DiffRow, ...]` (already ranked, product
only) and `excluded: dict[str, int]`, with `changed_lines` summing `row.churn` over `files`
and `changed_files` returning `len(self.files)`.

The three class predicates, each a separate function so that deleting one is a surgical
change a single test catches:

- `_is_lockfile(path)` — take the basename as `path.rpartition(b"/")[2]`; return true when
  it ends with `LOCKFILE_SUFFIX` or is in `LOCKFILE_NAMES`.
- `_is_generated(row)` — return `False` immediately when `row.binary` or `row.header` is
  falsy. Otherwise take the first `HEADER_SCAN_LINES` lines of `row.header`
  (`b"\n".join(row.header.split(b"\n")[:HEADER_SCAN_LINES])`) and return whether any
  `GENERATED_MARKERS` entry appears in that window. The line bound lives here; the 8 KiB
  byte bound is applied by the git layer in Task 2 before the header reaches this function.
- `_is_artifact(path, artifact_paths)` — return true when `path` equals a value or begins
  with that value plus `b"/"`. No filesystem access, so a deleted path classifies exactly
  like a live one (D8).

`classify_row` is the closed-set dispatch and returns the first match or `None`:

```python
def classify_row(row: DiffRow, artifact_paths: Sequence[bytes]) -> str | None:
    """Return the first exclusion class this row matches, or None when it is product.

    The order is fixed: lockfile, then generated, then artifact. First match wins,
    so each dropped row is counted exactly once.
    """
```

`scope_rows` walks the rows once, seeds `excluded` as `{name: 0 for name in EXCLUSION_CLASSES}`,
appends product rows, and returns `ScopeResult(files=_rank(product), excluded=excluded)`.

`_rank(rows)` returns `tuple(sorted(rows, key=lambda row: (-row.churn, row.path)))` — churn
descending, raw path bytes ascending (D12). Sort on the bytes, never the decoded string, so
the order is independent of locale and of how any non-UTF-8 byte decoded.

`_decode(path)` returns `path.decode("utf-8", errors="surrogateescape")`.

`format_json(range_text, result)` builds the payload in the documented shape and returns
`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"`.
`ensure_ascii=True` is load-bearing: it renders a surrogate-escaped path as a `\udcff`
escape instead of raising on the write.

`format_text(result)` returns a `product:` line, an `excluded:` line naming the classes in
`EXCLUSION_CLASSES` order, then one `  <churn>  <path>` line per ranked file with
` (binary)` appended to a binary row. It takes no range argument — the text form does not
echo the range. The exact shape is pinned by the test in Step 1.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -5`

Expected: `OK`, `Ran 21 tests`, no warnings, no skips.

Then confirm the module is genuinely importable in isolation and that Task 2's contract
names exist:

```bash
python3 -c "
import importlib.util, sys
s = importlib.util.spec_from_file_location('d', 'home/common/agent-skills/scripts/diff-scope.py')
m = importlib.util.module_from_spec(s); sys.modules['d'] = m; s.loader.exec_module(m)
print(sorted(n for n in ('DiffRow','ScopeResult','classify_row','scope_rows','format_json','format_text','_is_lockfile','_decode','EXCLUSION_CLASSES','HEADER_SCAN_BYTES') if hasattr(m, n)))
"
```

Expected: all ten names printed. A missing name is a broken contract for Task 2. The
`sys.modules` assignment is required here for the same reason `load_module()` needs it —
see D20.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/diff-scope.py \
        home/common/agent-skills/tests/test_diff_scope.py
git commit -m "feat(agent-skills): add the diff-scope product-accounting core

Classifier, churn ranking and output formatters for the shared
"how big is this change, in product terms?" measurement, with the
classifier-layer suite. The git layer and CLI follow.

Refs: https://github.com/fagenorn/nix-config/issues/21

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Git layer and CLI

Turn the module into the executable the contract promises: read the range with git, attach
header text to the rows that need it, parse and validate the arguments, and print.

**Files:**
- Modify: `home/common/agent-skills/scripts/diff-scope.py`
- Modify (test): `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**
- Consumes from Task 1: `DiffRow`, `ScopeResult`, `scope_rows`, `format_json`,
  `format_text`, `_is_lockfile`, `EXCLUSION_CLASSES`, `HEADER_SCAN_BYTES`.
- Produces:
  - `class DiffScopeError(Exception)` — every condition under which no measurement can be
    produced; `main` catches it, writes `diff-scope: <message>` to stderr and returns 1.
  - `def parse_range(text: str) -> tuple[str, str]`
  - `def normalize_artifact_path(value: str) -> bytes`
  - `def parse_numstat(payload: bytes) -> tuple[DiffRow, ...]`
  - `def parse_name_status(payload: bytes) -> dict[bytes, bytes]`
  - `def read_headers(root, base, head, rows, statuses) -> dict[bytes, bytes]`
  - `def measure(root: Path, base: str, head: str, artifact_paths: Sequence[bytes]) -> ScopeResult`
  - `def main(argv: list[str] | None = None) -> int`

**Invariants:**
- Exactly one positional range argument, in `<base>..<head>` form. A bare revision, an
  empty side, a three-dot range and a multi-range string are each rejected with exit 1
  (D10). Everything inside the two sides goes to git verbatim, so git stays the authority
  on revision syntax.
- Every git read is `-z` framed. Path bytes are never decoded before classification, and
  never passed through a shell.
- `-M` is passed explicitly so the measurement never depends on the caller's
  `diff.renames` (D3).
- A row's content side comes from `--name-status`, never from a guess: status `D` reads
  `base`, everything else reads `head`. A `missing` response from `cat-file` is therefore
  unambiguous and is a **hard error**, not a recoverable case (D7).
- Content is read with **one** `cat-file --batch -z` for the whole range, and responses are
  consumed by their declared byte size, never by a delimiter. Binary rows and lockfile rows
  are never queried. A non-blob response (a submodule gitlink resolves to a commit) is
  treated as not generated rather than crashing.
- Each header window handed to the classifier is truncated to at most `HEADER_SCAN_BYTES`
  and is clipped to its own response, never spilling into the next one.
- An `--artifact-path` that matches no row is **not** an error (D8). An absolute value, or
  one containing a `..` component, **is**.
- Output is written as bytes through `sys.stdout.buffer` with `errors="surrogateescape"`
  (D19).
- Exit 0 for any produced measurement, including zero; exit 1 for any failure to measure.
  No exit status means "large" (D9).

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_diff_scope.py`. Add `import os`,
`import subprocess` and `import tempfile` to the existing import block (`sys` is already
imported by the loader), then add the module-level helpers and the new class **above** the
`if __name__ == "__main__":` block:

```python
def git_env():
    """A hermetic git environment: no user or system config, no signing."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "diff-scope-test",
            "GIT_AUTHOR_EMAIL": "diff-scope-test@example.invalid",
            "GIT_COMMITTER_NAME": "diff-scope-test",
            "GIT_COMMITTER_EMAIL": "diff-scope-test@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
        }
    )
    return env


def git(root, *arguments):
    """Run one git command by argv, so a path argument never meets a shell."""
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed ({completed.returncode}): "
            f"{completed.stderr}"
        )
    return completed.stdout.strip()


def write(root, relative_path: bytes, content: bytes) -> None:
    """Write a file whose name may hold any byte APFS accepts (newline, quote)."""
    target = os.path.join(os.fsencode(root), relative_path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(content)


def run_helper(root, *arguments):
    """Invoke the script the way a caller does, capturing raw bytes."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=root,
        env=git_env(),
        capture_output=True,
        check=False,
    )


def build_fixture_repo(root):
    """Two commits spanning every row shape the helper must survive."""
    git(root, "init", "-q", "-b", "main", ".")
    write(root, b"src/app.py", b"one\ntwo\nthree\n")
    write(root, b"pkg/old.txt", b"a\nb\nc\n")
    write(root, b"pnpm-lock.yaml", b"lock\n")
    write(root, b"assets/logo.png", b"\x00\x01\x02binary\x00")
    write(root, b"api/types.ts", b"// Code generated by protoc-gen-ts.\nexport {};\n")
    write(root, b"gone/Model.cs", b"// <auto-generated>\nclass Model {}\n")
    write(root, b"tie-a.txt", b"1\n2\n3\n4\n5\n")
    write(root, b"tie-b.txt", b"1\n2\n3\n4\n5\n")
    write(root, b".claude/specs/historical.md", b"old spec\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")

    write(root, b"src/app.py", b"one\ntwo\nthree\nfour\n")
    git(root, "mv", "pkg/old.txt", "pkg/new.txt")
    write(root, b"pnpm-lock.yaml", b"lock\nmore\n")
    write(root, b"assets/logo.png", b"\x00\x01\x02BINARY CHANGED\x00\x00")
    write(
        root,
        b"api/types.ts",
        b"// Code generated by protoc-gen-ts.\nexport {};\nexport const x = 1;\n",
    )
    git(root, "rm", "-q", "gone/Model.cs")
    write(root, b"tie-a.txt", b"1\n2\n3\n4\n5\n6\n")
    write(root, b"tie-b.txt", b"1\n2\n3\n4\n5\n6\n")
    write(root, b".claude/specs/this-run.md", b"new spec\n")
    write(root, b"we\nird.txt", b"newline path\n")
    write(root, b'qu"ote.txt', b"quote path\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "head")


class DiffScopeCommandTest(unittest.TestCase):
    """The git layer and the CLI, against a real scratch repository.

    The fixture range HEAD~1..HEAD holds eleven rows: one lockfile, two
    generated (one of them a deletion, readable only on its base side), one
    binary, one pure rename, one spec artifact, and five ordinary product
    files -- two of which carry equal churn, and two of which carry a newline
    and a double quote in their names.
    """

    ARTIFACT = ".claude/specs/this-run.md"

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = cls.temporary.name
        build_fixture_repo(cls.root)
        cls.range = "HEAD~1..HEAD"

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def measure(self, *arguments):
        completed = run_helper(self.root, self.range, *arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.decode("utf-8"))

    def test_product_totals_exclude_every_class(self):
        payload = self.measure("--artifact-path", self.ARTIFACT)
        self.assertEqual(payload["range"], "HEAD~1..HEAD")
        self.assertEqual(payload["product"], {"changed_lines": 5, "changed_files": 7})
        self.assertEqual(
            payload["excluded"], {"lockfile": 1, "generated": 2, "artifact": 1}
        )

    def test_every_row_git_emitted_is_accounted_for_exactly_once(self):
        payload = self.measure("--artifact-path", self.ARTIFACT)
        raw = subprocess.run(
            ["git", "diff", "--numstat", "-z", "-M", self.range],
            cwd=self.root,
            env=git_env(),
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
        # One count record per row; a rename adds two further path-only tokens.
        # No fixture path contains a tab, so a tab identifies a count record.
        rows = sum(1 for token in raw.split(b"\0") if token and b"\t" in token)
        self.assertEqual(rows, 11)
        self.assertEqual(
            len(payload["files"]) + sum(payload["excluded"].values()), rows
        )

    def test_a_deleted_generated_file_is_read_on_its_base_side(self):
        # gone/Model.cs exists only at base; head-side-only reading would miss
        # its <auto-generated> header and count it as product.
        payload = self.measure()
        self.assertNotIn(
            "gone/Model.cs", [entry["path"] for entry in payload["files"]]
        )
        self.assertEqual(payload["excluded"]["generated"], 2)

    def test_a_rename_is_one_zero_churn_row_under_its_new_path(self):
        entries = {entry["path"]: entry for entry in self.measure()["files"]}
        self.assertNotIn("pkg/old.txt", entries)
        self.assertEqual(
            entries["pkg/new.txt"],
            {"path": "pkg/new.txt", "changed_lines": 0, "binary": False},
        )

    def test_a_binary_row_is_product_with_zero_lines(self):
        entries = {entry["path"]: entry for entry in self.measure()["files"]}
        self.assertEqual(
            entries["assets/logo.png"],
            {"path": "assets/logo.png", "changed_lines": 0, "binary": True},
        )

    def test_paths_holding_a_newline_or_a_quote_survive_end_to_end(self):
        paths = {entry["path"] for entry in self.measure()["files"]}
        self.assertIn("we\nird.txt", paths)
        self.assertIn('qu"ote.txt', paths)

    def test_ties_rank_by_path(self):
        paths = [entry["path"] for entry in self.measure()["files"]]
        self.assertLess(paths.index("tie-a.txt"), paths.index("tie-b.txt"))

    def test_the_named_artifact_drops_and_counts_without_the_flag(self):
        with_flag = {
            entry["path"] for entry in self.measure("--artifact-path", self.ARTIFACT)["files"]
        }
        self.assertNotIn(self.ARTIFACT, with_flag)
        without_flag = {entry["path"] for entry in self.measure()["files"]}
        self.assertIn(self.ARTIFACT, without_flag)

    def test_an_artifact_path_matching_nothing_is_not_an_error(self):
        payload = self.measure("--artifact-path", ".claude/plans/never-written.md")
        self.assertEqual(payload["excluded"]["artifact"], 0)
        self.assertEqual(payload["product"]["changed_files"], 8)

    def test_a_leading_dot_slash_and_a_trailing_slash_are_stripped(self):
        payload = self.measure("--artifact-path", "./.claude/specs/")
        self.assertEqual(payload["excluded"]["artifact"], 1)

    def test_output_is_byte_identical_across_two_runs(self):
        first = run_helper(self.root, self.range, "--artifact-path", self.ARTIFACT)
        second = run_helper(self.root, self.range, "--artifact-path", self.ARTIFACT)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_text_format_reports_the_same_totals(self):
        completed = run_helper(
            self.root, self.range, "--format", "text", "--artifact-path", self.ARTIFACT
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.decode("utf-8").splitlines()
        self.assertEqual(lines[0], "product: 5 lines, 7 files")
        self.assertEqual(lines[1], "excluded: 1 lockfile, 2 generated, 1 artifact")
        self.assertIn("  0  assets/logo.png (binary)", lines)

    def test_an_empty_range_measures_zero_and_succeeds(self):
        completed = run_helper(self.root, "HEAD..HEAD")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(payload["product"], {"changed_lines": 0, "changed_files": 0})
        self.assertEqual(payload["files"], [])
        self.assertEqual(
            payload["excluded"], {"lockfile": 0, "generated": 0, "artifact": 0}
        )

    def test_a_malformed_range_exits_one(self):
        for bad in ("HEAD", "HEAD...HEAD~1", "..HEAD", "HEAD..", "a..b..c"):
            with self.subTest(range=bad):
                completed = run_helper(self.root, bad)
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertIn(b"diff-scope:", completed.stderr)

    def test_an_unknown_revision_exits_one(self):
        completed = run_helper(self.root, "HEAD..no-such-revision")
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn(b"diff-scope:", completed.stderr)

    def test_a_root_outside_a_work_tree_exits_one(self):
        with tempfile.TemporaryDirectory() as outside:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), self.range, "--root", outside],
                env=git_env(),
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn(b"work tree", completed.stderr)

    def test_an_absolute_or_escaping_artifact_path_exits_one(self):
        for bad in ("/etc/passwd", "../outside.md", "a/../../b.md"):
            with self.subTest(value=bad):
                completed = run_helper(self.root, self.range, "--artifact-path", bad)
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertIn(b"diff-scope:", completed.stderr)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -5`

Expected: `DiffScopeClassifierTest` still passes; every `DiffScopeCommandTest` fails —
the script has no `main`, so `run_helper` exits 0 with empty stdout and `json.loads`
raises `JSONDecodeError`, and the exit-code assertions read 0 instead of 1.

- [ ] **Step 3: Write the minimal implementation**

Prepend `#!/usr/bin/env python3` to `scripts/diff-scope.py` (the first line, above the
docstring). Add `import argparse`, `from dataclasses import dataclass, replace`,
`from pathlib import Path`, `import subprocess`, `import sys` to the imports.

```python
class DiffScopeError(Exception):
    """A condition under which no measurement can be produced; main exits 1."""
```

`_git(root, *arguments, stdin_payload=None) -> bytes` runs
`subprocess.run(["git", *arguments], cwd=str(root), input=stdin_payload, stdout=PIPE, stderr=PIPE, check=False)`.
On a non-zero return it raises `DiffScopeError` carrying the command and git's stderr
decoded with `errors="replace"`; on `FileNotFoundError` it raises
`DiffScopeError("git executable not found on PATH")`. It never uses `shell=True` and never
uses `text=True` — stdout carries raw path bytes.

`parse_range(text)` — reject `"..." in text` first (a three-dot range survives a naive
"exactly one `..`" check, because `"a...b".count("..")` is 1). Then split on `".."`,
require exactly two parts, and require both non-empty. Each rejection raises
`DiffScopeError` naming the offending value.

`normalize_artifact_path(value)` — reject a value starting with `/`; strip every leading
`./` then a trailing `/`; reject an empty or `.` result; reject any `..` component; return
`value.encode("utf-8", errors="surrogateescape")`. Values are repository-root-relative
because git reports numstat paths root-relative even from a subdirectory (D8).

`parse_numstat(payload)` — split on `b"\0"`, drop a trailing empty token, then walk the
token list **by index**, never with a plain `for token in tokens`: a rename record is
followed by two path-only tokens that are part of *that* record and must be consumed with
it, not visited as records of their own (D21).

```python
    index = 0
    while index < len(tokens):
        # split(b"\t", 2) — a tab is a legal filename byte and -z emits path bytes
        # verbatim, so only the first two tabs are field separators (D22).
        fields = tokens[index].split(b"\t", 2)
        # A count record is exactly <add>\t<del>\t<path>; anything else is corrupt.
        additions_text, deletions_text, path = fields
        if path == b"":
            # Rename or copy: git emits <record>\0<old>\0<new>\0. The destination is
            # the SECOND following token -- tokens[index + 1] is the OLD path (D21).
            path = tokens[index + 2]
            index += 3
        else:
            index += 1
```

A count of `b"-"` becomes `None` (binary); any other non-integer raises `DiffScopeError`.
A record that does not split into three fields, or a rename record whose two path tokens
are not both present (`index + 2 >= len(tokens)`), raises `DiffScopeError` — fail loud
rather than guess.

`parse_name_status(payload)` — split the same way; a status token beginning with `R` or `C`
consumes two path tokens and is keyed by the **second** (the destination), every other
status consumes one. Returns `{destination_path: status}`.

`read_headers(root, base, head, rows, statuses)` — build one request stream, skipping any
row that is `row.binary` or `_is_lockfile(row.path)` (a lockfile is excluded before the
generated check runs, so its content can never change the answer; an artifact row is
checked *after* generated, so it must still be read). For each remaining row, look up its
status — a row absent from `statuses` raises `DiffScopeError` — pick
`base if status[:1] == b"D" else head`, and append
`revision.encode("utf-8", errors="surrogateescape") + b":" + row.path + b"\0"`. Return
`{}` without a subprocess when nothing needs reading. Otherwise run
`_git(root, "cat-file", "--batch", "-z", stdin_payload=b"".join(requests))` and hand the
response to `_parse_batch`, zipped back onto the requested paths.

`_parse_batch(payload, expected)` returns one header window per request, in request order:

```python
    for _ in range(expected):
        newline = payload.find(b"\n", position)
        if newline < 0:
            raise DiffScopeError("truncated cat-file batch response")
        header = payload[position:newline]
        # Parse defensively and raise DiffScopeError for ANYTHING unparsable (D23).
        # A `missing` answer echoes the request verbatim, so for a path holding a
        # newline the find() above stops inside the path and `header` is a fragment
        # that neither ends with b" missing" nor rsplits into three parts. Letting
        # that reach the unpack raises ValueError, which escapes main's
        # `except DiffScopeError` and dies with a traceback instead of the
        # `diff-scope: ...` message every CLI error test asserts on.
        parts = header.rsplit(b" ", 2)
        if header.endswith(b" missing") or len(parts) != 3:
            # We only ever ask for a side git's own --name-status said exists,
            # so a missing answer is a hard error, never a fallback (D7).
            raise DiffScopeError(f"git reported missing content for {header!r}")
        object_type, size_text = parts[1:]
        try:
            size = int(size_text)
        except ValueError:
            raise DiffScopeError(f"unparsable cat-file header {header!r}") from None
        start = newline + 1
        end = start + size
        if end > len(payload):
            raise DiffScopeError("truncated cat-file batch content")
        windows.append(payload[start:end][:HEADER_SCAN_BYTES] if object_type == b"blob" else b"")
        position = end + 1  # one newline terminates each response
```

`payload[start:end][:HEADER_SCAN_BYTES]` — clip to the response first, then to the byte
bound, so a response shorter than 8 KiB never bleeds into the next one. A non-blob type
yields `b""`, which the classifier reads as not generated. An unparsable header raises
`DiffScopeError`.

`measure(root, base, head, artifact_paths)`:

```python
def measure(root, base, head, artifact_paths):
    """Return the product measurement for base..head, applying the three exclusions."""
    range_argument = f"{base}..{head}"
    rows = parse_numstat(_git(root, "diff", "--numstat", "-z", "-M", range_argument))
    if not rows:
        return scope_rows((), artifact_paths)
    statuses = parse_name_status(
        _git(root, "diff", "--name-status", "-z", "-M", range_argument)
    )
    headers = read_headers(root, base, head, rows, statuses)
    return scope_rows(
        (replace(row, header=headers.get(row.path)) for row in rows), artifact_paths
    )
```

`_validate_root(root)` — raise `DiffScopeError(f"--root is not a git work tree: {root}")`
when `root` is not a directory, when `_git(root, "rev-parse", "--is-inside-work-tree")`
raises, or when its output is not `b"true"`. The message must contain the words
`work tree`; the CLI test asserts on that.

`_emit(payload)` writes `payload.encode("utf-8", errors="surrogateescape")` to
`sys.stdout.buffer` and flushes. Plain `print()` would raise `UnicodeEncodeError` on a
surrogate-escaped path in the text format (D19).

`_parser()` builds `argparse.ArgumentParser(prog="diff-scope", description=__doc__)` with
the positional `range`, `--root` (`type=Path`, `default=Path.cwd()`), `--artifact-path`
(`action="append"`, `default=[]`, `metavar="PATH"`), and
`--format` (`choices=("json", "text")`, `default="json"`).

`main(argv=None)` parses, then inside one `try` block: `parse_range`, map
`normalize_artifact_path` over `args.artifact_path`, `_validate_root(Path(args.root))`,
`measure(...)`. On `DiffScopeError` it prints `f"diff-scope: {error}"` to stderr and
returns 1. On success it emits `format_json(args.range, result)` or `format_text(result)`
and returns 0. End the file with `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -5`

Expected: `OK`, `Ran 38 tests` across both classes (21 classifier + 17 CLI), no warnings,
no skips.

Then confirm the exclusion classes are load-bearing rather than incidentally satisfied —
this is acceptance criterion 6, and it is the one check the suite cannot make of itself.
For each class in turn, make its predicate return `False`, re-run, and confirm the suite
turns red **including that class's own dedicated tests**. Shared aggregate tests
(`test_a_range_of_only_excluded_rows_measures_zero`, `test_product_totals_exclude_every_class`,
`test_text_format_reports_the_same_totals`) fail for every class and are not the signal —
the class-specific names below are:

```bash
for class in lockfile generated artifact; do
  cp home/common/agent-skills/scripts/diff-scope.py /tmp/diff-scope.bak
  python3 - "$class" <<'PY'
import re, sys
path = "home/common/agent-skills/scripts/diff-scope.py"
source = open(path).read()
source = re.sub(rf"(def _is_{sys.argv[1]}\([^)]*\)[^:]*:\n)", r"\1    return False\n", source, count=1)
open(path, "w").write(source)
PY
  echo "=== $class disabled ==="
  python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 \
    | grep -oE 'FAIL: test_[a-z_]+' | sort -u
  cp /tmp/diff-scope.bak home/common/agent-skills/scripts/diff-scope.py
done
python3 -m unittest home/common/agent-skills/tests/test_diff_scope.py 2>&1 | tail -3
```

Expected, as observed when this loop was rehearsed against the reference implementation
during planning:

- **lockfile disabled** — 13 failures, including
  `test_lockfile_row_is_excluded_while_its_product_sibling_survives` and
  `test_every_lockfile_spelling_is_recognised`.
- **generated disabled** — 8 failures, including
  `test_generated_row_is_excluded_while_its_product_sibling_survives`,
  `test_auto_generated_marker_is_recognised` and
  `test_a_deleted_generated_file_is_read_on_its_base_side`.
- **artifact disabled** — 7 failures, including `test_only_the_named_artifact_is_excluded`,
  `test_artifact_prefix_matches_a_directory_not_a_sibling_prefix`,
  `test_the_named_artifact_drops_and_counts_without_the_flag` and
  `test_a_leading_dot_slash_and_a_trailing_slash_are_stripped`.
- **restored** — `OK`.

If disabling a class leaves the suite green, or reddens only the shared aggregates, that
class has no test that fails for exactly one reason — add one before proceeding. Then
confirm the mutation is gone with
`git diff --stat -- home/common/agent-skills/scripts/diff-scope.py` (expected: empty
output).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/diff-scope.py \
        home/common/agent-skills/tests/test_diff_scope.py
git commit -m "feat(agent-skills): read the range with git and expose the diff-scope CLI

Adds the -z numstat/name-status reads, the batched cat-file header scan
with its base-side read for deletions, argument validation and both
output formats, plus the CLI-layer suite over scratch repositories.

Refs: https://github.com/fagenorn/nix-config/issues/21

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Install the helper and register the suites

Put `diff-scope` on `~/.agents/bin` through the established pattern, and make the test
runner honest — it currently claims to "verify … skill contracts" while running neither
`test_agent_evidence.py` nor `test_agent_model_matrix.py` (D15).

**Files:**
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`

**Interfaces:**
- Consumes from Task 2: the executable script at
  `home/common/agent-skills/scripts/diff-scope.py`, and the suite at
  `home/common/agent-skills/tests/test_diff_scope.py`.
- Produces: `~/.agents/bin/diff-scope`, executable, resolvable by bare name because
  `home.sessionPath = [ "$HOME/.agents/bin" ]` is already present in the same module.

**Invariants:**
- The wiring is the same four-line `home.file` shape the other four helpers use; no new
  PATH plumbing, no new activation script.
- `home.sessionPath = [ "$HOME/.agents/bin" ]` stays exactly as-is — it is what makes AC 1
  true, and `test_workflow_skill_contracts.py::test_helper_binaries_resolve_from_bare_names`
  already asserts that line.
- `just agent-workflow-tests` runs all seven suites and stays green.
- No skill file, README or `CLAUDE.md` line is touched (D17).

- [ ] **Step 1: Wire the helper into home-manager**

In `home/common/agent-skills/default.nix`, inside the `home.file` attrset, after the
`".agents/bin/agent-evidence"` block:

```nix
    ".agents/bin/diff-scope" = {
      source = ./scripts/diff-scope.py;
      executable = true;
    };
```

- [ ] **Step 2: Register the suites in the test runner**

In `justfile`, replace the file list of the `agent-workflow-tests` recipe so it reads:

```
agent-workflow-tests:
  python3 -m unittest -v \
    home/common/agent-skills/tests/test_workflow_state.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py \
    home/common/agent-skills/tests/test_ship_release_contracts.py \
    home/common/agent-skills/tests/test_agent_evidence.py \
    home/common/agent-skills/tests/test_agent_model_matrix.py \
    home/common/agent-skills/tests/test_diff_scope.py \
    tests/test_agent_costs.py
```

Leave the recipe's comment and every other recipe untouched.

- [ ] **Step 3: Verify**

Run the full suite:

```bash
just agent-workflow-tests 2>&1 | tail -3
```

Expected: `OK`, with `Ran` reporting **150 tests** — the base commit's 70, plus 42 from the
two newly registered orphan suites, plus the 38 from `test_diff_scope.py` (more only if
you added tests beyond the plan). The count diagnoses a partial edit: 70 means neither
registration took, 108 means the two orphans are still missing, 112 means `test_diff_scope.py`
is still missing.

Run the build:

```bash
just build 2>&1 | tail -5
```

Expected: a successful build, no evaluation error.

Then the wiring gate — non-destructive, builds an attribute and inspects the store path,
and never activates:

```bash
p=$(nix --extra-experimental-features 'nix-command flakes' build --no-link \
      --print-out-paths '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files')
test -x "$p/.agents/bin/diff-scope" && echo "installed and executable"
```

Expected: `installed and executable`. This check **fails at the base commit** — the store
path there carries only `agent-evidence`, `agent-model-matrix`, `context-map-lint`,
`resolve-bindings` and `workflow-state` — so it is a gate that can actually fail. The
check runs against the darwin host because that is where the work happens; the module
lives under `home/common/`, so `anis-desktop` receives the identical wiring by
construction.

Finally, prove the built helper runs by bare-name invocation from that environment,
without activating anything:

```bash
(export PATH="$p/.agents/bin:$PATH"; cd "$(mktemp -d)" && git init -q -b main . \
  && git commit -q --allow-empty -m one && git commit -q --allow-empty -m two \
  && diff-scope HEAD~1..HEAD)
```

Expected:
`{"excluded":{"artifact":0,"generated":0,"lockfile":0},"files":[],"product":{"changed_files":0,"changed_lines":0},"range":"HEAD~1..HEAD"}`

- [ ] **Step 4: Confirm the branch's scope**

```bash
git diff --stat origin/main...HEAD -- \
  home/common/agent-skills/scripts/diff-scope.py \
  home/common/agent-skills/tests/test_diff_scope.py \
  home/common/agent-skills/default.nix \
  justfile
```

Expected: exactly those four paths, and no others in that pathspec. Do **not** assert over
the unscoped commit range — the spec and plan artifacts land in it, and a ship-time sync
merge will pull in whatever `main` advanced by.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/default.nix justfile
git commit -m "feat(agent-skills): install diff-scope and register the helper suites

Wires ~/.agents/bin/diff-scope through the existing home.file pattern and
adds test_diff_scope.py to just agent-workflow-tests, along with the two
suites the recipe never ran (test_agent_evidence, test_agent_model_matrix).

Refs: https://github.com/fagenorn/nix-config/issues/21

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Acceptance criteria coverage

| # | Criterion | Where it is met |
|---|-----------|------------------|
| 1 | Bare-name helper reports product lines, product file count, and files ranked by churn | Task 1 (`scope_rows`, `_rank`, `format_json`) · Task 2 (CLI) · Task 3 (install + bare-name run) |
| 2 | Lockfile, generated-header and artifact rows are excluded from both counts and the ranking | Task 1 Step 1, the three per-class tests; Task 2's fixture repeats all three against real git rows |
| 3 | An all-excluded range reports zero lines and zero files | Task 1 `test_a_range_of_only_excluded_rows_measures_zero`; Task 2 `test_an_empty_range_measures_zero_and_succeeds` covers the empty-range sibling |
| 4 | A historical artifact that is itself the product still counts | Task 1 `test_only_the_named_artifact_is_excluded` and `test_without_artifact_paths_a_historical_artifact_still_counts`; Task 2 `test_the_named_artifact_drops_and_counts_without_the_flag` |
| 5 | The ranking is deterministic | Task 1 `test_ranking_is_churn_descending_with_a_raw_byte_tie_break` and `test_ranking_does_not_depend_on_input_order`; Task 2 `test_ties_rank_by_path` and `test_output_is_byte_identical_across_two_runs` |
| 6 | Removing any one exclusion class makes the tests fail | Structurally: each class owns a test pairing a class row with a product sibling and asserting absence from `files`, absence from `changed_lines`, and the `excluded.<class>` count, while the sibling survives all three. Actively proved by Task 2 Step 4's three-way mutation loop |
| 7 | `just build` succeeds and the helper resolves by bare name from a freshly built environment | Task 3 Step 3 — `just build`, the `home-files` store-path `test -x`, and the bare-name invocation with `PATH` prefixed from that store path. No activation |

## Out of scope for this branch

Per the spec's "Out of scope" section — do not do any of these, and reject a review
suggestion that asks for them:

- Making `ship-issue`'s degradation gate or `from-issue`'s C4 note call the helper (D14).
- The scoped-review packet builder and its 20-file budget — https://github.com/fagenorn/nix-config/issues/24.
- Retuning the degradation gate from 400 to 1,000 lines.
- Any threshold, verdict or "too big" exit status in the helper (D9).
- Three-dot ranges, working-tree diffs, staged-vs-HEAD (D10).
- Deriving the lockfile allowlist from `SYNC.md` at runtime, or editing `SYNC.md` (D13).
- Any `patchRevision` bump.
