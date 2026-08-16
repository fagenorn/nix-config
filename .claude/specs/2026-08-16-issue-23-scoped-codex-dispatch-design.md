# Design: scoped Codex dispatch — the caller bounds the diff before it dispatches

Issue: https://github.com/fagenorn/nix-config/issues/23
Parent design: `.claude/specs/2026-08-16-codex-review-input-bound-design.md` on branch
`worktree-codex-review-input-bound` (not on main). Its D1–D9 are binding here and are cited as
"parent D<n>"; this file's own ledger numbers restart at D1.

This is **Layer 2** of the parent design's two-layer bound — the caller side. Layer 1 (issue #24,
merged) bounds how much a reviewer *collects*, inside the plugin patch. Layer 2 bounds how much
breadth the caller *hands over* in the first place. Parent D1 makes the redundancy deliberate:
neither layer is sufficient alone, and a 20-file cap bounds breadth, not volume — three files of
five thousand lines each pass this cap untouched. Nothing in this design should be read as a claim
that the file cap bounds total input.

## Problem

`diff-review` — the correctness axis of the two-axis diff review — dispatches over whatever range
it is handed. On a large branch the reviewer receives a lightweight summary and an instruction to
inspect the diff itself, fans per-file diffs across the entire range inside the Codex app-server,
and the process is killed with no findings and no trace (upstream `openai/codex#24048`). Seven such
deaths occurred across the first end-to-end batch, on every attempt against all three of its
branches. Each costs ~15 minutes of wall clock to discover that there will be no result, and each
burns the one-time native fallback — a slot that is supposed to mean *Codex failed*, not *the diff
was big*.

The caller currently has no idea how large the change is when it dispatches. It measures nothing.

## Solution

Before dispatching `diff-review`, the packet builder measures the range in product terms with the
shared `diff-scope` helper.

- **At or under the budget** (20 product files, parent D4): dispatch exactly as today. The
  dispatched packet is identical to what today's contract produces. This is the invariant
  acceptance criterion 2 pins.
- **Over the budget**: dispatch a review of the 20 highest-churn product files, and say so — in the
  packet, in the axis verdict, and in the calling controller's provenance.
- **No measurement available**: dispatch exactly as today and record that the coverage was not
  verified.

An oversized diff is a routine bounded review. It is not a Codex failure, it never consumes the
one-time native fallback, and it never causes a retry.

Determinism is inherited, not built. `diff-scope` already ranks product rows by churn descending
with a raw-path-bytes tie-break — a total order — so the same range yields the same subset with no
new selector component (parent D3).

## Decisions

### The size pre-flight

`diff-review` gains a second pre-flight, ordered **after** the shared runtime's capability
pre-flight. If `command -v codex-companion` fails we take the capability fallback and never
dispatch, so measuring first would be wasted work; and the native flow is unscoped by construction.
A layered pre-flight is already the runtime's shape — the bridge agent runs its own
`command -v codex-companion` check after the skill has run one — so an operation-owned third check
is idiomatic here, not novel.

Two sentences of existing prose currently say the shared file owns *the* pre-flight: `SKILL.md`'s
"pre-flight first, one sub-second call", and `DIFF-REVIEW.md`'s own header listing "pre-flight"
among the shared runtime contract's parts. Both must be narrowed to the **capability** pre-flight,
or the two contracts contradict each other the moment a second one exists.

The invocation shape, run from the worktree, by bare name with the anchored path as the fallback
for shells that skip profile init (the convention every other `~/.agents/bin` helper follows):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specDir> --artifact-path <planDir> \
  --format json
