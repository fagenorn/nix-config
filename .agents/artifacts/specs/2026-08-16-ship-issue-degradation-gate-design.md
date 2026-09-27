# Design: the degradation gate keeps its thresholds and stops keeping its arithmetic

Issue: https://github.com/fagenorn/nix-config/issues/22

External grounding (cited, not re-litigated):
`.claude/specs/2026-08-16-codex-review-input-bound-design.md` — **D6** (≤1,000 lines, ≤20 files)
and **D3** (the gate and the Codex pre-flight share one accounting implementation). That document
lives on branch `worktree-codex-review-input-bound`, not yet on main.
`.claude/specs/2026-08-16-diff-scope-helper-design.md` and `.claude/plans/2026-08-16-diff-scope-helper.md`
(on main) — the helper this gate now calls, and the reasoning behind its CLI.

## Problem

`ship-issue`'s Phase-5 gate decides full two-axis review versus the degraded merge-delta path. Its
size prerequisite is one sentence carrying two different kinds of knowledge at once:

> ≤400 changed lines AND ≤20 files, counted with `git diff --numstat $BASE_SHA..$HEAD_SHA` (lines =
> additions + deletions summed, files = row count) after dropping rows matching the lockfile
> allowlist, carrying a generated header … or under this run's own `<specDir>`/`<planDir>` artifacts

The **thresholds** are policy: how thorough a review this project wants. The **accounting** is
mechanism: what counts as a changed line and a changed file. Both are wrong today, for different
reasons.

**The thresholds were tuned against the wrong concern.** The gate was implicitly doubling as a guard
against oversized Codex input — a different concern with a different mechanism, which now has its own
bound. Freed of that duty, 400 is far too tight: across the first end-to-end batch of the collapsed
ladder all three branches blew it (2,816 / 3,911 / 4,451 product lines) and the merge-delta path has
never once fired in production. A gate whose degraded branch is unreachable is not a gate.

**The accounting is prose an agent hand-executes**, and as of issue 21 it is prose that contradicts a
committed implementation. `diff-scope` now owns the same six-clause rule as code, including the two
cases the prose never addressed: a binary row, for which git prints `-` instead of a count, and a
rename, whose destination path is the one that must be classified. Every hand-execution of the prose
is a chance to answer differently from the helper, and the drift is invisible because each site
produces a plausible number. The codex-review-input-bound design's D3 already promised these two
consumers one accounting implementation; nothing enforces that promise while the gate still describes
its own.

The two changes are coupled because they touch the same sentence, and because raising a threshold on
top of an unreliable measurement raises an unreliable number.

Raising the cap does not thin the review of a 900-line branch as much as the number suggests, and it is
worth being explicit about why, because it is the first objection a reader raises. Degradation is not
"review less of this branch" — it is "review only what the branch's own two-axis sdd review could not
have seen", which is the merge delta from the Phase-1 sync. The prerequisites the change leaves alone are
what earn that: `review_state` clean means both axes already came back clean on the whole branch. A
branch that never got that review carries `unknown` and never degrades at any size.

## Solution

Rewrite the gate's size prerequisite as **a policy statement plus a call**.

The policy — ≤1,000 product lines AND ≤20 product files — stays in `ship-issue/SKILL.md`, which is its
only authoritative home. The helper deliberately carries no threshold (diff-scope design D9: the
gate's twenty and the scoped-review budget's twenty are two decisions that share a number and must stay
free to move apart), so nothing else can hold it.

The accounting moves out entirely. The gate runs `diff-scope` and reads two integers. It stops naming
`--numstat`, stops defining lines as additions plus deletions, stops defining files as a row count, and
stops listing the generated-header markers. What survives in prose is exactly the part the helper
*cannot* know: which paths are **this run's own** process artifacts. That is a caller obligation, and
the rewrite makes it an instruction rather than a passive claim.

