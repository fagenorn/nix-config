# C4+G2 Review-Ladder Collapse Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Collapse the pipeline's four review rungs to two — plan review (unchanged) plus one two-axis diff review in sdd's final slot — per the approved spec `.claude/specs/2026-08-10-c4g2-review-ladder-design.md`.

**Architecture:** All changes are agent-skill prose (markdown contracts agents execute) plus one JSON eval-text update. Five surfaces: codex-collaboration (delete `decision-check`, add `diff-review`), from-issue (drop the decisionReview binding, carry `review_state` in the ship handoff), sdd (two-axis final review + two new reviewer templates replacing the single final template, implementer report-back addressing fix), ship-issue (Phase 5 degradation logic + `review.criticalPaths` binding), ship-issue eval 1 text. Deploy is commit → user runs `just switch` → `just evals`.

**Tech stack:** Markdown skill definitions under `home/common/`, deployed via nix-darwin/home-manager; repo verification is `just build`; behavioral verification is the deployed-skill eval harness.

## Global Constraints

- Axis verdicts: ≤400 words each, severity `Critical`/`Important`/`Minor`, findings anchored to `file:line`, reports **never merged** into one narrative.
- Ship degradation requires ALL of: `review_state` = `clean`; no manual conflict escalation in Phase-1 sync (allowlist auto-resolves count as clean); branch diff ≤400 changed lines AND ≤20 files excluding lockfiles/generated.
- Full two-axis review at ship when: `risky` label, OR diff intersects `review.criticalPaths` globs (optional binding; absent = label-only), OR any degradation condition fails, OR `review_state` = `unknown`.
- `REVIEW-CONTRACT.md` is not modified by any task.
- Per-task review machinery and the 5-round fix loop are not modified by any task (Task 4 touches only the implementer report-back wording).
- Codex leg invariants (must survive verbatim in edited text): `command -v codex-companion` pre-flight; `WORKTREE_ROOT:` first line; background launch inside the bridge; `--timeout-ms 840000`; one-time native fallback on real failure only; never retry; concurrency is never a fallback reason.
- `review_state` vocabulary everywhere it appears: `clean | residuals | unknown`.
- Commits: pathspec-only, conventional subject `<type>(agents): …` (repo precedent), trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, never touch GPG/SSH signing settings.

## Test seams

- Static grep gates per task (commands + expected-empty results given in each task) — the only in-repo falsifiable checks for prose contracts.
- `just build` (Task 6) — Nix evaluation gate before any success claim.
- Deployed behavior: `just evals from-issue 1|2|3` must stay green after the user's `just switch` (post-deploy; not an implementer gate). ship-issue evals stay plan-only with Task 5's text update.
- No new eval cases; no new seams.

## Auto-resolved decisions

### Single Codex kill-switch governs both operations
- **Question:** Does `diff-review` get its own config gate?
- **Choice:** No new key — `codex.planReview.enabled: false` now reads as "this project opted out of Codex review passes" and returns control to native flow for both operations.
- **Grounding:** Spec D5 is silent on a gate; YAGNI in the design skill; a project that disabled the Codex plan leg has no reason to want a Codex diff leg.
- **Alternative considered:** A `codex.diffReview` key — a second toggle nothing asked for, echoing the deleted `decisionReview` dead weight.

### Addressing fix scoped to the implementer template
- **Question:** Fix the SendMessage misaddressing in every sdd template or only where it was observed?
- **Choice:** Only `implementer-prompt.md` — the reviewer templates already open their report contract with "Your final message is the report itself".
- **Grounding:** Evidence record: the failures were grandchild *implementers*, 2/2 pipelines; the ambiguity ("report back with ONLY…") exists only in that template.
- **Alternative considered:** Adding the line to all four templates — belt-and-braces prose creep in files that already state the rule.

