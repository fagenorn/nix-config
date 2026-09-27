# Design: one executable definition of "how big is this change, in product terms?"

Issue: https://github.com/fagenorn/nix-config/issues/21

## Problem

The question "how big is this change, in product terms?" already has one authoritative
answer in this repo, and that answer is prose an agent hand-executes. `ship-issue`'s
degradation gate says: run `git diff --numstat <base>..<head>`, drop rows that are
lockfiles, carry a generated header, or live under this run's own spec and plan
artifacts, then sum additions plus deletions and count the surviving rows. The same rule
is restated a second time, in different words, in `from-issue`'s Phase-0 note.

A third consumer is now coming. The scoped-review packet builder (issue 24) must select
a bounded subset of a large diff, and its design settles that the subset is taken from
"the same numstat the degradation gate computes, with the same exclusions the gate
already applies" plus a churn ranking. Written as prose a third time, that sentence is a
promise no mechanism keeps: three hand-executions of a six-clause rule drift, and the
drift is invisible because each site produces a plausible number.

Two properties of the rule make hand-execution especially unreliable. The exclusion for
process artifacts is *directional* — only this run's own spec and plan output is dropped,
while a historical artifact that is itself the requested product still counts — so it
cannot be reduced to a fixed path prefix. And a real range contains rows the prose never
addresses: binaries, for which git prints `-` instead of a count, and renames, which git
renders as `dir/{old => new}/file`. Each agent resolves those silently and differently.

## Solution

Extract the accounting once, as an executable helper on `~/.agents/bin`, and change no
skill in this slice. The helper takes a two-dot range and reports three things: product
changed lines, product changed file count, and the surviving files ranked by churn. It
applies the three documented exclusions and nothing else.

It deliberately reports *measurements only*. It carries no threshold, no verdict, and no
"too big" exit status. The degradation gate's file cap and the scoped-review budget are
two different decisions that happen to share the number twenty; collapsing them into a
shared constant inside the helper would fuse two policies that must be free to move
apart. Each consumer keeps its own thresholds and asks the helper only for numbers.

This slice ships the helper, its tests, and its Nix wiring. Rewriting the gate's prose
into a call to it is the next slice, and is what retires the prose.

## Decisions

### The CLI contract

```
diff-scope <base>..<head> [--root PATH] [--artifact-path PATH]... [--format json|text]
```

This is a public contract two skills will bind to, so it is fixed here rather than left
to the implementer.

**Range.** Exactly one positional argument, in exactly `<base>..<head>` form: one `..`,
both sides non-empty. A bare revision, an empty side, and the three-dot `...` form are
each rejected with a diagnostic and exit 1. Everything inside the two sides is passed to
git verbatim, so git remains the authority on revision syntax. Per D10.

**`--root PATH`** (default: the working directory) — the repository to measure in,
matching `agent-model-matrix --root`. Not a git work tree is an error.

**`--artifact-path PATH`** — repeatable, **default: none**. Names one path this run
produced as process output. Values are **relative to the repository root, not to
`--root`** — git reports numstat paths relative to the repository root even when invoked
from a subdirectory (verified), so root-relative is the only frame in which a value can
match. A leading `./` and a trailing `/` are stripped before matching; an absolute path
or one escaping the repository is an error rather than a value that silently never
matches. Per D8.

**`--format {json,text}`** — default `json`.

**Exit codes.** `0` when a measurement was produced — including an empty range, and
including a range in which every row was excluded. Both are valid measurements of zero
and neither is an error; they are distinguishable only by `excluded`. `1` when the
helper could not measure: malformed range, `--root` is not a work tree, git failed
(unknown revision), an `--artifact-path` is absolute or escapes the repository, or git
reported a row's content missing on the very side it said the row exists on. `2` is
argparse's own usage error. There is no
exit status that means "this change is large" — per D9.

**stdout, `--format json`.** One compact object, `sort_keys=True`,
`separators=(",", ":")`, `ensure_ascii=True`, one trailing newline:

