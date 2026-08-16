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

- **At or under the budget** (20 product files, parent D4): dispatch exactly as today. The packet
  is byte-identical to the current contract. This is the invariant acceptance criterion 2 pins.
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

The invocation shape, run from the worktree, by bare name with the anchored path as the fallback
for shells that skip profile init (the convention every other `~/.agents/bin` helper follows):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specDir> --artifact-path <planDir> \
  --format json
```

Fields read from the JSON, and only these:

- `product.changed_files` — the budget comparison, and `M` in every disclosure.
- `files[].path` — the subset, taken as the first 20 entries in the order the helper emits.
- `files[].changed_lines` — the per-file churn printed beside each path in the packet.

`product.changed_lines` and `excluded` are deliberately **not** read. They are the degradation
gate's business, not this pre-flight's; naming them here as unread is what keeps a later reader from
wiring the gate's thresholds into the scoping decision.

The budget comparison is strict: `changed_files > 20` scopes, `== 20` does not.

### What the scoped packet carries

The packet stays a paths packet. It never embeds per-file diffs — that would reintroduce exactly
the prompt bloat parent D8 declined, and the shared runtime contract is "packet by paths".

Structurally, the current six numbered items are unchanged in the under-budget case. A scoped packet
differs in exactly two places:

- **Item 2, the scope line**, is rephrased from "review the diff `<base>..<head>` in the worktree"
  to "review the listed product files in the worktree, as changed across `<base>..<head>`", and
  gains a **coverage sentence** in substance:

  > This is a scoped review: `<N>` of `<M>` changed product files, selected as the highest-churn
  > files. Files outside the list are not under review in this pass — do not report on them, and do
  > not treat their absence from the list as evidence they are clean.

  The rest of item 2 — the correctness subject matter, and the instruction not to grade conformance
  — is untouched.

- **A seventh item, present only when scoped**: the selected paths, worktree-root-relative, one per
  line, in the helper's emitted order, each with its changed-line count. An unscoped packet has no
  item 7, which is what keeps "the packet contains exactly six items" true wherever it is graded
  today.

Terminology: item 2 has been called the **scope line** since the packet contract was written, and it
means *what to review for*. This design does not rename it and does not create a second thing called
a scope line. The new disclosure is the **coverage sentence**, and the value that travels to the
caller is the **scope** (`full` | `scoped: <N> of <M> product files` | `unmeasured`).

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

Unscoped verdicts keep today's format exactly, including the bare `**Correctness:** Clean` form the
regex still permits. A scoped review may not use the bare form: without the clause there is nowhere
for the coverage to go.

The rubric that defines this format, `correctness-reviewer-prompt.md`, is deliberately
reviewer-agnostic and is also the native reviewer's own prompt. Its new clause is therefore
conditional on the packet rather than on the reviewer: *when the packet states the review is scoped,
the assessment clause opens with `scoped to N of M product files;`*. On the native path no packet
ever says so, and the clause is inert.

### Provenance in both calling controllers

"The calling controller" is whichever one dispatched `diff-review`, and both do.

- **sdd's final review** already records "both verdicts plus the correctness axis's reviewer
  identity (`Codex` | `native` | `fallback` + failure class)" in the ledger. The scope joins that
  sentence as a fourth recorded value. sdd's report contract to its caller needs no change: it
  already carries the per-axis verdicts, and the coverage now rides inside the correctness verdict's
  own first line.
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

## Test seams

Existing seams; no new harness.

- **`just agent-workflow-tests`** (`test_workflow_skill_contracts.py`) — the deterministic seam. It
  already pins prose fragments in `codex-collaboration`'s SKILL.md and CERTIFICATION.md; the module
  gains a `DIFF-REVIEW.md` constant and one test asserting the pre-flight invocation, the anchored
  `~/.agents/bin/diff-scope` path, the ordering of capability pre-flight before size pre-flight, the
  coverage-sentence and verdict-clause contracts, and the not-a-failure-class rule. Prose is what
  this change *is*, so a prose-contract test is the strongest automated check available.
- **The `codex-collaboration` eval suite** (`just evals codex-collaboration <id>`) — the behavioural
  seam, plan-only and human-graded. A new eval poses an over-budget range and grades the pre-flight,
  the scoped packet, the coverage sentence, the verdict clause, the caller-side record, and the
  no-fallback rule. Existing eval 2 keeps grading the under-budget packet's in/out boundaries
  unchanged, with one permissive clause added so that a correct answer naming the size pre-flight
  and concluding "under budget, dispatch unchanged" is not mis-graded as a deviation.
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
| D3 | The pre-flight passes `--artifact-path <specDir> --artifact-path <planDir>` from the resolved bindings | Matches the gate's "this run's own artifacts" exclusion; the helper takes repository-relative values and both bindings already are | Pass nothing (lets the run's own spec and plan consume review budget); enumerate individual artifact files (needs a plan, breaks for non-plan reviews) |
| D4 | Add a new eval for the over-budget contract; amend eval 2 only with a permissive clause about naming the pre-flight | Acceptance criterion 2 requires eval 2's under-budget in/out boundaries to stay unchanged, but a plan-only grader would otherwise read a correct pre-flight mention as a deviation | Extend eval 2 to cover both cases (dilutes the boundary it exists to grade); leave eval 2 wholly untouched (invites a false grading failure) |
| D5 | A helper that is absent, exits non-zero, or emits unparsable output yields "no measurement": dispatch exactly as today and record `scope: unmeasured` | Matches the skill's existing capability-fallback posture — a missing runtime is never converted into a Codex attempt or a failure; `diff-scope` reaches `~/.agents/bin` only after a rebuild, so absence is a real state | Treat it as a Codex failure (spends the one-time fallback on a measurement problem); block the dispatch (skips the axis, which the never-skip rule forbids) |
| D6 | The coverage disclosure opens the verdict's em-dash assessment clause, never sits between `Clean` and the dash | `agent-evidence.py` `re.fullmatch`es the first line as `**Correctness:** (Clean( — .+)?\|Findings — .+)`; it is a live, test-covered consumer, so any other position breaks bridge certification | `**Correctness:** Clean (scoped: 20 of 44) — …` — reads well and fails the regex |
| D7 | Keep item 2's existing name and meaning (the "scope line" = what to review *for*); add the coverage as a sentence within it, and put the file list in an item 7 that exists only when scoped | Two different things called a scope line is a terminology trap; keeping the unscoped packet at exactly six items is what makes "the packet is unchanged under budget" literally true | A new numbered item for the disclosure (breaks the six-item framing in the under-budget case); rename item 2 (churns a contract every consumer already knows) |
| D8 | The one-time native fallback inherits the scoped packet unchanged, coverage sentence and all | The shared runtime's rule is "the same packet"; an exception forks the packet contract, and uniform disclosure means the coverage claim does not depend on reviewer identity | Unscope on fallback — the native reviewer has no app-server memory bug, but 44 files against a ≤400-word budget is its own failure mode |
| D9 | ship-issue records the scope in the PR body beside the correctness verdict; reviewer-identity recording is not added to ship-issue | ship-issue records no reviewer identity today, so "alongside the reviewer identity it already records" cannot be followed literally there; the PR body is where REVIEW.md already narrates review outcomes | Add reviewer identity to ship-issue too (a contract it does not have, beyond this issue); record nothing on the ship path (leaves a scoped Clean silent) |
| D10 | Add `DIFF-REVIEW.md` prose assertions to `test_workflow_skill_contracts.py` alongside the new eval | The eval is plan-only and human-graded; the repo already pins skill-prose contracts in exactly this module for exactly these skills, and prose is the entire deliverable here | Eval only — satisfies the issue's letter, leaves nothing that fails in CI or in `just agent-workflow-tests` when the prose is lost |
| D11 | The rubric's coverage clause is conditional on what the packet says, not on who is reading | `correctness-reviewer-prompt.md` is deliberately reviewer-agnostic and doubles as the native reviewer's prompt; a packet-conditional clause is inert on the never-scoped native path | An unconditional coverage requirement (forces a meaningless clause on unscoped native reviews); leaving the rubric untouched (the reviewer's authoritative output-format source would not mention the obligation) |
| D12 | The size pre-flight is defined in `DIFF-REVIEW.md` and runs after the shared capability pre-flight; `SKILL.md` is amended only to say an operation may add its own pre-flight | Measuring before the capability check is wasted when the capability is missing, and the native flow is unscoped anyway; the shared file currently reads "pre-flight first, one sub-second call", which a second pre-flight would contradict | Put the size pre-flight in `SKILL.md` (it is diff-review-only; `plan-review` has no range to measure); add it without amending `SKILL.md` (leaves two contradicting pre-flight contracts) |