### Ship's fallback when sdd templates are absent
- **Question:** What does ship-issue's full two-axis path do when the sdd skill (and its templates) is not installed?
- **Choice:** One fresh `reviewer` over the same range grading delivered-vs-promised AND code correctness, `Blocking`/`Should-fix`/`Discussion`, ≤400 words — a one-line inline fallback.
- **Grounding:** ship-issue's existing note: absent sibling skills degrade, the skill still runs; a merge gate cannot degrade to "no review".
- **Alternative considered:** Duplicating the axis rubrics inside ship-issue — recreates the drift the one-definition rule (spec D8) exists to prevent.

### Conformance template must work with no spec/issue
- **Question:** sdd runs standalone on plans without a from-issue spec or tracker issue — what does the conformance axis ground on?
- **Choice:** `[SPEC_FILE]`/`[ISSUE_REF]` placeholders are documented as omittable; the axis then grades delivered-vs-promised against the plan alone.
- **Grounding:** sdd SKILL.md is caller-agnostic today (final template already says "Spec (when distinct)").
- **Alternative considered:** Requiring a spec — would break standalone sdd, out of this design's scope.

---

### Task 1: codex-collaboration — delete `decision-check`, add `diff-review`

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: operation name `diff-review` with packet contract; validation accepting `Critical`/`Important`/`Minor` headings. Task 3's sdd text and Task 5's ship text invoke `diff-review` by exactly that name.

- [ ] **Step 1: Frontmatter + intro**

In the frontmatter, replace the `description:` line with:

```yaml
description: Run a private, isolated Codex pass — plan-review (from-issue Phase 5) or diff-review (the diff review's correctness axis) — and disposition its findings.
```

Replace the intro sentence `Support two operations: \`plan-review\` and \`decision-check\`.` with `Support two operations: \`plan-review\` and \`diff-review\`.`

- [ ] **Step 2: Generalize the kill-switch**

In `## Resolve policy`, replace the bullet `- \`enabled: false\` means return control so \`from-issue\` can use its fresh native reviewer flow. Do not launch Codex.` with:

```markdown
- `enabled: false` means the project has opted out of Codex review passes entirely:
  return control so the caller uses its native reviewer flow — for either operation.
  Do not launch Codex.
```

- [ ] **Step 3: Per-operation validation headings**

In `## Validate and fall back`, replace the sentence `A valid result has all three required headings and either \`None.\` or findings with evidence, confidence, and unknowns.` with:

```markdown
A valid result has the operation's three required headings (`Blocking` / `Should fix` /
`Discussion` for `plan-review`; `Critical` / `Important` / `Minor` for `diff-review`)
and either `None.` or findings with evidence, confidence, and unknowns.
```

- [ ] **Step 4: Delete the `## Operation: decision-check` section entirely** (heading through the final `- **No Claude fallback for this operation.** …` bullet), and append in its place:

````markdown
## Operation: `diff-review`

The correctness axis of the two-axis diff review (the sdd skill defines the axes and
owns dispatching the parallel native conformance axis — that axis never comes through
this skill). Same runtime contract as `plan-review`: resolve policy, pre-flight,
packet by paths, `WORKTREE_ROOT:` first line, one foreground `codex:codex-reviewer`
dispatch with background launch inside the bridge, validation, one-time native
`reviewer` fallback on a real Codex failure, never a retry, concurrency never a
fallback reason. The axis is never skipped.

Packet differences from `plan-review`:

- Scope line: review the diff `<base-sha>..<head-sha>` in the worktree for code
  correctness — bugs, boundary error handling, dead branches, assertions that fail to
  pin the documented contract, DRY against existing helpers, cross-task integration.
  Conformance to issue/spec/docs is the parallel axis's job; instruct the reviewer
  not to grade it.
- The caller's correctness rubric travels by absolute path (sdd's
  `correctness-reviewer-prompt.md`), with concrete values supplied for every
  placeholder it names.
