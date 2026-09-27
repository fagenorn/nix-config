# Detached-reviewer plan sync — design

Issue: fagenorn/nix-config#6 — "Sync the detached-reviewer plan's embedded snippets and gates with what
shipped (live-review S1–S3)".
Target: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` (executed, shipped via merged PR #5).
Base: `f99d7b9`.

## Problem

The detached-reviewer plan is an executed record: `sdd` ran it, it produced three commits (`377241e`,
`2bf8022`, `13b0006`), and it is the document anyone will read to understand why patch p5 looks the way
it does. Three passages in it are false against the artifacts it produced. A live Codex plan-review
caught all three (S1–S3, verbatim in
`.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md` §4):

- **S1 — the embedded test is not the test that landed.** Task 1 Step 2 dictates
  `tests/reviewer-detach.test.mjs` verbatim, and its version still defines an `async function waitFor(…)`
  retry helper and wraps the `result` call in it. The plan's *own* Phase-5 disposition D1 accepted
  replacing that with a single `result` call asserting exit 0 with stderr in the assertion message — and
  that is what shipped. The dictated text and the landed file disagree, which is the one failure a
  copy-this-block-byte-for-byte instruction cannot survive.

- **S2 — two gates cite `git diff --stat` as evidence for facts `--stat` cannot print.** Task 1 Step 6
  claims its `--stat` output shows "the patch diff includes the new `tests/reviewer-detach.test.mjs`
  hunks and the one-predicate change"; Task 3 Step 4 claims it shows "the hunks touch only the Launch
  paragraph, the failure-class bullets, and the diff-review paragraph". `--stat` prints a filename and a
  line count. It has no opinion on hunks, regions, or content. This is a direct hit on the bar's
  verification rule (`~/.agents/standards/the-bar.md`: "Run it and show the behaviour… State what you ran
  and what it printed"): a named command standing in for a check nobody could have performed with it.

- **S3 — the R6 coverage line over-claims against the gate list beneath it.** R6/AC6 forbids three things
  in the skill text — harness background tasks, completion notifications, and the launch command. Task 3
  Step 4 greps for one of them (`background`). The Spec-coverage line says "three edits + greps", reading
  as if all three prohibitions were grep-verified. Two were never written down.

None of this changes what shipped. The code, the patch, and the skill text are correct; the record of how
they were verified is not. Left alone, the next person to execute or cite this plan inherits an
instruction that produces a different file than the one in the repo, and two gates that pass while
proving nothing.

## Solution

One in-place amendment to `.claude/plans/2026-08-11-detached-reviewer-bridge.md`, in a single
`docs(plans):` commit — the repo's established post-hoc plan-sync shape (`8cee250` +33/-2, `59f3303`
+14/-9: both single-file amendments to an executed plan that fix embedded dictated text and stated
`Expected:` values while leaving every recorded decision intact).

### Why amending an executed plan is legitimate

The strongest objection to this whole issue is `the-bar.md`'s rule on records: "Point-in-time records —
accepted decisions, past plans, published reports — keep their original paths: a citation into an
accepted record is part of that record, and rewriting it invalidates the thing it was evidence for."
A past plan is named in that list. So why edit one?

Because the rule protects **what the record attests** — its path, its citations, its decisions — and an
executed plan in this repo carries two different kinds of text:

| kind | example | on drift |
| --- | --- | --- |
| **attestation** — what was decided, reviewed, dispositioned | `## Auto-resolved decisions`, `## Standards review (Phase 5)`, D1, D2 | never rewritten; a later fact is recorded elsewhere |
| **instruction** — dictated bodies and `Run:` / `Expected:` gates | Task 1 Step 2's test block, the Step 4 gate list | synced to what shipped; a stale instruction is a live defect |

S1–S3 are all instruction drift. The amendment touches no attestation: D1 and D2 stay byte-stable, and D1
in particular becomes the *provenance* of the synced snippet rather than a pending correction. This is
exactly the split both precedent commits took — `8cee250`'s subject is literally "sync embedded template
text **and record** final-review dispositions": synced instructions, appended (never edited)
attestations.

### The four passages

1. **Task 1 Step 2's embedded test block** → resynced to the landed file, byte-for-byte.
2. **Task 1 Step 6's regeneration gate** → `--stat` demoted to a labelled file-level summary; a patch
   hunk-header grep carries the "the new test is in the patch" claim; the two guard-message greps already
   in the step are named as what carries the "one-predicate change" claim.