Then the boundary gets an executable referent. `ship-issue`'s evals are all `plan-only` — the runner
prints the prompt and the expected output for manual grading, and can never be green or red — so the
issue's "the eval suite asserts the 1,000-line boundary … and passes" lands in two places: eval 1's
`expected_output` for the manual grade, and `test_workflow_skill_contracts.py` for the mechanical one.

## Decisions

### The gate bullet's new shape

Line 134 of `home/common/agent-skills/skills/ship-issue/SKILL.md`, inside the
`**Pick the path first.**` list, becomes:

```markdown
- The branch diff is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count:
  `diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>`
  (executable `~/.agents/bin/diff-scope`; use the full path if the bare name does not resolve) — its first
  line reads `product: <lines> lines, <files> files`, after the helper drops lockfiles, generated-header
  files, and the artifact paths you named. The gate measures PRODUCT changes, not process artifacts, so
  pass one `--artifact-path` per **file this run wrote** — `<spec_path>`, `<plan_path>`, plus anything
  else it put there (a `research` findings file) — and never `<specDir>`/`<planDir>` themselves, which
  hold every artifact this repo has ever accepted; a historical artifact that is itself the requested
  product still counts. No measurement — helper missing, or a non-zero exit — is not a small diff: run
  the full two-axis review.
```

The implementer may adjust wording for flow; the content above is the contract. Four things about it
are load-bearing.

**`$BASE_SHA..$HEAD_SHA` is already correct and already in scope.** Phase 5 opens by defining both
(`BASE_SHA=$(git merge-base HEAD origin/<integrationBranch>)`, `HEAD_SHA=$(git rev-parse HEAD)`), so the
gate passes a two-dot range with both sides resolved — exactly what diff-scope's D10 requires and
refuses to infer.

**`<spec_path>` and `<plan_path>` are the skill's own vocabulary.** `SKILL.md`'s "Invocation paths"
paragraph already receives both from the `from-issue` handoff, and the standalone path already derives
them (`ls <specDir>/ | grep "issue-<num>"`). Phase 5 holds both file paths before the gate runs; no new
plumbing, no new binding.

**The flag is repeatable and the list is "what this run wrote", not "the two handoff fields".** The
handoff names `spec_path` and `plan_path` because those are the artifacts every run produces, but
`research/SKILL.md` writes its findings under `specDir` too, and a run that did a research pass and named
only two paths would count its own findings file as product. Naming an extra path is free — an
`--artifact-path` matching no row is deliberately not an error (diff-scope D8) — while naming too few
inflates the measurement, so the instruction points at the safe direction.

**The `--format text` first line is a documented output**, verified against the current helper on a real
range in this worktree:

```
$ diff-scope bd7b60a~3..fc498cb --format text \
    --artifact-path .claude/specs/2026-08-16-diff-scope-helper-design.md \
    --artifact-path .claude/plans/2026-08-16-diff-scope-helper.md
product: 825 lines, 6 files
excluded: 0 lockfile, 0 generated, 1 artifact
  440  .claude/plans/2026-08-16-codex-collection-budget.md
  ...
```

That run is also the clearest available illustration of why the artifact flag takes files: another run's
plan (`2026-08-16-codex-collection-budget.md`) sits under `<planDir>` and correctly counts as 440 product
lines, because this run did not write it.

The quoted `product: <lines> lines, <files> files` is a **reading aid, not a parser contract**. The gate
asks an agent to read two labelled integers, so a cosmetic change to the helper's text form would not
break the instruction, and the real line is already pinned where it is observable —
`test_diff_scope.py:567` asserts `lines[0] == "product: 5 lines, 7 files"` against a live CLI run. The
gate's contract test therefore does not reach into `diff-scope.py` to compare format strings; that would
assert an implementation detail from the wrong suite, and the helper's own CLI-layer test already fails
first if the line is renamed.

### Terminology: "product lines", not "changed lines"

