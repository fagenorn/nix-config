# Design: the reviewer's self-collection instruction carries a budget

Issue: https://github.com/fagenorn/nix-config/issues/24
Parent design: `.claude/specs/2026-08-16-codex-review-input-bound-design.md` (branch
`worktree-codex-review-input-bound`) — this issue is that design's **Layer 1**.
Evidence: `.claude/specs/2026-08-16-codex-worker-death-research.md` (on main).
Base: `codex-plugin-cc` pinned at `db52e28f`, patch p8. Ships as p9.

## Problem

When a diff is too large to embed inline, the Codex companion hands the model a lightweight
summary and exactly one sentence of direction: inspect the target diff yourself with read-only
git commands before finalizing findings. That sentence carries no bound of any kind — not on how
many files to open, not on how much output to pull, not on the access pattern.

The model obeys it literally. The observed behaviour is dozens of per-file diffs at widened
context, fanned out across the entire range, executed inside the Rust app-server's own
tool-calling turn. That process has a documented, still-unfixed upstream defect
(`openai/codex#24048`) under which accumulated large tool output grows its memory without limit
until the OS kills it. Because the memory lives in the app-server rather than the Node worker, no
JavaScript heap trace can reach the job log — which is exactly why these deaths present as silent
and causeless, and why ~15 minutes of wall clock is spent per attempt discovering that there will
be no review.

The user-visible cost: a correctness review of a large branch reliably produces nothing, on
precisely the branches where an independent read is most valuable.

## Solution

The over-cap guidance stops being an open invitation and becomes a prescription. It states a
collection budget, orders the work — survey before diffing — points the survey at material the
packet already contains, forbids the access patterns that actually kill, and requires the model to
disclose what the budget left unread.

Nothing else moves. The under-cap ("inline-diff") guidance is byte-identical to today. Both
inline-diff thresholds are untouched (parent D8). `inputMode` semantics, the prompt template's
structure, and the caller-side Layer 2 bound are all out of scope.

This is deliberately redundant with Layer 2 (parent D1): Layer 2 is repo-owned and immediate,
this one lives in the plugin patch and takes effect only in a `claude` process launched after the
rebuild — the process-snapshot rule.

### The guidance string, verbatim

The over-cap branch returns these five lines, joined with `"\n"` — one instruction per line,
matching the one-instruction-per-line prose of the `<review_method>` block the placeholder lands
in:

```
The repository context below is a lightweight summary, so collect the rest of the evidence yourself with read-only git commands, on a budget.
Survey first: the changed-file list and diff stat included below show what changed; if they do not break the sizes down per file, get that with a single stat-level command before you read any file's diff.
Then take targeted per-file diffs, at default context, for at most 8 files — the largest changes and anything the user's focus area names.
Never take the full diff in one command, never widen the diff context, never fan out across every changed file, and never pull one very large file's diff whole.
If the change is bigger than that budget covers, review what it does cover properly and state in your summary which parts of the change you did not read.
```

Read in position — after "If the user supplied a focus area, weight it heavily, but still report
any other material issue you can defend." and before `</review_method>` — it continues the block's
imperative voice and its per-line rhythm without introducing a heading or a list.

In source it is an array literal of five one-sentence elements joined with `"\n"`, so the
zero-context patch hunk carries one reviewable line per instruction. Multi-line is safe here:
`collectionGuidance` has exactly two consumers — the prompt substitution and the tests — with no
log line, status field, or single-line assumption anywhere, and the template interpolation uses a
function replacer, so nothing in the value is re-interpreted.

The under-cap branch keeps returning, unchanged:

```
Use the repository context below as primary evidence.
```

Two phrases are preserved verbatim from today's over-cap string — *lightweight summary* and
*read-only git commands* — because the existing suite asserts both (per D3). They are also the two
clauses worth keeping on their own merits: the first tells the model what it has, the second is a
real safety constraint. No repo-side prose (skills, evals, `CLAUDE.md`) quotes either string, so
the plugin's own tests are the only consumers that constrain the wording.

## Decisions

**The collection budget is stated in files, and it is 8.** Files are the unit the model can count
before spending, the unit the packet's own stat survey reports in, and the unit the evidence is
recorded in. A byte budget is unenforceable by a model — it cannot know the size of a diff before
running it. Eight sits strictly below the 9-file floor of the observed deaths while still
permitting a substantive read. See D1.