3. **Task 3 Step 4's gate list** → the two missing R6 prohibition greps added; `--stat` demoted the same
   way; a hunk-header listing plus a full-diff read carry the "exactly three regions" claim.
4. **The Spec-coverage R6 line** → restated to name exactly the gates that now exist.

Nothing here is a stronger check invented after the fact. Each replacement either already existed in the
step, or is the check the evidence spec records as having been performed during execution ("byte-for-byte
body diff; whole-file stale-prose sweeps"), now written down.

### Verification provenance (stated precisely, because that is the point of this issue)

Every gate quoted below was run at `f99d7b9` before being written down. Two of them were run in their
**committed** form rather than the working-tree form the plan prescribes: the plan says
`git diff [-U0] -- <SKILL.md>` because Task 3 Step 4 runs before Task 3's commit, whereas at `f99d7b9`
that change is already committed, so it was checked with
`git show [-U0] 13b0006 -- <SKILL.md>`. Same change, same hunks; different command. Saying "`git diff`
was run" would be the same species of claim S2 exists to remove.

## Decisions

### D-1 · S1: the whole-block resync *is* the `waitFor` removal

Extracting the plan's embedded snippet (164 lines) and the landed `tests/reviewer-detach.test.mjs` from
inside `patches/agent-plugins/codex-plugin-cc.patch` (150 lines, a `new file mode` hunk) and diffing them
yields **exactly two hunks, both at the `waitFor` sites, and nothing else**. Measured, not assumed. The
two readings of AC1 therefore collapse into one edit, after which the block is byte-identical to the
shipped file.

**Hunk A** — delete the helper and its trailing blank line, leaving the blank line after `GUARD_MESSAGE`
followed directly by `function makeReviewRepo()`:

```js
async function waitFor(predicate, { timeoutMs = 5000, intervalMs = 50 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = await predicate();
    if (value) {
      return value;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Timed out waiting for condition.");
}
```

**Hunk B** — in test 1, replace the retry wrapper:

```js
  const resultPayload = await waitFor(() => {
    const collected = run("node", [SCRIPT, "result", launchPayload.jobId, "--json"], { cwd: repo, env });
    if (collected.status !== 0) {
      return null;
    }
    return JSON.parse(collected.stdout);
  });
```

with the landed form — comment included, because the comment is part of the shipped file and states why
the retry is unnecessary:

```js
  // status --wait reported `completed`, so the record is terminal: one direct
  // `result` call must succeed — no retry loop.
  const collected = run("node", [SCRIPT, "result", launchPayload.jobId, "--json"], { cwd: repo, env });
  assert.equal(collected.status, 0, collected.stderr);
  const resultPayload = JSON.parse(collected.stdout);
```

Test 1's `async () => {` stays even though no `await` survives in its body — that is how the file shipped,
and matching the artifact beats tidying it.

Arithmetic: 164 − 12 (helper + blank) − 2 (7-line wrapper → 5-line body) = **150**, which is what makes the
amended Task 1 Step 6 gate self-consistent: the hunk header it expects is `@@ -0,0 +1,150 @@`.

Nothing else in the plan references the helper. `waitFor` appears at exactly three lines (the definition,
the call, and D1); the other `retry` / `poll` hits belong to the agent-definition body, the decision entry
that quotes it, and Task 2's commit message — all about the bridge's prohibition on polling loops,
unrelated and untouched.

### D-2 · S2a: Task 1 Step 6 — `--stat` summarises, greps prove

Replace the two lines at the head of the step's gate block with:

> Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`
>
> Expected: a summary line only — exactly these two files modified, nearly all the lines landing in the
> patch. `--stat` counts changed lines; it cannot show which hunks the regenerated patch gained or what
> they contain, so the three content checks below carry those claims.
>
> Run: `grep -A5 "^diff --git a/tests/reviewer-detach\.test\.mjs" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
>
> Expected: one match, showing `new file mode 100644` and the whole-file hunk header `@@ -0,0 +1,150 @@` —
> the new test enters the patch as a single added-file hunk of exactly the block Step 2 dictates.
>
> The one-predicate change in `plugins/codex/scripts/codex-companion.mjs` is what the next two greps
> prove — the old guard message gone from the patch entirely, the new one present exactly twice:

The two guard-message greps that follow (`Reviewer jobs must be fresh, foreground` → exit 1;
`Reviewer jobs must be fresh and read-only.` → `2`) are **unchanged**. They were always the real
content-level proof of the predicate change; the amendment only stops `--stat` from claiming their work.

Verified at `f99d7b9`: the `grep -A5` returns exactly one match, showing `new file mode 100644` and
`@@ -0,0 +1,150 @@`; the patch contains five `new file mode` hunks but only one `@@ -0,0 +1,150 @@`;
`377241e` is 2 files changed, 160 insertions, 4 deletions.

### D-3 · S2b + S3: Task 3 Step 4, the full replacement gate list

The step keeps its title ("Verify the edits are exactly the three regions") — it already carried
prohibition greps before this change, so the title was never a literal table of contents. Its body
becomes, in full (the plan spells the SKILL.md path out on every line; abbreviated to `<SKILL.md>` here
for readability):

> R6's three prohibitions, one case-insensitive grep each — match on exit status, not on printed output:
>
> Run: `grep -in "background" <SKILL.md>`
>
> Expected: no output (exit 1). At this task's starting commit the same grep matches in the Launch
> paragraph ("as a background / Bash task") and the diff-review paragraph ("with background launch inside
> the bridge") — this gate fails until both edits land.
>
> Run: `grep -in "codex-companion task" <SKILL.md>`
>
> Expected: no output (exit 1). This gate also fails until Step 1's edit lands: at the starting commit the
> old Launch paragraph names the launch command itself, `codex-companion task --fresh --reviewer
> --timeout-ms 840000`. Matched on the two-word form deliberately — the bare word must survive in the
> pre-flight `command -v codex-companion`, which this task does not touch.
>
> Run: `grep -in "completion notification" <SKILL.md>`
>
> Expected: no output (exit 1). Unlike the other two this one already passes at the starting commit — the
> wording has never been in this file, and the gate is here so the rewrite cannot introduce it. The bridge
> reports by returning its output, never by notifying.
>
> Run: `grep -n "the process crashes or reaches its hard timeout" <SKILL.md>`
>
> Expected: no output (exit 1) — the process-level failure class is gone.
>
> Run: `grep -c "Launch mechanics live solely" <SKILL.md>`
>
> Expected: `1`.
>
> Run: `git -C "$WORKTREE" diff --stat -- home/common/claude-code/skills/codex-collaboration/SKILL.md`
>
> Expected: a summary line only — one file changed, a handful of lines. `--stat` cannot show *which*
> regions moved; the two checks below carry that claim.
>
> Run: `git -C "$WORKTREE" diff -U0 -- home/common/claude-code/skills/codex-collaboration/SKILL.md | grep '^@@'`
>
> Expected: exactly three hunk headers — one in the `## Launch` second paragraph (~line 96), one in the
> `## Validate and fall back` bullet list (~line 114), one in the diff-review mechanics clause (~line
> 155). A fourth header means a stray edit landed: revert it.
>
> Run: `git -C "$WORKTREE" diff -- home/common/claude-code/skills/codex-collaboration/SKILL.md`
>
> Expected: read all three hunks. Each removes exactly the Old text and adds exactly the New text dictated
> in Steps 1–3; no other line in the file differs.

Every existing gate keeps its relative order; the two new ones are inserted directly after their sibling
`background` gate so the R6 sweep reads as one unit.

Measured at `f99d7b9` (greps against the live file; diff facts via `git show [-U0] 13b0006`):

| grep (case-insensitive) | before `13b0006` | live |
| --- | --- | --- |
| `background` | 2 | 0 (exit 1) |
| `codex-companion task` | 1 | 0 (exit 1) |
| `completion notification` | 0 | 0 (exit 1) |
| `codex-companion` (bare) | 2 | **1** — the pre-flight `command -v codex-companion` |

`13b0006` is 1 file, +11/-8, with **exactly three hunks** in both default-context and `-U0` form; the
`-U0` headers are `@@ -96,5 +96,7 @@`, `@@ -114,2 +116,3 @@`, `@@ -155 +158 @@`.

### D-4 · S3b: the Spec-coverage R6 line names the gates

R6's prohibitions come from the design spec's requirement table
(`.claude/specs/2026-08-11-detached-reviewer-bridge-design.md`: "…no longer mentions harness background
tasks, completion notifications, or the launch command"), which is why the three greps map 1:1 onto it.
The coverage line becomes:

> - R6/AC6 (skill states contract only; no background tasks / completion notifications / launch command):
>   Task 3 — the three edits, plus Step 4's one case-insensitive negative grep per prohibition
>   (`background`, `codex-companion task`, `completion notification`, each exiting 1 against the edited
>   file) and the positive `Launch mechanics live solely` pin.

### D-5 · What does not change

`## Standards review (Phase 5)`, including D1 and D2, stays byte-stable (see "Why amending an executed
plan is legitimate"). D2's ruling — implementers match on exit code, not on `grep -c` output — is the
rule the new S3 gates are written to, so the amendment honours it rather than editing it.

## Test seams

A documentation amendment is tested at the same seam the plan itself uses: **every command the amended
text names, run against the shipped artifacts, with its stated expectation observed**. No new seam is
invented. Three checks, all runnable from the worktree at HEAD:

1. **Snippet-equals-artifact (the S1 seam).** Extract the fenced block from Task 1 Step 2, extract the
   added lines of the `tests/reviewer-detach.test.mjs` hunk from
   `patches/agent-plugins/codex-plugin-cc.patch`, `diff` them. Expect empty output, exit 0. This is the
   plan's own idiom — Task 3 Step 5 already gates patch determinism with a
   `git diff -U0 "$PIN" | diff - "$WORKTREE/…patch"` diff-to-empty check.
2. **Every amended gate, actually executed**, against the live file for the greps and against `13b0006`
   for the diff-shape facts (provenance stated above). Prior art: `59f3303` corrected a stated `Expected:`
   value ("sdd (1)" → "sdd (3, all in §Finish)") by measuring it first.
3. **AC5 single-file check.** `git show --stat HEAD` on the amendment commit names exactly
   `.claude/plans/2026-08-11-detached-reviewer-bridge.md`. AC5 scopes to that commit: this run's own
   from-issue artifacts (this spec, and any plan file) are separate commits under `.claude/`, not part of
   the amendment diff.

Prior art for the whole shape: `8cee250` and `59f3303`, the repo's two existing plan-sync commits.

## Out of scope

- **The shipped artifacts.** `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`,
  `home/common/claude-code/skills/codex-collaboration/SKILL.md`, and the plugin sources are correct and
  are not touched. The plan text moves to them, never the reverse.
- **The evidence spec.** `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md` §4 already
  records S1–S3 and their dispositions; this issue promotes those dispositions into the plan, it does not
  restate them elsewhere.
- **The plan's attestations.** `## Auto-resolved decisions`, `## Standards review (Phase 5)`, D1, D2, and
  the Phase-5 verdict are byte-stable.
- **No provenance note is added to the plan.** `8cee250` added an "Execution reviews" paragraph to its
  plan's provenance section, but the equivalent section here is `## Standards review (Phase 5)`, which is
  out of scope. Provenance lives in the commit message, this design doc, and the evidence spec.
- **Task 2 Step 6's `grep -c "run_in_background: true" … || true  # 0`.** The same cosmetic class D2
  already dispositioned as accepted; a different step, named by no acceptance criterion.
- **Any other `--stat` or gate in the plan.** There are exactly two `--stat` occurrences (the two S2
  sites); Task 2's regeneration step verifies through built-closure content greps and needs no change.
- **Re-running the plan.** This amends a record of merged work; nothing is re-executed and no `just build`
  is required (no `.nix` file changes).
- **No ADR.** The repo has no ADR convention and no `docs/` tree; the decisions live in this spec, per the
  issue's binding.

## Auto-resolved decisions

### S1 resync scope: whole block or just the `waitFor` sites?
- **Question:** Does AC1 require resyncing the entire Task 1 Step 2 block against the landed test body, or
  only removing the `waitFor` definition and its call?
- **Choice:** Both — they are the same edit. Diffing the extracted plan snippet against the extracted
  landed test showed exactly two differing hunks, both at the `waitFor` sites. Apply those two; the block
  is then byte-identical to the shipped file (164 → 150 lines).
- **Grounding:** Measured at `f99d7b9`: plan L178–341 vs `codex-plugin-cc.patch` L1703–1852 (de-`+`-ed)
  differ only at the helper definition and the `result` call site. AC1's own wording ("contains no
  `waitFor` definition or call; the `result` collection appears as a single call whose assertion carries
  stderr") is satisfied exactly by those two hunks.
- **Alternative considered:** Wholesale replacement of the fenced block with the extracted patch text —
  identical result, larger and less reviewable diff, and it risks laundering an unnoticed difference
  through a bulk paste instead of surfacing it.

### Keep `async` on test 1 although no `await` remains
- **Question:** After the retry loop goes, test 1's arrow function has no `await` left. Drop `async`?
- **Choice:** Keep it. The plan must show what shipped.
- **Grounding:** The landed file (patch L1741) reads
  `test("a background reviewer run survives its launcher and lands a verbatim durable result", async () => {`.
  The block exists to be copied byte-for-byte into the scratch checkout (plan Global Constraints: "copied
  byte-for-byte from this plan").
- **Alternative considered:** Dropping `async` as a tidy-up — it would make the plan false in a *new* way
  and, if executed, regenerate a patch that differs from the shipped one.

### Leave D1 in place after the snippet is synced
- **Question:** With the retry gone from the snippet, does D1's disposition ("dead `waitFor` retry around
  `result` in Task 1 test 1") become stale and need rewording?
- **Choice:** Leave it byte-stable. It is a true record of a review exchange and now reads as the
  provenance of the synced text.
- **Grounding:** Issue scope boundary ("the plan's recorded D1/D2 dispositions … OUT"); `the-bar.md`'s
  point-in-time-records rule, applied to attestations as split out under "Why amending an executed plan is
  legitimate"; `8cee250` amended embedded text while leaving its recorded dispositions intact.
- **Alternative considered:** Appending "(synced 2026-08-11)" to D1 — edits the one section the issue put
  out of bounds, for information the commit message already carries.

### Reconciling the amendment with the-bar's "point-in-time records" rule
- **Question:** `the-bar.md` says past plans are point-in-time records that must not be rewritten. Does
  that forbid this issue outright?
- **Choice:** No — split the plan's text into attestations (never rewritten) and instructions (synced to
  what shipped), and confine the amendment to the second. Recorded in the spec body, since the repo has no
  ADR tree to hold it.
- **Grounding:** The rule's own wording protects citations *into* a record ("a citation into an accepted
  record is part of that record"); a dictated code block and a `Run:`/`Expected:` gate assert nothing
  about the past, they instruct a future executor. Both precedent commits took exactly this split —
  `8cee250` synced embedded template text in the same commit that *appended* new dispositions.
- **Alternative considered:** Treating the plan as immutable and recording the corrections only in the
  evidence spec — leaves a live instruction in the repo that regenerates a different patch than the one
  committed, and the issue explicitly rejects it by naming the repo's `docs(plans): sync…` practice.

### What carries the content claim in Task 1 Step 6
- **Question:** `--stat` cannot show the patch gained the test hunks and the predicate change. What
  replaces it, without inventing a gate nobody ran?
- **Choice:** Keep `--stat` as an explicitly labelled file-level summary; add one hunk-header grep
  (`grep -A5 "^diff --git a/tests/reviewer-detach\.test\.mjs" <patch>`) for the new test; name the two
  guard-message greps *already in the step* as the proof of the one-predicate change.
- **Grounding:** Issue text: "Reword those gates to the content-level checks that were actually run
  (patch-content greps, hunk inspection)". The two guard greps are already present at Task 1 Step 6 and
  are patch-content greps; the hunk-header grep verified true at `f99d7b9`.
- **Alternative considered:** Re-applying the patch to a scratch checkout and diffing the test file
  byte-for-byte — the stronger check the sdd reviewer ran, but as a *gate* it duplicates Task 3 Step 5's
  determinism check and adds a scratch-checkout dependency to a step that has none.

### `grep -A5` although the plan's house style is `grep -c` / `grep -n`
- **Question:** The plan uses `grep -c` (8×), `grep -n` (2×), `grep -in` (1×) and never `-A`. Should the
  new patch check use two house-style greps (`-n` on the `diff --git` line, `-c` on the hunk header)
  instead?
- **Choice:** Use `grep -A5`. One command, and it shows the two facts *adjacent* — which is the actual
  claim ("the test lands as one added-file hunk"), not two independently-true counts.
- **Grounding:** `@@ -0,0 +1,150 @@` occurs once in the patch, but the patch has five `new file mode`
  hunks, so a separate count of each would not prove they belong to the same file. The plan already
  carries richer multi-command bash blocks with inline expected values (Task 2 Step 6, Task 3 Step 5), so
  a second grep flag is not a style break. Preferring a weaker check for flag consistency would repeat the
  S2 mistake.
- **Alternative considered:** The two-grep house-style form — cheaper to read, strictly weaker.

### State the hunk header as `@@ -0,0 +1,150 @@` or as a placeholder
- **Question:** Should the new Task 1 Step 6 gate pin the exact added-file hunk header, or leave the line
  count open (`@@ -0,0 +1,<n> @@`)?
- **Choice:** Pin `@@ -0,0 +1,150 @@`.
- **Grounding:** Step 2 dictates the file verbatim, and after the S1 amendment that block is exactly 150
  lines — so the plan determines the count itself, and the pin doubles as a cross-check between the two
  amended passages. Confirmed against the committed patch. The plan's house style pins exact expected
  values elsewhere (`Expected: 2`, `# tests 107 / # pass 103`).
- **Alternative considered:** A `<n>` placeholder — weaker, and the plan's Global Constraints treat exact
  falsifiable expectations as the norm.

### How Task 3 Step 4 proves "exactly the three regions"
- **Question:** What replaces `--stat` for the claim that only the Launch paragraph, the failure-class
  bullets, and the diff-review clause changed?
- **Choice:** Two checks — a hunk-header listing (`git diff -U0 … | grep '^@@'`, expect exactly three
  headers at the named line ranges) and a full `git diff` read against the Old/New text pairs Steps 1–3
  dictate. `--stat` is kept as an explicitly labelled summary.
- **Grounding:** Verified against `13b0006`: exactly three hunks in both default and `-U0` form, headers at
  `@@ -96,5 +96,7 @@`, `@@ -114,2 +116,3 @@`, `@@ -155 +158 @@`. The evidence spec records the executed
  check as a "whole-file stale-prose sweep" — reading the diff is that check, written down.
- **Alternative considered:** A hunk *count* alone (`grep -c '^@@'` → `3`) — a count cannot show
  *location*, which is precisely the claim being made; a smaller version of the same error.

### Use `-U0` for the hunk-header listing
- **Question:** Default context or `-U0`?
- **Choice:** `-U0`.
- **Grounding:** Three reasons. `-U0` headers point at the changed lines themselves (~96 / ~114 / ~155), so
  the stated ranges mean something; with zero context there are no context lines, so `^@@` matches hunk
  headers and nothing else (a markdown line beginning `@@` could otherwise appear as context); and `-U0`
  is this plan's established diff idiom (Global Constraints: the patch is zero-context, regenerated with
  `git diff -U0`).
- **Alternative considered:** Default context — ranges padded by three lines, reading as approximate, and
  `^@@` no longer provably header-only.

### Where the two new prohibition greps sit in the gate list
- **Question:** Insert the `codex-companion task` and `completion notification` greps where?
- **Choice:** Immediately after the existing `background` grep, at the head of the step, under one lead-in
  line naming them as R6's three prohibitions. Every existing gate keeps its relative order.
- **Grounding:** The three greps are the three parts of one requirement (design spec R6: "harness
  background tasks, completion notifications, or the launch command"); grouping them makes the amended
  Spec-coverage R6 line checkable at a glance. Minimal disturbance to existing text is the shape of both
  precedent commits.
- **Alternative considered:** Appending them at the end of the list — separates them from their sibling
  gate and leaves the R6 sweep scattered through the step.

### Expectation phrasing: exit status, not `grep -c`
- **Question:** State the new gates as `grep -c … → 0` or as `grep -in …` with "no output (exit 1)"?
- **Choice:** `grep -in`, "Expected: no output (exit 1)", under a lead-in telling the implementer to match
  on exit status rather than printed output.
- **Grounding:** The plan's own D2 disposition: "the exit-1 expectation in the gate is already correct,
  implementers should match on exit code." It is also the exact phrasing of the two negative gates already
  in this step, so the list stays internally consistent. AC3 requires case-insensitive greps → `-i`; `-n`
  matches the neighbouring gate's flags.
- **Alternative considered:** `grep -c` → `0` — contradicts a recorded disposition in the very document the
  amendment is making truthful.

### Scope the launch-command grep to `codex-companion task`
- **Question:** Grep for the bare `codex-companion`, or the two-word `codex-companion task`?
- **Choice:** `codex-companion task`, and say in the gate why.
- **Grounding:** Measured on the live SKILL.md: bare `codex-companion` returns **1** match — the legitimate
  pre-flight `command -v codex-companion` at line 88, which R6 does not prohibit and Task 3 does not touch.
  A bare-word gate would be permanently red. AC3 names the two-word form.
- **Alternative considered:** Bare word with a documented exception count (`grep -c` → `1`) — brittle (any
  future legitimate mention breaks it) and it inverts a prohibition into a census.

### Describe the two new gates in the file's own idiom, not new jargon
- **Question:** The two new greps behave differently — `codex-companion task` goes 1 → 0 across Step 1's
  edit, `completion notification` was never present. Coin labels ("flipping gate" / "standing
  prohibition") to mark the difference?
- **Choice:** State the difference in plain prose reusing the file's existing phrasing — "this gate fails
  until Step 1's edit lands" for the first, "unlike the other two this one already passes at the starting
  commit … the gate is here so the rewrite cannot introduce it" for the second. No coined terms.
- **Grounding:** The plan already expresses exactly this idea at the `background` gate ("this gate fails
  until both edits land"); "gate" is house vocabulary (used at L27, L131, L649, L722), "flipping gate" is
  not. Introducing jargon into a document being amended for accuracy adds a second thing for a reader to
  resolve. Stating them identically would have been a fresh inaccuracy in a commit whose purpose is
  removing them.
- **Alternative considered:** One undifferentiated bullet list — cheaper, and it quietly reintroduces the
  class of error S2 is about (a check described as proving more than it does).

### State verification provenance precisely (`git show` vs `git diff`)
- **Question:** The amended Task 3 gates prescribe `git diff` (uncommitted, mid-task), but at `f99d7b9` the
  change is committed, so they were verified with `git show … 13b0006`. Claim "the gates were run"?
- **Choice:** No — say which form was run and why it is the same change, in the spec body.
- **Grounding:** `the-bar.md`: "State what you ran and what it printed, or say plainly that you did not
  verify." Claiming the prescribed command was run when a different one was is the exact species of defect
  S2 documents.
- **Alternative considered:** Reconstructing an uncommitted working-tree state to run `git diff` verbatim —
  ceremony for an identical result on a docs change.

### Leave Task 2 Step 6's cosmetic `grep -c … || true  # 0`
- **Question:** Task 2 Step 6 uses the same `grep -c` cosmetic pattern D2 flagged. Fix it while nearby?
- **Choice:** Leave it.
- **Grounding:** D2 dispositioned this class as "accepted as cosmetic"; no acceptance criterion names Task
  2; the issue's scope is four passages. Smaller and more reversible wins.
- **Alternative considered:** Sweeping every `grep -c` in the plan to exit-code form — defensible, but it
  widens a deliberately narrow docs-accuracy diff and re-litigates a settled disposition.

### Keep Task 3 Step 4's title unchanged
- **Question:** The step gains two prohibition greps; does "Verify the edits are exactly the three regions"
  still fit?
- **Choice:** Keep the title.
- **Grounding:** The step already contained two prohibition greps before this change, so the title was
  never a literal contents list; no AC mentions it; retitling widens the diff for no truth gained.
- **Alternative considered:** "Verify the prohibitions and the three regions" — marginally more accurate,
  churns a heading other text may reference.

### One commit, `docs(plans):` subject
- **Question:** One commit or one per finding?
- **Choice:** One commit, subject `docs(plans): sync detached-reviewer plan snippets and gates with what
  shipped`, ending with the configured `Co-Authored-By: Claude Opus 5 (1M context)` trailer, SSH-signed by
  default, local only (no push, no PR).
- **Grounding:** Both precedents are single commits touching a single plan file with `docs(plans):`
  subjects. AC5 requires the final diff to touch exactly one file, which a single commit makes trivially
  checkable via `git show --stat`.
- **Alternative considered:** Three commits (one per finding) — no reviewer benefit for ~60 lines of
  Markdown in one file, and it turns the AC5 check into a range check.

### Spec filename
- **Question:** What topic slug for this design doc?
- **Choice:** `.claude/specs/2026-08-11-detached-reviewer-plan-sync-design.md`.
- **Grounding:** `specDir` binding is `.claude/specs`; the directory's convention is
  `<YYYY-MM-DD>-<topic>-design.md` (four existing `-design.md` files). The slug keeps it adjacent to
  `2026-08-11-detached-reviewer-bridge-design.md` and `-evidence.md` while staying distinct from both.
- **Alternative considered:** Appending to the existing evidence spec — that file is a point-in-time record
  of the AC8 demo, and the issue's scope boundary marks it out of bounds.