The gate's old wording ("≤400 changed lines") and the helper's vocabulary disagree, and the rewrite adopts
the helper's: `diff-scope` labels its output `product:` precisely because the number is *after* the three
exclusions. Every surface this change touches uses **product lines** and **product files** — the gate
bullet, eval 1's `expected_output`, and the test constants — so that one phrase is greppable across all
three and a grader reading "product" is reading the same word the tool prints. No glossary file records
this: the repo has no context map or area tree (only an eval fixture's), and creating one for a single
term would invent a convention here for the surface the `agent-skills` README says belongs to *consuming*
projects.

### What the gate no longer says, and why the carve-out sentence is not one of them

Dropped: the `git diff --numstat` command, "lines = additions + deletions summed, files = row count",
"the lockfile allowlist" as a rule the reader must apply, and the literal markers `<auto-generated>` /
`// Code generated by`. Each is now a definition inside `diff-scope.py`, and each restatement is a copy
that can silently disagree with it — the bar's DRY rule ("every policy, format, constant and contract has
exactly one authoritative home") read literally.

Kept: one clause of intent ("the gate measures PRODUCT changes, not process artifacts") and the carve-out
("a historical artifact that is itself the requested product still counts"). The alternative considered
was stripping to a bare threshold plus a call and letting `diff-scope --help` carry everything else.
Rejected, because the carve-out is not documentation of the helper's behaviour — it is the *reason the
caller must choose the right flag values*. The helper's default is to exclude nothing (diff-scope D8);
whether a historical spec counts is decided entirely by what the gate passes. Delete the sentence and the
next agent reaches for `--artifact-path .claude/specs`, which is both easier to type and wrong.

### The invocation form: `--format text`, bare name, full-path anchor

`--format text` over `--format json` piped to `jq`. `jq` is installed system-wide
(`hosts/common/common-packages.nix:37`), so this is not an availability argument. It is diff-scope's own
D11, which justifies the existence of the text form by naming *this* consumer: "the gate consumer quotes
the numbers into a PR body or a decision line, and a quotable sentence removes the transcribe-from-JSON
step that is itself a drift vector." The text form hands the gate one line holding both integers plus an
`excluded:` line it can cite when explaining a surprising degradation. The JSON form would put a pipe, a
`jq` filter and the field paths `.product.changed_lines` / `.product.changed_files` into prose an agent
copies literally — three more things to get wrong, and JSON is the *default*, so an agent that drops
`--format` silently gets the shape the prose did not describe. The bar's Token economy rule points the
same way: fewer parameters, forms a model emits reliably.

`--root` is not passed. Phase 5 already runs every one of its git commands in the worktree, and the
helper defaults to the working directory — "let defaults absorb the common case so it need emit nothing
at all".

The bare name with a `~/.agents/bin/diff-scope` anchor is the house convention, not a stylistic choice:
`resolve-bindings`, `workflow-state`, `agent-evidence` and `context-map-lint` are all called that way
across nine skills, and `test_workflow_skill_contracts.py::test_helper_binaries_resolve_from_bare_names`
enforces the anchor for shells that skip profile init.

### When the helper cannot answer, the gate does not degrade

A new failure mode arrives with the delegation: `diff-scope` can be missing, or exit 1 (unknown revision,
`--root` not a work tree, a malformed range). The gate takes the full two-axis review in that case, and
never falls back to hand-executed `--numstat`.

This is not defensive decoration. `~/.agents/bin/` on this host currently holds five helpers and **not**
`diff-scope`: issue 21 merged the `home.file` entry at `default.nix:77`, but the machine has not been
switched since, so the symlink does not exist yet. Until the next `just switch`, an agent following the
new prose will find neither the bare name nor the full path. The rule has to be stated because it will be
exercised on day one.

The same activation lag settles a question about this change's own delivery: a skill is read through the
**activated** generation's `~/.claude/skills` link, not from the worktree, so `ship-issue`'s Phase 5 will
grade *this* branch under the gate that is currently activated (400 lines, hand-counted). That is fine —
the branch is small either way — but it means no run can demonstrate the new gate until a switch, which is
why the issue's behavioural criteria are graded by eval 1 and a recorded helper run rather than by
observing a live degradation.

Two alternatives were considered. Falling back to the prose arithmetic restores precisely the drift this
change exists to remove, and would do so on exactly the runs where nobody notices. Blocking the phase
lets a review-thoroughness optimisation stop a ship — a gate whose *failure* mode is worse than its
strictest verdict. Taking the full review is the conservative direction on both axes: it is what the gate
does today for every branch over the threshold, and an unmeasured diff is not a small diff (the bar:
truthful terminal states; a run that did no work is not a success).

### Where "asserts the boundary … and passes" lands

The issue's last acceptance criterion cannot be met inside the eval harness alone. All three ship-issue
evals are `"mode": "plan-only"`; `run-eval.sh` prints the prompt and `expected_output` for a human or CI
to grade, as the file's own `notes` field says ("ship-issue's phases push, open PRs, and merge, so
exercising them for real would need a throwaway GitHub repo"). "Asserts" is satisfiable there; "passes"
is not.

So the criterion splits across the two instruments the repo actually has:

1. **Eval 1 (`phase-walk-with-no-improvised-polling`), `expected_output`** — the fragment
   `the diff is small (≤400 lines/20 files)` becomes the retuned boundary *and* names the delegation, so
   a plan walk that recites hand-counted numstat arithmetic grades as a failure rather than as a
   stylistic difference. This is the manual-grade instrument.
2. **`home/common/agent-skills/tests/test_workflow_skill_contracts.py`** — the deterministic instrument,
   already run by `just agent-workflow-tests`. It is where this repo pins skill-markdown invariants, and
   it does not read `ship-issue/SKILL.md` yet; the change adds a `SHIP_ISSUE` path constant, a
   `SHIP_ISSUE_EVALS` path constant, and **the boundary as two module-level string constants** — the one
   place in the test file where the numbers are spelled out, reused by both tests below. That matters:
   without it the retune would leave three literal copies of "1,000" (skill, eval, test) and the test's
   copy would be a third home rather than the pin. With it, one constant asserts the policy *and* asserts
   that the two documents agree with it, so a future retune touches the skill, the eval, and exactly one
   line of test.

   - **`test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary`** — over the section
     between `**Pick the path first.**` and `**Merge-delta check (degraded path).**` (the existing
     `section()` helper): both boundary constants are present; `diff-scope $BASE_SHA..$HEAD_SHA`,
     `--artifact-path` and the no-measurement clause are present; `--numstat` and `400` are absent; and
     `assert_ordered` pins all four prerequisites still in their order (`review_state` → conflict → the
     size clause → `risky` / `criticalPaths`), which is what makes "every non-size prerequisite is
     unchanged" a check rather than a promise.
   - **`test_ship_issue_eval_restates_the_gate_boundary_it_grades`** — `evals/evals.json` carries the same
     boundary constants and no longer carries `≤400`. Two restatements of one boundary exist (verified by repo-wide grep: exactly
     `SKILL.md:134` and `evals.json:10`, no others); this test is what stops them separating again.
   - **One row added to `test_helper_binaries_resolve_from_bare_names`**, asserting `ship-issue` anchors
     `~/.agents/bin/diff-scope`. The anchor is asserted only there — its existing home — so no fragment is
     asserted twice.

   Splitting the gate contract and the SKILL↔eval agreement into two tests is deliberate: each then fails
   for one reason, and a `subTest` per fragment names which one, matching the suite's existing style.

The rejected option was updating eval 1 only. It satisfies "asserts" and leaves "passes" unfalsifiable —
a criterion no command can check is a criterion that decays. Converting eval 1 to a pipeline eval was also
rejected: per the eval file's own notes it needs a throwaway GitHub repo, which is a different and much
larger slice than retuning one gate.

Eval 1's edit stays **one clause long**. It grades a whole nine-phase walk, and the degradation gate is
one sub-clause of a paragraph; expanding it into the flag list would make a correct walk fail for omitting
detail the eval never set out to grade. The clause carries the two numbers and the delegation — nothing
about `--format`, `--root`, or which paths get named. Those belong to the skill, which is where an agent
reads them, and to the contract test, which is where they are checked.

Note what the deterministic seam does **not** claim. It pins the gate's *prose contract* — the numbers,
the delegation, the surviving prerequisites. It cannot execute the issue's behavioural criteria (a
900-line branch degrades, a 1,100-line branch does not), because the gate is prose an agent follows.
Those are graded by eval 1 and demonstrated once, by hand, on a real range. Stating that plainly is
better than a test whose name implies coverage it does not have.