- Include: worktree root, base and head SHAs, the diff-package path when the caller
  built one, the plan path (routing context for what the tasks were), inferred verify
  commands, every applicable `AGENTS.md`/`CLAUDE.md`, and the standards layers
  matching the diff's file types (`~/.agents/standards/the-bar.md`, its `stacks/`
  shards, project `docs/standards/` shards whose globs intersect). **Skip the
  map-first domain-doc selection** — domain conformance belongs to the other axis,
  and the light packet is what keeps Codex inside its runtime budget.
- Reviewer output contract: exactly three top-level sections `Critical` /
  `Important` / `Minor` (must-fix-before-merge / should-fix / nice-to-have),
  ≤400 words total, every finding with a stable ID, live `path:line` evidence,
  confidence (`high` / `medium` / `low`), and unknowns (`none` when empty); `None.`
  under an empty section; unreadable artifacts reported explicitly.

Verify-and-disposition stays with the calling controller and its own fix-flow rules:
return the validated three-section result (or the fallback reviewer's) unmodified,
plus the reviewer identity (`Codex` | `Claude fallback` + failure class) for the
caller's ledger.
````

- [ ] **Step 5: Verify**

Run: `grep -cn "decision-check\|decisionReview" home/common/claude-code/skills/codex-collaboration/SKILL.md`
Expected: `0` (exit 1). (At the base commit this returns ≥3 — the check can fail.)
Run: `grep -n "diff-review" home/common/claude-code/skills/codex-collaboration/SKILL.md | head -3`
Expected: hits in the description line, intro, and the new operation heading.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/SKILL.md
git commit -m "feat(agents): codex-collaboration diff-review op replaces decision-check

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/claude-code/skills/codex-collaboration/SKILL.md
```

### Task 2: from-issue — drop decisionReview, carry review_state in the ship handoff

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: handoff field `review_state:   clean | residuals | unknown` — Task 5's ship-issue text reads exactly that field name; Task 3's sdd report supplies its value.

- [ ] **Step 1: SKILL.md bindings line**

In `## Project bindings (resolve first)`, the `Keys used:` paragraph ends with `\`codex.planReview{enabled,focus}\`, \`codex.decisionReview\` (default false).` Replace that tail with `\`codex.planReview{enabled,focus}\`.`

- [ ] **Step 2: SKILL.md Phase 6 — carry the state**

At the end of the Phase 6 section (after the `**CHECKPOINT** — Confirm the implementation is committed on the feature branch.` line), add:

```markdown
sdd's report includes `review_state` (`clean | residuals | unknown`) from its two-axis
final review; carry it verbatim into the Phase-7 handoff — ship-issue's Phase-5
degradation decision reads it.
```

- [ ] **Step 3: SKILL.md Phase 7 handoff template**

In the Phase 7 subagent prompt block, insert a new line directly under `  head_sha:       <SHA at end of Phase 6 execute>`:

```
  review_state:   <clean | residuals | unknown — from sdd's report>
```

- [ ] **Step 4: AUTO.md — remove the cross-check step**

In `## The self-answer pattern`, delete item 4 entirely (`4. **Cross-check the high-stakes ones** — …` through `… \`Cross-check: unavailable\`, continue.`) and renumber item `5. **Continue.** Don't post the question. Don't wait.` to `4.`

- [ ] **Step 5: Verify**

Run: `grep -rn "decisionReview\|decision-check\|Cross-check" home/common/agent-skills/skills/from-issue/`
Expected: no output (exit 1). (Non-empty at the base commit.)
Run: `grep -n "review_state" home/common/agent-skills/skills/from-issue/SKILL.md | wc -l`
Expected: `2` (Phase 6 note + handoff template line).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md
git commit -m "feat(agents): from-issue drops decision-check, ships review_state in the handoff

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md
```

### Task 3: sdd — two-axis final review and its two templates

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Create: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Create: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Delete: `home/common/agent-skills/skills/sdd/final-reviewer-prompt.md`

**Interfaces:**
- Consumes: operation name `diff-review` from Task 1.
- Produces: template filenames `conformance-reviewer-prompt.md` / `correctness-reviewer-prompt.md` (Task 5 references both), report field `review_state` (Task 2's handoff consumes it).

- [ ] **Step 1: SKILL.md intro sentence**

Replace `Execute a plan by dispatching a fresh implementer per task, a task review (spec compliance + code quality) after each, and one whole-branch review at the end.` with `Execute a plan by dispatching a fresh implementer per task, a task review (spec compliance + code quality) after each, and one two-axis whole-branch review (conformance ∥ correctness) at the end.`

- [ ] **Step 2: SKILL.md Agent tiers bullet**

Replace the bullet `- The **final whole-branch review** dispatches as \`reviewer\`; it reviews the union of every task, so if any single task warranted your most capable model, this does too — override the model upward rather than down.` with:

```markdown
- The **final review's two axes** dispatch per §Final review — the conformance axis as
  `reviewer` (it reviews the union of every task, so if any single task warranted your
  most capable model, this does too — override the model upward rather than down), the
  correctness axis via `codex-collaboration`'s `diff-review` when that skill is
  available, else as `reviewer`.
```

- [ ] **Step 3: SKILL.md `## Final review` section**

Replace the entire `## Final review` section (both paragraphs) with:

````markdown
## Final review — two axes

Run `scripts/review-package PLAN_FILE MERGE_BASE HEAD` (MERGE_BASE = `git merge-base
<integration-branch> HEAD`) once, then review the branch on two axes **in parallel, as
isolated subagents** over that same package:

- **Conformance axis** — did the diff deliver what issue + spec + plan promised,
  honoring the project's ADRs, context docs, and standards. Native `reviewer`, model
  per Agent tiers, template
  [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md).
- **Correctness axis** — is it built right: bugs, boundary error handling, dead
  branches, assertions that pin the documented contract, DRY, cross-task integration.
  When the `codex-collaboration` skill is available, invoke its `diff-review`
  operation for this axis — it owns the Codex launch and performs its own one-time
  native fallback on a real Codex failure. Unavailable → dispatch a native `reviewer`
  with [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md). Either way
  the axis is never skipped.

Point the conformance dispatch at the ledger's deferred-minor and parked lines so it
triages what must be fixed before merge. Verdicts come back ≤400 words each, findings
Critical/Important/Minor anchored to file:line. **Never merge the two reports** into
one narrative — they are independent signals; disposition each on its own, and record
both verdicts plus the correctness axis's reviewer identity (`Codex` | `native` |
`fallback` + failure class) in the ledger.