**Two file counts on this code path are different things and must not be conflated.** The
**inline-diff cap** (2 files) decides whether the *companion* embeds the whole diff in the prompt;
it is small because everything it admits is paid for in prompt size whether or not it is relevant.
The **collection budget** (8 files) decides how many per-file diffs the *model* may pull once it is
already in self-collect mode; it is larger because those diffs are targeted by the model at the
files that matter. Parent D4's 20-file **scoped-review budget** is a third quantity again, owned by
Layer 2, and bounds which files are in scope at all. The parent design flags this exact
conflation hazard for its own pair of twenties; the same care applies here.

**Volume is bounded by the prescribed access pattern, not by a second number.** The parent design
is explicit that a file cap does not bound volume — three 5,000-line files pass any file cap while
presenting the app-server with as much accumulated output as the diffs that killed it. This design
answers that with rules the model can actually follow: survey the per-file change sizes first,
take diffs one path at a time, keep the context at its default width, never issue a whole-range
diff, and never pull one very large file's diff whole. Widened context is called out by name
because the observed killing calls used `git diff --unified=25`, which multiplies output per hunk.
The very-large-single-file clause is what makes this layer cover the case the parent design
assigns to it — a change of one or two enormous files clears any file cap untouched. See D6, D7.

**The survey step points at what the packet already contains.** Both lightweight branches already
emit stat sections and a changed-file list — `Diff Stat` + `Changed Files` for a branch target,
`Staged Diff Stat` / `Unstaged Diff Stat` + `Changed Files` for a working-tree target. The
stat-level survey is therefore a *read*, not a command to run: strictly cheaper than instructing a
`git diff --stat`, and it makes the budget spendable on the right files from the first move. The
wording holds for both target modes without branching. See D4.

**The guidance string is static.** The builder's caller has `fileCount` and `diffBytes` in hand,
but neither improves the instruction. `diffBytes` is a saturating measurement — the companion's own
probe is deliberately bounded and reports `maxBytes + 1` on overflow — so it cannot honestly
describe an over-cap diff's size, and quoting it would state a wrong number to the model. The
model gets the true per-file sizes from the stat sections already in the packet. See D2.

**The budget number is an inline literal in the string, not a new module constant.** It has one use
site, and a module-level constant would sit beside the two frozen inline thresholds — precisely
where the conflation above is easiest to make. See D1.

**Disclosure is part of the instruction.** A budgeted read that returns `approve` must not be
readable as full coverage. The prompt's output contract asks for a terse ship/no-ship summary, and
how much of the change was actually read is material to that call, so the disclosure clause fits
the contract rather than fighting it. This is parent D7's obligation echoed at the model layer;
Layer 2 still owns the caller-side provenance. See D6.

**The behaviour contract.** For `inputMode: "self-collect"`, `collectionGuidance` states a numeric
file budget, prescribes a stat-level survey before per-file diffs, and forbids a whole-range
fan-out. For `inputMode: "inline-diff"`, `collectionGuidance` is unchanged and carries none of the
budget language. `inputMode`, `fileCount`, `diffBytes`, `content` and the changed-file list are
untouched on both branches, in both target modes.

**Ships as patch revision p9.** One function in the companion's review-context builder, one new
test, one Nix line. The patch is regenerated through the repo's zero-context workflow, never
hand-edited: work in a scratch clone of the pinned rev `db52e28f`, apply with
`git apply --unidiff-zero`, regenerate with `git diff -U0 <pin>`, bump `patchRevision` 8 → 9. Any
assertion *about* the patched source reads the scratch clone or the built store path — never the
patch text, which carries no per-line file attribution.

## Test seams

Existing seams only; no new harness. Both are named by the parent design.

- **The patched plugin's own node test suite**, run env-scrubbed exactly as the repo's `CLAUDE.md`
  documents (`env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u
  CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`), or four upstream tests fail
  spuriously. The p8 baseline must hold.
  - A new dedicated test asserts the budgeted guidance on an over-cap fixture: `inputMode` equal to
    `self-collect` as a branch guard, then a behavioural regex set — the stated budget
    (`/at most 8 files/i`), the stat-first survey (`/survey/i`, `/stat/i`), and the fan-out
    prohibition (`/never fan out/i`) — strict enough that removing the budget language fails the
    suite (acceptance criterion 4) while surviving harmless rewording elsewhere in the string. The
    plan finalises the literals; these are the anchors it may not drop.
  - It follows the fixture pattern of the existing self-collect test (a three-file repo, one
    commit, three edits, resolved with no explicit scope — i.e. working-tree mode) and the file's
    `assert.match(context.collectionGuidance, /…/i)` style. The guidance does not vary by target
    mode, so one mode's fixture is sufficient coverage for the builder.
  - The existing inline-diff test gains one additive `assert.doesNotMatch` on the budget marker,
    encoding "under-cap unchanged" (acceptance criterion 2). No existing assertion is modified or
    removed anywhere in the file — the preserved phrases (D3) are what makes that possible.
  - Retuning the budget number later therefore requires updating this test. That is intended: the
    number lives in exactly two places, both of which should move together.
  - The suite must still deposit no leftover plugin state directories and leave no surviving broker
    or `codex app-server` processes; the hermetic-state-root helpers already guarantee this, and
    neither file this issue touches participates in them.