```json
{"range":"<base>..<head>",
 "product":{"changed_lines":412,"changed_files":13},
 "files":[{"path":"<repo-relative>","changed_lines":214,"binary":false}],
 "excluded":{"lockfile":2,"generated":1,"artifact":5}}
```

`product.changed_lines` is the sum of `files[].changed_lines`; `product.changed_files`
is `len(files)`. `files` is the ranking. `excluded` counts each dropped row exactly once,
under the first class it matches in the fixed order lockfile → generated → artifact, so
`len(files) + sum(excluded.values())` equals the number of rows git emitted — an
invariant the suite asserts. `ensure_ascii` keeps a non-UTF-8 path printable as escaped
surrogates rather than crashing the write.

**stdout, `--format text`.** The same *measurement* for a human or an agent quoting it
into prose, minus the range identity: a `product:` line, an `excluded:` line, then one
indented `<churn>  <path>` line per ranked file, binaries suffixed ` (binary)`.
(**amended by issue 32's alignment spec, D2** —
`.claude/specs/2026-08-17-issue-32-spec-doc-alignment-design.md`; this paragraph
originally read "the same content", which was never true of the shipped helper.) The
omission is deliberate: every line of the text form is measured output, whereas the range
is caller-supplied *input*, and a quoter carries it in the invocation printed above the
output — the pattern `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`
already demonstrates. `--format json` echoes `range` because it is the machine record and
must stay self-describing once detached from the command that produced it.

### How the range is read

`git diff --numstat -z -M <base>..<head>`, run with `--root` as the working directory.

`-z` rather than plain numstat because the plain form is lossy in two ways this helper
cannot tolerate: it collapses a rename to `pkg/{old => new}/file`, which has to be
reverse-engineered back into a path, and it C-quotes unusual paths (`"we\"ird.txt"`),
which has to be unescaped. Under `-z` a normal row is `<add>\t<del>\t<path>\0` and a
rename row is `<add>\t<del>\t\0<old>\0<new>\0` — the third tab-field is empty and two
NUL-terminated paths follow — with path bytes verbatim. Per D3.

`-M` is passed explicitly so the measurement does not silently depend on the caller's
`diff.renames` configuration. With rename detection off, a pure file move stops being one
zero-churn row and becomes a delete plus an add carrying the file's whole length twice —
a difference large enough to move a size gate.

### How a row is classified

A row's **path** — the term this document uses throughout — is the *destination* path git
reports for it: the new path on a rename, and the single path git prints on every other
row, including a deletion. "Head-side path" would be wrong for a deletion, whose path
exists only at base. Its **churn** is additions plus deletions; a binary row, which git
prints as `-` and `-`, has churn 0 and is flagged `binary`.

Classification runs in a fixed order; the first match wins and the row is dropped:

1. **lockfile** — the basename ends with `.lock`, or is one of `package-lock.json`,
   `bun.lockb`, `go.sum`, `pnpm-lock.yaml`. This is the allowlist `ship-issue/SYNC.md`
   documents, reduced: its `**/*.lock` glob already subsumes `Cargo.lock`.
2. **generated** — the row is not binary, and the first five lines of its content contain
   `<auto-generated>` or `// Code generated by`. "First five lines" is evaluated over at
   most the first 8 KiB, so a file whose first five lines exceed that is scanned only as
   far as the byte bound. Which side is read is settled by the row's status rather than
   guessed at: a deletion is read at base, everything else at head. Per D6, D7.
3. **artifact** — the path equals one of the `--artifact-path` values, or begins with one
   followed by `/`.

Everything surviving is **product**.

Three consequences are deliberate and load-bearing:

**A binary is product.** It contributes one to the file count and zero to the line total.
That is the literal reading of the documented rule — "lines = additions + deletions
summed, files = row count" — applied to a row git reports no line counts for. Dropping
binaries would be a fourth exclusion class the accounting never authorised. The `binary`
flag exists so the packet builder can tell a zero-churn binary from a zero-churn pure
rename, which are otherwise identical in the output and want opposite handling.