Findings → verify each against the live worktree first (stale or unsupported ones are
rejected by you, in the ledger), then dispatch ONE fixer with the complete list
labeled by axis — where both axes flag the same lines, dedupe at dispatch and credit
both axes in the ledger (per-finding fixers each rebuild context and re-run suites; a
real session's per-finding fix wave cost more than all its tasks combined). Then
exactly one scoped re-review per axis that had findings, over the fix range.
Adjudicate residuals like the task-loop breaker. There is no second fix wave —
residual load-bearing findings surface to the caller.
````

- [ ] **Step 4: SKILL.md `## Finish` report contract**

Replace `Report to the calling workflow: final review result, commit range \`<base7>..<head7>\`, parked findings with rulings, verification status, ≤500 characters of notes.` with:

```markdown
Report to the calling workflow: per-axis final-review verdicts, `review_state`
(`clean` when both axes are clean or every residual is parked-with-ruling, else
`residuals`), commit range `<base7>..<head7>`, parked findings with rulings,
verification status, ≤500 characters of notes.
```

- [ ] **Step 5: Create `conformance-reviewer-prompt.md`**

Full file content:

````markdown
# Conformance Reviewer Prompt Template (final review, conformance axis)

One of the two isolated axis reviewers in the final review. This axis grades
delivered-vs-promised; the parallel correctness axis grades bugs and build quality —
this prompt tells its reviewer not to duplicate that job.

```
Subagent (reviewer — model per SKILL.md Agent tiers; the final review warrants your
most capable model):
  description: "Final review — conformance axis"
  prompt: |
    You are reviewing a completed feature branch for CONFORMANCE: did the diff
    deliver what the issue, spec, and plan promised, honoring the project's
    documented decisions and standards? A parallel reviewer grades code
    correctness (bugs, tests, integration) — do not grade that here.

    ## Ground first

    Invoke `doc-grounded-questions` via the Skill tool if available; otherwise
    ground map-first yourself: read the context map (`docs/CONTEXT-MAP.md`, or the
    configured `docPaths.contextMap`), open only the area `CONTEXT.md` files whose
    `governs:` globs intersect the diff's paths or whose terms appear in the
    issue, their `adr/` dirs plus `system`, and the standards shards whose globs
    intersect the diff. No map → read whichever of `docPaths.{context,standards}`
    exist.

    ## Requirements

    Issue: [ISSUE_REF]
    Spec: [SPEC_FILE]
    Plan: [PLAN_FILE]

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — commit list, stat summary, full diff with context.
    When checking a finding, read the live file at HEAD, not a snapshot. Your
    review is read-only on this checkout: do not mutate the working tree, the
    index, HEAD, or branch state in any way.

    ## What to Check

    - **Delivered vs promised:** every spec requirement and plan-task deliverable
      present in the diff; deviations are justified improvements, not silent
      departures. Missing, extra, or misunderstood scope is a finding.
    - **Doc conformance:** the diff honors the ADRs and canonical area terms you
      grounded in; terminology the change retires is purged from adjacent code
      and docs.
    - **Stale-prose audit:** re-read every context-doc sentence, ADR clause,
      docstring, and comment adjacent to the diff's footprint — prose the diff
      falsifies must have been updated with it.
    - **Message-format parity:** operator-facing strings, error messages,
      audit-trail formats, and labels the spec promises match the implementation
      byte-for-byte, or the deviation is explicitly justified.
    - **Ledger triage:** [DEFERRED_AND_PARKED_LINES] — for each, verdict:
      must-fix-before-merge or defer-with-reason. Parked rulings deserve
      skepticism, not deference.

    ## Output Format

    ≤400 words total. Begin directly with the coverage verdict — every line a
    verdict, a finding with file:line, or a check you ran; no preamble, no
    closing summary.

    ### Coverage
    ✅ | ❌ per spec requirement / plan task, one line each.

    ### Issues
    #### Critical (Must Fix)  #### Important (Should Fix)  #### Minor
    Conformance gaps — promised-but-missing scope, ADR violations — are Critical.

    ### Ledger Triage
    Per deferred/parked line: must-fix | defer, one-line reason.

    ### Verdict
    **Conformance:** [Clean | Findings] — 1–2 sentence assessment.
```

**Placeholders:** `[ISSUE_REF]` (issue number/URL, or the caller's one-line intent
statement when there is no tracker; omit the line when neither exists),
`[SPEC_FILE]` (omit when no spec exists — standalone plans are graded against the
plan alone), `[PLAN_FILE]`, `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package`), `[DEFERRED_AND_PARKED_LINES]` (copied verbatim from the
ledger).
````

