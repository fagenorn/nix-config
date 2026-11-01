# ship-issue PRs read on their own: why, what, evidence, merge danger — issue 494

Issue: https://github.com/fagenorn/nix-config/issues/494. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "The ship-issue PR body template is a skill contract whose machine-read lines remainder mode parses back."}, "concurrency_or_persistence": {"value": "no", "evidence": "Prose template and contract tests only; no locking or persisted state."}, "open_design_questions": {"value": "doubt", "evidence": "Where the template lives and how it fits the tight instruction-budget ceilings (ship-owner 464 B, implementation-owner 79 B headroom) is open."}, "criteria_shape": {"value": "no", "evidence": "Four acceptance criteria, each checked by contract tests or just recipes."}}, "paths": ["home/common/agent-skills/skills/ship-issue/SKILL.md", "home/common/agent-skills/skills/ship-issue/REVIEW.md", "home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md", "home/common/agent-skills/skills/from-issue/ship-handoff.md", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "home/common/agent-skills/instruction-load.json"]}
Verdict: {"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Someone who opens a PR made by ship-issue, in this repository or in
elevenyellow/nodocom (same global skill), cannot tell from the PR page why it exists,
what changed, how we know it works or how risky it is to merge. The body template has
one prose slot, "2-4 bullets of what shipped", written for the author. Those bullets
cite internal IDs nobody explains (decision numbers, review finding codes, slice
labels) and undefined domain terms. The rest of the body is bookkeeping: bare spec and
plan paths, an acceptance table reading only `AC1 | code | met`, and review ranges as
SHA pairs (PR #490 is typical). Nothing says what was wrong before, and nothing shows
evidence, risk or rollback.

The body also cannot carry a fenced code block, where sketches normally go. The
lifecycle guard accepts a PR body only inline, in one double-quoted argument without
`"`, `$`, backtick or backslash.

Two hard limits shape the fix:

- **The Instruction Budget gate.** Any edit to `instruction-load.json` other than
  lowering a ceiling or a profile note needs the `instruction-budget-raise` label,
  which only the user applies. Headroom at base `8d0bbc25` is 464 B on ship-owner hot
  (ship-issue `SKILL.md`, `REVIEW.md` and three siblings), 79 B on implementation-owner
  hot (which holds `from-issue/ship-handoff.md`), and 2 B on ship-owner conditional
  (which holds `HUMAN-GATE.md` and `REMAINDER.md`).
- **The skill lint L2.** ship-issue's `SKILL.md` body is at exactly 500 reflowed lines,
  its ceiling. A reflowed line is one per 100 characters, and a blank line counts 1.
  `REVIEW.md` is at exactly 100. Above 100, the lint's L3 rule requires a `## Contents`
  list.

## Solution

The Phase-4 body opens with four readable sections, in order: **Why**, **What
changes**, **Evidence** and **Merge danger**. A collapsed `<details>` block with the
summary "Delivery record" follows. It holds the spec and plan as blob URLs, the
existing `## Acceptance` section (its table gains a `Criterion` column), and the
review and verification notes. `Closes #<num>` stays the last line, outside the block,
and is dropped on a hold as today. Every step that today writes notes "in the PR body"
or "the PR body's Summary" names the Delivery record instead. from-issue's inline
fallback names the same four headings and the block.

The **Delivery record** is that collapsed block of the PR body and nothing else. It is
not the acceptance record file (`<plan stem>.acceptance.md`), and not review-package's
durable `delivery-detail` package. Skill text always writes the name capitalized, so
it reads as a handle.

The template stays in `SKILL.md` Phase 4 (per D1). It uses blank lines only where
GitHub-flavoured Markdown needs them (per D2). Compressing the neighbouring Phase 2, 4
and 8 prose pays for it (per D10). Besides `SKILL.md`, only `REVIEW.md` changes in
ship-issue (two destination phrases). The guard does not change.

### Target text — `SKILL.md` Phase 4

The fence after "Run `check-launch` again, then:" becomes, verbatim:

```
gh pr create --repo <resolved-repository> --base <integration> --head <branch> --title "<title>" --body "## Why
<1-3 sentences: what was wrong or missing and who notices, with the issue URL>
## What changes
<smallest sketch (diff, call tree or before/after) indented 4 spaces, then 2-4 plain bullets>
## Evidence
<before and after: the failing test that now passes, output or behaviour>
## Merge danger
<one- or two-way door; blast radius in a word; rollout and rollback>
<details><summary>Delivery record</summary>

Spec: <blob URL>, plan: <blob URL>
## Acceptance
Acceptance state: <effective acceptance state>

Acceptance record: <record-path or none>

<acceptance table>

<review and verification notes>
</details>

Closes #<num>"
```

The five paragraphs after that fence (guard form, acceptance, title, auto-close, full
URLs) become three:

1. The guard-form paragraph, unchanged, then two sentences: "Above `<details>`,
   explain or link each domain term on first use and name no internal ID (decision,
   finding, slice or `ACn`). Title: the issue title verbatim unless the implementation
   deviated meaningfully; under 70 chars." (per D8)
2. The acceptance paragraph. The table becomes "a Markdown table with the columns `AC`,
   `Criterion`, `Kind` and `Verdict`, one row per record row, copying its closed tokens
   and its claim before `— measured:`". The keyword list becomes "(any form of close,
   fix or resolve before an issue reference)". The auto-close paragraph is appended as
   "GitHub auto-closes only on a merge into the **default branch**; otherwise Phase 8's
   `gh issue close <num>` closes the issue, and the close branch keeps `Closes #<num>`
   for traceability." (per D5, D10)
3. The full-URL paragraph. Its example becomes
   "(`https://github.com/<resolved-repository>/issues/<n>`; spec and plan as blob URLs
   at the pushed head)", and its rationale ends at "— a bare `#N` resolves against the
   source repo." (per D4, D10)

### Target text — the note sites (per D6)

- Phase 2 step 1: "keep its `tree`, `run` and `skipped`. On Phase 2's own run, note
  each skip as `verification skipped: <id> (<reason>)` in the Delivery record."
- Phase 2 step 2 and the baseline-diff note: "in the PR body's Summary" and "in the PR
  body" become "in the Delivery record".
- Phase 5: "Record the route in the Delivery record per REVIEW.md." The Codex routing
  error is recorded "in the Delivery record beside the correctness verdict".
- Phase 8 hold comment: "the PR body's acceptance table and the record's blob URL at
  the merge SHA" (per D4, D5).
- `REVIEW.md`: the diff-review scope is recorded "in the Delivery record beside the
  correctness verdict…", and the range record reads "Phase 5 records its route in the
  Delivery record as". Each line stays under 100 characters.

### Target text — from-issue's inline fallback (per D7)

"The PR body has `## Why`, `## What changes`, `## Evidence` and `## Merge danger`,
then a collapsed `<details>` Delivery record; it carries `Closes #<num>` only when the
sdd report's `acceptance_state` is `met` or `not_applicable`, and no closing keyword
otherwise:". The later close clause shortens to "then close the issue on that
condition; otherwise hold it with ship-issue Phase 8 step 1's hold sequence…".

## Decisions

### What a reader sees (per D2, D3, D8)

- **Why** is 1–3 sentences: what was wrong or missing and who notices, with the
  issue's full URL. It must make sense without opening the issue.
- **What changes** is the smallest sketch that shows the change (a diff, a call tree,
  a before/after state), each line indented four spaces so it renders as code without
  a fence, then 2–4 plain bullets.
- **Evidence** is before and after: the failing test that now passes, command output,
  or the observed behaviour.
- **Merge danger** gives a one- or two-way door, the blast radius in a word, and how it
  rolls out and back.
- In these four sections a domain term is explained or linked on first use, and no
  bare internal ID appears: no decision number, finding code, slice label or `ACn`.
  The Delivery record may use them, since its acceptance table is keyed by `ACn`.

Rendered on GitHub, the four sections show as `<h2>` headings with a `<pre>` sketch
and a list. The Delivery record shows collapsed. Inside it the `## Acceptance` heading,
the table and any notes render normally. The `Closes` line renders outside the block.

### What a later step reads back (per D3, D5)

- `Acceptance state:`, `Acceptance record:` and `Closes #<num>` keep their exact text.
  Each of them, and the acceptance table, appears exactly once; everything but
  `Closes` sits inside the Delivery record. The pinned strings in
  `SHIP_ISSUE_MACHINE_TEXT` do not change. Only the table's columns change (per D5).
- Remainder mode (`REMAINDER.md` § Close or hold from the PR body) is unchanged. It
  reads one `Acceptance state:` line, one `Acceptance record:` line and "its
  acceptance table", none of which depends on position or column count. No code parses
  the body: an agent reads it through `gh pr view --json body`.
- `HUMAN-GATE.md` Gate 1 ("the `## Acceptance` section filled … and the `Closes #<num>`
  trailer") and Phase 6's "rewrite the PR body's `## Acceptance` per Phase 4" stay true
  as written, because the heading is kept.
- The hold comment (`Held for verification: <PR URL>`, then the state, the table and
  the record link) now carries the four-column table.
- The acceptance table is the one under `## Acceptance` with the `AC` header. A
  readable section may hold another table, such as a before/after table in Evidence.
  The close-or-hold choice reads only the `Acceptance state:` line, so the worst case
  of a misread table is a hold comment that quotes the wrong table.
- A PR opened before this change, still in the old layout, parses the same way: a
  remainder owner finds the same three lines and copies its three-column table.

### When the Delivery record is written (per D6)

Phase 4 opens the PR with the readable sections, the spec and plan URLs, the
acceptance section, and Phase 2's verification notes: skipped, reused, or the baseline
diff. Phase 5 then adds REVIEW.md's range record, each axis's verdict with the
diff-review scope, and any routing error to the same block. Today it writes them into
the body after creation in the same way. Review findings keep their current homes:
applied Should-fix items as PR comments, and Minor or Discussion items in the durable
delivery-detail package. The Delivery record carries only the review text the body
carries today, so nothing is copied twice.

### Guard and rendering facts relied on

- The guard's pr-create form has `whole_text_characters: false`. Its body refuses only
  `"`, `$`, backtick, backslash, NUL and CR. A spike ran the installed guard against a
  fully rendered body in this worktree. It exited 0 with `<details>`, `<summary>`,
  4-space-indented code, `| < > ( ) [ ] { } ~ * ? # & ;` and `'`, and exited 2 on a
  backtick, `$` or backslash.
- A GitHub GFM render spike (`gh api markdown`, mode `gfm`) of the exact template shape
  rendered as follows:
  - An indented block right after an ATX heading renders as `<pre>`.
  - A list directly after it renders as a list.
  - A heading directly after a paragraph or a list renders as a heading.
  - A `<details><summary>…</summary>` line followed by a blank line renders the
    Markdown inside the block.
  - A paragraph followed directly by `</details>` closes the block.
  - The table renders, preceded and followed by blank lines.
- A criterion's claim can contain a backtick or a `"`. As the guard paragraph already
  requires, the agent drops these before it renders the body. A refused body fails
  closed at the guard and is re-rendered, never sent another way.

### Budget fit (per D1, D2, D10)

Measured on a prototype of exactly the target text above, in a scratch worktree, with
`agent_tools.instruction_load` and `skill_lint`:

| Ceiling | Base | Prototype | Ceiling value |
|---|---:|---:|---:|
| ship-owner hot (both hosts) | 51612 | 51964 (+352) | 52076 |
| ship-owner conditional (claude) | 34445 | 34445 | 34447 |
| implementation-owner hot (both hosts) | 132615 | 132682 (+67) | 132694 |
| implementation-owner conditional (claude) | 102333 | 102685 | 102814 |
| orchestrated-issue-owner hot / conditional | 136974 / 115271 | 137041 / 115623 | 137511 / 115802 |
| from-issue-controller conditional (claude) | 46444 | 46511 | 46610 |
| corpus | 416180 | 416599 | 423190 |
| `SKILL.md` body, reflowed lines (L2 ≤ 500) | 500 | 499 | 500 |
| `REVIEW.md`, reflowed lines (L3 at > 100) | 100 | 100 | 100 |

On the prototype, `agent_tools.instruction_load check --base origin/main` printed
`check: pass`. No ceiling turns loose, and `instruction-load.json` is unchanged.
`test_workflow_skill_contracts`, `test_shell_example_contracts`,
`test_dispatch_contracts`, `test_skill_lint` and `test_instruction_load` all passed
there (293 tests). With 1 reflowed line and 12 B of implementation-owner headroom
left, the target text is binding. A wording change in the plan or in review must be
re-measured with the same two commands before it is committed.

## Test seams

The new cases go in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
next to `test_ship_issue_documents_carry_their_machine_text`. They pin template markup
that is rendered verbatim into the `gh pr create` argument, and the destination name
the other phases cite. They pin no guidance sentence (per D9). A throwaway version of
each failed at base for the stated reasons and passed on the prototype.

1. **The template reads first, then records.** Locate the template as the fenced
   `gh pr create … --body "…"` block in `SKILL.md` and assert, in order: `## Why`,
   `## What changes`, `## Evidence`, `## Merge danger`,
   `<details><summary>Delivery record</summary>`, `Spec: `, `plan: `, `## Acceptance`,
   the `Acceptance state:` and `Acceptance record:` lines, `<acceptance table>`,
   `<review and verification notes>`, `</details>`, `Closes #<num>`. Then assert:
   - `## Summary` is absent.
   - Each machine line occurs exactly once.
   - The body holds no `"`, `$`, backtick or backslash, so a fenced sketch fails here
     before it fails at the guard.

   A separate case asserts that the inline-fallback section of `ship-handoff.md` names
   `` `## Why` ``, `` `## What changes` ``, `` `## Evidence` ``, `` `## Merge danger` ``,
   `` `<details>` `` and "Delivery record", in that order. This covers AC1. Today it
   fails with "missing `## Why`".
2. **Notes go to the Delivery record.** Split `SKILL.md` and `REVIEW.md` into
   paragraphs and list items. For each anchor, the one block holding it names
   "Delivery record" and not "Summary". The anchors are the closed note lines
   `` `verification skipped: <id> (<reason>)` `` and `` `verification reused: tree <id>` ``
   in `SKILL.md`, and `` `review range: delta `` and the diff-review scope value
   `` `unmeasured` `` in `REVIEW.md`. This covers AC3. Today it fails on all four
   anchors.

AC2 is the existing `SHIP_ISSUE_MACHINE_TEXT` table and the remainder cases, kept
unchanged. AC4 is `just agent-workflow-tests` and `just build`. The plan also runs
`just agent-instruction-budget`, the required CI context that holds D1 and D10.

## Out of scope

- PRs not opened through ship-issue, including ship-release's release PRs, whose body
  `ship-release/CHANGELOG.md` owns. ship-release reads merged PR bodies for intent and
  now finds a Why section. It needs no change.
- Changing the lifecycle guard to accept a body file: deferred by the issue, not
  rejected.
- Any `instruction-load.json` change or ceiling raise, and any new skill file (per D1).
- `HUMAN-GATE.md`, `REMAINDER.md`, `CI-MERGE.md` and `POST-SELECTION-SYNC.md`. All four
  are unchanged, held by the 2-byte ship-owner conditional headroom.
- How Phase 5 and Phase 6 edit the body after creation (the mechanism is unchanged),
  and any new list of review findings in the body.
- New eval cases. The ship-issue evals do not mention the body layout.
- Rewriting already-merged PR bodies.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The template stays in ship-issue `SKILL.md` Phase 4. No new skill file is created and `instruction-load.json` is not touched; the growth is paid for by trims (D10). | `instruction_load.run_check` treats any model edit except lowering a ceiling or a note as a raise needing the user-only label. A new reference file must be named by `SKILL.md` (lint L4a) and listed in every profile that loads it (`_member_violations`), which is a model edit. | A conditional `ship-issue/PR-BODY.md`: needs the label. A doc under `~/.agents/share/`: outside the measured corpus, so it evades the gate it exists to enforce. Moving other `SKILL.md` text to a sibling: `REVIEW.md` is at L3's 100 lines, and the movable blocks are pinned in `SKILL.md`. Putting the template in `DELIVERY-LOOP.md`, which has room: that file is read only under lifecycle identity, so a standalone run would never see the template. |
| D2 | The template puts blank lines only where GFM needs them: after the `<summary>` line, around the table, after `</details>`, and in the unchanged acceptance block. The four sections follow each other directly, and What changes is one placeholder line covering sketch and bullets. | `SKILL.md`'s body sits at the L2 ceiling of 500 reflowed lines, and the same text with blank-separated sections measured 503. The GFM render spike shows the compact shape renders identically. | Blank lines between sections: over L2. Describing the four sections in prose rather than literal headings: weaker for the agent and the test, and no shorter. |
| D3 | `<details><summary>Delivery record</summary>` is one line. The unchanged `## Acceptance` section moves inside the block, followed by the notes. `Closes #<num>` stays the last line, outside. | The issue orders the record as spec and plan, acceptance, review, verification. HUMAN-GATE Gate 1 and Phase 6 cite `## Acceptance`, and HUMAN-GATE has 2 B of conditional headroom. REMAINDER reads lines, not positions. Render and guard spikes. | Renaming or dropping the `## Acceptance` heading: forces HUMAN-GATE edits over its ceiling. `Closes` inside the block: hides the trailer a reviewer checks for. |
| D4 | Spec and plan are blob URLs at the pushed head SHA. The Phase-4 URL rule says so once, and Phase 8's record link becomes "the record's blob URL at the merge SHA". | `bindings.vcs.merge.strategy` is `merge`, so the pushed head stays reachable after `delete_branch: true`. The merge SHA is unknown at Phase 4. DRY: one URL rule. | Branch-name URLs: break when the branch is deleted. Spelling the full URL template in each place: over the line ceiling. |
| D5 | The acceptance table becomes `AC`, `Criterion`, `Kind`, `Verdict`. `Criterion` is the record row's claim before `— measured:`, and the other cells copy closed tokens. The hold comment says "acceptance table", not "three-column table". `REMAINDER.md` is unchanged and finds the table under `## Acceptance` by its `AC` header. | The issue asks for "the acceptance table with each criterion's text". The column order follows the record's `HEADER`. REMAINDER reads "its acceptance table" with no column count, and close-or-hold reads only the `Acceptance state:` line. | Keeping three columns: ignores the issue. Copying the whole Criterion cell: its measured clause carries backticks, `"` and `\|`, which the guard refuses. |
| D6 | Every note site names "the Delivery record": Phase 2's skipped, reused and baseline-diff notes, Phase 5's route record and routing error, and `REVIEW.md`'s range record and diff-review scope. The block carries only the review text the body carries today (route, verdicts, scope). Findings stay in PR comments and the durable detail package. | AC3. The issue: "everything that today fills the body". PR #490's Review section held the route and the axis verdicts. REVIEW.md's severity mapping gives findings their homes. | A single global "all notes go to the Delivery record" sentence: AC3 measures each site. A new findings list in the body: duplicates PR comments and the durable package. |
| D7 | The inline fallback in `ship-handoff.md` names the four headings and the collapsed `<details>` Delivery record itself. The close clause reuses "on that condition" to pay for it (+67 B of 79). | The fallback runs when the ship-issue skill is absent, so it cannot point at Phase 4. Implementation-owner hot headroom is 79 B. | Pointing at ship-issue's Phase 4: absent on that path. Copying the full template: over the ceiling. |
| D8 | The readability rule is stated once, in Phase 4's guard paragraph: above `<details>`, explain or link each domain term on first use and name no internal ID (decision, finding, slice or `ACn`). | The issue's What to build. The guard paragraph already governs what the body may contain. | A per-section rule in each placeholder: repeats one rule four times. |
| D9 | The two new contract cases pin the template's markup and each note site's destination name. They pin no placeholder or guidance sentence. `SHIP_ISSUE_MACHINE_TEXT` is unchanged. | `docs/standards/agent-helpers.md` rule 6 and #291 D6: tests pin only text a tool or agent consumes. The markup is rendered verbatim into the `gh pr create` argument, and "Delivery record" is the handle later phases write into. | Pinning placeholder sentences: English-phrase pins. A negative "in the PR body" pin: also a phrase pin, and AC3's positive check already fails today. |
| D10 | Budget offsets, all inside the phases this change touches. Title joins the guard paragraph. Auto-close shortens and joins the acceptance paragraph. The keyword list becomes "any form of close, fix or resolve". The bare-`#N` rationale ends at "the source repo". Phase 2 step 1 says "its `tree`, `run` and `skipped`" and "each skip". Phase 8 drops the spelled-out record URL. Measured: ship-owner hot +352/464 B, `SKILL.md` 499/500 lines, gate pass. | The gate's ceilings and L2. Precedent: #439 fit reviewer guidance into the existing budget by compressing adjacent prose, with no label. | Trimming unrelated phases: scope creep. Raising a ceiling: needs the user-only label. |