```

`specDir` and `planDir` come from the caller's already-resolved bindings; a dispatcher that has none
uses the documented defaults `.claude/specs` and `.claude/plans` rather than passing no
`--artifact-path` at all, so the run's own artifacts never consume review budget by accident.

Fields read from the JSON, and only these:

- `product.changed_files` — the budget comparison, and `M` in every disclosure.
- `files[].path` — the subset, taken as the first 20 entries in the order the helper emits.
- `files[].changed_lines` — the per-file churn printed beside each path in the packet.

`product.changed_lines` and `excluded` are deliberately **not** read. They are the degradation
gate's business, not this pre-flight's; naming them here as unread is what keeps a later reader from
wiring the gate's thresholds into the scoping decision.

The budget comparison is strict: `changed_files > 20` scopes, `== 20` does not. A range that
measures zero product files — everything excluded — is under budget and dispatches whole, which is
today's behaviour.

### What the scoped packet carries

The packet stays a paths packet. It never embeds per-file diffs — that would reintroduce exactly
the prompt bloat parent D8 declined, and the shared runtime contract is "packet by paths".

Structurally, the current six numbered items are unchanged in the under-budget case. A scoped packet
differs in exactly three places (D16 narrows D7, which counted two):

- **Item 2, the scope line**, is rephrased from "review the diff `<base>..<head>` in the worktree"
  to "review the listed product files in the worktree, as changed across `<base>..<head>`", and
  gains a **coverage sentence** in substance:

  > This is a scoped review: `<N>` of `<M>` changed product files, selected as the highest-churn
  > files. Files outside the list are not under review in this pass — do not report on them, and do
  > not treat their absence from the list as evidence they are clean.

  The rest of item 2 — the correctness subject matter, and the instruction not to grade conformance
  — is untouched.

- **Item 4 becomes conditional.** Today it carries "the diff-package path when the caller built
  one, and the plan path". That diff package is `sdd/scripts/review-package`'s output, and that
  script writes an unconditional full-range `git diff -U10 <base>..<head>`; the rubric then tells
  the reviewer to read the diff file once. Handing it over on a scoped dispatch would bound what is
  graded while leaving the entire range to be read — the one thing this design exists to stop. So
  on a scoped dispatch the diff-package path does not travel, and item 4 carries the plan path
  alone: routing context is not a diff. The same omission shows on item 3's placeholder surface —
  `[DIFF_FILE]` is left unsupplied, which is a state the rubric's `**Placeholders:**` paragraph
  already contemplates, and which routes the reviewer into the rubric's "no diff file was supplied"
  branch. Unscoped and unmeasured dispatches carry item 4 exactly as today.

  The shared review package itself is untouched. sdd's final review still runs
  `scripts/review-package` once, and the conformance axis still reads that package whole; shrinking
  it would degrade an axis this issue does not own. Layer 2 changes what the *correctness packet
  points at*, never what the script produces — `sdd/scripts/review-package` gets no edit here.

- **A seventh item, present only when scoped**: the selected paths, worktree-root-relative, one per
  line, in the helper's emitted order, each with its changed-line count. It is a **collection
  instruction**, not merely a disclosure: the packet directs the reviewer to fetch the diff for
  exactly those paths — `git diff <base>..<head> -- <path>`, one bounded read per listed path — and
  to treat that set as the whole of the range under review. An unscoped packet has no item 7, which
  is what keeps "the packet contains exactly six items" true wherever it is graded today.

The rubric carries the same instruction where the reviewer will actually look for it. Its
`## Diff Under Review` paragraph already branches on whether a diff file was supplied; that branch
gains a scoped clause naming the listed paths as the whole of the range to fetch. The clause stays
conditional on what the packet declares (D11), so it is inert on an unscoped dispatch and on the
native path, where no packet ever declares a scope. Without it, a scoped packet would still meet a
rubric telling the reviewer to `git diff base..head` the whole range, and the bound would be
advisory only.

Terminology: item 2 has been called the **scope line** since the packet contract was written, and it
means *what to review for*. This design does not rename it and does not create a second thing called
a scope line. The new disclosure is the **coverage sentence**, and the value that travels to the
caller is the **scope** (`full` | `scoped: <N> of <M> product files` | `unmeasured`).