- [ ] **Step 6: Create `correctness-reviewer-prompt.md`**

Full file content:

````markdown
# Correctness Reviewer Prompt Template (final review, correctness axis)

The native form of the correctness axis — dispatched directly when
`codex-collaboration` is unavailable. When that skill IS available, its `diff-review`
operation carries this file by absolute path as the Codex reviewer's rubric, so keep
the body reviewer-agnostic: nothing in it may assume which model is reading it.

```
Subagent (reviewer):
  description: "Final review — correctness axis"
  prompt: |
    You are reviewing a completed feature branch for CORRECTNESS: is it built
    right? A parallel reviewer grades conformance to issue/spec/docs — do not
    grade delivered-vs-promised scope here.

    ## Inputs

    Plan (routing context for what the tasks were): [PLAN_FILE]
    Verify commands: [VERIFY_COMMANDS]
    Standards: read `~/.agents/standards/the-bar.md`, its `stacks/` shards
    matching the diff's file types, and the project's `docs/standards/` shards
    whose globs intersect the diff.

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once; when checking a finding, read the live file at HEAD,
    not a snapshot. Inspect code outside the diff only to evaluate a concrete
    risk you can name — cross-task contract drift, changed lock ordering, shared
    mutable state — one focused check per named risk, named in your report. Your
    review is read-only on this checkout: do not mutate the working tree, the
    index, HEAD, or branch state in any way. Do not re-run the full test suite —
    the implementers' reported runs are the evidence; run at most one focused
    test to resolve a specific doubt reading the code raised.

    ## What to Check

    - **Bugs and boundaries:** error handling at boundaries,
      unfamiliar-principal / missing-entity fallbacks, edge cases, half-finished
      branches that assume the happy path.
    - **Dead branches:** stranded `else` arms, unused props, flag arms no code
      path reaches — plan pivots leave these behind.
    - **Assertions that pin:** would the tests fail if the documented contract
      broke? Assertions that pass under any 400 emitter, any non-null array, or
      a substring of a transformed value pin nothing.
    - **DRY:** new helpers that duplicate ones the codebase already has.
    - **Cross-task integration:** interfaces one task defines and another
      consumes actually match; naming consistent across tasks; no task undone by
      a later one.

    ## Output Format

    ≤400 words total. Begin directly with the first section — every line a
    finding or a check you ran; no preamble, no closing summary. Every finding
    carries a stable ID, live `path:line` evidence, confidence
    (`high` / `medium` / `low`), and unknowns (`none` when empty). Write `None.`
    under an empty section. Report unreadable artifacts explicitly.

    ### Critical (Must Fix)
    ### Important (Should Fix)
    ### Minor

    ### Verdict
    **Correctness:** [Clean | Findings] — 1–2 sentence assessment.
```