### `from-issue/investigate.md`'s C4 note stays verbatim

C4 restates the artifact exclusion — "when estimating or later counting scope via `git diff --numstat`,
exclude this run's own `specDir`/`planDir` artifacts" — and is the second prose restatement the diff-scope
design named. It is nonetheless out of this slice, for a reason and not by omission: it carries **no
threshold**, so it is not "a sibling restatement of the same boundary" that this issue's scope boundary
puts in; and its primary moment is a Phase-0 *estimate* of work not yet written, where there is no range
for `diff-scope` to measure. Rewriting it is a from-issue change with its own judgement call (what does
an unwritten change's size gate call?), and folding it in here widens the slice into a second skill for
zero movement on any acceptance criterion. It is recorded as a residual, not resolved.

### No ADR, no context-map area

The diff-scope design settled the identical question for the identical area (its D16): the ADR gate needs
hard-to-reverse **and** surprising **and** a real trade-off, and this repo has no `adr/` tree or context
map outside an eval fixture, so one record would invent a whole convention for itself. Nothing has changed
since. This spec is the record.

## Test seams

Existing seams only; no new harness.

1. **`just agent-workflow-tests`** — the deterministic gate, covering all three assertions above. It
   already runs `test_workflow_skill_contracts.py` and must stay green on the six other suites it runs;
   baseline verified at this branch's base: **156 tests, OK**.

   The section anchors and the ordering were executed against the *current* `SKILL.md` before being
   written down: `section("**Pick the path first.**", "**Merge-delta check (degraded path).**")` yields a
   1,108-character section in which `review_state` → `conflict` → the size clause → `risky` →
   `criticalPaths` appear in that order, and in which `400` and `--numstat` are both **present**. That last
   part is the point — the two `assertNotIn`s fail against today's file and pass only after the rewrite,
   so they are assertions rather than decoration.
2. **`just evals ship-issue 1`** — prints the prompt and the updated `expected_output` for manual grading.
   Green/red is not available here and the plan must not pretend otherwise; the gate is "the printed
   expected output states the retuned boundary and the delegation".
3. **`just build`** — `SKILL.md` and `evals.json` are copied into the home-manager generation, so the
   build must still evaluate. This is the repo's documented sole build gate.

Deliberately not a seam: `test_diff_scope.py`. The helper is untouched, and adding a gate-flavoured test
there would assert the caller's policy inside the callee's suite — the fusion diff-scope's D9 exists to
prevent.

## Acceptance criteria

Each maps to a command the plan phase can run, or is explicitly marked as evidence rather than a gate.

| # | Criterion | Gate |
|---|-----------|------|
| A1 | The gate obtains product line and file counts from `diff-scope`, and restates no numstat arithmetic | `just agent-workflow-tests` — gate-contract test: `diff-scope $BASE_SHA..$HEAD_SHA` and `--artifact-path` present in the Phase-5 gate section, `--numstat` absent |
| A2 | The boundary is ≤1,000 product lines AND ≤20 product files | same test: both boundary constants present, `400` absent from the section |
| A3 | The invocation names the **files** this run wrote, and the historical-artifact carve-out survives | same test: `<spec_path>`/`<plan_path>` in the command, the carve-out sentence present; reviewed by eye against diff-scope D8 |
| A4 | An unmeasurable diff takes the full two-axis review | same test: the no-measurement clause is present in the gate section |
| A5 | Every non-size prerequisite is unchanged (`review_state` clean, conflict-free sync, no `risky` label, no `criticalPaths` hit) | same test: `assert_ordered` over the four prerequisites; plus `git diff` touching exactly one bullet in `SKILL.md` |
| A6 | The eval suite asserts the retuned boundary, and passes | `just agent-workflow-tests` (mechanical: SKILL↔eval agreement test) **and** `just evals ship-issue 1` printing the retuned `expected_output` (manual grade) |
| A7 | `ship-issue` anchors the helper's full path | `just agent-workflow-tests` — `test_helper_binaries_resolve_from_bare_names` gains the `ship-issue` / `~/.agents/bin/diff-scope` row |
| A8 | The generation still evaluates | `just build` |
| A9 | The boundary is spelled out exactly once in the test file, and both documents are checked against that one spelling | code review of the test module: two module-level boundary constants, no other literal `1,000` / `20 product files` in the file |
| A10 | *Evidence, not a gate:* the prescribed invocation produces the two integers on a real range | one recorded `diff-scope` run over the branch's own `$BASE_SHA..$HEAD_SHA`, quoted in the PR body — which is also the issue's demo |

## Out of scope

- **Any change to `diff-scope.py`**, its tests, or its Nix wiring. The helper is a merged contract; this
  slice is its first consumer.
- **Every non-size degradation prerequisite**, the merge-delta scope, the two-axis structure, and the
  never-skip / one-time-fallback rules.
- **The Codex review-input bound and the scoped-review packet budget** — separate issues, and per the
  codex-review-input-bound design's D4 the two twenties must stay independent decisions.
- **`from-issue/investigate.md`'s C4 note** — recorded as a residual above.
- **`ship-issue/REVIEW.md`** — it describes the merge-delta scope and checklist, not the boundary
  (verified: no `400`, no file cap).
- **Activating the change.** `~/.agents/bin/diff-scope` appears at the next `just switch`; per this repo's
  CLAUDE.md the build gate is `just build` and switching happens only when asked.
- **Deferred `diff-scope` residuals carried from issue 21.**

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Split the gate sentence in two: the thresholds (≤1,000 lines, ≤20 files) stay in `ship-issue/SKILL.md` as their only authoritative home, and the accounting is delegated wholly to `diff-scope` | the-bar's DRY rule ("every policy, format, constant and contract has exactly one authoritative home"); the codex-review-input-bound spec's D6 for the numbers and its D3 for one shared accounting implementation; diff-scope's D9 keeps the helper threshold-free so the gate is the only home available | Push the thresholds into the helper as defaults — fuses the gate's ≤20 files with the scoped-review budget's 20-file cap, two decisions the codex spec's D4 requires to move independently |
| D2 | Prescribe `diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>`, called by bare name with a `~/.agents/bin/diff-scope` full-path anchor and no `--root` | diff-scope's D11 justifies the text form by naming the gate consumer, and its first line carries both integers plus quotable exclusion counts; the-bar's Token economy (few parameters, forms a model emits reliably, defaults absorb the common case); the bare-name-plus-anchor convention is already enforced by `test_helper_binaries_resolve_from_bare_names` | `--format json` piped to `jq -r '.product.changed_lines'` — `jq` is installed, but it puts a pipe, a filter and two field paths into prose an agent copies literally, and JSON is the default so a dropped `--format` silently changes the shape |
| D3 | The gate passes one `--artifact-path` per **file this run wrote** — `<spec_path>`, `<plan_path>`, and anything else it put under those directories — never `<specDir>`/`<planDir>` themselves, and keeps the carve-out sentence as the instruction that justifies it | diff-scope's D8: directory granularity cannot express "this run's own artifacts" and would drop a historical spec that is itself the product; `ship-issue`'s "Invocation paths" already carries `spec_path`/`plan_path`, but `research/SKILL.md` also writes findings under `specDir`, so a two-field list under-names; an unmatched value is deliberately not an error, so naming extra is free while naming too few inflates the count; verified live — another run's plan under `<planDir>` correctly counted 440 product lines | Pass the two directories (silently breaks the carve-out the issue requires to survive); pass exactly the two handoff fields (misses a research findings file the same run wrote); pass nothing (over-counts on every run that wrote a spec) |
| D4 | No measurement — helper absent or a non-zero exit — is not a small diff: the gate takes the full two-axis review, and never falls back to hand-executed `--numstat` | the-bar's Fail loud and Truthful terminal states; verified: `~/.agents/bin/diff-scope` does **not** exist on this host until the next `just switch`, so the path is live on day one rather than hypothetical | Fall back to the prose arithmetic — restores exactly the drift this change removes, on the runs where nobody notices; block the phase — lets a review-thoroughness optimisation stop a ship |
| D5 | "The eval suite asserts the boundary … and passes" lands in two instruments: eval 1's `expected_output` for the manual grade, and two new tests plus one new row in `test_workflow_skill_contracts.py` for the mechanical one | All three ship-issue evals are `plan-only` and `run-eval.sh` only prints them for grading (the eval file's own `notes` explains why: real execution needs a throwaway GitHub repo), so "passes" has no executable referent there; the contracts suite is where this repo pins skill-markdown invariants and it already runs under `just agent-workflow-tests` | Update eval 1 alone — leaves "and passes" unfalsifiable; convert eval 1 to a pipeline eval — needs a throwaway GitHub repo, a far larger slice than retuning one gate |
| D6 | The deterministic seam pins the gate's *prose contract* (numbers, delegation, surviving prerequisites) and explicitly does not claim to execute the issue's behavioural criteria, which eval 1 grades and one recorded `diff-scope` run demonstrates | the-bar's "tests that can fail" — the gate is prose an agent follows, so a test named for the behaviour would assert something it cannot observe, and a test whose name overstates its coverage is worse than an honest one | Name the test for the behaviour (a 900-line branch degrades) — implies coverage no unittest over markdown can have |
| D7 | The boundary lives in the test file as two module-level string constants, asserted against both `SKILL.md` and `evals.json`; the test spells the numbers exactly once | Otherwise the retune leaves three literal copies (skill, eval, test) and the test's copy is a third home rather than the pin; one constant lets the same line assert the policy value *and* that the two documents agree with it — the-bar's DRY rule ("deduplicate when the copies must change together") applied to the enforcement, not just the prose | Two independent literals in the two tests (a retune then edits four places and can half-land); derive the boundary from `SKILL.md` by regex and assert only agreement (nothing then pins the value, so a stray edit back to 400 stays green) |
| D8 | The gate quotes `product: <lines> lines, <files> files` as a reading aid, and no test compares that quote against `diff-scope.py`'s format string | The line is already pinned where it is observable — `test_diff_scope.py:567` asserts it from a live CLI run — and the gate's instruction is "read two labelled integers", which survives a cosmetic reformat; a contracts-suite grep into the helper's source would assert an implementation detail from the wrong suite | Assert the `product: ` prefix appears in `scripts/diff-scope.py` from the contracts test — couples two suites through a source string for a failure the helper's own test already catches first |
| D9 | Every surface uses **product lines** / **product files** (the helper's own `product:` vocabulary), replacing the old "changed lines"; no glossary or context-map file is created for the term | The number is post-exclusion, so "changed" was already wrong, and one phrase greppable across skill, eval and test is what makes the three checkable against each other; the repo has no context map or area tree outside an eval fixture, and the `agent-skills` README frames that surface as belonging to *consuming* projects, so creating one here invents a convention for a single term (the diff-scope design's D16 settled the same question the same way) | Keep "changed lines" (contradicts the helper's own label and the exclusions); open `docs/CONTEXT-MAP.md` plus an area file for the term |
| D10 | `from-issue/investigate.md`'s C4 note stays verbatim; it is recorded as a residual, not resolved | C4 carries no threshold, so it is not the "sibling restatement of the same boundary" this issue's scope admits; its primary moment is a Phase-0 estimate of unwritten work, where no range exists for the helper to measure | Rewrite C4 to call `diff-scope` in the same change — widens the slice into a second skill, and needs its own judgement call about the no-range case, for zero movement on any acceptance criterion |
| D11 | A10's recorded run is persisted as `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`, produced by invoking the script directly (`python3 home/common/agent-skills/scripts/diff-scope.py`), and the file instructs the ship phase to re-run the same command fresh for the PR body rather than quoting the recorded integers | A10 is evidence consumed by a later phase, and a committed file is the only durable channel between plan execution and Phase 4/5 of `ship-issue`; the repo already carries `-evidence.md` artifacts under `specDir` (`2026-08-11-detached-reviewer-bridge-evidence.md`, `2026-08-16-c4g2-post-deploy-evidence.md`); the direct script path is forced by D4's verified fact that `~/.agents/bin/diff-scope` does not exist until a `just switch` that is out of scope; re-running fresh follows the repo's "pin fresh pre-flight per invocation" precedent (commit f2d9ef9), because review fixups and the Phase-1 sync merge move the range after the recording | Leave A10 to the ship phase alone (nothing durable to quote, and the demo silently depends on a helper that is not on PATH); quote the integers as final in the PR body (stale the moment any commit lands) |
| D12 | Each document edit ships in the same task as the test that pins it, tests written first: the two `assertNotIn`s land red against today's `SKILL.md`, the rewrite turns them green inside the same task, so `just agent-workflow-tests` is green at every commit boundary | The spec's Test seams section verified that `400` and `--numstat` are *present* in today's gate section, so a test-only task would have to commit a red suite, and a prose-only-first task would leave the rewrite unpinned at its own gate — neither gate is honest; pairing keeps the D7 constant and the document it governs reviewable together | Land all tests in one trailing task (falsifiability then has to be reconstructed by checking out the pre-rewrite file, and one commit in the middle is red); land all prose first (each prose task's gate is then a `grep` the task itself wrote, with no suite-level pin) |
| D13 | The gate-contract test asserts the **whole prescribed invocation as one span** (`diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>`) and adds `--root` to the absent list, rather than checking the range and a bare `--artifact-path` separately | Phase-5 Codex plan review: the fragment form passes against a gate that names only `<spec_path>`, which is precisely the D3 failure mode (under-naming this run's artifacts inflates the count), while the acceptance map claimed the two-path command was asserted — a test weaker than the criterion it is mapped to | Keep the separate fragments (leaves A3 claiming coverage the test does not have); assert the full bullet text (over-pins the connective wording the implementer is explicitly allowed to adjust) |
| D14 | The A10 evidence document states that its `excluded: … artifact` count covers the committed spec and plan only — the evidence file names itself but matches no row until a later re-run — and Task 3 is incomplete until its report names the evidence path plus the re-run obligation to the ship owner | Phase-5 Codex plan review: the count is measured before the evidence file is committed, so the original prose asserted something false at the moment it is written (the plan-prose ≠ code-prose rule); and `from-issue/ship-handoff.md` carries only `spec_path`, `plan_path` and a free-form summary, so nothing routes a third artifact automatically | Drop the self-naming `--artifact-path` (loses the correct count on every post-commit re-run, including the ship-time one); extend the ship handoff contract with an evidence field (a `from-issue` change, out of this slice) |