Two objections this shape has to answer:

- *Item 7 makes the "light packet" heavier.* It adds roughly twenty lines, and it removes both the
  full-range diff package and the instruction to inspect an entire range. The packet grows slightly;
  what the reviewer is asked to read shrinks by design. That is the trade the light-packet rule was
  always making.
- *A list does not stop a model fanning out anyway.* Correct, and not claimed. Layer 2 instructs;
  it does not enforce. Enforcement of collection volume is Layer 1's job inside the plugin patch
  (issue #24), which is precisely why parent D1 requires both.

Scoping bounds what is **supplied** and what is **graded**, not what may be **consulted**. The
rubric's existing carve-out — inspect code outside the diff only to evaluate a concrete named risk,
one focused check per risk — survives untouched, so cross-task integration findings that reach into
an unlisted file remain legal and remain reportable. What the reviewer may not do is silently grade
the unlisted files or imply they were covered, or read the whole range back in under cover of the
carve-out: a named risk buys one focused check, not a re-fetch of the range item 7 bounded.

Packet shape is safe to extend: the bridge agent writes the delegation prompt unchanged to a
temporary file and enqueues it, so the packet is opaque prose to the transport and no numbered-item
count is parsed anywhere in the runtime.

### The verdict discloses coverage — inside the assessment clause

`agent-evidence.py` validates a `diff-review` terminal result by `re.fullmatch` against the first
line:

```
\*\*Correctness:\*\* (?:Clean(?:\s+[—-]\s+.+)?|Findings\s+[—-]\s+.+)
```

This is a live machine consumer with test coverage, so the disclosure's position is not a matter of
taste. Anything inserted between `Clean` and the dash fails the match; anything inside the trailing
assessment clause passes. The coverage therefore opens the assessment clause:

```
**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.
**Correctness:** Findings — scoped to <N> of <M> product files; <1–2 sentence assessment>.
```

Verified against the live regex: `Clean — scoped to 20 of 44 product files; …` and
`Findings — scoped to 20 of 44 product files; …` both match, while
`Clean (scoped: 20 of 44) — …` and `Scoped Clean — 20 of 44 …` both fail. The two most natural
alternative phrasings are the two that break.

Unscoped verdicts keep today's format exactly, including the bare `**Correctness:** Clean` form the
regex still permits. A scoped review may not use the bare form: without the clause there is nowhere
for the coverage to go.

(Unrelated and untouched: the same validator matches section headings by exact text, while the
rubric template writes `### Critical (Must Fix)`. That mismatch predates this change, sits in the
heading check rather than the first-line check D6 rests on, and is not addressed here.)

The rubric that defines this format, `correctness-reviewer-prompt.md`, is deliberately
reviewer-agnostic and is also the native reviewer's own prompt. Its two new clauses are therefore
conditional on the packet rather than on the reviewer: *when the packet states the review is scoped,
the assessment clause opens with `scoped to N of M product files;`* in `## Output Format`, and *when
the packet states the review is scoped and lists the paths under review, the "no diff file was
supplied" branch of `## Diff Under Review` fetches only those paths* (D16). On the native path no
packet ever says so, and both clauses are inert.

### Provenance in both calling controllers

The skill hands the fact over, the controllers record it. `DIFF-REVIEW.md`'s disposition contract
today returns the validated result unmodified "plus the reviewer identity … for the caller's
ledger"; it now returns the **scope** alongside it, using the three fixed values above. That return
is the single hand-off point — neither controller re-derives the measurement.

"The calling controller" is whichever one dispatched `diff-review`, and both do.

- **sdd's final review** already records "both verdicts plus the correctness axis's reviewer
  identity (`Codex` | `native` | `fallback` + failure class)" in the ledger. The scope joins that
  sentence as a fourth recorded value **on the `diff-review` path only** — the recording sentence is
  conditioned on the axis having come through `diff-review`, exactly as ship-issue's is. sdd's other
  correctness path is the capability fallback, which dispatches the native reviewer directly: it
  never enters `diff-review`, never measures, and returns no scope, so it records reviewer identity
  as it does today and records no scope. Neither fixed value is stretched to cover it — `full` would
  assert a coverage nothing verified, and `unmeasured` names a `diff-review` dispatch whose
  pre-flight produced nothing, not a path that has no pre-flight. sdd's report contract to its caller
  needs no change: it already carries the per-axis verdicts, and the coverage now rides inside the
  correctness verdict's own first line.
- **ship-issue Phase 5**, on its full two-axis path, dispatches `diff-review` directly. It records
  *no* reviewer identity today — the phrase "alongside the reviewer identity it already records"
  from the issue is literally true only of sdd. Its provenance surface is the PR body, where the
  review outcome is already narrated (REVIEW.md already writes "merge-delta empty, nothing to
  review" there). The scope lands there beside the correctness verdict. Reviewer-identity recording
  is not pulled into ship-issue by this change.

`review_state` semantics are untouched. There is a structural coincidence worth writing down and
*not* relying on: an over-budget diff has more than 20 product files by the same accounting and the
same three exclusions the degradation gate uses, so it cannot satisfy the gate's ≤20-file condition
and always takes the full two-axis path. That is an observation, not a mechanism. Parent design is
explicit that the gate's thresholds and the scoping budget are two different decisions that happen
to share the number 20; this design leaves the gate alone (issue #22 owns it) and does not lean on
the coincidence to carry the disclosure obligation.

### Fallback preservation

Stated where scoping is defined, because that is where a future reader will look for it: an
oversized diff is not one of the three Codex failure classes, and scoping adds no fourth. A helper
that is absent, exits non-zero, or emits output the caller cannot parse produces *no measurement* —
never a failure, never a fallback, never a retry. The shared runtime's closed list of failure
classes ("treat only these as Codex failures") is unchanged.

When Codex does fail on a scoped dispatch, the one-time native fallback receives **the same packet**
— scoped, with its item 7 and its coverage sentence intact. The shared runtime's "same packet" rule
needs no exception, and the coverage disclosure is uniform regardless of who produced the verdict.

The separate *capability* fallback — `codex-collaboration` or the bridge agent unavailable, so the
controller dispatches the native correctness reviewer itself — is never scoped. The pre-flight lives
inside `diff-review`; a path that never enters `diff-review` never measures. That is intentional:
the native reviewer does not have the failure mode this design routes around.

### The degrade path when `diff-scope` is unresolvable

`diff-scope` is on `origin/main` but reaches `~/.agents/bin` only after a rebuild, so a machine can
legitimately have the skill and not the helper. That, a non-zero exit (a bad range, a `--root` that
is not a work tree, git unavailable), and unparsable output all collapse to one outcome: **no
measurement**. The dispatch then proceeds exactly as it does today — unscoped, six items, today's
verdict format — and the controller records `scope: unmeasured`. Nothing is disclosed to the
reviewer, because nothing about the packet differs from an under-budget one; the honest statement is
to the caller, that coverage was not verified rather than verified-full.

### Two accepted imprecisions

Both are inherited from the helper and both fail in the safe direction; they are recorded so a later
reader does not mistake them for oversights.

- **Binary rows can occupy budget slots, but never displace a text file.** `files[]` includes binary
  product rows with a churn of zero, so the churn-descending order places every one of them after
  every text row. A binary path enters the subset only once all text product files are already in
  it. The subset is therefore taken from `files[]` verbatim — filtering binary rows would be exactly
  the new selector component parent D3 forbids, for no coverage gain.
- **Artifact exclusion is path-prefix only.** Passing `--artifact-path <specDir> --artifact-path
  <planDir>` excludes historical spec and plan files too, even where those artifacts *are* the
  product — a distinction the degradation gate's prose draws but the helper cannot. The effect is to
  under-count product files, which can only make a review less scoped, never more. Scoping in the
  safe direction is the right failure for a coverage bound.

### Contract changes by file

Seven product files (six prose, one JSON fixture) plus one test file. Nothing under `patches/`,
nothing under `lib/`, no `.nix` change. That is one or two files above the issue's ~4–6 estimate,
because ship-issue turned out to need two files rather than one and the contract-test seam is
additive (per D10).

| File | Change |
|------|--------|
| `codex-collaboration/DIFF-REVIEW.md` | Owns it all: the size pre-flight and its invocation, the scoped variant of item 2 with the coverage sentence, item 4's conditional diff-package path (with `[DIFF_FILE]` unsupplied when scoped), item 7 as the bounded per-file collection instruction, the three scope values, the fallback-preservation rule, the unmeasured degrade path. Header narrowed to "capability pre-flight". Disposition returns the scope beside the reviewer identity. |
| `codex-collaboration/SKILL.md` | One narrowing only: "pre-flight first, one sub-second call" becomes the *capability* pre-flight, and an operation may define its own additional pre-flight in its reference file. Failure classes, fallback rule, and no-retry rule untouched. |
| `sdd/correctness-reviewer-prompt.md` | Output Format gains the packet-conditional coverage clause opening the assessment clause; `## Diff Under Review`'s "no diff file was supplied" branch gains the packet-conditional scoped clause naming the listed paths as the whole of the range to fetch (D16). Body stays reviewer-agnostic; the named-risk carve-out is untouched. |
| `sdd/final-review.md` | The existing "record both verdicts plus the correctness axis's reviewer identity … in the ledger" sentence gains the scope as a fourth recorded value, conditioned on the axis having come through `diff-review`; the capability-fallback path records reviewer identity as today and no scope. |
| `ship-issue/REVIEW.md` | The full two-axis section gains one sentence: the correctness axis's scope is recorded in the PR body beside its verdict. Authoritative for the mechanics. |
| `ship-issue/SKILL.md` (Phase 5) | One clause beside "Axis reports are never merged", pointing at REVIEW.md for the scope record. No dispatch selection changes, so no `agent-dispatch` comment is added or altered. |
| `codex-collaboration/evals/evals.json` | New eval 3 for the over-budget contract; one permissive clause added to eval 2. |
| `agent-skills/tests/test_workflow_skill_contracts.py` | A `DIFF-REVIEW.md` constant and one test pinning the new prose (test seam, not product). |

## Test seams

Existing seams; no new harness.

- **`just agent-workflow-tests`** (`test_workflow_skill_contracts.py`) — the deterministic seam. It
  already pins prose fragments in `codex-collaboration`'s SKILL.md and CERTIFICATION.md; the module
  gains a `DIFF-REVIEW.md` constant and one test asserting the pre-flight invocation, the anchored
  `~/.agents/bin/diff-scope` path, the ordering of capability pre-flight before size pre-flight, the
  coverage-sentence and verdict-clause contracts, and the not-a-failure-class rule. Prose is what
  this change *is*, so a prose-contract test is the strongest automated check available.
- **The `codex-collaboration` eval suite** (`just evals codex-collaboration <id>`) — the behavioural
  seam, plan-only and **manually graded**. A new eval poses an over-budget range and grades the
  pre-flight, the scoped packet (including item 4's dropped diff-package path and item 7's
  collection instruction), the coverage sentence, the verdict clause, the caller-side record, and
  the no-fallback rule. Existing eval 2 keeps grading the under-budget packet's in/out boundaries
  unchanged, with one permissive clause added so that a correct answer naming the size pre-flight
  and concluding "under budget, dispatch unchanged" is not mis-graded as a deviation.

  What the runner does and does not do matters here (D17): for `mode: plan-only`, `run-eval.sh`
  prints the prompt and the expected output, records a `PRINTED` result line, and exits 0. It
  verifies that the eval exists, is well-formed, and renders — it never produces a grade. The
  grade is a human reading a rendered transcript against `expected_output`, and it needs a named
  owner and a recorded result, or the acceptance criterion that says "the eval suite asserts … and
  passes" has none. Both existing evals in this suite are already plan-only and manually graded, so
  this states the suite's actual contract rather than changing it.
- **`just build`** — the Nix layer. No `.nix` file changes (`diff-scope` was wired to
  `~/.agents/bin` by issue #21) but the skill trees are home-manager sources, so the build is the
  regression check that the tree still evaluates and deploys.

Note for the plan phase: `CLAUDE.md` states "there is no test/lint suite — `just build` is the
verification step". That is stale — `just agent-workflow-tests` exists and is the real seam here.
Correcting `CLAUDE.md` is not in this issue's scope.

Deliberately not a seam: a live end-to-end Codex review. Non-deterministic, ~15 minutes, and the
batch showed a passing live run does not generalise across diff sizes. Evidence to record, not a
gate to block on.

## Out of scope

- **Retuning the degradation gate.** Issue #22 owns it. The gate's thresholds are not read, not
  written, and not referenced as a dependency by anything here.
- **Any change to the plugin patch, `patchRevision`, or Layer 1's collection guidance.** Issue #24,
  already merged.
- **Chunking a large diff into several sequential reviews.** Rejected in the parent design: it
  multiplies the ~15-minute slots and adds cross-chunk finding dedup.
- **Any change to the two-axis structure, the never-skip rule, the one-time-fallback rule, or the
  conformance axis.**
- **Any change to `sdd/scripts/review-package` or to the review package it produces.** Both axes
  share one package; shrinking it would degrade the conformance axis, which this issue does not own.
  D16 changes only what the *correctness packet points at* — the script, its `git diff -U10` range,
  and the conformance axis's input are all untouched.
- **Scoping the native correctness path**, whether reached by capability fallback or by a project
  opt-out.
- **Adding reviewer-identity recording to ship-issue.** It has none today; this change adds the
  scope, not the identity.
- **Reconciling the two spellings of reviewer identity** (`Codex | Claude fallback` in the skill's
  disposition contract, `Codex | native | fallback` in sdd's ledger sentence). Pre-existing, noted
  so the scope vocabulary is not made to match one of them; the scope uses its own fixed three
  values everywhere.
- **A live end-to-end Codex review as a gate.**

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Both calling controllers record the scope — sdd's final review and ship-issue's Phase 5 | "The calling controller" is whichever dispatched `diff-review`, and ship-issue's full two-axis path dispatches it directly; parent D7 puts the fact in the caller's provenance, not in one caller's | sdd only — leaves a scoped Clean undisclosed on the ship path, which is the exact hazard parent D7 exists to close |
| D2 | The scoped packet carries paths plus per-file churn, taken as the first 20 entries of `files[]` verbatim, including binary rows | The shared runtime contract is "packet by paths"; the helper's churn-descending, path-tie-broken order is already a total order, and binary rows sort last so they never displace a text file (parent D3: no new selector component) | Embed per-file diffs (reintroduces the bloat parent D8 declined); filter binary rows (a new selector component, zero coverage gain) |
| D3 | The pre-flight passes `--artifact-path <specDir> --artifact-path <planDir>` from the resolved bindings, falling back to the documented `.claude/specs` / `.claude/plans` defaults when the dispatcher has none | Matches the gate's "this run's own artifacts" exclusion; the helper takes repository-relative values and both bindings already are; a dispatcher without bindings must not silently drop the exclusion | Pass nothing (lets the run's own spec and plan consume review budget); enumerate individual artifact files (needs a plan, breaks for non-plan reviews) |
| D4 | Add a new eval for the over-budget contract; amend eval 2 only with a permissive clause about naming the pre-flight | Acceptance criterion 2 requires eval 2's under-budget in/out boundaries to stay unchanged, but a plan-only grader would otherwise read a correct pre-flight mention as a deviation | Extend eval 2 to cover both cases (dilutes the boundary it exists to grade); leave eval 2 wholly untouched (invites a false grading failure) |
| D5 | A helper that is absent, exits non-zero, or emits unparsable output yields "no measurement": dispatch exactly as today and record `scope: unmeasured` | Matches the skill's existing capability-fallback posture — a missing runtime is never converted into a Codex attempt or a failure; `diff-scope` reaches `~/.agents/bin` only after a rebuild, so absence is a real state | Treat it as a Codex failure (spends the one-time fallback on a measurement problem); block the dispatch (skips the axis, which the never-skip rule forbids) |
| D6 | The coverage disclosure opens the verdict's em-dash assessment clause, never sits between `Clean` and the dash | `agent-evidence.py` `re.fullmatch`es the first line as `**Correctness:** (Clean( — .+)?\|Findings — .+)`; it is a live, test-covered consumer, so any other position breaks bridge certification | `**Correctness:** Clean (scoped: 20 of 44) — …` — reads well and fails the regex |
| D7 | Keep item 2's existing name and meaning (the "scope line" = what to review *for*); add the coverage as a sentence within it, and put the file list in an item 7 that exists only when scoped | Two different things called a scope line is a terminology trap; keeping the unscoped packet at exactly six items is what makes "the packet is unchanged under budget" literally true | A new numbered item for the disclosure (breaks the six-item framing in the under-budget case); rename item 2 (churns a contract every consumer already knows) |
| D8 | The one-time native fallback inherits the scoped packet unchanged, coverage sentence and all | The shared runtime's rule is "the same packet"; an exception forks the packet contract, and uniform disclosure means the coverage claim does not depend on reviewer identity | Unscope on fallback — the native reviewer has no app-server memory bug, but 44 files against a ≤400-word budget is its own failure mode |
| D9 | ship-issue records the scope in the PR body beside the correctness verdict; reviewer-identity recording is not added to ship-issue | ship-issue records no reviewer identity today, so "alongside the reviewer identity it already records" cannot be followed literally there; the PR body is where REVIEW.md already narrates review outcomes | Add reviewer identity to ship-issue too (a contract it does not have, beyond this issue); record nothing on the ship path (leaves a scoped Clean silent) |
| D10 | Add `DIFF-REVIEW.md` prose assertions to `test_workflow_skill_contracts.py` alongside the new eval | The eval is plan-only and human-graded; the repo already pins skill-prose contracts in exactly this module for exactly these skills, and prose is the entire deliverable here | Eval only — satisfies the issue's letter, leaves nothing that fails in CI or in `just agent-workflow-tests` when the prose is lost |
| D11 | The rubric's coverage clause is conditional on what the packet says, not on who is reading | `correctness-reviewer-prompt.md` is deliberately reviewer-agnostic and doubles as the native reviewer's prompt; a packet-conditional clause is inert on the never-scoped native path | An unconditional coverage requirement (forces a meaningless clause on unscoped native reviews); leaving the rubric untouched (the reviewer's authoritative output-format source would not mention the obligation) |
| D12 | The size pre-flight is defined in `DIFF-REVIEW.md` and runs after the shared capability pre-flight; both places that call the shared check *the* pre-flight — `SKILL.md`'s "one sub-second call" and `DIFF-REVIEW.md`'s own header — are narrowed to the *capability* pre-flight | Measuring before the capability check is wasted when the capability is missing, and the native flow is unscoped anyway; leaving either sentence unnarrowed puts two contracts in direct contradiction | Put the size pre-flight in `SKILL.md` (it is diff-review-only; `plan-review` has no range to measure); add it without narrowing the existing prose (silently contradictory contracts) |
| D13 | Scoping bounds what is graded, not what may be consulted: the rubric's named-risk carve-out for reading outside the diff survives untouched | Cross-task integration is one of the axis's five checks, and killing it to bound input would trade a dead slot for a blind spot; the reviewer may reach into an unlisted file for a named risk but may not grade or imply coverage of unlisted files | Restrict the reviewer to the listed files absolutely (loses the cross-file findings the correctness axis exists for); say nothing (leaves the reviewer to guess whether the list is a wall or a focus) |
| D14 | Extends D10: `test_workflow_skill_contracts.py` pins the whole disclosure chain — the `DIFF-REVIEW.md` contract, the rubric's packet-conditional clause, and both controllers' record sentences (`sdd/final-review.md`, `ship-issue/REVIEW.md`, `ship-issue/SKILL.md`) — as three test methods in that one module | D10's grounding (prose is the entire deliverable and this module already pins skill prose) applies identically to acceptance criteria 6 and 7, which would otherwise have no automated pin at all; the file count in the contract-changes table is unchanged, and every prose task then carries a gate that fails at the base commit rather than a reviewer's eye | `DIFF-REVIEW.md` assertions only, gating the four remaining prose files with `grep` (a grep gate cannot pin an *absence*, so a controller sentence silently deleted later still passes) |
| D15 | Add one regression lock to `test_agent_evidence.py` asserting the live validator accepts `**Correctness:** Clean — scoped to N of M product files; …` and rejects `Clean (scoped: …) — …`; it is green at the base commit by construction and is explicitly not a task's failing gate | D6 rests entirely on a regex in `agent-evidence.py` that nothing ties to the disclosure format, and that module already owns accept/reject cases for this exact validator through its public CLI seam — the right home for the assertion | Pin the format only in `DIFF-REVIEW.md` prose (a later regex edit breaks the contract silently); call the private `_valid_mediated_result` from the contract-test module instead (no precedent in this repo, and the wrong seam) |
| D16 | **Narrows D7.** A scoped packet differs in three places, not two: item 4 drops the diff-package path (item 3 correspondingly leaves `[DIFF_FILE]` unsupplied, keeping only the plan path as routing context), item 7 is a bounded per-file collection instruction over exactly the listed paths, and the rubric's `## Diff Under Review` "no diff file was supplied" branch gains the matching packet-conditional scoped clause naming those paths as the whole of the range to fetch | The diff package is `sdd/scripts/review-package`'s unconditional full-range `git diff -U10 base..head`, and the rubric tells the reviewer to read that file once — so a scoped packet that still carries it bounds what is *graded* while handing over the whole range to be *read*, and the issue's demo criterion cannot be met; the plan path stays because routing context is not a diff; `sdd/scripts/review-package` is untouched, so the conformance axis keeps its full input | Regenerate a pathspec-limited diff file for the scoped dispatch (requires changing `scripts/review-package`, whose output the conformance axis shares); keep item 4 and rely on the rubric clause alone (the reviewer still opens the full-range file, so nothing is bounded) |
| D17 | `plan-only` evals are **manually graded**: `just evals codex-collaboration <id>` verifies only that the eval exists, is well-formed, and renders, the automated pin for the disclosure obligation is `test_workflow_skill_contracts.py`, and the manual grade is run once after Task 4 by the controller executing this plan, recorded in the plan's execution log and the PR body | For `mode: plan-only`, `run-eval.sh` prints the prompt and expected output, records `PRINTED`, and exits 0 — presence and well-formedness, never a grade — so an acceptance criterion reading "the eval suite asserts … and passes" would otherwise have no owner and no producible pass; both existing evals in this suite are plan-only and manually graded, so naming the owner states the suite's contract rather than changing it | Let the plan imply the runner grades (a vacuous gate: exit 0 is printed output, not a pass); convert the eval to `mode: pipeline` (the sandbox has no `codex-companion` runtime, no Codex auth, and ~15 min of external wall clock per dispatch) |