**Only the destination path is classified.** A file moved *out of* an artifact path and
into product counts as product, which is the carve-out's own direction. Classifying a
rename against both sides would drop exactly that case. Per D4.

**An `--artifact-path` that matches no row is not an error.** A run that produced a spec
but not yet a plan legitimately passes a plan path that matches nothing, so the caller
cannot be required to pass only live paths. The failure this tolerates — a caller
mistyping a path — makes the measurement *larger*, which degrades the gate less and puts
more files in a review packet. Every failure mode of this flag is therefore conservative,
which is the reason it can afford to be silent. Per D8.

### How the artifact exclusion preserves the carve-out

The carve-out — "historical artifacts that are themselves the requested product still
count" — survives extraction because of two properties of `--artifact-path`, not because
of a comment.

First, **the default is to exclude nothing.** A caller that passes no `--artifact-path`
gets every changed file counted, historical specs included. There is no built-in
`.claude/specs` default that would have to be argued out of the way.

Second, **the flag takes a path, not a directory.** `<specDir>` holds every spec this
repository has ever accepted, so a directory-granular exclusion cannot express "this
run's own artifacts" — it would drop a historical spec that is itself the product. A
caller names the one or two files its run wrote. Matching is exact-or-prefix
(`value` or `value + "/"`), so naming a directory still works when a caller genuinely
wants one, and no filesystem access is involved, which means a deleted path classifies
identically to a live one. Per D8.

### Ranking

`files` is sorted by churn descending, ties broken by the raw path bytes ascending. A
diff has exactly one row per destination path, so the path is unique and the pair is a
total order — which is what makes the order reproducible rather than incidentally
stable. Sorting on raw bytes rather than the decoded string keeps the order independent
of locale and of how non-UTF-8 bytes decoded. Per D12.

Git already emits numstat in path order, so a helper that merely preserved git's order
would *appear* deterministic in every test while resting on an undocumented property.
The tie-break is asserted directly, with a fixture in which two files carry equal churn.

### Internal shape, and why it is part of the design

The helper separates a **git layer** — read the numstat rows, read the header text for
the rows that need it — from a **pure classifier** over rows that already carry their
header text and binary flag. That boundary is not decoration: it is what lets the
generated-header exclusion be tested without a scratch repository, and therefore what
makes per-class test isolation cheap enough to actually do (see Test seams).

Header text is read in two steps, both of them one subprocess for the whole range rather
than one per row: git provides batch primitives, and the helper sits on the latency path
of a review dispatch.

First, `git diff --name-status -z -M <range>` gives every row its status. Joined to the
numstat rows by destination path — unique within a diff, so no ordering assumption is
needed — it settles which side each row's content lives on: `D` reads base, everything
else reads head. This exists to remove a guess, not to add a call. Probing head first and
falling back on a "missing" answer would require parsing git's `<name> missing` response,
whose echoed name can itself contain a newline; asking only for a side git has already
said exists means **any `missing` response is unambiguously the hard error** D7 names,
rather than a case to recover from.

Second, one `git cat-file --batch -z` resolves `<rev>:<path>` for the rows that need it.
The `-z` is required, not stylistic: `--batch`'s default line protocol splits a path
containing a newline into two bogus requests, which was reproduced against git 2.51.2,
while `--batch -z` returns the correct blob. Responses stay size-framed, so content is
read by byte count and never by delimiter. Binaries are never queried. A response whose
type is not `blob` — a submodule gitlink resolves to a commit — is treated as not
generated rather than crashing the scan.

The five-line scan window is a correctness requirement, not an optimisation. This
repository's own `home/common/agent-skills/skills/ship-issue/SYNC.md` contains the
literal string `// Code generated by` in a prose table. A whole-file scan would classify
a hand-written skill document as machine-generated and silently shrink the product
measurement of any branch that edits it.

## Test seams

Two seams, both existing.