**Placeholders:** `[PLAN_FILE]`, `[VERIFY_COMMANDS]` (from the project bindings /
manifest detection), `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package`). When this file rides as the Codex rubric, the
`diff-review` packet supplies the same values.
````

- [ ] **Step 7: Delete the old template**

```bash
git rm home/common/agent-skills/skills/sdd/final-reviewer-prompt.md
```

- [ ] **Step 8: Verify**

Run: `grep -rn "final-reviewer-prompt" home/common/`
Expected: no output (exit 1). (Two references at the base commit — SKILL.md §Agent tiers and §Final review.)
Run: `grep -n "review_state" home/common/agent-skills/skills/sdd/SKILL.md`
Expected: exactly one hit, in §Finish.
Run: `ls home/common/agent-skills/skills/sdd/*reviewer-prompt.md`
Expected: `conformance-reviewer-prompt.md`, `correctness-reviewer-prompt.md`, `re-review-prompt.md`, `task-reviewer-prompt.md`.

- [ ] **Step 9: Commit**

```bash
git add home/common/agent-skills/skills/sdd/
git commit -m "feat(agents): sdd final review becomes the two-axis diff review

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/agent-skills/skills/sdd/
```

### Task 4: sdd implementer template — report-back addressing fix

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`

**Interfaces:**
- Consumes / Produces: nothing shared; independent of Tasks 1–3.

- [ ] **Step 1: Make the final message the explicit report channel**

In `## Report Format`, replace the line `Then report back with ONLY (under 15 lines — detail lives in the file):` with:

