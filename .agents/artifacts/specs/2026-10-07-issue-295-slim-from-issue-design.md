# Slim from-issue to skill best practices (#295)

Slice S4 of program [#291](https://github.com/fagenorn/nix-config/issues/291). The
program spec (`2026-10-07-issue-291-skill-best-practices-design.md`) binds this
slice; its rows are cited here as "#291 D<n>" and are not restated. This spec's
own rows are D1–D11 in `## Decision ledger` below.

## Problem

Every agent that runs `from-issue` pays for all of it. The nine scoped documents
total 113,396 bytes, and the five profile-hosts that load `SKILL.md` each carry
95–104 KB of from-issue prose before they read any code:

- `SKILL.md` is 915 reflowed lines (L2 limit 500, slice target 300). 196 of
  them are four acquisition routes, of which exactly one applies to an
  invocation, and 52 more serve only a relaunch.
- `AUTO.md`'s Phase-5 rollover (10 KB) is loaded by the dispatcher-owned owner,
  whose route never rolls over, and its transfer half by the fresh delegated
  owner, which only needs the receiving half. The profile notes already call
  this "route-scoping deferred (#155 D6)".
- Rules that `workflow-state`, `artifact-budget` and `launch-scope` enforce and
  explain on refusal are restated in prose, sometimes twice (the producer gate
  and the accepted-edit remeasurement appear in both `standards-review.md` and
  `REVIEW-CONTRACT.md`).
- Rationale and history sit in the hot path (the deadline-expiry paragraph is
  30 lines of why).
- Reference files route to reference files (`AUTO.md` names three siblings,
  `decision-ledger.md` names `AUTO.md`), and `AUTO.md` and `ship-handoff.md`
  exceed 100 lines with no `## Contents`.
- About 96 test methods read these files and most pin English phrases, so any
  rewording costs a test edit (#291 D6).

## Solution

Restructure the skill around **routes and phases**, then cut. `SKILL.md`
becomes the hub: identity rules every lifecycle owner obeys, the route
selector, the phase spine, and one-line pointers to reference files that hold
the content only one route or one phase uses. Each profile then lists a route
file hot only where that route is its standard route, conditional where it is a
named branch, and unread where it cannot occur. No reference file names
another, so `SKILL.md` is the only index.

Then each document is cut by content class (per-file table below): helper-
enforced rules shrink to "run X; act on its refusal", rationale leaves for the
specs that already hold it, duplicated text keeps one home, and machine-read
text is kept byte for byte (#291 D6).

### Target layout

All paths are under `home/common/agent-skills/skills/from-issue/`. "Hot" and
"cond" name the classification in each profile; `-` is unread (with a reason in
the profile). Profiles: **C** `from-issue-controller` (claude, codex), **O**
`orchestrated-issue-owner` (claude), **I** `implementation-owner` (claude,
codex), **P** `planning-owner`, **R** `plan-reviewer`. The prompt-only profiles
(`design-and-grill-owner`, `ship-owner`, `inline-ship-reviewer`,
`from-issue-mechanic`, `from-issue-mechanical-reviewer`) name a from-issue file
as their prompt source, which is not measured; their prompt fields and dispatch
sites do not change.

| File | Status | Holds | C | O | I | P | R |
|---|---|---|---|---|---|---|---|
| `SKILL.md` | kept | resolve rule; reference index with one-line load conditions; route selector; lifecycle identity; flow and checkpoints; ledger, lanes, Skill-tool rules; dispatch rules (leaf clauses, writing workers, self-reap, interim results, report boundary, phase gate with the `delegate` and bookkeeper sites); terminal return and suspension procedures; Phases 0–7 spine with the mechanical and ship-owner sites | hot | hot | hot | - | - |
| `acquire-dispatcher.md` | new | dispatcher-owned acquisition (envelope fields, owner-object validation, `delivery_remainder` relay); also the envelope a generic `delegate` owner receives | - | hot | cond | - | - |
| `acquire-direct.md` | new | direct autonomous acquisition (the interface-2 request JSON, the `direct-owner` and `build-delivery --kind contract` commands, the four reply kinds, the `resume` re-entry) | hot | - | - | - | - |
| `acquire-interactive.md` | new | ledger-free interactive acquisition and the ledger-free Phase-1 `worktrees` flow | cond | - | - | - | - |
| `acquire-durable.md` | new | explicit durable interactive acquisition (`init-run`, contract rule, control request, dispatch adoption) | cond | - | - | - | - |
| `resume-pack.md` | new | the resume-pack checks and what a verified pack replaces | cond | cond | cond | - | - |
| `AUTO.md` | kept, cut | auto posture; self-answer pattern; content stops; Phases 2–4 dispatch with both owner sites and their report shapes; Phase 5–7 rules for non-rollover routes; delivery relay | hot | hot | hot | - | - |
| `rollover.md` | new | the Phase-5 transfer gate, the continuation shape and the earlier-controller stop | hot | - | - | - | - |
| `delegated-owner.md` | new | the fresh delegated owner's checks and its Phase 6–7 sequence | - | - | hot | - | - |
| `investigate.md` | kept | PR pre-flight, the worktree pre-flight inspection (moved from `SKILL.md`), the note structure | hot | hot | - | - | - |
| `standards-review.md` | kept, cut | the caller input gate, route choice with the plan-review site, dispositions and the one accepted-edit remeasurement | hot | hot | - | - | - |
| `REVIEW-CONTRACT.md` | kept, cut (payload) | reviewer instructions, acceptance-map check, common-miss checklist, output | - | - | - | cond | hot |
| `ship-handoff.md` | kept, cut | ship-owner prompt, Phase-7 report handling and dispatch-gap fallback (moved from `SKILL.md`), inline fallback with its site, remainder-owner prompt | cond | hot | hot | - | - |
| `decision-ledger.md` | kept | the C1 table and rules (paste source) | hot | hot | cond | - | - |
| `bindings.md` | deleted | — its one rule is `SKILL.md`'s resolve paragraph (D4) | | | | | |
| `grounding.md` | deleted | — `doc-grounded-questions` owns the pass and the cache; `SKILL.md` keeps one line (D4) | | | | | |

`REVIEW-CONTRACT.md`, `AUTO.md`, `investigate.md`, `standards-review.md`,
`ship-handoff.md` and `decision-ledger.md` keep their names: other skills,
profile prompts and dispatch sites name them. Every dispatch marker and
`Agent(...)` line stays in the file `model-matrix.json` records for it, so the
matrix, every profile's `prompt`, `excluded_sites` and the payload set are
unchanged (D3). A file whose route its profile cannot take stays unread with a
reason, as the closure check requires (D2).

### Content classes and their disposition

| Class | Where it is today | Disposition |
|---|---|---|
| Route sections | `SKILL.md` §Lifecycle identity's four `###` routes; `AUTO.md`'s rollover; Phase 1's ledger-free list | Moved to the route files above. `SKILL.md` keeps a four-line selector, one condition per route, in the existing order (envelope, then `--auto`, then durability request, else interactive) |
| Relaunch-only text | `SKILL.md` §Resume pack | Moved to `resume-pack.md`; its list of always-read sections is rewritten against the new layout |
| Phase-only detail | Phase-0 worktree inspection; Phase-7 report handling and dispatch-gap fallback | Moved to `investigate.md` and `ship-handoff.md`, the files those phases already load |
| Helper-enforced rules | observation-slot discipline, deadline and `progress` rejections, live-worker refusals, artifact-budget metric comparisons, check-launch outcomes, contract-path refusals | One line each: run the command, obey its reply or refusal. Where the refusal does not say what to do, one mapping line stays (D7) |
| Duplicated rules | producer gate and accepted-edit remeasurement in both standards files; leaf clauses spelled twice in `ship-handoff.md`; `bindings.md` and `grounding.md` restating `SKILL.md` and `doc-grounded-questions` | One home each: the caller gate and remeasurement in `standards-review.md`; `REVIEW-CONTRACT.md` keeps reviewer-facing sections only |
| Rationale and history | deadline-expiry explanation, "why a fresh ship owner", "why one design dispatch", the Phase-0 race warning, interface-version history, D-number trails such as "(D5, D6, D11, D14)" | Cut. Each already lives in the accepted spec it came from; the plan cites none of them back into the skill |
| Self-evident text | sentences an agent following the rule would not get wrong without (restated "never inline", repeated "validate before decoding" after the identity section states it once) | Cut |
| Machine-read text | dispatch markers and `Agent(...)` lines; the leaf-agent clauses and the `Lifecycle worker:` carrier lines; vetted shell examples; frontmatter; JSON key sets (the request JSON, report shapes, continuation, both handoff shapes, `ship-summary/v2` keys); `workflow-state`, `launch-scope` and `resolve-project` argv | Byte for byte, in the file the consuming check reads (D3) |
| Wrong rather than wordy | — | Not edited; recorded in `### Findings to file` (D7) |

### Byte and line targets

Measured at the slice base `a891b08c` with `just agent-instruction-load report
--base origin/main --head HEAD --format json`. The five profiles that load a
scoped file in hot or conditional, over all their hosts, total 1,348,691 bytes,
of which 539,997 are from-issue documents (C 103,917 ×2, O 103,917, I 95,165
×2, P 9,479 ×2, R 9,479 ×2). The remaining 808,694 belong to `sdd`,
`ship-issue`, `codex-collaboration`, `worktrees` and the shared documents,
which other slices own (#291 D8).

The measure this slice is held to is therefore the **from-issue share** of
those profiles: the sum, over every profile-host above, of the bytes of the
`from-issue/` members it lists hot or conditional, at base and at head;
`head ≤ 0.65 × base`, so `head ≤ 350,998` (D1). The whole-profile total is
reported beside it but cannot reach −35% without other slices' cuts.

Per-file targets (bytes, ceiling not goal):

| File | Base | Target | Loads (profile-hosts) |
|---|---|---|---|
| `SKILL.md` | 54,921 | ≤ 21,000 and ≤ 280 reflowed body lines | 5 |
| `AUTO.md` | 24,111 | ≤ 8,500 | 5 |
| `rollover.md` | — | ≤ 3,800 | 2 |
| `delegated-owner.md` | — | ≤ 3,000 | 2 |
| `acquire-dispatcher.md` | — | ≤ 1,500 | 3 |
| `acquire-direct.md` | — | ≤ 5,500 | 2 |
| `acquire-interactive.md` | — | ≤ 1,000 | 2 |
| `acquire-durable.md` | — | ≤ 2,000 | 2 |
| `resume-pack.md` | — | ≤ 2,400 | 5 |
| `ship-handoff.md` | 14,300 | ≤ 11,000 (absorbs Phase-7 handling) | 5 |
| `investigate.md` | 3,174 | ≤ 3,800 (absorbs worktree inspection) | 3 |
| `standards-review.md` | 4,552 | ≤ 3,200 | 3 |
| `REVIEW-CONTRACT.md` | 9,479 | ≤ 6,800 | 4 |
| `decision-ledger.md` | 1,018 | ≤ 950 | 5 |

At the targets the from-issue share is 21,000×5 + 8,500×5 + 3,800×2 +
3,000×2 + 1,500×3 + 5,500×2 + 1,000×2 + 2,000×2 + 2,400×5 + 11,000×5 +
3,800×3 + 3,200×3 + 6,800×4 + 950×5 = 302,550 bytes, 56.0% of base: the
targets leave 48 KB of slack under the 0.65 line, so one file overshooting does
not fail the slice, while `SKILL.md`, `AUTO.md` and `ship-handoff.md` (five
loads each) are where an overshoot costs most. `SKILL.md`'s 280 lines leave
20 lines under the 300 acceptance line.

Moving text between hot and conditional changes neither total, since the
measure sums both (#291 Decisions). Moving it to unread counts only where the
profile truly cannot take that route; D2 records the test applied.

### Test-pin deletion (#291 D6)

Inventory at base (`test_workflow_skill_contracts.py`, 6,246 lines): about 96
methods read a scoped file. About 55–60 are prose-dominant, about 35–40 mix
prose with machine-read checks, and about 55 locate text by a heading. No
scoped file is read by `test_ship_release_contracts.py` or by
`WorktreesGuidanceTest` (which reads only `worktrees/SKILL.md`), so neither
changes. The two pins at L3509/L3517 sit on `ship-issue/HUMAN-GATE.md`, which S5
owns; they stay, and so does the text they pin (D9).

The rule per assertion, applied in the commit that rewrites the text it reads:

1. **Prose assertion** (`assertIn`/`assertNotIn`/`assert_ordered` over an
   English sentence or phrase, the sentence constants such as
   `BUILD_ROOT_CLAUSE`, `WRITER_RULE`, `REPORT_CANDIDATE_CLAUSE`): deleted. A
   method left with no assertion is deleted.
2. **Machine-read assertion** (#291 D6's list): kept, and re-pointed at the
   file that now holds the text. Concretely: the 16-key request JSON and the
   continuation's owner keys and artifact fields (`acquire-direct.md`,
   `rollover.md`); the `ship-handoff/v2`, legacy and `ship-summary/v2` key sets
   (`ship-handoff.md`); every `--request-file`/`--checkpoint-file`/
   `--summary-file`/`--input` value being `-`, over a `LIFECYCLE_DOCS` that
   gains the new route, rollover and delegated-owner files; the closed
   `capability_gap: agent_dispatch` and `blocked_on` value sets (the set, not
   an occurrence count); the `Agent(` line shape; and the ordered
   `workflow-state`/`launch-commit`/`launch-scope` argv and the
   `Lifecycle worker:` line.
3. **Heading anchor**: a test that slices by a heading follows the heading to
   its new file. Moved headings keep their text, so most anchors only change
   file; a heading only tests read may be renamed with its test (#291 D6).
4. **Shared policy tables**: `SHARED_POLICY_ENTRIES` keeps
   `from-issue/SKILL.md`, whose resolve paragraph stays byte for byte (D10);
   the from-issue rows of `SHARED_POLICY_SUPPORT` and
   `RETAINED_SUPPORT_CONTRACTS` are removed with the per-file "receives the
   retained `ResolvedProject`" sentences they pin.

Constraints from the machine-read checks that the rewrite must keep:

- `test_dispatch_contracts`: the three leaf-agent clauses appear exactly once
  in `SKILL.md`'s `## Dispatch, phase-budget and attempt-budget rules` region
  (up to the next `#`/`##` line) and once in `ship-handoff.md`'s single
  unlabeled fence, and nowhere else in either tree. `ship-handoff.md` keeps
  exactly one unlabeled fence and the remainder prompt's placeholder line. Any
  from-issue file with exactly one unlabeled fence must be an enrolled
  carrier, so every new file uses labeled fences (`json`, `text`) only.
- `agent_model_matrix`: each marker is one whole line, once, in its recorded
  file, with its call on the next line (D3). `DISPATCH_MARKER_TOTAL` stays 39.
- `test_shell_example_contracts` sweeps every `*.md`: moved commands keep their
  heredoc-fed, whole-allowed form; no chain, redirect or substitution is
  introduced.
- `instruction_load` closure and `skill_lint` L3/L4: every file over 100
  reflowed lines starts with `## Contents`; no reference file names a sibling.

### `instruction-load.json`, `skill-lint-debt.json` and the label

`skill-lint-debt.json` loses all six from-issue keys (`L2 …/SKILL.md`, `L3
…/AUTO.md`, `L3 …/ship-handoff.md`, the three `L4b …/AUTO.md names …` keys and
`L4b …/decision-ledger.md names AUTO.md`); a stale key fails the lint, so they
leave in the same commit that clears them. Shrinking the debt file needs no
label.

`instruction-load.json` changes in two ways:

1. **Membership** (needs the label): add the seven new files to C, O and I as
   the layout table says, each unread entry with a one-line reason; drop
   `bindings.md` and `grounding.md` from C, O and I; reclassify nothing else.
   The closure check makes this unavoidable: `SKILL.md` must name every
   reference file (L4a), and a profile that loads `SKILL.md` must then list
   every file it names. The issue itself requires the route files, so a
   label-free layout (all route text folded into existing files) would not meet
   it (D5). Each touched profile's `note` gains one sentence naming #295 and
   drops the "route-scoping is deferred (#155 D6)" clause this slice resolves.
2. **Ceilings**: `just agent-instruction-load tighten` lowers every hot ceiling
   to its measure. A conditional ceiling can rise, because relaunch-only and
   interactive-only text leaves hot `SKILL.md` for conditional files: C, O and
   I each gain `resume-pack.md`, C the two interactive route files and I
   `acquire-dispatcher.md` on the conditional side. Those raises are set to the head measure in the same
   labelled change, and the PR body lists each with its matching hot drop.

`raise` therefore fires on this PR whatever else it does, and only the user
may apply `instruction-budget-raise` (#291 D2). The ship phase stops at that
human gate before merge, by ship-issue's existing human-gate path: the ship
owner returns the gate, and the from-issue owner suspends with
`blocked_on=human_gate` and resumes when the label is present. No agent applies it, and no step works around the
`raise:` line (D5).

### Shipping under the label gate

The `Instruction Budget` check is required, so this PR's checks stay red on
the `raise:` line until the user applies the label. That red check is the human
gate, not a CI failure to fix: the ship handoff's `notes` names it, and the
gate is raised as above instead of editing `instruction-load.json` to make the
check pass (D5). After every integration-branch
sync, the owner re-runs `tighten` and the report: S5–S8 edit the same model
and other profiles in parallel, and `strict` protection makes the later
merger rebase onto the earlier's ceilings.

### Eval plan

Pipeline cases 1–3 (`EVAL_TREE=. just evals from-issue <id>`, `EVAL_MODEL`
`sonnet` and `opus`) run against the S3 baseline rows of 2026-10-07: case 1
9/9 on both models; case 2 4/4 on Sonnet (UNEXPECTED-PASS) and 3/4 on Opus
(EXPECTED-FAIL); case 3 5/5 on both. The criterion is pass count ≥ baseline
per case and model. Case 1 and case 3 exercise the interactive route and case 2
the direct autonomous route, so both of the new route files the controller can
read are covered.

Tree mode needs `CLAUDE_CODE_OAUTH_TOKEN`; it is unset in this environment and
the temporary config dir reports no login. The run is therefore gated, not
skipped (D6): the Phase-6 owner runs the six evals only when the token is
present and commits their rows; otherwise the plan's evidence row is
`human_pending`, the sdd report carries `acceptance_state: human_pending`, and
ship-issue holds the issue open as `needs-verification` with the exact six
commands in its verdict table. No eval result is claimed, estimated or
copied from the baseline.

### Findings to file

Filed as new issues after this phase, not fixed here:

1. The acceptance criterion's `skill-lint check --max-body-lines 300` names a
   flag `skill-lint` does not have. This slice measures the 300-line target
   with `agent_tools.skill_lint.reflowed_lines` over the parsed body, the
   function the L2 check itself uses; adding the flag is a gate-file change for
   S1's owner, and S5–S7 need it too (D8).
2. The program's "hot plus conditional bytes of its profiles" target is
   unreachable by any single heavy-skill slice, because those profiles mostly
   load documents other slices own (D1).

## Decisions

- **Hub and spokes.** `SKILL.md` is the only document that names a reference
  file; route and phase files name `SKILL.md` sections by heading, never a
  sibling (L4). Payload `REVIEW-CONTRACT.md` names nothing.
- **Route selection is unchanged.** The selector keeps today's order and
  conditions exactly; each route file starts where its `###` section starts
  today. A route file owns its route's acquisition and the route-specific part
  of Phase 1; Phases 0 and 2–7 stay shared.
- **Rollover splits by reader.** The transfer gate and the earlier
  controller's stop go to the controller; the receiving checks go to the
  delegated owner. The continuation JSON lives with the sender, and the
  receiver's checks name its fields.
- **No semantic change.** Every gate, order, closed set and stop keeps its
  meaning. A sentence is cut only when a helper enforces it, another home
  holds it, or it is rationale; a sentence that would change behaviour if
  read literally is kept or reported (D7).
- **Cross-file pointers go through `SKILL.md`.** Where a reference file today
  tells its reader to read part of a sibling (the resume pack scoping `AUTO.md`
  by phase; the delegated owner deferring to the resume pack), that scoping
  moves into `SKILL.md`'s reference index, one line per file, and the
  reference file says "the sections `SKILL.md`'s index names for this phase".
- **The headings owners must always read keep their text.** `Lifecycle
  identity`, `Decision ledger (artifact discipline)`, `Skill-tool
  invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal
  return procedure`, `Suspension procedure` and the `## Phase <n>` headings stay
  in `SKILL.md` with their current text: the resume-pack rule and other skills
  name them.
- **Anchors other skills cite stay true.** They are out of scope (#291 D8), so
  the text they cite stays where they say: `SKILL.md` keeps a `### Resume
  pack` heading with a one-line pointer (orchestrate-issues cites it), the
  `**Writing workers**` rule, the suspension and terminal return procedures and
  the lifecycle-call rule (sdd, ship-issue, worktrees, HUMAN-GATE); AUTO.md keeps
  the Phase-0 fog gate (wayfind) and ends on its push/PR/merge human-gate
  paragraph, which `ship-issue/HUMAN-GATE.md` cites as "`AUTO.md`'s final
  paragraph"; `ship-handoff.md` keeps `## Remainder owner prompt` (ship-issue)
  (D9).
- **Other anchors move with their text.** A heading only tests read follows its
  section into the new file and may be renamed with its test (#291 D6).

## Test seams

- `skill-lint check` (L1–L5, debt file shrink) and the L2 function over
  `SKILL.md`'s body for the 300-line target.
- `just agent-instruction-load report`/`check`/`tighten` for membership,
  closure and ceilings; `just agent-instruction-budget --raise-label` locally
  to prove the only remaining failure is the `raise:` line.
- The existing machine-read checks: `test_dispatch_contracts`,
  `test_shell_example_contracts`, `test_agent_model_matrix`,
  `test_instruction_load`'s live-tree test, and the lifecycle JSON key-set
  tests, all inside `just agent-workflow-tests`.
- The eval harness for behaviour (above). No new test pins prose.

## Out of scope

- Other skills' documents (`ship-issue`, `sdd`, `orchestrate-issues`,
  `doc-grounded-questions`, `worktrees`, `agents/*.md`, `AGENTS.md`), even
  where they cite a from-issue anchor (#291 D8); anchors they cite are kept.
- Helper behaviour, including error text (D7), the gate's own files and the
  `--max-body-lines` flag.
- Workflow semantics: phases, gates, lanes, review axes, report shapes.
- Profile prompts, dispatch sites, `model-matrix.json`, and hosts.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The −35% target is measured as the from-issue share: the bytes of `from-issue/` members each loading profile-host lists hot or conditional, summed, base 539,997, head ≤ 350,998; the whole-profile total is reported beside it | #291 D8: one owning slice per document, so this slice can cut only its own bytes; 808,694 of 1,348,691 profile bytes belong to other slices | The literal whole-profile sum: needs a 87% cut of from-issue alone, which no semantics-preserving slim reaches |
| D2 | A new file is hot where it is its profile's standard route, conditional where it is a named branch, unread with a reason where the route cannot occur (dispatcher route hot in O and conditional in I, for a generic `delegate`; direct route and rollover only in C; interactive and durable routes conditional in C, whose entry also serves interactive invocations such as eval cases 1 and 3; delegated owner only in I); text that is merely rarely read is never moved to unread | Profile notes define each profile's route (#155 D6); the instruction-load preface defines hot and conditional | Inheriting the origin's class everywhere: keeps the dead routes loaded, which is the waste this slice removes |
| D3 | Every dispatch marker and `Agent(...)` line stays in the file `model-matrix.json` records; only surrounding prose moves | Matrix sites carry a `path`; profile `prompt`s and the payload set derive from it | Moving sites with their route text: rewrites matrix paths and prompt fields for no byte gain |
| D4 | Delete `bindings.md` and `grounding.md`; `SKILL.md` keeps one line for each | Both restate `SKILL.md`'s resolve rule and `doc-grounded-questions`' own cache rule (The Bar, DRY) | Keeping them as 800-byte files: five loads each of text with another home |
| D5 | The `instruction-budget-raise` label is unavoidable; ship stops at a human gate (`blocked_on=human_gate`) until the user applies it | The issue requires per-route files; L4a plus the closure check force listing them; `lowered_to` treats any membership or note edit as more than lowering (#291 D2) | Folding routes into existing files to avoid the label: contradicts the issue's explicit route-file requirement |
| D6 | Evals run only when `CLAUDE_CODE_OAUTH_TOKEN` is present; otherwise the evidence row is `human_pending` and ship holds the issue as `needs-verification` with the six commands | Evals README one-time login; The Bar, verify before claiming done; #291 D7 | `just switch` for deployed-mode evals: changes the live machine and is not authorized; reporting baseline rows as results: fabrication |
| D7 | No helper is edited. Where a refusal does not say what to do (the two `progress` deadline rejections, which mean "suspend, print the re-entry line, never finish"), the skill keeps a one-line mapping; rules found wrong are recorded in `### Findings to file` | #291 permits improving error text but does not require it; the deadline messages are matched by a test and by this skill, so rewording them ripples beyond the slice for no byte gain | Rewording `workflow-state.py`'s messages: same one line of skill text, plus a helper and test change |
| D8 | The 300-line target is checked with `skill_lint.reflowed_lines` over `parse_frontmatter`'s body; the missing `--max-body-lines` flag is a finding for S1's owner | `skill_lint.py` has no such option and is a gate file | Adding the flag here: a gate-file and helper change outside this slice |
| D9 | Every anchor another skill cites keeps its text and file, including a `### Resume pack` stub in `SKILL.md` and `AUTO.md` ending on the human-gate paragraph | Out-of-scope citers in orchestrate-issues, sdd, ship-issue, HUMAN-GATE, worktrees, wayfind (#291 D8) | Re-pointing the citers: edits documents other slices own |
| D10 | `SKILL.md`'s resolve paragraph stays byte for byte and keeps its shared-policy test entry; the support files' per-file "receives the retained `ResolvedProject`" sentences are cut with their table rows | The paragraph is the corpus-wide resolve contract S8 owns; the support sentences restate it in every file (DRY) | Rewording the resolve paragraph here: one skill diverging from the shared contract |
| D11 | Tests: prose assertions deleted, machine-read assertions re-pointed to the file now holding the text, heading slices follow moved headings, `LIFECYCLE_DOCS` grows to cover the new files; no replacement pins | #291 D6; `docs/standards/agent-helpers.md` rule 6 | Converting pins to "concept present" checks: #291 D6's rejected alternative |
| D12 | Every plan task keeps the gate green at its own commit: it deletes the debt keys its change clears, runs `just agent-instruction-load tighten`, sets each conditional ceiling it raises to the measure, and names every raise in its commit body; the last task only reconciles notes, re-tightens and measures | `skill_lint.lint` fails a stale debt key and `LiveBudgetTest` runs breach and 5% tightness on every commit inside `just agent-workflow-tests` | One closing task for all debt and ceiling edits: every earlier commit would fail `just agent-workflow-tests` |
| D13 | A test that pins other skills' text beside a scoped file keeps every assertion on the other skills and loses only its scoped-file prose: a scoped file leaves a multi-file corpus or an identical-copy comparison (`InterimChildResultContractsTest.OWNERS` and its siblings), and an assertion that then fails because only a scoped file held the phrase is deleted as a scoped prose pin | #291 D6 deletes prose pins on scoped files; #291 D8 leaves sdd, ship-issue and orchestrate-issues pins to their own slices | Deleting the whole test: removes pins other slices own; keeping the scoped file in it: a prose pin on a scoped file |
| D14 | `REVIEW-CONTRACT.md` loses its "receives the retained `ResolvedProject`" sentence with its table row (D10) but keeps one clause telling its reader to use only the binding values and capability states the caller supplies, never resolving or inferring policy | Its reader, the plan-reviewer profile, loads `REVIEW-CONTRACT.md` and no `SKILL.md`, so the resolve paragraph that makes the other files' sentences redundant never reaches it | Cutting the clause with the others: the reviewer would lose its only instruction not to resolve policy itself |