**1. `home/common/agent-skills/tests/test_diff_scope.py`**, stdlib `unittest`, registered
in `just agent-workflow-tests`. It follows `test_agent_model_matrix.py`'s two-layer
precedent (**amended by D20** — this sentence originally read "precedent verbatim", which
D20 found to be exactly the bug: `load_module()` must additionally register the module in
`sys.modules` before `spec.loader.exec_module`, or every classifier-layer test errors in
`setUpClass`):

- *Classifier layer* — `importlib.util.spec_from_file_location` loads
  `scripts/diff-scope.py` and the tests call the pure classifier over synthetic rows.
  Every exclusion class, the ranking tie-break, the all-excluded case, and the carve-out
  live here. Its fixtures must be shaped the way the git layer actually emits rows — a
  binary row carrying absent counts rather than zeros, a rename row carrying both paths —
  or a bug in the git layer and a matching shortcut in the fixture cancel out and both
  stay green.
- *CLI layer* — `subprocess.run([sys.executable, SCRIPT, ...])` against a scratch git
  repository built in a `tempfile.TemporaryDirectory`. This layer covers only what the
  classifier layer structurally cannot: real `-z` parsing of a rename row, a real binary
  row, a real generated-header content read including the base-side read for a *deleted*
  generated file, the `len(files) + sum(excluded)` invariant against git's actual row
  count, exit 1 on a malformed range and outside a work tree, and byte-identical stdout
  across two runs of the same range.

  One fixture in this layer carries a path containing a newline and a path containing a
  double quote. Both `-z` decisions (D3 on the numstat read, D7 on the content read) exist
  only because of such paths, and both failure modes were reproduced by hand before the
  decisions were taken; without this fixture neither `-z` can be removed by a later
  simplification and caught.

**Structure required by "removing any one exclusion class makes the tests fail."** Each
of the three classes owns at least one test whose fixture pairs a row of that class with
a product sibling, and asserts three things: the class row is absent from `files`, its
churn is absent from `product.changed_lines`, and `excluded.<class>` counts it — while
the sibling survives all three. Deleting any single class's branch then reddens exactly
that class's tests and no others, which is the "fails for exactly one reason" bar. The
all-excluded test and the sum invariant are additional coverage, not substitutes: a suite
that only asserted aggregates could stay green if one class were folded into another.

The carve-out gets its own named test rather than riding along: given
`--artifact-path <specDir>/<this run's design>.md` and rows for both that file and a
historical spec in the same directory, only the named file is excluded. A second case
asserts that with no `--artifact-path` at all, both count.

**2. `just build`** — the Nix wiring seam. Non-destructive proof that the helper is
installed and executable, without activating:

```
p=$(nix --extra-experimental-features 'nix-command flakes' build --no-link \
      --print-out-paths '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files')
test -x "$p/.agents/bin/diff-scope"
```

That attribute path and the mode-555 result were confirmed against the current tree. The
check runs on the darwin host because that is where the work happens; the module is under
`home/common/`, so `anis-desktop` receives the same wiring by construction rather than by
a second assertion. Bare-name resolution on PATH follows from
`home.sessionPath = [ "$HOME/.agents/bin" ]`,
which is already present and already covered by
`test_workflow_skill_contracts.py::test_helper_binaries_resolve_from_bare_names`; it is
observed after an activation, and no new plumbing is added for it.

Deliberately not a seam: a skill eval. The helper is not a skill, no skill references it
in this slice, and the existing eval harness grades skill artifacts.

## Out of scope

- **Making any skill call the helper.** `ship-issue/SKILL.md`'s gate paragraph and
  `from-issue/investigate.md`'s C4 note stay verbatim. That rewrite is the behaviour
  change this slice defers, and it is what actually retires the prose. Per D14.
- **The scoped-review packet builder and its 20-file budget** — issue 24, D3/D4 of the
  codex-review-input-bound design.