```markdown
Then report back with ONLY (under 15 lines — detail lives in the file). Reporting
back means ending your turn with this as your final message — the controller reads
your final message directly. Never deliver it via SendMessage: you were not given a
recipient name, and agent-type names like `general-purpose` are not addressable
recipients. Do not wait for an acknowledgment.
```

- [ ] **Step 2: Verify**

Run: `grep -n "SendMessage" home/common/agent-skills/skills/sdd/implementer-prompt.md`
Expected: exactly one hit, in the replaced Report Format line. (Zero at the base commit — the check can fail.)

- [ ] **Step 3: Commit**

```bash
git add home/common/agent-skills/skills/sdd/implementer-prompt.md
git commit -m "fix(agents): sdd implementers report via final message, never SendMessage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/agent-skills/skills/sdd/implementer-prompt.md
```

### Task 5: ship-issue — Phase-5 degradation, criticalPaths binding, eval text

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json`

**Interfaces:**
- Consumes: handoff field `review_state` (Task 2), template filenames + `diff-review` op (Tasks 1, 3).
- Produces: binding name `review.criticalPaths` (documented here only).

- [ ] **Step 1: Bindings paragraph**

In `## Project bindings (resolve first)`, after the sentence ending `\`defaultBranch\` matters because it controls GitHub auto-close-on-merge (Phase 4).`, add:

```markdown
Optional `review.criticalPaths` (array of globs): diffs intersecting any of them
always get Phase 5's full two-axis review. Absent = the `risky` label is the only
always-full trigger.
```

- [ ] **Step 2: Invocation paths — review_state**

In `**Invocation paths.**`, replace `the bootstrapping prompt carries \`issue_number\`, \`branch\`, \`worktree_path\`, \`spec_path\`, \`plan_path\`, \`head_sha\`, \`auto\`, \`summary\` — use those instead of re-deriving.` with:

```markdown
the bootstrapping prompt carries `issue_number`, `branch`, `worktree_path`,
`spec_path`, `plan_path`, `head_sha`, `review_state`, `auto`, `summary` — use those
instead of re-deriving. Standalone, `review_state` is `unknown` unless the user
supplies evidence of a completed sdd two-axis review.
```

- [ ] **Step 3: Replace Phase 5's review-selection block**

Replace everything in `## Phase 5 — Review the PR` from the sentence `Dispatch a fresh subagent via the \`Agent\` tool …` through the end of the block-quoted rubric (the line `> Return findings ranked most-severe first, … not the report.`) with:

````markdown
The branch normally arrives already reviewed on two axes by sdd's final review
(conformance ∥ correctness — the sdd skill owns that machinery and its templates).
This phase reviews only what that review could not have seen — unless a risk signal
calls for the full ladder.

**Pick the path first.** Degrade to the merge-delta check when ALL of these hold;
otherwise run the full two-axis review:

- `review_state` is `clean` (handoff / sdd report: both axis verdicts clean, or every
  residual parked-with-ruling). `unknown` never degrades.
- The Phase-1 sync needed no manual conflict escalation (allowlist auto-resolves
  count as clean).
- The branch diff is small: ≤400 changed lines AND ≤20 files, counted over
  `git diff --stat $BASE_SHA..$HEAD_SHA` excluding lockfiles and generated files.
- The issue does NOT carry the `risky` label, and the diff does NOT intersect the
  `review.criticalPaths` globs.

**Merge-delta check (degraded path).** The reviewable delta is the sync-merge
commit's combined diff (`git show --cc <merge-commit>` — conflict resolutions and
scope-creep sweeps) plus any commits made after the head sdd reviewed. Empty →
record "merge-delta empty, nothing to review" in the PR body and continue to
Phase 6. Non-empty → dispatch one fresh `reviewer` subagent over exactly that delta
(nested dispatch works even inside an `Agent` subagent; if `Agent` isn't in your
tool surface, `ToolSearch` `select:Agent` first — never inline the review), with
Phase 1's scope-creep categories (retirement / addition) as its checklist plus the
project-hints review paragraph when `projectHints` exists. Findings come back
Blocking / Should-fix / Discussion, ≤400 words, file:line anchors.