- **`just build`** — the seam for the Nix layer and the `patchRevision` bump.

Deliberately not a seam: a live end-to-end Codex review against a large branch. It is the eventual
proof, but it is slow and non-deterministic, and the parent design already records that a passing
live run does not generalise across diff sizes. Live validation is evidence to record, not a gate
to block on.

## Out of scope

- **The inline-diff thresholds** (`DEFAULT_INLINE_DIFF_MAX_FILES = 2`,
  `DEFAULT_INLINE_DIFF_MAX_BYTES = 256 * 1024`). Frozen by parent D8 and acceptance criterion 3.
- **The caller-side Layer 2 bound** — the pre-flight, the scoped packet, and its disclosure
  obligation. Separate issue, separate files, no overlap.
- **The degradation gate retune** (parent D6).
- **`inputMode` semantics** and every other field of the review context.
- **The prompt template's structure.** The placeholder's position inside `<review_method>` and the
  surrounding blocks stay as they are; only the substituted string changes.
- **Upstream `openai/codex#24048`.** Open, unowned by this repo. This design routes around it; an
  oversized input reaching the app-server by any other path would still bite.
- **The under-cap guidance string.** Byte-identical to today by acceptance criterion 2.

## Decision ledger

Rows from the parent design are cited as "parent D5" etc. and are never restated here.

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | State the collection budget as "at most 8 files", written as an inline literal in the guidance string rather than a new module constant | Files are the only unit a model can count before spending; 8 sits strictly below the 9-file floor of the observed deaths and well above the 2-file inline cap. One use site, and a constant beside the two frozen thresholds invites the number-conflation the parent design warns about | A byte or line budget (unenforceable — the model cannot size a diff before running it); reusing parent D4's 20 files (that is Layer 2's breadth cap; at 20 this layer sits above every observed death floor and adds no redundancy); 5 files (more margin, too little review for a mid-size branch) |
| D2 | Keep the guidance string static; do not parameterise it on the `fileCount` / `diffBytes` the caller already holds | `diffBytes` is a saturating measurement — the companion's probe is bounded and reports `maxBytes + 1` on overflow — so it cannot honestly describe an over-cap diff, and the packet's stat sections give the model truer per-file sizes than any number in the prompt | Interpolate `fileCount` (honest, but adds nothing the stat survey does not already supply, and widens the hunk and the test surface) |
| D3 | Preserve the phrases *lightweight summary* and *read-only git commands* verbatim inside the rewritten string, so no existing assertion changes | The suite already asserts both on the self-collect branch, and no repo-side prose quotes either; keeping them holds the p8 baseline with zero edits to existing assertions, and both clauses earn their place independently | Free rewrite plus updating the two existing assertions — larger patch, and it discards a real safety clause for no gain |
| D4 | Make the survey step read the stat and changed-file sections the packet already includes, but fall back to one stat-level command when those sections carry no per-file breakdown (revises the original D4, which asserted per-file sizes are always present) | Only the branch target emits per-file `git diff --stat` (`git.mjs:264`); the working-tree target emits aggregate `--shortstat` plus a bare filename list (`git.mjs:242-249`), so an unconditional "how large each change is" is false in working-tree mode. One stat command is bounded — one line per file — and is the survey the issue asks for, not a fan-out | Unconditionally claim per-file sizes are present (false in working-tree mode, and the model cannot then pick "the largest changes" as instructed); widen working-tree collection to per-file `--stat` (changes context collection, which is out of scope) |
| D5 | Cover the over-cap branch with a new dedicated test using a behavioural regex set plus an `inputMode` guard, and add one additive `doesNotMatch` to the existing inline test | Matches the file's one-behaviour-per-test precedent and its regex assertion style; the regex set fails if the budget language is removed (acceptance criterion 4) while surviving harmless rewording | Exact-string equality (freezes wording the design does not intend to freeze); folding the assertions into the existing self-collect test (cheaper, but buries a distinct behaviour under a test named for mode selection) |
| D6 | Have the guidance also forbid widening diff context and require the model to state in its summary which parts it did not read | The observed killing calls were `git diff --unified=25`, so context width is a named amplifier, not a generality; the disclosure clause is parent D7's obligation echoed at the model layer, and coverage is material to the terse ship/no-ship summary the output contract already asks for | Budget and sequence only — leaves the width amplifier available and lets a partial read present as full coverage |
| D7 | Forbid pulling one very large file's diff whole, as a fourth prohibition on the same line | A file cap is no bound at all when one or two files are enormous — the case the parent design explicitly assigns to this layer; without it, an over-byte-cap single-file diff would reach the app-server whole | Rely on the 8-file budget alone (leaves the parent design's stated volume hole open in the exact shape it names); add a second numeric cap in lines or bytes (unenforceable by the model, per D1) |
| D8 | Verify the regenerated patch by re-applying it with `git apply --unidiff-zero` to a second fresh clone of the pin and `diff -r`-ing that tree against the scratch clone the suite was green against | `CLAUDE.md` forbids reading the patch text to assert anything about patched source — a zero-context patch carries no per-line file attribution — so the only honest integrity check is that the artifact reconstructs the tree; `diff -r` is exact and cheap | Grep the patch for the budget string (forbidden, and a match cannot tell you which file it landed in); trust that `git diff -U0` is self-evidently correct (leaves a mis-regenerated or truncated artifact undetected until the Nix build) |
| D9 | Assert the shipped guidance by building the `agent-plugins.codex` derivation directly and grepping `plugins/codex/scripts/lib/git.mjs` inside the resulting store path, in addition to `just build` | The Nix builder applies the patch with GNU `patch -p1`, which `CLAUDE.md` documents as applying a zero-context patch at lenient offsets with no error, so a green build does not establish that the hunks landed where intended; the store path is the sanctioned read target | Treat `just build` exit 0 as sufficient (cannot distinguish a mis-landed hunk from a correct one); read only the scratch clone (proves the source edit, not the artifact the system actually consumes) |
| D11 | Every verification gate asserts the producing command's own exit status — `set -o pipefail` where output is piped to `tail`, and an explicit non-zero assertion on the expected-red run — instead of relying on reading a summary line | Codex plan review B-02: in zsh a failing `node --test` piped to a successful `tail` exits 0, so the gates as written could not fail. Acceptance criteria 4 and 6 are only meaningful if their gates can go red | Keep the human-read "Expected: `# fail 0`" convention (unfalsifiable in an autonomous run, where nobody reads the tail) |
| D12 | Assert the under-cap guidance by exact string equality, additively, alongside the existing `/primary evidence/i` match | Codex plan review S-01: acceptance criterion 2 says *unchanged*, and the spec claims byte identity, but a regex match and a `doesNotMatch` both pass for many altered strings. Equality is the only assertion that states what the criterion means, and adding it changes no existing assertion (per D3) | `doesNotMatch(/at most 8 files/)` alone (proves only that the budget language did not leak, not that the string is unchanged) |
| D13 | Make the hygiene check compare identity sets — exact `codex-plugin-test-*` directory names and broker/app-server PID sets — snapshotted immediately around each full-suite run, and scope the terminal branch audit to an explicit path whitelist against the fixed base SHA `969f357` | Codex plan review S-02/S-03: a bare count can net to zero when a concurrent sibling run deletes one dir and this run leaks another, and `origin/main` is mutable while other agents push. Identity sets and a pinned base make both gates attributable | Counts against a stale baseline and selected path groups against `origin/main` (cheaper, but cancels out concurrent deltas and drifts as siblings land) |
| D10 | Make the acceptance-criterion-5 hygiene check a before/after delta around the suite run — leftover `codex-plugin-test-*` dirs and surviving broker / `codex app-server` processes snapshotted on both sides — rather than an absolute zero | Sibling agents on this machine run the same suite concurrently, so an absolute-zero assertion fails spuriously on their state and passes vacuously when nothing else has ever run; the criterion is that *this* run deposits nothing, which is what a delta measures | Assert absolute zero (spuriously red under a concurrent sibling run); skip the check and rely on `pinHermeticStateRoot` being correct (the criterion exists to verify that machinery, not to assume it) |

## Notes for the plan phase

- With both layers live, a scoped Layer 2 packet of up to 20 files is collected under Layer 1's
  8-file diff budget, so effective per-file diff coverage on a large branch is 8 files with the
  remainder disclosed. That is the intended disclosed-scope posture (parent D2, D7), not a
  conflict — but it is the number to expect when reading a scoped review's summary.
- `plugins/codex/scripts/lib/git.mjs` and `tests/git.test.mjs` are byte-identical to the pinned
  upstream at p8. p9 adds the first hunks against both; there is no existing hunk to reconcile and
  no file overlap with the Layer 2 issue.