- **The degradation gate's retune from 400 to 1,000 lines** — D6 of that same design.
- **Any threshold, verdict, or policy in the helper.** Per D9.
- **Three-dot ranges, working-tree diffs, staged-vs-HEAD.** Every documented call site
  already resolves its own merge-base and passes two revisions.
- **Deriving the lockfile allowlist from `SYNC.md` at runtime.** Per D13.
- **Any `patchRevision` bump.** Nothing in `patches/agent-plugins/` is touched.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Name it `diff-scope`, installed at `~/.agents/bin/diff-scope` through the existing `home.file` + `executable = true` pattern in `home/common/agent-skills/default.nix` | Matches the bare-domain half of the helper precedent (`workflow-state`, `resolve-bindings`, `context-map-lint`) and names what it measures; `home.sessionPath` already carries the directory, so no new plumbing | `agent-diff-scope` — the `agent-` prefix marks helpers that validate agent-workflow artifacts, and this one measures a git range |
| D2 | One input mode: the helper runs git itself. No stdin-numstat mode (reverses the Phase-0 lean) | The generated-header class needs blob content, so a stdin mode could not apply one of the three documented exclusions and would answer differently from the git mode — precisely the drift this extraction exists to kill; the fixture seam comes instead from importing the pure classifier, per `test_agent_model_matrix.py` | Accept numstat text on stdin as a test seam — two modes, one of which is quietly less correct |
| D3 | Read the range as `git diff --numstat -z -M <base>..<head>` and parse the three-field rename form | Verified against git 2.51.2: plain numstat collapses renames to `pkg/{old => new}/file` and C-quotes unusual paths, both lossy; `-M` explicit so the measurement does not depend on the caller's `diff.renames`, under which a pure move inflates from one zero-churn row to a delete plus a full-length add | Plain numstat plus an unquoting and brace-expansion parser; relying on git's default rename detection |
| D4 | Identify and classify every row by its destination path only — the new path on a rename, the printed path everywhere else including a deletion | The carve-out is directional — an artifact promoted into product must count — and git's own plain-numstat form already presents a rename under its new path | Exclude when either side matches: drops an artifact-to-product move and breaks the carve-out |
| D5 | A binary row is product: one file, zero lines, flagged `binary` in the ranking | The literal documented rule is "lines = additions + deletions summed, files = row count", and git reports no counts for a binary; excluding binaries would invent a fourth exclusion class the accounting never authorised | Drop binary rows; or treat `-` as a parse error |
| D6 | Detect a generated header by scanning at most the first five lines, bounded to 8 KiB, never scanning binaries | This repo's own `ship-issue/SYNC.md` contains `// Code generated by` as prose, so a whole-file scan would classify a hand-written skill doc as generated and silently shrink the product measurement | Whole-file scan; a `--no-generated-scan` escape hatch that makes an exclusion class optional |
| D7 | Pick each row's content side from `git diff --name-status -z -M` (deletion → base, otherwise head), joined to the numstat rows by destination path, then read content with one `git cat-file --batch -z`; a `missing` response is a hard error and a non-blob type is not generated | `--batch`'s line protocol splits a newline-containing path into two bogus requests while `--batch -z` returns the correct blob — reproduced on git 2.51.2; asking only for a side git said exists makes `missing` unambiguously the fail-loud case the bar demands rather than a recoverable guess; one subprocess per step keeps a review dispatch's latency path cheap | One `git show` per row with an unreadable-means-not-generated default (N subprocesses, silent fallback); probe head then fall back on `missing` (must parse an echoed name that can itself contain a newline) |
| D8 | Artifact exclusion is a repeatable `--artifact-path`, defaulting to none, repo-root-relative, matching a row when the path equals the value or begins with it plus `/`, with no filesystem access and no error when a value matches nothing (refines the Phase-0 lean's `--artifact-dir`) | `<specDir>` holds every historical spec, so directory granularity cannot express "this run's own artifacts" and would drop a historical spec that is itself the product; callers name the one or two files their run wrote, and prefix matching still covers a directory when wanted; git reports numstat paths root-relative even from a subdirectory (verified), and a run with a spec but no plan legitimately passes a path matching nothing, whose only failure direction is over-counting | `--artifact-dir`, directory-only — breaks the carve-out; defaulting to `.claude/specs`/`.claude/plans` — breaks it silently for every caller; erroring on an unmatched value — rejects a legitimate caller |
| D9 | The helper reports measurements only: no threshold, no verdict, no exit status meaning "too big" | D4 of the codex-review-input-bound design warns that the gate's ≤20 files and the scoping budget's 20 files are different decisions sharing a number; a shared constant here would fuse two policies that must move independently | A `--max-lines`/`--max-files` verdict mode that returns a pass/fail exit |
| D10 | Require the range positional to be exactly `<base>..<head>`; reject a bare revision, an empty side, and `...` with exit 1 | Every documented call site already computes `BASE_SHA=$(git merge-base ...)` and writes two-dot; a bare revision silently measures the working tree, and three-dot would need a second merge-base resolution for the blob-side reads | Pass the argument to git verbatim — permissive, and silently measures uncommitted work |
| D11 | Emit one compact JSON object by default (`sort_keys`, `ensure_ascii`) with a `--format text` companion, counting each excluded row once under the first matching class in the fixed order lockfile → generated → artifact | `agent-model-matrix` already prints machine output as `json.dumps(..., sort_keys=True, separators=(",",":"))`, and both known consumers are agents; the text form earns its place because the gate consumer quotes the numbers into a PR body or a decision line, and a quotable sentence removes the transcribe-from-JSON step that is itself a drift vector; single-class counting makes `len(files) + sum(excluded)` equal git's row count, an assertable invariant | Count a row under every class it matches — breaks the sum invariant; JSON only — pushes transcription back onto the agent; indented JSON — tokens for no reader |
| D12 | Rank by `(churn descending, raw path bytes ascending)` | A diff carries exactly one row per destination path, so path is a provably total tie-break; raw bytes keep the order locale-independent | Churn alone — not a total order, so AC5 is unmet; preserve git's emission order — deterministic only by an undocumented accident of git's path sorting |
| D13 | The lockfile allowlist lives as a constant in the helper and becomes the authoritative home for product accounting; `SYNC.md`'s identical table is left untouched | `SYNC.md`'s list governs merge auto-resolution — a different policy that merely shares today's membership, the same "two decisions sharing a value" hazard D4 warns about; parsing a Markdown table for a constant reintroduces the prose-drift vector this issue exists to remove | Parse `SYNC.md` at runtime; edit `SYNC.md` to cross-reference the helper (a change to a skill this slice must not touch) |
| D14 | Change no skill prose in this slice | The issue's stated intent is a prefactoring with no behaviour change; a doc line pointing at an uncalled helper asserts a contract nothing honours, and the consumer slice is what replaces the prose with a call | Add a "see `diff-scope`" pointer to the gate now |
| D15 | `just agent-workflow-tests` gains `test_diff_scope.py` plus the two orphaned suites `test_agent_evidence.py` and `test_agent_model_matrix.py` | No recipe runs either today — `just agent-model-matrix` runs the validator, not its tests — and both were verified green at `969f357`, so registering them cannot destabilise the gate | Register only the new file, leaving the runner's stated purpose ("verify … skill contracts") false |
| D16 | Record everything here; write no ADR and create no context-map area | The ADR gate needs all three of hard-to-reverse, surprising, and a real trade-off — but nothing consumes the contract yet, so it is at its most reversible point, and this repo has no `adr/` tree or context map outside an evals fixture, so one record would invent a whole convention for itself; the `cost-aware-model-matrix` spec settled the identical question the same way | Open `docs/areas/…/adr/` for the CLI contract — structure with no existing convention to join, and premature while the contract binds nothing |
| D17 | Ship no prose change at all: no skill edit, no README, no `CLAUDE.md` line — the slice is four files (script, suite, `default.nix`, `justfile`) | Resolves the plan brief's "whatever doc line the repo's conventions require" to *none*. The repo has no helper registry document: every helper is documented only inside the skills that call it (verified — `agent-model-matrix`/`workflow-state`/`agent-evidence` appear only in `default.nix` and in caller skills), and D14 forbids touching skill prose while nothing calls `diff-scope`. `test_workflow_skill_contracts.py::test_helper_binaries_resolve_from_bare_names` keys off skills that reference a helper, so an unreferenced helper needs no entry and the suite stays green untouched | A `CLAUDE.md` or new `scripts/README.md` entry — invents a registry convention for one row, the same objection D16 raised; a "see `diff-scope`" pointer in a skill — violates D14 |
| D18 | `test_diff_scope.py` carries its own hermetic `git_env()` (copied from `test_ship_release_contracts.py`) and drives git through `subprocess.run` **argv lists**, never a `bash -c` command string, and no shared test-helper module is extracted | D2 removed the stdin seam, so the CLI layer must build real scratch repositories; the required fixture carries a path containing a newline and one containing a double quote, which cannot survive interpolation into a shell command string, so `test_ship_release_contracts.py`'s `sh("<string>", cwd)` form is unusable here. Extracting a shared helper module would edit two already-green suites for two call sites that merely look alike — the-bar.md's "a `helpers` or `utils` module is a missing boundary" and its DRY rule ("deduplicate when the copies must change together") | Reuse or extract `sh()` — cannot express the byte-hazard fixture and churns two green suites; drive fixtures through `git commit -m` shell strings — same interpolation failure |
| D19 | Write both output formats as bytes through `sys.stdout.buffer` with `errors="surrogateescape"`; assert the non-UTF-8 path only at the classifier layer, and give the CLI layer newline and double-quote paths instead | Verified: `print()` of a surrogateescape-decoded path raises `UnicodeEncodeError`, so D11's `ensure_ascii` rationale protects the JSON *encoder* but not the *write*, and `--format text` decorates the path only where a byte would break the line format (**amended by D25** — this row originally read "emits the path undecorated", which the correctness review found to be exactly the bug); separately, APFS refuses to create an invalid-UTF-8 filename (`OSError` errno 92, verified on this host), so a CLI fixture could not carry one even if wanted, while newline and double-quote names create cleanly | Plain `print()` for both formats — crashes the text formatter on exactly the paths D3 and D7 exist to handle; a CLI fixture with a `\xff` path — cannot be created on darwin, so the suite would error rather than assert |
| D20 | `load_module()` must register the module in `sys.modules` (`sys.modules[spec.name] = module`) before `spec.loader.exec_module(module)` — so the classifier seam does **not** follow `test_agent_model_matrix.py` byte-for-byte | Verified on Python 3.13.12: a module loaded by `spec_from_file_location` and left out of `sys.modules` raises `AttributeError: 'NoneType' object has no attribute '__dict__'` from `dataclasses._is_type` for *any* dataclass field, because `from __future__ import annotations` makes annotations strings that `dataclasses` resolves through `sys.modules[cls.__module__]`. `agent-model-matrix.py` defines no dataclass so its test never hit this, and `test_agent_evidence.py` — the one suite whose script does use dataclasses — only ever runs it as a subprocess. The registration line is what the importlib docs prescribe for importing a source file directly | Copy `test_agent_model_matrix.py`'s loader verbatim as the spec's Test seams section says — every classifier-layer test errors in `setUpClass` before asserting anything; drop `from __future__ import annotations` — abandons the house style for a one-line fix |
| D21 | `parse_numstat` walks the token list **by index**, and a rename record takes its destination from `tokens[index + 2]`, consuming three tokens | Phase-5 standards review, verified empirically against git 2.51.2: `git diff --numstat -z -M` emits a rename as `<add>\t<del>\t\0<old>\0<new>\0`, so `tokens[index + 1]` is the **old** path. The plan previously prescribed `tokens[index + 1]`, contradicting its own comment. Recording the row under the old path breaks D4 (destination-keyed classification), makes the row absent from the `--name-status` map that `read_headers` requires, and takes the whole measurement to exit 1. A plain `for token in tokens` walk compounds it: the two path-only tokens are then visited as records of their own, each splitting into one field and raising `DiffScopeError` | Keep `tokens[index + 1]` — the rename test fails and the carve-out silently regresses; leave the walk unspecified — an implementer writes the obvious `enumerate` loop and 12 of 17 CLI tests fail for a reason that looks like a git-format problem |
| D22 | numstat records split with `token.split(b"\t", 2)`, never an unbounded `split(b"\t")` | Phase-5 standards review. A tab is a legal filename byte and `-z` emits path bytes verbatim (this spec's own verified-facts row), so an unbounded split yields four fields for `a\tb.txt` and hard-errors on a range the helper can measure perfectly well — the exact failure class `-z` was adopted to eliminate. The bounded split still yields three fields for a normal record, still yields `[b"0", b"0", b""]` for a rename record so the empty-path detection is unaffected, and still yields one field for a genuinely corrupt token | Unbounded split — a tab in a filename becomes an unmeasurable range; add a tab-path test fixture — APFS accepts it, but it widens the slice for a case no consumer has |
| D23 | `_parse_batch` validates the `cat-file` header shape before unpacking it, and raises `DiffScopeError` for anything unparsable | Phase-5 standards review. A `missing` answer echoes the request verbatim, so for a path holding a newline `payload.find(b"\n", ...)` stops **inside the path**: the fragment neither ends with `b" missing"` nor `rsplit`s into three parts, so the D7 fail-loud branch is bypassed and the unpack raises `ValueError`. That escapes `main`'s `except DiffScopeError` and dies with a traceback instead of the `diff-scope: <message>` line every CLI error test asserts on. The plan's own prose already promised "an unparsable header raises `DiffScopeError`"; the prescribed code could not deliver it | Leave the naive unpack — a latent traceback at exactly the boundary D7 says must fail loud; frame the batch response by scanning for the oid instead — reimplements git's framing for no gain |
| D24 | The Phase-5 standards review ran as the **native Claude reviewer**, not Codex, despite `codex.planReview.enabled = true` | The attempt deadline left ~25 minutes of shared wall clock for Phases 5-7. `codex-collaboration`'s pre-flight passed (`codex-companion` resolves), but its documented contract budgets **up to ~15 minutes** for one isolated Codex pass, which alone exceeds the margin needed to also execute and commit the plan. The skill's own timebox guidance is to fall back rather than wait. This is a deliberate timebox fallback, not a Codex runtime failure, and not a capability gap | Wait for the Codex pass — Phase 6 does not start and the attempt expires with nothing committed, the exact failure mode that killed the previous attempt on this issue |
| D25 | `--format text` escapes every C0 character and DEL in a path as a backslash escape (`\n`, `\r`, `\t` named, the rest `\xNN`) and doubles a literal backslash; `--format json` is unchanged, and a surrogate-escaped byte is left alone in both | Correctness-review finding COR-001: the text form is line-oriented, so an undecorated path split one ranked file across two physical lines — the suite's own legal `we\nird.txt` fixture already produced it. The escape is the minimum that restores "one ranked file, one physical line": it touches only characters that can end or misalign a line, so no realistic path renders differently than before, and doubling the backslash keeps it unambiguously decodable. JSON needs none of it (D11's `ensure_ascii` already escapes a control character) and the spec fixes that payload byte-for-byte, so the JSON branch is out of scope. Surrogates stay raw because `_emit` writes them back as the original bytes and none of them can end a line | Quote the whole path (shell- or `repr`-style) — changes every ordinary line for one hazard and invents a quoting dialect the caller must undo; escape only `\n` — leaves `\r` to overwrite the line on a terminal and a tab to break the column alignment; drop the text format — a documented output the design already committed to |
