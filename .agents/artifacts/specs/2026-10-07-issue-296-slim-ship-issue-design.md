# Slim ship-issue to skill best practices (#296)

Slice S5 of program [#291](https://github.com/fagenorn/nix-config/issues/291). The
program spec (`2026-10-07-issue-291-skill-best-practices-design.md`) binds this
slice; its rows are cited as "#291 D<n>". The sibling slice's spec
(`2026-10-07-issue-295-slim-from-issue-design.md`, merged with PR #312) is the
precedent; its rows are cited as "#295 D<n>" where this slice follows them. This
spec's own rows are D1–D15 in `## Decision ledger`.

## Problem

Every agent that ships an issue loads all of `ship-issue`. Its six documents
total 86,869 bytes, and every one of the five profile-hosts that loads the skill
loads all six:

- `SKILL.md` is 841 reflowed body lines (L2 limit 500, slice target 300).
- 11 KB of it serves only lifecycle identity (`## Delivery loop`, 7.5 KB) or only
  a `delivery_remainder` owner (`## Remainder mode`, 3.4 KB). The ledger-free
  route reads neither, and the dispatch-gap fallback in the orchestrated and
  implementation owners never runs remainder mode.
- `CI-MERGE.md` is half rationale (why the watch is 300 s, why it runs in the
  foreground, a transcript-mining anecdote) and half the post-selection sync
  route, which runs only after selection when the PR goes stale.
- Rules are stated twice or three times: the Phase-6 exit codes in `SKILL.md`
  and `CI-MERGE.md`; the Codex routing in `SKILL.md` and `REVIEW.md`; the scoped
  re-review in `SKILL.md` and `REVIEW.md`; the Phase-4 push and PR commands in
  `SKILL.md` and `HUMAN-GATE.md`; "Delivery interface version 2" closing
  paragraphs that restate `## Delivery loop` in `REVIEW.md` and `HUMAN-GATE.md`.
- Reference files route to reference files: `CI-MERGE.md` names `REVIEW.md` and
  `SYNC.md`, and `REVIEW.md` names `CI-MERGE.md` and `SYNC.md` (four L4b debt
  keys). Four files exceed 100 reflowed lines with no `## Contents` (four L3 keys).
- The description is imperative ("Deliver …"), not third person (#291 D9).
- Roughly 20 test methods read these files. #313 already moved their machine-read
  text into `SHIP_ISSUE_MACHINE_TEXT`, but phrase pins and identical-copy checks
  remain (#291 D6).

## Solution

Same shape as #295: `SKILL.md` becomes the hub, holding the rules every ship run
obeys, the Phase 0–8 spine, the four dispatch sites and a one-line-per-file
reference index. Text only one route uses moves to a route file (a reference
file in #291's vocabulary). Each file is
then cut by content class. No reference file names another, so `SKILL.md` is the
only index.

### Target layout

All paths are under `home/common/agent-skills/skills/ship-issue/`. Profiles:
**S** `ship-owner` (claude, codex), **O** `orchestrated-issue-owner` (claude),
**I** `implementation-owner` (claude, codex). O and I load ship-issue only on
from-issue's dispatch-gap fallback, so everything there is conditional except
what that branch cannot reach. The prompt-only profiles `ship-issue-reviewer` and
`ship-issue-rereviewer` take their prompt from `SKILL.md` and do not change.

| File | Status | Holds | S | O | I |
|---|---|---|---|---|---|
| `SKILL.md` | kept, cut | frontmatter; the resolve paragraph; entry validation; reference index; flow; standing authorization; launch guard and `### Local commits`; gh hygiene; Phases 0–8 with the four dispatch sites and Phase 8 step 1's close-or-hold sequence; `## Delivery loop` and `## Remainder mode` as stubs (D5) | hot | cond | cond |
| `DELIVERY-LOOP.md` | new | the lifecycle-call rule and the checkpoint call; the `ship-checkpoint/v2` key set; loop steps 1–7, with the stage-to-effect map that today sits in Phases 7–8 | hot | cond | cond |
| `POST-SELECTION-SYNC.md` | new | the post-selection sync route from `CI-MERGE.md` (current selection, sync run, trigger, steps 1–7, a merge that already landed, stops), plus `REVIEW.md`'s merge-delta check, its only user | cond | cond | cond |
| `REMAINDER.md` | new | remainder mode: entry, start points, selection from the PR head, close or hold from the PR body, exits, release and `finish` | cond | - | - |
| `SYNC.md` | kept, cut | divergence, foreign commits, the two scope-creep shapes, the allowlist table, the escalation format | hot | cond | cond |
| `REVIEW.md` | kept, cut | Codex failure semantics, templates and fallback rubrics, delta-route brief, `review range:` record lines, severity mapping, the five-step apply/push flow, durable Minor/Discussion detail | hot | cond | cond |
| `CONSOLIDATE.md` | kept, cut | the bar, the rubric, the destination table, the procedure with its proposal block and empty-outcome line | hot | cond | cond |
| `CI-MERGE.md` | kept, cut | the 40-minute escalation prompt, the failing-check route, the advisory-notes overflow rule, the worktree merge-exit quirk | cond | cond | cond |
| `HUMAN-GATE.md` | kept, cut | when to enter; the `--auto` return paragraph; Gate 1 and Gate 2 (the commands rendered by Phases 4 and 7, not copies of them); grant semantics; `## Never route around a denial` | cond | cond | cond |

`REMAINDER.md` is unread in O and I. The reason recorded for it is from-issue's
own rule that the dispatch-gap fallback covers only the review-bearing ship
launch, and that a `delivery_remainder` always goes to a fresh ship owner (D3).

Every dispatch marker and `Agent(...)` line stays in `SKILL.md`, where
`model-matrix.json` records it (#295 D3). `workflow-state build-delivery` is
spelled only in `SKILL.md` (D5). No ship-issue file carries a leaf-agent clause.
Every reference file stays at or under 100 reflowed lines; one that ends up
over 100 starts with `## Contents`.

### Content classes and their disposition

| Class | Where it is today | Disposition |
|---|---|---|
| Route sections | `## Delivery loop`, `## Remainder mode`, `CI-MERGE.md`'s `## Post-selection sync`, `REVIEW.md`'s merge-delta check | Moved to the three route files. `SKILL.md` keeps both headings as stubs, with the scope sentence and a pointer (D5) |
| Lifecycle notes inside phases | Phase 7's `merge_pr`/`delete_remote_branch` notes; Phase 8's stage-order paragraph | Moved into `DELIVERY-LOOP.md`'s stage map. Each phase keeps one line: "under lifecycle identity this effect is a `## Delivery loop` cycle" |
| Helper-enforced rules | `check-launch`'s output contract; `verified-tree` exit handling; `review-range` routing; `artifact-budget` metric comparisons; the guard's `gh pr create` form; the merge subject grammar | One line each: run the command, act on its reply or refusal. A mapping line stays only where the refusal does not say what to do, e.g. `record` exit 3 `tree_changed` is a failing verification, and `check` exit 2 means run but leave the pass unrecorded (D9) |
| Duplicated rules | the items listed under Problem | One home each. Exit codes go in `SKILL.md` Phase 6 and the escalation script in `CI-MERGE.md`. The Codex rung list sits by the sites in `SKILL.md`, and the Codex failure semantics in `REVIEW.md`. The scoped re-review goes by its site in `SKILL.md`. Phase 4 holds the two commands, which `HUMAN-GATE.md` presents as rendered. The two "Delivery interface version 2" paragraphs are cut |
| Rationale and history | the launch-guard paragraph on why superseded attempts can push; why the degrade-gracefully rule does not apply; why 300 s and foreground; the 244-poll anecdote; the "two of three audited sessions" line; the bucket-removal explanation; why HUMAN-GATE's Gate 2 cannot fold into Gate 1; `D18`-style trails | Cut. Each already lives in the accepted spec it came from. One short clause stays where the rule would otherwise read as arbitrary and get "fixed" by a later edit (e.g. "never `git rev-parse HEAD` read afresh: two attempts share this checkout") |
| Policy-support sentences | "This included document receives the phase owner's retained `ResolvedProject` …" in `SYNC.md`, `CONSOLIDATE.md`, `HUMAN-GATE.md` | Cut, together with their `RETAINED_SUPPORT_CONTRACTS` rows. Every reader of these files also loads `SKILL.md`, whose resolve paragraph governs (#295 D10) |
| Self-evident text | gh JSON-field notes (`conclusion`, `merged`), which gh's own error corrects; restated "never inline"; restated "validate before decoding" after the entry rule states it once | Cut |
| Machine-read text | the four dispatch markers and calls; the resolve paragraph; the `Lifecycle worker:` line and the two `launch-scope` sentences handed to writers; vetted shell examples (the `gh pr create` form, the merge line, the watch commands, the worktree-removal block, the checkpoint and `finish` heredocs, the `.claude/settings.json` row); frontmatter `name`; JSON key sets (`ship-checkpoint/v2`, the 9-key legacy row, the stop-summary fields); `workflow-state`/`launch-commit`/`review-range`/`verified-tree` argv; the closed PR-body and comment lines (`Acceptance state:`, `Acceptance record:`, `Closes #<num>`, `Held for verification: <PR URL>`, `review range: …`); `capability_gap: agent_dispatch`; the `.superpowers/` homes | Byte for byte, in the file the consuming check reads after the move (D7) |
| Cited anchors | see D4 | Kept with their text in their file |
| Wrong rather than wordy | see `### Findings to file` | Not edited, carried over verbatim (D12) |

The description becomes third person with its trigger clause kept, and no longer
than today's 178 bytes (D10):
`Delivers a finished feature-branch worktree: integration-branch sync, PR, review, CI, merge, issue close or hold, cleanup. Phase 7 of from-issue. Use for "ship #X", "land it".`
(175 bytes).

### Byte and line targets

Measured at the slice base `baac2897` (origin/main after #295 merged; the
ship-issue documents are byte-identical to this worktree's fork point
`defc1458`), with `just agent-instruction-load report --base baac2897 --head
baac2897 --format json` and the base-side bytes of each `documents` member.
The five loading profile-hosts are S claude, S codex, O claude, I claude and
I codex. Each loads all six files, 86,869 bytes. Together they total 1,140,613
hot+conditional bytes, of which **434,345** are ship-issue's.

The slice is held to the **ship-issue share**. That is the sum, over those
profile-hosts, of the bytes of the `ship-issue/` members each lists hot or
conditional, at base and at head. The bound is `head ≤ 0.65 × base`, so
**`head ≤ 282,324`** (D1). The whole-profile total is reported beside it.

Per-file targets (bytes; ceilings, not goals):

| File | Base | Target | Loads |
|---|---|---|---|
| `SKILL.md` | 49,934 | ≤ 22,000 and ≤ 280 reflowed body lines | 5 |
| `DELIVERY-LOOP.md` | — | ≤ 4,500 | 5 |
| `POST-SELECTION-SYNC.md` | — | ≤ 4,800 | 5 |
| `REMAINDER.md` | — | ≤ 2,600 | 2 |
| `SYNC.md` | 4,237 | ≤ 2,700 | 5 |
| `REVIEW.md` | 9,461 | ≤ 5,800 | 5 |
| `CONSOLIDATE.md` | 4,931 | ≤ 3,300 | 5 |
| `CI-MERGE.md` | 11,980 | ≤ 3,000 | 5 |
| `HUMAN-GATE.md` | 6,326 | ≤ 3,800 | 5 |

At the targets the share is 49,900 × 5 + 2,600 × 2 = 254,700 bytes, 58.6% of
base. That leaves 27,624 bytes under the 0.65 line, so one file overshooting
does not fail the slice. An overshoot in `SKILL.md` costs five times its size.
Its 280 lines leave 20 under the 300 acceptance line. Lines are measured with
`skill_lint.reflowed_lines` over `parse_frontmatter`'s body (#295 D8). A
paragraph may sit on one physical line, because reflow counts it per 100
characters anyway.

At the targets no profile ceiling rises. S hot falls from 68,563 to about 38,300.
S conditional falls by about 4 KB per host (its ship-issue part goes from 18,306
to 14,200). The O and I conditional sets each fall by about 37 KB. Membership
still changes (D2).

### Test-pin deletion (#291 D6)

The inventory at `baac2897` is taken from `test_workflow_skill_contracts.py`.
No scoped file is read by `test_ship_release_contracts.py` or
`WorktreesGuidanceTest`, so neither changes. `test_diff_scope.py` only names
`SYNC.md` in a synthetic row, and `test_shell_example_contracts.py` holds
copies of examples and sweeps every `*.md` by content. Neither needs an edit,
provided each moved example keeps its vetted form.

The rule for each assertion is applied in the commit that rewrites the text it
reads. It is #295 D11, with #295 D13 for shared corpora:

1. **Machine-read assertions stay** and are re-pointed at the file that now holds
   the text. These are `SHIP_ISSUE_MACHINE_TEXT`, which gains keys for the three
   new files and moves each item with its text: the loop items, the
   `--kind scope`/`test_ref`/`tracker_held` facts and `checkpoint-delivery` go
   to `DELIVERY-LOOP.md`; `--kind current-selection`, `release-worker` and
   `finish --summary-file -` go to `REMAINDER.md`; `--kind sync-selection` and
   the `mergeable` view go to `POST-SELECTION-SYNC.md`. `HUMAN-GATE.md` loses its
   push and `gh pr create` items, whose only home is now `SKILL.md` Phase 4.
   The others are the merge-delta marker, the watch fence, the merge-line forms,
   the bare-name helper anchors (`~/.agents/bin/workflow-state`, `review-range`
   and `review-package` stay in `SKILL.md`), the dispatch ids, the capability
   gap line, `WORKTREE_BUCKET_LITERAL`, `.superpowers/ship-review` having
   `REVIEW.md` as its single carrier, `.superpowers/issue-delivery/` in
   `REVIEW.md`, `SHARED_POLICY_ENTRIES["ship-issue/SKILL.md"]`, and the
   `build-delivery` caller list (`SKILL.md` stays its only ship-issue entry).
2. **`LIFECYCLE_DOCS`** replaces its three ship-issue entries with
   `*sorted(ship-issue/*.md)`, as #295 did for from-issue. That puts every new
   route file under the `-`-only input-flag check.
3. **Prose assertions on scoped files are deleted.** This covers `STDIN_CLAUSE`
   for `SHIP_ISSUE`, the ship-issue members of
   `test_delivery_interface_two_is_one_atomic_production_caller_contract`'s
   corpus, the `"keep the worktree"`/`report_path` phrase checks on
   `ship_review` and `ship_issue`, `SHIP_ISSUE` in `InterimChildResultContractsTest`
   (its `OWNERS`, the identical-copy loop and the section table; D8), and the
   three ship-issue rows of `RETAINED_SUPPORT_CONTRACTS`. Assertions on other
   skills' text in the same methods stay. A method left with no assertion is
   deleted.
4. **Kept on purpose:** `test_human_gate_carries_no_affirmative_bypass_instruction`.
   It asserts that no bypass spelling appears outside the ban list, so a deletion
   can never turn it red; only an added instruction can. Its heading anchor
   `## Never route around a denial` keeps its text (D11).

Constraints the rewrite keeps:

- `agent_model_matrix`: each marker is one whole line, once, in `SKILL.md`, with
  its call on the next line. `DISPATCH_MARKER_TOTAL` is unchanged.
- `test_shell_example_contracts`: moved commands keep their heredoc-fed,
  whole-allowed form, with no new chain, redirect or substitution.
- `test_dispatch_contracts`: no leaf-agent clause appears anywhere in ship-issue.
- `skill_lint` L3/L4: no reference file names a sibling. Cross-file pointers go
  through `SKILL.md`'s index (D6).
- `test_superpowers_homes_are_a_closed_allowlist`: every `.superpowers/` segment
  ship-issue spells today is still spelled somewhere.

### `instruction-load.json`, `skill-lint-debt.json` and the label

`skill-lint-debt.json` loses all nine ship-issue keys: `L2 …/SKILL.md`,
`L3 …/{CI-MERGE,CONSOLIDATE,HUMAN-GATE,REVIEW}.md` and the four `L4b` keys.
A stale key fails the lint, so each key leaves in the commit that clears it.
Shrinking the file needs no label.

`instruction-load.json` changes only in S, O and I. Its other entries and its
notes are untouched, so a parallel slice's edit to the same file conflicts on
lists, not prose (D13):

1. **Membership** (needs the label): add `DELIVERY-LOOP.md`,
   `POST-SELECTION-SYNC.md` and `REMAINDER.md` per the layout table. Give
   `REMAINDER.md` an `unread` reason in O and I. The closure check makes this
   unavoidable: `SKILL.md` must name every reference file (L4a), and a profile
   that loads `SKILL.md` must list every file it names (D2).
2. **Ceilings**: each task runs `just agent-instruction-load tighten`. A task
   whose intermediate state raises a ceiling (for example, a route file split
   out before its origin is cut) sets that ceiling to the measure and names the
   raise in its commit body. The final head raises none (D14).

Only the user applies `instruction-budget-raise` (#291 D2). The PR's
`Instruction Budget` check stays red on its `raise:` line until the label is
present. That red check is the human gate, not a CI failure to fix. The ship
phase stops there through ship-issue's existing human-gate path: the ship owner
returns the gate in a truthful `stopped` summary, and the from-issue owner
suspends `blocked_on=human_gate` until the label is present. No agent applies
the label, and no step edits `instruction-load.json` to clear the `raise:` line
(#295 D5). After every integration-branch sync the owner re-runs `tighten` and
the report.

### Eval plan

The only pipeline case is case 5, `tracker-free-ship-stops-before-push`. It
covers the standalone, ledger-free, tracker-free route through Phases 0–4. The
S3 baseline rows of 2026-10-07 (`evals/results/results.jsonl`, deployed tree)
are Sonnet 5/6 and 6/6, and Opus 6/6 and 6/6. The single Sonnet miss was "the
run names the push it would run next".

Run `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals ship-issue 5` once for each
model. The criterion: the pass count is at or above the lowest baseline row for
that model (Sonnet ≥ 5, Opus 6), and no assertion fails that never failed in a
baseline row (D15). Cases 1–4 are plan-only and graded by hand, so they are not
part of the acceptance criterion.

Tree mode needs `CLAUDE_CODE_OAUTH_TOKEN`, which is unset in this environment.
The run is gated, not skipped (#295 D6). The Phase-6 owner runs the two evals
only when the token is present, and commits their rows. Otherwise:

- the plan's evidence row is `human_pending`;
- the sdd report carries `acceptance_state: human_pending`;
- ship-issue holds the issue open as `needs-verification`, with the two exact
  commands in its verdict table.

No result is claimed, estimated or copied from the baseline.

### Findings to file

These are filed as new issues after this phase, not fixed here. Their text is
carried over verbatim:

1. **The docs-only CI skip is wrong here.** Phase 6 skips the CI wait when every
   changed path ends in `.md`, saying a markdown-only diff "cannot break a
   build". In this repository, skill `.md` files are the product. The required
   `Instruction Budget` check runs on every PR, and `.github/branch-protection.json`
   requires it with `enforce_admins`. So a markdown-only skill PR reaches the
   merge with its required check unresolved. Protection then refuses the merge,
   and nothing in the skill tells that refusal apart from the stale-head
   refusal that starts the post-selection sync.
2. **The CI escalation prompt offers "(c) merge without CI if the project allows
   admin-merge".** That contradicts `.agents/knowledge/rejections/ungated-agent-merges.md`
   and `HUMAN-GATE.md`'s ban on `--admin`. The escalation should offer only
   options that keep the required-check floor.
3. **The allowlist regenerates `Cargo.lock` with `cargo update`.** That command
   upgrades every dependency to its newest compatible version, rather than
   resolving the lockfile for the merged manifests (as `cargo generate-lockfile`
   or a build would). A sync merge can therefore carry unrelated version bumps.
4. **`from-issue/ship-handoff.md`'s inline fallback says "merge `--no-ff`".**
   ship-issue's Phase 7 and `CI-MERGE.md` say recent `gh` rejects that flag.
   from-issue owns the file, so it goes to the owning slice.
5. The program's `--max-body-lines` flag is still missing. That is #295's
   finding 1. If it is still unfiled when these are filed, it is filed once,
   for S4–S7.

## Decisions

- **Hub and spokes.** `SKILL.md` is the only document that names a reference
  file. Route and phase files name `SKILL.md` sections by heading, never a
  sibling (L4).
- **Route selection is unchanged.** A handoff starts at Phase 0. A
  `delivery_remainder` starts in remainder mode. Lifecycle identity runs the
  loop from the pre-merge selection gate. A stale or conflicting PR after
  selection takes the post-selection sync. Each route file starts where its
  section starts today.
- **No semantic change.** Every gate, order, closed set, stop and return shape
  keeps its meaning. A sentence is cut only when a helper enforces it, another
  home holds it, or it is rationale. A sentence that would change behaviour if
  read literally is kept or reported (D12).
- **Anchors other skills cite stay true (D4).** The headings this slice keeps in
  `SKILL.md` keep their text, and the phases keep their numbers and titles.

## Test seams

- `skill-lint check` (L1–L5, debt shrink), plus `skill_lint.reflowed_lines`
  over `SKILL.md`'s body for the 300-line target.
- `just agent-instruction-load report`/`check`/`tighten` for membership,
  closure, ceilings and the share measure. `just agent-instruction-budget
  --raise-label` locally, to prove the only remaining failure is the `raise:`
  line.
- The existing machine-read checks inside `just agent-workflow-tests`:
  `test_ship_issue_documents_carry_their_machine_text`,
  `test_dispatch_contracts`, `test_shell_example_contracts`,
  `test_agent_model_matrix`, `test_instruction_load`'s live-tree test,
  `LIFECYCLE_DOCS`, and the lifecycle key-set tests.
- The eval harness for behaviour (above). No new test pins prose.

## Out of scope

- Other skills' documents, even where they cite a ship-issue anchor (#291 D8).
  These include `from-issue` (S4), `sdd` (S6), `ship-release` and
  `orchestrate-issues` (S7), and the shared `agents/*.md`, `AGENTS.md`,
  `doc-grounded-questions` and `worktrees` (S8).
- Helper behaviour and helper error text (D9), the gate's own files, and the
  `--max-body-lines` flag.
- Workflow semantics: phases, gates, review axes, report shapes, and the findings
  above.
- `model-matrix.json`, profile prompts, dispatch sites, hosts, and other
  profiles' entries and notes in `instruction-load.json`.
- `evals.json` and its plan-only cases.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The −35% target is the ship-issue share: the bytes of `ship-issue/` members each loading profile-host lists hot or conditional, summed. Base 434,345 at `baac2897`, head ≤ 282,324. The whole-profile total (1,140,613) is reported beside it | #295 D1; #291 D8. The other 706,268 bytes of those profiles belong to other slices | The literal whole-profile sum: cutting ship-issue to zero would still miss it |
| D2 | Add `DELIVERY-LOOP.md`, `POST-SELECTION-SYNC.md` and `REMAINDER.md`. The `instruction-budget-raise` label is therefore unavoidable, and ship stops at the human gate until the user applies it | The 300-line target cannot hold the 11 KB of lifecycle and remainder text. The issue requires per-route files. L4a and closure force listing them. Any membership edit needs the label (#291 D2, #295 D5) | Folding the loop into an existing file to avoid the label: no hot-path file fits it, and putting it in a conditional file would misclassify the standard route |
| D3 | `DELIVERY-LOOP.md` is hot in S, where a `ship-handoff/v2` is the standard handoff, and conditional in O and I. `POST-SELECTION-SYNC.md` is conditional everywhere. `REMAINDER.md` is conditional in S and unread in O and I, because from-issue's fallback "covers only the review-bearing ship launch". Moved text keeps its old class everywhere else | #295 D2; S's prompt step 5 runs the loop for every v2 handoff; from-issue's Phase-7 fallback paragraph | Making the post-selection sync hot in S: it runs only after selection when the PR goes stale. Leaving remainder text loaded in O and I: their route cannot reach it |
| D4 | These anchors keep their text and file. In `SKILL.md`: the headings `## Delivery loop` and `## Remainder mode` (now stubs), the Phase-0 reviewer-dispatch probe, Phase 5's range selection, Phase 8 step 1's hold sequence, the `## gh hygiene` `unset GITHUB_TOKEN && ` derivation, `### Local commits`, and the Phase 0–8 headings. In `HUMAN-GATE.md`: the case of an owner running the path itself. In `REVIEW.md`: the worktree-local retained candidate. Auto-mode rules stay stated where the handoff's "ship-issue's auto-mode rules" finds them (the severity mapping and fix flow) | Out-of-scope citers: from-issue `SKILL.md`, `AUTO.md`, `ship-handoff.md`; `worktrees/SKILL.md`; `sdd/SKILL.md`; `sdd-workspace` (#291 D8, #295 D9) | Re-pointing the citers: that edits documents other slices own |
| D5 | The two stubs keep a scope sentence and a pointer. The `## Delivery loop` stub also keeps the one sentence naming `workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input -` as the builder. The route files say "the builder" and never spell the command | `test_build_delivery_callers_name_the_sanctioned_resolution_exception` requires every `build-delivery` caller to carry the resolve paragraph's exception sentence. `SKILL.md` already carries it, byte for byte | Spelling the builder in each route file: three more resolve-exception copies, or widening a shared test's caller list |
| D6 | Where a route file needs another file today (post-selection sync step 1 needs Phase 1's sync rules, step 3 needs the severity mapping and durable detail), it names the `SKILL.md` phase. `SKILL.md`'s index line for that file names the companions it reads with | L4b; #295 Decisions ("cross-file pointers go through `SKILL.md`") | Keeping sibling names under a debt key: the debt file may only shrink, and S5's acceptance requires no ship-issue key |
| D7 | Machine-read text moves byte for byte into the file its consuming check is re-pointed to. `SHIP_ISSUE_MACHINE_TEXT` gains the three new files as keys. `HUMAN-GATE.md` drops its copies of the Phase-4 push and `gh pr create` commands and presents Phase 4's rendered commands | #291 D6; The Bar, DRY (the copies must change together); the guard validates the executed command, not `HUMAN-GATE.md`'s copy | Keeping both copies pinned: the duplicate is the drift risk the pin was guarding against |
| D8 | ship-issue keeps the **Interim child results** rule's every clause in a shortened paragraph in Phase 5. It leaves `InterimChildResultContractsTest`'s `OWNERS`, identical-copy and section checks, which then cover from-issue and sdd | #295 D13; #291 D6. The identical-copy check is a phrase pin, and from-issue and sdd keep theirs | Keeping it byte-identical: the 1.2 KB pays rent five times, for a test this slice deletes anyway |
| D9 | No helper is edited. A refusal whose text does not say what to do gets one mapping line in the skill. The cases are `verified-tree record` exit 3 `tree_changed`, `check` exit 2, `check-launch` output other than the four-key object, `review-range` exit 1, and `gh pr checks` exit 1 `no required checks reported` | #295 D7. #291 permits improving error text but does not require it. These messages are read by tests and by other skills | Rewording the helpers' messages: the same skill line plus helper and test churn outside the slice |
| D10 | The description becomes third person and keeps its trigger clause, in 175 bytes against today's 178 | #291 D9; the description ceiling sums every skill's description | Rewriting the trigger phrases: they are what users type |
| D11 | Tests follow #295 D11/D13 as listed under Test-pin deletion. `LIFECYCLE_DOCS` globs `ship-issue/*.md`. `test_human_gate_carries_no_affirmative_bypass_instruction` stays | #291 D6; `docs/standards/agent-helpers.md` rule 6; the bypass test fails only on an added instruction, never on a deletion | Deleting the bypass test as a pin: it guards a safety property (no affirmative `--admin`/force instruction) that only an addition can break |
| D12 | Four wrong rules are filed, not fixed, and their text is carried over verbatim: the docs-only CI skip, the admin-merge escalation option, `cargo update` in the allowlist, and from-issue's `--no-ff` fallback. `--max-body-lines` stays #295's finding | #291 Out of scope ("a slice that finds a rule which is wrong rather than wordy files an issue"); `branch-protection.json`; `rejections/ungated-agent-merges.md` | Fixing them here: these are semantic changes inside a slice that must not change workflow semantics |
| D13 | Shared-file edits stay inside ship-issue's own entries: S/O/I member lists and ceilings, ship-issue debt keys, ship-issue test constants and rows. No profile `note` is edited | #291 D8; later slices conflict-merge into the same files | Adding #296 sentences to the O and I notes: prose conflicts with S6 and S7 for no reader benefit, since the `unread` reason already says why |
| D14 | Each plan task keeps the gate green at its own commit. It deletes the debt keys its change clears and runs `tighten`. It sets any intermediate raise to the measure and names it in the commit body. The last task re-tightens and reports the share | #295 D12; `LiveBudgetTest` checks breach and 5% tightness on every commit | One closing task for all debt and ceiling edits: every earlier commit fails `just agent-workflow-tests` |
| D15 | Evals run only case 5 (the sole pipeline case), on Sonnet and Opus, in tree mode. They pass when each model scores at least its lowest baseline row and no assertion fails that never failed at baseline. Without `CLAUDE_CODE_OAUTH_TOKEN` the evidence is `human_pending` | #291 D7/D11; #295 D6; the 2026-10-07 baseline rows | Requiring 6/6 on Sonnet: the baseline itself scored 5/6 once, so that would flag noise as regression |
| D16 | Each `SHIP_ISSUE_MACHINE_TEXT` item is pinned only in its one home. `CI-MERGE.md`'s key is removed, because its three watch commands live in `SKILL.md` Phase 6. `HUMAN-GATE.md`'s key loses `Closes #<num>` with the `gh pr create` copy and keeps the Gate 2 chain commands. The machine-read phrases `test_delivery_interface_two_is_one_atomic_production_caller_contract` found only in ship-issue (`current-launch`, `ship-checkpoint/v2`) move to `DELIVERY-LOOP.md`'s key | D7; #291 D6; The Bar, DRY | Keeping the copies pinned in `CI-MERGE.md` and `HUMAN-GATE.md`: a pin on a copy would block the cut that removes the duplicate |
| D17 | The Phase-4 `git push -u origin <branch>` and guard-form `gh pr create` pins move to `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE]` when Task 4 drops them from `HUMAN-GATE.md`'s key | Global Constraints (machine-read assertions are re-pointed), D16 (one home each); Task 4 review found the brief's verbatim tuple left them pinned nowhere | Leaving them unpinned: a deleted or reordered fence would pass every test while the lifecycle guard refuses the command at runtime |