**Full two-axis review.** Same machinery and rubrics as sdd's final review, over the
post-sync range `$BASE_SHA..$HEAD_SHA`: dispatch the native conformance reviewer
(sdd's `conformance-reviewer-prompt.md`, deployed beside its SKILL.md) in parallel
with the correctness axis via `codex-collaboration`'s `diff-review` when available,
else a native reviewer on sdd's `correctness-reviewer-prompt.md`. Verdicts ≤400
words each, Critical/Important/Minor, never merged; Critical findings gate the merge
the way Blocking findings do below. sdd templates unavailable → one fresh `reviewer`
over the same range grading delivered-vs-promised AND code correctness,
Blocking / Should-fix / Discussion, ≤400 words.
````

Keep everything after the old rubric block — from `Apply Blocking fixes inline — but \`apply\` and \`push\` are separate steps, not one verb.` onward — unchanged.

- [ ] **Step 4: Eval 1 expected text**

In `evals/evals.json`, eval id 1's `expected_output` contains the phrase `Phase 5 a fresh reviewer subagent`. Replace exactly that phrase with `Phase 5 the degradation decision — merge-delta-only check when review_state is clean, the sync was conflict-free, and the diff is small (≤400 lines/20 files); full two-axis review (conformance ∥ correctness, never merged) for the risky label, criticalPaths hits, or review_state unknown`.

- [ ] **Step 5: Verify**

Run: `grep -n "review_state\|criticalPaths\|merge-delta" home/common/agent-skills/skills/ship-issue/SKILL.md | wc -l`
Expected: ≥6 hits spanning bindings, invocation paths, and Phase 5. (Zero at the base commit.)
Run: `python3 -c "import json; json.load(open('home/common/agent-skills/skills/ship-issue/evals/evals.json'))"`
Expected: silent success (valid JSON survived the edit).
Run: `grep -c "doc-grounded-questions" home/common/agent-skills/skills/ship-issue/SKILL.md`
Expected: ≥1 (the Doc-grounded escalations section is untouched).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/evals/evals.json
git commit -m "feat(agents): ship-issue Phase 5 degrades behind the two-axis sdd review

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/evals/evals.json
```

### Task 6: Cross-cutting sweep and build gate

**Files:**
- Modify: none expected — this task verifies and fixes only what its own greps surface.

**Interfaces:**
- Consumes: all prior tasks' terminology (`diff-review`, `review_state`, template filenames).

- [ ] **Step 1: Stale-reference sweep**

Run each; expected no output (exit 1) unless noted:

```bash
grep -rn "decision-check\|decisionReview" home/common/
grep -rn "final-reviewer-prompt" home/common/
grep -rn "final whole-branch review" home/common/agent-skills/skills/
```

Any hit is a missed edit: fix it in the style of the owning task and note it in the report. (`.claude/specs/` hits are historical records and stay.)

- [ ] **Step 2: Consistency sweep**

```bash
grep -rn "review_state" home/common/ | grep -v Binary
```

Expected: hits in exactly three skills — from-issue (2), sdd (1), ship-issue (≥2) — all using the `clean | residuals | unknown` vocabulary. A fourth skill or a divergent vocabulary is a defect.

- [ ] **Step 3: Build gate**

```bash
git add home/common/ && just build
```

Expected: build succeeds (exit 0). This is the repo's verification step; a failure here blocks any success claim.

- [ ] **Step 4: Commit (only if Step 1 forced fixes)**

```bash
git add home/common/
git commit -m "fix(agents): C4+G2 sweep — stale ladder references

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- home/common/
```

No fixes → no commit; report "sweep clean, build green".
